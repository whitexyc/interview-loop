# 测试报告 — Module-077: 反爬绕过 + 代理池（robots.txt 遵循 / UA 轮换 / 限速重试退避 / 代理轮换）

> 测试人: Tester（module-077）
> 测试日期: 2026-08-26
> 测试对象: rag/crawl/crawler.py 反爬辅助区 + src/config.py 6 项 crawl_* 配置（工作树当前状态）
> 前置: Reviewer PASS（0 项 P1/P2，9 项 P3 建议非阻塞）｜ 基线: crawl 119（075×30 + 076×33 + 078×28 + 077×28）

## 1. 测试概览（本次实跑）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| py_compile | `python -c "import py_compile; py_compile.compile('rag/crawl/crawler.py'); py_compile.compile('src/config.py')"` | ✅ PY_COMPILE_OK（无 SyntaxError） |
| crawl 模块单测 | `.venv\Scripts\python -m pytest tests/crawl/ -v` | ✅ **119 passed, 0 failed**（32.88s，91 存量 + 28 新增，与基线逐字一致） |
| 全量回归 | `.venv\Scripts\python -m pytest tests/ -q` | ✅ **1366 passed, 3 skipped, 4 failed**（110.52s；绿数 1338→1366 = +28 精确对应 077 新增测试；4 failed 全部为 `TestChatWithTools` proxies 基线遗留，见 §1.1） |
| 全量失败归因 | 单测复跑 1 例 | ✅ `Client.__init__() got an unexpected keyword argument 'proxies'` —— langchain-openai 兼容问题，module-028 环境性基线遗留，与本模块零关联（复测确认） |
| config 验证 | `from src.config import settings; print(delay, retry, proxies)` | ✅ `1.0 3 ''`（另实测 retry_base=2.0、robots_ttl=3600、user_agents=''，与 Reviewer 声明一致） |
| anti-bot robots 分片 | `pytest tests/crawl/test_antibot.py -k "robots" -v` | ✅ **7 passed, 0 failed**（21 deselected） |
| anti-bot retry 分片 | `pytest tests/crawl/test_antibot.py -k "retry" -v` | ✅ **9 passed, 0 failed**（19 deselected） |
| anti-bot proxy 分片 | `pytest tests/crawl/test_antibot.py -k "proxy" -v` | ✅ **6 passed, 0 failed**（22 deselected） |
| anti-bot 全文件（关键类） | `pytest tests/crawl/test_antibot.py -v` | ✅ **28 passed, 0 failed**（exit 0；TestRobotsAllowed 7 + TestUARotation 4 + TestRetryAndBackoff 8 + TestProxyRotation 6 + TestRateLimitDelay 2 + TestAntibotConfig 1） |
| 新增生产代码行数（AC-4.2.1，独立复算） | AST 语句口径 + 物理行 | ✅ 8 个新函数体合计 33 语句 + 常量区 + fetch_page 增量 + config 6 字段 ≈ 140 物理行 < 200 上限（与 Reviewer ≈140 一致） |
| 方法体 ≤ 50 行 | AST 审计（Reviewer 实跑） | ✅ 最大 `_crawl_page_and_store` 44 行 / `fetch_page` 38 / `run_crawl` 33 / `_check_robots_allowed` 26 |

### 1.1 全量回归 4 个失败归因（module-028 基线遗留，非本模块）

- 失败用例：`tests/agent/test_agent_tools.py::TestChatWithTools` 下 4 项（`test_openai_path_returns_content_and_tool_calls` / `test_openai_path_preserves_reasoning_content` / `test_no_tool_calls_returns_empty_list` / `test_llm_failure_raises_llm_exception`）
- 错误信息（实跑复测确认）：`pydantic.v1.error_wrappers.ValidationError: Client.__init__() got an unexpected keyword argument 'proxies'`
- 归因：langchain-openai 版本与 `proxies` 参数不兼容，module-028 引入的环境性基线问题；module-078 Tester 报告同口径（1338 passed / 4 proxies 基线失败）。本次绿数 1366 = 1338 + 28（077 新增），**无任何新失败、无本模块引入的回归**。

## 2. 验收标准逐项核对

### §1 功能验收（20/20 全部 ✅）

