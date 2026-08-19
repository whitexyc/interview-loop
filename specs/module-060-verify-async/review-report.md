# Review 报告 — Module-060: verify 异步化（后置推送 P2，落库持久化）

> Reviewer | 2026-08-13
> 审查范围：plan.md / acceptance-criteria.md / task-brief.md / ADR-0013 / changelog.md + 全部变更文件（后端 verify_tasks.py / database.py / models.py / config.py / main.py / conftest.py / test_verify_tasks.py + 前端 5 文件 + 4 测试文件 + 记忆三件套）
> 独立验证：全量 pytest 复跑（795/2）+ 前端 vitest 复跑（58/0）+ tsc/vite build + 2 项环境性失败根因定位 + 变更范围逐文件核对

---

## 1. 结论

**✅ Pass（无 major 问题 → 进 Tester）**

| 维度 | 结论 |
|------|------|
| 方法学 | ✅ 与 plan/task-brief 一致（用户三决策：轮询 + 非流式同步 + 落库）；口径声明完整 |
| 正确性 | ✅ 核心逻辑正确（pending 先落库再调度 / _run_verify 状态流转 / 轮询端点状态机 / chat_stream 开关两分支） |
| 降级链 | ✅ fail-open 全链（落库失败→无 task_id / 异常→failed / 404→停止 / 开关 false 逐字一致逃生口） |
| 诚实性 | ✅ 真实 E2E 如实标"待环境"（本机无 PostgreSQL）；2 项 Redis 失败如实归因环境 |
| 测试 | ✅ 后端 17 项 mock DB 全绿 + 前端 58/0 + build PASS；独立复跑一致 |
| 结果解读 | ✅ 数字与独立复跑一致；2 项失败经复现确认为环境（Redis 未运行），非本模块回归 |
| 风格与最小改动 | ✅ 中文注释、对齐既有模式（_schedule_persist / 048/058 DDL / conftest 开关钉住）；无投机性改动 |
| 记忆核查 | ✅ project-context 模块行 + 头部日期、activity Developer 行、file-index 行、ADR-0013 状态行、CONTEXT.md 只增 全部落实 |

---

## 2. 独立验证记录

### 2.1 全量 pytest 独立复跑

`python -m pytest tests/ -q` → **795 passed / 2 failed（231.57s）**，与 changelog §5.4 逐字一致。

2 项失败：`test_cache.py::TestDeleteByPrefix::test_prefix_invalidation_real_redis`、`test_llm_chain.py::TestChainPersistence::test_set_get_roundtrip_real_redis`。复现确认失败原因为 **Redis 未运行**（`Get-Process redis-server` 无进程、`localhost:6379` TcpTestSucceeded=False，redis-py 8.1 连接报 `Timeout connecting to server`）。module-060 变更零触碰 cache.py / llm_chain.py / 任何 Redis 代码（diff 核对），故为环境依赖、非本模块回归——**AC「全量 780+N 全绿」在本环境未字面满足**，如实标注（见 minor #3）。

### 2.2 前端 vitest 复跑 + build

- `npx vitest run` → **58 passed / 0 failed**（9 测试文件，其中含 2 个遗留调试文件，见 minor #2）。
- `npx tsc --noEmit` → exit 0；`npx vite build` → 构建成功（chunk >500kB 为既有提示，非本模块引入）。

### 2.3 新测试逐文件收集计数

| 文件 | changelog 声称 | 实际 | 结论 |
|------|--------------|------|------|
| test_verify_tasks.py（后端） | 17 | 17（4+4+1+5+3） | ✅ |
| ragService.test.ts（前端） | +6 | +6（done 解析 3 + fetchVerifyResult 3） | ✅ |
| ChatPage.test.tsx（前端） | +4 轮询（+3 存量环境性修复） | +4 | ✅ |
| ChatMessage.test.tsx（前端） | +4 | +4 | ✅ |

### 2.4 关键实现逐点核对（通过项摘录）

