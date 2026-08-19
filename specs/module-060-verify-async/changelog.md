# Changelog — Module-060: verify 异步化（后置推送 P2，落库持久化）

> Developer（续作） | 2026-08-13
> 开工前已读 `memory/project-context.md` 全文（module-001~058 清单与迭代状态，避免重复/冲突）✅
> 续作背景：上一轮 Developer 网络中断被终止，WP1-3 文件改动已基本落地；接手后先 git status + 检查文件完整性 → 补齐缺失实现（handleRetry/verifying 透传/前端测试）→ 测试 + 全量 → 文档记忆。中断点 handleRetry 编辑已确认无语法错误但逻辑半完成，已补齐。

---

## 1. 模块目标与结果

| WP | 内容 | 结果 |
|----|------|------|
| WP1 | 后端 verify 后台任务基础设施（verify_tasks.py + verify_results 表 + 开关） | ✅ 全部落地（submit_verify_task / _run_verify / get_verify_task / DDL 幂等 / PW_VERIFY_ASYNC 默认 true）；单测 17 项全绿 |
| WP2 | chat_stream 异步化 + 轮询端点 | ✅ 开关 true：done 带 verify_task_id、无 verified 事件、连接早于 verify 关闭；开关 false：现状同步路径逐字一致（逃生口）；GET /ai/rag/chat/verify/{task_id} 状态机 pending/done/failed/404 |
| WP3 | 前端（types/ragService/ChatPage/ChatMessage） | ✅ 全部落地（verifyTaskId 解析 + fetchVerifyResult + 轮询补 verifiedClaims + verifying 提示 + 生命周期清理）；前端测试 58 项全绿 + build PASS |
| WP4 | 测试 + 文档 + 记忆 | ⏳ 全量 pytest **795 passed / 2 环境性失败**（真实 Redis 用例，Redis 3.2 不支持 redis-py 8.1 RESP3 HELLO——环境依赖，非本模块回归）；前端 vitest **58/0** + tsc/vite build PASS；**真实 E2E 待环境（本机无 PostgreSQL，见 §7）**；ADR-0013 + 记忆三件套已更新 |

**核心收益**：verify（幻觉检测）15-50s 从流式主链路尾部移除——答案 token 流完即发 done（带 verify_task_id）、连接关闭、前端 loading 立即结束，验证后台跑 + 前端 2s 轮询补结果，结果落 verify_results 表持久化（done 不因重启丢失）。

---

## 2. WP1 后端 verify 后台任务基础设施

### 2.1 新增 `ai_service/src/verify_tasks.py`

- **`submit_verify_task(answer, docs, *, identity, query, trace_id) -> task_id | None`**：
  1. 开关 `verify_async_enabled` 关闭 → 返回 None（调用方不发 task_id，前端不轮询，fail-open）
  2. 生成 task_id（uuid hex，复用 `observability.make_trace_id()`，语义一致）
  3. **先插 verify_results 表一条 pending 记录**（DB 为准；写失败 → 返回 None + 日志告警，不影响主链路答案交付）
  4. `asyncio.create_task(_run_verify(...))` fire-and-forget（只调度不 await，任务引用存入内存池 `_pool` 防 GC——对齐 `engine._schedule_persist` 成熟模式）
  5. done callback 释放池项（内存池只持执行期中间态，DB 结果永久保留不清理）
- **`_run_verify(task_id, answer, docs)`**：`time.perf_counter()` 计时 → `await reflector.verify_answer(answer, docs)`（内部已有 15/20/15s 超时，不会无限 hang）→ 成功 `_update_done`（status=done + claims JSONB/overall_confidence/supported/inferred/unsupported/verified_in_ms）；`Exception` → `_update_failed`（status=failed + error 截断 2000）。任务内全捕获，绝不抛回主链路。
- **`get_verify_task(task_id) -> dict | None`**：**读 DB 为准**（`VerifyResult` ORM + `async_session_factory`），pending/done/failed/不存在 None——轮询端点用，重启丢未完成任务属 fail-open 边界，已 done 结果持久可查。

### 2.2 `verify_results` 表（`src/database.py` + `rag/models.py`）

- `VERIFY_RESULTS_DDL` + `ensure_verify_results_table()`：对齐 feedback/request_logs 幂等模式（CREATE TABLE IF NOT EXISTS + COMMENT + `';'` 拆分逐条执行），`init_db()` 追加调用（重复启动不报错，DDL 幂等）。
- `VerifyResult` ORM：task_id(UNIQUE)/trace_id/identity/endpoint/query/status/claims(JSONB)/overall_confidence/supported/inferred/unsupported/error/verified_in_ms/created_at/updated_at，与 DDL 字段对齐。
- **不清理**：done 结果永久保留（飞轮数据源——verify 结果含逐句 verdict，可支撑答案可信度/幻觉调优数据积累）。

