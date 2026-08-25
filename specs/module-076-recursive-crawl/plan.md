# 开发计划 — Module-076: 递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池

## 1. 需求描述

- 需求来源: ADR-0019 阶段2 第二片；module-075 plan.md §8（阶段2 后续模块拆分表）
- 功能描述: 从源 URL（种子页）出发，提取页面内 `<a href>` 链接 → 递归跟踪（受深度限制，**默认 depth=1**，可配置）→ URL 规范化 + 内存去重池（已抓 URL 不重复抓）→ 白/黑名单过滤（**递归跟踪的链接同样过白/黑名单**）→ 总页数上限（防递归爆炸）
- 优先级: P0（阶段2 第二片，知识自动扩充的核心能力）
- 上下文: module-075 已实现 source_configs 表驱动白名单 + APScheduler 定时调度 + httpx 单页 fetch + 审查节点（reflector + factcheck_judge，fail-open）+ document_ingest 入库 + review_status 落库闭环。**当前抓取只做单页**（URL 直接 GET，不递归）。本模块把单页升级为受控递归。

### module-075 遗留核实（代码实证，2026-08-26）

| 遗留项 | 现状 | 本模块处置 |
|--------|------|-----------|
| 黑名单过滤未实现 | `_matches_any`（crawler.py:64）已定义且有单测（tests/crawl/test_crawler.py:52-61），但 `run_crawl` 主链路从未调用（死代码）；**黑名单 pattern 无配置来源** | 子任务 3 接线 + config 补 `crawl_blacklist_patterns` 来源 |
| `_matches_any` 白名单未接线 | 同上一行，死代码 | 递归白名单边界 = 链接命中本源 `url_pattern` 前缀（module-075「url_pattern 即该源白名单」哲学延续），种子与递归链接统一过黑名单 |
| review_status 落库 | 已修复（module-075 修复轮打通 crawler.py→ingest_document→add_document→Document ORM 四层透传，默认值向后兼容；Tester 验收通过 doc_id=16671） | 递归页面复用同一链路，无需再修；验收项覆盖 |
| .html 扩展名兼容 | 已修复（crawler.py 入库 filename 统一 `crawl_{...}.txt` 绕开 AnyDoc 扩展名路径 + document_parser 新增 html 回退；真实冒烟通过） | 递归复用 fetch_page→ingest_document 管线，验收确认递归 .html 页入库不抛 DocumentParseError |

## 2. 模块拆分

### 子任务 1: 递归爬取引擎 + 深度控制
- 描述: crawler.py 新增 `_extract_links` 纯函数（标准库正则提取 href + `urljoin` 绝对化）与 `_recursive_crawl`（深度判断 → 规范化 → visited 去重 → 白/黑名单 → fetch → 审查 → 入库 → 提取链接 → 递归子层）；source_configs 新增 `max_depth` 列（init_db 幂等 ALTER）；main.py 端点支持 max_depth
- 预估代码量: 功能代码 ≤ 90 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：新增 `_extract_links` / `_recursive_crawl`，改造 `run_crawl` 调用递归版）
  - `ai_service/src/database.py`（新增 CRAWL_DEPTH_DDL + ensure，init_db 挂接）
  - `ai_service/src/config.py`（新增 `crawl_max_depth`）
  - `ai_service/main.py`（修改：CrawlSourceRequest + POST/GET 端点支持 max_depth）
- 依赖: 无

### 子任务 2: URL 规范化 + 去重池
- 描述: `_normalize_url` 纯函数（urlparse → 去 fragment → scheme+host lowercase → 去尾部斜杠）+ `run_crawl` 内 `visited: set[str]` 内存去重池（单次 run_crawl 生命周期内有效，递归全树共享、同批跨源共享）
- 预估代码量: 功能代码 ≤ 25 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：新增 `_normalize_url` + `run_crawl` 内 visited）
- 依赖: 子任务 1

