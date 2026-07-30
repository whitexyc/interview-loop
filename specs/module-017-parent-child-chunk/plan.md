# M17: 父子分块检索 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M17 |
| 模块名称 | Parent-Child Chunking（父子分块检索） |
| 版本号 | 0.17.0-module-017 |
| 创建日期 | 2026-07-30 |
| 前置模块 | M8（RAG 知识库核心） |
| 范围 | ai_service only |
| 目标 | 父块（section级）存储无向量、子块（~300字符）存储向量+检索，结果映射回父块返回 |

## Agent 配置

| 角色 | 实例数 | 职责 |
|------|--------|------|
| Developer | x1 | Python AI 服务专项开发 |
| Reviewer | x1 | 代码审查 |
| Tester | x1 | 集成测试 + 迁移验证 |

---

## 1. 需求概述

### 1.1 当前状态
- `chunker.py` 按 `##` 标题 split，每个 chunk 独立存储 embedding 并直接参与检索
- `retriever.py` 对 `documents` 表全量做向量 + FTS 混合检索
- `engine.py` 中 `add_document()` 单次插入所有 chunk（embedding + content 一起写）

### 1.2 目标
1. 引入两级粒度：父块（完整 `##` section，无向量） + 子块（~300 字符，含向量）
2. 检索只命中子块，结果按 `parent_id` 映射回父块，去重后返回
3. 保留现有 API 签名不变（`search()` / `chat()` 调用方无感）

### 1.3 非目标
- 不动前端（`search()` 返回格式不变）
- 不新建表（仅在 `documents` 表加一列 `parent_id`）
- 不影响已存在的非父子格式文档（通过迁移脚本兼容）

---

## 2. 技术方案

### 2.1 Schema 变更（`models.py`）

新增列：

```python
parent_id = Column(Integer, ForeignKey("documents.id"),
                   nullable=True, index=True,
                   comment="父块 ID（NULL=父块/根块，非NULL=子块指向其父块）")
```

语义：
| `parent_id` | `embedding` | 含义 |
|---|---|---|
| `NULL` | `NULL` | 父块（section 级，不参与检索） |
| `NOT NULL` | `NOT NULL` | 子块（子段，参与检索） |
| `NULL` | `NOT NULL` | 旧格式文档（迁移前） |

### 2.2 分块器变更（`chunker.py`）

新增 `RecursiveCharacterTextSplitter` 作为二级 splitter：

| 参数 | 默认值 | 用途 |
|------|--------|------|
| `child_chunk_size` | `300` | 子块目标字符数 |
| `child_chunk_overlap` | `50` | 相邻子块重叠量 |

`chunk()` 返回格式从 `list[dict]` 改为：
```python
{
    "parents": [{"title": ..., "content": ...}],
    "children": [{"title": ..., "content": ..., "parent_index": 0}]
}
```

边界处理：无 `##` 标题时整个文档为单一父块；`min_chars` 过滤掉所有父块时返回空（`add_document` 自行兜底）。

### 2.3 检索器变更（`retriever.py`）

`_fts_search` 和 `_vector_search` 的 SQL 中：
- SELECT 列表追加 `parent_id`
- WHERE 追加 `AND parent_id IS NOT NULL`（仅子块参与检索）

结果 dict 携带 `parent_id` 字段，供引擎层完成父块映射。

### 2.4 引擎变更（`engine.py`）

**`add_document()` 改为两阶段插入**：
1. Hash 全文 → 查重（逻辑不变）
2. `chunker.chunk()` → 得到 parents + children
3. 先插入 parents（`embedding=NULL`, `parent_id=NULL`），提交获取 ID
4. 将 children 文本批量 embed → 插入 children（`embedding=vector`, `parent_id=parent.id`）
5. 无 parents 兜底：整文档为单一父块

**新增 `_expand_to_parents()` 方法**：
- 收集 `child_docs` 中唯一 `parent_id`，记录每父块最佳 `hybrid_score`
- 批量 `WHERE id IN (...)` 查询父块
- 返回去重父块列表（`id`, `title`, `content`, `source`, `hybrid_score`）

**`search()` / `_retrieve()` / `chat()` 各加一行**：
```python
docs = await self._expand_to_parents(docs)
```

### 2.5 迁移脚本

Python 脚本（手动执行一次）：旧文档 `parent_id IS NULL AND embedding IS NOT NULL` → 原行成为父块（`embedding` 置 NULL），复制一行作为子块（`parent_id` 指向父块，保留 embedding）。幂等，重复执行无害。

---

## 3. 文件清单

| # | 文件 | 变更 |
|---|------|------|
| 1 | `ai_service/rag/models.py` | 新增 `parent_id` 列 |
| 2 | `ai_service/rag/chunker.py` | `chunk()` 返回 `{parents, children}`，新增 `RecursiveCharacterTextSplitter` |
| 3 | `ai_service/rag/retriever.py` | SQL SELECT/WERE 追加 `parent_id`，过滤仅查子块 |
| 4 | `ai_service/rag/engine.py` | `add_document()` 两阶段插入，新增 `_expand_to_parents()`，`search`/`chat` 调映射 |
| 5 | `ai_service/rag/migrate_parent_child.py` | **新建**：旧格式 → 父子格式一次性迁移脚本 |

---

## 4. 实施步骤

1. **models.py**：加 `parent_id` 列，生成 Alembic 迁移
2. **chunker.py**：改造 `chunk()` 返回两级结构 + fallback 逻辑
3. **retriever.py**：SQL 加 `parent_id` 过滤
4. **engine.py**：改 `add_document()` + 新增 `_expand_to_parents()` + 三个方法各插一行映射调用
5. **迁移脚本**：编写并验证幂等迁移
6. **测试**：更新现有 RAG 测试 + 新增父子映射单测

---

## 5. 风险

| 风险 | 严重度 | 应对 |
|------|--------|------|
| 父块 ID 回填竞态（并发写入） | 低 | `add_document()` 内顺序执行，AsyncSession 单线程 |
| 旧文档迁移后检索中断 | 中 | 迁移脚本先于新检索器部署；幂等可重跑 |
| 子块过短语义丢失 | 低 | `child_chunk_overlap=50` 保证上下文连贯 |
| `_expand_to_parents` 大批量 IN 查询性能 | 低 | 单次检索子块数 < 50，IN 查询 < 10ms |