### 2.3 开关（`src/config.py`）

- `verify_async_enabled: bool = True`（读 `PW_VERIFY_ASYNC`）——生产默认开启；开关 false 时 submit 直接返回 None 不产生后台任务（测试环境由 conftest autouse 钉住 false，见 §4）。

---

## 3. WP2 chat_stream 改造 + 轮询端点

### 3.1 `ai_service/main.py` chat_stream（592-604 区域）

- **开关 true（生产默认）**：generate 完**不再同步 await verify** → `verify_task_id = await submit_verify_task(clean_answer, docs, identity=..., query=..., trace_id=...)` → done 事件 data = `{sources, verified: false, verify_task_id}` → **不再 yield verified 事件** → 生成器结束、连接关闭。提交失败（DB 写失败）→ done 无 verify_task_id（前端 fail-open 不轮询不显示面板，与现状空 claims 不显示一致）。
- **开关 false**：走现状同步路径（await verify → yield verified → yield done 带 verified: true），**与现状逐字一致**（逃生口，零回归）。
- 截断剥离逻辑保留（`clean_answer`，module-042）。
- `observability.timing("verify_submit", ...)`（module-058 计时口径）：异步化后端点侧不再有 `verify` 阶段，verify 耗时改由轮询 `verified_in_ms` 返回（口径变化见 §6）。

### 3.2 新端点 `GET /ai/rag/chat/verify/{task_id}`

- 查询异常 → 404（fail-open，不 500）
- 不存在（重启丢任务/过期）→ 404 `{"detail": "task not found"}`
- pending → 200 `{"status": "pending"}`；done → 200 `{"status": "done", claims, overall_confidence, total_claims, supported, inferred, unsupported, verified_in_ms}`；failed → 200 `{"status": "failed", error}`
- request_logs 表零改动（不加列）。

---

## 4. WP3 前端

### 4.1 `types/rag.ts`

- `ChatResponse.verifyTaskId?: string`（done 事件解析的异步验证任务 ID，无则不轮询 fail-open）
- 新增 `VerifyTaskResult` 类型（status: 'pending'|'done'|'failed' + claims/overall_confidence/counts/verified_in_ms/error）

### 4.2 `services/ragService.ts`

- `chatStream`：done 事件解析 `verify_task_id`（`parsed.sources` 分支内 `typeof parsed.verify_task_id === 'string'`）→ resolve 返回含 `verifyTaskId`；无 task_id（开关 false/提交失败）→ undefined。
- 新增 `fetchVerifyResult(taskId)`：GET 轮询接口（fetch 而非 aiHttp，chatStream 同款）；**404 归一化为 `{status: 'failed', error: 'task not found'}`**（fail-open），其余非 ok 抛错。

### 4.3 `pages/ChatPage.tsx`

- `doSend`：executeSend resolve 后 **loading 立即结束（finally，不再等 verify）**；有 `data.verifyTaskId` → 消息 patch 挂 `verifying: true` + `startVerifyPolling(taskId)`；无 → verifying: false。
- `startVerifyPolling`：2s 间隔 / 30 次（60s）上限；每次 `fetchVerifyResult`：done → 更新该消息 verifiedClaims + 停止；failed/404/网络异常/超时 → 停止 + 清除 verifying（fail-open 不显示面板不报错）；pending → 继续。
- **轮询生命周期清理**：新发送前、失败重试前（handleRetry 补齐）、切换会话、新建会话、组件卸载均 `clearVerifyPolling()`（`verifyTimerRef` useRef 存 timer + 卸载 cleanup effect + 竞态防护 `verifyTimerRef.current === timer` 判断）。
- `handleRetry`（续作补齐）：原中断点编辑为半完成状态（旧消息 patch 无 verifying、无轮询启动、无清理）——已补齐为与 doSend 一致（清轮询 + verifying patch + startVerifyPolling + deps）。

### 4.4 `components/ChatMessage.tsx`

- 新增 `verifying?: boolean` prop；`!isUser && !isStreaming && verifying && !verifiedClaims` → 显示"正在验证…"小字提示（顶部细分割线，风格对齐可信度面板）；verifiedClaims 到达后走现有可信度面板（"正在验证…"消失）。

---

## 5. WP4 测试

### 5.1 后端（`ai_service/tests/test_verify_tasks.py`，新 17 项，全部通过）

