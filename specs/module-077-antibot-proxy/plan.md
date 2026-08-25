# 开发计划 — Module-077: 反爬绕过 + 代理池

## 1. 需求描述
- 需求来源: ADR-0019 阶段2 第三片；module-075 plan.md §8（阶段2 后续模块拆分表）；module-076 plan.md §6 遗留决策 #6（robots.txt 未遵守，留 module-077）
- 功能描述: 在现有 httpx fetch 链路上增强反爬能力——robots.txt 遵循（fetch 前检查+缓存）+ UA 轮换（内置 UA 池 + 请求头增强）+ 限速与重试退避（per-source 请求间隔、429/5xx 指数退避重试）+ 代理配置化轮换 + 失败切换
- 优先级: P0（阶段2 第三片，提升抓取成功率与合规性）
- 上下文: module-075 已实现 APScheduler + source_configs 表驱动 + httpx 单页 fetch + 审查节点 + 入库闭环。module-076 已实现递归爬取 + 深度控制 + URL 去重 + 黑白名单接线。当前 `fetch_page` 使用单个硬编码 UA 头（`"PersonalKB-Crawler/1.0"`）、无 robots.txt 检查、无限速、无重试、无代理支持。

### module-076 遗留核实（代码实证，2026-08-26）

| 遗留项 | 现状 | 本模块处置 |
|--------|------|-----------|
| robots.txt 未遵守 | module-076 plan.md §6 遗留决策 #6 明确声明"不做，留 module-077" | 子任务 1 实现 |
| fetch_page 无重试 | httpx GET 30s 超时 + raise_for_status，失败直接返回 CrawlResult(error=...) | 子任务 3 实现 |
| 单一 UA 头 | `_USER_AGENT = "PersonalKB-Crawler/1.0"` 硬编码常量 | 子任务 2 实现 |
| 无代理支持 | AsyncClient 无 proxy 参数 | 子任务 4 实现 |
| 无请求频率控制 | 无 sleep / rate limiter | 子任务 3 实现 |

## 2. 模块拆分

### 子任务 1: robots.txt 遵循
- 描述: `fetch_page` 调用前检查目标 URL 的 robots.txt（httpx 拉取 + 标准库 `urllib.robotparser` 解析 + 按域名缓存结果避免重复拉取）。`_crawl_page_and_store` 在 fetch 前调用 `_check_robots` 判定是否允许抓取该 URL。
- 预估代码量: 功能代码 ≤ 50 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：新增 `_robots_cache: dict[str, robotparser]` 模块级缓存 + `_check_robots(url) -> bool` 异步函数 + `_crawl_page_and_store` 内 fetch 前调用）
- 依赖: 无

### 子任务 2: UA 轮换 + 请求头增强
- 描述: 内置 UA 池（~10 个主流浏览器 UA 字符串）+ 每次 fetch 随机选择一个 UA；请求头增加 `Accept`、`Accept-Language` 等常见浏览器头，降低被识别为爬虫的概率。
- 预估代码量: 功能代码 ≤ 20 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：新增 `_UA_POOL` 常量列表 + `_random_headers() -> dict` 纯函数 + `fetch_page` 内替换硬编码 UA）
- 依赖: 无

### 子任务 3: 限速与重试退避
- 描述: (a) per-source 请求间隔：配置 `crawl_request_delay_s`（默认 1.0 秒），同一 source 内连续请求间 sleep。使用 `asyncio.sleep` 在 `_recursive_crawl` 每次 fetch 前注入延迟。(b) 重试退避：`fetch_page` 内 429/5xx 响应指数退避重试（默认 max_retries=3，base_delay=1.0s），重试间 jitter 防惊群。参数化 `crawl_max_retries` / `crawl_retry_base_delay_s`。
- 预估代码量: 功能代码 ≤ 40 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：`fetch_page` 内重试循环 + `_recursive_crawl` 内 delay 注入）
  - `ai_service/src/config.py`（新增 3 项配置：`crawl_request_delay_s` / `crawl_max_retries` / `crawl_retry_base_delay_s`）
- 依赖: 子任务 2（重试时每轮换新 UA）

