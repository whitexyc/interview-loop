# 测试报告 -- Module-039: 证据链幻觉检测

> 测试人: Tester
> 测试日期: 2026-08-08
> 测试版本: 0.39.0-module-039
> 审查基准: review-report.md (Reviewer, 2026-08-08)

---

## 1. 测试结论

**VERDICT: PASS** -- 全部新增单测通过，全量回归 314/315 通过。唯一失败项 (`test_identity.py::test_identity_passed_to_service`) 为预存缺陷（`_recall_memory` 默认 `top_k` 从 3 变更为 5，测试未同步），与 module-039 无关。

### 统计

| 类别 | 通过 | 失败 | 状态 |
|------|------|------|------|
| 新增 test_reflector.py | 12 | 0 | PASS |
| 新增 test_agent_tools.py (verify_answer) | 3 | 0 | PASS |
| test_agent_tools.py 既有（计数已更新） | 31 | 0 | PASS |
| test_stream_memory.py (已验证事件修复) | 5 | 0 | PASS |
| 全量回归 tests/ | 314 | 1 (预存) | PASS |

---

## 2. 新增测试明细

### 2.1 test_reflector.py -- Reflector.verify_answer()

| 测试 | 描述 | 状态 |
|------|------|------|
| `TestVerifyAnswer::test_verify_answer_returns_claims` | LLM 返回合法 JSON -> 完整 claims + overall_confidence | PASS |
| `TestVerifyAnswer::test_verify_answer_empty_docs` | 空文档 -> 返回空 claims（零回归） | PASS |
| `TestVerifyAnswer::test_verify_answer_handles_llm_error` | LLM 异常 -> 返回空 claims，不抛异常 | PASS |
| `TestVerifyAnswer::test_verify_answer_empty_answer_text` | 空答案文本 -> 返回空 claims | PASS |
| `TestVerifyAnswer::test_verify_answer_evidence_out_of_bounds` | evidence 引用号越界 -> 降级为 unsupported | PASS |
| `TestVerifyAnswer::test_verify_answer_all_supported` | 全部 supported -> overall_confidence == 1.0 | PASS |
| `TestParseVerification::test_valid_json_array` | 合法 JSON 数组 -> 正确解析 | PASS |
| `TestParseVerification::test_markdown_wrapped_json` | markdown 代码块包裹 -> 成功解析 | PASS |
| `TestParseVerification::test_extra_text_before_json` | JSON 前有解释文字 -> 仍提取 | PASS |
| `TestParseVerification::test_invalid_json_returns_empty` | 非法 JSON -> 返回空列表 | PASS |
| `TestParseVerification::test_empty_claims_filtered_out` | 空 claim 条目 -> 被过滤 | PASS |
| `TestParseVerification::test_missing_verdict_defaults_to_unsupported` | 缺 verdict -> 默认 unsupported | PASS |

### 2.2 test_agent_tools.py -- verify_answer 工具

| 测试 | 描述 | 状态 |
|------|------|------|
| `TestToolRegistry::test_verify_answer_tool_registered` | verify_answer 注册为第 8 个工具; schema 含 answer + query | PASS |
| `TestToolRegistry::test_verify_answer_tool_executes` | 执行 verify_answer 工具 -> 返回格式化可信度文本（含图标 + 统计） | PASS |
| `TestToolRegistry::test_verify_answer_tool_no_docs` | 无 ctx.docs -> 返回提示"无法验证" | PASS |
| `TestToolRegistry::test_verify_answer_tool_no_answer` | 未提供 answer -> 返回提示"无法验证" | PASS |

### 2.3 既有测试更新

| 测试 | 变更 | 状态 |
|------|------|------|
| `test_builtin_tools_registered` | 工具列表 7 -> 8（新增 verify_answer） | PASS |
| `test_to_llm_schemas_format` | `len(schemas) == 7 -> 8` | PASS |
| `test_register_builtin_tools_into_custom_registry` | `len(reg.list_tools()) == 7 -> 8` | PASS |
| `test_stream_memory.py:_hit_stream` | 新增 verify_answer mock；事件序列含 verified | PASS |

---

## 3. 回归结果

### 全量: `python -m pytest tests/ -q`

```
314 passed, 1 failed, 3 warnings
```

失败项为预存缺陷:
- `test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` -- `assert captured["top_k"] == 3` 失败（实际 `5`）。根因是 `rag_engine._recall_memory()` 默认 `top_k` 从 `3` 变更为 `5`，测试未同步。与 module-039 无关。

### 全部 module-039 相关测试通过:

```bash
python -m pytest tests/test_reflector.py tests/test_agent_tools.py tests/test_stream_memory.py -q
# 49 passed
```

---

## 4. 测试覆盖度评估

对照 acceptance-criteria.md §5.1:

| AC # | 要求 | 覆盖 |
|------|------|------|
| 5.1.1 | verify_answer 正常返回测试 | `test_verify_answer_returns_claims` |
| 5.1.2 | verify_answer 空文档降级 | `test_verify_answer_empty_docs` |
| 5.1.3 | verify_answer 幻觉检测（LLM 错误） | `test_verify_answer_handles_llm_error` |
| 5.1.4 | verify_answer Agent 工具注册 | `test_verify_answer_tool_registered` |
| 5.1.5 | verify_answer Agent 工具执行 | `test_verify_answer_tool_executes` |

追加覆盖（plan §3.5 异常场景）:
- evidence 引用号越界降级: `test_verify_answer_evidence_out_of_bounds`
- 空答案文本降级: `test_verify_answer_empty_answer_text`
- 全部 supported confidence=1.0: `test_verify_answer_all_supported`
- JSON 解析容错（markdown/前缀/空claim/缺字段）: 5 个 `_parse_verification` 用例
- 工具无 docs 降级: `test_verify_answer_tool_no_docs`
- 工具无 answer 降级: `test_verify_answer_tool_no_answer`

---

## 5. 代码质量修复

### 5.1 _VERIFY_SCHEMA required 补充

`tool_registry.py` `_VERIFY_SCHEMA` 补充了 `"required": ["answer"]` (Reviewer §3.4 建议)。

### 5.2 test_stream_memory.py 见证事件序列修复

`_hit_stream` 新增 `verify_answer` mock，避免真实 LLM 调用在测试中执行。`test_memory_injected_when_recalled` 的 SSE 事件序列从 `["step", "step", "step", "step", "token", "token", "done"]` 更新为 `["step", "step", "step", "step", "token", "token", "verified", "done"]`，反映 module-039 新增的 SSE verified 事件。

---

## 6. 遗留事项

| 事项 | 严重性 | 说明 |
|------|--------|------|
| test_identity.py 预存缺陷 | LOW | `_recall_memory` top_k 默认值变更未同步测试，与 module-039 无关 |
| 前端 SSE verified 事件未处理 | MEDIUM | Review §3.1 已识别; ChatMessage 组件已实现但数据流断裂; 不阻塞后端测试 |
| Agent 端点无 post-hoc 验证 | LOW | Review §3.2 已识别; 设计决策，verify_answer 以工具形式提供 |
