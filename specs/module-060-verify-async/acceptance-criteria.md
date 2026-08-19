# 验收标准 — Module-060: verify 异步化（后置推送 P2，落库持久化）

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 用户决策（已确认）：① 轮询送达；② 非流式端点保持同步不动；③ 结果落库持久化

## 1. 功能验收（WP1 后端任务基础设施）

- [ ] 📋 `src/verify_tasks.py`：`submit_verify_task(answer, docs, *, identity, query, trace_id) -> task_id` —— 先插 verify_results pending 记录，再 `asyncio.create_task` 后台执行，返回 task_id
- [ ] 📋 `_run_verify`：成功 → UPDATE status=done + claims(JSONB)/overall_confidence/supported/inferred/unsupported/verified_in_ms；异常/超时 → UPDATE status=failed + error；任务内全捕获绝不抛回主链路
- [ ] 📋 `get_verify_task(task_id)` **读 DB 为准**（pending/done/failed；不存在 → None）
- [ ] 📋 内存池只持执行期中间态（answer+docs+task 句柄），完成后释放；DB 结果不清理
- [ ] 📋 `verify_results` 表：`init_db` 自愈幂等 DDL（对齐 module-048/058 模式），字段含 task_id(UNIQUE)/trace_id/identity/endpoint/query/status/claims/overall_confidence/counts/error/verified_in_ms/created_at/updated_at
- [ ] 📋 `PW_VERIFY_ASYNC` 默认 true；开关 false 时 verify_tasks 不产生后台任务

## 2. 功能验收（WP2 chat_stream 改造 + 轮询端点）

- [ ] 📋 开关 true：chat_stream generate 完**不再同步 await verify** → done 事件 data = `{sources, verified: false, verify_task_id}` → **不再 yield verified 事件** → 连接关闭
- [ ] 📋 开关 false：chat_stream 行为与现状逐字一致（同步 verify → verified 事件 → done 事件）
- [ ] 📋 新端点 `GET /ai/rag/chat/verify/{task_id}`：pending → 200 `{status: "pending"}`；done → 200 `{status: "done", claims, overall_confidence, total_claims, supported, inferred, unsupported, verified_in_ms}`；failed → 200 `{status: "failed", error}`；不存在 → 404
- [ ] 📋 截断剥离逻辑（clean_answer）保留
- [ ] 📋 request_logs 表零改动（verify 计时口径变化如实记录：端点侧不再有 verify 阶段，耗时由轮询 verified_in_ms 返回）

## 3. 功能验收（WP3 前端）

- [ ] 📋 `types/rag.ts`：`ChatResponse.verifyTaskId?: string` + `VerifyTaskResult` 类型（status/claims/overall_confidence/counts/verified_in_ms/error）
- [ ] 📋 `ragService.ts`：`chatStream` 解析 done 事件 `verify_task_id` → resolve 返回含 `verifyTaskId`；新增 `fetchVerifyResult(taskId)`（404 手动处理）
- [ ] 📋 `ChatPage.tsx`：executeSend resolve 后 **loading 立即结束（不再等 verify）**；有 `verifyTaskId` → 标记消息 verifying → 轮询（2s 间隔、60s/30 次上限）→ done 更新该消息 verifiedClaims + 停止；failed/404/超时 → 停止（不显示面板，fail-open）
- [ ] 📋 轮询生命周期清理：组件卸载/重试/切换会话 → clearInterval + 竞态防护
- [ ] 📋 `ChatMessage.tsx`：`verifying` prop → "正在验证…"提示；verifiedClaims 到达后走现有可信度面板

## 4. 验收（WP4 收口）

- [ ] 📋 真实 E2E 冒烟记录：uvicorn 8001 真实 chat_stream → done 事件带 task_id、**连接关闭先于 verify 完成** → 轮询 pending→done 流转 → DB verify_results done 记录
- [ ] 📋 ADR-0013-verify-async.md 产出（决策：轮询 + 落库 + 非流式保持同步 + 计时口径变化）
- [ ] 📋 面试口径更新点落盘（verify"异步后置：答案先出、轮询补验证，结果落库持久化"）

## 5. 降级验收

- [ ] 📦 verify 后台任务异常/超时 → status=failed → 前端停止轮询不报错（fail-open，与现状空 claims 不显示一致）
- [ ] 📦 任务不存在/服务重启丢未完成任务 → 轮询 404 → 前端 fail-open（**已 done 结果 DB 不丢**）
- [ ] 📦 verify_results 写库失败 → 任务内捕获 + 日志告警，不影响主链路答案交付
- [ ] 📦 `PW_VERIFY_ASYNC=false` → 行为与现状完全一致（逃生口留证）
- [ ] 📦 全量 pytest 780+N 全绿保持

## 6. 接口兼容

- [ ] 🔌 非流式端点 /ai/rag/chat（engine.chat 同步 verify）**零改动**
- [ ] 🔌 agent / agent-lg 端点（不做 verify）**零改动**
- [ ] 🔌 request_logs 表结构/落库逻辑零改动
- [ ] 🔌 done 事件新增字段 `verify_task_id` 为**增量**（旧前端读到 done 无 task_id → 不轮询、不显示面板，fail-open）；`verified` 字段保留（开关 false 时仍 true）
- [ ] 🔌 verify_results 建表幂等（服务重复启动不报错）

## 7. 测试验收

- [ ] 🧪 `tests/test_verify_tasks.py`（新）：submit 返回 task_id / DB pending→done 更新（mock reflector.verify_answer）/ 异常→failed / get 查 DB / 轮询端点状态机（pending/done/failed/404）/ DDL 幂等 / 开关 false 无后台任务
- [ ] 🧪 chat_stream 端点测试：开关 true done 事件含 verify_task_id 且无 verified 事件；开关 false verified→done 顺序保持
- [ ] 🧪 conftest autouse fixture `default_verify_async_disabled` 钉住测试环境 `verify_async_enabled=False`（对齐 module-056/058 开关模式）；新测试显式开 true
- [ ] 🧪 前端：ragService.test（fetchVerifyResult 成功/404）、ChatPage.test（轮询 mock 更新面板 + loading 立即结束 + 清理）、ChatMessage.test（verifying 态）
- [ ] 🧪 `python -m pytest tests/ -q` — 全量 780+N 全绿（**不改存量测试掩盖**）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含 done 先于 verify 冒烟 + 轮询流转 + DB 落库 + 计时口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-060 行** + 头部"最后更新"日期改为当天
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0013-verify-async.md 状态行更新（✅ 已实施）
- [ ] 📝 **CONTEXT.md 只增不删**（verify 异步化术语追加；同步/合并永远取更全一侧）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
