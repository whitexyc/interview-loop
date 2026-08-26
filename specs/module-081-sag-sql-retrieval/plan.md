# module-081-sag-sql-retrieval 开发计划

## 1. 需求描述

在现有 Agentic RAG 知识库之上实现 **SAG（SQL-Retrieval Augmented Generation）** 检索模式，与现有 RAG 三通道检索**可切换**。

### SAG 核心思想（Zleap arXiv 2606.15971）
- **离线**：文档入库时抽取「事件 + 实体」（约 11 类），**不预建全局图谱**
- **在线**：查询时用 **SQL join 动态连边**，把相关文档/实体连接起来
- 对比现有 GraphRAG：增量 append-only，无级联抽取、无全局重算——天然适配已就绪的增量 append 管线（module-079）
- 多跳最强（MuSiQue Recall@5 80%），适合作答"跨文档引用链/关系链"类问题

### 硬性需求
1. **RAG/SAG 双模式开关**：config 增加检索模式开关（`retrieval_mode`），默认 `hybrid` = 现有行为零回归
2. **SAG 数据层**：实体/事件/关系落表（新增 DDL），增量 append 路径在文档入库时抽取实体/事件并落表
3. **SAG 检索通道**：查询时识别查询中的实体 → SQL join 关联 → 返回相关文档/片段
4. **端点**：检索模式经现有 `/ai/rag/search` 与 `/ai/rag/chat` 生效（开关切换即可）
5. **复用**：骨架尽量复用现有组件（graph 抽取能力、reflector、document_ingest hooks）

---

## 2. 子任务拆分

### 子任务 1：config + DDL + ORM（~40 行生产代码）

**涉及文件**：
- `ai_service/src/config.py`：+`retrieval_mode` 开关（~3 行）
- `ai_service/src/database.py`：+SAG 三表 DDL + ensure 函数 + init_db 挂接（~30 行）
- `ai_service/rag/models.py`：+SAG ORM 模型（~15 行）

**实现要点**：
- `retrieval_mode: Literal["hybrid", "sag", "hybrid_sag"] = "hybrid"`（PW_RETRIEVAL_MODE 回退）
- 三张表（CREATE TABLE IF NOT EXISTS 幂等，对齐 database.py init_db 惯例）：
  - `sag_entities`：id, name, entity_type, source_doc_ids(JSONB), created_at
  - `sag_events`：id, event_text, entity_ids(JSONB), source_doc_id, created_at
  - `sag_relations`：id, source_entity_id, target_entity_id, relation_type, source_doc_id, created_at
- GIN 索引 on `sag_entities(name)` 支持模糊匹配查询实体
- ORM: `SagEntity`, `SagEvent`, `SagRelation`（对齐 `Document` 范式）

### 子任务 2：SAG 实体/事件抽取 + 入库 hook（~60 行生产代码）

**涉及文件**：
- `ai_service/rag/retrieval/sag_extractor.py`：新建（~50 行）
- `ai_service/rag/retrieval/document_ingest.py`：+SAG 抽取 hook（~10 行）

**实现要点**：
- 复用 `rag/graph/graph_extractor.py` 的 `_ENTITY_PROMPT` + `_parse_json` 范式
- `sag_extractor.extract_entities_events(document_text)` → LLM 提取 entities + events JSON
  - entity_types: concept, technology, algorithm, framework, tool, person, company, language, event, metric, method（~11 类）
  - 返回 `{entities: [{name, type}], events: [{text, entity_names}]}`
- `document_ingest.ingest_document()` 结尾 hook：`await sag_extractor.ingest_sag_data(doc_id, text)`
  - 失败 fail-open（与 document_ingest 现有纪律一致，不阻断入库）
  - 开关 `retrieval_mode in ("sag", "hybrid_sag")` 才执行
- LLM 调用复用 `LLMFactory.get_client("fallback", temperature=0.1)`（低温度结构化输出）

### 子任务 3：SAG 检索通道（~50 行生产代码）

**涉及文件**：
- `ai_service/rag/retrieval/sag_retriever.py`：新建（~40 行）
- `ai_service/rag/engine.py`：+SAG 检索分支（~10 行）

**实现要点**：
- `sag_retriever.retrieve(query, top_k=5)` → SQL 查询流程：
  1. 复用 `graph_extractor.extract_from_query(query)` 提取查询实体名
  2. SQL: `SELECT DISTINCT d.* FROM documents d JOIN sag_entities se ON d.id = ANY(se.source_doc_ids) WHERE se.name ILIKE ANY(:entity_names) ORDER BY ... LIMIT :top_k`
  3. 可选一跳：`sag_relations` join 找 related entities → 再 join documents
  4. 返回格式对齐 `HybridRetriever.retrieve()` 输出（{title, content, score, ...}）
