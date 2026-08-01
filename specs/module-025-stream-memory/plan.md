# 功能规格说明书 — Module-025: 流式记忆接入

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-025 |
| 模块名称 | 流式记忆接入（chat_stream 记忆注入） |
| 版本号 | 0.25.0-module-025 |
| 优先级 | P1 |
| 预估代码量 | ≤ 50 行 |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-023 遗留 + 用户确认
- 原始描述：前端实际使用 `/ai/rag/chat/stream`（流式），但 module-023 的长期记忆只在 `chat` 同步路径注入了。流式路径 `generate_answer_stream` 的 `memory` 参数已预留但未接入。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 流式对话也能用长期记忆
以便 前端聊天（实际用的流式接口）也能引用历史结论
```

### 2.3 验收场景（BDD 格式）

```
场景 1：流式记忆注入
  假设 用户有保存的记忆
  当 走 chat_stream 流式对话
  那么 生成 prompt 包含记忆（"历史记忆: ..."）

场景 2：无记忆零回归
  假设 用户无记忆
  当 走 chat_stream
  那么 行为与之前完全一致（memory 为空串）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | chat_stream SSE 事件格式不变 |
| 零回归 | 无记忆时行为完全一致 |
| 超时 | 记忆检索 5s 超时降级 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/main.py` | 修改 | chat_stream Step 5 接入记忆 |

### 3.2 业务逻辑说明

#### 核心流程（chat_stream 改造）

```
当前 (main.py:312):
  generate_answer_stream(request.query, docs, history=request.history)

新:
  1. 在 Step 5 前调用 rag_engine._recall_memory(query, client_ip)
     - client_ip 从 request.state 获取（module-023 已透传）
     - 5s 超时降级返回空串（engine._recall_memory 已实现）
  2. 传给 generate_answer_stream:
     generate_answer_stream(query, docs, history=history, memory=memory)
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 复用 engine._recall_memory | module-023 已实现（5s 超时 + 失败返回空串） |
| 记忆注入仅生成步骤 | 不影响检索/反思（保持流式步骤不变） |
| client_ip 从 request.state | module-023 已在 chat 端点透传，stream 复用 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 记忆检索超时 | asyncio.TimeoutError | 返回空串（engine 已处理） |
| 记忆检索失败 | Exception | 返回空串（engine 已处理） |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 保存一条记忆
curl -X POST http://localhost:8000/ai/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "用户偏好简洁回答", "ip": "192.168.1.1"}'

# 2. 流式对话（应包含记忆）
curl -X POST http://localhost:8000/ai/rag/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "回答风格", "history": [], "client_ip": "192.168.1.1"}'

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
# 流式对话 step 事件正常，token 事件包含记忆相关回答
# 无记忆时行为不变
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 记忆未注入 | client_ip 未取到 | 检查 request.state.client_ip |
| 记忆检索失败 | 记忆未保存 | 检查 /ai/memory/save |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-023 | engine._recall_memory + memory 参数 | ✅ |
| module-005 | chat_stream | ✅ |

### 5.2 下游依赖

无（独立小改）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| client_ip 未取到 | 记忆不注入 | 低 | 默认 'unknown' |

### 6.2 技术注意事项

- [x] generate_answer_stream 的 memory 参数已存在（module-023）
- [x] engine._recall_memory 已实现（5s 超时 + 降级）
- [x] 改动集中在 main.py chat_stream

### 6.3 开发建议

- 改动极小（几行），复用现有能力
- 验证无记忆时零回归

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-01 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
