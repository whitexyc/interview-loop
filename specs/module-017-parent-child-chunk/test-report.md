# M17 测试报告 — Parent-Child Chunking

## 测试结论：PASS ✅

测试时间：2026-07-30
测试人：Tester

## 构建验证

| 检查项 | 状态 | 说明 |
|--------|------|------|
| chunker 导入 | PASS | RecursiveCharacterTextSplitter 正确配置 (300/50) |
| models 导入 | PASS | parent_id 列存在于 Document 表定义 |
| engine 导入 | PASS | _expand_to_parents 方法已定义 |
| retriever 导入 | PASS | SQL 含 parent_id IS NOT NULL 过滤 |
| migration 导入 | PASS | migrate_parent_child.main 可调用 |

## 单元测试

### Test 1: Chunker 两级分块
- 输入：含 2 个 `##` 节的长文档
- 输出：2 parents + 7 children
- 每 child 的 parent_index 正确映射到对应 parent（0→Section1, 1→Section2）
- 子块长度约 200-300 字符（符合 chunk_size=300 预期）✅

### Test 2: Models Schema
- `parent_id` 列为 Integer, ForeignKey("documents.id"), nullable ✅

### Test 3: Engine 方法
- `_expand_to_parents()` 方法存在 ✅
- 已接入 `search()`, `chat()`, `_retrieve()` 三条路径 ✅

### Test 4: Retriever SQL
- `_fts_search` 和 `_vector_search` 均包含 `parent_id IS NOT NULL` 过滤 ✅
- SELECT 列表包含 `parent_id` ✅

### Test 5: Migration Script
- `migrate_parent_child.main()` 可导入可调用 ✅

## 已知问题

| # | 严重度 | 描述 | 处理 |
|---|--------|------|------|
| 1 | 中 | Alembic 迁移不存在——项目从未使用 Alembic。parent_id 列在 ORM 中定义但需通过 `init_db()` 或手动 ALTER TABLE 创建 | 部署时在 init_db() 中添加 `Base.metadata.create_all()` |

## 验收标准核对

全部通过。详见 `acceptance-criteria.md`。
