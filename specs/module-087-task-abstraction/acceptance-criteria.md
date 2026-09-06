# 验收标准 — Module-087: 任务抽象（task 表 + 一次请求 = 1 task + "子只读父写"所有权）

> 依据：`plan.md` v1（2026-09-06）| 验收口径：全量 **1638 passed / 0 failed / 3 skipped** 基线，**新增 0 失败、存量测试零改动** 红线
> roadmap 验收方向：**观测聚合 / 预算 / checkpoint 均挂在 task 上**（+ 关键设计约束"子只读父写"落地）
> 命令均在 `ai_service/` 目录执行，解释器 `.venv/Scripts/python.exe`

## 1. 功能验收

### 1.1 tasks 表与写侧原语（WP-A database.py / WP-B src/tasks.py）
- [ ] AC-1 `TASKS_DDL` 存在且与 plan §2 WP-A 草案**逐字一致**（14 列：id/task_id UNIQUE/parent_task_id/trace_id/endpoint/intent/status/budget_token_limit/tokens_used/memory_write/checkpoint/identity/created_at/finished_at）+ `CREATE INDEX IF NOT EXISTS idx_tasks_trace`；`ensure_tasks_table()` 按 `DDL.split(";")` 拆分执行（对齐 request_spans 模式）；`init_db` 尾部挂接
- [ ] AC-2 **建表幂等**：`ensure_tasks_table()` 二次执行不报错（Tester 真实 PG 验证；单测断言 SQL 文本含 `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`）
- [ ] AC-3 **红线（git diff 核验全空）**：`REQUEST_LOGS_DDL` / `TOOL_CALL_LOGS_DDL` / `REQUEST_SPANS_DDL` 三段 DDL 一字不改；`src/observability.py` / `src/verify_tasks.py` / `rag/router.py` / `agent/tool_registry.py` / `mcp_server.py` / `rag/engine.py` / `agent/react.py` / `agent/langgraph_react.py` / `requirements.txt` / `frontend/` / `backend/` 零 diff
- [ ] AC-4 `tasks_enabled=False` → `begin_task` 零落库（`_spawn` 不被调用）但仍 set `_task_id_var`（对齐 begin_request 先例），返回值恒 32 位小写 hex
- [ ] AC-5 `begin_task` 开关开：INSERT 捕获 11 绑定列全字段——task_id 32hex / parent_task_id="" / trace_id 透传 / endpoint 透传 / intent="" / status="running" / budget_token_limit=0 / tokens_used=0 / memory_write="write" / checkpoint={} / identity 透传；created_at 走 DB default（INSERT 不含该列）
- [ ] AC-6 fail-open 双保险：`_run_sql` session 抛异常 → `logger.warning("tasks 落库失败（fail-open...）")` **不上抛**；`_spawn` 无运行 loop → RuntimeError 窄捕获静默放弃；`_pending_tasks` 引用池 + `add_done_callback(discard)` 存在
- [ ] AC-7 `finish_task`：error=True → status="failed"，False → "completed"；tokens_used 汇总 = usage 各供应商 prompt+completion 之和；`_SQL_FINISH` 含 `WHERE task_id = :task_id AND status = 'running'`（幂等）+ intent CASE 空串不覆盖；finished_at 为 Python 侧 `datetime.utcnow()` 传入
- [ ] AC-8 `finish_task` 空 task_id / 开关关 → 首行 return 零落库零报错
- [ ] AC-9 **SQL 卫生**：`_SQL_INSERT` / `_SQL_FINISH` / `_SQL_OVERVIEW` 全参数化（grep 无 f-string/`%`/`+` 拼 SQL）；`_SQL_OVERVIEW` 只读（词边界断言无 INSERT/UPDATE/DELETE）

### 1.2 中间件挂接与生命周期（WP-C main.py）
- [ ] AC-10 tasks_enabled + 对话四路径逐一（ASGITransport）→ `request.state.task_id` 为 32hex；INSERT 捕获 trace_id == state.trace_id、endpoint == 请求路径、identity == resolve_identity 结果；087 块位置在 088 块之后、call_next 之前（429 零 task 反向锁位置）
- [ ] AC-11 **覆盖面边界**：非白名单路径（如 /ai/memory/save、/ai/rag/search、/ai/health）零 task；429 短路请求零 task（同 088 边界）
- [ ] AC-12 `tasks_enabled=False` → 全链路零 task 零收口，058/088 行为逐字不变（存量 test_observability / test_tracing 全过佐证）
- [ ] AC-13 **trace 缺失边界**：request_logs_enabled=false + trace_spans_enabled=false（state.trace_id 不存在）→ 零 task（聚合锚缺失跳过，plan §1 决策 7）
- [ ] AC-14 persist 收口钩子：`persist_request_log` 调用 `finish_task` 且 intent/error 透传、tokens_used 口径正确；`request_logs_enabled=False` 时 finish 仍执行（独立开关）；state 无 task_id（未建 task 的请求）→ no-op
- [ ] AC-15 **一次请求 = 1 task（集成）**：ASGITransport chat 最轻链 → 恰 1 条 INSERT + 1 条 UPDATE，task_id/trace_id 两侧同值；trace_id 与 request_spans 根 span 同值（088 兼容）
- [ ] AC-16 **零改动实证**：persist_request_log 既有 record 构造/save 分支语义不变（stats 上移 + gate 前追加旁路为仅有的两处变化）；test_observability 全部存量断言零改动通过

