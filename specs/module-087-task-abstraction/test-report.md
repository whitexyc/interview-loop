# 测试报告 — Module-087 任务抽象（task 表 + 一次请求 = 1 task + "子只读父写"所有权）

> Tester 验收 | 2026-09-06 | 验收依据：plan.md v1 + acceptance-criteria.md（AC-1~38，AC-34 已按编排者裁定 code 1 口径勘误）+ changelog.md v2 + review-report.md（§9 二轮 PASS；B1/B2 备忘非阻塞）
> 审查基线：全量 **1638 passed / 0 failed / 3 skipped**（module-088 闭环态）；本模块红线：**新增 0 失败、存量测试零改动**；预期全量 **1670 = 1638 + 32**
> 口径变更提醒（Reviewer 移交要点③）：/ai/memory/save 被所有权闸拒绝现返回 **code 1**（fail-closed 对齐 083），正常路径仍 code 0 透传——本报告 T7 按此口径实证

## 1. 验证命令执行结果（独立复跑，不采信声明）

| 验证 | 命令（在 ai_service） | 结果 | 判定 |
|------|----------------------|------|------|
| 定向新增 | `.venv/Scripts/python.exe -m pytest tests/api/test_tasks.py -q` | **32 passed**（17.25s，2 warnings） | ✅ |
| **全量回归** | `.venv/Scripts/python.exe -m pytest tests/ -q` | **1670 passed / 0 failed / 3 skipped**（121.19s，164 warnings） | ✅ = 1638 + 32 算术自洽 |
| 受影响存量 | `pytest tests/api/ tests/agent/ tests/core/ -q` | **830 passed / 3 skipped**（65.21s）= 798 基线 + 32 新增 | ✅ 零新增失败 |
| py_compile | 7 变更文件（database/tasks/main/memory/config/conftest/test_tasks） | exit 0 无输出 | ✅ |
| 红线核验 | `git diff --stat`（observability/verify_tasks/router/tool_registry/mcp_server/engine/react/langgraph/requirements/backend/frontend）+ `git status --short frontend backend` | **输出全空（零 diff）** | ✅ |
| AC-38 改动面 | `git status --short ai_service` | 恰 7 文件：database.py / tasks.py（新）/ main.py / memory.py / config.py / test_tasks.py（新）/ conftest.py | ✅ 与 AC-38 清单一致 |
| 存量零改动 diff 形态 | `git diff tests/ src/database.py` | conftest.py **+14 纯新增**（default_tasks_disabled fixture，既有 fixture 零触碰）；database.py **+54 纯新增 0 删行**（三表 DDL 一字未动） | ✅ |

## 2. 全量回归差异逐根因归类（预期 1670/0/3 vs 实测 1670/0/3）

- 实测 **1670 passed / 0 failed / 3 skipped** 与预期**逐字一致**：1638 基线 + 32 新增（test_tasks.py 30 项 + 修复轮端点级 2 项）。
- **新增失败：0 条**——无任何失败需要归类；3 skipped 与基线同源（real_redis 环境依赖项，Redis 6379 本轮可达但该 3 项为既定 skip 口径，088 闭环态即 3 skipped，非本模块引入）。
- 3 skipped 明细归属：存量 skip（与 1638 基线中 3 skipped 同一批次），module-087 零归属。

## 3. 真实 PG 对账（T1-T8）

### 3.0 前置快照与首启建表（AC-2 真实库实证）

- 启动前快照：tasks 表 **ABSENT**（Developer 未触真实 PG，表未建）+ request_logs 38 / tool_call_logs 467 / request_spans 19 + 三表 MIN(id)×2 行 MD5（request_logs=8567a770… / tool_call_logs=d8ea9c96… / request_spans=858f8579…）。
- uvicorn 8010 首次启动 init_db：tasks 表建出，**14 列逐字**（id/task_id/parent_task_id/trace_id/endpoint/intent/status/budget_token_limit/tokens_used/memory_write/checkpoint/identity/created_at/finished_at）+ idx_tasks_trace 索引在位（pg_indexes=1）；三表 MD5 与行数零变化。