- **WP1 submit_verify_task**：先插 pending（`_insert_pending`，DB 写失败捕获返回 None fail-open）→ `asyncio.create_task` fire-and-forget → 池存 `{answer, docs, identity, query, trace_id, task}` 防 GC → done callback pop 释放。开关关返回 None 不产生任务（AC §1「开关 false 时 verify_tasks 不产生后台任务」✅，conftest 钉住 + 显式测试双证）。
- **WP1 _run_verify**：`perf_counter` 计时 → `reflector.verify_answer`（复用 15/20/15s 内部超时）→ `_update_done`/`_update_failed`；任务内全捕获绝不抛回。verify_answer 内部超时返回 empty_result（非异常）→ done + 空 claims（前端 claims.length>0 不显示，与现状空 claims fail-open 一致）——status=failed 仅真异常触发（minor #4 语义注记）。
- **WP2 chat_stream**：开关 true 不再同步 await verify → done 带 `verify_task_id`/`verified:false`、不再发 verified 事件、连接早于 verify 关闭（测试断言 `verified` 不在事件序列 + verify_answer 零调用）；提交失败 done 无 task_id（fail-open）。开关 false 现状同步路径逐字一致（测试断言事件序列 `step,step,step,step,token,token,verified,done`）。`clean_answer` 截断剥离保留（main.py:597）。identity 用 `resolve_identity`（user_id 优先 client_ip 兜底，测试断言 XFF→"9.9.9.9"）、trace_id 从 `request.state.trace_id`（中间件注入）。
- **WP2 轮询端点**：读 DB 为准（`get_verify_task`）；pending/done/failed 200、不存在/查询异常 404 fail-open（测试覆盖 5 态）。request_logs 表零改动（diff 核对）。
- **WP3 前端**：types 两字段、chatStream done 解析 `verify_task_id`（增量兼容，无 task_id 不轮询）、`fetchVerifyResult` 404 归一化 failed；ChatPage loading 立即结束（finally，不再等 verify）+ verifying 态 + `startVerifyPolling` 2s/30 次上限 + done 更新 verifiedClaims + failed/404/超时停止 fail-open + 生命周期清理（新发送/重试/切会话/新建/卸载 clearInterval + `verifyTimerRef.current === timer` 竞态防护）；ChatMessage verifying prop + "正在验证…"提示（isStreaming/用户消息/verifiedClaims 已到 均不显示）。handleRetry 续作补齐与 doSend 一致。
- **DDL/ORM**：VERIFY_RESULTS_DDL 幂等（CREATE TABLE IF NOT EXISTS + 分号拆分，对齐 048/058）；VerifyResult ORM 字段与 DDL 对齐；`init_db()` 追加调用。
- **变更范围**：非流式 /ai/rag/chat、agent/agent-lg、request_logs **零改动**（diff 核对）；`agent/router.py` / `test_golden_intent.py` / module-033 changelog 为先前会话遗留（module-058 已标注），非本模块范围。
- **记忆/文档**：project-context module-060 行 + 头部日期 2026-08-13 ✅；activity Developer 行 ✅（本行 Reviewer 追加）；file-index 3+4 行 ✅；ADR-0013 状态行 ✅ 已实施；CONTEXT.md 只增（verify 异步化节）✅；Developer changelog 注明开工前已读 project-context ✅。

---

## 3. Major Findings（必须修复）

无。

---

## 4. Minor Findings（不阻塞，建议收口时处理）

