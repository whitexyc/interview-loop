# 变更日志 — Module-025: 流式记忆接入

## 变更概述
前端实际使用 `/ai/rag/chat/stream`（流式）对话，但 module-023 的长期记忆只在同步 `chat` 路径注入了。本模块将记忆注入接入流式路径：`chat_stream` Step 5 生成前调用 `rag_engine._recall_memory(query, client_ip)` 召回跨会话记忆，并把结果传给 `reflector.generate_answer_stream(memory=...)`。无记忆时 memory 为空串，行为与之前完全一致（零回归）。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/main.py | 修改 | chat_stream 增加 `fastapi_req: Request` 参数取 client_ip；Step 5 生成前调用 `_recall_memory` 并传入 `generate_answer_stream(memory=)` |
| ai_service/tests/test_stream_memory.py | 新增 | 流式记忆注入单测（5 用例：有记忆注入 / 无记忆零回归 / 召回失败契约 / client_ip 透传 / casual_chat 跳过） |

## 关键设计说明
### 设计决策 1: 复用 engine._recall_memory（不新写记忆逻辑）
- 决策: 直接调用 module-023 已实现的 `rag_engine._recall_memory`，其内部已有 5s 超时（`asyncio.wait_for(timeout=5)`）+ 失败返回空串的降级，外层不额外 try/catch。
- 原因: 避免重复实现，且确保流式与同步路径的记忆召回行为一致。

### 设计决策 2: client_ip 从 request.state 获取
- 决策: `getattr(fastapi_req.state, "client_ip", "unknown")`，与同步 `chat` 端点同款模式。
- 原因: 限流中间件已把 client_ip 注入 `request.state`（module-023 透传），取不到时默认 `'unknown'`（此时 `_recall_memory` 内部直接返回空串）。

### 设计决策 3: 记忆注入仅限知识库生成步骤
- 决策: 记忆召回放在 Step 5（`event_stream` 内），casual_chat / 无 docs 分支在此之前提前 return，不触发召回。
- 原因: 保持流式步骤（意图→检索→Rerank→反思）不变，记忆只影响生成 prompt。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法编译 | `python -m py_compile ai_service/main.py ai_service/tests/test_stream_memory.py` | OK |
| 新增单测 | `python -m pytest ai_service/tests/test_stream_memory.py -v` | 5 passed |
| 全量回归 | `python -m pytest ai_service/tests/` | 101 passed, 2 既有 async 技术债务失败（test_engine.py，非本次回归） |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：chat_stream 接入长期记忆 | Developer |
