# Review Report — Module-041: Agent 工作记忆 Scratchpad

> Reviewer | 2026-08-08

---

## 审查范围

对照 `specs/module-041-agent-scratchpad/acceptance-criteria.md` 逐项核对代码实现、测试覆盖和文档完整性。

**审查证据来源：**
- `ai_service/agent/react.py` — ReactContext + _SYSTEM_PROMPT + react_loop fallback
- `ai_service/agent/tool_registry.py` — _note_to_self 工具 + _NOTE_SCHEMA + 注册 + _generate_answer scratchpad 传参
- `ai_service/agent/reflector.py` — generate_answer / generate_answer_stream scratchpad 参数 + prompt 注入
- `ai_service/agent/langgraph_react.py` — LangGraph fallback scratchpad 传参
- `ai_service/tests/test_agent_tools.py` — TestNoteToSelf (11 测试) + TestNoteToSelfCoexistence (3 测试)
- 测试运行结果: **51 passed, 0 failed** (python -m pytest tests/test_agent_tools.py -q)

---

## 逐项核对

### 1. 功能验收 (6/6 通过)

| # | 标准 | 状态 | 证据 |
|---|------|------|------|
| 1 | ReactContext.scratchpad 字段存在，初始化为空列表 | PASS | `react.py:89` — `self.scratchpad: list[str] = []` |
| 2 | note_to_self 注册为第 10 个 Agent 工具，list_tool_names() 含 "note_to_self" | PASS | `tool_registry.py:378-382` 注册；测试 `test_builtin_tools_registered` (line 89) 确认第 10 位 |
| 3 | note_to_self 写入 scratchpad，ctx.scratchpad 追加笔记 | PASS | `tool_registry.py:262` `ctx.add_note(note)`；`react.py:91-93` `add_note`；测试 `test_note_to_self_writes_to_scratchpad` (line 842) |
| 4 | generate_answer 读取 scratchpad，prompt 含"[工作笔记]"段 | PASS | `reflector.py:219-223` 构造 scratchpad_section 并拼入 sections；测试 `test_scratchpad_injection_in_reflector_generate_answer` (line 968) |
| 5 | 空 scratchpad 零回归，generate_answer 行为不变 | PASS | `reflector.py:219` `if scratchpad:` 门控；测试 `test_generate_answer_empty_scratchpad_zero_regression` (line 946) |
| 6 | ReAct 系统提示词含 note_to_self | PASS | `react.py:55` — `- note_to_self: 记录中间发现或推理结论到工作笔记，后续轮次可参考`；测试 `test_system_prompt_contains_note_to_self` (line 825) |

### 2. 降级验收 (3/3 通过)

| # | 标准 | 状态 | 证据 |
|---|------|------|------|
| 1 | 空内容 note — 返回提示 | PASS | `tool_registry.py:259-260` `if not note or not note.strip(): return "（未提供笔记内容）"`；测试 line 857 (空)、line 871 (纯空白) |
| 2 | note 过长自动截断 — 500 字上限 | PASS | `tool_registry.py:261` `note = note.strip()[:500]`；测试 `test_note_to_self_truncates_long_note` (line 885) — 1000 字输入截为 500 |
| 3 | ReactContext 无 scratchpad 时 generate_answer 不抛异常 | PASS | `reflector.py:173` 默认 `scratchpad=None`，line 219 `if scratchpad:` 门控；测试 `test_scratchpad_none_zero_regression` (line 997) |

### 3. 接口兼容 (3/3 通过)

| # | 标准 | 状态 | 证据 |
|---|------|------|------|
| 1 | 现有工具不变 — regression | PASS | tool_registry.py 仅新增 _note_to_self + _NOTE_SCHEMA + 注册调用；9 个已有工具代码零改动；测试 `test_verify_answer_register_unchanged` (line 1075) |
| 2 | react_loop 行为不变 | PASS | `react.py:256-259` 仅在 fallback 调 reflector.generate_answer 时多传 `scratchpad=`（向后兼容）；现有 ReAct 测试全部通过 |
| 3 | verify_answer 不受影响 | PASS | tool_registry.py `_verify_answer` 函数体无变更；测试 `test_verify_answer_register_unchanged` (line 1075) 确认注册/desc/props 不变 |

### 4. 测试验收 (3/3 通过)

| # | 标准 | 状态 | 证据 |
|---|------|------|------|
| 1 | note_to_self 工具注册 + 执行测试 | PASS | `TestNoteToSelf` 类 (line 812) — 11 个测试覆盖：注册、写入、空/空白降级、截断、多轮累积、generate_answer 读取、空回归、prompt 注入、None 回归、_SYSTEM_PROMPT |
| 2 | 与 module-039 verify_answer 共存测试 | PASS | `TestNoteToSelfCoexistence` 类 (line 1022) — 3 个测试：共存注册、同一 ctx 先后调用、verify_answer 不受影响 |
| 3 | 全量 + 新增 / 0 失败 | PASS | `python -m pytest tests/test_agent_tools.py -q` → **51 passed in 50.57s** |

### 5. 文档验收 (2/2 通过)

| # | 标准 | 状态 | 证据 |
|---|------|------|------|
| 1 | changelog.md / review-report.md / test-report.md | PASS | changelog.md — 变更详情、降级说明、验证清单齐全；test-report.md — 测试范围、新增用例、修复记录、运行结果齐全；review-report.md — 本文档 |
| 2 | 记忆文件更新 | PASS | `memory/agent-scratchpad.md` — 核心实现、关键决策表、降级表、涉及文件、测试覆盖齐全 |

---

## 代码质量观察 (非阻塞)

以下为审查过程中发现的次要观察项，不影响验收通过：

1. **双重 strip** — `_note_to_self` (tool_registry.py:261) 调用 `note.strip()[:500]` 后传给 `ctx.add_note(note)`，而 `add_note` (react.py:93) 再次调用 `note.strip()`。功能正确但存在冗余 strip。建议：去掉 add_note 中的 strip，由 _note_to_self 统一处理（或反之，保留一处即可）。

2. **scratchpad 在 ReAct 循环内不可见** — LLM 在 ReAct 循环的工具调用轮次中只能看到 truncated tool 结果文本 (`已记录笔记 (N): [前 200 字]`)，而非完整 scratchpad 内容。这是有意设计（scratchpad 定位为 generate_answer 时注入），与验收标准一致。

---

## 裁决

**PASS** — 所有 17 项验收标准 (5 组) 均通过代码审查和测试验证。51 个测试 0 失败，实现与规范完全对齐。