### 1.3 读侧端点（WP-B/WP-C GET /ai/observability/task/{task_id}）
- [ ] AC-17 200 契约形状（plan §7 字段名逐字）：`{code:0, msg:"success", data:{task_id, parent_task_id, trace_id, endpoint, intent, status, budget_token_limit, tokens_used, memory_write, checkpoint, identity, created_at, finished_at, obs:{request_logs, request_spans, tool_calls}}}`
- [ ] AC-18 task 不存在 → `{"code":1,"msg":"task 不存在"}`；DB 异常 → `{"code":1,"msg":"task 查询失败（fail-open）"}` 不 500（对齐 088 trace 端点）
- [ ] AC-19 `get_task_overview` 单 SQL 标量子查询聚合三表（`COUNT(*) ... WHERE trace_id = t.trace_id`）；三计数键组装进 `obs` 子 dict；无行返回 None
- [ ] AC-20 obs 三计数与三表真实 COUNT 一致（Tester 真实 PG 对账 T2 实证）

### 1.4 "子只读父写"所有权闸（WP-D rag/memory/memory.py / WP-B 原语）
- [ ] AC-21 原语：`memory_write_allowed()` 默认 True；`set_memory_write_mode("read")` → False；回置 "write" → True；非法值（如 "child"/""）→ no-op 保持原值
- [ ] AC-22 `MemoryService.save` 默认放行：正常路径 `_save` 被调、返回 `{"status":"saved"}` / `{"status":"updated"}` 语义逐字不变（存量 tests/memory/ 全过佐证）
- [ ] AC-23 read 模式 → save 不调 `_save`、返回 `{"status": "blocked"}`、logger.warning 含"子只读父写"字样、**不上抛**（fail-open）
- [ ] AC-24 **闸面边界**：read 模式下 `save_short` 与 session_memory 写入不受影响（闸只设 save 入口，不设 `_save`——plan §0.3）；save 的 3 处生产调用面（engine._persist_memory ×2 + /ai/memory/save）无需改动即被闸覆盖

### 1.5 开关与配置（WP-E config.py / conftest.py）
- [ ] AC-25 `tasks_enabled: bool = True` 字段存在；env 回退名 **PW_TASKS_ENABLED**（文档/plan/AC 全程唯一口径——088 发现-1 教训，严禁写 PW_TASKS）
- [ ] AC-26 conftest 新增 `default_tasks_disabled` autouse fixture（钉 false）；存量 fixture 零改动（git diff tests/ 仅 conftest 纯新增）

## 2. 边界条件验收
- [ ] AC-27 **既有数据零迁移**：tasks 表只含本模块新增行；088 之前/之后的 request_logs/tool_call_logs/request_spans 行不回填不改动，经 trace_id 与 task join 均可查（T3 对账）
- [ ] AC-28 `checkpoint` 列 v1 零读写：INSERT 不含该列（default '{}'）、finish UPDATE 不触碰、overview 原样透传
- [ ] AC-29 `budget_token_limit` v1 零执法：0=不限，生产代码无任何预算判断逻辑（089 接管）
- [ ] AC-30 `parent_task_id` v1 恒 ""（无生产写入方，T5 消费）
- [ ] AC-31 中间件极端异常（call_next 自身抛出且端点 finally 未达）task 悬挂 running——v1 接受并声明（文档/changelog 如实记录，单测不覆盖）

## 3. 异常场景验收
- [ ] AC-32 DB 不可用：begin/finish fail-open（logger.warning 不上抛），请求主链路响应零影响
- [ ] AC-33 端点异常路径收口：chat_stream 流生成器 finally 的 persist（error=failed）→ status="failed"；既有 try/except/finally 语义零改动
- [ ] AC-34 /ai/memory/save 在闸拒绝时返回 code 1 + message 含"子只读父写"（拒绝必须可见，fail-closed 对齐 083 审批闸——编排者裁定 2026-09-06 取代 plan §8 待澄清 3 的 code 0 缺省；修复轮 v2 勘误，正常路径仍 code 0 透传）

## 4. 非功能验收
### 4.1 向后兼容零回归
- [ ] AC-35 全量回归：`python -m pytest -q` = **1638 基线 + ~28 新增全绿 / 0 failed / 3 skipped**（预期 ≈1666，新增 0 失败）
- [ ] AC-36 行数：生产代码 AST 合计 **~97 ≤ 200**（plan §3 对照表）；新增函数全部 ≤50 行
- [ ] AC-37 代码质量：tasks.py / get_task_overview / begin_task / finish_task / set_memory_write_mode / memory_write_allowed public docstring（Args/Returns/Raises）齐全；0 print；0 裸 except（`except Exception as e` + warning fail-open / `except RuntimeError` 窄捕获）

