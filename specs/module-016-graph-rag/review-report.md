# 审查报告 — Module-016: Graph RAG

## 1. 审查结论

- 结论: **FAIL**（不通过 -- 1 个阻塞问题须修复）
- 审查时间: 2026-07-30
- 审查人: Reviewer
- 审查耗时: ~40 分钟

**不通过理由**: AGE Cypher 查询的参数绑定机制存在根本性缺陷。SQLAlchemy `text().bindparams()` 配合 asyncpg 驱动将 `:param` 编译为 `$1` 占位符，但 PostgreSQL 的 `$$...$$` dollar-quoting 会将其视为字面文本，导致 AGE 收到无效的 Cypher 查询（如 `name: $1`），数据库参数值从未传递给 Cypher 引擎。这是一个运行时 bug，会影响所有 3 个查询方法（`upsert_entity`, `upsert_relation`, `search_related`）。

---

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `graph_store.py` | L113-126, L152-159, L195-206 | **AGE Cypher 参数绑定失效**。SQLAlchemy `text().bindparams()` 将 `:name`/`:type`/`:s_name`/`:t_name`/`:names`/`:limit` 编译为 asyncpg 的 `$1`, `$2` 占位符，但这些占位符出现在 `$$...$$` dollar-quoting 内部。PostgreSQL 将 `$$...$$` 内容视为字面文本 —— `$1` 不被当作参数引用，而是作为字面字符串 "$1" 传递给 AGE Cypher 引擎。结果是：(a) AGE 收到语法无效的 Cypher（如 `MERGE (e:Entity {name: $1, type: $2})`）；(b) 实际参数值从未进入 Cypher。数据库引擎配置在 `src/database.py` L12-17 使用标准 `create_async_engine`，无 `literal_binds=True` 选项。 | 阻塞 | **方案 A（推荐）**: 将 Cypher 查询中的 `:param` 替换为 Python f-string 插值，同时对值进行 Cypher 字符转义（转义单引号和花括号）。由于 `$$...$$` 已提供 PostgreSQL 级别的注入保护，只需防范 Cypher 层面的注入。对字符串值执行 `value.replace("'", "\\'").replace("}", "\\}")` 后插入。<br>**方案 B**: 移除 `$$...$$` dollar-quoting，改用标准引号包裹 Cypher 查询，手动转义其中的单引号，然后使用 `text().bindparams()` —— 此时 `:param` 在 dollar-quoting 之外，PG 能正常解析。<br>**方案 C**: 在 `create_async_engine` 中设置 `connect_args={"server_settings": {"literal_binds": "true"}}` （需验证 asyncpg 支持性，且全局启用可能有副作用）。 |

### 2.2 高优先级问题（必须修复）

无额外高优先级问题（问题 #1 已覆盖核心缺陷）。

### 2.3 建议改进（不阻塞，建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 2 | `graph_store.py` | L113-126 | `upsert_entity()` 中 `doc_id_str` 通过 Python 字符串拼接（`'"' + doc_id_str + '"'`）直接插入 Cypher 查询。当前安全因为 `doc_id` 参数类型为 `int`（L91），但若未来接口变更为接受字符串 ID，将产生 Cypher 注入风险。 | 中 | 对 `doc_id` 值做显式的非数字字符过滤：`if not str(doc_id).isdigit(): raise ValueError(...)`。或统一使用方案 A 修复问题 #1 后一并解决。 |
| 3 | `graph_store.py` | L210-222 | `search_related()` 的 `row[0]` 解析逻辑依赖 `agtype` 结果的手动 JSON 解析。AGE 的 agtype 格式并非标准 JSON（可能包含 `::` 类型标注、特殊字符转义等），`json.loads(raw)` 对某些 agtype 输出会失败。当前已通过 `except (json.JSONDecodeError, ValueError, TypeError)` 捕获，但会导致静默丢失有效结果。 | 中 | 使用 AGE 的 `agtype_to_json()` 函数在 SQL 中转换，或在 Python 端实现 agtype 解析器（处理 `"text"::type` 格式）。当前降级策略可接受（丢失部分结果但不抛出异常）。 |
| 4 | `graph_store.py` | L77-83 | `ensure_graph()` 的 `create_graph()` 调用使用 f-string `f"SELECT create_graph('{GRAPH_NAME}')"` —— GRAPH_NAME 是模块常量 (`"knowledge_graph"`)，当前安全，但与文件中其他查询使用 `bindparams` 的模式不一致。如果未来 GRAPH_NAME 可配置化，将引入 SQL 注入。 | 低 | 使用 `text("SELECT create_graph(:name)").bindparams(name=GRAPH_NAME)` 保持一致性。 |
| 5 | `graph_extractor.py` | L116-126 | `extract_from_document` 分两次 LLM 调用（实体 → 关系），串行执行。如果第一步提取实体耗时 3s，第二步提取关系又 3s，总计 6s。两次调用独立（关系提取仅依赖第一步结果），但第二步可用更轻量的 prompt 或批量提取。 | 低 | 非阻塞——当前方案在 docstring 中已说明设计理由（L15-18）。若后续发现延迟过高，可考虑第一步成功后并发：实体 prompt + 关系 prompt 同时发送（关系 prompt 不依赖实际实体列表，只依赖文档）。 |