### 3.1 ⚠️ 发现-1（阻塞级，真实缺陷非环境性）：begin_task INSERT 真实库必败 → 真实环境零 task 行

- **现象**：T1 真实 chat 请求（X-Trace-Id: 087a0123456789abcdef0123456789abcd，/ai/rag/chat）——中间件 087 块正常执行（root span 落库 19→20、task_id 生成、INSERT 参数含正确 trace_id/endpoint/identity），但 tasks 表 **0 新行**；uvicorn 日志 `tasks 落库失败（fail-open，不影响主链路）: … asyncpg.exceptions.DataError: invalid input for query argument $10: {} ('dict' object has no attribute 'encode')`。
- **根因**：`src/tasks.py` `begin_task` 经 SQLAlchemy `text()` 直传 `"checkpoint": {}`（Python dict）绑定 JSONB 列——asyncpg 驱动要求 JSONB 参数为 **str**（内部调 `.encode()`），dict 必炸 DataError。**每次 begin_task INSERT 100% 失败**，被 fail-open warning 吞掉，主链路无感 → "一次请求 = 1 task" 在真实环境完全失效。
- **为何 hermetic 32 项全绿仍漏**：test_tasks.py 全部 mock `_spawn`（打桩捕获 Python 参数，dict 合法），不打真实驱动；observability.py（request_logs）走 ORM `session.add(RequestLog)`（JSONB 类型装饰器自动 dumps）故线上一直正常；tracing.py 虽同样 raw text() 但其 INSERT 无 JSONB 列。**Reviewer 二轮亦仅跑 hermetic（32/32 + 830/3），此缺陷只能由真实 PG 对账暴露——AC §5 分层防线设计目的达成。**
- **修复方向（Developer 采纳即可，1 行）**：`begin_task` 参数 `"checkpoint": {}` → `"checkpoint": "{}"`（JSON 字符串；与 DDL default '{}' 同值；本报告探针行以 `'{}'` 字符串插入成功即反证）。test_tasks.py 对 INSERT 参数的 `checkpoint={}` 断言同步改为 `"{}"`（系本模块自有新测试文件，不在"存量测试零改动"红线内）。
- **波及面**：真实环境下 AC-4/AC-5（INSERT）、AC-15（一次请求=1 task 集成）、AC §5 T1/T4/T7-task 侧全部不可达；tasks_enabled 开关、收口 UPDATE、读侧端点、所有权闸不受影响（见 T3-T8）。

### 3.2 T1 task 生命周期真实落库 — ❌（被发现-1 阻塞）

- 请求/中间件/参数三面正常（INSERT 参数逐字可见：task_id=df5c7a99…、trace_id==header 逐字、endpoint=/ai/rag/chat、identity=127.0.0.1），但 INSERT DataError → **0 task 行**；intent/status/tokens_used/finished_at 回写（T2）因无行同样不可达。修复后需重跑。

### 3.3 T3 finish_task 幂等（真实代码路径）— ✅

- 合规探针行（checkpoint='{}' 字符串插入成功——反证修复方向）+ 从 venv 导入**生产 src/tasks.py** 真实调用 `finish_task`：
  - 首次收口：intent=knowledge / status=completed / tokens_used=42 / finished_at 非空（naive UTC，与 datetime.utcnow() 口径一致）；
  - 二次收口（换参 intent='agent' / tokens_used=999）：**行零变化**（WHERE status='running' 不匹配）+ 恒 1 行不产生第二行 → 幂等实证 IDEMPOTENT=True。

### 3.4 T4 GET /ai/observability/task/{task_id} 与库一致 — ✅

- 探针行（挂 2 request_logs + 3 request_spans + 1 tool_call_logs 探针观测行）→ 端点返回 `{code:0, msg:"success", data:{…13 列 + obs}}`，**plan §7 契约字段名逐字**；13 字段与库行逐值一致（checkpoint 读回 {} dict——JSONB 读写往返 OK）；obs={request_logs:2, request_spans:3, tool_calls:1}。
- task 不存在 → `{"code":1,"msg":"task 不存在"}` **HTTP 200**（不 500，AC-18 真实环境实证）。

