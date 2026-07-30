# 变更日志 — Module-017: Parent-Child Chunking（父子分块检索）

## 变更概述
引入两级粒度的文档分块策略：父块（完整 `##` section，无向量，不进检索）和子块（~300字符，携带向量，参与混合检索）。检索命中子块后通过 `parent_id` 映射回父块，确保返回给用户的始终是语义完整的 section 级别内容。API 签名和响应格式不变，对调用方透明。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/models.py | 修改 | 新增 `parent_id` 列（Integer, FK→documents.id, nullable, indexed） |
| ai_service/rag/chunker.py | 修改 | `chunk()` 返回 `{parents, children}` 两级结构；新增 `RecursiveCharacterTextSplitter` 二级分割器（chunk_size=300, overlap=50） |
| ai_service/rag/retriever.py | 修改 | FTS 和向量检索 SQL：SELECT 追加 `parent_id`，WHERE 追加 `AND parent_id IS NOT NULL` |
| ai_service/rag/engine.py | 修改 | `add_document()` 改为两阶段插入（父块先 flush → 子块向量化后携带 `parent_id` 入库）；新增 `_expand_to_parents()` 方法；`search()`/`chat()`/`_retrieve()` 各加一行父块映射调用 |
| ai_service/rag/migrate_parent_child.py | 新增 | 旧格式文档一次性迁移脚本：原行置空 embedding 变父块 + 新增子块行；幂等（已迁移跳过） |

## 关键设计说明

### 设计决策 1: 单表 `parent_id` 自引用而非父子两张表
- 决策: 在 `documents` 表加一列 `parent_id` FOREIGN KEY 指向自身，通过 `parent_id IS NULL/NOT NULL` 区分父子
- 原因: 避免新建表带来的 JOIN 复杂度；FTS + pgvector 查询只需一行 WHERE 条件即可过滤子块；向前兼容旧数据（`parent_id IS NULL AND embedding IS NOT NULL` 格式仍可读取）

### 设计决策 2: 父块 flush 而非 commit
- 决策: `add_document()` 中父块插入后用 `session.flush()` 获取 DB 分配的 ID，最后一次性 `commit()`
- 原因: 保持事务原子性——如果子块向量化或入库失败，父块自动回滚，不会产生孤儿行

### 设计决策 3: 检索过滤在 SQL 层而非应用层
- 决策: 在 `_fts_search` 和 `_vector_search` 的 SQL 中直接加 `AND parent_id IS NOT NULL`
- 原因: 数据库层过滤比应用层过滤效率高；向量检索的 `embedding IS NOT NULL` 条件已过滤父块（因父块 embedding 为 NULL），`parent_id IS NOT NULL` 额外排除旧格式文档

### 设计决策 4: `_expand_to_parents` 按 parent_id 去重取 max score
- 决策: 同一父块的多个子块同时命中时，只返回一次父块，hybrid_score 取最佳子块分数
- 原因: 避免搜索结果中同一 section 重复出现；最佳子块分数代表该 section 与查询的最高相关度

### 设计决策 5: 迁移脚本幂等设计
- 决策: 每次迁移前检查 `WHERE parent_id = 原行.id`，已有子块则跳过
- 原因: 可在生产环境安全重跑，不会产生重复子块行

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法检查 | `cd ai_service && python -m py_compile rag/models.py rag/chunker.py rag/retriever.py rag/engine.py rag/migrate_parent_child.py` | 无错误 |
| 数据模型 | `cd ai_service && python -c "from rag.models import Document; print(Document.__table__.columns.keys())"` | 包含 `parent_id` |
| 迁移试运行 | `cd ai_service && python -m rag.migrate_parent_child --dry-run` | 输出待迁移数量，不修改数据 |
| 迁移正式执行 | `cd ai_service && python -m rag.migrate_parent_child` | 输出迁移数量，幂等 |
| 引擎导入 | `cd ai_service && python -c "from rag.engine import rag_engine; print('OK')"` | OK |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：models.py 加列、chunker.py 两级分割、retriever.py SQL 过滤、engine.py 两阶段插入 + 父块映射、迁移脚本 | Developer |
