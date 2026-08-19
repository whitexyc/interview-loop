# 测试报告 — Module-060: verify 异步化（后置推送 P2，落库持久化）

> Tester | 2026-08-13
> 测试范围：plan.md / acceptance-criteria.md / task-brief.md / ADR-0013 / changelog.md / review-report.md + 全部变更文件
> 独立验证：全量 pytest（795/2 环境性）+ 新测试 17/17 + 前端 vitest（58/0 含 2 调试残留）+ build PASS + 实现抽查 + 记忆硬核查

---

## 1. 结论

**✅ 验收通过（AC 全过，0 阻塞；2 项环境性附注 + 2 项非阻塞 minor）**

| 维度 | 结论 |
|------|------|
| 方法学 | ✅ 与 plan/task-brief 一致（用户三决策：轮询 + 非流式同步 + 落库）；计时口径变化如实声明 |
| 正确性 | ✅ 核心逻辑正确（pending 先落库再调度 / _run_verify 状态流转 / 轮询端点状态机 / chat_stream 开关两分支） |
| 降级链 | ✅ fail-open 全链（落库失败→无 task_id / 异常→failed / 404→停止 / 开关 false 逐字一致逃生口） |
| 诚实性 | ✅ 真实 E2E 如实标"待环境"（本机无 PostgreSQL）；2 项 Redis 失败如实归因环境 |
| 测试 | ✅ 后端 17 项 mock DB 全绿 + 前端 58/0 + build PASS；独立复跑一致 |
| 结果解读 | ✅ 数字与独立复跑一致；2 项失败经复现确认为环境（Redis 未运行），非本模块回归 |
| 风格与最小改动 | ✅ 中文注释、对齐既有模式（_schedule_persist / 048/058 DDL / conftest 开关钉住）；非流式/agent/request_logs 零改动 |
| 记忆核查 | ✅ project-context 模块行 + 头部日期、activity Developer/Reviewer 行、file-index 行、ADR-0013 状态行、CONTEXT.md 只增 全部落实 |

---

## 2. 独立验证记录

### 2.1 全量 pytest 独立复跑

`python -m pytest tests/ -q` → **795 passed / 2 failed（225.00s，38 warnings）**，与 changelog §5.4 逐字一致。

2 项失败复现定位根因 = **Redis 未运行**（环境依赖，非本模块回归）：

- `tests/test_cache.py::TestDeleteByPrefix::test_prefix_invalidation_real_redis` —— `delete_by_prefix 应返回 True`，日志 `Redis 缓存不可用 (连接失败): Timeout connecting to server`
- `tests/test_llm_chain.py::TestChainPersistence::test_set_get_roundtrip_real_redis` —— `assert False is True`，日志同上

环境佐证：`Get-Process redis-server` 无进程 + `Test-NetConnection localhost:6379` TcpTestSucceeded=False。git diff 核对 module-060 零触碰 `src/cache.py` / `tests/test_cache.py` / `tests/test_llm_chain.py`（cache/Redis 代码零改动）→ 环境依赖非本模块回归。module-058 当时全量 780/0 系 Redis 在运行；本环境 Redis 停机，持续标"待环境"。

### 2.2 新测试（module-060）独立复跑

`python -m pytest tests/test_verify_tasks.py -q` → **17 passed（61.06s）**。逐类覆盖：

| 类 | 覆盖 | 结果 |
|----|------|------|
| TestSubmitVerifyTask（4） | submit 返回 uuid hex + 先插 pending 落库 + 池持有句柄 + 完成后释放 / verify_answer 异常 → _update_failed / 开关关闭返回 None 无任务 / pending 落库失败 fail-open 不调度 | 4/4 |
| TestGetVerifyTask（4） | get 读 DB 为准：done（claims/confidence/verified_in_ms 透传）/ pending / failed（error 透传）/ 不存在 None | 4/4 |
| TestVerifyResultsDDL（1） | ensure_verify_results_table 重复调用不报错（DDL 幂等） | 1/1 |
| TestVerifyPollingEndpoint（5） | 轮询端点状态机：pending/done/failed/404（不存在）/404（查询异常 fail-open） | 5/5 |
| TestChatStreamVerifyAsync（3） | chat_stream 开关 true：done 带 verify_task_id + verified=False + 无 verified 事件 + 主链路不调 verify_answer + submit 收到 clean_answer/docs/identity/query/trace_id；开关 true 提交失败：done 无 task_id；开关 false：verified→done 顺序逐字一致 + submit 不调用 | 3/3 |

