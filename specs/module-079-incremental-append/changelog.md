# 变更记录 — Module-079: 增量 append 不重建路径验证（新增语料追加、无全量重嵌）

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本（Planner 全量代码审计：验收 1-4 已满足、验收 5 需加固 + backlog ① 修复） | Planner |
| v2 | 2026-08-26 | Developer 实现：find_semantic_duplicate 加固（pgvector SQL top-K + ndarray bug 根除 + fail-open）+ config 1 项 + 验收 1-5 测试锁定 | Developer |

## 1. 生产代码变更（验收 5 加固，唯一生产改动点）

### 1.1 `ai_service/rag/retrieval/document_dedup.py` — `find_semantic_duplicate` 重写

**问题**（Planner 审计 + Tester backlog ①）：
- 候选获取走 ORM 全表拉取根父块 embedding + Python 逐条 `_cosine` = **O(N)** 时间/内存；
  文档量级增长时每次入库全量传输 + 余弦。
- `if not emb`（原 :157）对 pgvector 0.2.5 返回的 **numpy ndarray** 抛
  `ValueError: truth value of an array is ambiguous`——`doc_dedup_semantic_enabled`
  默认 True 时真实入库语义去重受阻（module-078 Tester 冒烟发现）。

**修复**（对齐 crawler `_conflict_candidates` / retriever `_vector_search` 先例）：
1. 候选查询改为 pgvector SQL `ORDER BY embedding <=> :vec ASC LIMIT :k`
   （模块级常量 `_SEMANTIC_DUP_SQL`）：`WHERE parent_id IS NULL AND embedding
   IS NOT NULL AND is_canonical IS true AND (source IS NULL OR source NOT LIKE 'memory:%')`，
   过滤条件与原 ORM 查询**逐字语义一致**；embedding 字符串绑定规避 asyncpg 类型编解码。
2. Python 只对 top-K 结果判余弦阈值（`1 - (embedding <=> :vec)` SQL 侧算好），
   不再全表逐条余弦 → **O(N) → O(log N + K)**。
3. **ndarray bug 结构性根除**：余弦由 SQL 计算，Python 不再对 embedding 做真值判定
   （无 `if not emb` / `if emb is None`），只判 `row["cosine"]` 数值。
4. 新增 fail-open：候选查询/判定失败（如 pgvector 维度不匹配）→ 日志 + 返回 None，
   不阻断入库（对齐全链路 fail-open 纪律；旧实现查询失败会向上抛）。
5. 返回契约不变：`{"id", "title", "cluster_id", "cosine"}` 或 None，
   `ingest_document` 调用方**零改动**。

**正确性论证**（top-K 截断不改变判定）：`ORDER BY embedding <=> :vec ASC` 按距离升序 =
余弦降序；全表存在 cosine ≥ 阈值（0.95）的候选必在前 K 高余弦内 → top-K 与全表扫描在
"是否存在 ≥ 阈值候选"上结果一致。默认 K=50 远超真实语义重复量级。

**行数**：`find_semantic_duplicate` 重写后 **49 行**（AST end_lineno-lineno+1，含签名与
docstring，≤ 50 铁律 ✓）；新增生产代码合计 ≈ 35 行（≤ 200 铁律 ✓，git diff 口径）。

### 1.2 `ai_service/src/config.py` — 新增 1 项配置

- `doc_dedup_candidate_top_k: int = 50` —— L2 语义去重向量候选上限（pgvector top-K，
  `ORDER BY embedding <=> :vec LIMIT :k`）；`PW_DOC_DEDUP_CANDIDATE_TOP_K` 可覆盖
  （实测 env=20 → 20 ✓）。默认 50 远超语义重复量级，防极端候选数。
- 其余配置不动：`doc_dedup_semantic_enabled`（True）/ `doc_dedup_threshold`（0.95）/
  `doc_dedup_boilerplate_enabled`（True）语义不变。

## 2. 测试变更

### 2.1 新增 `ai_service/tests/core/test_incremental_append.py`（plan 子任务 2，hermetic 全 mock）

| 测试组 | 对应验收 | 关键断言 |
|--------|---------|----------|
| 增量嵌入 | 验收 1 | `embed_documents` 只对新文档子块调用（await 次数=子块数、参数=新子块文本）；存量 2 篇零嵌入调用 |
| 增量嵌入 fail-open | 验收 1 | 嵌入服务抛异常 → `compute_doc_embedding` 返回 None → `doc_embedding=None` 仍入库成功（真实 fail-open 链路，mock 服务层） |
| 检索增量生效 | 验收 2 | add_document 提交后 `cache.delete_by_prefix("rag:retrieve:")` 被 await；`_vector_search` 候选 SQL 命中新子块（含 `parent_id IS NOT NULL` / `embedding IS NOT NULL` 断言） |
| 无全量重嵌 | 验收 3 | 追加仅 INSERT（新父块+新子块），零 UPDATE/DELETE；存量 embedding 逐字节不变；engine/ingest/dedup 三文件不引用 reindex/rebuild/backfill 脚本（源码级守卫）；ensure_graph + upsert_entity/upsert_relation 幂等追加 |
| 去重不破坏增量 | 验收 4 | 入库 A → 同内容再入库（L1 命中 duplicate 不写库、不落原件）→ 新文档 B 正常追加；add_document 内部 title/content_hash 兜底去重命中 → duplicate 且零嵌入 |
| 性能与 N 无关 | 验收 5 | 存量文档数 N=0 与 N=200 各跑一次入库，`embed_documents` 调用次数相同（=1） |