### 3.5 T5 get_task_overview 三标量子查询与手工 SQL 一致 — ✅

- obs 三计数 {2,3,1} == 三条独立 `COUNT(*) … WHERE trace_id='087b…'` {2,3,1} **逐值相等**；同 trace_id 打 088 端点 GET /ai/observability/trace/{trace_id} → code 0 + span_count=3（兼容互证）。

### 3.6 T6 开关关（PW_TASKS_ENABLED=false，OS env 注入，.env 零改动）— ✅

- `PW_TASKS_ENABLED=false` 重启 8010 → 真实 chat 成功返回 RAG 答案 → **tasks 1→1 零增长**（唯一行系探针行，本次请求零建零收口零 fail-open 告警）；request_logs 40→41（endpoint=chat / intent=knowledge / error=false）+ request_spans 26→29（root + intent_routing + retrieval）——**058/088 存量行为逐字不变**实证。
- 探针侧注意：`PW_TASKS_ENABLED=`（空串）会使 pydantic bool 解析启动即崩——系探针操作失误非模块缺陷（bool 字段不接受空串，与 088 发现-1 同类 fail-fast 行为）。

### 3.7 T7 /ai/memory/save 口径（code 1 新口径实证）— ✅

- **默认 write 模式（真实 curl）**：POST /ai/memory/save → `{"code":0,"data":{"id":17444,…,"status":"saved"}}`——code 0 透传存量语义逐字不变（探针 documents 行已清理）。
- **read 模式拒绝（半实探针：真实 app + ASGITransport 全中间件链 + set_memory_write_mode("read") 同上下文 + _save 打桩）**：→ `{"code":1,"message":"记忆保存被拒绝（task 所有权：子只读父写）"}`——**code 1 编排者裁定口径实证**（fail-closed 对齐 083）、message 含"子只读父写"、HTTP 200 结构化拒绝不 500、**_save 零调用**（闸在写入口生效）、真实 warning 日志"长期记忆写入被拒绝（task 所有权：子只读父写，module-087）"落日志（AC-23）。
- **write 复位**：set_memory_write_mode("write") → code 0 恢复；**非法值 no-op**：set_memory_write_mode("child") → memory_write_allowed()=True（AC-21 五态实证补真实面）。
- 附带实证 AC-11 真实面：/ai/memory/save 非白名单路径，tasks_enabled=true 下零 task 行。
- AC §5 T8（记忆闸真实对账不做）：如约——v1 无生产置 read 通道，hermetic 32 项中 TestMemoryGate 3+2 项即验收；本报告 3.7 的半实探针系超出 AC 要求的补充实证。

### 3.8 T8 重启幂等（AC-2 真实库 + AC §5 T6）— ✅

- 首启 init_db 建 tasks 表（14 列 + idx_tasks_trace）后，追加 **3 轮独立 init_db 执行**（累计 4 次 ensure_tasks_table）：零报错零崩溃、information_schema 中 tasks 表恒 1 张、idx_tasks_trace 恒 1 个（无重复创建）、探针数据不丢（status=completed 保持）、三表 MIN 行 MD5 与行数零变化。

### 3.9 AC §5 原方案 T1/T4/T7 task 侧 — ❌ 被发现-1 阻塞（修复后须重跑）

- AC §5 T1（task 生命周期落库行逐字段）/ T4（缺失 header 自生成 trace_id 建 task + JOIN）/ T7（流式 finally 收口 status=completed + intent 非空）的 **task 侧断言全部因 INSERT 必败无法达成**——非测试不可为，乃被测功能不可达。流式/非流式的 persist 收口调用链本身（058 既有 finally 语义零改动 + 真实 finish_task 代码路径幂等）已由 3.3 探针独立验证成立。

## 4. 数据清理记录（如实申报）

