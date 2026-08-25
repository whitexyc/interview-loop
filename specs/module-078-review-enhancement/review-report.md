# 审查报告 — Module-078

审查人: Reviewer（module-078）
审查日期: 2026-08-26
审查对象: 审查节点增强（质量评分阈值校准 + 矛盾检测 + 审查策略强化）
审查范围: `_review_content` / `_check_conflict` / `ReviewResult` / review_score 四层透传 / 配置项 / 测试

## 1. 审查结论

- 结论：✅ **通过**（附 4 项 minor 修复建议，均不阻塞验收；无 P0/P1 级问题）

实现与 plan.md / acceptance-criteria.md 逐项对齐：三档策略语义正确、矛盾检测链路（embed → 向量候选 → memory_conflict_judge 选型 → dual 双确认 + 对称回退）实现完整且全 fail-open、`ReviewResult(str)` 桥接零回归、review_score 四层透传完整、配置向后兼容、测试 28 项全绿（实测）。

## 2. 问题列表（如有）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `ai_service/src/database.py` | 321-324 | **`ensure_review_status_column`（module-075 函数）尾部被意外复制了一段完整执行块**：module-078 的 diff 在 `ensure_review_status_column` 内重复粘贴了 `async with async_session_factory() ... commit()` 整块，导致每次启动对 review_status DDL 执行两遍。幂等 ALTER 无功能影响，但属明确编辑错误进入生产文件，且与其他 `ensure_*` 函数结构不一致 | 中 | 删除 321-324 行重复块，恢复与其他 `ensure_*` 一致的函数体 |
| 2 | `ai_service/rag/crawl/crawler.py` | 350-351 + 374 | **嵌入失败被误记为"矛盾命中"日志**：`_check_conflict` 在 embed 失败时返回 `{"conflict": False, "detail": "嵌入失败"}`（374 行），而 `_review_content` 的"矛盾命中"日志仅以 `conflict_detail` 非空为门（350 行），输出"矛盾命中: 嵌入失败"——conflict=False 却被标记为矛盾命中，日志语义失真（AC 1.5 要求矛盾命中日志含候选 id/标题/判定器，本场景无候选） | 低 | 二选一：① `_check_conflict` 嵌入失败时返回 `detail=""`；② 350 行改为 `if conflict and conflict_detail:` |
| 3 | `ai_service/main.py` | 1113 | **无启用的源配置早退分支响应 data 缺 `conflict` 字段**：正常路径（1125 行）含 `"conflict": summary.conflict_count`，早退分支（"无启用的源配置"）data 仅 crawled/approved/rejected 三项——AC 1.4"run 响应 data 含 conflict 计数"在早退分支不满足，前端读 `data.conflict` 得 undefined | 低 | 早退分支补 `"conflict": 0` |
| 4 | `ai_service/rag/crawl/crawler.py` | 568-569 | **`_crawl_page_and_store` 外层异常兜底恒 `review = "approved"`（与 policy 无关）**：strict 档若 `_review_content` 意外抛异常（当前内部已全捕获，实际不可达）会泄漏为 approved，与 strict fail-closed 语义相悖 | 低 | 兜底按 `settings.crawl_review_policy` 区分（strict → "rejected"），或加注释声明为防御性兜底（`_review_content` 内部已 fail-open，此分支仅兜意外） |

**观察项（不阻塞，建议记录）**：

| # | 文件 | 说明 |
|---|------|------|
| O1 | `crawler.py:390` `_conflict_candidates` | 候选 SQL 未排除记忆行（`source LIKE 'memory:%'`）：旧格式记忆文档（parent_id NULL + embedding NOT NULL，见 `memory.py` 复制/升级路径）可能进入矛盾候选池，与新抓取网页做矛盾判定。需 cosine ≥ 0.6 才触发，实际概率低，且与 AC 1.3 字面（仅 parent_id IS NULL + embedding 非空）一致。建议对齐 retriever 语义补 `AND (source IS NULL OR source NOT LIKE 'memory:%')` |
| O2 | `crawler.py:305` `_review_content` | strict 档下 HHEM 不可用（`hhem_judge.predict` 内部吞异常返回 None，不抛异常）不会触发 fail-closed 拒绝——score=NULL、不拒绝。AC 1.2"审查异常 → rejected"与"模型缺失不阻断"存在语义模糊地带，实现与 AC 字面一致，可接受，建议 changelog 如实声明 |
| O3 | `crawler.py:305` `_review_content` | 被充分性拒绝的文档短路跳过 HHEM（`if status == "approved"` 门控），review_score=NULL 语义为"未评分"而非"HHEM 不可用"。诚实且省一次推理，可接受，建议注释说明 |
| O4 | 基线同步 | HEAD（bc7eb5e module-076 收口）的 `ingest_document`/`add_document`/`models.py` 均无 review_status 参数/列，但 crawler 已调用 `review_status=...`（HEAD 状态 crawl 入库路径会 TypeError → 被捕获为 ingest error）。module-078 工作树一并补齐四层（review_status + review_score）。非本模块引入（028b266 基线同步缺三处文件），建议 changelog 如实记录 |

