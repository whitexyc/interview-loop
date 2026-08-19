# 功能规格说明书 — Module-060: verify 异步化（后置推送 P2，落库持久化）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。
> 详细执行简报见同目录 `task-brief.md`（已探明事实，勿重复调研）。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-060 |
| 模块名称 | verify 异步化（证据链验证后置推送，module-051 P2 落地） |
| 优先级 | P2（积压已久的体验优化，非功能缺口） |
| 预估代码量 | 功能代码（不含注释/测试）约 200-250 行；含注释/测试约 550-650 行（前端 + 后端）——按含注释/测试口径预估，豁免默认 ≤200 功能代码上限 |
| 创建日期 | 2026-08-13 |
| 最后更新 | 2026-08-13 |
| 负责人 | Planner: 主会话, Developer: vibe-coding-workflow |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户输入（对话确认）+ 既有 backlog（module-051 plan.md:96 P2"异步后置推送"）
- 原始描述：verify（幻觉检测）同步阻塞流式主链路尾部 15-50s，答案已出但前端 `loading` 持续转圈。需异步化：答案先交付，验证后到。

### 2.2 用户故事

```
作为 知识库问答的使用者
我想要 答案流完就立即结束"生成中"状态（loading 结束），验证结果后台跑、完成后再显示
以便 不再为验证等待 15-50s，感知延迟大幅下降；验证结果仍能完整展示
```

### 2.3 验收场景（BDD 格式）

```
场景 1：流式对话答案不阻塞
  假设 用户发起一个 knowledge 问题（真实 RAG 链路）
  当 流式生成结束，后端提交 verify 后台任务并立即发 done 事件（带 verify_task_id）、关闭连接
  那么 前端 loading 立即结束；验证期间消息显示"正在验证…"；轮询拿到 done 结果后显示可信度面板

场景 2：verify 失败 fail-open
  假设 verify 后台任务异常/超时（reflector 既有降级返回空 claims）
  当 任务标记 failed、轮询接口返回 {status: "failed"}
  那么 前端停止轮询、不显示验证面板、不报错（与现状"空 claims 不显示"一致）

场景 3：开关关闭零回归
  假设 PW_VERIFY_ASYNC=false
  当 发起流式请求
  那么 chat_stream 行为与现状逐字一致（同步 verify → verified 事件 → done 事件）

场景 4：已完成结果持久化
  假设 某次 verify 任务 done 且已落库 verify_results
  当 服务重启后前端凭 task_id 再次轮询
  那么 仍能查到 done 结果（DB 为准，重启不丢已完成结果）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 响应时间 | 答案首字 TTFB 不变；**请求完成（loading 结束）不再等 verify**（15-50s 从主链路移除）；轮询间隔 2s、上限 60s |
| 并发量 | 内存任务池 asyncio 单线程无锁；verify 任务 CPU/网络密集但异步不阻塞事件循环（reflector 内部已 to_thread） |
| 可用性 | fail-open：verify 失败/任务丢失/DB 写失败均不影响主链路答案交付 |
| 安全级别 | 轮询端点仅返回 task_id 对应记录，不暴露其他数据；无需鉴权（与现有 /ai 端点一致） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/src/verify_tasks.py` | 新增 | 内存任务池 + verify_results 表读写（submit/get/后台执行） |
| `ai_service/src/database.py` | 修改 | `VERIFY_RESULTS_DDL` + `ensure_verify_results_table()` + `init_db()` 追加调用（幂等） |
| `ai_service/rag/models.py` | 修改 | `VerifyResult` ORM（对齐 DDL） |
| `ai_service/src/config.py` | 修改 | `verify_async_enabled`（读 `PW_VERIFY_ASYNC`，默认 true） |
| `ai_service/main.py` | 修改 | chat_stream 改造（done 带 verify_task_id）+ 新轮询端点 `GET /ai/rag/chat/verify/{task_id}` |
| `ai_service/tests/conftest.py` | 修改 | autouse fixture `default_verify_async_disabled` 钉住测试环境 false |
| `ai_service/tests/test_verify_tasks.py` | 新增 | 任务池 + 轮询端点 + chat_stream 开关行为测试 |
| `frontend/src/types/rag.ts` | 修改 | `ChatResponse.verifyTaskId` + `VerifyTaskResult` 类型 |
| `frontend/src/services/ragService.ts` | 修改 | `chatStream` 解析 task_id + `fetchVerifyResult` |
| `frontend/src/pages/ChatPage.tsx` | 修改 | 轮询补 verifiedClaims + verifying 状态 + 清理 |
| `frontend/src/components/ChatMessage.tsx` | 修改 | `verifying` prop + "正在验证…"提示 |
| `frontend/src/__tests__/ragService.test.ts` | 修改 | fetchVerifyResult / done 解析测试 |
| `frontend/src/__tests__/ChatPage.test.tsx` | 修改 | 轮询更新面板 + loading 时序 + 清理 |
| `frontend/src/__tests__/ChatMessage.test.tsx` | 修改 | verifying 态测试 |
| `specs/module-060-verify-async/{changelog,review-report,test-report}.md` | 新增 | Developer/Reviewer/Tester 产出 |
| `specs/adr/0013-verify-async.md` | 新增 | ADR：verify 异步化决策记录 |