| # | 残留 | 处置 |
|---|------|------|
| 1 | tasks 表探针行 ×1（probe087task…，id=1，系全表唯一行） | DELETE id=1 → tasks 表回到 0 行空表 |
| 2 | request_logs 探针行 ×2（trace 087b…）+ T6 探针 chat 行 ×1（trace 62d586d8…，id=41/42/43） | DELETE 3 行 → 回到基线 38 |
| 3 | request_spans 探针 span ×3（087b…）+ 本会话 curl/请求根 span ×8（400 请求 / 3 个观测端点 curl / T6 chat 3 span / memory curl，id=30,32-41） | DELETE 11 行 → 回到基线 19 |
| 4 | tool_call_logs 探针行 ×1（087b…，id=468） | DELETE 1 行 → 回到基线 467 |
| 5 | documents 记忆探针行 ×2（真实 /ai/memory/save 写入 id=17444 父 + 17445 子，content 含 m087-tester-probe 标记） | DELETE 2 行 |
| 6 | uvicorn 8010（三次启停） | TaskStop 杀净，netstat 无 LISTENING |
| 7 | 一次性对账脚本（%TEMP%\m087_tester\：pg.py / insert_obs.py / t5_counts.py / t7_readmode.py / cleanup*.py / do_cleanup.py + json 探针体） | 用后即删（目录已不存在） |
| 8 | .env | **零改动**（开关关闭经 OS env 注入，未编辑文件，无需备份还原） |
| 9 | ASGI 半实探针的 fire-and-forget span | 未落库（脚本事件循环即关，_spawn 任务被弃）——fire-and-forget 丢弃语义顺带实证，零残留 |

终态核验：tasks=0 / request_logs=38 / tool_call_logs=467 / request_spans=19，三表 MIN(id)×2 行 MD5 与启动前基线**逐字节一致**（8567a770… / d8ea9c96… / 858f8579…）——库态完全还原。

## 5. Tester 新发现（Reviewer 未覆盖）

### 发现-1（阻塞）：begin_task INSERT 真实库必败——checkpoint dict 直传 asyncpg JSONB（详见 §3.1）

- 级别：**阻塞（真实缺陷，非环境性）**。真实环境一次请求 = 1 task 完全失效（tasks 表恒空），AC-5/AC-15 实质不成立；task 概览端点对真实请求恒返回"task 不存在"；089 预算账本 / 090 checkpoint 若在现状上开发将建立在死底座上。
- 修复面（1 行 + 自有测试断言同步）：`src/tasks.py` begin_task 参数 `"checkpoint": {}` → `"checkpoint": "{}"`（与 DDL default '{}' 同值，无语义变化）；test_tasks.py 中 INSERT 参数含 `checkpoint={}` 的断言（TestPrimitives）同步改 `"{}"`——该文件系本模块自有新测试，不在"存量测试零改动"红线内。
- 修复后最小重验面（建议）：定向 32/32 + T1/T2 真实 chat 落库对账 + 流式 task 侧收口 + 全量回归。
- 为何三轮（Developer/Reviewer/hermetic）均漏：test_tasks.py 全量 mock `_spawn`（打桩捕获 Python 参数），asyncpg 驱动层序列化从未被执行——AC §5"真实对账"分层防线的设计目的正中此靶。

### 发现-2（备忘，非阻塞，非本模块缺陷）：`PW_TASKS_ENABLED=`（空串）启动即崩

- pydantic-settings bool 字段不接受空串：`.env` 写 `PW_TASKS_ENABLED=`（等号后空）→ Settings 实例化 ValidationError 崩溃；OS env 同理。系 pydantic 标准行为（088 发现-1 同类 fail-fast 面），与 087 代码无关；运维写开关时需写完整字面量 true/false。无需代码改动，仅备忘提示。

## 6. Reviewer 遗留备忘核验（B1 / B2，逐项）

| # | 备忘 | Tester 核验 | 维持 |
|---|------|------------|------|
| B1 | 同请求内 resolve_identity 二次调用（088 块 + 087 块各一次，main.py:265/:276） | 代码通读确认两处独立调用（每次含 JWT 解析）；系 plan WP-C 草案逐字，真实请求 identity 参数正确（T1 日志 127.0.0.1） | ✅ 维持非阻塞备忘 |
| B2 | tasks_enabled=false 时 persist 侧仍执行 get_request_stats() + tokens 求和（main.py:339-347） | 代码通读确认：stats 上移在 gate 之前；logs on 时 stats 本就必算（零额外成本），仅 tasks+logs 双关时多一次空快照；T6 真实环境（tasks off）chat 收口正常、request_logs 逐字落库 | ✅ 维持非阻塞备忘 |

