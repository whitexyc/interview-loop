# Module-060 任务简报：verify 异步化（后置推送 P2，落库持久化）

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
> **用户决策（已确认，勿改）**：① 送达机制 = 前端轮询；② 非流式端点 /ai/rag/chat **保持同步不动**；③ verify 结果**落库持久化**。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`，FastAPI + asyncpg + pgvector + Apache AGE）。

**要解决的问题（代码实测）**：verify（证据链幻觉检测）当前**同步阻塞在流式 SSE 主链路尾部**——答案 token 先流完了，但 `verify_answer` 的 15-50s（LLM 拆句 15s + HHEM 20s + LLM 判分 15s 降级，见 module-050/051/055）卡在 `done` 事件之前，前端 `loading` 一直转圈直到 verify 完成。本模块把 verify 改成**后台异步执行 + 前端轮询补结果**，答案先交付，验证后到。

**现状（代码实测，勿改口径）**：

- **chat_stream 端点**（`main.py:425-619`）：SSE 时序 Step5 流式生成（565-574）→ Step7 验证（592-604）：`verified = await reflector.verify_answer(clean_answer, docs)`（**main.py:598**，同步 await）→ `yield verified`（601）→ `yield done`（602/604）→ 生成器结束、连接关闭。**verify 阻塞在 SSE 连接内**。
- **前端**（`ChatPage.tsx doSend` 212-245）：`data = await executeSend(text, history)`（**223**）await 涵盖整个 SSE 含 verify → resolve 后 setMessages 挂 `verifiedClaims`（229）→ finally setLoading(false)（243）。**verify 期间 loading=true、ChatMessage isStreaming=true（"生成中…"）**。
- **SSE 事件解析**（`ragService.ts chatStream` 74-164）：token（JSON 字符串）/ step（`parsed.step`）/ done（`parsed.sources`）/ verified（`Array.isArray(parsed.claims)`）；读到 done 不 break，**连接关闭才 resolve**；verifiedClaims 由返回值带回（158-163）。
- **验证面板展示**（`ChatMessage.tsx:292-412`）：条件 `!isStreaming && verifiedClaims && claims.length>0`。
- **verify 实现**（`reflector.py:412-516 verify_answer`）：LLM 拆句（464，15s 超时）→ HHEM 判分（`_judge_by_hhem` 518-590，≤8 claims × ≤2 docs，`factcheck_judge.py _PREDICT_TIMEOUT=20s`）→ 降级 LLM 判分（611，15s）；失败/超时返回 `empty_result`（空 claims，**fail-open 现状**）。
- **异步先例（成熟模式）**：`engine.py:462-479 _schedule_persist` / `590-604 _schedule_session_persist`——`asyncio.create_task(...)` fire-and-forget，任务内 try/except 降级绝不抛回响应。
- **非流式端点**（`/ai/rag/chat` main.py:393 → `engine.chat` engine.py:369 同步 verify）：**用户决策保持不动**，本模块零改动。
- **agent/agent-lg 端点**（main.py:622-763）：**不做 verify**，零改动。
- **可观测性**（module-058）：`src/observability.py` contextvar 观测上下文（init_request/timing/record_usage）；request_logs 落库（main.py:612 persist_request_log）。verify 计时目前在端点同步路径（main.py:598-599）。
- **建表模式**：`database.py init_db`（89-97）幂等建 feedback/request_logs；DDL 模式 `REQUEST_LOGS_DDL`（57-77）= CREATE TABLE IF NOT EXISTS + COMMENT + `';'` 拆分逐条执行。
- **配置开关模式**（`src/config.py`）：`request_logs_enabled`（PW_REQUEST_LOGS）、`tool_phase_split`（PW_TOOL_PHASE_SPLIT）等 settings 字段。
- **测试**：全量 **780 passed / 0 failed**（module-058 后）。conftest.py autouse fixtures 钉住测试环境开关（disable_rate_limit / intent_classifier=False / tool_phase_split=False / request_logs_enabled=False，monkeypatch settings）——**新开关须加同款 autouse fixture**。
- **前端测试**：`ragService.test.ts` / `ChatPage.test.tsx` / `ChatMessage.test.tsx` 存在。

## 二、用户决策（已确认）

| 决策点 | 结论 |
|--------|------|
| verify 结果送达机制 | **前端轮询**（GET /ai/rag/chat/verify/{task_id}，~2s 间隔，60s 上限） |
| 非流式端点 /ai/rag/chat | **保持同步不动**（前端已不用，契约稳定，E2E 零影响） |
| verify 结果存储 | **落库持久化**（verify_results 表，done 结果不因重启丢失） |

## 三、任务步骤（按序，每步有通过标准）

### WP1 后端 verify 后台任务基础设施

- **`ai_service/src/verify_tasks.py`（新）**：内存任务池 + DB 持久化双轨。
  - `submit_verify_task(answer, docs, *, identity, query, trace_id) -> task_id`：生成 task_id（uuid hex，可复用 `observability.make_trace_id()`）→ **先插 verify_results 表一条 pending 记录**（task_id/trace_id/identity/endpoint/query/status=pending/created_at）→ `asyncio.create_task(_run_verify(...))`（fire-and-forget，不 await）→ 返回 task_id。
  - `_run_verify(...)`：`time.perf_counter()` 计时 → `await reflector.verify_answer(answer, docs)`（内部已有 15/20/15s 超时，不会无限 hang）→ 成功：UPDATE DB 该行 status=done + claims(JSONB)/overall_confidence/supported/inferred/unsupported/verified_in_ms；`Exception`：UPDATE status=failed + error 字段。任务内全捕获，绝不抛回。
  - `get_verify_task(task_id) -> dict | None`：**查 DB**（轮询端点用；DB 为准，未完成 pending / 已完成 done / 失败 failed）。
  - 内存 dict 只持有执行期中间态（answer+docs+task 句柄），任务完成即释放；**DB 结果永久保留**（不设清理，避免丢飞轮数据源）。
- **`ai_service/src/database.py`（改）**：`VERIFY_RESULTS_DDL` + `ensure_verify_results_table()`（对齐 REQUEST_LOGS_DDL 幂等模式）+ `init_db()` 追加调用。
- **`ai_service/rag/models.py`（改）**：`VerifyResult` ORM（对齐 DDL）。
- **`ai_service/src/config.py`（改）**：`verify_async_enabled`（读 `PW_VERIFY_ASYNC`，默认 true）。
- **通过标准**：单测覆盖 submit/get/DB 状态流转/TTL 释放/开关；DDL 幂等（重复 init_db 不报错）。

### WP2 chat_stream 端点改造 + 轮询端点

- **`ai_service/main.py`（改）chat_stream**（592-604 区域）：
  - 开关 true：generate 完**不再同步 await verify** → `verify_task_id = await submit_verify_task(...)` → `yield done` data 改为 `{sources, verified: False, verify_task_id}` → 生成器结束、连接关闭。**不再 yield verified 事件**。
  - 开关 false：走现状（同步 await verify → `yield verified` → `yield done` 带 verified: true）——**零回归逃生口**。
  - 截断剥离逻辑保留（`clean_answer`）。
- **新端点 `GET /ai/rag/chat/verify/{task_id}`**：查 verify_results 表 →
  - 存在 + status=pending → 200 `{status: "pending"}`
  - 存在 + done → 200 `{status: "done", claims, overall_confidence, total_claims, supported, inferred, unsupported, verified_in_ms}`
  - 存在 + failed → 200 `{status: "failed", error}`
  - 不存在（含重启丢任务/过期）→ 404 `{detail: "task not found"}`（前端 fail-open）
- **request_logs 不动**（不加列；verify 耗时改由轮询 `verified_in_ms` 返回——changelog 如实记录口径变化）。
- **通过标准**：chat_stream 开关 true 时 done 事件含 verify_task_id 且无 verified 事件、连接关闭早于 verify 完成；开关 false 行为与现状逐字一致；轮询端点状态机（pending→done/failed/404）单测覆盖。

### WP3 前端

- **`frontend/src/types/rag.ts`（改）**：`ChatResponse` 加 `verifyTaskId?: string`；新增 `VerifyTaskResult` 类型（status: 'pending' | 'done' | 'failed' + claims/overall_confidence/counts/verified_in_ms/error）。
- **`frontend/src/services/ragService.ts`（改）**：`chatStream` 解析 done 事件里的 `verify_task_id` → resolve 返回含 `verifyTaskId`；新增 `fetchVerifyResult(taskId)`（GET 轮询接口，封装 404 与状态）。
- **`frontend/src/pages/ChatPage.tsx`（改）**：`doSend` 里 executeSend resolve 后：
  - loading 立即结束（现状 finally，**不再等 verify**）；
  - 若 `data.verifyTaskId`：先 setMessages 挂 sources（verifiedClaims 暂空）+ 标记该消息 verifying → 启动轮询（2s 间隔、上限 60s/30 次）→ 每次 `fetchVerifyResult`：done → setMessages 更新 verifiedClaims + 停止；failed/404/超时 → 停止（不显示验证面板，fail-open）。
  - 清理：组件卸载/重试/切换会话时 clearInterval（useRef 存 timer + 卸载清理）。
- **`frontend/src/components/ChatMessage.tsx`（改）**：加 `verifying?: boolean` prop；`verifying && !verifiedClaims` 时显示"正在验证…"小字提示；verifiedClaims 到达后走现有面板。
- **通过标准**：前端测试覆盖——done 事件解析 task_id / 轮询 done 更新面板 / pending 多轮 / 失败停止 / loading 立即结束断言 / 卸载清理。

### WP4 测试 + 文档 + 记忆

- **`ai_service/tests/conftest.py`（改）**：autouse fixture `default_verify_async_disabled` 钉住测试环境 `verify_async_enabled=False`（对齐 module-056/058 开关模式——否则默认 true 会漂移走 chat_stream 存量测试）；新测试显式开 true。
- **`ai_service/tests/test_verify_tasks.py`（新）**：submit 返回 task_id / DB pending→done 更新（mock reflector.verify_answer）/ 异常→failed / get 查 DB / 轮询端点状态机（fixture 或 mock DB）/ DDL 幂等 / 开关 false 时 submit 行为。
- **chat_stream 端点测试（新或并入 test_verify_tasks）**：开关 true → done 事件含 verify_task_id 且无 verified 事件；开关 false → verified→done 顺序保持。
- **前端测试**：ragService.test.ts（fetchVerifyResult 成功/404）、ChatPage.test.tsx（轮询 mock 更新面板 + loading 时序 + 清理）、ChatMessage.test.tsx（verifying 态）。
- **真实 E2E 冒烟（记录进 test-report）**：uvicorn 8001 真实 chat_stream → 断言 done 事件带 task_id、**连接关闭时 verify 尚未完成**（主链路不再等 verify）→ 轮询 pending→done → DB verify_results 落库 done 记录。
- **文档**：changelog.md / review-report.md / test-report.md；**ADR-0013-verify-async.md（新，specs/adr/）** 记录决策（轮询 + 落库 + 非流式保持同步 + verify 计时口径变化）；memory 三件套；CONTEXT.md 只增；面试口径更新点落盘。
- **通过标准**：全量 780 + 新增全绿；记忆三文件按硬性约束更新；ADR-0013 状态行 ✅。

## 四、纪律项（违反 = 返工）

1. **不破坏现状**：非流式端点、agent/agent-lg 端点、request_logs 表**零改动**；开关 false 时 chat_stream 行为与现状逐字一致
2. **存量测试不改**：新开关默认 true 必须在 conftest 钉住 false（对齐既有开关模式），存量 chat_stream 测试零改动
3. **DB 为准**：轮询端点读 verify_results 表，不读内存（重启后 pending 任务丢失属 fail-open 边界，如实记录）
4. **verify 任务内部超时**复用 reflector.verify_answer 既有 15/20/15s 超时，不新增无限任务
5. **诚实**：verify 计时口径变化（request_logs 无 verify 阶段 → 轮询 verified_in_ms）如实写入 changelog

## 五、交付物

1. WP1-3 代码 + 测试（780 + 新增全绿）
2. 真实 E2E 冒烟记录（done 先于 verify、轮询流转、DB 落库）
3. ADR-0013-verify-async.md（决策记录）
4. changelog / review-report / test-report + memory 三件套 + CONTEXT.md 只增
5. 面试口径更新点（verify"异步后置：答案先出、轮询补验证，结果落库持久化"）