---

## 3. plan.md 技术方案逐项核对

### 3.1 AGE 图模型 (plan 1.1)

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| 图名 `knowledge_graph` | graph_store.py L45 | PASS | 模块级常量 |
| 节点 `Entity` (name, type, doc_ids) | graph_store.py L115 (MERGE Entity) | PASS | |
| 边 `RELATED_TO` | graph_store.py L156 (MERGE RELATED_TO) | PASS | 统一关系类型 |

### 3.2 新增文件 (plan 1.2)

**graph_store.py:**
| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| ensure_graph() | L60-89 | PASS | CREATE EXTENSION + LOAD 'age' + SET search_path + create_graph |
| upsert_entity() | L91-132 | PASS | MERGE Entity with ON CREATE/ON MATCH doc_ids merge logic |
| upsert_relation() | L134-165 | PASS | MERGE RELATED_TO edge |
| search_related() | L167-252 | PASS | 两步查询: Cypher traverse → SQL JOIN documents |

**graph_extractor.py:**
| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| extract_from_document(content) → {entities, relations} | L81-136 | PASS | 分两步 LLM 调用 |
| extract_from_query(query) → [entity_names] | L138-166 | PASS | 逗号分隔解析 |
| GraphExtractor 类 | L71-200 | PASS | |

### 3.3 engine.py 集成 (plan 1.3)

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| add_document 后提取实体+关系→AGE | engine.py L521-544 | PASS | after session.commit, in try/except |
| _retrieve round 0 并行向量检索+图搜索 | engine.py L276-290 | PASS | `asyncio.gather(vector_task, graph_task)` |
| 合并去重（向量优先） | engine.py L287-290 | PASS | vector_docs first, graph_docs dedup by id |
| import graph_store + graph_extractor | engine.py L38-39 | PASS | |

### 3.4 文件清单 (plan 2)

| # | 文件 | 操作 | 状态 | 备注 |
|---|------|------|------|------|
| 1 | `ai_service/rag/graph_store.py` | 新建 | PASS | 257 行 |
| 2 | `ai_service/rag/graph_extractor.py` | 新建 | PASS | 201 行 |
| 3 | `ai_service/rag/engine.py` | 修改 | PASS | +2 imports, ~26 lines graph integration |

---

## 4. 验收标准核对

### 4.1 图存储

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| ensure_graph 幂等创建 knowledge_graph | graph_store.py L69-84 | PASS | `CREATE EXTENSION IF NOT EXISTS` + try/except for duplicate graph name |
| upsert_entity MERGE 同义实体 doc_ids | graph_store.py L113-126 | PASS | ON CREATE 初始化 + ON MATCH 追加（含去重逻辑） |
| upsert_relation MERGE RELATED_TO 边 | graph_store.py L152-159 | PASS | MERGE 幂等，每对实体只建一条边 |

### 4.2 实体提取

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| extract_from_document 返回 {entities, relations} | graph_extractor.py L133-136 | PASS | |
| extract_from_query 返回实体名称列表 | graph_extractor.py L138-166 | PASS | 返回 `list[str]`，最多 10 个 |
| LLM 返回非 JSON 时静默降级返回空 | graph_extractor.py L168-196 (_parse_json) | PASS | 三级回退: json.loads → 提取{...} → 返回{} |