| 类 | 覆盖 |
|----|------|
| TestSubmitVerifyTask（4） | submit 返回 uuid hex + 先插 pending 落库 + 池持有句柄 + 完成后释放 / verify_answer 异常 → _update_failed / 开关关闭返回 None 无任务 / pending 落库失败 fail-open 不调度 |
| TestGetVerifyTask（4） | get 读 DB 为准：done（claims/confidence/verified_in_ms 透传）/ pending / failed（error 透传）/ 不存在 None |
| TestVerifyResultsDDL（1） | ensure_verify_results_table 重复调用不报错（DDL 幂等） |
| TestVerifyPollingEndpoint（5） | 轮询端点状态机：pending/done/failed/404（不存在）/404（查询异常 fail-open） |
| TestChatStreamVerifyAsync（3） | chat_stream 开关 true：done 带 verify_task_id + verified=False + 无 verified 事件 + 主链路不调 verify_answer + submit 收到 clean_answer/docs/identity/query/trace_id；开关 true 提交失败：done 无 task_id；开关 false：verified→done 顺序逐字一致 + submit 不调用 |

- **续作修复**：`mock.patch("main_module.get_verify_task")` → `"main.get_verify_task"`（mock.patch 字符串按真实模块名 `main`，非别名 `main_module`——沿 test_agent_tools/test_feedback 惯例）。

### 5.2 conftest

- autouse fixture `default_verify_async_disabled` 钉住测试环境 `verify_async_enabled=False`（对齐 module-056/058 开关模式）——存量 chat_stream 测试以现状同步路径为准，默认 true 会漂移；新测试显式 setattr True + mock DB。

### 5.3 前端（vitest 全量 **58 passed / 0 failed**，build PASS）

- `ragService.test.ts`（+6）：chatStream done 解析 verify_task_id → verifyTaskId / 无 task_id → undefined / verified 事件（开关 false）仍解析 verified_claims；fetchVerifyResult done 成功 / 404 归一化 failed / pending 透传。
- `ChatPage.test.tsx`（+4 轮询 + 3 存量环境性修复）：轮询 done 更新可信度面板 + loading 立即结束（消息级 "AI 思考中..." 消失）+ pending 多轮后 done + failed 停止 fail-open + 卸载清理不再调 fetchVerifyResult。
  - **存量环境性修复（module-029 已记录根因，非本模块回归）**：① 新增 conversationService mock（jsdom 下真实网络请求必失败 → activeConversationId 恒 null → doSend 早退）；② 两个 doSend 依赖测试补挂载等待（`await act(..., setTimeout 0)`）等 createConversation 完成；③ "render pipeline panel and upload section" 的 `getByText('知识库')` 为 M18 迁移后的过期断言（上传已移入 KnowledgePage），更新为当前 ChatPage 稳定文案 "Agent 模式"。
- `ChatMessage.test.tsx`（+4）：verifying 态显示 / verifiedClaims 已到显示面板而非提示 / isStreaming 不显示 / 用户消息不显示。

### 5.4 全量 pytest

- **797 收集 = 780 基线 + 17 新增；795 passed / 2 failed**。2 项失败均为**环境依赖**（非本模块回归，基线环境同样失败）：
  - `test_cache.py::test_prefix_invalidation_real_redis`、`test_llm_chain.py::test_set_get_roundtrip_real_redis`——真实 Redis 用例。本机 Redis 为 `D:\JAVA1\lesson\Redis-x64-3.2.100`（**Redis 3.2**），redis-py 已装 **8.1.0**（requirements 声明 `>=5.0.0`），8.x 默认 RESP3 握手发 `HELLO`，Redis 3.2 不支持 → 连接失败（实测 `protocol=2` 可连，但属生产代码改动，本模块不改非范围文件）。**修复方向**：升级本地 Redis ≥6 或给 `src/cache.py` from_url 加 `protocol=2`（留后续模块/环境处理）。

---

## 6. 已知边界与口径声明