### 3.2 数据库变更

```sql
-- 表名: verify_results
-- 说明: 证据链验证任务与结果（module-060 异步 verify 落库，done 结果持久化不因重启丢失）
CREATE TABLE IF NOT EXISTS verify_results (
    id                  BIGSERIAL   PRIMARY KEY,
    task_id             VARCHAR(64) NOT NULL UNIQUE,
    trace_id            VARCHAR(64) NOT NULL DEFAULT '',
    identity            VARCHAR(256) NOT NULL DEFAULT '',
    endpoint            VARCHAR(128) NOT NULL DEFAULT 'chat_stream',
    query               TEXT        NOT NULL DEFAULT '',
    status              VARCHAR(16) NOT NULL DEFAULT 'pending',
    claims              JSONB,
    overall_confidence  DOUBLE PRECISION,
    supported           INTEGER     NOT NULL DEFAULT 0,
    inferred            INTEGER     NOT NULL DEFAULT 0,
    unsupported         INTEGER     NOT NULL DEFAULT 0,
    error               TEXT,
    verified_in_ms      INTEGER,
    created_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE verify_results IS '证据链验证任务与结果（异步 verify 落库，pending→done/failed）';
COMMENT ON COLUMN verify_results.task_id IS '验证任务 ID（UUID hex，前端轮询 key）';
COMMENT ON COLUMN verify_results.trace_id IS '请求追踪 ID（关联 request_logs）';
COMMENT ON COLUMN verify_results.identity IS '请求身份（user_id 优先，client_ip 兜底，对齐 048 口径）';
COMMENT ON COLUMN verify_results.status IS '任务状态：pending（进行中）/ done（完成）/ failed（失败）';
COMMENT ON COLUMN verify_results.claims IS '验证结果（claims 数组 JSONB：claim/verdict/evidence）';
COMMENT ON COLUMN verify_results.verified_in_ms IS 'verify_answer 任务耗时（毫秒，口径对齐 module-058 计时）';
```

**不修改现有表**；建表走 `init_db` 自愈幂等 DDL（对齐 module-048/058 模式，`';'` 拆分逐条执行，不另起迁移脚本）。

### 3.3 API 接口定义

#### 接口 1：流式问答（改造，SSE done 事件变化）

```
请求方法: POST
请求路径: /ai/rag/chat/stream
开关 true 时 done 事件 data 变化:
  {"sources": [...], "verified": false, "verify_task_id": "<uuid>"}
  （不再同步发送 verified 事件；答案先交付，验证结果由轮询接口后取）
开关 false 时与现状一致（verified 事件 → done 事件带 verified: true）
```

#### 接口 2：验证结果轮询