| 验收项 | 验证方式 | 状态 |
|--------|----------|------|
| AC-1.1.1 robots 允许 → 正常抓取 | 单测 `test_robots_allow`（mock Allow: / → `_check_robots_allowed` True）实跑 PASSED | ✅ |
| AC-1.1.2 robots 禁止 → 跳过且不调 fetch_page | 单测 `test_robots_disallow` PASSED + 代码审读（`_crawl_page_and_store` 前置 `if not await _check_robots_allowed(url)` → `summary.skipped += 1` 提前 return，fetch_page 不可达） | ✅ |
| AC-1.1.3 同域名二次请求命中缓存 | 单测 `test_robots_cache_hit`（httpx.get call_count==1）PASSED + 代码审读（`_robots_cache[host] = (expire_ts, rp)` 按域名缓存） | ✅ |
| AC-1.1.4 robots 拉取失败 fail-open | 单测 `test_robots_fail_open`（ConnectError → True 抓取继续）PASSED + 代码审读（`except Exception: return True`，含 fail-open 注释） | ✅ |
| AC-1.1.5 robots 检查固定 UA `PersonalKB-Crawler` | 单测 `test_robots_uses_fixed_ua` PASSED + 代码审读（`_ROBOTS_UA = "PersonalKB-Crawler"`，`rp.can_fetch(_ROBOTS_UA, url)`） | ✅ |
| AC-1.2.1 `_UA_POOL` ≥ 8 个 UA | 单测 `test_ua_pool_size` PASSED + 代码审读（`_BUILTIN_UA_POOL` 10 条桌面+移动浏览器 UA） | ✅ |
| AC-1.2.2 `_random_headers()` 四键 | 单测 `test_random_headers_keys` PASSED + 代码审读（User-Agent/Accept/Accept-Language/Accept-Encoding） | ✅ |
| AC-1.2.3 连续 10 次 ≥ 2 种 UA | 单测 `test_ua_randomness` PASSED | ✅ |
| AC-1.2.4 fetch_page 使用随机 headers | 单测 `test_fetch_uses_random_headers` PASSED + 代码审读（`kw["headers"] = _random_headers()`，非硬编码） | ✅ |
| AC-1.3.1 429 → 重试成功 | 单测 `test_429_triggers_retry_then_success`（429→200）PASSED | ✅ |
| AC-1.3.2 500 → 重试成功 | 单测 `test_500_triggers_retry_then_success`（500→200）PASSED | ✅ |
| AC-1.3.3 指数退避（≥1s / ≥2s） | 单测 `test_exponential_backoff_delays`（mock sleep ≥1.0 / ≥2.0）PASSED + 代码审读（`delay = base_delay * (2 ** attempt)` + `random.uniform(0, delay*0.5)` jitter） | ✅ |
| AC-1.3.4 超 `crawl_max_retries` 返回失败 | 单测 `test_max_retries_exceeded_returns_failure`（retry_max=3 连续 429 → success=False）PASSED | ✅ |
| AC-1.3.5 超时直接重试无额外延迟 | 单测 `test_timeout_retries_no_extra_delay`（sleep 未被调用）PASSED + 代码审读（`except httpx.TimeoutException: if attempt < max_retries: continue` 无 sleep） | ✅ |
| AC-1.3.6 非 429/5xx/超时（403）不重试 | 单测 `test_non_retryable_error_no_retry`（call==1）PASSED + 代码审读（`HTTPStatusError` 直返失败） | ✅ |
| AC-1.3.7 同源请求间隔 ≥ `crawl_request_delay_s` | 单测 `test_delay_injected_between_requests`（sleep 1.0s）PASSED + 代码审读（`_rate_limit_delay` monotonic 判定） | ✅ |
| AC-1.4.1 空代理列表 → 直连 | 单测 `test_empty_proxy_list_returns_none` + `test_no_proxy_when_empty`（无 proxy kwarg）PASSED + 代码审读（`if proxy: kw["proxy"] = proxy` 才传） | ✅ |
| AC-1.4.2 2 代理 round-robin 轮换 | 单测 `test_round_robin_rotation`（A→B→A）PASSED + 代码审读（`_proxy_index % len(_proxy_pool)`） | ✅ |
| AC-1.4.3 重试切换到下一代理 | 单测 `test_proxy_switch_on_retry`（A 500→B 200）PASSED + 代码审读（每次 attempt 调 `_next_proxy()`） | ✅ |
| AC-1.4.4 全部代理失败返回失败 | 单测 `test_all_proxies_fail_returns_failure` PASSED + 代码审读（重试耗尽 → `CrawlResult(success=False)`） | ✅ |