1. **verify 计时口径变化（必然，如实记录）**：异步化后 request_logs 不再含 `verify` 阶段（module-058 有该字段预期）；verify 耗时改由轮询接口返回的 `verified_in_ms` 返回（`_run_verify` 内 `perf_counter` 计时）。request_logs 表**零改动**。
2. **服务重启丢未完成任务**：重启后 pending 任务丢失 → 轮询 404 → 前端 fail-open 不显示面板；**已 done 结果 DB 不丢**（永久可查）。属 fail-open 边界，如实记录。
3. **DB 写失败 fail-open**：pending 插入失败 → done 无 task_id（前端不轮询）；后台结果更新失败 → 日志告警，不影响主链路。
4. **内存池不持久**：只持执行期中间态（answer+docs+task 句柄），任务完成即释放；DB 为唯一权威状态（"DB 为准"纪律）。
5. **轮询开销**：2s/次 × 60s 上限 30 次，DB 单行主键查询成本可忽略。
6. **前端旧兼容**：done 新增 `verify_task_id` 为增量字段，旧前端读到 done 无 task_id → 不轮询不显示面板，fail-open；`verified` 字段保留（开关 false 时仍 true）。

## 7. 环境说明（诚实标注）

- **真实 E2E 冒烟（uvicorn 8001 真实 chat_stream：done 先于 verify、轮询 pending→done、DB verify_results done 记录）→ 待环境**：本机当前**无 PostgreSQL**（`localhost:5432` 未监听；全盘无 postgres.exe/pg_ctl/psql/initdb；注册表无 PostgreSQL 安装项；WSL 无 postgres；Docker Desktop 未运行）。AI 服务 lifespan 的 `init_db()`（启用 pgvector + 自愈建表）无错误处理，PG 缺失时服务无法启动，故真实 E2E 无法执行。即使安装裸 PG 也缺 **pgvector 扩展**（`CREATE EXTENSION vector` 会失败），需带 pgvector 的 PG。方法学 + 命令（待 PG 就绪后执行）：
  1. `cd ai_service && uvicorn main:app --port 8001`（启动自动建 verify_results 表）
  2. `curl -N -X POST http://localhost:8001/ai/rag/chat/stream -H "Content-Type: application/json" -d '{"query":"什么是G1 GC","history":[]}'` → 断言 SSE：token 事件 → **done 事件带 verify_task_id 且 verified:false、无 verified 事件**（done 先于 verify）
  3. `curl http://localhost:8001/ai/rag/chat/verify/{task_id}` → 轮询 pending → done（含 claims/overall_confidence/verified_in_ms）
  4. `psql -d personal_website -c "SELECT task_id, status, claims, verified_in_ms FROM verify_results ORDER BY id DESC LIMIT 5"` → 落库 done 记录
  - 异步 verify 全链路行为（done 先于 verify、轮询状态机、DB pending→done、开关两分支）已由 **17 项单测（mock DB）全绿**覆盖，E2E 为叠加真实 DB/LLM 的最终确认。
- **Redis 环境**：见 §5.4（Redis 3.2 + redis-py 8.1 HELLO 不兼容，2 项真实 Redis 单测环境性失败）。
- 本模块新增测试均 mock DB（假 session 打桩 `async_session_factory`，对齐 test_observability/test_feedback 模式），不依赖真实 PG。

## 8. 面试口径更新点

> verify"异步后置"：答案先出、轮询补验证，结果落库持久化。

- **问题**：流式对话尾部 15-50s 的幻觉检测（verify）怎么优化的？
- **回答**：verify 从"同步阻塞在流式 SSE 主链路尾部"改为"**后台异步 + 前端轮询 + 落库持久化**"。流式生成完立即发 done 事件（带 `verify_task_id`）、关闭连接，**loading 立即结束**；verify（LLM 拆句 + HHEM 判分，内部 15/20/15s 超时）后台 `asyncio.create_task` fire-and-forget 执行，结果写 `verify_results` 表（pending→done/failed）；前端 2s 轮询 `GET /ai/rag/chat/verify/{task_id}` 补结果（done 更新可信度面板，failed/404 fail-open 不显示）。**关键取舍**：① 非流式端点保持同步不动（前端已不用，契约稳定）；② DB 为准（重启丢未完成任务 fail-open，已 done 结果不丢，且 verify 结果成为飞轮数据源）；③ `PW_VERIFY_ASYNC=false` 逃生口走现状同步路径逐字一致；④ 计时口径变化：request_logs 不再有 verify 阶段，耗时由轮询 `verified_in_ms` 返回。