## 3. 验收标准核对

### 1. 功能验收

| 验收项 | 对应代码 | 状态 |
|--------|----------|------|
| 1.1 阈值默认 0.3 + PW_ 环境变量覆盖 + 进程内动态调整 | `src/config.py:362`（`crawl_hhem_threshold=0.3`，env_prefix=PW_）；`crawler.py:306-307`（阈值读 config 不硬编码）；测试 `test_threshold_raised_changes_verdict`（0.3→0.5 后 score=0.4 由 approved 变 rejected，单测锁定） | ✅ |
| 1.1 score < 阈值 → rejected；≥ 阈值不因分拒 | `crawler.py:326-327`（`if score < threshold: status = "rejected"`） | ✅ |
| 1.2 fail-open（默认）：审查异常 → approved，零回归 | `crawler.py:317-319`（reflector 异常）、333-335（hhem 异常）：仅 strict 置 rejected，fail-open/lenient 保持 approved；测试 `test_fail_open_exception_approved` | ✅ |
| 1.2 lenient：矛盾 → rejected；异常仍放行 | `crawler.py:344-345`（`if conflict and policy in ("lenient", "strict")`）；测试 `test_lenient_conflict_rejected` / `test_lenient_exception_approved` | ✅ |
| 1.2 strict：矛盾 → rejected；异常 → rejected；strict 阈值 | `crawler.py:344-345` + 307（`crawl_hhem_threshold_strict`）+ 测试 `test_strict_conflict_rejected` / `test_strict_exception_rejected` / `test_strict_uses_strict_threshold` | ✅ |
| 1.2 三档 PW_ 切换 + 非法值 fail-fast | `src/config.py:361`（`Literal["fail-open","lenient","strict"]` 启动即 ValidationError，实测 `PW_CRAWL_REVIEW_POLICY=bogus` 报错） | ✅ |
| 1.3 矛盾命中 → lenient/strict rejected、fail-open 仅记录 | `crawler.py:344-345` + `conflict_count` 独立计数（85 行）+ `CrawlSummary`；测试 `test_fail_open_conflict_only_recorded` / `test_run_crawl_conflict_count` | ✅ |
| 1.3 判定器复用 memory_conflict_judge（nli/clf/dual 不重写） | `crawler.py:422-445` `_judge_conflict` 仅调用 `_nli_contradicts` / `_clf_contradicts`（内部惰性导入 `nli_judge` / `memory_conflict_clf`），零重写 | ✅ |
| 1.3 dual 双确认 + 对称回退 | `crawler.py:433-443`（双确认 `nli_hit and clf_hit`；nli 不可用 → clf 单判 / clf 不可用 → nli 单判 / 双不可用 → (False, "dual")）；测试 5 项全覆盖 | ✅ |
| 1.3 候选：根父块 + embedding 非空 + cosine ≥ 0.6 + top-K=3 | `crawler.py:390-417`（SQL `WHERE parent_id IS NULL AND embedding IS NOT NULL ORDER BY embedding <=> :vec LIMIT :k` + Python `float(r[3]) >= min_cosine` 过滤）；测试 `test_candidates_filtered_by_cosine`（0.59 丢弃、SQL 断言） | ✅ |
| 1.3 模型缺失/None/嵌入失败/异常不阻断 | `crawler.py:356-386` 全 fail-open（`_nli_contradicts`/`_clf_contradicts` 异常 → None；`_check_conflict` 异常 → `{"conflict": False}`）；测试 `test_embed_failure_fail_open` / `test_dual_both_unavailable_skip` | ✅ |
| 1.4 documents 新增 `review_score FLOAT` 列（幂等 ALTER） | `src/database.py:330-334`（REVIEW_SCORE_DDL `ADD COLUMN IF NOT EXISTS`）+ 336-341（ensure）+ 273-274（init_db 挂接） | ✅ |
| 1.4 HHEM 不可用 → NULL | `crawler.py:323-328`（predict 返回 None → score 保持 None）；测试 `test_hhem_unavailable_score_none` | ✅ |
| 1.4 四层透传（默认 None 向后兼容） | `crawler.py:571-575`（层1→2 `_crawl_page_and_store` → `ingest_document(review_score=...)`）→ `document_ingest.py:88,194`（层2→3 → `add_document(review_score=...)`）→ `engine.py:1114,1209,1242`（层3→4 父块+子块 `Document(review_score=...)`）→ `models.py:118-121`；全部默认 None；测试 3 层 mock 验证 | ✅ |
| 1.4 run 响应 data 含 conflict + details 含 review_score/conflict | `main.py:1125`（`"conflict": summary.conflict_count`）+ `crawler.py:577-578`（details 补 review_score/conflict）；测试 `test_run_endpoint_includes_conflict` / `test_crawl_page_to_ingest`（**早退分支 1113 行缺 conflict，见问题 #3**） | ✅* |
| 1.5 每次审查一行结构化日志 | `crawler.py:348-349`（url/status/score/sufficient/conflict/policy/elapsed_ms）；测试 `test_review_log_line_structured` | ✅ |
| 1.5 矛盾命中日志含 id/标题/判定器 | `crawler.py:351` + detail 构造（378-379 行）；测试断言 "id=5" / "dual"（**嵌入失败误标为矛盾命中，见问题 #2**） | ✅* |

