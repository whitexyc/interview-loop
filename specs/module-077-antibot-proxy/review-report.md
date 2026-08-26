# 审查报告 — Module-077: 反爬绕过 + 代理池

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-26
- 审查人: Reviewer（独立复审）
- 审查耗时: ~25 分钟
- 测试基线: pytest tests/crawl 119/0 passed（91 存量 + 28 新增），py_compile 双文件 OK

**验证命令实跑结果：**

| 命令 | 结果 |
|------|------|
| `pytest tests/crawl/test_antibot.py -q` | **28 passed**，31.22s |
| `pytest tests/crawl -q` | **119 passed**（91 存量 + 28 新增），33.35s |
| `py_compile.compile('rag/crawl/crawler.py')` + `('src/config.py')` | OK（无 SyntaxError） |
| config 默认值实测 | `crawl_request_delay_seconds=1.0, crawl_retry_max=3, crawl_retry_base_seconds=2.0, crawl_proxies='', crawl_robots_cache_ttl=3600, crawl_user_agents=''` |
| 方法长度审计 | 全部 ≤50 行（最大 `_crawl_page_and_store` 44 行） |
| 新增生产代码行数 | ≈140 行（< 200 上限） |

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `config.py` L374 ↔ `crawler.py` L224-225 | config:374; crawler:224 | **`crawl_robots_cache_ttl=0` 语义反转**：config 注释写"0 = 不缓存"，但代码 `ttl <= 0` 时短路返回缓存命中值 → ttl=0 意味着"永久缓存（不刷新）"而非"不缓存"。Plan §3.1 原设计"不做 TTL 刷新"，TTL 是实现时额外引入的。默认 3600 不触发此边界。 | P3 | 二选一：① 修正注释为"0 = 不限时（进程生命周期内有效）"（与 plan 一致）；② 改代码使 ttl=0 时每次重新拉取。推荐①（与 plan 哲学一致）。 |
| 2 | `config.py` L373 | config:373 | **直连回退注释失真**：config 注释写"全部失败 → fail-open 直连"，但 `fetch_page` 实现为全部代理轮换重试耗尽后直接返回 `CrawlResult(success=False)`，**无直连回退**。Plan §3.4 未承诺直连回退。 | P3 | 删除注释中"全部失败 → fail-open 直连"表述。 |
| 3 | `config.py` L378 | config:378 | **`crawl_retry_base_seconds` 默认值 2.0 vs plan §3.6 表声明 1.0**。代码内部自洽（config 注释、测试均显式设置），无功能影响。 | P3 | 统一口径：改 plan 表为 2.0 或改默认值为 1.0。当前 2.0 更保守安全。 |
| 4 | `crawler.py` L460 | crawler:460 | **限速 source_id 硬编码为 0（全局而非 per-source）**：`_crawl_page_and_store` 调用 `await _rate_limit_delay(0)`，plan §3.3 设计 per-source 语义，实际全部 URL 共享同一计数器。当前单源串行场景无功能影响。 | P3 | 注释更正为"全局限速"；或传入真实 source_id 为未来并发预留。 |
| 5 | `crawler.py` L230 | crawler:230 | **robots.txt 拉取无 User-Agent 头**：`httpx.AsyncClient(timeout=5)` 不传 headers → 默认 UA 为 `python-httpx/...`。部分站点拒绝非浏览器 UA 返回 403 → fail-open 放行（合规性静降级，设计内）。`timeout=5` 为内联魔法数字（铁律 4）。 | P3 | 传 `headers={"User-Agent": _ROBOTS_UA}` + 提取 `_ROBOTS_TIMEOUT_S = 5` 常量。 |
| 6 | `crawler.py` L235 | crawler:235 | **`type(...)()` 构造链过度复杂**：`rp = type(_robots_cache.get(host, (0, None))[1] or _make_robot_parser())()` 恒等于 `_make_robot_parser()`，可读性差。 | P3 | 直接 `rp = _make_robot_parser()`（标准库 import 有缓存，成本可忽略）。 |
| 7 | `crawler.py` L521 | crawler:521 | **`return CrawlResult(..., error=last_error or "重试用尽")` 为不可达死代码**：for 循环内所有路径均已 return（429/5xx、Timeout、HTTPStatusError、Exception 四分支全覆盖）。 | P3 | 可删除或保留作防御性代码。若保留建议加注释。 |
| 8 | `test_antibot.py` | — | **缺少 AC-3.2/3.3/4.1.2 独立测试**：AC-3.2（robots 非文本 HTML 404 → fail-open）无专测；AC-3.3（代理 ConnectError → 切下一代理）仅以 500 模拟；AC-4.1.2（`_random_headers` < 1ms）无专测。代码行为经审读确认正确（均走通用 except 兜底）。 | P3 | 补 2-3 个 mock 用例：robots 404 HTML 响应、ConnectError 代理失败、`_random_headers` 计时。 |
| 9 | `changelog.md` 设计决策 3 | changelog | **jitter "±20%" 描述与实现不符**：代码 `random.uniform(0, delay * 0.5)` 是 [0, +50%] 单向正偏移（无负 jitter），非 "±20%"。另外 `_check_robots_allowed` 的 except（L250）无日志（fail-open 注释满足铁律 5 豁免但排障无痕）。 | P3 | ① changelog 改为"+0~50% jitter"；② except 内加 `logger.debug("robots.txt 拉取失败，fail-open: %s", e)`。 |