### 子任务 4: 代理配置化轮换 + 失败切换
- 描述: 配置化代理列表（`crawl_proxy_list` 逗号分隔 `http://host:port`），`fetch_page` 内使用当前代理发起请求；请求失败时切换到下一个代理重试（与子任务 3 重试逻辑整合：每次重试先切代理再换 UA）。代理轮换使用简单轮询索引（round-robin）。
- 预估代码量: 功能代码 ≤ 30 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：新增 `_proxy_pool: list[str]` 模块级 + `_next_proxy() -> str | None` + `fetch_page` 内 httpx.AsyncClient(proxy=...)）
  - `ai_service/src/config.py`（新增 `crawl_proxy_list: str = ""`）
- 依赖: 子任务 3（代理切换集成进重试循环）

### 子任务 5: 测试
- 描述: 单元测试（mock httpx + mock robots.txt 响应 + mock 代理列表）；重点覆盖：robots.txt 允许/禁止/缓存命中/解析失败 fail-open、UA 轮换随机性、重试退避 429/5xx/超时不重试、代理切换 + 全部失败、限速 delay 注入。
- 预估代码量: 测试代码 ~120 行（**不含在 ≤200 行生产代码限额内**）
- 涉及文件:
  - `ai_service/tests/crawl/test_antibot.py`（新建）
  - `ai_service/tests/conftest.py`（若需补充 autouse 开关钉住）
- 依赖: 子任务 1 + 2 + 3 + 4

## 3. 技术方案

### 3.1 robots.txt 遵循

```
_check_robots(url) -> bool:
  host = urlparse(url).hostname
  if host in _robots_cache:
      return _robots_cache[host].can_fetch(_USER_AGENT, url)
  robots_url = f"{scheme}://{host}/robots.txt"
  resp = httpx.get(robots_url, timeout=5)
  rp = RobotFileParser()
  rp.parse(resp.text.splitlines())
  _robots_cache[host] = rp
  return rp.can_fetch(_USER_AGENT, url)
```

- **缓存策略**: `_robots_cache: dict[str, RobotFileParser]` 模块级 dict，进程生命周期内有效（单次 run_crawl 周期内多个同域名 URL 共享缓存）。不做 TTL 刷新——抓取批次通常在分钟级完成，robots.txt 极少变化。
- **失败策略**: robots.txt 拉取失败（404/超时/网络错误）→ fail-open 允许抓取（robots.txt 不存在视为无限制；网络错误不阻塞抓取主链路）。
- **库选型**: 标准库 `urllib.robotparser.RobotFileParser`（零新依赖）+ httpx 拉取文本。不引入 `reppy` / `protego` 等第三方库。
- **User-Agent 一致性**: `can_fetch` 使用与 fetch 相同的 UA 字符串（子任务 2 的 `_random_headers` 每次请求随机选择，robots 检查使用 `PersonalKB-Crawler` 通用前缀）。

### 3.2 UA 轮换 + 请求头增强

```python
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
    # ~10 个主流 Chrome/Firefox/Safari UA
]

def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,...",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
```

- **设计**: 纯函数，每次调用返回新 dict。`fetch_page` 内替换硬编码 `_USER_AGENT`。
- **robots 检查 UA**: 使用通用前缀 `"PersonalKB-Crawler"` 而非随机 UA（robots 规则用固定身份检查，每次不同 UA 可能导致不一致）。

### 3.3 限速与重试退避

**限速**:
```python
# _recursive_crawl 内，fetch 前注入延迟
if _last_fetch_time.get(source_id):
    elapsed = time.monotonic() - _last_fetch_time[source_id]
    if elapsed < settings.crawl_request_delay_s:
        await asyncio.sleep(settings.crawl_request_delay_s - elapsed)
_last_fetch_time[source_id] = time.monotonic()
```

- 使用 `time.monotonic()` 单调时钟 + `_last_fetch_time: dict[int, float]`（key 为 source_id），避免不同源之间互相限速（每个源独立节奏）。
- 延迟注入在 `_recursive_crawl` 内而非 `fetch_page` 内（fetch 是通用函数，限速是抓取调度语义）。

**重试退避**:
```python
# fetch_page 内重试循环
for attempt in range(settings.crawl_max_retries + 1):
    headers = _random_headers()
    proxy = _next_proxy()
    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers=headers,
            proxy=proxy,
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < settings.crawl_max_retries:
                    delay = settings.crawl_retry_base_delay_s * (2 ** attempt)
                    jitter = random.uniform(0, delay * 0.5)
                    await asyncio.sleep(delay + jitter)
                    continue
            resp.raise_for_status()
            # ... 正常处理
    except httpx.TimeoutException:
        if attempt < settings.crawl_max_retries:
            continue  # 超时直接重试，无额外延迟
        return CrawlResult(error="抓取超时")
    except Exception as e:
        return CrawlResult(error=str(e)[:200])
```