### 2. 非功能验收

| 验收项 | 对应代码 / 证据 | 状态 |
|--------|-----------------|------|
| 2.1 单页审查额外耗时 ≤ 10s / 总耗时 ≤ 60s / 页数上限不变 | 设计预算 1 次 embed + ≤3 次判定（top-K=3），异常即跳过；`crawl_max_pages_per_run=10` 不变。**真实热态耗时未实测**（conftest 钉住 memory_conflict_enabled=false，无真实模型冒烟），留待 Tester 真机验证 | ⏳ |
| 2.2 矛盾检测异常不阻断入库 | `_check_conflict` 全 fail-open（356-386 行） | ✅ |
| 2.2 embedding NULL 行不报错 | SQL `WHERE embedding IS NOT NULL`（398 行） | ✅ |
| 2.2 strict 仅在显式切换时生效 | 默认 `crawl_review_policy="fail-open"`（config.py:361），strict 需 `PW_CRAWL_REVIEW_POLICY=strict` | ✅ |
| 2.3 新增生产代码 ≤ 200 行（AST 口径） | **实测 AST ≈120 语句**（`_review_content` 40 + `_check_conflict` 18 + `_conflict_candidates` 9 + `_judge_conflict` 14 + `_nli_contradicts` 7 + `_clf_contradicts` 8 + `ReviewResult` ~12 + config 5 + database ~10 + models/ingest/engine/main 透传 ~16），≤ 200 ✓ | ✅ |
| 2.3 单方法 ≤ 50 行 | 实测 AST 语句数：`_review_content` 40 / `_check_conflict` 18 / `_conflict_candidates` 9 / `_judge_conflict` 14 / `_crawl_page_and_store` 35，均 ≤ 50（物理行 `_review_content` 48 亦 ≤ 50） | ✅ |
| 2.3 新公开方法有 docstring | `ReviewResult` / `_review_content` / `_check_conflict` / `_conflict_candidates` / `_judge_conflict` / `_nli_contradicts` / `_clf_contradicts` / `_crawl_page_and_store` 全部有 docstring | ✅ |
| 2.3 无空 catch / 吞异常 | 所有 except 均记录日志（crawler.py:317/333/382/452/463；`_nli_contradicts`/`_clf_contradicts` 返回 None 前先 warning） | ✅ |
| 2.3 复用不重写 | reflector / hhem_judge / nli_judge / memory_conflict_clf / embedding_service 全为惰性导入调用，零重写（git diff 确认这些文件未改动） | ✅ |

### 3. 可运行验证（实测）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 新增单测 | `pytest tests/crawl/test_review_enhancement.py -v` | **28 passed, 0 failed（实测）** |
| crawl 全量 | `pytest tests/crawl/ -q` | **91 passed（63 存量 + 28 新增）, 0 failed（实测）** |
| py_compile | `python -m py_compile` 7 个改动文件 | **exit 0 无报错（实测）** |
| 全量回归 | `pytest tests/ -q` | 后台运行中，changelog 声称 1338 passed / 4 个 langchain-openai `proxies` 基线遗留（module-028 环境性）——最终结果见报告末尾补充 |
| 阈值/策略配置 | `PW_CRAWL_HHEM_THRESHOLD=0.5` / `PW_CRAWL_REVIEW_POLICY=strict` | changelog 声称实测生效（pydantic-settings env_prefix=PW_ 机制确认） |

