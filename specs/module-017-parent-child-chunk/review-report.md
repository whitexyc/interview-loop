# 审查报告 — Module-017: Parent-Child Chunking（父子分块检索）

## 1. 审查结论

- **结论**: **PASS_WITH_ISSUES**
- 审查时间: 2026-07-30
- 审查人: Reviewer
- 审查耗时: 约 45 分钟

> 代码实现质量高，与 plan.md 高度吻合，关键路径逻辑正确，安全无隐患。存在 1 个中等问题（缺 Alembic 迁移），但该项目**没有 Alembic 基础设施**，这是 plan.md 模板化需求与项目实际的偏差，不应阻塞进入测试阶段。另有 2 个低优先级建议。

---

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 中等问题（建议修复，可附条件通过）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | (不存在) | — | plan.md 第 4 节与 acceptance-criteria.md 第 1 节均要求"Alembic 迁移脚本可正向执行和回滚"，但未生成。经核查，`ai_service/` 目录下无 `alembic/` 目录、无 `alembic.ini`、`database.py` 仅启用 pgvector 扩展，整个项目从未使用 Alembic。 | 中 | 方案 A: 在 plan.md 中将此条标记为"延后"（待引入 Alembic 后补做）；方案 B: 由 `init_db()` 调用 `Base.metadata.create_all()` 使 ORM 模型直接建表（当前子块 ORM 定义已完备，SQLAlchemy 能自动生成正确的 ADD COLUMN DDL）。 |

### 2.3 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 2 | `engine.py` | L301-303 | `_expand_to_parents()` 中，若子块的 `parent_id` 在数据库中查不到对应父块行（孤儿引用，如父块被手动删除），当前静默丢弃该 parent_id，无任何日志。 | 低 | 在 `result.scalars().all()` 返回后，对比 `parent_scores.keys()` 与查询到的父块 ID 集合，若存在缺失则 WARN 日志记录孤儿 parent_id。 |
| 3 | `chunker.py` | L62 | `separators` 列表中 `"。"` 在 `"."` 之前，对中文-dominant 文档是正确的，但对纯英文文档会先按句号分割（中文句号），不够精确。当前项目主要是中文技术笔记，实际影响极低。 | 低 | 无需修改，记录此设计考量即可。若未来需要纯英文文档支持，可通过参数注入 separators。 |

---

## 3. 验收标准核对

### 3.1 数据模型验收 (Section 1)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| `parent_id` 列（Integer, FK, nullable, indexed） | `models.py:33-35` | PASS | 完全匹配 |
| 列语义正确（父块双 NULL，子块双 NOT NULL） | `engine.py:396-407, 417-431` | PASS | 父块 `embedding=None, parent_id=None`；子块 `embedding=emb, parent_id=parent.id` |
| 旧格式兼容（`parent_id IS NULL AND embedding IS NOT NULL`） | `migrate_parent_child.py:56-60` | PASS | 迁移脚本处理，检索 SQL 也显式过滤 |
| Alembic 迁移可正向/回滚 | — | NOT MET | 项目无 Alembic 基础设施（见问题 #1） |

### 3.2 Chunker 验收 (Section 2)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| `chunk()` 返回 `{parents, children}` | `chunker.py:120-122` | PASS | |
| 父块按 `##` 标题分割 | `chunker.py:56-58, 82-98` | PASS | `MarkdownHeaderTextSplitter([("##", "section")])` |
| 子块 `child_chunk_size=300, child_chunk_overlap=50` | `chunker.py:59-63` | PASS | |
| `parent_index` 正确指向父块下标 | `chunker.py:108, 117` | PASS | `pi` 来自 `enumerate(parents)` |
| 无 `##` fallback | `chunker.py:101-104` | PASS | 返回空，由 `engine.py:389-391` 兜底 |
| 全部父块被过滤时返回空 | `chunker.py:101-104` | PASS | |
| 正常文档父块数 = 段落数，子块数 >= 父块数 | `chunker.py:108-118` | PASS | |