- **429/5xx**: 指数退避 + jitter（base_delay × 2^attempt + random jitter）
- **超时**: 直接重试（不加延迟——超时说明网络不稳，快试快判）
- **其他异常**: 不重试（非暂时性错误）
- **重试时同时换 UA + 切代理**（子任务 2/4 集成点）

### 3.4 代理配置化轮换 + 失败切换

```python
_proxy_list: list[str] = []
_proxy_index: int = 0

def _load_proxies() -> list[str]:
    return [p.strip() for p in settings.crawl_proxy_list.split(",") if p.strip()]

def _next_proxy() -> str | None:
    global _proxy_list, _proxy_index
    if not _proxy_list:
        _proxy_list = _load_proxies()
    if not _proxy_list:
        return None
    proxy = _proxy_list[_proxy_index % len(_proxy_list)]
    _proxy_index += 1
    return proxy
```

- **设计**: 简单 round-robin，每次重试切到下一个代理。`_proxy_list` 模块级缓存（从 config 读取一次）。
- **空列表**: `crawl_proxy_list=""`（默认）→ 不使用代理，`_next_proxy()` 返回 None，httpx 不传 proxy 参数。
- **失败切换**: 已集成在重试循环中——每次重试调 `_next_proxy()` 自然轮换。
- **不做的事情**: 真实代理市场接入（付费代理 API）、代理健康检查、SOCKS5 代理——这些留用户决策，本模块只做配置化 HTTP 代理轮换。

### 3.5 无头浏览器渲染（Playwright）—— 评估结论

| 维度 | 评估 |
|------|------|
| 依赖重量 | playwright ~300MB（Chromium 下载）+ pip install playwright |
| 平台兼容 | Windows/Linux/macOS 需 `playwright install chromium`，CI 环境额外配置 |
| 与现有架构集成 | httpx 异步 vs playwright 需要 BrowserContext 生命周期管理，改动面大 |
| 收益面 | 仅 JS 渲染站点（React/Vue SPA）需要，当前白名单站点（Spring/FastAPI/掘金等）多为服务端渲染 |
| 维护成本 | Chromium 版本更新 + 无头模式内存泄漏风险 + 超时控制更复杂 |

**结论：Playwright 不纳入本模块**。理由：
1. **依赖克制**：引入 ~300MB Chromium 下载 + 系统级依赖，违反轻量原则
2. **收益面窄**：ADR-0019 白名单站点多为 SSR，JS 渲染需求仅少数 SPA
3. **改动面大**：需异步 BrowserContext 生命周期管理，与现有 httpx 链路不兼容
4. **可后续扩展**：若真实抓取遇到 JS 渲染站点，可在后续 module-08x 中作为可选后端接入（`fetch_page` 参数化 `render_js=True` 时走 playwright）

### 3.6 config.py 新增配置项

| 配置项 | 环境变量 | 类型 | 默认值 | 说明 |
|--------|---------|------|--------|------|
| `crawl_request_delay_s` | PW_CRAWL_REQUEST_DELAY_S | float | 1.0 | 同源请求间隔（秒） |
| `crawl_max_retries` | PW_CRAWL_MAX_RETRIES | int | 3 | 429/5xx 最大重试次数 |
| `crawl_retry_base_delay_s` | PW_CRAWL_RETRY_BASE_DELAY_S | float | 1.0 | 重试退避基础延迟（秒） |
| `crawl_proxy_list` | PW_CRAWL_PROXY_LIST | str | "" | 逗号分隔 HTTP 代理列表 |

### 3.7 生产代码行数预算（铁律 2 ≤ 200 行）

| 改动点 | 预估行数 |
|--------|---------|
| `_check_robots` + `_robots_cache` + 缓存逻辑（crawler.py 新增） | ~30 |
| `_UA_POOL` + `_random_headers()`（crawler.py 新增） | ~18 |
| `fetch_page` 重试循环改造（含 UA/代理切换） | ~25 |
| `_proxy_list` + `_next_proxy()` + `_load_proxies()`（crawler.py 新增） | ~15 |
| `_recursive_crawl` 限速 delay 注入 + `_last_fetch_time` | ~12 |
| config.py（4 项新配置） | ~6 |
| `_crawl_page_and_store` robots 检查调用 | ~4 |
| **合计** | **~110** |

## 4. 验收标准

见同目录下 `acceptance-criteria.md`