### §2 边界条件验收（5/5 全部 ✅）

| 验收项 | 验证方式 | 状态 |
|--------|----------|------|
| AC-2.1 robots.txt 空白内容 → 允许 | 单测 `test_robots_empty_content_fail_open` PASSED | ✅ |
| AC-2.2 `*` 通配符规则正确匹配 | 单测 `test_robots_wildcard_rules` PASSED（`User-agent: *` + `Disallow: /admin/`） | ✅ |
| AC-2.3 `crawl_max_retries=0` 不重试 | 单测 `test_max_retries_zero_no_retry`（call==1）PASSED + 代码审读（`range(max_retries + 1)` 单次） | ✅ |
| AC-2.4 `crawl_request_delay_s=0` 不限速 | 单测 `test_no_delay_when_config_zero`（sleep 未调用）PASSED + 代码审读（`if delay <= 0: return`） | ✅ |
| AC-2.5 代理列表含空格/换行正确解析 | 单测 `test_proxy_with_spaces_parsed` PASSED + 代码审读（`_load_proxies` strip + 空项过滤） | ✅ |

### §3 异常场景验收（4/4 全部 ✅，含 2 项行为审读确认）

| 验收项 | 验证方式 | 状态 |
|--------|----------|------|
| AC-3.1 robots 拉取超时（5s）→ fail-open | 代码审读（`httpx.AsyncClient(timeout=5, ...)` 内 TimeoutException 落入 `except Exception: return True`）+ `test_robots_fail_open` 已覆盖同一 except 路径（ConnectError 与 Timeout 同为 httpx 异常走同一分支） | ✅ |
| AC-3.2 robots 返回非文本/HTML 404 → parse 不崩溃 fail-open | 代码审读：404 → `resp.raise_for_status()` 抛 HTTPStatusError → except → True；200+HTML → `rp.parse(resp.text.splitlines())` 标准库对任意行不崩溃。行为正确；**无专测**（Reviewer P3 #8 覆盖缺口，同属 except 兜底路径，已由 fail-open 测试部分覆盖） | ✅ |
| AC-3.3 代理连接拒绝 → 切换下一代理 | 代码审读：`except Exception` → `continue` → 下一 attempt 重调 `_next_proxy()` 切换；`test_proxy_switch_on_retry` 以 500 覆盖同一「失败→切代理」路径（ConnectError 走同一 except Exception 分支）。行为正确；**无 ConnectError 专测**（Reviewer P3 #8） | ✅ |
| AC-3.4 重试用尽 error 含最后异常摘要（截断 200） | 单测 `test_error_message_truncated`（len ≤ 200）PASSED + 代码审读（`str(e)[:200]`） | ✅ |

### §4 非功能验收（11/11 全部 ✅）