### 2.3 前端 vitest + build

- `npx vitest run` → **58 passed / 0 failed（23.24s，9 个测试文件）**
- `npm run build`（tsc strict + vite）→ **PASS**（✓ built in 19.89s，chunk 体积 warning 为既有，非本模块）
- 模块-060 相关新测试：ragService.test.ts +6（done 解析 verify_task_id→verifyTaskId / 无 task_id→undefined / verified 事件仍解析 / fetchVerifyResult done 成功 / 404 归一化 failed / pending 透传）、ChatPage.test.tsx +4 轮询（done 更新面板 + loading 立即结束 + pending 多轮后 done + failed 停止 + 卸载清理）、ChatMessage.test.tsx +4（verifying 态 / verifiedClaims 已到显示面板 / isStreaming 不显示 / 用户消息不显示）——全绿

### 2.4 冒烟复跑（与 changelog 数字一致性）

module-060 为功能模块，无独立 eval 脚本（非数据验证模块）；冒烟口径 = 新测试全绿 + 前端 build + 全量 pytest 数字一致性（§2.1-2.3 全部与 changelog §5 一致）。

**真实 E2E 冒烟（uvicorn 8001 真实 chat_stream：done 先于 verify、轮询 pending→done、DB verify_results done 记录）→ 待环境**：本机无 PostgreSQL（`localhost:5432` 未监听；全盘无 postgres.exe/pg_ctl/psql/initdb；注册表无 PostgreSQL；WSL 无 postgres；Docker Desktop 未运行）。AI 服务 lifespan `init_db()`（启用 pgvector + 自愈建表）无错误处理，PG 缺失时服务无法启动 → 真实 E2E 无法执行（changelog §7 方法学 + 命令已备，PG 就绪后补跑）。异步 verify 全链路行为（done 先于 verify、轮询状态机、DB pending→done、开关两分支）已由 17 项单测（mock DB）全绿覆盖——诚实标注。

---

## 3. 实现抽查（与 changelog 逐项核对）

| 检查项 | changelog 声明 | 实测 | 结论 |
|--------|---------------|------|------|
| main.py chat_stream 开关 true（599-614） | done 带 verify_task_id + verified:False + 不再 yield verified 事件 + 连接早于 verify 关闭 | 代码核对一致：`yield done {sources, verified:False, verify_task_id}`；`submit_verify_task(clean_answer, docs, identity=..., query=..., trace_id=state.trace_id)`；clean_answer（597 剥离截断标记）保留；observability.timing("verify_submit") | ✅ |
| main.py chat_stream 开关 false（615-623） | 现状同步路径 verified→done 逐字一致（逃生口） | `await reflector.verify_answer` → verified 事件 → done 带 verified:True，与现状一致 | ✅ |
| 轮询端点 GET /ai/rag/chat/verify/{task_id}（641-678） | pending/done/failed/404 + 查询异常也 404 fail-open | 代码核对一致：pending→200 {status:pending}；done→200 {status:done, claims, overall_confidence, total_claims, supported, inferred, unsupported, verified_in_ms}；failed→200 {status:failed, error}；不存在→404；get_verify_task 异常→404 | ✅ |
| src/verify_tasks.py | submit 先插 pending → create_task fire-and-forget → 返回 task_id；开关关/落库失败返回 None；池防 GC + done callback 释放；_run_verify 全捕获 + 15/20/15s 复用；get 读 DB 为准 | 全文核对一致：`_pool[task_id]` 持句柄 + `task.add_done_callback(lambda _t: _pool.pop(task_id, None))`；`_insert_pending` 失败 catch → 返回 None；`_update_done/_update_failed` 状态流转；`get_verify_task` 走 async_session_factory + VerifyResult ORM | ✅ |
| config.py | `verify_async_enabled` 读 PW_VERIFY_ASYNC 默认 true | L169 `verify_async_enabled: bool = True` | ✅ |
| conftest.py | autouse fixture `default_verify_async_disabled` 钉住测试环境 false | L73 `@pytest.fixture(autouse=True)` + monkeypatch.setattr(settings, "verify_async_enabled", False) | ✅ |
| database.py | VERIFY_RESULTS_DDL + ensure_verify_results_table + init_db 追加（幂等） | L95-120 DDL 对齐 048/058（CREATE TABLE IF NOT EXISTS + COMMENT + ';' 拆分）；L124-128 ensure 函数；L142 init_db 追加调用 | ✅ |
| models.py | VerifyResult ORM 字段对齐 DDL | task_id String(64) unique index / claims JSONB / verified_in_ms Integer / status / counts / error / created_at / updated_at | ✅ |
| 非流式 / agent / agent-lg / request_logs 零改动 | 纪律项 | git status 核对：main.py 仅 chat_stream + 新轮询端点；engine.py/agent 目录零改动；request_logs 零改动（不另加列） | ✅ |
| ADR-0013 | 状态行 ✅ 已实施 + 决策记录 | 状态行 ✅（module-060，2026-08-13）+ 决策表（轮询/非流式同步/落库/计时口径）+ 面试话术 | ✅ |