## 7. 验收标准核对（AC-1 ~ AC-38 逐项签署）

签署口径：✅ 通过 / ⚠️ 有条件通过（附条件）/ ❌ 不通过（附根因）。

### 7.1 tasks 表与写侧原语（AC-1~9）

| AC | 判定 | 依据（Tester 独立证据） |
|----|------|------------------------|
| AC-1 DDL 逐字 + ensure + init_db 挂接 | ✅ | 真实 PG information_schema：**14 列逐字**（id/task_id/parent_task_id/trace_id/endpoint/intent/status/budget_token_limit/tokens_used/memory_write/checkpoint/identity/created_at/finished_at）+ idx_tasks_trace（pg_indexes=1）；代码通读 database.py:201-250（DDL.split(";") 拆分）；TestDDL 单测锁定 |
| AC-2 建表幂等 | ✅ | **真实库 4 次执行**（首启 + 3 轮 init_db）：零报错、表恒 1 张、索引恒 1 个、数据不丢（T8） |
| AC-3 红线零 diff | ✅ | git diff 全空（observability/verify_tasks/router/tool_registry/mcp_server/engine/react/langgraph/requirements/backend/frontend）；database.py **+54 纯新增 0 删行**（三表 DDL 一字未动的 diff 形态实证） |
| AC-4 开关关零落库仍 set var | ✅ | 代码通读 tasks.py:121-124（首行短路前 set var）+ 单测 + T6 真实环境 tasks 零增长 |
| AC-5 INSERT 11 绑定列 | ✅（复验轮 2 后） | 一轮 ❌（checkpoint dict 直传 asyncpg JSONB 必败，§3.1）；修复轮 2 改绑 `"{}"` JSON 字符串后 **T1 真实落库实证**：task 行 11 列全字段逐值正确（trace_id==header 逐字 / intent=knowledge / status=completed / tokens_used=8802==usage qwen 4161+4641 逐值精确 / finished_at 非空）——详见 §10 |
| AC-6 fail-open 双保险 + 引用池 | ✅ | 代码通读（tasks.py:84 RuntimeError 窄捕获 / :103 Exception+warning / :77,86-87 引用池+discard）；**真实环境反向实证**：发现-1 的 DataError 被 fail-open 吞掉仅 warning，主链路响应零影响 |
| AC-7 finish 幂等 + CASE + Python 侧 finished_at | ✅ | **真实代码路径**（生产 src/tasks.py finish_task 直调真实库）：status=completed、intent CASE 生效、二次收口换参零变化恒 1 行、finished_at naive UTC |
| AC-8 空 task_id / 开关关首行 return | ✅ | 代码通读 tasks.py:151 + 双分支专测 |
| AC-9 SQL 卫生 | ✅ | 三 SQL 全 :xxx 绑定通读确认、无 f-string/%/+ 拼接；_SQL_OVERVIEW 纯 SELECT |

### 7.2 中间件挂接与生命周期（AC-10~16）

| AC | 判定 | 依据 |
|----|------|------|
| AC-10 四端点接线 + 087 块位置 | ✅ | 代码通读 main.py:271-276（088 块后、call_next 前）+ 单测（429 反向位置锁）；真实 uvicorn 日志实证中间件执行且参数捕获正确——落库失败归 AC-5 |
| AC-11 非白名单 / 429 零 task | ✅ | 单测 + **真实环境**：tasks_enabled=true 下 /ai/memory/save 真实请求零 task 行（T7 附带实证） |
| AC-12 开关关全链路零 task 058 逐字 | ✅ | T6 真实环境：PW_TASKS_ENABLED=false chat → tasks 零增长 + request_logs/spans 照常落库 + 存量 test_observability 全绿 |
| AC-13 trace 缺失跳过 | ✅ | 代码通读 main.py:272-273（getattr 默认空 → 内层 if 跳过）+ 单测 |
| AC-14 persist 收口钩子 + 独立开关 + no-op | ✅ | 代码通读 main.py:339-347（stats 上移 + finish_task 调用）+ 真实 finish 代码路径（T3）+ 单测三分支 |
| AC-15 一次请求 = 1 task 集成 | ✅（复验轮 2 后） | 一轮 ❌（真实环境 0 task 行，发现-1）；修复轮 2 后 **T1/T3 真实实证**：chat 与 chat/stream 两次请求 → tasks 表恰 2 行（一次请求=1 task）+ 每行 trace_id 与 request_logs/request_spans 同值关联——详见 §10 |
| AC-16 persist 既有语义不变 | ✅ | git diff 仅 stats 上移 + finish 追加两处；record 构造逐字未动；存量 test_observability 全绿 + T6 真实 request_logs 行（endpoint=chat/intent=knowledge/error=false）逐字落库 |

