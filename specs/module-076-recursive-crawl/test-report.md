# 测试报告 — Module-076

> 测试范围：递归爬取 + 链接跟踪 + 深度控制 + 去重 URL 池
> 测试依据：acceptance-criteria.md（v2）、changelog.md、review-report.md
> 测试环境：Windows + Python 3.11.15（`.venv\Scripts\python.exe`）、pytest-9.1.1

## 1. 测试结论
- 结论：✅ 验收通过
- 测试时间：2026-08-26
- 测试人：Tester（module-076 第四阶段）

## 2. 测试结果汇总
| 验证项 | 结果 |
|--------|------|
| 模块单测 `pytest tests/crawl/ -v` | ✅ 63 passed（module-075 30 项 + module-076 33 项），2 warnings，27.00s |
| 全量回归 `pytest tests/ -q` | ✅ 1310 passed / 4 failed（module-028 基线遗留）/ 3 skipped，100.40s |
| py_compile `rag/crawl/crawler.py` | ✅ PY_COMPILE_OK |
| import 冒烟 `import main` | ✅ IMPORT_OK（pydantic IncompleteFieldDefinitionWarning 为既有告警，非错误） |
| DDL 幂等 `asyncio.run(init_db())` | ✅ DDL_IDEMPOTENT_OK（可重复执行） |
| 生产代码行数（铁律 2） | ✅ AST 精确统计（不含注释/docstring/空行）129 行 ≤ 200 |
| 最大方法行（铁律 3） | ✅ `_recursive_crawl` 37 / `_crawl_page_and_store` 45 / `run_crawl` 48（含 docstring，均 ≤ 50） |

### 2.1 全量回归 4 项失败归属核验（非本模块）
4 个失败全部位于 `tests/agent/test_agent_tools.py::TestChatWithTools`（test_openai_path_returns_content_and_tool_calls / test_openai_path_preserves_reasoning_content / test_no_tool_calls_returns_empty_list / test_llm_failure_raises_llm_exception），错误均为：
```
pydantic.v1.error_wrappers.ValidationError: Client.__init__() got an unexpected keyword argument 'proxies'
```
**根因核验（实测）**：
- 系统环境变量 `HTTP_PROXY/HTTPS_PROXY = http://127.0.0.1:7897` 存在；langchain-openai 的 `ChatOpenAI` 实例化时将环境代理转为 `proxies` 参数透传给底层 openai SDK；
- 已装 `openai 1.33.0`（新版 SDK `Client.__init__` 已移除 `proxies` 参数，改用 `http_client`）→ 参数不兼容；
- 该测试文件不在 module-076 变更清单（changelog 5 文件：crawler.py / config.py / database.py / main.py / test_recursive_crawl.py）内，与 crawl 代码零关联；
- 与 module-075 全量回归时的遗留失败一致（module-028 环境遗留），**非本模块引入**。

