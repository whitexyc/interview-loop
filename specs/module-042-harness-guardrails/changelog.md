# Changelog — Module-042: Harness 围栏

> 2026-08-08

---

## 变更摘要

三项 Agent 安全围栏已实现：

1. **工具超时 (15s)** — `AgentTool.run()` 用 `asyncio.wait_for(…, timeout=15)` 包装，超时返回提示文本，不阻塞 ReAct 循环
2. **输入校验** — `ChatRequest.query` max_length=2000（422 拒绝），`history` 超 20 条静默截断保留最近 20 条（AC 1.4 对齐）
3. **答案截断** — chat/chat_stream/agent/agent-lg 四个端点答案超过 10000 字符自动截断并附加 `[答案过长，已截断]` 提示

**评审修复 (2026-08-08):**
- **AC 1.4 对齐**：history 超限行为从 `Field(max_length=20)` 422 拒绝改为 `field_validator` 静默截断保留最近 20 条（验收标准写"超条数截断"）
- **Agent 端点流式一致性**：截断从端点 handler 后置改为 `react_loop` / `langgraph_react_loop` 内部执行，token 与 done 事件 answer 内容一致
- **截断后验证偏差修复**：`chat_stream` 的 verify_answer 调用前剥离截断标记，避免标记文本误导置信度评估
- **测试补齐**：新增 TimeoutError 测试、ChatRequest 边界测试、4 端点截断测试（共 24 个新用例）
- **文档补齐**：创建 `test-report.md`

---

## 修改文件

| 文件 | 操作 | 行数变化 |
|------|------|----------|
| `ai_service/agent/tool_registry.py` | 修改 | +4 行 (初始实现) |
| `ai_service/rag/schemas.py` | 修改 | +9 行 (含 AC 1.4 修复) |
| `ai_service/agent/react.py` | 修改 | +12 行 (含 max_answer_len 截断) |
| `ai_service/agent/langgraph_react.py` | 修改 | +15 行 (含 max_answer_len 截断) |
| `ai_service/main.py` | 修改 | +21 行 (含 verify 偏差修复) |
| `ai_service/tests/test_agent_tools.py` | 修改 | +248 行 (新增测试) |
| `ai_service/tests/test_schemas.py` | 修改 | +47 行 (新增测试) |
| `specs/module-042-harness-guardrails/test-report.md` | 新增 | - |

---

## 详细变更

### 1. `ai_service/agent/tool_registry.py`

- 新增 `import asyncio`
- `AgentTool.run()` 内 try 块改为 `asyncio.wait_for(self.func(ctx, args), timeout=15)`
- 新增 `asyncio.TimeoutError` 捕获，返回 `"(工具 {name} 执行超时)"`
- 保留原有 `Exception` 兜底捕获（返回空串）

### 2. `ai_service/rag/schemas.py`

- 导入扩展为 `from pydantic import BaseModel, Field, field_validator`
- `ChatRequest.query` 改为 `str = Field(..., max_length=2000)`（422 拒绝超长查询）
- `ChatRequest.history` 改为 `list[dict] = Field(default_factory=list)`（移除 max_length=20）
- 新增 `field_validator("history", mode="before")` — `truncate_history`: 列表 > 20 条时静默保留最近 20 条（AC 1.4 对齐）

### 3. `ai_service/agent/react.py`

- `react_loop()` 新增 `max_answer_len: int = 0` 参数
- 预算=0 直接回答路径：答案超限时截断并附加标记后 yield
- 无 tool_call 直接回答路径：截断后 yield token + done（内容一致）
- 预算耗尽兜底生成路径：截断后 yield token + done（内容一致）

### 4. `ai_service/agent/langgraph_react.py`

- `ReActGraphState` 新增 `max_answer_len: int` 字段
- `finalize` 节点：答案超限时截断后写入 events
- `fallback` 节点：答案超限时截断后写入 events（token + done 一致）
- `langgraph_react_loop()` 新增 `max_answer_len` 参数，预算=0 路径同步截断

### 5. `ai_service/main.py`

- `/ai/rag/chat`: 保留答案截断保护（后置，不影响 engine 内部逻辑）
- `/ai/rag/chat/stream`: (a) 流式截断标记 token 继续按计划产出；(b) **修复**: `full_answer` 传入 `verify_answer` 前剥离 `[答案过长，已截断]` 标记，避免标记文本误导置信度
- `/ai/rag/chat/agent`: (a) 传入 `max_answer_len=MAX_ANSWER_LEN` 给 `react_loop`；(b) 移除后置截断代码（由 react_loop 内部处理）
- `/ai/rag/chat/agent-lg`: (a) 传入 `max_answer_len=MAX_ANSWER_LEN` 给 `langgraph_react_loop`；(b) 移除后置截断代码

### 6. `ai_service/tests/test_agent_tools.py` (新增测试)

- `TestToolRegistry::test_tool_run_timeout_returns_prompt` — AC 1.1/1.2: 15s 超时返回 `"(工具 slow_tool 执行超时)"`
- `TestAnswerTruncationChat` (3 tests) — AC 1.5/2.3: /ai/rag/chat 截断 + sources 保留
- `TestAnswerTruncationAgent` (2 tests) — AC 1.5/2.3: /ai/rag/chat/agent token/done 一致截断
- `TestAnswerTruncationAgentLG` (2 tests) — AC 1.5/2.3: /ai/rag/chat/agent-lg 截断
- `TestAnswerTruncationChatStream` (2 tests) — AC 1.5/2.3: /ai/rag/chat/stream 截断标记 token + verify 清洗

### 7. `ai_service/tests/test_schemas.py` (新增测试)

- `TestChatRequestValidation::test_query_exactly_2000_chars_passes` — 边界：恰好 2000 通过
- `TestChatRequestValidation::test_query_over_2000_chars_raises_422` — 超限 422
- `TestChatRequestValidation::test_history_exactly_20_items_passes` — 恰好 20 条不截断
- `TestChatRequestValidation::test_history_over_20_items_silently_truncates` — 25 条静默截断为 20
- `TestChatRequestValidation::test_short_history_unchanged` — 短历史不截断
- `TestChatRequestValidation::test_empty_history_unchanged` — 空历史不变
- `TestChatRequestValidation::test_default_history_empty` — 默认值

---

## 验收对照

| 场景 | 状态 | 说明 |
|------|------|------|
| 工具 >15s 超时 | ✅ | 返回 `"(工具 slow_tool 执行超时)"`，LLM 继续下一轮 |
| query >2000 字符 | ✅ | Pydantic 自动 422: `"String should have at most 2000 characters"` |
| history >20 条 | ✅ | **修复后**: 静默截断保留最近 20 条（AC 1.4 对齐） |
| 答案 >10000 字符 | ✅ | 截断 + `[答案过长，已截断]`，sources 完整保留 |
| Agent 端点流式一致 | ✅ | **修复后**: token 与 done 事件 answer 内容一致 |
| 截断后验证偏差 | ✅ | **修复后**: verify 前剥离截断标记 |
| 测试覆盖 | ✅ | 新增 24 个测试用例覆盖全部功能 |
| 文档 | ✅ | changelog + review-report + test-report 均存在 |