### 7.3 读侧端点（AC-17~20）

| AC | 判定 | 依据 |
|----|------|------|
| AC-17 200 契约形状逐字 | ✅ | 真实端点响应字段集与 plan §7 逐字（13 列 + obs{request_logs,request_spans,tool_calls}），checkpoint 读回 {} dict（JSONB 往返） |
| AC-18 不存在 code 1 / 异常不 500 | ✅ | **真实端点**：不存在 → {"code":1,"msg":"task 不存在"} HTTP 200 |
| AC-19 单 SQL 标量子查询 + obs 组装 + 无行 None | ✅ | 代码通读 tasks.py:60-72/:191-214 + 单测 + 真实 T4 |
| AC-20 obs 三计数 == 真实 COUNT | ✅ | **T5 真实对账**：obs {2,3,1} == 三条独立 COUNT {2,3,1} 逐值相等 + 088 trace 端点互证 |

### 7.4 "子只读父写"所有权闸（AC-21~24）

| AC | 判定 | 依据 |
|----|------|------|
| AC-21 原语五态 | ✅ | 单测 + 真实探针（read→False / write→True / "child" no-op 保持放行） |
| AC-22 save 默认放行语义逐字 | ✅ | **真实 curl** code 0 + data.status=saved + 存量 tests/memory 全绿 |
| AC-23 read 拒绝 + warning + 不上抛 | ✅ | 半实探针（真实 app 全中间件链）：_save 零调用 + 结构化 blocked + 真实 warning 日志"子只读父写"落日志 + 零异常 |
| AC-24 save_short/session 不受影响 | ✅ | 单测（闸只设 save 入口）+ 代码通读（_save 未动） |

### 7.5 开关与配置（AC-25~26）

| AC | 判定 | 依据 |
|----|------|------|
| AC-25 tasks_enabled + PW_TASKS_ENABLED 唯一口径 | ✅ | 代码通读 config.py:158-162（注释明示勿写 PW_TASKS）+ **T6 真实环境 OS env 生效实证** |
| AC-26 conftest autouse 钉关 + 存量零改动 | ✅ | git diff tests/ **仅 conftest +14 纯新增**（既有 fixture 零触碰） |

### 7.6 边界 / 异常 / 非功能（AC-27~38）

