# 开发计划 — Module-079: 增量 append 不重建路径验证（新增语料追加、无全量重嵌）

## 1. 需求描述

- 需求来源: ADR-0019 决策 3（用户 2026-08-24 拍板："复用 documents 表 upsert 路径，新增语料直接追加，不做全量重嵌/重建图——立刻省钱"）+ ADR-0019 验收标准第 3 项（阶段 3：增量 append 不重建路径验证）
- 功能描述: **验证型模块**——逐项核实现有入库链路（`ingest_document` → `add_document`）是否天然满足"增量 append 不重建"的 5 项验收；对不满足项做最小加固；用测试锁定行为防回归
- 优先级: P0（阶段 3 第一片，SAG 演进方向的当前落地形态）
- 上下文: 前置 module-075（抓取入库）/ 076（递归爬取）/ 077（反爬）/ 078（审查增强）已全量闭环（119 crawl 测试全绿，全量 1366/4 基线）。抓取链路末端经 `ingest_document` 入库。本模块不动抓取/审查主链路，只验证与加固"入库 = 纯增量追加"这一核心承诺
- Agent 配置: Developer ×1, Reviewer ×1, Tester ×1

## 2. 五项验收与现状核实（Planner 代码审计，2026-08-26）

| # | 验收项 | 现状（代码实证） | 结论 |
|---|--------|------------------|------|
| 1 | **增量嵌入**：新文档只嵌入新文档 | `add_document`（engine.py）只对 `children`（新文档子块）调 `embedding_service.embed_documents(child_texts)`；对存量文档零嵌入调用；嵌入失败 fail-open 不阻断入库 | ✅ 已满足，测试锁定 |
| 2 | **检索增量生效**：入库后检索含新文档 | 子块落库后 `_vector_search` 查 `parent_id IS NOT NULL AND embedding IS NOT NULL`（retriever.py:779/819-822）立即可命中；`add_document` 提交后 `cache.delete_by_prefix("rag:retrieve:")` 清检索缓存（engine.py:1252） | ✅ 已满足，测试锁定 |
| 3 | **无全量重嵌**：追加不改存量 embedding | `add_document` 只 INSERT 新父块/子块，**无任何对存量行的 UPDATE embedding**；`graph_store.ensure_graph()` 幂等建图（非重建）、`upsert_entity` 幂等追加 doc_ids；全量重嵌仅存在于手动运维脚本 `scripts/reindex_knowledge_base.py` / `migrate_embedding_1024.py` / `backfill_graph.py`，**不在任何自动入库路径中** | ✅ 已满足，测试锁定 |
| 4 | **去重不破坏增量** | L1 `exact_hash` 命中（document_ingest.py:146）直接返回 duplicate 不写库；`add_document` 内 title/content_hash 去重命中（engine.py）返回 duplicate；去重分支与增量追加互不阻塞 | ✅ 已满足，测试锁定 |
| 5 | **性能 O(1) 非 O(n)** | **风险点**：`find_semantic_duplicate`（document_dedup.py:142-172）ORM **全表拉取根父块 embedding + Python 逐条 `_cosine` = O(N)** 时间/内存，且开关 `doc_dedup_semantic_enabled` 默认 **True**（config.py）；叠加 backlog ① `if not emb`（:157）对 pgvector 返回的 ndarray 抛 `ValueError` → 语义去重默认开时真实入库受阻 | ❌ **需加固**（本次唯一生产改动） |

### 2.1 结论

- 验收 1-4：现有行为正确，**无需改主链路**，测试锁定（验证型模块的主体工作）
- 验收 5：`find_semantic_duplicate` 的 O(N) 全表扫描是唯一的"增量成本随文档数增长"点，且 ndarray bug 阻断真实语义去重 → **最小加固**（对齐 crawler `_conflict_candidates` 已存在的 pgvector SQL top-K 先例）
- 未发现自动链路的全量重嵌路径（验收 3），故**无需新增"全量重嵌防护开关"**；防护目标是"增量性能退化 + ndarray 阻断"，由 document_dedup.py 加固承担

## 3. 模块拆分

### 子任务 1: 语义去重候选查询 O(N) → O(K) 加固 + ndarray bug 修复（document_dedup.py）
- 描述: `find_semantic_duplicate` 候选获取从"ORM 全表拉取 + Python 全量余弦"改为"pgvector SQL `ORDER BY embedding <=> :vec LIMIT :k` 索引查询 + Python 仅对 top-K 算余弦"（对齐 crawler.py `_conflict_candidates` 先例，embedding 字符串绑定规避 asyncpg 类型编解码）；同步根除 backlog ① `if not emb` ndarray 真值判定
- 预估代码量: 生产代码 ≤ 45 行（铁律 2 预算内，实际预计 ~35 行）
- 涉及文件:
  - `ai_service/rag/retrieval/document_dedup.py`（`find_semantic_duplicate` 重写）
  - `ai_service/src/config.py`（新增 `doc_dedup_candidate_top_k: int = 50`）
