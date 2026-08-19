# 功能规格说明书 — Module-041: Agent 工作记忆 Scratchpad

> Planner | 2026-08-08

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-041 |
| 模块名称 | Agent 工作记忆 Scratchpad（跨轮次草稿纸） |
| 版本号 | 0.41.0-module-041 |
| 优先级 | P2（Agent 跨轮次推理效率） |
| 预估代码量 | ≤ 120 行 |

---

## 2. 需求

### 2.1 现状

Agent ReAct 循环多轮工具调用时，中间推理只能靠 messages 历史——LLM 要从越来越长的消息中自己找回之前的发现。没有结构化"草稿纸"，导致：
- 第一轮搜到的关键信息，第三轮可能被遗忘
- 无法标记"已确认"vs"待验证"的发现
- 预算耗尽兜底生成时，只能看到累积的 documents，看不到推理过程

### 2.2 目标

给 Agent 一个 `scratchpad`——跨轮次可读写的结构化便签。LLM 通过 `note_to_self` 工具写入中间发现，generate_answer 时自动拼入 prompt。

### 2.3 验收场景

```
场景 1：Agent 记录中间发现
  假设 Agent 第一轮搜到"G1 使用 Region 分区"
  当 LLM 调 note_to_self("G1 核心：Region 分区机制")
  那么 scratchpad 追加一条记录 → 后续轮次可见

场景 2：generate_answer 读取 scratchpad
  假设 scratchpad 有 3 条记录
  当 兜底生成 / LLM 调 generate_answer
  那么 scratchpad 以"[工作笔记]"段拼入 prompt

场景 3：空 scratchpad 零回归
  假设 Agent 从未调 note_to_self
  那么 generate_answer 行为不变（无 scratchpad 段）

场景 4：多轮累积
  假设 Agent 3 轮各写一条 note
  那么 scratchpad 含 3 条记录，按写入序排列
```

---

## 3. 技术方案

### 3.1 涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `ai_service/agent/react.py` | 修改 | ReactContext 加 scratchpad 字段；_SYSTEM_PROMPT 加 note_to_self 工具说明 |
| `ai_service/agent/tool_registry.py` | 修改 | 新增 `_note_to_self` 工具 + schema + 注册为第 10 个工具 |
| `ai_service/agent/reflector.py` | 修改 | generate_answer 方法：docs 拼装前追加 scratchpad 段 |

### 3.2 核心逻辑

#### ReactContext.scratchpad

```python
class ReactContext:
    def __init__(self, ...):
        ...
        self.scratchpad: list[str] = []  # module-041: Agent 工作笔记，按写入序

    def add_note(self, note: str) -> None:
        self.scratchpad.append(note.strip())
```

#### note_to_self 工具

```python
async def _note_to_self(ctx, args):
    note = args.get("note", "")
    if not note or not note.strip():
        return "（未提供笔记内容）"
    ctx.add_note(note)
    return f"已记录笔记 ({len(ctx.scratchpad)}): {note[:200]}"
```

#### generate_answer scratchpad 注入

reflector.py `generate_answer` 方法，在 docs_detail 拼接前：

```python
scratchpad_text = ""
if ctx and getattr(ctx, 'scratchpad', None):
    notes = ctx.scratchpad
    if notes:
        lines = [f"  {i+1}. {n}" for i, n in enumerate(notes)]
        scratchpad_text = f"\n[工作笔记 - Agent 推理过程中的关键发现]\n" + "\n".join(lines) + "\n"
# 然后拼入 sections 或 docs_detail 之前
```

#### 系统提示词更新

react.py `_SYSTEM_PROMPT` 工具列表追加：
```
- note_to_self: 记录中间发现或推理结论，后续轮次可参考（工作笔记/草稿纸）
```

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 空内容 note | 返回提示 |
| note 过长 | 自动截断 500 字 |
| scratchpad 为空 | generate_answer 不注入空段 |

### 3.4 设计决策

| 决策 | 说明 |
|------|------|
| scratchpad 存 ReactContext 非外部存储 | 请求级生命周期，不跨会话——就是"草稿纸" |
| 不分 supported/inferred 标注 | 那是 answer 验证的事（039），scratchpad 是自由笔记 |
| tool_registry 不新增文件 | 全部改动在已有文件中 |

---

## 4. 验收标准

见 `acceptance-criteria.md`

## 5. 依赖

- module-028 (ReactContext / ToolRegistry / react_loop)
- module-004 (Reflector.generate_answer)