- engine.py `_retrieve` 新增 `sag` 分支（与 hybrid/rrf/weighted 并列）
  - `hybrid_sag` 模式：SAG 结果 + 现有三通道 RRF 融合（取并集去重，SAG 补充多跳文档）

### 子任务 4：测试（~50 行测试代码）

**涉及文件**：
- `ai_service/tests/retrieval/test_sag.py`：新建（~50 行）

**测试内容**：
- DDL 幂等（二次运行不报错）
- SAG 实体/事件抽取 mock（LLM 返回合法/非法/空 JSON）
- SAG 入库 hook（开关开/关/抽取失败 fail-open）
- SAG 检索（实体匹配/一跳关系/空结果/开关切换）
- 全量回归：`retrieval_mode="hybrid"` 零行为变化

---

## 3. 技术方案

### 3.1 SAG 数据模型（简化版，一跳够用）

```
sag_entities (实体表)
├── id BIGSERIAL PK
├── name VARCHAR(256) NOT NULL          -- 实体名（如 "G1 GC", "Kafka"）
├── entity_type VARCHAR(32) NOT NULL    -- 类型（concept/technology/...）
├── source_doc_ids JSONB NOT NULL DEFAULT '[]'  -- 关联文档 ID 列表
├── created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
└── INDEX: GIN on name (pg_trgm 或 ILIKE 模糊匹配)

sag_events (事件表)
├── id BIGSERIAL PK
├── event_text TEXT NOT NULL            -- 事件描述
├── entity_ids JSONB NOT NULL DEFAULT '[]'  -- 关联实体 ID 列表
├── source_doc_id INTEGER NOT NULL      -- 来源文档 ID
├── created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

sag_relations (关系表)
├── id BIGSERIAL PK
├── source_entity_id INTEGER NOT NULL
├── target_entity_id INTEGER NOT NULL
├── relation_type VARCHAR(64) NOT NULL  -- 关系类型
├── source_doc_id INTEGER NOT NULL      -- 来源文档 ID
├── created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

### 3.2 检索流程

```
Query → [graph_extractor.extract_from_query] → entity_names
       → [sag_retriever._sql_entity_search] → 匹配文档（sag_entities.name ILIKE）
       → [sag_retriever._sql_relation_search] → 一跳关联文档（sag_relations join）
       → 合并去重 → top_k
```

### 3.3 与现有 RAG 的集成

- `retrieval_mode="hybrid"`：现有行为，零回归
- `retrieval_mode="sag"`：纯 SAG 检索（替代三通道）
- `retrieval_mode="hybrid_sag"`：三通道 RRF + SAG 补充（SAG 结果附加到融合结果中去重）

---

## 4. 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 实体抽取质量不稳定 | SAG 检索召回率下降 | 低温度 0.1 + fail-open（抽取失败不阻断入库） |
| ILIKE 模糊匹配精度 | 误匹配无关文档 | 限制 entity_type + 结合 embedding 余弦二次过滤（后续优化） |
| 增量入库延迟增加 | 每次入库 +1 次 LLM 调用 | 异步 fire-and-forget（与 module-033 记忆提取同款） |
| existing tests regression | 全量回归失败 | 默认 `hybrid` 零回归 + conftest autouse 钉住 |
| 200 行预算紧张 | 功能裁剪 | 一跳关系暂用简化 SQL，多跳留后续模块 |

---

## 5. 待澄清

1. **entity_type 列表**：✅ 拍板（调度员 2026-08-26）——接受 11 类：concept / technology / algorithm / framework / tool / person / company / language / event / metric / method。entity_type 值域在 sag_extractor.py 内定义，与 graph_extractor 解耦（不强行复用其 8 类）。
2. **hybrid_sag 融合策略**：✅ 拍板——SAG 结果**附加到 RRF 结果后去重**（取并集、按 SAG 命中优先置前可选），不做 SAG 独立进 RRF 公式（行数预算限制，多跳融合留后续模块）。
3. **SAG 入库 LLM 成本**：✅ 拍板——异步 fire-and-forget + fail-open（对齐 module-033 记忆提取同款模式）；抽取失败只记录日志，绝不阻断入库；由 retrieval_mode 门控（仅 sag / hybrid_sag 模式执行抽取）。
4. **SAG 检索与 reranker 交互**：✅ 拍板——SAG 检索结果**经过 reranker 精排**（与现有 retriever 输出通道一致，作为候选进入同一精排阶段）。
5. **source_doc_ids 更新策略**：✅ 拍板——**追加模式**：同一实体出现在多篇文档时，source_doc_ids 数组追加 doc_id 并去重（INSERT ... ON CONFLICT (name, entity_type) DO UPDATE SET source_doc_ids = 数组并集），减少行数便于 join。
