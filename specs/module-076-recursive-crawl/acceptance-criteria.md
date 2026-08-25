# 验收标准 — Module-076: 递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池

> 验收依据: `plan.md`（v2，2026-08-26）。覆盖 ADR-0019 阶段2 第二片五项目标：链接提取 / 递归深度控制（默认 1）/ URL 去重 / 白黑名单集成 / 总页数限制。

## 1. 功能验收

### 1.1 核心路径验收

- [ ] **1.1.1** 种子 URL `max_depth=0` 时仅抓取种子页（等价 module-075 单页行为），不跟踪任何链接
- [ ] **1.1.2** 种子 URL `max_depth=1`（默认）时抓取种子页 + 种子页内链接（命中本源 url_pattern 前缀），形成一层抓取树
- [ ] **1.1.3** 种子 URL `max_depth=2` 时递归两层（种子 → 链接 → 链接的链接）
- [ ] **1.1.4** `source_configs` 表新增 `max_depth` 列（INT NOT NULL DEFAULT 1，存量行自动取 1），DDL 幂等（init_db 可重复执行）
- [ ] **1.1.5** `POST /ai/crawl/sources` 可设置 `max_depth`（缺省 1）；非法值（<0 或 >5）返回 `code=1` 拒绝
- [ ] **1.1.6** `GET /ai/crawl/sources` 返回中每个源包含 `max_depth` 字段
- [ ] **1.1.7** `POST /ai/crawl/run` 行为从单页变为按 `source.max_depth` 递归抓取，响应结构不变（crawled/approved/rejected/errors/skipped）
- [ ] **1.1.8** 全局上限 `crawl_max_depth=2`（PW_CRAWL_MAX_DEPTH）生效：`source.max_depth=5` → 实际按 2 递归（min 取）
- [ ] **1.1.9** 递归抓取的页面通过审查节点（reflector.check_sufficiency + factcheck_judge，fail-open）后入库，`review_status` 正确写入 DB（approved/rejected 均可查询到）
- [ ] **1.1.10** 递归抓取的 .html 页面（含 `.html` 后缀链接）入库不抛 DocumentParseError（filename 为 .txt + document_parser html 回退生效）

### 1.2 边界条件验收

- [ ] **1.2.1** URL 规范化：`https://example.com/path#frag` → `https://example.com/path`（去 fragment）
- [ ] **1.2.2** URL 规范化：`https://example.com/path/` → `https://example.com/path`（去尾部斜杠，路径非空时）
- [ ] **1.2.3** URL 规范化：`HTTPS://Example.COM` → `https://example.com`（scheme+host lowercase）
- [ ] **1.2.4** 循环链接防爆：A→B→A 时 visited set 阻止第二次抓 A（规范化后判重）
- [ ] **1.2.5** 跨源去重：同一批次内两个源链接到同一页，只抓一次（visited 全树共享）
- [ ] **1.2.6** 黑名单过滤：种子 URL 或递归链接命中 `crawl_blacklist_patterns` 前缀 → 跳过，不抓取不入库（日志记录）
- [ ] **1.2.7** 白名单边界：递归链接不命中本源 `url_pattern` 前缀（外域/外链）→ 丢弃不递归
- [ ] **1.2.8** 链接提取只保留 http/https，忽略 mailto:/javascript:/ftp:/data:
- [ ] **1.2.9** 相对路径链接正确解析为绝对 URL（`urljoin(base_url, href)`）
- [ ] **1.2.10** 单页提取链接数 > `crawl_max_links_per_page`（默认 20）时截断（只取前 20）
- [ ] **1.2.11** URL 以 `/` 结尾（末段为空）时入库 filename 生成不产生 `crawl_.txt`（回退 name/host 段）

### 1.3 异常场景验收

- [ ] **1.3.1** 递归过程中某页抓取失败（404/500/超时 >30s）不阻断整棵树，继续抓其他链接（fail-open）
- [ ] **1.3.2** 递归过程中某页审查节点调用失败 → fail-open 默认 approved 入库（不误杀）
- [ ] **1.3.3** 递归过程中某页入库失败 → 不阻断其他链接的抓取（errors 计数 + 日志）
- [ ] **1.3.4** `crawl_max_pages_per_run`（默认 10）总页数限制在递归模式下仍生效——**所有深度页面合计**不超过上限（递归全树共享计数）
- [ ] **1.3.5** 空页面 / 无链接页面：`_extract_links` 返回空列表，递归自然终止
- [ ] **1.3.6** 非 HTML 内容（如 PDF 二进制）页面：不提取链接（返回空），递归终止，内容走 document_parser 正常入库

## 2. 非功能验收