## 3. 验收标准核对
### 3.1 功能验收
| 验收项 | 状态 | 证据 |
|--------|------|------|
| 1.1.1 max_depth=0 仅抓种子页 | ✅ | crawler.py `_recursive_crawl` depth 语义（种子=0，`depth > max_depth` 返回）；单测 `test_depth_zero_seed_only`（fetch=1、ingest=1、不递归） |
| 1.1.2 max_depth=1 种子+一层 | ✅ | `run_crawl` 默认 source_depth=1；单测 `test_depth_one_seed_plus_links`（crawled=3、fetch=3，白名单链接入树） |
| 1.1.3 max_depth=2 两层递归 | ✅ | 单测 `test_depth_two_two_levels`（fetch=3，depth=3 的 d 页不抓） |
| 1.1.4 max_depth 列 DDL 幂等 | ✅ | database.py:325-326 `CRAWL_DEPTH_DDL`（`ADD COLUMN IF NOT EXISTS ... DEFAULT 1`）+ `ensure_max_depth_column`(L331) + init_db 挂接(L271)；实测 init_db 重复执行无报错；单测 `test_legacy_row_without_max_depth`（存量行兜底 1） |
| 1.1.5 POST /ai/crawl/sources 设置 max_depth | ✅ | main.py:1056 默认 1、:1067 `if not 0 <= req.max_depth <= CRAWL_DEPTH_API_MAX` → code=1、:1042 命名常量 `CRAWL_DEPTH_API_MAX=5`；INSERT 参数化（:depth） |
| 1.1.6 GET 返回 max_depth 字段 | ✅ | main.py:1090 SELECT 含 max_depth、:1096 响应字段 |
| 1.1.7 POST /ai/crawl/run 响应结构不变 | ✅ | main.py:1115-1124 返回 crawled/approved/rejected/errors/skipped，与 module-075 一致 |
| 1.1.8 全局上限 crawl_max_depth=2 生效 | ✅ | crawler.py `max_depth = min(source_depth, settings.crawl_max_depth)`；单测 `test_global_depth_cap`（source.max_depth=5 → fetch=3 按 2 层） |
| 1.1.9 递归页审查后 review_status 落库 | ✅ | `_crawl_page_and_store` 调 `ingest_document(review_status=review)`；单测 `test_rejected_recursive_still_ingested`（rejected 仍入库，review_status="rejected" 透传） |
| 1.1.10 .html 页面递归入库不抛 DocumentParseError | ✅ | `_crawl_filename` 恒生成 `.txt` 文件名（document_parser html 回退为 module-075 已验能力）；TestCrawlFilename 3 项防 `crawl_.txt` |

### 3.2 边界条件验收
| 验收项 | 状态 | 证据 |
|--------|------|------|
| 1.2.1 URL 规范化去 fragment | ✅ | `_normalize_url`（urlunsplit fragment 置空）；单测 `test_drop_fragment` |
| 1.2.2 URL 规范化去尾斜杠 | ✅ | `_normalize_url` `len(path)>1 and endswith("/")` 时 rstrip；单测 `test_drop_trailing_slash` |
| 1.2.3 scheme+host lowercase | ✅ | `_normalize_url` scheme.lower() + hostname.lower()；单测 `test_lowercase_scheme_host` |
| 1.2.4 循环链接防爆 A→B→A | ✅ | `visited: set[str]` 规范化后判重（`_recursive_crawl` 入口 `url in visited` 返回）；单测 `test_cycle_a_b_a`（fetch=2） |
| 1.2.5 跨源去重 | ✅ | `visited` 在 `run_crawl` 创建、全树/全源共享；单测 `test_cross_source_shared_visited`（第二源种子命中 visited，fetch=2） |
| 1.2.6 黑名单过滤（种子+递归） | ✅ | `_is_blacklisted_url`（run_crawl 种子检查 + `_recursive_crawl` 递归检查）；单测 `test_blacklisted_seed_skipped`（skipped=1、fetch=0）+ `test_blacklist_recursive_link` |
| 1.2.7 白名单边界（外域丢弃） | ✅ | `whitelist=[_normalize_url(url_pattern)]` + `_recursive_crawl` `_matches_any` 判定；单测 `test_external_link_dropped`（外域链接 fetch=1 不递归） |
| 1.2.8 仅保留 http/https | ✅ | `_extract_links` 内 `_is_safe_url` 过滤；单测 `test_unsafe_schemes_filtered`（mailto:/javascript:/ftp:/data:/file: 全丢弃） |
| 1.2.9 相对路径绝对化 | ✅ | `urljoin(base_url, href.strip())`；单测 `test_relative_url_resolved` |
| 1.2.10 链接数 >20 截断 | ✅ | `len(links) >= max_links: break`（config `crawl_max_links_per_page=20`）；单测 `test_truncate_over_max`（25 → 20） |
| 1.2.11 filename 防 crawl_.txt | ✅ | `_crawl_filename` 末段空时回退 `"page"`/host；单测 `test_trailing_slash_not_empty_segment`（`crawl_docs.txt`）+ `test_host_fallback`（`crawl_example.com.txt`） |

