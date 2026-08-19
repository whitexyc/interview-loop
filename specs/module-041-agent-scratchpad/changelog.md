# Changelog — Module-041: Agent 工作记忆 Scratchpad

> 2026-08-08 | white

---

## 变更摘要

给 Agent ReAct 循环添加跨轮次工作记忆（scratchpad），LLM 通过 `note_to_self` 工具写入中间发现，`generate_answer` 时自动拼入 prompt。

## 涉及文件

| 文件 | 变更类型 | 行数变化 |
|------|---------|---------|
| `ai_service/agent/react.py` | 修改 | +9 行 |
| `ai_service/agent/tool_registry.py` | 修改 | +18 行 |
| `ai_service/agent/reflector.py` | 修改 | +12 行 |
| `ai_service/agent/langgraph_react.py` | 修改 | +1 行 |

## 详细变更

### 1. `ai_service/agent/react.py`

- **ReactContext**: 新增 `scratchpad: list[str]` 字段（初始化为空列表）和 `add_note(note)` 方法
- **_SYSTEM_PROMPT**: 工具列表追加 `verify_answer` 和 `note_to_self`，现在共列出 10 个工具
- **react_loop**: 预算耗尽兜底生成调用 `reflector.generate_answer` 时传入 `scratchpad=ctx.scratchpad`

### 2. `ai_service/agent/tool_registry.py`

- 新增 `_note_to_self(ctx, args)` 异步函数：读取 `args.note`，空内容返回提示，过长截断至 500 字，调 `ctx.add_note()` 写入 scratchpad，返回确认消息
- 新增 `_NOTE_SCHEMA`：`{type: "object", properties: {note: {type: "string"}}, required: ["note"]}`
- `register_builtin_tools` 注册 `note_to_self` 为第 10 个工具
- 注释/文档字符串：内置工具数 9→10
- `_generate_answer` 调用 `reflector.generate_answer` 时传入 `scratchpad=ctx.scratchpad`

### 3. `ai_service/agent/reflector.py`

- `generate_answer` / `generate_answer_stream`: 新增 `scratchpad: Optional[list[str]] = None` 参数
- 在 `sections` 拼接时，若 scratchpad 非空则构造 `[工作笔记 - Agent 推理过程中的关键发现]` 段落注入
  - 格式：编号列表（`  1. note1\n  2. note2`）
  - 空 scratchpad 时零回归（`scratchpad_section = ""`）

### 4. `ai_service/agent/langgraph_react.py`

- LangGraph 预算耗尽 fallback 节点：传入 `scratchpad=ctx.scratchpad`

## 降级说明

| 场景 | 处理 |
|------|------|
| note_to_self 收到空内容 | 返回"（未提供笔记内容）" |
| note 超过 500 字 | 自动截断至 500 字存储 |
| scratchpad 为空 | generate_answer 不注入 scratchpad 段（零回归） |
| 无 ctx 场景（如 eval 直接调 generate_answer） | scratchpad 默认 None，行为不变 |

## 验证

- [x] Agent 通过 note_to_self 记录中间发现，后续轮次可见
- [x] generate_answer 空 scratchpad 时零回归（prompt 与旧版逐字节一致）
- [x] 多轮累积笔记正确追加
- [x] 空内容 note 正确处理（不崩溃、返回提示）
- [x] 50 个测试全部通过（含 14 个新增 + 3 处修复）
- [x] test-report.md 已创建
- [x] 用户记忆文件已更新
- [x] 验收标准 1.6（系统提示词含 note_to_self）已通过 git diff 手工确认 + test_system_prompt_contains_note_to_self 自动化验证