### 4.3 engine 集成

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| add_document 入库后日志"Graph: extracted N entities" | engine.py L541-542 | PASS | `logger.info("Graph: extracted %d entities, %d relations", ...)` |
| _retrieve round 0 并行向量+图搜索 | engine.py L276-290 | PASS | `asyncio.gather()` 并行执行 vector_task + graph_task |
| 合并去重（向量优先） | engine.py L287-290 | PASS | vector_docs 先加入，graph_docs 按 id 去重后追加 |
| 图搜索失败降级不阻塞 | engine.py L543-544 (add_document); graph_store.py L250-252 (search_related) | PASS | 图搜索返回 []，异常全部 catch |

### 4.4 代码质量

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 参数化 Cypher 查询（防注入） | graph_store.py | **FAIL** | 见阻塞问题 #1。`:param` 在 `$$...$$` 内部，编译为 `$1` 字面文本，未实际传参。 |
| try/except 覆盖所有图操作 | graph_store.py L66-89, L105-132, L146-165, L186-252 | PASS | 所有公共方法含顶层 try/except |
| 无新增 pip 依赖 | requirements.txt | PASS | 仅使用 sqlalchemy + json + asyncio（均已安装） |
| py_compile 通过 | graph_store.py, graph_extractor.py | 待验证 | 语法层面无可见错误 |

---

## 5. 正确性分析

### 5.1 AGE Cypher 参数绑定问题（详细）

**问题根源链**：

```
Python ─── text("...$$...:name...$$...").bindparams(name=value)
   │
   ▼ 编译
SQLAlchemy ─── :name → $1 (asyncpg 占位符)
   │
   ▼ 发送给 PG
PostgreSQL ─── 解析 SQL:
   SELECT * FROM cypher('knowledge_graph', $$ ... $1 ... $$) AS (...)
                                    ^^^^^^^^^  dollar-quoted 区域
   $1 在 dollar-quoting 内部 → 视为字面文本 "$1"
   │
   ▼ Cypher 引擎收到
AGE ─── MERGE (e:Entity {name: $1, type: $2}) ...
         $1, $2 不是合法的 Cypher 值 → 语法错误或行为异常
```

**不生效的方法**: `upsert_entity` (L113-126), `upsert_relation` (L152-159), `search_related` (L195-206)

**验证**: `src/database.py` L12-17 使用标准 `create_async_engine`，无 `literal_binds=True` 配置。grep 整个 `ai_service/` 目录确认零 `literal_binds` 引用。

**唯一未受影响的方法**: `ensure_graph()` (L60-89) —— 其查询不含参数，只有常量。

### 5.2 并行合并逻辑

```python
# engine.py L276-290
if round_num == 0:
    query_entities = await graph_extractor.extract_from_query(query)
    vector_task = asyncio.wait_for(
        hybrid_retriever.retrieve(search_text, top_k=top_k), timeout=15)
    graph_task = graph_store.search_related(query_entities, top_k=top_k)
    vector_docs, graph_docs = await asyncio.gather(vector_task, graph_task)
    # 合并: 向量结果优先，图结果追加去重
    docs = list(vector_docs) if vector_docs else []
    for gd in (graph_docs or []):
        if gd.get("id") and gd["id"] not in {d.get("id") for d in docs}:
            docs.append(gd)
```

- `asyncio.gather` 并行执行，如果一个失败另一个仍继续（取决于异常处理）。PASS
- `vector_task` 包裹在 `asyncio.wait_for` 中（含超时），但 `graph_task` 未包裹。如果图搜索卡住，整个 round 0 会被阻塞。graph_store.search_related 内部无超时控制。这是个小缺陷但非阻塞（search_related 是标准 SQL 查询，不太可能卡死）。NOTE
- 去重使用 set comprehension `{d.get("id") for d in docs}` -- 正确。PASS

### 5.3 add_document 图写入时机

```python
# engine.py L521-544
await session.commit()          # ← 先提交文档到 PG
try:
    await graph_store.ensure_graph()
    extraction = await graph_extractor.extract_from_document(content)
    ...
    await graph_store.upsert_entity(name, ent_type, int(parent_id))
    ...
    await graph_store.upsert_relation(src, tgt)
except Exception as e:
    logger.warning("Graph 提取/写入失败，跳过: %s", e)
```