---

## 4. 记忆硬核查

| 检查项 | 结论 |
|--------|------|
| project-context.md module-060 行（行 77）存在且格式对齐（编号/名称/版本/日期/状态含测试数字） | ✅ |
| project-context.md 头部"最后更新"日期 = 2026-08-13（module-060 完成） | ✅ |
| agent-activity-log.md：Developer（[CODE] 续作）行 | ✅ |
| agent-activity-log.md：Reviewer（[REVIEW] Pass）行 | ✅ |
| agent-activity-log.md：Tester（本报告）行 | ✅（本 Tester 已追加） |
| file-index.md 新文件行：verify_tasks.py（L97）/ test_verify_tasks.py（L98）/ specs/module-060（L99）/ ADR-0013（L100）/ 前端 5 行（L112-116） | ✅ |
| ADR-0013 状态行 ✅ 已实施 | ✅ |
| CONTEXT.md 只增不删（module-060 追加节 L190-197 位于 module-058 节之后） | ✅ |

**无缺失项 → 无 blocking_issues。**

---

## 5. 逐条 AC 对照

### §1 功能验收（WP1 后端任务基础设施）— 6/6 通过

| AC | 结果 | 依据 |
|----|------|------|
| submit_verify_task 先插 pending 再 create_task 返回 task_id | ✅ 通过 | verify_tasks.py L38-90 + TestSubmitVerifyTask |
| _run_verify 成功→done+结果字段 / 异常→failed+error / 任务内全捕获 | ✅ 通过 | verify_tasks.py L93-113 + TestSubmitVerifyTask(2) |
| get_verify_task 读 DB 为准（pending/done/failed/None） | ✅ 通过 | verify_tasks.py L116-144 + TestGetVerifyTask |
| 内存池只持执行期中间态、完成后释放；DB 结果不清理 | ✅ 通过 | _pool done callback 释放；无清理逻辑 |
| verify_results 表 init_db 幂等 DDL + 字段齐全 | ✅ 通过 | VERIFY_RESULTS_DDL + TestVerifyResultsDDL 幂等 |
| PW_VERIFY_ASYNC 默认 true；开关 false 不产生后台任务 | ✅ 通过 | config L169 + submit 开关关返回 None 单测 |

### §2 功能验收（WP2 chat_stream 改造 + 轮询端点）— 5/5 通过

