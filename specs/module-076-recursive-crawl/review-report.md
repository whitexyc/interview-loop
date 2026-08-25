# 审查报告 — Module-076

> 审查范围：递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池
> 依据：plan.md（v2）、acceptance-criteria.md、changelog.md、实际代码（crawler.py / config.py / database.py / main.py / test_recursive_crawl.py 完整读取）

## 1. 审查结论

- 结论：✅ 通过（附 2 项低危观察建议，不阻断）
- 审查时间：2026-08-26
- 审查人：Reviewer（module-076 第四阶段）

**独立验证记录（非仅凭 changelog）**：
| 验证项 | 命令 | 实测结果 |
|--------|------|----------|
| 模块单测 | `pytest tests/crawl/test_recursive_crawl.py -q` | `33 passed, 2 warnings in 33.96s` ✓ |
| 存量回归 | `pytest tests/crawl/ -q` | `63 passed, 2 warnings in 32.84s`（075 的 30 项 + 076 的 33 项，零回归）✓ |
| 编译冒烟 | `py_compile` 四文件 | `py_compile OK` ✓ |
| import 冒烟 | `import main` | `import main OK` ✓ |
| 生产行数 | AST 口径独立复核 | 新代码 ~118–158 行 < 200（changelog 报 158，复核口径差异源于 run_crawl 整函数计数，远低于上限）✓ |
| conftest 钉住 | tests/conftest.py:229 `@pytest.fixture(autouse=True) default_crawl_disabled` | 已钉住 `crawl_enabled=False`（hermetic 双重保证）✓ |