## 3. 验收标准核对

| AC 编号 | 验收项 | 对应代码/测试 | 状态 | 备注 |
|---------|--------|--------------|------|------|
| AC-1.1.1 | robots 允许 → 正常抓取 | `_check_robots_allowed` L228 + test_robots_allow | ✅ | |
| AC-1.1.2 | robots 禁止 → 跳过 | `_crawl_page_and_store` L457 前置判断 + test_robots_disallow | ✅ | |
| AC-1.1.3 | 同域名缓存命中 | `_robots_cache` dict + TTL + test_robots_cache_hit（call_count==1） | ✅ | |
| AC-1.1.4 | robots 拉取失败 → fail-open | except L250 → True + test_robots_fail_open（ConnectError） | ✅ | |
| AC-1.1.5 | robots 用固定 UA | `_ROBOTS_UA` L32 + can_fetch L228/239 + test_robots_uses_fixed_ua | ✅ | |
| AC-1.2.1 | UA 池 ≥8 | `_BUILTIN_UA_POOL` 10 条 + test_ua_pool_size | ✅ | |
| AC-1.2.2 | headers 四键 | `_random_headers` L237-244 + test_random_headers_keys | ✅ | |
| AC-1.2.3 | UA 随机性 | `_pick_ua` random.choice + test_ua_randomness（10 次 ≥2 种） | ✅ | |
| AC-1.2.4 | fetch 用随机 headers | `fetch_page` L492 headers kwarg + test_fetch_uses_random_headers | ✅ | |
| AC-1.3.1 | 429 触发重试 | fetch_page L499 status check + test_429_triggers_retry_then_success | ✅ | |
| AC-1.3.2 | 500 触发重试 | fetch_page L499 `>= 500` + test_500_triggers_retry_then_success | ✅ | |
| AC-1.3.3 | 指数退避间隔 | L502 `base * 2^attempt` + jitter + test_exponential_backoff_delays | ✅ | |
| AC-1.3.4 | 超过重试返回失败 | L506 return + test_max_retries_exceeded_returns_failure | ✅ | |
| AC-1.3.5 | 超时无额外延迟 | L512 `continue` 无 sleep + test_timeout_retries_no_extra_delay | ✅ | |
| AC-1.3.6 | 非 429/5xx 不重试 | L515 HTTPStatusError 直返 + test_non_retryable_error_no_retry（call==1） | ✅ | |
| AC-1.3.7 | 同源限速间隔 | `_rate_limit_delay` L289 + test_delay_injected_between_requests | ✅ | source_id=0 全局，见建议 #4 |
| AC-1.4.1 | 空代理 → 直连 | `_next_proxy` L279 None + test_empty_proxy_list_returns_none + test_no_proxy_when_empty | ✅ | |
| AC-1.4.2 | round-robin 轮换 | `_next_proxy` L283 `% len` + test_round_robin_rotation（A→B→A） | ✅ | |
| AC-1.4.3 | 重试切换代理 | fetch_page L495 `_next_proxy` 每次 + test_proxy_switch_on_retry | ✅ | |
| AC-1.4.4 | 全部代理失败 | 重试耗尽 + test_all_proxies_fail_returns_failure | ✅ | |
| AC-2.1 | robots 空内容 → 允许 | rp.parse([]) 默认全允许 + test_robots_empty_content_fail_open | ✅ | |
| AC-2.2 | robots * 通配符 | RobotFileParser 标准库行为 + test_robots_wildcard_rules | ✅ | |
| AC-2.3 | retry_max=0 不重试 | `range(0+1)` = 1 次 + test_max_retries_zero_no_retry（call==1） | ✅ | |
| AC-2.4 | delay=0 不限速 | L292 `delay <= 0: return` + test_no_delay_when_config_zero | ✅ | |
| AC-2.5 | 代理含空格解析 | `_load_proxies` strip + test_proxy_with_spaces_parsed | ✅ | |
| AC-3.1 | robots 超时 → fail-open | except 统一 + test_robots_fail_open（ConnectError） | ✅ | |
| AC-3.2 | robots 非文本 → fail-open | except 统一（RobotFileParser.parse 不崩） | ⚠️ | 无独立测试，行为正确（见建议 #8） |
| AC-3.3 | 代理连接拒绝 → 切换 | except → continue → `_next_proxy()` | ⚠️ | 无独立"ConnectError"专测（见建议 #8） |
| AC-3.4 | error 截断 200 | L518 `str(e)[:200]` + test_error_message_truncated | ✅ | |
| AC-4.1.1 | robots 缓存无重复请求 | test_robots_cache_hit call_count==1 | ✅ | |
| AC-4.1.2 | _random_headers < 1ms | 纯内存操作 | ⚠️ | 无专测（见建议 #8） |
| AC-4.2.1 | 生产代码 ≤200 行 | ≈140 行 | ✅ | |
| AC-4.2.2 | 公开函数有 docstring | 全部新函数有 docstring | ✅ | |
| AC-4.2.3 | 无空 catch | 所有 except 有 fail-open 语义或 error 信息 | ✅ | |
| AC-4.2.4 | 无新外部依赖 | 仅标准库 urllib.robotparser + 已有 httpx | ✅ | |
| AC-4.2.5 | conftest autouse 钉住 | `default_antibot_mocks` 钉住 6 项安全值 | ✅ | |
| AC-4.3.1 | fetch_page 签名不变 | `async def fetch_page(url: str) -> CrawlResult` 逐字一致 | ✅ | |
| AC-4.3.2 | run_crawl 签名不变 | `async def run_crawl(sources, *, max_pages=0) -> CrawlSummary` 逐字一致 | ✅ | |
| AC-4.3.3 | 数据类字段不变 | CrawlResult/CrawlSummary 字段零改动 | ✅ | |
| AC-4.3.4 | 无代理时行为一致 | conftest 钉住 + 存量 91 测试全绿 | ✅ | |