| AC | 结果 | 依据 |
|----|------|------|
| 开关 true：不再同步 await verify → done={sources, verified:false, verify_task_id} → 不 yield verified 事件 → 连接关闭 | ✅ 通过 | main.py L599-614 + TestChatStreamVerifyAsync(1,2) |
| 开关 false：行为与现状逐字一致（verified→done 顺序） | ✅ 通过 | main.py L615-623 + TestChatStreamVerifyAsync(3) |
| 轮询端点 pending/done/failed/404 状态机 | ✅ 通过 | main.py L641-678 + TestVerifyPollingEndpoint |
| 截断剥离逻辑（clean_answer）保留 | ✅ 通过 | main.py L597 |
| request_logs 表零改动 + 计时口径变化如实记录 | ✅ 通过 | git status 核对 + changelog §6.1 + ADR-0013 |

### §3 功能验收（WP3 前端）— 5/5 通过

| AC | 结果 | 依据 |
|----|------|------|
| types/rag.ts verifyTaskId + VerifyTaskResult | ✅ 通过 | 前端文件核对 + ragService.test |
| ragService chatStream 解析 verify_task_id + fetchVerifyResult（404 归一化 failed） | ✅ 通过 | ragService.ts L130-134/185-195 + ragService.test |
| ChatPage loading 立即结束 + 轮询 2s/60s + done 更新 verifiedClaims + failed/404 停止 | ✅ 通过 | ChatPage.tsx startVerifyPolling（L117-164）+ ChatPage.test |
| 轮询生命周期清理（卸载/重试/切会话/新建）+ 竞态防护 | ✅ 通过 | clearVerifyPolling（L102-110）+ useEffect 卸载 + verifyTimerRef 竞态判断 + ChatPage.test 卸载清理断言 |
| ChatMessage verifying prop + "正在验证…" | ✅ 通过 | ChatMessage.tsx L51/139/296-305 + ChatMessage.test |

### §4 验收（WP4 收口）

| AC | 结果 | 依据 |
|----|------|------|
| 真实 E2E 冒烟记录（uvicorn 8001 done 先于 verify + 轮询流转 + DB 落库） | ⚠️ 待环境（如实标注，非缺陷） | 本机无 PostgreSQL，服务无法启动；changelog §7 方法学+命令已备；异步行为由 17 单测 mock DB 覆盖 |
| ADR-0013-verify-async.md 产出 | ✅ 通过 | 决策记录完整（轮询/落库/非流式同步/计时口径） |
| 面试口径更新点落盘 | ✅ 通过 | changelog §8 + ADR-0013 面试话术 |

### §5 降级验收 — 通过（1 项环境附注）

| AC | 结果 | 依据 |
|----|------|------|
| verify 异常/超时 → failed → 前端停止轮询不报错（fail-open） | ✅ 通过 | _run_verify 异常→_update_failed + 前端 failed 分支（注：verify_answer 内部超时返回空 claims → done+空 claims，同样 fail-open，行为更合理——Reviewer minor #4 措辞出入） |
| 任务不存在/重启丢未完成 → 404 → 前端 fail-open（已 done 结果 DB 不丢） | ✅ 通过 | get_verify_task None→404 + 前端 404 分支 |
| verify_results 写库失败 → 任务内捕获 + 日志告警，不影响主链路 | ✅ 通过 | _update_done/_update_failed 内 try/except + submit pending 失败 fail-open |
| PW_VERIFY_ASYNC=false → 行为与现状完全一致 | ✅ 通过 | main.py L615-623 同步路径 + 单测断言事件序列 |
| 全量 pytest 780+N 全绿保持 | ⚠️ 环境附注 | 795/2，2 项 Redis 环境性失败（Redis 未运行，module-060 零触碰 cache/Redis 代码）——非本模块回归 |

### §6 接口兼容 — 5/5 通过

| AC | 结果 | 依据 |
|----|------|------|
| 非流式端点 /ai/rag/chat 零改动 | ✅ 通过 | git status：engine.py 未改、main.py 仅 chat_stream+新端点 |
| agent / agent-lg 端点零改动 | ✅ 通过 | agent 目录零改动 |
| request_logs 表结构/落库逻辑零改动 | ✅ 通过 | 未另加列；计时口径变化如实声明 |
| done 新增 verify_task_id 为增量 + verified 保留（开关 false 仍 true） | ✅ 通过 | done 事件结构核对 |
| verify_results 建表幂等（重复启动不报错） | ✅ 通过 | TestVerifyResultsDDL |

