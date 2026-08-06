# 验收标准 — Module-036: Agent 端点接入会话记忆

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-036 |
| 模块名称 | Agent 端点接入会话记忆 |
| 关联 plan.md | `specs/module-036-agent-memory/plan.md` |
| 验收日期 | 2026-08-07 |
| 验收人 | Tester |
| 验收版本 | 0.36.0-module-036 |

---

## 1. 功能验收

### 1.1 Agent 会话恢复

- [ ] 📋 agent 端点恢复持久化会话 — 验证方式：/ai/rag/chat/agent 构造 ctx 前走 `_resolve_session_history`（优先持久化）
- [ ] 📋 agent-lg 端点恢复持久化会话 — 验证方式：/ai/rag/chat/agent-lg 同
- [ ] 📋 无会话零回归 — 验证方式：无持久化时用 request.history（行为不变）

### 1.2 Agent 会话保存

- [ ] 📋 agent 完成后保存会话 — 验证方式：react_loop 结束后 `_schedule_session_persist`（fire-and-forget）
- [ ] 📋 agent-lg 完成后保存会话 — 验证方式：langgraph_react_loop 结束后同
- [ ] 📋 会话落库 source 正确 — 验证方式：写 source=`memory:<identity>:session:`

### 1.3 命名修正（若实施）

- [ ] 📋 ReactContext.client_ip → identity — 验证方式：改名后引用一致（grep 无遗留 client_ip 记忆用途）
- [ ] 📋 recall_memory 工具语义 — 验证方式：仍按 identity 召回长短期记忆（行为不变）

---

## 2. 接口验收

### 2.1 兼容性

- [ ] 📦 agent/agent-lg 端点签名不变（SSE 事件格式不变）
- [ ] 📦 recall_memory 工具行为不变
- [ ] 📦 会话 source `memory:<identity>:session:` 格式不变
- [ ] 📦 匿名降级（user_id 否则 client_ip）不变

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [ ] 💻 所有 public 方法有 Docstring

### 3.2 命名规范

- [ ] 💻 Python snake_case

### 3.3 代码长度

- [ ] 💻 单方法 ≤ 50 行
- [ ] 💻 模块生产代码 ≤ 150 行（plan 声明调整）

### 3.4 编译检查

- [ ] 💻 py_compile 通过
- [ ] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [ ] 🧪 agent 端点会话恢复测试（有持久化优先 / 无则 request.history）
- [ ] 🧪 agent 端点会话保存测试（完成后触发 _schedule_session_persist）
- [ ] 🧪 命名修正后引用一致性（若实施）

### 4.2 回归测试

- [ ] 🧪 `python -m pytest tests/ -q`：292 基线 + 新增通过 / 0 失败
- [ ] 🧪 agent 工具回归（test_agent_tools.py）

### 4.3 真实 E2E（Tester 可选执行）

- [ ] 🧪 Agent 对话 → 会话落库 memory:<identity>:session: → 新对话恢复
- [ ] 🧪 匿名按 client_ip 隔离 Agent 会话

### 4.4 测试命令

```bash
cd ai_service
python -m pytest tests/test_agent_tools.py tests/test_session_memory.py -q
python -m pytest tests/ -q
```

**预期输出**：新增单测全过；全量 292 + 新增 / 0 失败。

---

## 5. 文档验收

### 5.1 变更记录

- [ ] 📝 changelog.md 已更新（含版本/日期/变更/变更人）

### 5.2 设计说明

- [ ] 📝 Agent 会话记忆方案记录在 plan.md（§3）

### 5.3 共享记忆

- [ ] 📝 memory/project-context.md 更新（module-036 行 + 技术决策）
- [ ] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 8 | 0 | 0 | 0 |
| 接口验收 | 4 | 0 | 0 | 0 |
| 代码质量验收 | 5 | 0 | 0 | 0 |
| 测试验收 | 8 | 0 | 0 | 0 |
| 文档验收 | 4 | 0 | 0 | 0 |
| **合计** | **29** | **0** | **0** | **0** |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-07
- 结论:
  - [ ] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 待执行

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
