# ADR-0013：verify 异步化（后置推送，落库持久化）

## 元信息

- 状态：✅ **已实施（module-060，2026-08-13）**——chat_stream 流式生成完不再同步 await verify，改 `asyncio.create_task` 后台执行 + done 事件带 `verify_task_id` + 前端 2s 轮询 `GET /ai/rag/chat/verify/{task_id}` 补结果，结果落 `verify_results` 表持久化（pending→done/failed，done 不因重启丢失）；`PW_VERIFY_ASYNC` 默认 true（false 回退现状同步路径逃生口）。详见 `specs/module-060-verify-async/changelog.md`
- 日期：2026-08-13
- 关联：module-051（HHEM 裁判接入）、module-055（HHEM 超时四层修复）、module-058（observability/计时）、module-048（feedback 表幂等 DDL 模式）、module-033（`_schedule_persist` fire-and-forget 先例）、backlog「异步后置推送 P2」

## 背景：现状（代码实测）

- verify（证据链幻觉检测）当前**同步阻塞在流式 SSE 主链路尾部**：`main.py:598` `verified = await reflector.verify_answer(clean_answer, docs)` 在 `done` 事件之前，verify 15-50s（LLM 拆句 15s + HHEM 20s + LLM 判分 15s 降级链）卡住前端 `loading`（ChatPage doSend await 涵盖整个 SSE）。module-055 已把交叉对数/截断/预算优化到 ~2.4-9s，但瓶颈仍在主链路内。
- 前端 SSE 解析读到 done 不 break，**连接关闭才 resolve**——故 verify 结束前前端无法结束 loading。

## 决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| verify 结果送达机制 | **前端轮询**（GET /ai/rag/chat/verify/{task_id}，2s 间隔、60s 上限） | 比 SSE 推送简单可靠（后台任务生命周期跨连接）；轮询为轻量 DB 主键查询，成本可忽略 |
| 非流式端点 /ai/rag/chat | **保持同步不动** | 前端已不用（契约稳定，E2E 零影响）；只改用户实际使用的流式路径 |
| verify 结果存储 | **落库持久化**（verify_results 表） | ① done 结果重启不丢（DB 为准）；② verify 结果含逐句 verdict，成为**飞轮数据源**（答案可信度/幻觉调优）；③ 轮询端点直接读表，不读内存 |
| 后台执行方式 | `asyncio.create_task` fire-and-forget（不 await） | 对齐 `engine._schedule_persist` 成熟模式（module-033）；只调度不 await，任务引用入内存池防 GC |
| 开关 | `PW_VERIFY_ASYNC` 默认 true，false 回退现状同步路径 | 逃生口：存量 chat_stream 行为逐字一致，任何意外可一键回退 |
| 计时口径 | request_logs 不再有 verify 阶段；耗时由轮询 `verified_in_ms` 返回 | 异步化后 verify 不占主链路，端点侧无法再计 verify 耗时（口径变化如实记录） |

## 关键业务规则

1. **DB 为准**：轮询端点读 `verify_results` 表（不读内存任务池）；重启丢未完成任务 → 404 → 前端 fail-open（与现状空 claims 不显示一致）；已 done 结果永久可查。
2. **任务内部超时复用** `reflector.verify_answer` 既有 15/20/15s（不新增无限任务）。
3. **全链路 fail-open**：pending 落库失败 → done 无 task_id（前端不轮询）；verify 异常 → status=failed → 轮询返回 failed → 前端停止不报错；DB 写失败 → 日志告警不影响主链路。
4. **结果不清理**：verify_results 保留（飞轮数据源）。
5. **前端生命周期**：轮询 timer 在卸载/重试/切会话/新发送时清理（useRef + 竞态防护）。

## 降级链

```
verify 后台任务异常/超时 → status=failed → 前端停止轮询不显示面板（fail-open，与现状空 claims 不显示一致）
任务不存在/重启丢未完成 → 轮询 404 → 前端 fail-open（已 done 结果 DB 不丢）
verify_results 写库失败 → 任务内捕获 + 日志告警，不影响主链路答案交付
PW_VERIFY_ASYNC=false → chat_stream 走现状同步路径（verified→done 顺序逐字一致，逃生口）
```

## 验证（module-060）

- 单测 17 项（test_verify_tasks.py，mock DB 全绿）：submit/get/状态流转/TTL 释放/开关/轮询端点状态机/chat_stream 开关两分支。
- 前端测试 58/0 + build PASS：done 解析 task_id / 轮询 done 更新面板 / pending 多轮 / failed/404 停止 / loading 立即结束 / 卸载清理 / verifying 态。
- 全量 pytest：**795 passed / 2 环境性失败**（真实 Redis 用例——本机 Redis 3.2 不支持 redis-py 8.1 RESP3 HELLO，非本模块回归）。
- 真实 E2E **待环境**：本机无 PostgreSQL（服务 init_db 依赖，无法启动）；方法学 + 命令见 changelog §7。

## 面试话术

> "流式对话尾部的幻觉检测（verify，15-50s）原来是同步阻塞在 SSE 主链路里——答案流完了，前端 loading 还一直转圈等验证。我把它改成**异步后置**：流式生成完立即发 done（带 verify_task_id）、关闭连接，loading 立刻结束；verify 用 asyncio.create_task 后台跑（fire-and-forget，内部沿用 15/20/15s 超时），结果写 verify_results 表持久化；前端 2s 轮询 GET /ai/rag/chat/verify/{task_id} 补结果，done 就更新可信度面板，failed/404 就 fail-open 不显示。关键取舍：**DB 为准**——重启丢未完成任务就 404 fail-open，但已 done 的结果不丢，而且 verify 结果成了飞轮数据源（逐句 verdict 可支撑幻觉调优）；**非流式端点保持同步不动**（契约稳定）；**PW_VERIFY_ASYNC=false 逃生口**走旧逻辑逐字一致。感知延迟从 15-50s 降到答案流完即止。"