- 依赖: 无

### 子任务 2: 五项验收测试（新增 tests/core/test_incremental_append.py）
- 描述: 每项验收一组测试（验收 1-4 行为锁定 + 验收 5 复杂度锁定 + ndarray 回归），mock embedding_service / session / cache，hermetic 不依赖真实 PG 与 bge-m3
- 预估代码量: 测试代码 ~300 行（**不含在 ≤200 行生产代码限额内**）
- 涉及文件:
  - `ai_service/tests/core/test_incremental_append.py`（新建）
  - `ai_service/tests/core/test_document_dedup.py`（适配 find_semantic_duplicate 新查询形态，若存量用例依赖旧 ORM mock）
- 依赖: 子任务 1

### 子任务 3: 存量去重测试适配 + 全量回归
- 描述: 确认 `tests/core/test_document_dedup.py` 在新查询形态下语义不变（行为断言不漂移，仅 mock 方式适配）；全量回归 `tests/` 基线 1366/4 不降；py_compile 验证
- 预估代码量: 0（纯验证）
- 涉及文件: 无
- 依赖: 子任务 1 + 2

## 4. 技术方案

### 4.1 为什么 find_semantic_duplicate 是唯一加固点（复杂度论证）

增量入库链路逐环节复杂度（N = 存量文档数）：

| 环节 | 现状复杂度 | 说明 |
|------|-----------|------|
| L1 内容哈希去重 | O(log N) ≈ 常量 | `doc_content_hash` 列有索引（models.py `index=True`），SQL 索引查询 |
| L2 语义去重候选 | **O(N)（风险）** | ORM 全表取根父块 embedding 到 Python + 逐条 `_cosine`；文档量级增长时每次入库全量传输 + 余弦 |
| 分块 + 嵌入 | O(新文档子块数) | 只对新文档，与 N 无关 ✅ |
| 图实体提取 | O(新文档) | `extract_from_document(新内容)` + 幂等 upsert，与 N 无关 ✅ |
| 检索缓存失效 | O(1) | `delete_by_prefix("rag:retrieve:")`，与 N 无关 ✅ |

→ 唯一破坏"增量时间与文档数无关"的是 L2 候选全表扫描。改造后该环节变 pgvector 索引 top-K：O(log N + K)，K 固定 → 整链路与 N 近似无关，验收 5 成立。

### 4.2 改造设计（对齐 crawler `_conflict_candidates` 先例）

改造后 `find_semantic_duplicate` 流程：

```
1. vec = await compute_doc_embedding(strip_boilerplate(doc_text))   # 不变，fail-open
2. vec_str = f"[{','.join(str(v) for v in vec)}]"                   # 字符串绑定（规避 asyncpg 类型编解码）
3. SQL: SELECT id, title, duplicate_cluster_id,
             1 - (embedding <=> :vec) AS cosine
       FROM documents
       WHERE parent_id IS NULL
         AND embedding IS NOT NULL
         AND is_canonical IS TRUE
         AND (source IS NULL OR source NOT LIKE 'memory:%')
       ORDER BY embedding <=> :vec ASC
       LIMIT :k                                                        # k = doc_dedup_candidate_top_k
4. Python 遍历 top-K 行：cosine ≥ threshold 取最优 → 返回 {"id","title","cluster_id","cosine"} 或 None
```

要点：
- **查询形态与生产检索通道 `_vector_search`（retriever.py:815-825）完全一致**：同样的 `<=>` 距离排序 + LIMIT + embedding 字符串绑定 → 复用其 pgvector 索引路径（检索 Hit@5 0.9905 生产实测证明该形态可用）
- **正确性论证（top-K 截断不改变判定结果）**：`ORDER BY embedding <=> :vec ASC` 按距离升序 = 余弦降序。若全表存在 cosine ≥ 阈值（0.95）的候选，其必然位于前 K 高余弦内 → top-K 截断与全表扫描在"是否存在 ≥ 阈值候选"上结果一致。默认 K=50，真实语义重复（几乎相同文本）量级远小于此
- **返回契约不变**：仍返回 `{"id", "title", "cluster_id", "cosine"}` 或 None，`ingest_document` 调用方零改动
- **ndarray bug 根除（backlog ①）**：SQL 层 `WHERE embedding IS NOT NULL` + 余弦由 SQL 算好（`1 - (embedding <=> :vec)`），Python 侧不再对 embedding 做真值判定（原 `if not emb` 对非空 ndarray 抛 `ValueError: truth value ambiguous`），只判 `row.cosine` 数值
- **候选同源排除语义保留**：`source IS NULL OR source NOT LIKE 'memory:%'` 与现查询逐字一致（防把记忆文档折叠进知识库簇）

### 4.3 配置变更（config.py，仅 1 项）

- `doc_dedup_candidate_top_k: int = 50` —— L2 语义去重向量候选上限（pgvector top-K；注释说明：语义重复量级远小于 50，防极端；`PW_DOC_DEDUP_CANDIDATE_TOP_K` 可覆盖）
- 其余配置不动：`doc_dedup_semantic_enabled`（True）/ `doc_dedup_threshold`（0.95）/ `doc_dedup_boilerplate_enabled`（True）沿用现状