## 2. 问题列表（如有）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/rag/crawl/crawler.py | 366-367 | `source_depth = max(int(raw_depth) if raw_depth is not None else 1, 0)`：`int(raw_depth)` 对非整数值（直接改库/非法调用方传入）会抛 ValueError 且无捕获 → 单源异常中断整个批次（手动端点 500；调度器路径被外层 catch 吞成整批失败）。正常来源为 DB INTEGER 列 + API 0-5 校验，理论触发面低 | 低 | 建议 `try/except (TypeError, ValueError)` 兜底 1 并 logger.warning，保持 fail-open 哲学（与 `_load_sources_from_db` 存量兜底 1 口径一致） |
| 2 | ai_service/rag/crawl/crawler.py | 93, 369 | 白名单边界对"url_pattern 带尾斜杠"不自洽：`_normalize_url` 保留根路径 `/`（len(path)>1 才去尾斜杠），故 url_pattern=`https://example.com/` 规范化后仍带 `/`，而页面内裸根链接 `https://example.com` 规范化后无 `/` → `_matches_any` 前缀不命中被丢弃。属前缀匹配固有边界，验收矩阵未覆盖，影响面窄（仅根路径链接） | 低（观察项） | 可在 changelog/遗留清单如实声明；如要修，url_pattern 入库前统一去尾斜杠即可 |
| 3 | ai_service/rag/crawl/crawler.py（全链路） | 多处 logger | 日志行本身不携带 `request_id` 参数（如 `_crawl_page_and_store` / `_recursive_crawl` / `_load_sources_from_db` 的 warning） | 说明（非问题） | 项目已由 module-058 修复轮通过 `TraceIdFilter`（src/observability.py:76）在根 logger 全局注入 `record.trace_id`（main.py:63 挂载，日志格式含 `%(trace_id)s`），请求上下文内的日志行自动带 trace_id；调度器触发（无请求上下文）为空串，与 module-075 既定约定一致，不视为违规 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 |
|--------|----------|------|
| 1.1.1 max_depth=0 仅种子页 | `run_crawl`（crawler.py:366-367 保留 0）+ 单测 test_depth_zero_seed_only | ✅ |
| 1.1.2 max_depth=1 种子+一层 | `_recursive_crawl` depth 语义（种子=0，`depth > max_depth` 返回）+ test_depth_one_seed_plus_links（crawled=3） | ✅ |
| 1.1.3 max_depth=2 两层 | test_depth_two_two_levels（fetch=3，d 层 depth=3 不抓） | ✅ |
| 1.1.4 max_depth 列 DDL 幂等 | database.py `CRAWL_DEPTH_DDL`（`ADD COLUMN IF NOT EXISTS ... DEFAULT 1`）+ `ensure_max_depth_column` + init_db 挂接；存量行默认 1 | ✅ |
| 1.1.5 POST 校验 0-5 | main.py:1042 `CRAWL_DEPTH_API_MAX=5`，:1067 `if not 0 <= req.max_depth <= CRAWL_DEPTH_API_MAX` → code=1 | ✅ |
| 1.1.6 GET 返回 max_depth | main.py:1090 SELECT 含 max_depth，:1096 返回字段 | ✅ |
| 1.1.7 run 响应结构不变 | main.py:1115-1124 返回 crawled/approved/rejected/errors/skipped | ✅ |
| 1.1.8 全局上限 min 生效 | `max_depth = min(source_depth, settings.crawl_max_depth)`（crawler.py:368）+ test_global_depth_cap（5→2） | ✅ |
| 1.1.9 review_status 落库 | `_crawl_page_and_store` ingest_document(review_status=review) + test_rejected_recursive_still_ingested | ✅ |
| 1.1.10 .html 递归入库 | `_crawl_filename` 恒 .txt + document_parser html 回退（module-075 复用） | ✅ |
| 1.2.1-1.2.3 URL 规范化 | `_normalize_url`（crawler.py:88-102）：fragment 置空 / len(path)>1 去尾斜杠 / scheme+host lowercase；TestNormalizeUrl 6 项（含 port/query 保留、非法端口 fail-open） | ✅ |
| 1.2.4 循环 A→B→A | `visited` 规范化后判重 + test_cycle_a_b_a（fetch=2） | ✅ |
| 1.2.5 跨源去重 | `visited` 在 `run_crawl` 全树共享（crawler.py:357）+ test_cross_source_shared_visited | ✅ |
| 1.2.6 黑名单种子+递归 | `_is_blacklisted_url`（run_crawl 种子检查 :365 + `_recursive_crawl` :347）+ 两单测 | ✅ |
| 1.2.7 白名单边界 | `whitelist=[_normalize_url(url_pattern)]` + `_recursive_crawl` `_matches_any(url, whitelist)` + test_external_link_dropped | ✅ |
| 1.2.8 仅 http/https | `_extract_links` `_is_safe_url` 过滤（mailto:/javascript:/ftp:/data:/file: 丢弃）+ test_unsafe_schemes_filtered | ✅ |
| 1.2.9 相对路径绝对化 | `urljoin(base_url, href.strip())` + test_relative_url_resolved | ✅ |
| 1.2.10 链接截断 | `len(links) >= max_links: break`（crawl_max_links_per_page=20）+ test_truncate_over_max | ✅ |
| 1.2.11 filename 防 crawl_.txt | `_crawl_filename` 空段回退（`segment or "page"`）+ TestCrawlFilename 3 项 | ✅ |
| 1.3.1 单页失败不阻断 | `_crawl_page_and_store` fetch 失败 errors++ 返回 [] + test_single_page_failure_does_not_block | ✅ |
| 1.3.2 审查 fail-open | 审查 try/except 兜底 `review="approved"` + `_recursive_crawl` 外层 except + test_review_failure_fail_open_approved | ✅ |
| 1.3.3 入库失败不阻断 | 入库 except → errors++ 且子链接仍展开（`_extract_links` 在 except 后）+ test_ingest_failure_does_not_block（ingest 3 次） | ✅ |
| 1.3.4 总页数全树共享 | `len(visited) >= limit` 入口判定（黑名单不入池不计数）+ test_total_page_limit_shared_across_tree（limit=3→3 页） | ✅ |
| 1.3.5 空/非 HTML 终止 | `_extract_links` `not html or "<a" not in ...` 返回 [] + test_empty_page_terminates / test_empty_or_non_html | ✅ |
| 2.1.1/2.1.2 性能上限 | 深度 2 + 单页 20 链接 + 总页数 10 三层约束，最坏 ~5 分钟（串行 await 设计） | ✅ |
| 2.1.3 visited 查找 O(1) | `set[str]` 哈希 | ✅ |
| 2.1.4 调度非阻塞 | 异步递归 + APScheduler AsyncIOScheduler 语义不变 | ✅ |
| 2.2.1 递归链接过 _is_safe_url | `_extract_links` 内过滤（file:// 拦截） | ✅ |
| 2.2.2 纯正则防 XXE | `_HREF_RE` 标准库 re + urllib.parse，零新依赖 | ✅ |
| 2.2.3 日志 URL 截断 [:80] | 全链路 `url[:80]` / `url_pattern[:80]` | ✅ |
| 2.2.4 黑名单默认空串 | config `crawl_blacklist_patterns: str = ""` + TestBlacklistPatterns.test_empty_default | ✅ |
| 2.3.1 新增生产代码 ≤200 | AST 复核 ~118-158 行 < 200 | ✅ |
| 2.3.2 纯函数 | `_extract_links` / `_normalize_url` 无副作用可独立单测 | ✅ |
| 2.3.3 _recursive_crawl ≤50 行 | 37 行（含 docstring）；`_crawl_page_and_store` 45、`run_crawl` 48 | ✅ |
| 2.3.4 公开方法 docstring | 全部（含私有新方法） | ✅ |
| 2.3.5 无空 catch | 所有 except 均有日志+计数 | ✅ |
| 2.3.6 无硬编码魔法数字 | 深度/链接上限走 config；`_FILENAME_SEGMENT_MAX=50`、`CRAWL_DEPTH_API_MAX=5` 命名常量 | ✅ |
| 2.3.7 _matches_any 不再死代码 | 调用点：`_is_blacklisted_url`（种子+递归）+ `_recursive_crawl` 白名单判定 | ✅ |

## 4. 铁律合规检查

