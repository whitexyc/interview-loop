# M17: 父子分块检索 — 验收标准

## 1. 数据模型验收

- [ ] `documents` 表新增 `parent_id` 列（Integer, FK→documents.id, nullable, indexed）
- [ ] `parent_id` 列语义正确：父块 `parent_id IS NULL AND embedding IS NULL`，子块 `parent_id IS NOT NULL AND embedding IS NOT NULL`
- [ ] 旧格式文档兼容：`parent_id IS NULL AND embedding IS NOT NULL` 的旧记录仍可读取，不被新检索器误返回
- [ ] Alembic 迁移脚本可正向执行（`upgrade`）和回滚（`downgrade`）

## 2. Chunker 验收

- [ ] `chunk()` 返回格式从 `list[dict]` 改为 `{"parents": [...], "children": [...]}`
- [ ] 父块按 `##` 标题分割，每父块包含完整 section 文本 + `title`
- [ ] 子块按 `RecursiveCharacterTextSplitter` 对每个父块内容二次分割，`child_chunk_size=300`、`child_chunk_overlap=50`
- [ ] 子块中 `parent_index` 正确指向对应父块在 `parents` 列表中的下标
- [ ] 无 `##` 标题时 fallback：整个文档为单一父块，子块从该父块分割产生
- [ ] 所有父块被 `min_chars` 过滤掉时，返回空 parents 和空 children（由 `add_document()` 兜底）
- [ ] 有 `##` 标题的正常文档：父块数量 = 标题段落数，子块总数 >= 父块数

## 3. 检索器验收

- [ ] `_fts_search` SQL 的 SELECT 包含 `parent_id`，WHERE 追加 `AND parent_id IS NOT NULL`
- [ ] `_vector_search` SQL 的 SELECT 包含 `parent_id`，WHERE 追加 `AND parent_id IS NOT NULL`
- [ ] 两路检索结果 dict 均携带 `parent_id` 字段
- [ ] 仅子块参与检索（父块 embedding 为 NULL，不会被向量检索命中；FTS 显式过滤）
- [ ] 旧格式文档（`parent_id IS NULL AND embedding IS NOT NULL`）不被检索到（两路均已过滤）

## 4. 引擎验收

### 4.1 文档入库（`add_document`）

- [ ] 两阶段插入：先插入父块（`embedding=NULL, parent_id=NULL`）→ commit 获取 ID → 再插入子块（`embedding=vector, parent_id=父块ID`）
- [ ] 子块 `content_hash` 基于各自子块内容计算（非父块内容），去重仍按原始全文 hash
- [ ] 重复检测按原始全文 title/content_hash 匹配，逻辑不变
- [ ] 无 parents 时 fallback：整文档为单一父块，子块从该父块分割
- [ ] 返回格式不变：`{"id": int, "title": str, "chunks": int, "duplicate": bool}`

### 4.2 父块映射（`_expand_to_parents`）

- [ ] 从 child_docs 收集唯一 `parent_id`，记录每个父块的最佳（最高）`hybrid_score`
- [ ] 批量查询父块：`SELECT * FROM documents WHERE id IN (...)`
- [ ] 返回去重父块列表，每父块携带 `hybrid_score`（来自其最佳子块）
- [ ] 返回字段包含 `id`, `title`, `content`, `source`, `hybrid_score`

### 4.3 检索/问答接口

- [ ] `search()` 在检索后调用 `_expand_to_parents()`，返回父块内容（而非子块）
- [ ] `_retrieve()` 在检索后调用 `_expand_to_parents()`，后续 rerank 基于父块
- [ ] `chat()` 在检索后调用 `_expand_to_parents()`，反思循环和生成基于父块
- [ ] API 响应格式不变：`SearchResponse.results[]` 和 `ChatResponse.sources[]` 字段与 M8 一致

## 5. 迁移脚本验收

- [ ] 旧格式文档（`parent_id IS NULL AND embedding IS NOT NULL`）正确迁移：原行 embedding 置 NULL → 变为父块；新增一行 `parent_id=原行id` + 保留 embedding → 变为子块
- [ ] 迁移幂等：重复执行不产生额外行（检测到已有子块时跳过）
- [ ] 迁移后可被新检索器正常检索（子块有 `parent_id IS NOT NULL`）

## 6. 边界条件验收

- [ ] 空内容文档：`add_document` 抛出 `ValueError`（与现有行为一致）
- [ ] 纯短标题无内容的文档：chunker 返回空，`add_document` fallback 正确处理
- [ ] 单父块文档（无 `##`）：检索返回该父块（通过其子块命中）
- [ ] 多父块文档（有多个 `##`）：检索命中最相关父块，不返回无关 section
- [ ] 子块被过滤后在 `_expand_to_parents` 中正确聚合：`parent_id` 去重，分数取 max
- [ ] 检索无结果时 `_expand_to_parents` 直接返回空列表（不报错）
- [ ] 并发添加文档：不同文档可并发写入（不同 session），不产生父块 ID 错乱

## 7. 向后兼容验收

- [ ] `SearchResponse` 和 `ChatResponse` 的 JSON schema 不变
- [ ] 现有 RAG 单元测试全部通过（`ai_service/tests/`）
- [ ] 前端调用 `search()` 和 `chat()` 无感知变化
- [ ] 旧格式文档（迁移前）不影响新检索器运行（不会因 NULL parent_id 崩掉）

## 8. 验证命令

| 验收项 | 命令 | 预期 |
|--------|------|------|
| 语法检查 | `cd ai_service && python -m py_compile rag/models.py rag/chunker.py rag/retriever.py rag/engine.py` | 无错误 |
| 数据模型 | `cd ai_service && python -c "from rag.models import Document; print(Document.__table__.columns.keys())"` | 包含 `parent_id` |
| Chunker 单元测试 | `cd ai_service && python -m pytest tests/ -k "chunk" -v` | 全部通过 |
| 检索器单元测试 | `cd ai_service && python -m pytest tests/ -k "retrieve" -v` | 全部通过 |
| 引擎集成测试 | `cd ai_service && python -m pytest tests/ -k "engine" -v` | 全部通过 |
| 完整测试套件 | `cd ai_service && python -m pytest tests/ -v` | 全部通过 |
| 迁移脚本试运行 | `cd ai_service && python -m rag.migrate_parent_child --dry-run` | 输出待迁移数量，不修改数据 |
| 迁移脚本正式执行 | `cd ai_service && python -m rag.migrate_parent_child` | 输出迁移数量，幂等 |
