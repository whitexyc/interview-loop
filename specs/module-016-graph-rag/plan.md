# M16: Graph RAG — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M16 |
| 模块名称 | Graph RAG |
| 版本号 | 0.16.0-module-016 |
| 前置模块 | M5, M17 |
| 范围 | ai_service only |
| 目标 | Apache AGE 知识图谱：实体提取→关系建模→图遍历检索→与向量搜索合并 |

---

## 1. 技术方案

### 1.1 AGE 图模型
- 图名：`knowledge_graph`
- 节点：`Entity` (name, type, doc_ids)
- 边：`RELATED_TO`（统一关系类型）

### 1.2 新增文件
**`graph_store.py`**：GraphStore 类
- ensure_graph() / upsert_entity() / upsert_relation() / search_related()

**`graph_extractor.py`**：GraphExtractor 类
- extract_from_document(content) → {entities, relations}
- extract_from_query(query) → [entity_names]

### 1.3 engine.py 集成
- `add_document()`：入库后提取实体+关系→AGE
- `_retrieve()`：round 0 并行向量检索+图搜索→合并去重

---

## 2. 文件清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `ai_service/rag/graph_store.py` | 新建 |
| 2 | `ai_service/rag/graph_extractor.py` | 新建 |
| 3 | `ai_service/rag/engine.py` | 修改 |