### 3.3 检索器验收 (Section 3)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| `_fts_search` SELECT 含 `parent_id`，WHERE 含 `AND parent_id IS NOT NULL` | `retriever.py:201-210` | PASS | L203, L207 |
| `_vector_search` SELECT 含 `parent_id`，WHERE 含 `AND parent_id IS NOT NULL` | `retriever.py:234-244` | PASS | L237, L241 |
| 两路结果 dict 均携带 `parent_id` | `retriever.py:214, 248` | PASS | `dict(row)` 自动包含所有 SELECT 列 |
| 仅子块参与检索 | `retriever.py:207, 240-241` | PASS | FTS: `parent_id IS NOT NULL`；Vector: `embedding IS NOT NULL AND parent_id IS NOT NULL` |
| 旧格式不被检索到 | `retriever.py:207, 241` | PASS | 旧格式 `parent_id IS NULL` 被两路同时过滤 |

### 3.4 引擎验收 (Section 4)

#### 4.1 文档入库 (`add_document`)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 两阶段插入（父块 flush → 子块 parent_id） | `engine.py:396-432` | PASS | flush L410, commit L435 |
| 子块 `content_hash` 基于子块内容 | `engine.py:431` | PASS | `hashlib.sha256(child["content"])` |
| 重复检测逻辑不变 | `engine.py:369-381` | PASS | 按全文 title/content_hash 匹配 |
| 无 parents fallback | `engine.py:389-391` | PASS | 整文档为单一父块 |
| 返回格式不变 | `engine.py:439-444` | PASS | `{id, title, chunks, duplicate}` |

#### 4.2 父块映射 (`_expand_to_parents`)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 收集唯一 `parent_id`，记录最佳 score | `engine.py:299-306` | PASS | dict key=parent_id, value=max score |
| 批量查询父块 | `engine.py:312-315` | PASS | `WHERE id IN (...)` |
| 返回去重父块，含 `hybrid_score` | `engine.py:319-327` | PASS | |
| 返回字段含 `id, title, content, source, hybrid_score` | `engine.py:321-327` | PASS | |

#### 4.3 检索/问答接口

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| `search()` 调用 `_expand_to_parents()` | `engine.py:73` | PASS | |
| `_retrieve()` 调用 `_expand_to_parents()` | `engine.py:260` | PASS | |
| `chat()` 调用 `_expand_to_parents()` | `engine.py:160` | PASS | |
| API 响应格式不变 | `engine.py:76-88, 175-185` | PASS | `SearchResponse` 和 `ChatResponse` 字段与 M8 一致 |

### 3.5 迁移脚本验收 (Section 5)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 旧格式正确迁移（置空 embedding + 新增子块） | `migrate_parent_child.py:86-104` | PASS | |
| 幂等（已有子块跳过） | `migrate_parent_child.py:71-78` | PASS | |
| 迁移后可被新检索器检索 | `migrate_parent_child.py:94-103` | PASS | 子块 `parent_id=原行id`, embedding 保留 |

### 3.6 边界条件验收 (Section 6)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 空内容抛 `ValueError` | `engine.py:362-363` | PASS | |
| 纯短标题无内容 | `chunker.py:101-104` + `engine.py:389-391` | PASS | fallback 兜底 |
| 单父块文档可检索 | `engine.py:280-333` | PASS | `_expand_to_parents` 正常映射 |
| 多父块返回最相关 section | `engine.py:280-333` | PASS | 子块不同 parent_id → 各自命中 |
| `_expand_to_parents` 空输入不报错 | `engine.py:295-296` | PASS | |
| 并发不同文档不产生 ID 错乱 | `engine.py:369` | PASS | 每文档独立 session |

### 3.7 向后兼容验收 (Section 7)

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| `SearchResponse` / `ChatResponse` JSON schema 不变 | `engine.py:76-88, 175-185` | PASS | 字段完全一致 |
| 前端无感知 | 全局 | PASS | `search()`/`chat()` 签名和返回格式不变 |
| 旧格式不影响检索器 | `retriever.py:207, 241` | PASS | 两路均过滤 `parent_id IS NULL` |

---

## 4. 架构评估

- **分层正确性**: 通过。Python AI 服务侧文件职责清晰：`models.py`（数据模型）、`chunker.py`（预处理）、`retriever.py`（召回）、`engine.py`（编排）。各层通过依赖注入松散耦合。