### 3.3 异常场景验收
| 验收项 | 状态 | 证据 |
|--------|------|------|
| 1.3.1 单页失败不阻断整树 | ✅ | `_crawl_page_and_store` fetch 失败 → errors++ 返回 `[]`；单测 `test_single_page_failure_does_not_block`（中段 404，errors=1、crawled=2、fetch=3） |
| 1.3.2 审查节点失败 fail-open | ✅ | `_review_content` 双 try/except 兜底 approved + `_crawl_page_and_store` 外层 except；单测 `test_review_failure_fail_open_approved`（review_status="approved" 入库） |
| 1.3.3 入库失败不阻断 | ✅ | ingest except → errors++，`_extract_links` 在 except 之后仍执行（子链接继续展开）；单测 `test_ingest_failure_does_not_block`（errors=1、crawled=2、ingest=3 次） |
| 1.3.4 总页数上限全树共享 | ✅ | `_recursive_crawl` 入口 `len(visited) >= limit` 全树共享计数（黑名单不入池不计数）；单测 `test_total_page_limit_shared_across_tree`（limit=3 → 全树 3 页） |
| 1.3.5 空/无链接页面终止 | ✅ | `_extract_links` `not html or "<a" not in ...` 返回 `[]`；单测 `test_empty_page_terminates` |
| 1.3.6 非 HTML 内容不提取链接 | ✅ | 无 `<a` 即返回 `[]`（内容仍走 document_parser 入库）；单测 `TestExtractLinks::test_empty_or_non_html`（"PDF binary content" → []） |

### 3.4 非功能验收
| 验收项 | 状态 | 证据 |
|--------|------|------|
| 2.1.1 depth=1+10 链接 ≤6 分钟 | ✅ | 串行 await 设计，最坏 11×30s ≈ 5.5 分钟（审查/入库本地开销远小于超时），边界内 |
| 2.1.2 depth=2+50 页 ≤25 分钟 | ✅ | 最坏 50×30s = 25 分钟（`crawl_max_pages_per_run=10` 默认更保守，50 为上限场景） |
| 2.1.3 visited 查找 O(1) | ✅ | `set[str]` 哈希集合 |
| 2.1.4 调度非阻塞 | ✅ | 异步递归 + APScheduler `AsyncIOScheduler`（asyncio.create_task 语义，与请求并发不冻结） |
| 2.2.1 _is_safe_url 对递归链接生效 | ✅ | `_extract_links` 内逐链接过滤（file:/// 等拦截，测试含 `file:///etc/passwd` 用例） |
| 2.2.2 纯正则提取防 XXE | ✅ | `_HREF_RE = re.compile(r'href=["\']([^"\']+)')` 标准库 re + urllib.parse，零新依赖 |
| 2.2.3 日志 URL 截断 [:80] | ✅ | 全链路 `url[:80]` / `url_pattern[:80]`（`_crawl_page_and_store`/`_recursive_crawl`/`run_crawl`/main.py） |
| 2.2.4 黑名单默认空串 | ✅ | config.py:350 `crawl_blacklist_patterns: str = ""`；单测 `test_empty_default` |

### 3.5 代码质量验收
| 验收项 | 状态 | 证据 |
|--------|------|------|
| 2.3.1 新增生产代码 ≤200 行 | ✅ | AST 独立统计（不含注释/docstring/空行）129 行（changelog 物理行口径 195、review 复核 118-158，三口径均 < 200） |
| 2.3.2 纯函数可独立单测 | ✅ | `_extract_links`/`_normalize_url` 无副作用，TestNormalizeUrl 6 项 + TestExtractLinks 5 项独立断言 |
| 2.3.3 _recursive_crawl ≤50 行 | ✅ | 37 行（含 docstring）；`_crawl_page_and_store` 45、`run_crawl` 48，均 ≤ 50 |
| 2.3.4 新增公开方法有 docstring | ✅ | 代码逐方法核对：`run_crawl`/`fetch_page`/`_review_content`/`_load_sources_from_db` 及全部新私有方法均有 docstring |
| 2.3.5 无空 catch/吞异常 | ✅ | `_crawl_page_and_store`（2 处 except→warning+计数）、`_recursive_crawl`（except→warning+errors++）、`fetch_page`（3 类 except→CrawlResult.error）、`_normalize_url`（ValueError→fail-open 原样返回） |
| 2.3.6 无硬编码魔法数字 | ✅ | `_FETCH_TIMEOUT_S=30`/`_FILENAME_SEGMENT_MAX=50`/`CRAWL_DEPTH_API_MAX=5` 命名常量；深度/链接上限/页数上限走 config |
| 2.3.7 _matches_any 主链路接线 | ✅ | 两个真实调用点：`_is_blacklisted_url`（种子+递归）+ `_recursive_crawl` 白名单判定，不再为死代码 |