```
请求方法: GET
请求路径: /ai/rag/chat/verify/{task_id}
路径参数:
  - task_id: string（必填，verify_task_id）

成功响应 (200):
  pending:  {"status": "pending"}
  done:     {"status": "done", "claims": [...], "overall_confidence": 0.82,
             "total_claims": 5, "supported": 4, "inferred": 1, "unsupported": 0,
             "verified_in_ms": 5200}
  failed:   {"status": "failed", "error": "..."}

错误响应:
  - 404: 任务不存在/已过期 → {"detail": "task not found"}
```

### 3.4 业务逻辑说明

#### 核心流程

```
1. chat_stream 端点流式生成结束（main.py:592-604 区域）
2. 开关 true：submit_verify_task(answer, docs, identity, query, trace_id)
   a. 生成 task_id → 插 verify_results 一条 pending 记录
   b. asyncio.create_task(_run_verify(...)) —— fire-and-forget，不 await（对齐 engine._schedule_persist 模式）
   c. 返回 task_id
3. 端点立即 yield done 事件（带 verify_task_id、verified:false）→ 连接关闭
   → 前端 loading 立即结束，答案已交付
4. 后台 _run_verify：await reflector.verify_answer(answer, docs)（内部 15/20/15s 超时）
   → 成功：UPDATE verify_results status=done + claims/confidence/counts/verified_in_ms
   → 异常：UPDATE status=failed + error
5. 前端轮询 GET /ai/rag/chat/verify/{task_id}（2s 间隔、60s 上限）
   → pending 继续；done 更新消息 verifiedClaims（ChatMessage 面板）；failed/404 停止 fail-open
```

#### 关键业务规则

| 序号 | 规则描述 | 实现位置 |
|------|----------|----------|
| 1 | 轮询端点**读 DB 为准**（不读内存任务池）——重启丢未完成任务、已 done 结果持久可查 | `get_verify_task` → verify_results 表 |
| 2 | verify 任务内部超时复用 `reflector.verify_answer` 既有 15/20/15s（不新增无限任务） | `_run_verify` |
| 3 | 开关 false 时 chat_stream 走现状同步路径（verified→done 顺序） | main.py chat_stream |
| 4 | 内存任务池只持执行期中间态（answer+docs+task 句柄），完成后释放；DB 结果不清理（飞轮数据源） | verify_tasks.py |
| 5 | 前端轮询生命周期：组件卸载/重试/切会话 → clearInterval | ChatPage |

### 3.5 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| verify 后台任务异常/超时 | `_run_verify` 捕获 → UPDATE status=failed → 轮询返回 failed → 前端停止轮询不报错（fail-open） |
| 任务不存在/重启丢失 | 轮询 404 → 前端停止轮询（fail-open，与现状空 claims 不显示一致） |
| verify_results 写库失败 | 任务内 try/except + 日志告警，不影响主链路答案交付（fail-open） |
| 开关 false | chat_stream 同步路径，行为与现状逐字一致 |

---

## 4. WP 拆解与通过标准

### WP1 后端 verify 后台任务基础设施

- `src/verify_tasks.py`（新）：`submit_verify_task` / `_run_verify` / `get_verify_task` / 内存池 TTL 释放
- `src/database.py`：`VERIFY_RESULTS_DDL` + `ensure_verify_results_table()` + `init_db()` 追加
- `rag/models.py`：`VerifyResult` ORM
- `src/config.py`：`verify_async_enabled`（`PW_VERIFY_ASYNC` 默认 true）
- **通过标准**：单测覆盖 submit 返回 task_id / DB pending→done（mock verify_answer）/ 异常→failed / get 查 DB / DDL 幂等 / 开关 false 行为；`init_db` 重复调用不报错

### WP2 chat_stream 端点改造 + 轮询端点

- main.py chat_stream：开关 true 提交任务 + done 带 `verify_task_id` + 不 yield verified 事件；开关 false 现状
- 新端点 `GET /ai/rag/chat/verify/{task_id}`：pending / done / failed / 404
- **通过标准**：端点测试——开关 true done 事件含 task_id 无 verified 事件；开关 false verified→done 顺序；轮询端点状态机（mock DB 或 fixture）；request_logs 零改动