**统计**: 37 项 AC，34 项 ✅ 通过，3 项 ⚠️ 无独立测试但行为正确。

## 4. 架构评估

- **分层正确性**: ✅ crawler.py 为 RAG 抓取层，反爬功能均在同层实现，不跨层调用。
- **依赖方向**: ✅ crawler.py → config.py + httpx + 标准库，无反向依赖。
- **DTO 约束**: ✅ 不涉及。
- **新增依赖**: ✅ 无新外部依赖（仅标准库 urllib.robotparser，延迟导入）。
- **向后兼容**: ✅ fetch_page/run_crawl 签名不变，无代理/无重试时行为与 module-076 逐字一致。

## 5. 安全评估

- **SQL 注入防护**: N/A（无 SQL 操作）
- **XSS 防护**: N/A
- **API Key 安全**: ✅ 代理/UA 配置来自 settings（环境变量），非用户输入
- **敏感信息日志处理**: ✅ 无密码/key 泄露
- **注入面**: ✅ 代理列表从 config 读取，不接受运行时注入
- **robots.txt 拉取超时**: ✅ 设置 5s 超时（L230），不会无限挂起

## 6. 铁律合规检查

| 铁律 | 结果 | 证据 |
|------|------|------|
| 1 plan+acceptance 先行 | ✅ | plan.md + acceptance-criteria.md 齐全 |
| 2 生产代码 ≤200 行 | ✅ ≈140 行 | changelog 行数口径说明（077+078 合并提交伪影，各自 ≤200） |
| 3 方法 ≤50 行 | ✅ 最大 44 行 | `_crawl_page_and_store` 44 / `fetch_page` 38 |
| 4 docstring + 常量命名 | ✅ | 全部新方法有 docstring；`_FETCH_TIMEOUT_S`/`_ROBOTS_UA` 已命名；`timeout=5` 内联见建议 #5 |
| 5 无空 catch | ✅ | `_check_robots_allowed` except → True（fail-open 豁免）；fetch_page 各 except 产出 error |
| 6 无跨层依赖 | ✅ | 仅依赖 config + 标准库 + httpx |
| 7 API 统一格式 | N/A | 无新增端点 |
| 8 INFO 日志 + 禁敏感信息 | ✅ | robots 跳过/抓取失败/批次完成有日志；无密钥 |
| 9 禁 SQL 拼接/硬编码密钥 | ✅ | 无 SQL、无密钥 |
| 10 架构变更走 ADR | ✅ | 延续 ADR-0019 阶段2 |
| 11 记忆三件套 | ✅ | 入场已读；本报告完成后写记忆行 |
| 12 自跑 lint+测试 | ✅ | tests/crawl 119/0 + py_compile OK |

## 7. 审查总结

**总体评价**: module-077 实现完整、自洽且质量良好。四个子任务（robots.txt 遵循 / UA 轮换 / 限速重试退避 / 代理轮换）全部按 plan 落地，零新依赖，fail-open 哲学贯穿始终，向后兼容由存量 91 项测试全绿 + 签名/数据类零改动双重保证。测试 28 项全部通过且与 AC 逐项映射。

**问题定性**: 9 项问题全部为 P3 级——5 项文档/语义不一致（ttl=0 语义反转、直连回退注释失真、retry_base 2.0 vs plan 1.0、per-source 变全局 0、jitter 描述）、3 项测试覆盖缺口（AC-3.2/3.3/4.1.2）、2 项代码风格（过度复杂构造、死代码）。**无功能缺陷、无安全/合规阻断项。**

**推荐处置**: 建议 Tester 阶段前顺手修正建议 #1（ttl 注释）、#2（直连注释）、#5①（robots 拉取补 UA 头）——均为一行改动；建议 #8 的 3 个测试缺口建议 Tester 回归时补入；其余记录 backlog。

**本审查判定：通过，放行进入 Tester 阶段。**