### 2.1 性能验收

- [ ] **2.1.1** depth=1 + 10 个链接 × 30s 超时 ≤ 6 分钟（含审查 + 入库）
- [ ] **2.1.2** depth=2 + `crawl_max_pages_per_run=50` 上限场景 ≤ 25 分钟（最坏 50 页 × 30s）
- [ ] **2.1.3** URL 规范化 + visited set 查找 O(1)（集合哈希）
- [ ] **2.1.4** 递归不改变 APScheduler 定时任务非阻塞语义（asyncio.create_task 调度，与用户请求并发不冻结）

### 2.2 安全验收

- [ ] **2.2.1** `_is_safe_url` 对递归提取的链接同样生效（file:/// 等被拦截）
- [ ] **2.2.2** 链接提取用纯正则（无 DOM/XML 解析器，防 XXE）；不引入新重依赖（标准库 re + urllib.parse）
- [ ] **2.2.3** 日志中 URL 截断 `[:80]`（沿用 module-075 口径），无敏感信息泄露
- [ ] **2.2.4** 黑名单默认值为空字符串（零配置 = 仅白名单边界生效），配置不含硬编码密钥

### 2.3 代码质量验收

- [ ] **2.3.1** 新增生产代码 ≤ 200 行（铁律 2；不含注释/docstring/测试；git diff --numstat 核）
- [ ] **2.3.2** `_extract_links` / `_normalize_url` 为纯函数（无副作用，可独立单测）
- [ ] **2.3.3** `_recursive_crawl` 方法 ≤ 50 行（铁律 3，含 docstring）
- [ ] **2.3.4** 所有新增公开方法有 docstring（铁律 4）
- [ ] **2.3.5** 无空 catch / 吞异常（铁律 5）——递归内 except 必须有日志或计数
- [ ] **2.3.6** 无硬编码魔法数字（深度上限/链接上限/超时等命名常量或走 config）
- [ ] **2.3.7** `_matches_any` 主链路接线后不再为死代码（run_crawl / _recursive_crawl 有调用点）

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 模块单测全绿 | `cd ai_service && .venv\Scripts\python.exe -m pytest tests/crawl/test_recursive_crawl.py -v` | 全部 PASSED |
| 存量抓取单测不回归 | `cd ai_service && .venv\Scripts\python.exe -m pytest tests/crawl/ -v` | 全部 PASSED（module-075 30 项 + 本模块新增） |
| 全量回归 | `cd ai_service && .venv\Scripts\python.exe -m pytest tests/ -q` | 全量 passed / 0 新增 failed（允许既有环境性失败 5 项） |
| import 冒烟 | `cd ai_service && .venv\Scripts\python.exe -c "import main"` | import main OK |
| DDL 幂等 | `cd ai_service && .venv\Scripts\python.exe -c "import asyncio; from src.database import init_db; asyncio.run(init_db())"` | 无报错（可重复执行） |
| py_compile | `cd ai_service && .venv\Scripts\python.exe -c "import py_compile; py_compile.compile('rag/crawl/crawler.py')"` | 无报错 |
| 生产行数 | `cd ai_service && git diff --numstat`（对比 module-075 提交 f143c80） | 新增生产代码 ≤ 200 行 |

### 单测场景矩阵（test_recursive_crawl.py 必含）

| 场景 | 断言 |
|------|------|
| max_depth=0 → 仅种子页 | 只调 1 次 fetch，链接不递归 |
| max_depth=1 → 种子 + 一层 | fetch 调用 = 种子 + 白名单链接数 |
| max_depth=2 → 两层 | 深度 2 的页面链接不再展开 |
| 全局上限生效 | source.max_depth=5 → 实际递归深度 2 |
| A→B→A 循环 | B 返回后 A 不再二次 fetch |
| 跨源共享 visited | 两源链接同一页只抓一次 |
| 黑名单命中（种子 + 递归） | `_matches_any` 命中跳过，不 fetch 不入库 |
| 外域链接丢弃 | 不命中 url_pattern 前缀的链接不递归 |
| URL 规范化三例 | fragment/尾斜杠/lowercase（1.2.1-1.2.3） |
| 链接截断 >20 | 只提取前 20 |
| 单页失败不阻断 | 中段页 404 → 后续链接继续抓 |
| 审查失败 fail-open | mock 抛异常 → review_status=approved |
| 入库失败不阻断 | mock ingest_document 抛异常 → 其他链接继续 |
| 总页数上限全树生效 | limit=3 时全树合计抓取 ≤ 3 页 |
| 空/非 HTML 页面 | `_extract_links` 返回 []，递归终止 |

## 4. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