### 2.2 `ai_service/tests/core/test_document_dedup.py` 适配（plan 子任务 3）

- 行为断言**逐字保留**，仅 mock 形态适配新查询契约：`FakeScalars/FakeResult.scalars()`
  （ORM Document 对象）→ `FakeRow(dict) + FakeResult.mappings()`（SQL 行，cosine 预置）。
- SQL 捕获断言（排除 memory 源 / is_canonical 过滤）改为直接 `str(text())` 语句断言，
  语义不变。
- 新增：`test_semantic_duplicate_query_topk_limit`（`LIMIT :k` + `params["k"] ==
  settings.doc_dedup_candidate_top_k` 固定）、`test_semantic_duplicate_ndarray_cosine_no_valueerror`
  （np.float64 候选余弦不抛 ValueError，backlog ① 回归）、
  `test_semantic_duplicate_query_failure_fail_open`（查询失败 → None）。

### 2.3 `ai_service/tests/test_incremental_append.py`（并行会话遗留文件，适配修复）

- 该文件由并行会话/前序工作遗留（git 未跟踪），mock 旧 ORM 查询形态（`scalars()` +
  Document 候选），且含**重复函数名** `test_find_semantic_duplicate_with_none_candidates`
  （后者带错误断言 `dup["id"] == 42`）。
- 适配：`FakeResult`/`FakeMappingsResult` 增加 `mappings()` 契约；ndarray 候选测试改
  SQL top-K 行形态（cosine 预置）；删除重复定义与错误断言；`test_semantic_query_has_limit`
  改返回 `FakeMappingsResult([])`。当前该文件与并行会话的适配已合并一致（见 §4 撞车说明）。

## 3. 验证结果

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 定向单测 | `python -m pytest tests/ -v -k "dedup or incremental or append"` | **91 passed / 0 failed**（dedup 19 + core incremental 11 + 顶层 incremental 61） |
| py_compile | `python -c "import py_compile; py_compile.compile('rag/retrieval/document_dedup.py'); py_compile.compile('src/config.py')"` | OK |
| 配置生效 | `$env:PW_DOC_DEDUP_CANDIDATE_TOP_K="20"; python -c "from src.config import settings; print(settings.doc_dedup_candidate_top_k)"` | 20 ✓ |
| 行数 | AST `find_semantic_duplicate` end_lineno-lineno+1 | **49**（≤ 50 铁律 ✓） |
| 全量回归 | `python -m pytest tests/ -q` | 见 §3.1 |

### 3.1 全量回归

基线：1366 passed / 4 failed（module-028 langchain-openai proxies 环境性遗留）。
实际运行：**1396 passed / 4 failed / 3 skipped**（0 新增失败，净增 30 用例）。
4 failed 与基线同签名：`tests/agent/test_agent_tools.py::TestChatWithTools::test_openai_path_*`
（`Client.__init__() got an unexpected keyword argument 'proxies'`，module-028 遗留，已复跑归因确认）。

## 4. 撞车说明（并行会话协调，必须上报）

本模块开发期间发现**另一自主会话在同一 git 工作树并发编辑 module-079 相关文件**：
- `document_dedup.py` 在我开始前已被写入"module-079 `if emb is None` 修复"（partial fix）；
- `tests/test_incremental_append.py`（顶层）由该会话创建且在我适配期间**被再次改写**
  （edit 工具报 Drift，9 行外部漂移）。

处理：本实现按 plan 的 top-K 设计**整体重写** supersede 了 partial fix（`if emb is None`
被结构性消除）；顶层测试文件与并行会话的适配**合并一致**（双方改动兼容，测试全绿）。
已按 MEMORY 教训记录：多会话并行产出同一工作树存在真实撞车风险，后续应先 specs/ 声明式认领。

## 5. 遗留（决策清单，非阻塞）

1. **pgvector 索引确认**（plan 待澄清 2）：`documents.embedding` 列是否已有 pgvector
   向量索引（psql `\d documents`）——REVIEW 检查项；缺失则 top-K 查询退化为全扫
   （性能提升有限但不破坏正确性），记遗留、本模块不动 DDL。
2. **`doc_dedup_candidate_top_k` 默认值**（plan 待澄清 1）：取 50；如需更保守（20），
   仅改 config 一行。
3. 顶层 `tests/test_incremental_append.py` 与 `tests/core/test_incremental_append.py`
   覆盖有重叠（后者为 plan 指定文件、覆盖更全）；如 Reviewer 认为冗余可合并/删除前者
   （git 未跟踪，删除零风险）。
4. 顶层测试文件头部注释仍引用旧修复口径（"emb is None 修复回归"），与实际结构修复
   （SQL 侧余弦）表述有偏差——纯注释，行为断言均指向新契约。
