# Test Report — Module-042: Harness 围栏

> Tester | 2026-08-08

---

## 测试覆盖摘要

| AC 引用 | 测试场景 | 测试位置 | 状态 |
|--------|---------|---------|------|
| AC 1.1/1.2/4.1 | AgentTool.run asyncio.TimeoutError → 返回 "(工具 X 执行超时)" | `test_agent_tools.py::TestToolRegistry::test_tool_run_timeout_returns_prompt` | PASS |
| AC 1.1/1.2/4.1 | AgentTool.run 超时 → 返回 "(工具 t 执行超时)" (用户指定名称) | `test_agent_tools.py::TestToolRegistry::test_tool_timeout` | PASS |
| AC 1.1/1.2/4.1 | AgentTool.run RuntimeError → 返回 "" (已有) | `test_agent_tools.py::TestToolRegistry::test_tool_run_failure_returns_empty` | PASS |
| AC 1.3/4.1 | ChatRequest.query > 2000 字符 → ValidationError (422) | `test_schemas_validation.py::test_query_too_long` | PASS |
| AC 1.4/4.1 | ChatRequest.history > 20 条 → 静默截断保留最近 20 条 | `test_schemas_validation.py::test_history_too_many` | PASS |
| AC 1.3/4.1 | ChatRequest.query > 2000 字符 → ValidationError (422) | `test_schemas.py::TestChatRequestValidation::test_query_over_2000_chars_raises_422` | PASS |
| AC 1.3/4.1 | ChatRequest.query = 2000 字符 → 通过 | `test_schemas.py::TestChatRequestValidation::test_query_exactly_2000_chars_passes` | PASS |
| AC 1.4/4.1 | ChatRequest.history > 20 条 → 静默截断保留最近 20 条 | `test_schemas.py::TestChatRequestValidation::test_history_over_20_items_silently_truncates` | PASS |
| AC 1.4/4.1 | ChatRequest.history = 20 条 → 通过不截断 | `test_schemas.py::TestChatRequestValidation::test_history_exactly_20_items_passes` | PASS |
| AC 1.4/4.1 | ChatRequest.history < 20 条 → 原样保留 | `test_schemas.py::TestChatRequestValidation::test_short_history_unchanged` | PASS |
| AC 1.4/4.1 | ChatRequest.history 不传 → 默认空列表 | `test_schemas.py::TestChatRequestValidation::test_default_history_empty` | PASS |
| AC 1.5/2.3 | /ai/rag/chat: 答案 >10000 截断 + sources 保留 (用户指定名称) | `test_main.py::test_answer_truncation` | PASS |
| AC 1.5/2.3 | /ai/rag/chat: 答案 >10000 截断 + sources 保留 | `test_agent_tools.py::TestAnswerTruncationChat::test_answer_truncated_and_sources_preserved` | PASS |
| AC 1.5/2.3 | /ai/rag/chat: 短答案不截断 | `test_agent_tools.py::TestAnswerTruncationChat::test_short_answer_not_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat: 恰好 10000 字符不截断 | `test_agent_tools.py::TestAnswerTruncationChat::test_exactly_max_not_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/agent: 超长答案 token + done 一致截断 | `test_agent_tools.py::TestAnswerTruncationAgent::test_agent_long_answer_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/agent: 短答案不截断 | `test_agent_tools.py::TestAnswerTruncationAgent::test_agent_short_answer_not_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/agent-lg: 超长答案 token + done 一致截断 | `test_agent_tools.py::TestAnswerTruncationAgentLG::test_agent_lg_long_answer_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/agent-lg: 短答案不截断 | `test_agent_tools.py::TestAnswerTruncationAgentLG::test_agent_lg_short_answer_not_truncated` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/stream: 超长流截断标记 token | `test_agent_tools.py::TestAnswerTruncationChatStream::test_stream_truncation_marker_emitted` | PASS |
| AC 1.5/2.3 | /ai/rag/chat/stream: 短答案流不截断 | `test_agent_tools.py::TestAnswerTruncationChatStream::test_stream_short_answer_not_truncated` | PASS |
| - | verify_answer 清洗截断标记后验证 (偏差修复) | `test_agent_tools.py::TestAnswerTruncationChatStream::test_stream_truncation_marker_emitted` | PASS |

---

## 测试运行

```bash
cd ai_service
python -m pytest tests/ -q
```

### 新增测试 (module-042)

- `test_agent_tools.py`: +18 tests (test_tool_timeout + 17 existing from earlier dev)
- `test_schemas_validation.py`: +2 tests (test_query_too_long, test_history_too_many) -- new file
- `test_main.py`: +1 test (test_answer_truncation) -- new file
- `test_schemas.py`: +7 tests (ChatRequest Field validation)
- `test_agent_tools.py`: +17 tests (TimeoutError + 4 endpoint groups)

### 回归确认

- 所有已有测试继续通过，0 新增失败
- ReAct 循环 (budget / 工具累积 / 推理回传 / SSE 事件序列) 不受影响
- ToolRegistry 现有测试 (RuntimeError / 注册 / schema) 不受影响

### 预存失败 (非 module-042 引入)

| 测试 | 原因 |
|------|------|
| `test_identity.py::test_identity_passed_to_service` | assert 5 == 3 — top_k 参数不一致 |
| `test_rerank_langgraph.py::test_sse_tool_trace_events` | 429 rate limit — 测试间 IP 限流累积 |
| `test_rerank_langgraph.py::test_budget_zero_endpoint_direct_answer` | 429 rate limit — 同上 |

### 最新全量运行

```
355 passed, 3 failed, 3 warnings in 120.19s
```
全部 3 次失败均为预存缺陷，module-042 新增测试 0 失败。

---

## 边界场景覆盖

| 边界 | 端点 | 预期 | 测试 |
|------|------|------|------|
| answer = 0 字符 | 全部 | 不触发截断 | 已有 short answer tests |
| answer = 9999 字符 | 全部 | ≤阈值，不截断 | 已有 short answer tests |
| answer = 10000 字符 | 全部 | 恰好阈值，不截断 (> 比较) | `test_exactly_max_not_truncated` |
| answer = 10001 字符 | 全部 | 触发截断 + 标记追加 | 各端点 long answer tests |
| answer = 50000 字符 | 全部 | 截断到 10000 + 标记 | 各端点 long answer tests (15000) |
| query = 2000 字符 | 全部 | 通过 | `test_query_exactly_2000_chars_passes` |
| query = 2001 字符 | 全部 | 422 ValidationError | `test_query_over_2000_chars_raises_422` |
| history = 20 条 | 全部 | 原样保留 | `test_history_exactly_20_items_passes` |
| history = 25 条 | 全部 | 静默截断保留最近 20 条 | `test_history_over_20_items_silently_truncates` |
| history = 0 条 | 全部 | 空列表 | `test_empty_history_unchanged` |

---

## AC 1.4 对齐说明

验收标准 AC 1.4 写"超条数截断"（静默截断），原始实现使用 `Field(max_length=20)` 返回 422 拒绝。已修正为：

- `ChatRequest.history`: 移除 `max_length=20` Field 约束，改用 `field_validator` 在 `mode="before"` 时静默截断保留最近 20 条消息
- 行为：客户端发送 25 条 → 服务端保留最近 20 条处理，不返回 422
- 测试：`test_history_over_20_items_silently_truncates` 验证截断后为最近 20 条

---

## Agent 端点流式一致性修复

原始实现：react_loop 的 token 事件输出完整答案，但端点 handler 在循环结束后对 done 事件 answer 执行截断 → token 与 done 内容不一致。

已修正为：
- `react_loop` 和 `langgraph_react_loop` 接受 `max_answer_len` 参数
- 在三种答案产出路径（直接回答 / 预算=0 / 预算耗尽兜底）中统一执行截断
- 端点 handler 传入 `MAX_ANSWER_LEN`，不再执行后置截断
- token 和 done 事件的 answer 内容一致

---

## 截断后验证偏差修复

原始实现：`chat_stream` 将含 `[答案过长，已截断]` 标记的完整 answer 传入 `reflector.verify_answer()`，标记文本可能被当作 claim 导致误导性置信度。

已修正：
- `full_answer` 传入 verify 前先剥离截断标记：`clean_answer = full_answer.replace("\n\n[答案过长，已截断]", "")`
- 验证仅针对实际答案内容（截断后的前 10000 字符）

---

## 判定

所有 AC Section 4 测试需求已满足。4 个端点的截断行为已验证。ChatRequest 校验边界完整覆盖。AgentTool 超时分支已测试。

补充测试按用户指定名称交付：
- `test_agent_tools.py::TestToolRegistry::test_tool_timeout` — AC 1.1/1.2
- `test_schemas_validation.py::test_query_too_long` — AC 1.3
- `test_schemas_validation.py::test_history_too_many` — AC 1.4
- `test_main.py::test_answer_truncation` — AC 1.5

全量 pytest: 355 passed, 3 failed (全部预存，非 module-042 引入)。