## 5. 风险评估

- **风险 1: robots.txt 缓存导致过期判断**
  - 应对: 缓存仅在单次 run_crawl 生命周期内有效（模块级 dict），不跨批次持久化；APScheduler 每次触发 run_crawl 重新拉取
- **风险 2: 代理质量不可控（免费代理不稳定/高延迟）**
  - 应对: 配置化列表由用户自行维护；重试机制自动切换失败代理；空列表 = 不用代理（零回归）
- **风险 3: 限速 delay 累积导致抓取时间过长**
  - 应对: 默认 1s 间隔 + 10 页上限 = 最坏 +10s 延迟，相比单页 30s 超时+审查入库可忽略
- **风险 4: UA 池中 UA 字符串过时**
  - 应对: UA 池内置主流浏览器最新版 UA；后续可通过配置 `crawl_ua_list` 扩展（本模块不做，留 backlog）
- **风险 5: robots.txt 解析差异（不同实现对同一 robots.txt 解释不同）**
  - 应对: 使用标准库 `urllib.robotparser`，遵循 Google robots.txt 规范；fail-open 策略保守
- **风险 6: 并发抓取时限速竞态（多个协程同时访问 `_last_fetch_time`）**
  - 应对: `_last_fetch_time` 是 dict 读写（Python dict 线程安全 + asyncio 单线程），不存在竞态；若未来引入并发抓取需加锁

## 6. 复用清单

| 复用项 | 来源 | 说明 |
|--------|------|------|
| `fetch_page(url)` | crawler.py | 本模块改造：加重试循环 + UA 轮换 + 代理切换，签名不变返回 CrawlResult |
| `_crawl_page_and_store(url, summary)` | crawler.py | 本模块改造：fetch 前加 robots 检查，其余逻辑不变 |
| `_recursive_crawl(...)` | crawler.py | 本模块改造：fetch 前加限速 delay，其余逻辑不变 |
| `_normalize_url(url)` | crawler.py | 不修改 |
| `_extract_links(html, base_url, max_links)` | crawler.py | 不修改 |
| `_is_safe_url(url)` | crawler.py | 不修改 |
| `_matches_any(url, patterns)` | crawler.py | 不修改 |
| `_review_content(url, content, title)` | crawler.py | 不修改 |
| `_crawl_filename(url)` | crawler.py | 不修改 |
| `CrawlResult` / `CrawlSummary` | crawler.py | 不修改 |
| `start_scheduler()` / `shutdown_scheduler()` | crawler.py | 不修改 |
| `run_crawl(sources, max_pages)` | crawler.py | 不修改（限速注入在 _recursive_crawl 层） |

## 7. 不在本模块范围

- 无头浏览器渲染（Playwright）—— 依赖克制，评估后排除，留后续 module-08x
- 真实代理市场接入（付费代理 API）—— 留用户决策
- Cookie 管理 / Session 维持 —— 当前单页请求无需
- CAPTCHA 识别 / 人机验证绕过 —— 伦理与法律边界，不做
- 代理健康检查 / 自动剔除 —— 留后续扩展
- 自定义 UA 列表配置 —— 留 backlog

## 8. 遗留决策清单（默认值已定，任务完成后统一汇报由用户决策）

| # | 决策点 | 本模块默认值 | 理由 |
|---|--------|-------------|------|
| 1 | robots.txt 失败策略 | fail-open（允许抓取） | robots.txt 不存在=无限制；网络错误不阻塞抓取 |
| 2 | UA 池大小 | ~10 个主流浏览器 UA | 覆盖 Chrome/Firefox/Safari 主要版本 |
| 3 | 限速默认间隔 | 1.0 秒 | 粗粒度礼貌间隔，不过度影响抓取效率 |
| 4 | 重试次数 | 3 次 | 429/5xx 通常 1-2 次可恢复，3 次保底 |
| 5 | 重试退避策略 | 指数退避 + jitter（base × 2^attempt） | 防惊群效应，业界标准做法 |
| 6 | Playwright 不纳入 | 排除 | 依赖克制 + 收益面窄 + 改动面大，详见 §3.5 |
| 7 | 代理协议 | 仅 HTTP 代理 | SOCKS5 需 httpx[socks] 额外依赖，留扩展 |
| 8 | robots 检查 UA | 固定 "PersonalKB-Crawler" 前缀 | robots 规则用固定身份检查，与 fetch 随机 UA 解耦 |

## 9. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本 | Planner |