- 图写入在文档提交之后，即使失败也不回滚文档。正确——符合"失败不阻塞入库"。PASS
- 图写入在独立的 try/except 中，异常仅产生 warning。PASS
- **潜在问题**: `parent_id` 是父块的 DB ID，如果 `parent_objs[0]` 在 session.commit 之前尚未分配 ID（MySQL/PostgreSQL auto-increment 在 flush 后分配），此处 `await session.flush()` 已在 L491 执行，确保 ID 有效。PASS

### 5.4 graph_store.search_related 结果分数

```python
# graph_store.py L244
"hybrid_score": 0.6,  # 默认图检索分数（低于向量检索）
```

- 硬编码分数 0.6，低于向量检索的典型分数（0.7-0.95）。这确保在最终结果中，向量检索的文档通常排在前面。设计合理。PASS
- 但该分数在 engine.py 的低分过滤中（`min_score >= 0.6`）可能被淘汰。注释说明了"低于向量检索"的意图。可接受。PASS

---

## 6. 代码质量评估

### 6.1 注释覆盖率

| 检查项 | 状态 | 说明 |
|--------|------|------|
| graph_store.py 模块 docstring | PASS | L1-32: 32 行 docstring 含位置、依赖、4 项设计决策 |
| graph_extractor.py 模块 docstring | PASS | L1-27: 27 行 docstring 含 3 项设计决策 |
| 类 docstring | PASS | GraphStore L48-58, GraphExtractor L71-79 |
| 方法 docstring | PASS | 所有公共方法含 Args/Returns |
| 行内注释 | PASS | 分步注释（Step 1, Step 2, etc.） |

### 6.2 命名规范

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 文件名 snake_case | PASS | `graph_store.py`, `graph_extractor.py` |
| 类名 PascalCase | PASS | `GraphStore`, `GraphExtractor` |
| 方法名 snake_case | PASS | `ensure_graph`, `upsert_entity`, `extract_from_document` |
| 常量 UPPER_SNAKE | PASS | `GRAPH_NAME`, `_ENTITY_PROMPT`, `_RELATION_PROMPT`, `_QUERY_ENTITY_PROMPT` |
| 单例变量 | PASS | `graph_store`, `graph_extractor` |

### 6.3 代码长度

| 检查项 | 行数 | 上限 | 状态 |
|--------|------|------|------|
| graph_store.py | 257 | 500 | PASS |
| graph_extractor.py | 201 | 500 | PASS |
| engine.py graph 集成 (新增) | ~28 | 200 (模块) | PASS |
| ensure_graph() | 30 | 50 | PASS |
| upsert_entity() | 42 | 50 | PASS |
| upsert_relation() | 32 | 50 | PASS |
| search_related() | 86 | 50 | **超标** |
| extract_from_document() | 56 | 50 | **超标** |
| extract_from_query() | 29 | 50 | PASS |
| _parse_json() | 28 | 50 | PASS |

`search_related()` 86 行：包含 Cypher 查询(prompt 构造) + agtype 解析 + SQL JOIN 文档查询 + 格式化。建议拆分 agtype 解析为独立方法。`extract_from_document()` 56 行：包含文档截断 + 实体提取 + 关系提取。可接受（两个 LLM 调用的自然流程）。

### 6.4 异常处理检查

| 方法 | 异常路径 | 降级策略 | 状态 |
|------|----------|----------|------|
| ensure_graph() | L87-89 | return False | PASS |
| upsert_entity() | L130-132 | return False | PASS |
| upsert_relation() | L163-165 | return False | PASS |
| search_related() | L250-252 | return [] | PASS |
| extract_from_document() | L130-131 | return {"entities": [], "relations": []} | PASS |
| extract_from_query() | L164-166 | return [] | PASS |
| _parse_json() | L183-196 | 3 级回退 → {} | PASS |
| engine.py graph block | L543-544 | warning log, 继续 | PASS |

**结论**: 所有方法异常隔离完整，降级不传播。PASS。

---

## 7. 安全评估