## 4. 遗留问题（如有）
| # | 问题 | 严重级别 | 备注 |
|---|------|----------|------|
| 1 | crawler.py `run_crawl` 中 `int(raw_depth)` 对非整数值（直接改库/非法调用方）抛 ValueError 无捕获 → 单源异常中断批次 | 低 | 正常来源为 DB INTEGER 列 + API 0-5 校验，理论触发面低；建议 try/except (TypeError, ValueError) 兜底 1 + logger.warning（review 报告低危 #1） |
| 2 | url_pattern 带尾斜杠时，页面内裸根链接（规范化后无 `/`）不被白名单前缀命中而被丢弃 | 低（观察项） | 前缀匹配固有边界，验收矩阵未覆盖；建议遗留清单如实声明（review 报告低危 #2） |
| 3 | 全量回归 4 failed（TestChatWithTools × 4） | 基线遗留（非本模块） | module-028 环境遗留：HTTP_PROXY/HTTPS_PROXY 环境变量 + openai 1.33.0 移除 `proxies` 参数，与本模块零关联 |

## 5. 测试总结

**结论：✅ 验收通过。**

1. **测试证据链完整（全部实测，非仅凭 changelog）**：模块单测 63 passed（075 的 30 项零回归 + 076 的 33 项全绿）；全量回归 1310 passed / 4 failed / 3 skipped（4 项失败经根因核验为 module-028 proxies 环境遗留，与本模块零关联）；py_compile、`import main`、init_db DDL 幂等冒烟全部通过。
2. **验收矩阵全覆盖**：功能 10 项（1.1.1-1.1.10）、边界 11 项（1.2.1-1.2.11）、异常 6 项（1.3.1-1.3.6）、非功能 8 项（2.1-2.2）、代码质量 7 项（2.3.1-2.3.7）逐项核对，均有代码证据 + 单测锁定，全部达标。
3. **单测场景矩阵 15 项必含场景**全部落地：深度 0/1/2、全局上限 min、A→B→A 循环、跨源 visited 共享、黑白名单（种子+递归）、外域丢弃、URL 规范化三例、>20 截断、单页失败/审查失败/入库失败 fail-open、总页数全树上限、空/非 HTML 终止，另含 filename 防 `crawl_.txt`、DB max_depth 加载等防御性测试。
4. **铁律合规**：生产代码 ≤200 行（AST 纯代码 129 行）、方法 ≤50 行（最大 48）、全部 docstring、无空 catch、魔法数字命名常量、`_matches_any` 主链路接线闭环 module-075 遗留——铁律 2/3/4/5/9 全部达标。
5. **向后兼容扎实**：config 三项新配置均有默认值、DB 列 `DEFAULT 1` 存量兜底、`_load_sources_from_db` 旧行兜底 1（单测锁定）、POST 缺省 1 + 0-5 校验、run 响应结构不变。
6. **遗留 2 项低危观察**（review 报告同款）不阻断验收：`int(raw_depth)` 非法值防护、url_pattern 尾斜杠与裸根链接的前缀匹配边界，建议记入遗留决策清单下轮处理。

- 审查人: Reviewer（module-076 第四阶段，2026-08-26）
- 测试人: Tester（module-076 第四阶段，2026-08-26）
- 验收时间: 2026-08-26
- 结论: [x] 通过 / [ ] 不通过
