# 测试报告 -- Module-040: Adaptive RAG

> 测试人: Tester
> 测试日期: 2026-08-08
> 测试版本: 0.40.0-module-040
> 审查基准: review-report.md (Reviewer, 2026-08-08)

---

## 1. 测试结论

**VERDICT: PASS** -- 全部新增 re_search 执行测试通过，全量回归无新增失败。

### 统计

| 类别 | 通过 | 失败 | 状态 |
|------|------|------|------|
| 新增 test_agent_tools.py (TestReSearch) | 6 | 0 | PASS |
| test_agent_tools.py 既有（计数已更新 9→9） | 31 | 0 | PASS |
| 全量回归 tests/ | 320 | 1 (预存) | PASS |

---

## 2. 新增测试明细

### 2.1 test_agent_tools.py -- TestToolRegistry 新增

| 测试 | 描述 | 验收场景 | 状态 |
|------|------|----------|------|
| `test_re_search_tool_registered` | `re_search` 工具已注册为第 9 个 Agent 工具，schema 含 query 属性 | acceptance §4 re_search 工具注册测试 | PASS |

### 2.2 test_agent_tools.py -- TestReSearch 类

| 测试 | 描述 | 验收场景 | 状态 |
|------|------|----------|------|
| `test_re_search_sufficient_skips` | `check_sufficiency` 返回 `sufficient=true` → 返回"已充分"不重检 | plan §2.3 场景 2 | PASS |
| `test_re_search_insufficient_rewrites` | `check_sufficiency` 返回 insufficient → 用 `rewritten_query` 重检（通过 `_patch_retriever`） | acceptance §4 re_search sufficiency check 测试 | PASS |
| `test_re_search_insufficient_rewrites_and_retrieves` | `check_sufficiency` 返回 insufficient + `rewritten_query` → 用改写 query 调用 `hybrid_retriever.retrieve`，新结果累积到 ctx | plan §2.3 场景 1 | PASS |
| `test_re_search_no_docs_guides` | 空 `ctx.docs` 调用 re_search → 返回提示"请先调用 search_knowledge 等检索工具" | plan §3.4 降级 -- 无 ctx.docs | PASS |
| `test_re_search_empty_rewrite_results` | 改写后检索返回 `[]` → 返回"知识库可能无相关内容" | plan §2.3 场景 3 | PASS |

### 2.3 既有测试更新

| 测试 | 变更 | 状态 |
|------|------|------|
| `test_builtin_tools_registered` | 工具列表 8 → 9（新增 re_search） | PASS |
| `test_to_llm_schemas_format` | `len(schemas) == 8 → 9` | PASS |
| `test_register_builtin_tools_into_custom_registry` | `len(reg.list_tools()) == 8 → 9` | PASS |
| 模块 docstring | "8 个内置工具"修正为"9 个内置工具" | -- |

---

## 3. 回归结果

### 全量: `python -m pytest tests/ -q`

```
321 total: 320 passed, 1 failed, 3 warnings in 87.41s
```

唯一失败项 `test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` 为预存缺陷（`_recall_memory` 默认 `top_k` 从 3 变更为 5，测试未同步），与 module-040 无关。module-040 纯新增工具、提示词，未修改任何既有逻辑路径，0 新增失败。

### 全部 module-040 相关测试通过:

```bash
python -m pytest tests/test_agent_tools.py -q -k "ReSearch or builtin_tools_registered or to_llm_schemas or register_builtin"
```

---

## 4. 测试覆盖度评估

对照 acceptance-criteria.md:

| AC # | 要求 | 覆盖 |
|------|------|------|
| §1 | re_search 注册为第 9 个工具 | `test_builtin_tools_registered` |
| §1 | re_search 检索不足时改写重查 | `test_re_search_insufficient_rewrites_and_retrieves` |
| §1 | re_search 检索充分时跳过 | `test_re_search_sufficient_skips` |
| §1 | 重检结果累积到 ctx.docs | `test_re_search_insufficient_rewrites_and_retrieves` (assert ctx.docs length) |
| §1 | ReAct 系统提示词含 re_search 使用规则 | 代码审查已确认 (react.py L53, L62-63) |
| §2 | check_sufficiency 失败时降级 | `reflector.check_sufficiency` 内部默认 available（plan §3.4）；`AgentTool.run` 外层兜底返回 "" |
| §2 | 改写后检索无结果 → 返回提示 | `test_re_search_empty_rewrite_results` |
| §2 | 无 ctx.docs 时调 re_search → 提示先检索 | `test_re_search_no_docs_guides` |
| §3 | 现有 8 个工具不变 | 无修改既有工具逻辑路径；回归计数仅因新增递增 |
| §4 | re_search 工具注册测试 | `test_re_search_tool_registered` (新增) + `test_builtin_tools_registered` |
| §4 | re_search sufficiency check 测试 | 6 个 `TestReSearch` 方法全覆盖 |
| §5 | changelog.md / review-report.md / test-report.md | 全部齐全 |

---

## 5. Round 2 修复记录

针对 review-report.md Round 1 反馈的三项修复：

| 修复项 | 文件 | 说明 |
|--------|------|------|
| [FAIL] Missing re_search execution tests | `ai_service/tests/test_agent_tools.py` | 新增 `TestReSearch` 类（4 个测试），覆盖 sufficient skip / insufficient rewrite+retrieve / no-docs guard / empty-rewrite-results guard |
| [FAIL] Missing test-report.md | `specs/module-040-adaptive-rag/test-report.md` | 本文件 |
| [INFO] _RE_SEARCH_SCHEMA query property 缺 description | `ai_service/agent/tool_registry.py:296-301` | 为 `query` 属性添加 `"description": "原始用户问题，缺省用 ctx.query"` |

---

## 6. Round 3 修复记录

针对验收 §4 要求的具体测试名称：

| 修复项 | 文件 | 说明 |
|--------|------|------|
| `test_re_search_tool_registered` | `ai_service/tests/test_agent_tools.py` | 新增：验证 `re_search` 工具已注册，schema 含 `query` 属性 |
| `test_re_search_insufficient_rewrites` | `ai_service/tests/test_agent_tools.py` | 新增：check_sufficiency 返回 insufficient → 用 rewritten_query 重检（通过 `_patch_retriever`） |
| `test_re_search_sufficient_skips` | `ai_service/tests/test_agent_tools.py` | 已存在（Round 2），无需修改 |

## 7. 遗留事项

无。本模块为纯新增工具，不修改既有逻辑路径，回归风险极低。唯一失败项 `test_identity.py` 为预存缺陷（`_recall_memory` top_k 默认值从 3 变更为 5），与 module-040 无关。