### WP3 前端

- types/rag.ts / ragService.ts / ChatPage.tsx / ChatMessage.tsx
- **通过标准**：前端测试——done 解析 task_id / 轮询 done 更新面板 / pending 多轮 / failed/404 停止 / loading 立即结束 / 卸载清理 / verifying 态显示

### WP4 测试 + 文档 + 记忆

- conftest autouse 钉住 `verify_async_enabled=False`；新增测试显式开 true
- 真实 E2E 冒烟（uvicorn 8001）：done 先于 verify、轮询 pending→done、DB verify_results done 记录
- 文档：changelog / review-report / test-report / **ADR-0013-verify-async.md** / memory 三件套 / CONTEXT 只增 / 面试口径
- **通过标准**：全量 pytest 780+新增全绿 + 前端测试全绿；记忆三文件硬性约束满足

---

## 5. 验收概述

> 详细验收标准见同目录 `acceptance-criteria.md`。

核心验收项：
1. 流式对话答案先交付、loading 立即结束（不等 verify）
2. 轮询补 verifiedClaims → ChatMessage 可信度面板正常显示
3. verify 失败/重启 → fail-open（不显示面板、不报错）
4. `PW_VERIFY_ASYNC=false` → 行为与现状逐字一致
5. 已完成 verify 结果 DB 持久化（重启可查）
6. 非流式 / agent / agent-lg / request_logs 零改动

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 服务重启丢未完成任务 | 轮询 404 → 前端不显示验证面板 | 低（本地单机） | fail-open + 已 done 结果 DB 不丢；如实记录边界 |
| verify 计时口径变化 | request_logs 无 verify 阶段（module-058 有该字段预期） | 必然 | changelog 如实声明；耗时由轮询 `verified_in_ms` 返回 |
| 轮询空转 | 前端 2s/次 × 60s 最多 30 次轻量查询 | 低 | 60s 上限硬停；DB 单行主键查询成本可忽略 |
| DB 写失败（pending 插入/更新） | verify 结果拿不到 | 低 | fail-open：任务内捕获，日志告警，主链路不受影响 |
| 存量测试漂移 | 默认 true 影响 chat_stream 存量测试 | 高 | conftest autouse 钉住 false（对齐 module-056/058 成熟模式） |

### 6.2 技术注意事项

- [ ] `asyncio.create_task` 只调度不 await；任务引用需避免被 GC（提交处持有或模块级存储）
- [ ] 内存池 dict 并发：asyncio 单线程无锁即可；跨线程（to_thread 内部）不触碰内存池
- [ ] 前端轮询 timer 必须清理（卸载/重试/切会话），避免泄漏与竞态
- [ ] done 事件 `verified:false` 与旧前端字段兼容（旧前端读到 done 无 task_id 则无验证，fail-open）

### 6.3 开发建议

- 优先实现 WP1+WP2（后端闭环），再 WP3 前端，最后 WP4 测试文档
- `task_id` 复用 `observability.make_trace_id()`（uuid hex），语义一致
- 前端 `fetchVerifyResult` 用 fetch 而非 aiHttp（chatStream 同款），404 需手动处理
- 测试用 fixture/mock DB（对齐现有 conftest 模式），不依赖真实 PG 跑全量

---

## 7. 依赖关系

### 7.1 上游依赖（已完成）

| 依赖模块 | 依赖内容 |
|----------|----------|
| module-048 | feedback 表建表模式（幂等 DDL 对齐） |
| module-051/055 | verify_answer 链路与超时（15/20/15s）、降级链 |
| module-058 | observability（trace_id/timing）、request_logs 表模式、conftest 开关钉住模式 |

### 7.2 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| PostgreSQL | verify_results 落库 | 可用性同现有（落库失败 fail-open） |
| HHEM/LLM | verify_answer 后台执行 | 复用既有降级链 |

---

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-13 | 初始版本（用户决策：轮询 + 非流式保持同步 + 落库） | Planner |