| 铁律 | 状态 | 证据 |
|------|------|------|
| 1. 编码前先产出 plan.md + acceptance-criteria.md | ✅ | 两份文档均存在且内容完整；changelog 记录 plan v1→v2 代码实证核实重写（2026-08-26），先计划后编码 |
| 2. 一次一个 module-XXX；新增生产代码 ≤200 行 | ✅ | 改动仅限本模块 5 文件；AST 独立复核 ~118-158 行 < 200（changelog 报 158，差异为计数口径，均远低于上限） |
| 3. 方法 ≤50 行、类 ≤500 行 | ✅ | `_recursive_crawl` 37 行、`_crawl_page_and_store` 45 行、`run_crawl` 48 行、`_extract_links` 27 行、`_normalize_url` 19 行（均含 docstring，物理行口径）；CrawlResult/CrawlSummary 数据类极小 |
| 4. public/导出方法必须有 Docstring | ✅ | `run_crawl`/`_load_sources_from_db`/`fetch_page`/`_review_content` 等公开方法及全部新私有方法均有 docstring |
| 5. 严禁空 catch/吞异常 | ✅ | 逐处核查：`_crawl_page_and_store`（2 处 except→warning+计数）、`_recursive_crawl`（except→warning+errors++）、`_normalize_url`（ValueError→fail-open 原样返回，文档声明）、`fetch_page`（3 类 except→CrawlResult.error）、`_load_sources_from_db`/`_scheduled_crawl_job`/`start_scheduler` 均有日志 |
| 6. 严禁跨层/反向/循环依赖 | ✅ | crawler 仅依赖 src.config / src.database / rag.retrieval.document_ingest / agent.reflector / factcheck_judge（函数级懒加载，module-075 同款模式），无新增依赖环 |
| 7. 禁 SQL 拼接、禁硬编码密钥 | ✅ | main.py INSERT 用 `text()` 参数化（:url/:name/:depth）；database.py DDL 为静态字符串；无任何密钥硬编码 |
| 8. INFO 日志含摘要；异常含 request_id | ✅ | INFO 摘要：`run_crawl` 批次完成行（crawled/approved/rejected/errors/skipped）、调度器启动行等；request_id 由 module-058 `TraceIdFilter`（src/observability.py:76 + main.py:63）全局注入日志格式 `%(trace_id)s`，异常日志在请求上下文中自动带 trace_id（调度器场景无请求上下文为空串，与 075 约定一致） |
| 9. 所有新方法有 docstring | ✅ | `_normalize_url`/`_extract_links`/`_crawl_filename`/`_blacklist_patterns`/`_is_blacklisted_url`/`_crawl_page_and_store`/`_recursive_crawl` 全部具备 |

## 5. 审查总结

**结论：✅ 通过。**

module-076 实现与 plan.md（v2）/ acceptance-criteria.md 高度一致，且**全部实测核验通过**，非仅凭 changelog 声明：

1. **核心引擎正确**：`_recursive_crawl` 深度语义（种子=0，`depth > max_depth` 截断）、visited 去重池（`run_crawl` 全树跨源共享、循环 A→B→A 自断）、总页数上限全树共享计数（`len(visited) >= limit`，黑名单 URL 不入池不计数）均与设计一致，并有单测逐一锁定。
2. **module-075 遗留闭环**：`_matches_any` 获得两个真实调用点（`_is_blacklisted_url` 种子+递归统一过滤、递归白名单边界），不再是死代码；黑名单配置来源落实为 config `crawl_blacklist_patterns`（默认空串向后兼容）。
3. **向后兼容性扎实**：config 三项新配置均有默认值；DB 列 `DEFAULT 1` 存量行兜底；`_load_sources_from_db` 对 5 列旧行兜底 1（单测锁定）；`int(x or 1)` 的 `0 or 1` 陷阱已修复（`max_depth=0` 逃生口有效）；POST 缺省 1、0-5 校验 code=1；run 响应结构不变。
4. **安全与健壮**：纯正则链接提取（防 XXE、零新依赖）、`_is_safe_url` 对递归链接同样生效、三层防递归爆炸（深度 2 + 单页 20 链接 + 总页数 10）、全链路 fail-open（抓取/审查/入库任一失败不阻断树）。
5. **测试充分**：33 项单测覆盖验收矩阵全部场景（功能/边界/异常），外加 filename/黑名单解析/DB 加载等防御性测试；存量 30 项零回归；py_compile + import main 全过。
6. **DDL 幂等**：`ADD COLUMN IF NOT EXISTS` 模式对齐 superseded/review_status 同款，init_db 挂接完成。

**2 项低危观察（不阻断，建议下轮或直接修复）**：
- crawler.py:366-367 `int(raw_depth)` 对非法值无防护，建议 try/except 兜底 1（fail-open 哲学）。
- crawler.py:93+369 url_pattern 带尾斜杠时裸根链接被白名单前缀误弃，属前缀匹配固有边界，建议遗留清单如实声明。

**验证口径说明**：验收命令为 `git diff --numstat` 对比 f143c80，但本地工作树 module-075 尚未提交（rag/crawl/、tests/crawl/ 均为 untracked），changelog 已如实改用 AST 口径并披露原因；本审查独立 AST 复核（~118-158 行）确认 ≤200 行达标，口径差异不构成问题。