1. **前端轮询竞态：`patchLastAssistant` 未受清理保护（AC §3「竞态防护」只覆盖了 stopTimer）**（`frontend/src/pages/ChatPage.tsx` startVerifyPolling）。当用户在新消息 B 发送后、上一轮 A 轮询的 in-flight `fetchVerifyResult` 恰在此窗口 resolve 时：`clearVerifyPolling` 已清 timer，但回调仍会执行 `patchLastAssistant`，把**旧任务 A 的 verifiedClaims 挂到最新消息 B**（或把 A 的 failed 态清掉 B 的 verifying）。现有防护 `verifyTimerRef.current === timer` 仅保护 `stopTimer`，不保护 `patchLastAssistant`。窗口极窄（fetch 为 DB 单行查询，ms 级 + 需 A 恰在此时 done），非阻塞。建议：轮询启动时捕获目标消息标识（如消息 index/`data.messageId`），`patchLastAssistant` 前校验目标仍是待补消息。
2. **遗留调试测试文件未清理**（`frontend/src/__tests/_debug_m060.test.tsx`、`_debugm2.test.tsx`，均未跟踪、含 `console.log` + `expect(true).toBe(true)` 空断言）。当前 vitest "58/0" 中 2 项即来自这两个调试文件，计数含噪声。建议：收口前删除，58→56 为真实有效用例数。
3. **AC「全量 pytest 780+N 全绿」本环境未字面满足（795/2）**：2 项为真实 Redis 用例，失败根因=Redis 未运行（端口 6379 关闭，已复现），module-060 零触碰 Redis 代码，属环境依赖而非本模块回归；Developer 已诚实标注。建议：Tester 复跑确认同根因，changelog/记忆将 2 项持续标注为"待环境"（与真实 E2E 待环境同口径）；修复方向（升级本地 Redis ≥6 或 cache.py `protocol=2`）留后续模块。
4. **文档措辞「异常/超时 → status=failed」与实现有细微出入**（AC §1/§5、changelog §2.1）：实现中 verify_answer 内部 15/20/15s 超时返回 empty_result（非异常），落库为 `done` + 空 claims（前端 claims.length>0 不显示，fail-open 一致）；`status=failed` 仅真异常（如落库/未预期错误）触发。**行为比措辞更合理**（优雅降级不应记 failed），建议 changelog/AC 措辞补充"verify_answer 内部超时 → done + 空 claims（前端不显示）"以消除歧义。
5. **观察（非本模块）**：`frontend/src/pages/ChatPage.tsx` 轮询上限为"2s × 30 次 = 60s"硬停，若 verify 恰在 60s 后完成则结果不展示（fail-open 边界，已声明，符合设计）；无 action 建议。

---

## 5. AC 逐条核查摘要

| AC 分组 | 结果 | 说明 |
|--------|------|------|
| §1 WP1 功能（7 项） | ✅ 全过 | submit/run/get/内存池/DDL/PW_VERIFY_ASYNC 全部实现且有测试 |
| §2 WP2 功能（5 项） | ✅ 全过 | 开关两分支 + 轮询端点状态机 + clean_answer 保留 + request_logs 零改动 |
| §3 WP3 前端（5 项） | ✅ 全过 | types/service/ChatPage/ChatMessage/生命周期清理（竞态防护基本到位，见 minor #1） |
| §4 WP4 收口（3 项） | ⚠️ 部分 | ADR-0013 ✅ / 面试口径 ✅ / **真实 E2E 待环境**（无 PostgreSQL，诚实标注，方法学+命令已就绪） |
| §5 降级（5 项） | ✅ 全过（1 项注明） | failed/404/写库失败/开关回退全过；"全量全绿"见 minor #3（795/2 环境性） |
| §6 接口兼容（5 项） | ✅ 全过 | 非流式/agent/agent-lg/request_logs 零改动；done 增量字段兼容；DDL 幂等 |
| §7 测试（5 项） | ✅ 全过 | test_verify_tasks 17 + 端点测试 + conftest 钉住 + 前端测试 + 独立复跑一致 |
| §8 文档记忆（7 项） | ✅ 全过 | 三件套 + ADR-0013 状态行 + CONTEXT 只增 + 开工前已读 |

---

## 6. Reviewer 活动记录

`memory/agent-activity-log.md` 已追加本行（2026-08-13 + module-060 + Reviewer + verdict pass + 主要发现摘要）。