- **依赖方向**: 正确。`engine.py` → `retriever.py` + `chunker.py` + `models.py`，无反向依赖。`retriever.py` 不依赖 `chunker.py` 或 `engine.py`。

- **新增依赖**: 无。`RecursiveCharacterTextSplitter` 来自已存在的 `langchain_text_splitters` 库（chunker.py 中 L23 的 `MarkdownHeaderTextSplitter` 已依赖该库）。无需 ADR。

- **设计决策记录质量**: changelog.md 中 5 个设计决策记录详尽，解释了关键 trade-off（单表自引用 vs 双表、flush vs commit、SQL 层过滤 vs 应用层过滤、去重策略、幂等设计）。这些决策不需要额外 ADR。

---

## 5. 安全评估

- [x] **SQL 注入防护**: 通过。所有 SQL 使用 SQLAlchemy `text()` 参数化查询（`:query`、`:limit`、`:query_embedding` 绑定参数）。向量嵌入的 f-string `f"[{','.join(...)}]"` 来源是 embedding 模型输出的 float 列表，非用户输入，无注入风险。

- [x] **XSS 防护**: N/A。Python AI 服务层不直接渲染 HTML，前端负责转义。

- [x] **密码安全**: N/A。本模块无密码处理。

- [x] **API Key 安全**: N/A。本模块不涉及外部 API 调用（embedding 调用由 `EmbeddingService` 封装）。

- [x] **敏感信息日志处理**: 通过。日志输出使用格式化字符串，无敏感信息泄露。错误日志记录 `exc_info=True`，符合规范。

---

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: **否**
- 原因: 本模块的设计决策（单表自引用、flush 而非 commit、SQL 层过滤）已在 changelog.md 第 4 节充分记录。新增的 `RecursiveCharacterTextSplitter` 来自已有依赖 `langchain_text_splitters`，不属新依赖。无需额外 ADR。

---

## 7. 审查检查清单

- [x] 命名符合规范（Python: `snake_case` 变量/函数, `PascalCase` 类）
- [x] 所有 public 方法有 docstring 注释（`chunk()`, `retrieve()`, `add_document()`, `_expand_to_parents()`, `search()`, `chat()`）
- [x] 复杂逻辑有行内注释（chunker 的分步逻辑、engine 的两阶段插入、retriever 的 score fusion）
- [x] 异常处理无空 catch（`engine.py:445-448` rollback + re-raise; `engine.py:89-91` log + 友好返回; retriever graceful degradation）
- [x] 关键操作有 INFO 级别日志（`engine.py:54, 104, 365, 437`）
- [x] 代码长度在限制内（`chunker.py` ~127 行, `engine.py` ~455 行, `retriever.py` ~287 行, `migrate_parent_child.py` ~141 行 — `engine.py` 略超 200 行但 plan.md 已在范围说明中注明为整合模块）
- [x] 安全检查完成（SQL 参数化、无硬编码密钥、日志无敏感信息）
- [x] 依赖审计完成（无新增依赖）
- [x] 所有验收标准逐项核对
- [x] 已读取全部 5 个变更文件的完整内容

---

## 8. 风险总结

| 风险 | 当前状态 | 影响 |
|------|----------|------|
| 旧格式文档检索中断 | 检索 SQL 显式过滤 `parent_id IS NOT NULL`，旧格式在迁移前不可检索。**部署顺序要求: 先跑迁移脚本，再部署新检索器。** changelog.md 和 plan.md 已明确此顺序。 | 中 — 已文档化，需运维遵守部署顺序 |
| 父块 flush 后子块入库失败 | `engine.py:445-448` 有 rollback，事务原子性保证无孤儿行。 | 低 — 已覆盖 |
| `_expand_to_parents` 孤儿 parent_id | 静默丢弃（见问题 #2）。当前场景概率极低（无手动删行路径），建议加 WARN 日志。 | 低 |
| 并发不同文档 | 各自独立 session，无竞态。 | 低 — 已覆盖 |
| 模块总行数 | `engine.py` 约 455 行（超过 Vibe Coding 单模块 200 行默认上限）。plan.md 在范围中已说明本模块涉及 5 个文件的集成修改，属合理跨文件模块。 | 信息 — 已在 plan 中注明 |