## 9. 涉及文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `ai_service/src/verify_tasks.py` | 新增 | 后台任务池 + verify_results 读写 |
| `ai_service/tests/test_verify_tasks.py` | 新增 | 17 项单测 |
| `ai_service/src/database.py` | 改 | VERIFY_RESULTS_DDL + ensure_verify_results_table + init_db 追加 |
| `ai_service/rag/models.py` | 改 | VerifyResult ORM |
| `ai_service/src/config.py` | 改 | verify_async_enabled（PW_VERIFY_ASYNC 默认 true） |
| `ai_service/main.py` | 改 | chat_stream 异步化 + 轮询端点 |
| `ai_service/tests/conftest.py` | 改 | autouse fixture 钉住 false |
| `frontend/src/types/rag.ts` | 改 | verifyTaskId + VerifyTaskResult |
| `frontend/src/types/conversation.ts` | 改 | MessageDTO.verifying（续作补齐） |
| `frontend/src/services/ragService.ts` | 改 | done 解析 task_id + fetchVerifyResult |
| `frontend/src/pages/ChatPage.tsx` | 改 | 轮询补 verifiedClaims + verifying 状态 + 生命周期清理（含 handleRetry 补齐） |
| `frontend/src/components/ChatMessage.tsx` | 改 | verifying prop + "正在验证…"提示 |
| `frontend/src/__tests__/ragService.test.ts` | 改 | +6 |
| `frontend/src/__tests__/ChatPage.test.tsx` | 改 | +4 + 3 存量环境性修复 |
| `frontend/src/__tests__/ChatMessage.test.tsx` | 改 | +4 |
| `specs/module-060-verify-async/changelog.md` | 新增 | 本文 |
| `specs/adr/0013-verify-async.md` | 新增 | ADR 决策记录 |
| `memory/project-context.md` / `agent-activity-log.md` / `file-index.md` | 改 | 记忆三件套 |
| `CONTEXT.md` | 改 | 只增（verify 异步化术语） |

## 10. 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1 | 2026-08-13 | 初版（续作补齐 handleRetry/verifying 透传/前端测试；全量 pytest 795/2 环境性、前端 58/0 + build PASS；真实 E2E 待环境——本机无 PostgreSQL） |
| v2 | 2026-08-13 | 环境修复补跑（见 §11）：Docker 启动后全量 797/0 全绿 + 真实 E2E 冒烟通过 + 删 _debug 残留（前端 56/0）+ 删旧 Redis 3.2 |

---

## 11. 主会话环境修复补跑记录（2026-08-13，收口更新）

> 承接 §7「环境说明」：当时判定的两个环境问题（Redis HELLO 不兼容、本机无 PostgreSQL）**根因均为 Docker 未启动**——本项目的 Redis 与 PostgreSQL 都跑在 Docker 容器里（`my_redis`（bitnami/redis:latest）、`my_postgres`（postgres_age，含 AGE + pgvector），`docker ps` 可见），本机无本地安装（此前验证误用 `D:\JAVA1\lesson\Redis-x64-3.2.100` 本机旧 Redis 3.2）。

**Docker 启动后的补跑结果**：

1. **全量 pytest 797/0 全绿**——原 795/2 的 2 项真实 Redis 用例（`test_cache.py::test_prefix_invalidation_real_redis`、`test_llm_chain.py::test_set_get_roundtrip_real_redis`）在 Docker Redis 7 下 RESP3 握手成功全部通过（redis-py 8.1 与 Redis ≥6 兼容）。§5.4"升级本地 Redis ≥6 或 cache.py protocol=2"的修复方向**已被 Docker Redis 7 自然满足，无需改代码**。
2. **真实 E2E 冒烟通过**（§7 方法学落地，uvicorn 8001 + Docker PG）：
   - 真实 chat_stream（"什么是G1 GC"）：主链路 **33.9s** 关闭——事件序列 step×4 → token 流 → **done 带 verify_task_id + verified:false + 无同步 verified 事件**（done 先于 verify，核心断言通过）
   - 轮询 `GET /ai/rag/chat/verify/{task_id}`：**pending → pending → done**（后台 verify 耗时 **10.2s / verified_in_ms=10022**），返回 claims=8 / overall_confidence=0.875 / supported=6 / inferred=1 / unsupported=1
   - **DB verify_results 落库 done 记录**（task_id 对齐，持久化验证）
   - 主链路关闭时 verify 仍在后台跑（不阻塞答案交付）
3. **收口清理**：删除 2 个 `_debug*.test.tsx` 调试残留（Reviewer minor，污染 vitest 计数 58→56 真实）；前端 vitest 复验 **56/0**。
4. **旧 Redis 3.2 已删除**（用户要求，`D:\JAVA1\lesson\Redis-x64-3.2.100`；端口已由 Docker Redis 占用故无进程残留）。

**最终验收口径**：后端全量 **797/0 全绿**（含 17 项新单测）+ 前端 **56/0** + build PASS + **真实 E2E 冒烟全绿**——AC §5-5「全量 780+N 全绿」与 §4-1「真实 E2E 冒烟」均由真实环境补跑达成。
