# 验收标准 — Module-077: 反爬绕过 + 代理池

## 1. 功能验收

### 1.1 robots.txt 遵循
- [ ] AC-1.1.1: robots.txt 允许的 URL 正常抓取（mock robots.txt 返回 `Allow: /`，`_check_robots` 返回 True）
- [ ] AC-1.1.2: robots.txt 禁止的 URL 跳过抓取（mock robots.txt 返回 `Disallow: /private/`，匹配 URL 返回 False，`_crawl_page_and_store` 不调用 `fetch_page`）
- [ ] AC-1.1.3: 同域名第二次请求命中缓存（mock httpx.get 仅调用 1 次 robots.txt 拉取，第二次 `_check_robots` 不发 HTTP 请求）
- [ ] AC-1.1.4: robots.txt 拉取失败（404/超时）时 fail-open 允许抓取（mock httpx.get 抛异常，`_check_robots` 返回 True，抓取继续）
- [ ] AC-1.1.5: robots.txt 使用固定 UA `"PersonalKB-Crawler"` 而非随机 UA（检查 `_check_robots` 内 httpx 请求头）

### 1.2 UA 轮换 + 请求头增强
- [ ] AC-1.2.1: `_UA_POOL` 包含 ≥8 个不同 UA 字符串（断言长度）
- [ ] AC-1.2.2: `_random_headers()` 返回 dict 包含 `User-Agent`/`Accept`/`Accept-Language`/`Accept-Encoding` 四个键（断言键集）
- [ ] AC-1.2.3: 连续 10 次调用 `_random_headers()` 产生 ≥2 种不同 UA（随机性验证）
- [ ] AC-1.2.4: `fetch_page` 内 httpx.AsyncClient 使用 `_random_headers()` 返回的 headers（mock 验证 headers 参数非硬编码）

### 1.3 限速与重试退避
- [ ] AC-1.3.1: 429 响应触发重试（mock httpx 返回 429 → 200，验证 `fetch_page` 最终返回 success=True）
- [ ] AC-1.3.2: 500 响应触发重试（mock httpx 返回 500 → 200，验证重试成功）
- [ ] AC-1.3.3: 429 重试间隔符合指数退避（mock asyncio.sleep，验证第 1 次 delay ≥ 1s，第 2 次 delay ≥ 2s）
- [ ] AC-1.3.4: 超过 `crawl_max_retries` 次重试后返回失败（mock 连续 429，`crawl_max_retries=3`，验证最终返回 CrawlResult(success=False)）
- [ ] AC-1.3.5: 超时直接重试无额外延迟（mock httpx.TimeoutException，验证 asyncio.sleep 未被调用）
- [ ] AC-1.3.6: 非 429/5xx/超时异常不重试（mock httpx.HTTPStatusError 403，验证仅调用 1 次 httpx.get）
- [ ] AC-1.3.7: 同源请求间隔 ≥ `crawl_request_delay_s`（mock time.monotonic，验证 `_recursive_crawl` 内 sleep 调用）

### 1.4 代理配置化轮换 + 失败切换
- [ ] AC-1.4.1: `crawl_proxy_list` 为空时不使用代理（`_next_proxy()` 返回 None，httpx.AsyncClient 不传 proxy）
- [ ] AC-1.4.2: 配置 2 个代理时 round-robin 轮换（第 1 次请求用代理 A，第 2 次用代理 B，第 3 次回到 A）
- [ ] AC-1.4.3: 重试时切换到下一个代理（mock 第 1 次请求用代理 A 失败，重试用代理 B 成功）
- [ ] AC-1.4.4: 全部代理失败后返回失败（mock 所有代理超时，验证最终 CrawlResult(success=False)）

## 2. 边界条件验收

- [ ] AC-2.1: robots.txt 为空白内容（无规则）→ 允许抓取
- [ ] AC-2.2: robots.txt 包含 `*` 通配符规则（`User-agent: *` + `Disallow: /admin/`）→ 正确匹配
- [ ] AC-2.3: `crawl_max_retries=0` 时不重试（mock 429，验证仅 1 次请求）
- [ ] AC-2.4: `crawl_request_delay_s=0` 时不限速（mock asyncio.sleep 未被调用）
- [ ] AC-2.5: `crawl_proxy_list` 含空格/换行时正确解析（`" http://a:8080 , http://b:8080 "` → 2 个代理）

## 3. 异常场景验收

- [ ] AC-3.1: robots.txt 拉取超时（5s）→ fail-open 允许抓取
- [ ] AC-3.2: robots.txt 返回非文本内容（HTML 404 页面）→ `RobotFileParser.parse` 不崩溃，fail-open
- [ ] AC-3.3: 代理连接拒绝 → 重试切换下一个代理
- [ ] AC-3.4: 所有重试用尽后 error 信息包含最后一条异常摘要（截断 200 字符）

## 4. 非功能验收

### 4.1 性能验收
- [ ] AC-4.1.1: robots.txt 缓存命中时无 HTTP 请求（mock httpx.get 调用计数 = 1 而非 N）
- [ ] AC-4.1.2: `_random_headers()` 调用耗时 < 1ms（纯内存操作）

### 4.2 代码质量验收
- [ ] AC-4.2.1: 新增生产代码 ≤ 200 行（不含注释/docstring/测试）
- [ ] AC-4.2.2: 所有新增公开函数有 docstring（`_check_robots`/`_random_headers`/`_next_proxy`）
- [ ] AC-4.2.3: 无空 catch / 吞异常（所有 except 块有日志或向上传播）
- [ ] AC-4.2.4: 无新外部依赖（仅使用标准库 `urllib.robotparser` + 已有 httpx/random/asyncio/time）
- [ ] AC-4.2.5: conftest autouse fixture 钉住测试环境（抓取相关开关 false + 代理/限速默认值）

### 4.3 向后兼容验收
- [ ] AC-4.3.1: `fetch_page(url)` 函数签名不变（参数/返回类型与 module-076 逐字一致）
- [ ] AC-4.3.2: `run_crawl(sources, max_pages)` 函数签名不变
- [ ] AC-4.3.3: CrawlResult / CrawlSummary 数据类字段不变
- [ ] AC-4.3.4: 无代理配置时行为与 module-076 完全一致（零回归）

## 5. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 单元测试 | `cd ai_service && python -m pytest tests/crawl/test_antibot.py -v` | All tests passed |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | 全量绿（≥ module-076 基线 + 新增） |
| py_compile | `python -c "import py_compile; py_compile.compile('rag/crawl/crawler.py'); py_compile.compile('src/config.py')"` | 无 SyntaxError |
| config 验证 | `cd ai_service && python -c "from src.config import settings; print(settings.crawl_request_delay_s, settings.crawl_max_retries, settings.crawl_proxy_list)"` | `1.0 3 ""` |
| robots mock 验收 | `cd ai_service && python -m pytest tests/crawl/test_antibot.py -k "robots" -v` | robots 相关测试全绿 |
| 重试 mock 验收 | `cd ai_service && python -m pytest tests/crawl/test_antibot.py -k "retry" -v` | 重试相关测试全绿 |
| 代理 mock 验收 | `cd ai_service && python -m pytest tests/crawl/test_antibot.py -k "proxy" -v` | 代理相关测试全绿 |

## 6. 验收结论
- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