### 子任务 3: 白/黑名单主链路接线
- 描述: `_matches_any` 接入主链路——黑名单（config `crawl_blacklist_patterns` 逗号分隔 URL 前缀）对**种子 URL 与递归链接统一过滤**；递归白名单边界 = 链接命中本源 `url_pattern` 前缀（源级白名单）
- 预估代码量: 功能代码 ≤ 15 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（修改：种子检查 + `_recursive_crawl` 内调用 `_matches_any`）
  - `ai_service/src/config.py`（新增 `crawl_blacklist_patterns`）
- 依赖: 子任务 1

### 子任务 4: 测试 + 回归
- 描述: 单元测试（mock httpx + mock 审查 + mock ingest_document：深度 0/1/2、去重、黑名单、URL 规范化、链接截断、fail-open 全树不阻断）；conftest autouse 钉住 crawl_enabled=false（hermetic）；全量回归
- 预估代码量: 测试代码 ~130 行（**不含在 ≤200 行生产代码限额内**）
- 涉及文件:
  - `ai_service/tests/crawl/test_recursive_crawl.py`（新建）
  - `ai_service/tests/conftest.py`（若需补充 autouse 开关钉住）
- 依赖: 子任务 1 + 2 + 3

## 3. 技术方案

### 3.1 递归抓取架构

```
run_crawl(sources, max_pages)
  ├── limit = max_pages or settings.crawl_max_pages_per_run   # 总页数上限（沿用 module-075）
  ├── visited = set()          # 去重池：单次 run_crawl 全树共享（跨源共享）
  ├── for each source:
  │     ├── 种子 URL = url_pattern；max_depth = min(source.max_depth, settings.crawl_max_depth)
  │     ├── 种子过 _is_safe_url + 黑名单（_matches_any）
  │     └── _recursive_crawl(seed, depth=0, max_depth, visited, summary)
  │           ├── if len(visited) >= limit: return          # 总页数上限（全树共享）
  │           ├── if depth > max_depth: return
  │           ├── url = _normalize_url(url)
  │           ├── if url in visited: return                 # 去重（循环 A→B→A 自断）
  │           ├── if _matches_any(url, blacklist): return   # 黑名单
  │           ├── visited.add(url)
  │           ├── result = fetch_page(url)                  # 复用 module-075，30s 超时
  │           ├── if not result.success: errors++ / continue（fail-open）
  │           ├── review = _review_content(url, content, title)（fail-open）
  │           ├── ingest_document(..., review_status=review)（异常捕获，fail-open）
  │           └── for link in _extract_links(content, url, limit):
  │                 _recursive_crawl(link, depth+1, max_depth, visited, summary)
```

### 3.2 URL 规范化（`_normalize_url(url) -> str`）
- `urllib.parse.urlparse` → 去 fragment（`#...`）→ scheme + host lowercase → 去尾部 `/`（仅路径非空时）
- 纯函数、无副作用、可单测
- 例: `https://EXAMPLE.com/path/#frag` → `https://example.com/path`

### 3.3 链接提取（`_extract_links(html, base_url, max_links) -> list[str]`）
- 标准库 `re` 正则 `href=["']([^"']+)` + `urllib.parse.urljoin(base_url, href)` 绝对化（**不引入 BeautifulSoup——纯正则满足 href 提取，避免新重依赖，且天然无 DOM 解析器防 XXE**）
- `urljoin` 后仅保留 http/https（mailto:/javascript:/ftp:/data: 丢弃）
- 返回前统一过 `_normalize_url`（fragment 自然消除）
- 上限: 提取链接数 > `crawl_max_links_per_page`（默认 20）时截断，防导航页/页脚爆量
- 非 HTML 内容（content-type 非 text/html 或正文无 `<a`）返回空列表，递归自然终止

### 3.4 深度控制
- `source_configs.max_depth INT DEFAULT 1`（单源可配）：
  - 0 = 仅种子页（等价 module-075 单页行为，逃生口）
  - 1 = 种子 + 一层链接（**默认**）
  - 2+ = 更深（用户可配，需注意抓取量增长）
- 全局上限 `crawl_max_depth = 2`（config，PW_CRAWL_MAX_DEPTH）：单源实际深度取 `min(source.max_depth, crawl_max_depth)`，防用户误配过大值
- 深度语义: `_recursive_crawl(url, depth)`，`depth` 从 0 计（种子页 depth=0），`depth > max_depth` 即返回