| AC | 判定 | 依据 |
|----|------|------|
| AC-27 既有数据零迁移 | ✅ | 三表 +54 纯新增 0 删行（tasks 表全新）；基线快照 38/467/19 → 终态同值 + MIN 行 MD5 逐字节一致（零回填零改动） |
| AC-28 checkpoint v1 零读写逻辑 | ✅（复验轮 2 后） | 一轮 ⚠️（INSERT 携带 dict 即发现-1 根因）；修复轮 2 后 INSERT 绑定 `"{}"` JSON 字符串（与 DDL default 同值，task 行 checkpoint 落库 `"{}"` + 端点读回 {} dict 往返正常）；FINISH 不触碰 + 生产零 checkpoint 逻辑维持 |
| AC-29 budget 零执法 | ✅ | 代码通读 + 真实探针行 budget_token_limit=0 + DDL 注释归属 089 |
| AC-30 parent_task_id 恒 "" | ✅ | 代码通读 + 真实探针行 parent_task_id="" |
| AC-31 悬挂 running v1 声明 | ✅ | changelog §六如实声明；真实观测补充：body 解析 400 类请求经中间件（088 建 span）但 INSERT 失败无行——现网无悬挂行实例，声明边界维持 |
| AC-32 DB 不可用 fail-open | ✅ | 代码通读 + 真实反证（DataError 被吞仅 warning，chat 主链路照常） |
| AC-33 流式 finally 收口 error=failed | ✅（复验轮 2 后） | 一轮 ⚠️（task 侧终态被 发现-1 阻塞）；复验 **chat/stream 真实请求**：流结束 finally 收口 → task status=completed + intent=knowledge 非空（error=false 正常路径；error=true 的 failed 映射已由真实 finish_task 代码路径 + 单测覆盖）——详见 §10 |
| AC-34 save 拒绝 code 1（新口径） | ✅ | **T7 半实探针**：read 模式 → {"code":1,"message":"记忆保存被拒绝（task 所有权：子只读父写）"} + _save 零调用；正常路径 code 0 透传逐字不变（真实 curl）——编排者裁定口径实证 |
| AC-35 全量回归 1670/0/3 | ✅ | **1670 passed / 0 failed / 3 skipped**（121.19s）= 1638 + 32 逐字自洽，新增 0 失败 |
| AC-36 行数 | ✅ | AST 独立复算 **94 ≤ 200**（database +10 / tasks 61 / main +18 / memory +4 / config +1，与 changelog §三 v2 逐字一致）；新增函数最长 get_task_overview 10 语句 ≤50 |
| AC-37 docstring / 0 print / 0 裸 except | ✅ | tasks.py public 函数 Args/Returns 分节通读确认（修复轮 LOW#3 后）；grep print 0 命中；except 仅 1×Exception+warning + 1×RuntimeError 窄捕获 |
| AC-38 红线总核验 | ✅ | git status 改动面恰 7 文件 + specs/memory 产物；红线清单全空；tests/ 仅 conftest 纯新增 |

**签署汇总（复验轮 2 终态）：✅ 38 / ⚠️ 0 / ❌ 0**（一轮终态实为 34✅/2⚠️/2❌——首轮汇总行笔误 33 系 34 之误，随复验一并更正；4 项更新均系修复轮 2 后真实对账实证）。

## 8. 已知边界 / 备注

- 本报告 T1-T8 编号沿用派发口径；与 AC §5 原方案 T1-T8 的映射已在 §3 各节标注（§3.2=AC§5 T1+T2 / §3.6=AC§5 T5 / §3.7=AC§5 T8+超出 / §3.8=AC§5 T6 / §3.9=AC§5 T1·T4·T7 task 侧；AC§5 T3 三表零迁移对账并入 §3.0 基线快照 + AC-27 签署依据）。
- 真实 chat 依赖外部 LLM（deepseek）+ 本地 bge-m3 + Redis，T1/T6 两次真实请求全部成功返回答案——LLM 侧无环境性失败，本报告零"环境性失败"归类项。
- py_compile 覆盖 7 文件含 tests/api/test_tasks.py（超出 AC §6 的 6 文件清单，从严执行）。
- 时区口径：finished_at/created_at 均为 naive UTC（datetime.utcnow() + DB CURRENT_TIMESTAMP），与全库既有口径一致（plan 钉死）。
- 存量 3 skipped 与 1638 基线同源（非本模块引入）；全量 164 warnings 与基线同源（pydantic deprecation 等，零新增类别）。

## 9. 验收结论

**✅ 通过（PASS，复验轮 2 后收口，2026-09-06 Tester）**