| 验收项 | 验证方式 | 状态 |
|--------|----------|------|
| AC-4.1.1 robots 缓存命中无 HTTP 请求 | 单测 `test_robots_cache_hit`（call_count==1）PASSED | ✅ |
| AC-4.1.2 `_random_headers()` < 1ms | 代码审读：纯内存 dict 构造 + `random.choice`，无 I/O，量级微秒级。行为正确；**无计时专测**（Reviewer P3 #8） | ✅ |
| AC-4.2.1 新增生产代码 ≤ 200 行 | Reviewer AST ≈140 行 + Tester 独立复算（8 新函数 33 语句 + 常量区 + fetch 增量 + config 6 字段 ≈ 140 物理行）< 200 | ✅ |
| AC-4.2.2 新增公开函数有 docstring | 代码审读：`_ua_pool`/`_check_robots_allowed`/`_make_robot_parser`/`_pick_ua`/`_random_headers`/`_load_proxies`/`_next_proxy`/`_rate_limit_delay` 全部有 docstring | ✅ |
| AC-4.2.3 无空 catch / 吞异常 | 代码审读：`_check_robots_allowed` except 带 fail-open 注释（I/O 容错豁免，铁律 5）；fetch_page 各 except 均产出错误信息（`HTTP {code}` / `抓取超时` / `str(e)[:200]`）；无裸 except | ✅ |
| AC-4.2.4 无新外部依赖 | 代码审读：仅标准库 `urllib.robotparser`（`_make_robot_parser` 延迟导入）+ 已有 httpx/random/asyncio/time | ✅ |
| AC-4.2.5 conftest autouse fixture 钉住测试环境 | 代码审读：tests/conftest.py `default_antibot_mocks`（autouse）钉住 `crawl_retry_max=0` / `crawl_proxies=""` / `crawl_robots_cache_ttl=0` / `crawl_user_agents=""` / `crawl_request_delay_seconds=0` / `_check_robots_allowed`=AsyncMock(True) | ✅ |
| AC-4.3.1 `fetch_page(url)` 签名不变 | 代码审读：`async def fetch_page(url: str) -> CrawlResult`（与 module-076 逐字一致） | ✅ |
| AC-4.3.2 `run_crawl(sources, max_pages)` 签名不变 | 代码审读：`async def run_crawl(sources: list[dict], *, max_pages: int = 0) -> CrawlSummary` | ✅ |
| AC-4.3.3 CrawlResult / CrawlSummary 字段不变 | 代码审读：`CrawlResult(url/success/content/title/error/review_status)`、`CrawlSummary(crawled/approved/rejected/conflict_count/skipped/errors/details)` 字段零改动（review_status 为 075 引入、conflict_count 为 078 引入，本模块未触碰） | ✅ |
| AC-4.3.4 无代理配置行为与 module-076 完全一致 | 全量回归中存量 91 项 crawl 测试全绿 + `test_no_proxy_when_empty`（proxy=None 不传参）+ 签名/数据类零改动 | ✅ |

## 3. 可运行验证命令（全部实测）

| 验收项 | 预期输出 | 实测 |
|--------|----------|------|
| 单元测试 `-k` 分片（robots/retry/proxy） | All tests passed | ✅ 7 / 9 / 6 全绿 |
| anti-bot 全文件 | 28 passed | ✅ **28 passed, 0 failed** |
| crawl 全量 | 119 passed（基线） | ✅ **119 passed, 0 failed**（32.88s） |
| 全量回归 | 基线不降，4 环境性遗留 | ✅ **1366 passed / 3 skipped / 4 failed**（全为 module-028 proxies 基线，实测归因确认） |
| py_compile | 无 SyntaxError | ✅ crawler.py + config.py 双文件通过 |
| config 验证 | `1.0 3 ""` | ✅ delay=1.0, retry=3, proxies=''（字段名以实际为准：`crawl_request_delay_seconds`/`crawl_retry_max`/`crawl_proxies`，验收文档中 `crawl_request_delay_s` 等旧名属文档漂移，值一致，见遗留建议 6） |

## 4. Reviewer 9 项 P3 复核（全部存在、均非阻塞）

| # | 位置 | 内容 | Tester 复核 |
|---|------|------|-------------|
| 1 | config.py:374 ↔ crawler.py:227 | `crawl_robots_cache_ttl` 注释「0 = 不缓存」与实现 `if ttl <= 0 or now < expire_ts`（ttl≤0 永不过期）语义相反 | ✅ 存在（conftest 钉住 ttl=0 且 AsyncMock `_check_robots_allowed`，测试无影响；生产默认 3600 正常；纯文档误导，P3） |
| 2 | config.py:373 | 注释声称代理「全部失败 → fail-open 直连」，实现为重试耗尽直接 `success=False`，无直连回退 | ✅ 存在（plan §3.4 未承诺直连回退，注释失真非功能缺陷，P3） |
| 3 | config.py:378 | `crawl_retry_base_seconds` 默认 2.0 vs plan §3.6 表约定 1.0 | ✅ 存在（实测 2.0；代码内部自洽，测试显式设置，P3） |
| 4 | crawler.py:535 | 限速为全局计数器 `_rate_limit_delay(0)` 恒用 source_id=0，与 plan per-source 设计不符（方向安全，更保守） | ✅ 存在（`_crawl_page_and_store` 内 `await _rate_limit_delay(0)` 注释自认；多源场景第二源首请求被前源最后请求限速，不违反最小间隔，P3） |
| 5 | crawler.py:232 | robots.txt 拉取未传 UA 头（httpx 默认 python-httpx/...）+ `timeout=5` 内联魔法数字未命名常量 | ✅ 存在（严格站点 403 → 拉取失败 → fail-open 合规性静默降级，属设计内；P3） |
| 6 | crawler.py:235 | 解析器构造 `type(_robots_cache.get(host, (0, None))[1] or _make_robot_parser())()` 恒等于 `RobotFileParser()`，过度复杂 | ✅ 存在（功能正确，P3 风格） |
| 7 | crawler.py:521 | `return CrawlResult(..., error=last_error or "重试用尽")` 为不可达死代码（for 内四分支全覆盖 return） | ✅ 存在（保留作防御无功能影响，P3） |
| 8 | tests/crawl/test_antibot.py | 覆盖缺口：AC-3.2（robots HTML 404 无专测）、AC-3.3（无 ConnectError 专测，仅 500 模拟）、AC-4.1.2（`_random_headers` 无计时专测） | ✅ 存在（三处行为均经审读确认正确，走通用 except/纯内存路径，覆盖缺口非功能缺陷，P3） |
| 9 | changelog.md 决策 3 | jitter 描述「±20%」与实现 `random.uniform(0, delay*0.5)`（+0~50%）不符；`_check_robots_allowed` except 无日志 | ✅ 存在（plan 原文与实现一致，changelog 描述偏差；except 带 fail-open 注释豁免铁律 5 但排障无痕，P3） |

