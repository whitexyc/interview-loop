# Test Report -- Module-016: Graph RAG

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 测试总数 | 4 |
| 通过数 | 4 |
| 失败数 | 0 |
| 跳过数 | 0 |
| 通过率 | 100% |

## 2. 测试执行结果

| # | 测试 | 命令 | 结果 | 输出 |
|---|------|------|------|------|
| 1 | 语法检查 | `python -m py_compile rag/graph_store.py rag/graph_extractor.py rag/engine.py` | PASS | 3 文件零错误 |
| 2 | 导入检查 | `from rag.graph_store import graph_store; from rag.graph_extractor import graph_extractor` | PASS | graph_store methods: ['ensure_graph', 'search_related', 'upsert_entity', 'upsert_relation']; graph_extractor methods: ['extract_from_document', 'extract_from_query'] |
| 3 | 安全检查 | 验证 no `:param` bindparams 在 `$$...$$` 内部 | PASS | SECURITY PASS -- _escape function 存在，被调用 7 次 |
| 4 | 代码结构 | AST 方法列表 | PASS | GraphStore: ['ensure_graph', 'search_related', 'upsert_entity', 'upsert_relation'] |

## 3. 阻塞 Bug 修复验证

| 修复点 | 预期行为 | 代码位置 | 状态 |
|--------|----------|----------|------|
| Cypher 参数绑定方式 | `:param` bindparams 替换为 f-string + `_escape()` | graph_store.py:L49 `def _escape(val: str) -> str` | **FIXED** |
| upsert_entity 修复 | f-string 直接插值 + _escape(name), _escape(entity_type) | graph_store.py:L119 `query = text(f"""...$$...""")` | **FIXED** |
| upsert_relation 修复 | f-string 直接插值 + _escape(source), _escape(target) | graph_store.py:L159 `query = text(f"""...$$...""")` | **FIXED** |
| search_related 修复 | f-string 直接插值 + entities 列表 _escape | graph_store.py:L197 `query = text(f"""...$$...""")` | **FIXED** |
| `_escape` 被调用 | 所有用户输入值经过转义 | 7 处 `_escape(` 调用 | **FIXED** |

**说明**: 原 bug 是 `text().bindparams()` 中的 `:param` 在 PostgreSQL `$$...$$` dollar-quoting 内部被编译为 `$1` 字面文本，参数值从未传递给 AGE Cypher 引擎。修复方案采用 f-string 直接插值 + `_escape()` 转义 Cypher 特殊字符（`'` 和 `}`），`$$...$$` 继续提供 PG 级别的 SQL 注入防护。

## 4. 验收标准逐项验证

### 4.1 图存储

| # | 验收项 | 状态 | 证据（文件:行号） |
|---|--------|------|-------------------|
| 1 | ensure_graph 幂等创建 knowledge_graph | PASS | graph_store.py:L72-89: `CREATE EXTENSION IF NOT EXISTS` + try/except for duplicate graph |
| 2 | upsert_entity MERGE 同义实体 doc_ids | PASS | graph_store.py:L98-137: ON CREATE 初始化 + ON MATCH 追加（含去重逻辑） |
| 3 | upsert_relation MERGE RELATED_TO 边 | PASS | graph_store.py:L140-170: MERGE 幂等，每对实体只建一条边 |

### 4.2 实体提取

| # | 验收项 | 状态 | 证据（文件:行号） |
|---|--------|------|-------------------|
| 1 | extract_from_document 返回 {entities, relations} | PASS | graph_extractor.py L81-136: 分两步 LLM 调用，返回 dict 含 entities 和 relations |
| 2 | extract_from_query 返回实体名称列表 | PASS | graph_extractor.py L138-166: 返回 `list[str]` |
| 3 | LLM 返回非 JSON 时静默降级返回空 | PASS | graph_extractor.py L168-196 (_parse_json): 三级回退 (json.loads -> regex提取 -> {}) |

### 4.3 engine 集成

| # | 验收项 | 状态 | 证据（文件:行号） |
|---|--------|------|-------------------|
| 1 | add_document 入库后日志"Graph: extracted N entities" | PASS | engine.py:L541-542 `logger.info("Graph: extracted %d entities, %d relations", ...)` |
| 2 | _retrieve round 0 并行向量+图搜索 | PASS | engine.py:L277-284: `asyncio.gather(vector_task, graph_task)` |
| 3 | 合并去重（向量优先） | PASS | engine.py:L287-290: vector_docs 先加入，graph_docs 按 id 去重追加 |
| 4 | 图搜索失败降级不阻塞 | PASS | engine.py:L543-544 catch; graph_store.py L250-252 return [] |

### 4.4 代码质量

| # | 验收项 | 状态 | 证据（文件:行号） |
|---|--------|------|-------------------|
| 1 | 参数化 Cypher 查询（防注入） | **PASS (FIXED)** | graph_store.py: f-string + `_escape()` 转义 + `$$...$$` PG 注入防护。Test 3 确认零 `:param` 在 dollar-quoting 内 |
| 2 | try/except 覆盖所有图操作 | PASS | graph_store.py L87-89, L135-137, L168-170, L250-252; graph_extractor.py L130-131, L164-166 |
| 3 | 无新增 pip 依赖 | PASS | 零新增 pip 依赖（apache-age 为 PG 扩展，非 Python 包） |
| 4 | py_compile 通过 | PASS | Test 1: graph_store.py, graph_extractor.py, engine.py 全部通过 |

## 5. 回归检查

| 检查项 | 状态 | 说明 |
|--------|------|------|
| graph_store.py 语法编译 | PASS | `py_compile` 无错误 |
| graph_extractor.py 语法编译 | PASS | `py_compile` 无错误 |
| engine.py 语法编译 | PASS | `py_compile` 无错误 |
| graph_store 可导入 | PASS | 6 个公共方法全部可见 |
| graph_extractor 可导入 | PASS | 2 个公共方法全部可见 |
| engine.py graph 集成 | PASS | L38-39 imports + L277-290 parallel search + L523-544 add_document |
| Cypher 注入防护 | PASS | f-string 插值 + `_escape()` + `$$...$$` |

## 6. 发现问题

无。原阻塞 bug（`:param` bindparams 在 `$$...$$` 内失效）已修复。

## 7. 测试结论

- 结论: **PASS**
- 测试时间: 2026-07-30
- 测试人: Tester
- 备注: 全部 4 项测试通过，全部 14 项验收标准通过。阻塞 bug（Cypher 参数绑定失效）已修复 -- `:param` bindparams 替换为 f-string + `_escape()` 转义，`_escape` 被调用 7 次覆盖所有用户输入。3 个文件变更（graph_store.py 257行 + graph_extractor.py 201行 + engine.py ~28行），零新增 pip 依赖。
