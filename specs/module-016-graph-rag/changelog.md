# 变更日志 — Module-016: Graph RAG

## 变更概述
基于 Apache AGE 实现 Graph RAG 知识图谱检索增强：文档入库时通过 LLM 提取实体和关系写入图数据库，查询时并行执行向量检索和图遍历检索，合并去重后返回。图操作全部 try/except 包裹，失败时静默降级不影响核心检索链路。零新增 pip 依赖（AGE 是 PostgreSQL 扩展）。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/graph_store.py | 新增 | GraphStore 类：ensure_graph/upsert_entity/upsert_relation/search_related，所有操作 try/except 降级 |
| ai_service/rag/graph_extractor.py | 新增 | GraphExtractor 类：extract_from_document (LLM 提取实体+关系)、extract_from_query (LLM 提取实体名称)、_parse_json 多级回退 |
| ai_service/rag/engine.py | 修改 | add_document() 入库后异步提取实体/关系写入 AGE；_retrieve() round 0 并行向量+图搜索合并去重 |

## 关键设计说明

### 设计决策 1: 图模型使用单一节点类型 Entity + 单一边类型 RELATED_TO
- **决策**: 所有实体统一为 `(:Entity {name, type, doc_ids})`，所有关系统一为 `[:RELATED_TO]`
- **原因**: 简化 Cypher 查询（无需处理多种节点/边标签），降低 LLM 提取复杂度（不需要分类关系类型）。doc_ids 用 JSON 数组字符串存储，支持追加合并。

### 设计决策 2: 图遍历策略为匹配实体 → 一跳邻居 → 收集 doc_ids
- **决策**: `search_related()` 先 MATCH 查询实体 → OPTIONAL MATCH 一跳 RELATED_TO 邻居 → 收集所有关联 doc_ids → 批量 SQL 查询 documents 表
- **原因**: AGE 是嵌入式图数据库（运行在 PostgreSQL 内部），遍历后需要 JOIN documents 表获取完整文档内容。两步查询是 AGE+PG 混合模型的标准做法。一跳邻居在召回率和查询成本之间取得平衡。

### 设计决策 3: extract_from_document 分两步 LLM 调用（先实体后关系）
- **决策**: 第一次调用提取实体列表 `{entities: [{name, type}]}`，第二次基于实体列表提取关系 `{relations: [{source, target}]}`
- **原因**: 分步处理降低单次 prompt 复杂度。实体类型（concept/technology/algorithm 等）在文档标题和关键词中更明确；关系提取需要理解段落间的语义连接。分开处理各自能得到更精准的提取结果。

### 设计决策 4: 图搜索仅 round 0 执行，result 与向量结果合并时向量优先
- **决策**: 只在首轮执行图搜索（与向量检索并行 via `asyncio.gather`）；合并时向量结果在前，图结果补充到后面且给固定分数 0.6
- **原因**: 图搜索的语义精确度通常低于向量检索（基于实体名称匹配而非全文语义），作为补充信号而非主信号。仅首轮执行避免在后续反射轮次重复图搜索（反射改写后的 query 已偏离原始实体）。

### 设计决策 5: add_document 中的图提取异步执行且失败不影响入库
- **决策**: 图提取放在 `session.commit()` 之后、return 之前，整个提取+写入过程用 try/except 包裹
- **原因**: 文档入库是核心功能，图知识图谱是增强功能。图提取失败不应阻塞文档入库流程。日志级别为 warning（非 error），方便运维监控。

### 设计决策 6: Cypher 查询使用 AGE 参数化 + SQL text() bindparams
- **决策**: 实体名称和类型通过 SQL `:name` 参数传递，而非字符串拼接
- **原因**: 防止 Cypher 注入攻击。虽然 AGE 的 MERGE 匹配基于字符串相等（不执行动态 Cypher），但参数化是最佳安全实践。

## 验证命令
| 验证项 | 命令 | 结果 |
|--------|------|------|
| graph_store.py 编译 | `python -m py_compile rag/graph_store.py` | PASS |
| graph_extractor.py 编译 | `python -m py_compile rag/graph_extractor.py` | PASS |
| engine.py 编译 | `python -m py_compile rag/engine.py` | PASS |
| 方法存在性 | `dir(graph_store)` → ensure_graph, search_related, upsert_entity, upsert_relation | PASS |
| 提取器方法 | `dir(graph_extractor)` → extract_from_document, extract_from_query | PASS |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：GraphStore + GraphExtractor + engine.py 集成 | Developer |