### 3.5 去重策略
- **批次内去重（本模块核心）**: `visited: set[str]` 内存级，URL 规范化后加入；`run_crawl` 生命周期内有效（单次抓取周期，不跨批次持久化——任务书明确内存级）
- **跨批次去重**: 复用 document_dedup L1（doc_content_hash 文档级 sha256）——同 URL 同内容二次入库被 exact_hash 丢弃，不重复造轮子
- **跨源去重**: 同批不同源链接到同一页，共享 visited 防重复抓

### 3.6 白名单/黑名单过滤
- **黑名单**（本模块新增配置来源）: config `crawl_blacklist_patterns: str = ""`（PW_CRAWL_BLACKLIST_PATTERNS，逗号分隔 URL 前缀，如 `https://csdn.net,https://blog.csdn.net`）→ `_matches_any(url, patterns)` 命中即跳过（种子 + 递归链接统一）
- **白名单**（递归边界）: 递归链接必须命中本源 `url_pattern` 前缀（module-075「url_pattern = 该源白名单」哲学延续，DB COMMENT 同义）——递归不跨出源配置范围，抓取范围可预期
- 优先级: 白名单边界判定在前（非本源前缀直接丢弃，不递归），黑名单判定在 visited 去重之后（黑名单 URL 不入池不计数）

### 3.7 防递归爆炸三层（总页数限制）
1. 深度上限: `min(source.max_depth, crawl_max_depth=2)`
2. 单页链接上限: `crawl_max_links_per_page = 20`（PW_CRAWL_MAX_LINKS_PER_PAGE，config）
3. 总页数上限: 沿用 `run_crawl(max_pages)` / config `crawl_max_pages_per_run = 10`——**递归全树共享同一计数**（`len(visited) >= limit` 即停），所有深度页面合计不超限
4. 单页 30s 超时（复用 module-075 fetch_page）

### 3.8 数据表变更
- `source_configs` 新增列:
  - `max_depth INT NOT NULL DEFAULT 1` — 单源最大抓取深度
- DDL: `ALTER TABLE source_configs ADD COLUMN IF NOT EXISTS max_depth INTEGER NOT NULL DEFAULT 1;`
- init_db 幂等 ALTER（对齐 module-075 `ensure_source_configs_table` / `ensure_review_status_column` 拆分执行模式）

### 3.9 API 端点变更
- `POST /ai/crawl/sources`: `CrawlSourceRequest` 新增可选字段 `max_depth: int = 1`（校验 0 ≤ max_depth ≤ 5，非法返回 code=1）
- `GET /ai/crawl/sources`: 返回新增 `max_depth` 字段
- `POST /ai/crawl/run`: 行为变化——单页抓取变为按 `source.max_depth` 递归抓取（响应结构不变：crawled/approved/rejected/errors/skipped）

### 3.10 生产代码行数预算（铁律 2 ≤ 200 行）

| 改动点 | 预估行数 |
|--------|---------|
| `_normalize_url`（crawler.py 新增） | ~10 |
| `_extract_links`（crawler.py 新增） | ~18 |
| `_recursive_crawl`（crawler.py 新增，≤50 行铁律） | ~40 |
| `run_crawl` 改造（visited + 调递归版） | ~20 |
| `_load_sources_from_db` + 种子黑名单检查 | ~8 |
| config.py（crawl_max_depth / crawl_blacklist_patterns / crawl_max_links_per_page） | ~6 |
| database.py（CRAWL_DEPTH_DDL + ensure + init_db 挂接） | ~12 |
| main.py（CrawlSourceRequest + POST/GET max_depth） | ~10 |
| **合计** | **~124** |

## 4. 验收标准

见同目录下 `acceptance-criteria.md`

## 5. 风险评估

- **风险 1: 递归抓取量指数增长**（depth=2 时每页 20 链接 → 理论 400 页）
  - 应对: 三层上限（深度 2 + 单页 20 链接 + 总页数 10 全树共享计数）——实际单源最多 10 页
- **风险 2: 无限循环**（A→B→A→B→…）
  - 应对: `_normalize_url` 规范化 + visited set 去重，循环自断（单测锁定）
