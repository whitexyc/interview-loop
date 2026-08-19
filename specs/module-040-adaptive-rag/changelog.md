# Module-040 Adaptive RAG 变更记录

> 2026-08-08 | white

---

## 概述

为 Agent ReAct 路径新增 `re_search` 工具，填补检索自校正能力缺口（此前 `reflector.check_sufficiency` 仅在 engine.py 固定流水线中使用，Agent 路径完全未调用）。

---

## 修改文件

### 1. `ai_service/agent/tool_registry.py` — 新增 re_search 工具

- **新增 `_re_search` 函数**（227-252 行）：调 `reflector.check_sufficiency` 判断 ctx.docs 是否充分，不充分则用 `rewritten_query` 重新混合检索，新结果按 id 去重累积到 ctx.docs。
- **新增 `_RE_SEARCH_SCHEMA`**（296-301 行）：`{type:"object", properties:{query:{type:"string"}}}`，required 为空（query 可选，缺省用 ctx.query）。
- **注册为第 9 个工具**（354-358 行）：`reg.register("re_search", ...)`。
- **降级处理**：无 ctx.docs 提示先检索；check_sufficiency 返回充分提示无需重检；改写后仍无结果提示知识库无相关内容；check_sufficiency 自身失败由 reflector 内部默认充分。
- **文档更新**：docstring 从"8 个内置工具"改为"9 个内置工具"。

### 2. `ai_service/agent/react.py` — 系统提示词更新

- **工具列表**（53 行）：加入 `re_search: 检索不足时自动改写查询重检`。
- **使用规则**（62-63 行）：新增第 5 条——检索结果不相关时调用 re_search 自动改写查询重检，无需手动换 search_fts/search_vector。

### 3. `ai_service/tests/test_agent_tools.py` — 测试适配

- `test_builtin_tools_registered`：期望工具列表从 8 个扩展到 9 个（含 re_search）。
- `test_to_llm_schemas_format`：schema 数量断言从 8 更新为 9。
- `test_register_builtin_tools_into_custom_registry`：工具数量断言从 8 更新为 9。
- 模块 docstring："7 个内置工具"修正为"9 个内置工具"。

---

## 验收对照

| 场景 | 状态 |
|------|------|
| 场景 1：Agent 检索结果不足 → re_search 改写重检累积 | 通过（_re_search 实现） |
| 场景 2：检索已充分 → 返回"已充分"不重检 | 通过（sufficient=true 分支） |
| 场景 3：改写后仍无结果 → 返回无结果提示 | 通过（空 docs 分支） |
| 场景 4：不影响现有工具 | 通过（仅新增，未修改现有工具逻辑） |

---

## 风险评估

- **低风险**：纯新增工具，不修改现有 8 个工具的任何逻辑。
- **依赖服务**：reflector.check_sufficiency（已稳定）、hybrid_retriever（已稳定）。
- **测试回归**：现有 9 个工具注册 / schema 计数测试已同步更新。

---

## Round 2 修复记录（2026-08-08，Review 反馈修复）

### 修复项 1：新增 re_search 执行测试（`ai_service/tests/test_agent_tools.py`）

Review 指出 acceptance criteria §4 要求 "re_search sufficiency check 测试"，但仅有注册列表测试，缺少专用执行测试。

新增 `TestReSearch` 类（4 个测试）：

| 测试 | 覆盖验收场景 |
|------|-------------|
| `test_re_search_sufficient_skips` | check_sufficiency 返回 sufficient=true → 返回"已充分"不重检 |
| `test_re_search_insufficient_rewrites_and_retrieves` | check_sufficiency 返回 insufficient + rewritten_query → 用改写 query 检索，新结果累积到 ctx |
| `test_re_search_no_docs_guides` | 空 ctx.docs 调用 re_search → 返回提示引导先检索 |
| `test_re_search_empty_rewrite_results` | 改写后检索返回 [] → 返回"知识库可能无相关内容" |

测试模式遵循 `verify_answer` 既有风格（`test_verify_answer_tool_executes` / `test_verify_answer_tool_no_docs` / `test_verify_answer_tool_no_answer`），mock `reflector.check_sufficiency` + `hybrid_retriever.retrieve`。

### 修复项 2：创建 test-report.md（`specs/module-040-adaptive-rag/test-report.md`）

Review 指出 acceptance criteria §5 要求 test-report.md 与 changelog.md、review-report.md 并列。已创建完整测试报告，包含测试统计、新增测试明细、回归结果、覆盖度评估、Round 2 修复记录。

### 修复项 3：_RE_SEARCH_SCHEMA query 属性添加 description（`ai_service/agent/tool_registry.py`）

Review 指出 `_RE_SEARCH_SCHEMA` 的 `query` 属性缺少 `description`，与其他所有 schema 不一致。添加 `"description": "原始用户问题，缺省用 ctx.query"`，与 `_SEARCH_SCHEMA` 的 `"description": "检索关键词（缺省用原始问题）"` 风格对齐。

---

## Round 3 修复记录（2026-08-08，Review 反馈修复）

Review 指出两项缺陷：

### 修复项 1：补跑全量回归测试 + 更新 test-report.md

Round 2 的 test-report.md 标记全量回归为"待执行"。已执行 `python -m pytest tests/ -q`，结果：**319 total, 318 passed, 1 failed**（90.22s）。唯一失败项 `test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` 为预存缺陷（`_recall_memory` 默认 `top_k` 从 3 变更为 5，测试未同步），与 module-040 无关。4 个新增 TestReSearch 测试全部通过，module-040 纯新增工具、提示词，未修改任何既有逻辑路径，0 新增失败。test-report.md 的回归结果行和"全量回归"小节已更新为实际执行数据。

### 修复项 2：更新 rag-architecture.md 与 rag-agent-roadmap.md 记忆文件

Acceptance criteria SS5 要求记忆文件反映 module-040 完成：

- **rag-architecture.md**：在 module-039 证据链验证条目后新增 "Adaptive RAG re_search 工具 (module-040)" 条目，记录 re_search 工具架构决策、降级路径、测试结果（4 新增通过，318/319 全量回归）。
- **rag-agent-roadmap.md**：在"已完成"列表新增 module-040 条目；将"待发散"中的 "Adaptive-RAG 评估落地" 更新为 "Adaptive-RAG 深化 — module-040 已完成 re_search 工具基础落地，后续 CRAG 分级自纠/Adaptive 路径门控见 P1"。