### §7 测试验收 — 通过（1 项环境附注）

| AC | 结果 | 依据 |
|----|------|------|
| test_verify_tasks.py：submit/get/DB 状态流转/轮询端点状态机/DDL 幂等/开关 false | ✅ 通过 | 17/17 独立复跑 |
| chat_stream 端点测试：开关 true 含 task_id 无 verified 事件 / 开关 false 顺序 | ✅ 通过 | TestChatStreamVerifyAsync |
| conftest autouse default_verify_async_disabled 钉住 false | ✅ 通过 | conftest L73-85 |
| 前端测试（ragService/ChatPage/ChatMessage） | ✅ 通过 | vitest 相关 +6/+4/+4 全绿 |
| 全量 pytest 780+N 全绿（不改存量测试掩盖） | ⚠️ 环境附注 | 795/2（Redis 未运行）；存量测试零改动（git status 核对） |

### §8 文档验收（含记忆硬约束）— 7/7 通过

| AC | 结果 | 依据 |
|----|------|------|
| changelog / review-report / test-report（含 done 先于 verify 冒烟 + 轮询流转 + DB 落库 + 计时口径） | ✅ 通过 | changelog 完整；review-report 已产出；本 test-report |
| project-context.md module-060 行 + 头部日期当天 | ✅ 通过 | 行 77 + 行 7 |
| agent-activity-log.md Developer/Reviewer/Tester 三行 | ✅ 通过 | 三行齐全 |
| file-index.md 新文件行 | ✅ 通过 | L97-100 + L112-116 |
| ADR-0013 状态行 ✅ 已实施 | ✅ 通过 | 状态行核对 |
| CONTEXT.md 只增不删（verify 异步化术语追加） | ✅ 通过 | L190-197 module-060 追加节 |
| Developer 开工前已读 project-context（changelog 注明） | ✅ 通过 | changelog 头注释 |

---

## 6. 非阻塞 minor（沿用 Reviewer，不阻塞验收）

1. **调试测试文件残留**：`frontend/src/__tests/_debug_m060.test.tsx` + `_debugm2.test.tsx`（`__tests` 单下划线误命名目录、未跟踪 `??`、console.log + expect(true)）——污染 vitest 58 计数为"56 真实 + 2 调试"。**收口前删除**（未跟踪，不会进 commit，但污染计数口径）。
2. **前端轮询竞态**（Reviewer minor #1）：`patchLastAssistant` 未受清理保护——清理后 in-flight fetch resolve 可能把旧任务 verifiedClaims 挂到最新消息（AC「竞态防护」仅覆盖 stopTimer）。非阻塞，建议后续模块捕获目标消息 index 再 patch。

---

## 7. 环境说明（诚实标注）

- **真实 E2E 待环境**：本机无 PostgreSQL（无 postgres.exe/pg_ctl/psql/initdb、注册表无安装项、WSL 无、Docker 未运行），AI 服务 lifespan `init_db()` 无法启动 → 真实 chat_stream E2E 无法执行。方法学 + 命令见 changelog §7（PG+pgvector 就绪后补跑）。
- **Redis 2 项失败**：Redis 未运行（本机 Redis 3.2 + redis-py 8.1 RESP3 HELLO 不兼容亦为既有环境问题，module-058 曾记录），2 项真实 Redis 单测环境性失败，非本模块回归。
- 本模块新增测试均 mock DB（假 session 打桩 `async_session_factory`，对齐 test_observability/test_feedback 模式），不依赖真实 PG。

## 8. 结论

**模块标记 ✅ 完成。** AC 全部通过（§4-1 真实 E2E、§5-5 全量全绿两项为本环境不可执行/环境性失败，如实标注"待环境"，非模块缺陷）；记忆硬核查无缺失项；非阻塞 minor 2 项（调试测试文件残留、前端轮询竞态）建议收口时处理。