## 5. 验收结论

**验收通过 40/40**

- 功能验收 20/20 ✅（robots.txt 遵循 / UA 轮换 / 限速重试退避 / 代理轮换全部满足）
- 边界条件 5/5 ✅（空白 robots / 通配符 / retry=0 / delay=0 / 代理列表空格解析）
- 异常场景 4/4 ✅（robots 超时与 404 fail-open / 代理切换 / 异常摘要截断；其中 AC-3.2、AC-3.3 为行为审读确认 + 通用 except 路径测试覆盖，专测缺口属 Reviewer P3 #8 非阻塞）
- 非功能 11/11 ✅（代码 ≤200 行 / docstring / 无空 catch / 零新依赖 / conftest 钉住 / 签名与数据类零改动 / 无代理零回归）
- 全量回归 1366 passed / 4 failed（4 个全部为 module-028 langchain-openai `proxies` 环境性基线遗留，实跑归因确认与本模块零关联；绿数 1338→1366 = +28 精确对应 077 新增测试）
- 关键测试：anti-bot 测试类 **28/28 全绿**（robots 7 / retry 9 / proxy 6 分片 + 全文件，exit 0）
- Reviewer 9 项 P3 逐一复核：全部存在、全部非阻塞（5 项文档/语义、3 项测试覆盖缺口、2 项风格/死代码）

**不通过理由不存在。**

## 6. 遗留建议（非阻塞）

1. Reviewer P3 #1：修正 `crawl_robots_cache_ttl` 注释语义（0 = 不限时 / 进程生命周期内有效），或改实现为真「不缓存」
2. Reviewer P3 #2：删除 config.py:373 注释中「全部失败 → fail-open 直连」表述；若确需直连兜底，补 `except` 分支无代理重试 + 测试
3. Reviewer P3 #3：统一 retry_base 口径（改 plan 表 2.0 或改默认 1.0，推荐改 plan，代码 2.0 更稳健）
4. Reviewer P3 #5：robots 拉取显式传 `headers={"User-Agent": _ROBOTS_UA}` + 提取 `_ROBOTS_TIMEOUT_S = 5` 常量
5. Reviewer P3 #8：补 3 个专测（robots 404 响应 fail-open / `httpx.ConnectError` 代理切换 / `_random_headers` 计时断言）
6. Reviewer P3 #9：changelog jitter 描述改「+0~50%」；`_check_robots_allowed` except 内补 `logger.debug` 便于排障
7. 验收标准 §5 文档字段名漂移：`crawl_request_delay_s`/`crawl_max_retries`/`crawl_proxy_list` 应更正为实际字段 `crawl_request_delay_seconds`/`crawl_retry_max`/`crawl_proxies`（值与预期一致，纯文档）
8. 既有 backlog（非本模块）：`document_dedup.py:157` numpy ndarray 真值判定缺陷；本机 hhem-2.1-open 权重缺失 score 恒 NULL

## 7. 签署

- 测试人: Tester（module-077）
- 验收时间: 2026-08-26
- 结论: **✅ 验收通过 40/40**