- **第一轮（2026-09-06 上午）**：❌ 不通过——命令表全过（1670/0/3）+ T3-T8 对账全过，唯一阻塞 发现-1：begin_task INSERT checkpoint dict 直传 asyncpg JSONB 必败（fail-open 吞掉）→ 真实环境零 task 行（AC-5/AC-15 ❌，AC §5 T1/T4/T7 task 侧不可达）；详见 §3.1/§5/§7 一轮记录（历史保留）。
- **修复轮 2（Developer）**：tasks.py 1 行 `checkpoint: {} → "{}"` + test_tasks.py 自有断言同步 + changelog §九 含可复用坑记录（raw text() 写 JSONB 必须传 JSON 字符串）——根因/修复/参照系（ORM vs text() 路径）如实入档。
- **复验（§10）**：五项最小复验全过——定向 32/32 + T1 真实落库（trace_id==header 逐字、tokens_used=8802==usage 逐值精确）+ T2 三表关联同值 + 流式 finally 收口 + 全量回归 **1670/0/3**（143.13s）；红线仍全空、tasks.py 61 AST 不变。
- **AC 终态：38/38 全过**（✅ 38 / ⚠️ 0 / ❌ 0）。
- 测试残留：本轮探针 10 行（tasks 2 / request_logs 2 / request_spans 6）全清，库态与基线逐值一致；8010 杀净；.env 零改动；对账脚本用后即删。
- **module-087 任务抽象标记完成（模块完成态 v0.87.0；全局迭代版本维持 v0.88.0——版本号以实际模块序，087 完成不覆盖 088 既有编号）。

## 10. 复验节（Developer 修复轮 2 后，2026-09-06）

> 修复面核实：src/tasks.py:131 `"checkpoint": "{}"`（行内注释固化原因）+ tests/api/test_tasks.py:244 断言 `== "{}"` 同步 + changelog §九（根因/修复/可复用坑记录）+ 变更记录 v3——独立通读确认，读侧零改动。

### 10.1 复验结果（五项全过）

| 项 | 结果 | 关键证据 |
|----|------|----------|
| 定向 test_tasks.py | **32 passed**（14.54s） | 断言同步后全绿 |
| **T1 task 真实落库**（chat + X-Trace-Id: 087c0123…abcd） | ✅ | tasks 表新增恰 1 行：task_id=69c28780…（32hex）/ trace_id==header 逐字 / endpoint=/ai/rag/chat / intent=knowledge / status=completed / budget=0 / parent="" / memory_write=write / checkpoint="{}" / identity=127.0.0.1 / finished_at 非空 |
| **T2 关联与口径** | ✅ | task.trace_id == request_logs.trace_id（1 行）== request_spans.trace_id（3 行 root+intent_routing+retrieval）同值 JOIN；tool_call_logs 0（chat 无工具，正确）；**tokens_used=8802 == request_logs.usage qwen(prompt 4161+completion 4641) 逐值精确**（收口汇总公式终证） |
| **流式 task 侧收口**（chat/stream + 087d0123…abcd） | ✅ | 流结束 finally 收口：tasks 恰新增 1 行（endpoint=/ai/rag/chat/stream）+ status=completed + intent=knowledge 非空；两次请求 → tasks 恰 2 行（一次请求=1 task 终证） |
| **全量回归** | **1670 passed / 0 failed / 3 skipped**（143.13s） | = 1638 + 32，新增 0 失败红线维持 |

### 10.2 复验补充观测（如实记录，非阻塞）

- **流式 task tokens_used=0 与 request_logs usage={} 同快照同口径**：stream 请求的 request_logs 行（endpoint=chat_stream，usage={}，timings 完整）与 task 行 tokens_used=0 一致——finish_task 忠实求和 stats.usage，二者同源同值；流式路径 usage 累积为 058 既有行为（module-085 Tester 真实 chat 亦有 usage={} 先例），**非本模块引入，不属于 module-087 范围**，如实留痕供后续模块参考。
- 修复轮 2 复核：红线 git diff 仍全空（含 verify_tasks.py）、改动面仍 7 文件、tasks.py AST 仍 61（字面量改动零语句增减）。

### 10.3 复验环境申报

- 本轮探针残留 10 行全清：tasks 2（087c…/087d… 两 trace）+ request_logs 2 + request_spans 6，按 trace_id 精确 DELETE；终态 tasks=0 / request_logs=38 / tool_call_logs=467 / request_spans=19 与基线逐值一致。
- uvicorn 8010 杀净（netstat 无 LISTENING）；.env 零改动（本轮未用开关切换，无需注入）；一次性脚本（%TEMP%\m087r2\）用后即删。