### 4.4 存量测试兼容性

- `tests/core/test_document_dedup.py` 中 `find_semantic_duplicate` 用例以 FakeResult/FakeScalars mock ORM select 结果 → 新查询形态下同步适配（改 mock 假 session 的 `execute` 返回 FakeRows，或 mock 内部 `_query`）。**行为断言不变**（阈值命中 / 不命中 / fail-open / canonical / 同源排除语义一致），仅 mock 方式变化
- 其余文件（engine / ingest / retriever / crawler）零改动 → 上游存量测试不受影响

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| top-K 截断漏判语义重复（极端：>50 个候选全在阈值内） | 极端场景少标一次簇 | 正确性论证（§4.2）：余弦降序下 ≥ 阈值候选必在前 K；K=50 远超实际重复量级；可 `PW_DOC_DEDUP_CANDIDATE_TOP_K` 调大 |
| pgvector embedding 列无索引 → top-K 退化为全扫 | 性能提升有限 | 查询形态与生产检索通道 `_vector_search` 同源（生产可用性已证明）；REVIEW 加一项检查：psql `\d documents` 确认 embedding 有 pgvector 索引，若无 → 记遗留（本模块不动 DDL） |
| 存量去重测试 mock 适配引入断言漂移 | 误报回归 | 子任务 3 全量回归基线 1366/4 不降为硬门槛；行为断言逐字保留，仅 mock 形态变化 |
| 误判为"需要全量重嵌防护"扩大范围 | 违反模块最小化 | 审计结论明确：自动链路无全量重嵌路径（§2 验收 3），不新增重嵌防护开关；加固仅限 document_dedup.py |

## 6. 测试计划（tests/core/test_incremental_append.py）

| 测试组 | 对应验收 | 断言要点 |
|--------|---------|----------|
| 增量嵌入 | 验收 1 | mock `embedding_service.embed_documents`：断言仅对新文档子块调用（调用次数 = 新文档子块数），断言无对存量文档的嵌入调用 |
| 检索增量生效 | 验收 2 | 入库后 `_vector_search` 候选 SQL 能命中新子块（mock session 返回新 doc_id）；`cache.delete_by_prefix("rag:retrieve:")` 被调用（缓存失效） |
| 无全量重嵌 | 验收 3 | 入库前后断言存量文档 embedding 逐字节不变（mock session 记录 DML：只出现 INSERT，无 UPDATE/DELETE 存量）；断言无 reindex/rebuild 函数被调用 |
| 去重不破坏增量 | 验收 4 | 先入库 A → 相同内容再入库（L1 命中 duplicate，不写库）→ 新文档 B 正常入库（duplicate=False，chunks>0）；L1 去重不阻塞后续增量 |
| 性能 O(1) | 验收 5 | 语义去重候选 SQL 断言带 `LIMIT :k`（固定 K，不随存量文档数增长）；用不同存量文档数跑两次，断言 `embed_documents` 调用次数相同（与 N 无关） |
| ndarray 加固 | backlog ① | `find_semantic_duplicate` 候选 embedding 为 numpy ndarray 形态时不再抛 ValueError（回归锁定） |

- hermetic：沿用 conftest 现有 autouse 钉住（`doc_dedup_semantic_enabled=False` 等）；语义去重用例体内显式 setattr True + mock 各层（对齐 module-064 测试范式）
- 冒烟（Tester 阶段，可选真实环境）：真实 PG + bge-m3 入库新文档 A 再入库 B，验证 B 入库耗时与存量文档数无显著线性关系、检索接口能召回新文档

## 7. 验收标准索引

- 完整验收清单见同目录 `acceptance-criteria.md`（功能 5 项 + 边界/异常 + 非功能铁律 + 可运行验证命令）
- 本模块交付物: plan.md / acceptance-criteria.md / document_dedup.py 加固 / config.py 1 项配置 / test_incremental_append.py / 全量回归报告
- 铁律口径: 新增生产代码 ≤ 200 行（实际预计 ≤ 50 行）；单方法 ≤ 50 行；docstring 齐全；无空 catch

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本（Planner 全量代码审计：验收 1-4 已满足、验收 5 需加固 + backlog ① 修复） | Planner |

## 9. 待澄清

1. **`doc_dedup_candidate_top_k` 默认值**：取 50（远超语义重复量级）。若 Reviewer 认为应更保守（如 20），改动仅 config 一行，不涉及逻辑
2. **pgvector 索引确认**：REVIEW 阶段检查 documents.embedding 是否有 pgvector 索引（`\d documents`）；缺失则记遗留，不在本模块动 DDL
3. **与 reindex_knowledge_base.py 的边界**：该脚本为手动全量重建运维工具（DELETE+INSERT），本模块验证的是"正常入库链路不走 reindex 也能增量追加"，两者明确区分，不混淆
