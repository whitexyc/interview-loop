# Review Report — Module-042: Harness 围栏

> Reviewer | 2026-08-08

---

## 1. 功能验收审查

| AC | 描述 | 实现位置 | 判定 |
|----|------|---------|------|
| AC 1.1 | AgentTool.run 含 15s 超时 — `asyncio.wait_for` 包裹 | `tool_registry.py:62` — `await asyncio.wait_for(self.func(ctx, args), timeout=15)` | PASS |
| AC 1.2 | 工具超时返回 `"(工具 X 执行超时)"` 不抛异常 | `tool_registry.py:63-65` — `asyncio.TimeoutError` 捕获后返回提示字符串，不 re-raise | PASS |
| AC 1.3 | ChatRequest.query max_length=2000 — 超长返回 422 | `schemas.py:19` — `Field(..., max_length=2000)`，Pydantic 自动 ValidationError | PASS |
| AC 1.4 | ChatRequest.history max_length=20 — 超条数截断 | `schemas.py:22-28` — `field_validator("history", mode="before")` 静默截断保留最近 20 条 | PASS |
| AC 1.5 | 答案 >10000 字符截断 — 末尾加`[答案过长，已截断]` | `main.py:331-332` (chat)、`react.py:207-208,220-222,267-268` (3条路径)、`langgraph_react.py:166-167,194-196`、`main.py:471-476` (stream) | PASS |

## 2. 降级验收审查

| AC | 描述 | 审查结论 |
|----|------|---------|
| AC 2.1 | 工具超时不阻塞 loop — LLM 可继续 | PASS: `AgentTool.run()` 捕获超时返回字符串，调用方 `react_loop` 将其作为普通工具结果追加到消息历史，LLM 下一轮正常继续决策 |
| AC 2.2 | 现有一切工具行为不变 — 短耗时工具不受影响 | PASS: `asyncio.wait_for(..., timeout=15)` 对短耗时任务是透传——超时前正常返回，路径不变 |
| AC 2.3 | 截断不丢 sources — sources 完整返回 | PASS: 截断仅作用于 `answer` 字符串字段；`sources` 由各端点独立构造（`ctx.docs` 末尾切片），与截断逻辑完全解耦 |

## 3. 接口兼容审查

| AC | 描述 | 审查结论 |
|----|------|---------|
| AC 3.1 | ChatRequest 旧字段不变 — query + history 保持 | PASS: 字段名、类型均未变，仅对 query 新增 max_length 校验、history 新增 field_validator（不改变外部 API 契约） |
| AC 3.2 | 短 query/少 history 不受影响 | PASS: query <2000、history <20 条场景下校验/截断逻辑均不触发，行为与旧版一致（有测试覆盖） |

## 4. 测试验收审查

| AC | 描述 | 测试位置 | 判定 |
|----|------|---------|------|
| AC 4.1a | 工具超时测试 | `test_agent_tools.py::TestToolRegistry::test_tool_run_timeout_returns_prompt` — 999s sleep 触发 15s 超时 | PASS |
| AC 4.1b | ChatRequest 校验测试（7 用例） | `test_schemas.py::TestChatRequestValidation` — query 边界 2000/2001、history 边界 20/25/0/默认 | PASS |
| AC 4.1c | 4 端点答案截断测试（10 用例） | `test_agent_tools.py`: `TestAnswerTruncationChat(3)`, `TestAnswerTruncationAgent(2)`, `TestAnswerTruncationAgentLG(2)`, `TestAnswerTruncationChatStream(2)` + 工具失败已有用例 | PASS |
| AC 4.2 | `python -m pytest tests/ -q` — 全量通过 | 参照 `test-report.md`，新增 24 用例，0 新失败 | PASS |

## 5. 文档验收审查

| AC | 描述 | 判定 |
|----|------|------|
| AC 5.1 | changelog.md 存在且完整 | PASS: 涵盖所有 7 个修改文件、按文件详述变更、验收对照表 |
| AC 5.2 | review-report.md (本文) | PASS |
| AC 5.3 | test-report.md 存在且完整 | PASS: 包含测试覆盖表、运行结果、边界场景矩阵、AC 对齐说明 |

---

## 6. 深度审查发现

### 6.1 代码质量 — 无阻塞问题

以下为审查中确认的设计/实现要点，均为正向确认：

1. **截断一致性已修复**：`react_loop` / `langgraph_react_loop` 均新增 `max_answer_len` 参数，在 3 种答案产出路径（预算=0 直接回答、LLM 无 tool_call 直接回答、预算耗尽兜底生成）统一执行截断。端点 handler 不再后置截断，`token` 与 `done.answer` 内容保证一致。changelog 已有记录。

2. **截断后验证偏差已修复**：`main.py:497` 的 `chat_stream` 在调用 `reflector.verify_answer()` 前剥离 `[答案过长，已截断]` 标记（`clean_answer = full_answer.replace(...)`），避免标记文本误导置信度评估。

3. **LangGraph finalize 节点 token 事件回填**：`langgraph_react.py:168-172` 截断后回写已追加的 `token` 事件，保证 `token` 和 `done` 事件内容一致。逻辑正确——图节点顺序执行保证了 llm_call→finalize 的先后关系。

4. **AC 1.4 行为对齐**：`ChatRequest.history` 从初始的 `Field(max_length=20)` 422 拒绝改为 `field_validator` 静默截断，符合验收标准"超条数截断"的语义。changelog 已有说明。

### 6.2 观察项（非阻塞）

**O-1: chat_stream 流式截断的粒度限制**

`main.py:467-476` 中流式截断逻辑：
```python
async for token in reflector.generate_answer_stream(...):
    answer_parts.append(token)
    total_len += len(token)
    yield ...
    if total_len >= MAX_ANSWER_LEN:
        truncation_note = "\n\n[答案过长，已截断]"
        ...
        break
```
最后一个正则 token 在 `>=` 检查前已追加并 yield，导致答案总长度可能超过 `MAX_ANSWER_LEN` 一个 token 的长度（实践中通常为几个字符）。这是流式输出的固有属性——无法在 token 生成中途截断。**判定：可接受，属于流式场景的合理近似。**

**O-2: agent-lg fallback 路径截断无独立测试**

`langgraph_react.py:194-196` 中 `fallback` 节点的截断代码与 `finalize` 节点结构一致（`max_len and len(answer) > max_len` → 切片 + 标记追加），但 `test_agent_lg_long_answer_truncated` 覆盖的是 `finalize` 路径（LLM 直接回答），没有触发 `fallback` 路径（预算耗尽）的独立截断测试。**判定：可接受——两者代码结构相同，且手写版 react_loop 的 fallback 截断路径已被 `test_budget_exhausted_fallback_generation` 间接覆盖。**

---

## 7. 综合判定

| 维度 | 结果 |
|------|------|
| 功能验收 (Section 1) | 5/5 PASS |
| 降级验收 (Section 2) | 3/3 PASS |
| 接口兼容 (Section 3) | 2/2 PASS |
| 测试验收 (Section 4) | 2/2 PASS |
| 文档验收 (Section 5) | 3/3 PASS |
| 阻塞问题 | 0 |
| **总体判定** | **PASS** |

所有 15 项验收标准均已满足。0 个阻塞性缺陷。changelog 中记录的 4 项评审修复（AC 1.4 对齐、Agent 端点流式一致性、截断后验证偏差修复、测试补齐）已全部到位。建议合并。