### 4.2 红线总核验
- [ ] AC-38 `git diff --stat` 实证（AC-3 清单全空 + tests/ 仅 conftest 新增 fixture + 改动面仅 database.py / src/tasks.py / main.py / rag/memory/memory.py / src/config.py / tests/api/test_tasks.py / tests/conftest.py）

## 5. Tester 真实对账方案（"数据与落库一致"实质，hermetic 单测的分层补充）

> uvicorn 8010 真实起服（.env 真实凭据，tasks_enabled 默认 true）+ 一次性 asyncpg/psql 只读 SQL；示例 header 用纯 hex `087a0123456789abcdef0123456789abcd`（白名单 [0-9a-f-] 内）；对账脚本用后即删、探针数据清理（module-085/088 先例）。

- **T1 task 生命周期真实落库**：`curl -s -X POST http://127.0.0.1:8010/ai/rag/chat -H "X-Trace-Id: 087a0123456789abcdef0123456789abcd" -H "Content-Type: application/json" -d '{"query":"什么是RAG","session_id":"t087"}'` → SQL `SELECT task_id, trace_id, endpoint, intent, status, tokens_used, finished_at FROM tasks ORDER BY id DESC LIMIT 1` → **恰 1 新行**：trace_id==header 逐字、endpoint=/ai/rag/chat、intent=knowledge、status=completed、tokens_used>0、finished_at 非空
- **T2 聚合一致性（观测聚合挂 task 实证）**：`curl -s http://127.0.0.1:8010/ai/observability/task/{task_id}` → code 0；data.obs 三计数 == 三条独立 SQL 逐值相等：`SELECT COUNT(*) FROM request_logs WHERE trace_id='...'` / `SELECT COUNT(*) FROM request_spans WHERE trace_id='...'` / `SELECT COUNT(*) FROM tool_call_logs WHERE trace_id='...'`；且 `GET /ai/observability/trace/{trace_id}`（088 端点）同 trace_id 树存在（兼容互证）
- **T3 三表零迁移对账**：上线前后 snapshot——request_logs/tool_call_logs/request_spans 全表行数差 == tasks 新增行数（1:1）；三表任取 1 条**上线前旧行**内容可回读且未被改动（SELECT MIN(id) 行比对）
- **T4 缺失 header 兜底**：不带 X-Trace-Id 再发一次 chat → tasks 新行 trace_id 为 32 位小写 hex 且 == 该请求 request_logs.trace_id（JOIN 验证）
- **T5 开关关**：.env 写 `PW_TASKS_ENABLED=false` 重启 → 再发 chat → tasks 行数零增长（COUNT 前后相等）；恢复 true 还原（**变量名逐字，勿写 PW_TASKS**）
- **T6 重启幂等**：连续 3 次重启（init_db ×3）不崩、tasks 表结构不重复创建、数据不丢（088 T8 同口径）
- **T7 流式收口**：`curl -N -X POST .../chat/stream -d '{"query":"..."}'` 流结束后 → 该请求 task status=completed 且 intent 非空（finally 收口实证）；（可选）`curl --max-time 3` 中途断连 → task 仍收口（finally 语义）
- **T8 记忆闸边界**：真实环境无置 read 通道（v1 无生产调用方，plan §1 决策 6）——AC-21~24 hermetic 单测覆盖即验收，真实对账不做（如实记录）

## 6. 可运行验证命令表

```bash
# 定向新增（Developer/Reviewer/Tester）
cd ai_service && .venv/Scripts/python.exe -m pytest tests/api/test_tasks.py -q
# 预期：~28 passed

# 受影响存量定点（存量零改动实证）
.venv/Scripts/python.exe -m pytest tests/api/test_observability.py tests/api/test_dashboard.py tests/api/test_tracing.py tests/memory/ tests/agent/test_tool_call_logs.py -q
# 预期：全绿零失败（存量测试文件零改动）

# 语法
.venv/Scripts/python.exe -m py_compile src/database.py src/tasks.py main.py rag/memory/memory.py src/config.py tests/conftest.py
# 预期：exit 0 无输出

# AST 行数复核（Reviewer 口径）
.venv/Scripts/python.exe -c "import ast,sys; [print(f, sum(isinstance(n,ast.stmt) for n in ast.walk(ast.parse(open(f,encoding='utf-8').read())))) for f in ['src/database.py','src/tasks.py','main.py','rag/memory/memory.py','src/config.py']]"
# 预期：与 plan §3 对照表一致（diff 口径 ~97 ≤ 200）

# 红线核验
git diff --stat -- src/observability.py src/verify_tasks.py rag/router.py agent/tool_registry.py mcp_server.py rag/engine.py agent/react.py agent/langgraph_react.py requirements.txt backend/ frontend/
# 预期：输出为空（零 diff）

# 全量回归（Tester，基线 1638/0/3 零新增失败）
.venv/Scripts/python.exe -m pytest -q
# 预期：1638 + ~28 ≈ 1666 passed / 0 failed / 3 skipped

# 真实冒烟 + 对账（Tester，§5 T1~T8）
# uvicorn src.main:app --port 8010（或既有启动方式）+ §5 SQL 逐条
```