- **风险 3: 外部页面链接量巨大**（导航/页脚/广告数百链接）
  - 应对: `crawl_max_links_per_page=20` 截断 + 白名单边界（仅本源前缀）天然过滤外链
- **风险 4: robots.txt 未遵守**（本模块不做 robots 礼仪）
  - 应对: 如实声明，module-077 专门做反爬/robots/代理
- **风险 5: 单次 run_crawl 时间过长**
  - 应对: 总页数上限（10 页）× 单页 30s 超时 = 最坏 ~5 分钟 + 审查/入库；调度器任务并发用 asyncio.create_task 非阻塞
- **风险 6: 递归页 filename 生成空段**（URL 以 `/` 结尾时 `split('/')[-1]` 为空 → `crawl_.txt`）
  - 应对: filename 生成对空段回退（用 `name` 或 host 段），单测覆盖

## 6. 遗留决策清单（默认值已定，任务完成后统一汇报由用户决策）

| # | 决策点 | 本模块默认值 | 理由 |
|---|--------|-------------|------|
| 1 | 默认抓取深度 | **depth=1**（种子 + 一层链接） | 任务书明确「默认 depth=1，可配置」；0 为逃生口等价 module-075 |
| 2 | 黑名单配置来源 | config `crawl_blacklist_patterns`（逗号分隔前缀，不建表） | 轻量内聚；后续需 DB 驱动再迁移 |
| 3 | 递归白名单边界 | 仅本源 `url_pattern` 前缀（不跨源） | 抓取范围可预期，与 module-075 源级白名单哲学一致 |
| 4 | 单页链接上限 | 20 | 防导航/页脚爆量；可 PW_CRAWL_MAX_LINKS_PER_PAGE 调 |
| 5 | 全局深度上限 | 2 | 防用户误配过深；min(source, global) 生效 |
| 6 | robots.txt 检查 | 不做（留 module-077） | 模块边界，如实声明 |
| 7 | 链接提取库 | 标准库 re + urlparse（不引 BeautifulSoup） | 任务书「标准库（BeautifulSoup 或正则）」二选一取正则——零新依赖 + 防 XXE |

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本 | Planner |
| v2 | 2026-08-26 | 代码实证核实后重写：修正「遗留问题」表述（.html/review_status 已修）、黑名单来源落实为 config、深度/链接上限等默认值从「待澄清」落实为「遗留决策清单」、补总页数上限全树共享设计 | Planner |

## 8. 复用 module-075 逻辑清单

| 复用项 | 来源 | 说明 |
|--------|------|------|
| `fetch_page(url)` | crawler.py | 单页 httpx GET → CrawlResult（30s 超时 + UA + 标题提取），不修改 |
| `_review_content(url, content, title)` | crawler.py | 审查节点包装（reflector + factcheck_judge，fail-open），不修改 |
| `_is_safe_url(url)` | crawler.py | URL 协议安全校验（仅 http/https），不修改 |
| `_matches_any(url, patterns)` | crawler.py | 前缀匹配，**本模块接入主链路**（黑名单过滤） |
| `ingest_document(...)` | document_ingest.py | 入库管线（含 review_status 透传），不修改 |
| `CrawlResult` / `CrawlSummary` | crawler.py | 数据类，不修改 |
| `start_scheduler()` / `shutdown_scheduler()` | crawler.py | APScheduler 生命周期，不修改 |
| `_load_sources_from_db()` | crawler.py | DB 读源配置，扩展 max_depth 字段 |
| `run_crawl(sources, max_pages)` | crawler.py | 批量抓取入口，**改造为调用递归版本**（visited + 深度 + 过滤） |

## 9. 不在本模块范围

- robots.txt 礼仪 / 反爬绕过 / 代理池 / Cookie 管理 / Playwright 无头浏览器（module-077）
- 审查节点增强（阈值校准/矛盾检测/人工复核 UI，module-078）
- 增量 append 不重建验证（module-079）
- 反向闭环（低分题→待学笔记→自动抓取，module-080）
- 跨批次持久化 URL 去重（document_dedup L1 exact_hash 已覆盖，不新建表）