- [x] **Cypher 注入防护**: FAIL（见阻塞问题 #1）。`:param` bindparams 在 `$$...$$` 内部失效，参数值未传递给 Cypher。修复后（方案 A：f-string + Cypher 转义）需要重新评估。
- [x] **SQL 注入防护**: PASS。graph_store.py L229-234 使用 SQLAlchemy ORM `select(Document).where(Document.id.in_(...))`，自动参数化。
- [x] **LLM Prompt 注入**: PASS。用户 query 插入 prompt 模板，由 LLM 内部处理，无注入向量。
- [x] **无硬编码密码**: PASS。数据库连接从 settings 读取。
- [x] **无新依赖**: PASS。零新增 pip 依赖。

### 安全追加说明（修复后）

若采用**方案 A**（f-string + Cypher 转义）修复问题 #1，需对以下值进行转义：
- `upsert_entity`: `name` → 转义 `'` 和 `}`
- `upsert_entity`: `entity_type` → 转义 `'` 和 `}`
- `upsert_relation`: `source`, `target` → 转义 `'` 和 `}`
- `search_related`: entity names → 每个 name 转义 `'`

`$$...$$` 已提供 PG 级 SQL 注入保护。修复后需防范的是 Cypher 层面的注入（如用户实体名包含 `'}) RETURN 1;//`）。

---

## 8. 依赖审计

| 依赖 | 操作 | 状态 |
|------|------|------|
| apache-age (PostgreSQL 扩展) | 预安装（不在 Python 依赖中） | 无需 pip |
| 其他 Python 包 | 无新增 | PASS |

**ADR 需求**: 建议记录 ADR 说明选择 Apache AGE 作为图存储的原因、MERGE 幂等策略、以及 `$$...$$` dollar-quoting 与 asyncpg 参数绑定的兼容性问题及解决方案。

---

## 9. 架构评估

- **分层正确性**: PASS。`graph_store.py`（数据访问层）+ `graph_extractor.py`（AI 集成层）+ `engine.py`（编排层），层次清晰，单向依赖。
- **图模型设计**: 简化的 Entity + RELATED_TO 模型适合 MVP 阶段。没有过度设计（不需要属性图、标签等高级特性）。
- **引擎集成方式**: 并行执行 + 降级策略正确。HyDE + 向量检索 + 图检索的使用优先级合理（向量优先，图补充）。
- **单例模式**: `graph_store` + `graph_extractor` 均为全局单例，与项目现有模式一致。

---

## 10. 审查检查清单

- [x] 已读取 plan.md 和 acceptance-criteria.md
- [x] 已阅读完整变更文件: graph_store.py(257行), graph_extractor.py(201行), engine.py(graph sections)
- [x] plan.md 技术方案逐项核对（全部 PASS）
- [x] 验收标准逐项核对（1 项 FAIL: 参数化查询）
- [x] 正确性分析完成（参数绑定、并行合并、写入时机、分数策略）
- [x] 安全问题深度分析（Cypher 注入风险详细追踪）
- [x] 命名符合规范
- [x] 异常处理全面
- [x] 代码长度（2 个方法超标的合理解释）
- [x] 依赖审计（无新增 pip 依赖）
- [x] 每个问题都标注了文件路径 + 行号
- [x] review-report.md 已输出

---

## 11. 总结

M16 Graph RAG 在架构设计、模块分层、异常隔离方面质量很高 -- 32 行模块 docstring 解释清晰，所有方法有完整的 try/except 降级，engine.py 集成精准（并行检索 + 向量优先合并）。但存在 1 个阻塞级别的参数绑定 bug：

**根本原因**: AGE Cypher 查询使用 PostgreSQL `$$...$$` dollar-quoting 包裹 Cypher 语句，同时使用 SQLAlchemy `text().bindparams()` 传参。asyncpg 将 `:param` 编译为 `$1` 占位符，但 `$1` 在 dollar-quoted 区域中被 PostgreSQL 视为字面文本，参数值从未进入 Cypher 引擎。

**影响范围**: `upsert_entity`, `upsert_relation`, `search_related` 三个方法全部受影响。`ensure_graph` 不受影响（无参数）。

**修复路径**: 将 `:param` 替换为 Python f-string 插值 + Cypher 字符转义。`$$...$$` 已提供 PG 级别的注入保护，只需对 Cypher 层面的特殊字符（`'`, `}`）进行转义。

修复后本模块应能 PASS。