## 4. 铁律合规检查

| 铁律 | 检查结果 |
|------|----------|
| 1. 编码前先产出 plan.md + acceptance-criteria.md | ✅ 两文件均存在且内容完整（plan 含模块拆分/技术方案/风险/预算/遗留决策；AC 含功能+非功能验收+验证命令） |
| 2. 一次一个 module-XXX；新增生产代码 ≤ 200 行 | ✅ 仅增强审查节点，未动抓取/递归/入库主链路结构；AST 口径 ≈120 语句 ≤ 200 |
| 3. 方法 ≤ 50 行 | ✅ 新方法 AST 语句数与物理行数均 ≤ 50 |
| 4. public/导出方法必须有 docstring | ✅ 全部具备（含 `ReviewResult` 类级 + 方法级） |
| 5. 严禁空 catch/吞异常 | ✅ 所有 except 均带 logger 记录；`_nli_contradicts`/`_clf_contradicts` 失败返回 None 前先 warning |
| 6. 禁硬编码密钥 | ✅ 本模块新增配置无任何密钥；阈值/策略/候选参数全部进 config |
| 7. review_score 四层透传完整性 | ✅ crawler → ingest_document → add_document → Document ORM（父块+子块），全链路默认 None 向后兼容（git diff + 3 层 mock 测试双重验证） |

**额外核查**：
- `ReviewResult(str)` 桥接正确性：`str.__new__(cls, status)` + 属性赋值，值比较 `== "approved"` 零回归（存量测试断言 `result == "approved"` 兼容）；`_crawl_page_and_store` 对普通字符串返回（`getattr` 兜底）兼容 ✓
- 向量字符串绑定先例：`_conflict_candidates` 的 `f"[{','.join(str(v) for v in vec)}]"` 字符串绑定与 `retriever._vector_search`（retriever.py:830-834 同款写法，生产已验证）一致，规避 asyncpg 类型编解码 ✓
- 矛盾检测门控决策（changelog 补充项）：受 `memory_conflict_enabled` 主开关门控，conftest autouse 钉住 false 保证 module-075/076 存量测试 hermetic（conftest.py:341-357 `default_crawl_disabled` + `default_memory_conflict_disabled` 确认）✓

## 5. 审查总结

**总体评价**：module-078 是高质量实现。核心三件套——策略三档（fail-open 零回归 / lenient / strict fail-closed）、矛盾检测（embed → 根父块向量候选 → memory_conflict_judge 选型 → dual 双确认 + 对称回退，全链路 fail-open）、review_score 四层透传——均与 plan/AC 逐字对齐；`ReviewResult(str)` 桥接巧妙解决"存量字符串比较零回归 + 新结构化消费"双需求；阈值配置化与 Literal fail-fast 对齐既有先例；28 个新单测覆盖验收矩阵主路径（阈值动态调整、三档判定、dual 双确认/回退、候选余弦过滤、四层透传、日志断言），实测 28/28 与 crawl 全量 91/91 全绿，py_compile 7 文件通过。

**不通过理由不存在**。4 项 minor 建议（问题 #1-4）中，#1（database.py 重复执行块）为 diff 编辑事故应尽快清理，#2/#3 为日志/API 一致性小修，均可低成本修复；修复后重跑 `tests/crawl/` 即可确认零回归。

**遗留提示**：
- AC 2.1 性能预算（单页审查 ≤10s 热态）未做真实模型冒烟验证（conftest 钉住开关），建议 Tester 在真实环境（PG + bge-m3 + nli_judge/memory_conflict_clf 热态）下触发一次 `/ai/crawl/run` 验证耗时与日志字段
- 观察项 O1-O4 建议记入 changelog/遗留清单，由用户决策是否采纳（记忆行排除、strict+HHEM 不可用语义等）



**补充（全量回归实测结果）**：`pytest tests/ -q` 实测 **1338 passed, 3 skipped, 4 failed**（110.74s）——与 changelog 声明逐字一致。4 个失败全部为 `tests/agent/test_agent_tools.py::TestChatWithTools` 的 `ChatOpenAI ... got an unexpected keyword argument 'proxies'`（langchain-openai 版本兼容性，module-028 环境性基线遗留，复测确认），与 module-078 改动零关联。
