# 功能规格说明书 — Module-036: Agent 端点接入会话记忆

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-036 |
| 模块名称 | Agent 端点接入会话记忆 |
| 版本号 | 0.36.0-module-036 |
| 优先级 | P2（记忆体系完整性最后一块；Agent 路径缺会话恢复/保存） |
| 预估代码量 | **声明调整：≤ 150 行**（复用现成函数，改动小） |
| 创建日期 | 2026-08-07 |
| 最后更新 | 2026-08-07 |
| 负责人 | Planner: 规划执行, Developer: 一次派发闭环 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：记忆体系复盘（module-034 完成后）→ 用户选定 C 方向
- 现状缺口：

| 记忆能力 | 普通 chat/stream | Agent 路径（/ai/rag/chat/agent + agent-lg） |
|---|---|---|
| 长期+短期记忆召回 | ✅ `_recall_memory` | ✅ 已有（recall_memory 工具走同一函数） |
| **会话恢复**（持久化 history） | ✅ `_resolve_session_history` | ❌ **缺**（直接传 request.history） |
| **会话保存**（写库） | ✅ `_schedule_session_persist` | ❌ **缺**（agent 完成不保存） |

### 2.2 用户故事

```
作为 用户（登录或匿名）
我想要 Agent 模式的对话也能恢复最近会话、结束后持久化
以便 刷新/换设备不丢 Agent 对话历史（与普通聊天一致）
```

### 2.3 验收场景（BDD 格式）

```
场景 1：Agent 会话恢复
  假设 用户有持久化会话
  当 调 /ai/rag/chat/agent
  那么 history 优先从持久化恢复（而非仅当前请求）

场景 2：Agent 会话保存
  假设 Agent 对话结束
  当 完成后
  那么 会话轮次异步写库（source=memory:<identity>:session:，不阻塞响应）

场景 3：无会话零回归
  假设 无持久化会话
  当 调 agent 端点
  那么 用当前请求 history（行为不变）

场景 4：匿名隔离
  假设 匿名用户
  当 agent 对话
  那么 会话按 client_ip 隔离
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 复用 | 复用 `_resolve_session_history` / `_schedule_session_persist`（module-034 现成） |
| 零回归 | 无会话时用 request.history；agent 工具行为不变 |
| 不阻塞 | 会话保存 fire-and-forget |
| 隔离 | 按 identity（user_id 否则 client_ip） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/main.py` | 修改 | /ai/rag/chat/agent + /ai/rag/chat/agent-lg：会话恢复 + 会话保存接入 |
| `ai_service/agent/react.py` | 修改 | ReactContext 命名语义修正（client_ip → identity，可选） |
| `ai_service/agent/langgraph_react.py` | 修改 | 同上（可选，若改） |
| `ai_service/agent/tool_registry.py` | 修改 | `_recall_memory` 用 ctx.identity（若改名） |
| `ai_service/tests/test_agent_tools.py` | 修改 | agent 会话恢复/保存单测 |

### 3.2 业务逻辑说明

#### 功能 1：Agent 端点会话恢复

```
/ai/rag/chat/agent（main.py L514）与 /ai/rag/chat/agent-lg（L575）：
  - 现状：ctx = ReactContext(query, identity, request.history)  ← 直接用请求 history
  - 改：先调 _resolve_session_history(identity, request.history) 拿有效 history，
        再构造 ctx（与 chat_stream Step 5 一致）
  - 无持久化 → 返回 request.history（零回归）
```

#### 功能 2：Agent 端点会话保存

```
Agent 对话完成后（react_loop / langgraph_react_loop 结束）：
  - 调 _schedule_session_persist(identity, query, answer)（fire-and-forget，不阻塞）
  - 与 chat/chat_stream 的 knowledge 路径一致
```

#### 功能 3（可选）：ReactContext.client_ip → identity 命名修正

```
现状：ctx.client_ip 承载 identity（user_id 或 client_ip，module-034 语义已变）
  - tool_registry._recall_memory 用 ctx.client_ip → 实为 identity（行为正确，命名过时）
  - module-034 Review 建议 #4：重构时更名 identity
本模块顺手改名（连带 tool_registry 引用），让语义正确
  - 影响：react.py / langgraph_react.py / tool_registry.py / main.py 构造处
  - 零功能影响（值不变，仅命名）
```

### 3.3 关键设计决策

| 决策 | 说明 |
|------|------|
| 复用现成函数 | 不重写会话逻辑，`_resolve_session_history`/`_schedule_session_persist` 已实现 |
| agent 与 chat 对齐 | Agent 路径会话行为与普通聊天一致 |
| 命名修正顺带做 | client_ip → identity，语义正确（低风险） |

### 3.4 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| 会话恢复失败 | 返回 request.history（零回归） |
| 会话保存失败 | 异步日志降级，不阻塞 |
| 无身份 | identity="unknown"，隔离正确 |

### 3.5 跨模块契约

```
- agent 端点签名不变（SSE 事件格式不变）
- recall_memory 工具行为不变（长+短期）
- 会话 source = memory:<identity>:session:（module-034 一致）
- 匿名降级（user_id 否则 client_ip）不变
```

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
python -m pytest tests/test_agent_tools.py tests/test_stream_memory.py -q
python -m pytest tests/ -q   # 全量回归 292 基线
python -m pytest tests/test_session_memory.py -q
```

### 4.2 预期输出

```
新增单测全过；全量 292 + 新增 通过 / 0 失败
E2E：Agent 对话 → 会话落库 memory:<identity>:session: → 新对话恢复
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| agent 不保存会话 | 未触发 _schedule_session_persist | 检查 react_loop 结束处 |
| agent 不恢复会话 | 未走 _resolve_session_history | 检查 ctx 构造 |
| 回归失败 | 改名影响引用 | 检查 client_ip→identity 全量替换 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| module-034 | `_resolve_session_history` / `_schedule_session_persist` / session_memory | ✅ |
| module-028/030 | ReactContext / react_loop / langgraph_react | ✅ |

### 5.2 下游依赖

- 无。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 命名改名遗漏引用 | 编译/运行错 | 低 | grep client_ip 全量核对 |
| 会话保存重复 | 与 chat 路径混淆 | 低 | agent 端点独立触发一次 |

### 6.2 技术注意事项

- [x] `_resolve_session_history(identity, request.history)` 已存在（engine.py L398）
- [x] `_schedule_session_persist(identity, query, answer)` 已存在
- [ ] grep `client_ip` 确认改名范围（react/tool_registry/main/agent-lg）
- [ ] 复用而非重写

### 6.3 开发建议

- 先会话恢复 → 会话保存 → 命名修正（若做）
- 保持 agent 工具行为不变

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-07 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-07 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
