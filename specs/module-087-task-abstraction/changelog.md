# 变更记录 — Module-087: 任务抽象（task 表 + 一次请求 = 1 task + "子只读父写"所有权）

> Developer: 2026-09-06 | 依据：`plan.md` v1（2026-09-06，WP-A~G）+ `acceptance-criteria.md`（AC-1~AC-38）
> 基线：module-088 闭环后全量 **1638 passed / 0 failed / 3 skipped**——本模块红线：**新增 0 失败、存量测试零改动（tests/ 仅 conftest 纯新增 fixture）**、observability.py / 三表既有 DDL / verify_tasks.py / router.py / tool_registry.py / mcp_server.py / engine.py / react.py / langgraph_react.py / requirements.txt / frontend / backend 零 diff
> 实施说明：单会话完成 WP-A~G；**未跑全量回归、未启动长驻服务、未改 .env、未触真实 PG**（全量回归与 T1~T8 真实对账归 Tester）
> 编排者裁定：/ai/memory/save 被所有权闸拒绝时返回 **code 1**（拒绝必须可见，fail-closed 对齐 083 审批闸）；tasks 清理策略 v1 = 不清理。**初版误按 plan §8 待澄清 3 的 code 0 缺省实现并误报"裁定已执行"，修复轮 v2 已按裁定更正（端点 blocked 分支 + 端点级测试 + AC-34 勘误，见 §八）**

---

## 一、实现总览（任务生命周期链路图）

```
对话请求（四端点白名单 _TASK_ENDPOINTS）POST /ai/rag/chat[/stream|/agent|/agent-lg]
  ↓
main.py rate_limit_middleware（单中间件内顺序）：
  ① 058 块（零 diff）：request_logs_enabled → make_trace_id + init_request + state.trace_id
  ② health 早期 return / 429 限流短路（零 task，同 088 边界）
  ③ 088 块（零改动）：trace_spans_enabled → X-Trace-Id sanitize/自生成 + begin_request 根 span
  ④ 087 新块（tasks_enabled + 路径 ∈ 白名单）：state.trace_id 存在（聚合锚在）→
       request.state.task_id = tasks.begin_task(trace_id, endpoint, identity)
       （INSERT status=running fire-and-forget fail-open；contextvar 快照传 downstream）
  ↓ 请求结束（收口单一汇聚点 persist_request_log，4 调用点全覆盖）
  ⑤ tasks.finish_task(state.task_id, intent, error, tokens_used=Σ usage 各供应商
       prompt+completion)——UPDATE WHERE status='running' 幂等；流式在流 finally
       → 终态与 request_logs 同快照同口径；独立于 request_logs_enabled
  ↓ 读侧
GET /ai/observability/task/{task_id}（{code,msg,data} fail-open，088 trace 端点同构）
  → tasks.get_task_overview：单 SQL（task 13 列 + 3 标量子查询计数经 trace_id
     与 request_logs/request_spans/tool_call_logs join——裁定 1：三表零 ALTER）
"子只读父写"三层（roadmap 关键设计约束）：
  tasks.memory_write 列（父=write 子=read）
  + src/tasks.py 原语（_memory_write_var ContextVar + set_memory_write_mode/
    memory_write_allowed，v1 无生产调用方置 read，调用方在 T5）
  + MemoryService.save 入口闸（read → warning + {"status":"blocked"} fail-open；
    /ai/memory/save 端点将 blocked 转 code 1 拒绝可见——编排者裁定，修复轮 v2）
```

## 二、WP 实现说明

### WP-A src/database.py（AC-1/2/3，+10 AST 行）
- `TASKS_DDL` 与 plan §2 WP-A 草案**逐字一致**（14 列含 task_id UNIQUE / budget_token_limit / memory_write / checkpoint JSONB DEFAULT '{}' + `CREATE INDEX IF NOT EXISTS idx_tasks_trace` + COMMENT ON TABLE + 12 条 COMMENT ON COLUMN = 15 条语句）；`ensure_tasks_table()` 照抄 request_spans 拆分执行模式（`DDL.split(";")`）；`init_db` 尾部挂接 2 行（ensure + "tasks 表已就绪（module-087 任务抽象）"日志）。REQUEST_LOGS_DDL / TOOL_CALL_LOGS_DDL / REQUEST_SPANS_DDL 三段一字未动（红线，git diff 核验空）。

### WP-B src/tasks.py 新模块（AC-4~9/19/21/28~30，**61 AST 行，新文件**）
- **写侧**：`_task_id_var`/`_memory_write_var` 两个 ContextVar（default ""/"write"）+ `_pending_tasks` 引用池（防 GC，088 minor-1 先例）+ `_spawn`（asyncio.create_task，无运行 loop RuntimeError 窄捕获静默放弃）+ `_run_sql`（raw `text(sql)` 参数化执行 + commit，**全异常 logger.warning("tasks 落库失败（fail-open，不影响主链路）")不上抛**）。
- `begin_task`：uuid4().hex → set var → 开关关 return（对齐 begin_request 先例）→ `_SQL_INSERT` spawn（11 绑定列：task_id/parent_task_id=""/trace_id/endpoint/intent=""/status="running"/budget_token_limit=0/tokens_used=0/memory_write="write"/checkpoint={}/identity；created_at 走 DB default、finished_at 由收口传入）。
- `finish_task`：空 task_id 或开关关首行 return → status = failed if error else completed → `_SQL_FINISH` spawn（`SET intent = CASE WHEN :intent <> '' THEN :intent ELSE intent END, status, tokens_used, finished_at WHERE task_id = :task_id AND status = 'running'`——幂等 + intent 空串不覆盖；checkpoint/budget 列不触碰；finished_at = Python 侧 `datetime.utcnow()`）。
- **所有权原语**：`set_memory_write_mode`（仅 read/write 接受，非法 no-op）+ `memory_write_allowed()`（`!= "read"`）。
- **读侧**：`get_task_overview`（单 SQL `_SQL_OVERVIEW`：task 13 列 + 3 个标量子查询 `(SELECT COUNT(*) FROM <表> x WHERE x.trace_id = t.trace_id)` 全参数化只读；无行 None；三计数键 pop 进 `obs` 子 dict；**异常原样上抛**由端点层统一 fail-open）。
- 三条 SQL 常量全 `:xxx` 绑定（无 f-string/`%`/`+` 拼接）；无 ORM 模型（tool_call_logs/request_spans 先例）。

### WP-C main.py（AC-10~18，+16 AST 行）
- 顶部 `from src import tasks` 1 行 + `_TASK_ENDPOINTS` frozenset（对话四端点，精确对齐 persist_request_log 既有调用面）。
- **中间件 087 块**：插在 088 块之后、`return await call_next(request)` 之前（plan 草案逐字落实）——trace_id 终值已定 + contextvar 快照传 downstream；429/health 零 task；trace 缺失（logs+spans 全关 → state.trace_id 不存在）跳过（聚合锚缺失，决策 7）。
- **persist_request_log 微调**（唯一既有函数行为面变化）：`stats = observability.get_request_stats()` 上移到 request_logs gate 之前（决策 9，收口需要 usage；logs off 多一次空 dict 快照 `_obs()` 惰性初始化安全）+ gate 前插入 `tasks.finish_task(...)`（tokens_used = Σ usage 各供应商 prompt+completion）。既有 record 构造/save 分支语义零改动（test_observability 16 项存量全绿锁定）。
- **新端点** `GET /ai/observability/task/{task_id}`（088 trace 端点同构）：try/except → code 1 "task 查询失败（fail-open）"不 500；None → code 1 "task 不存在"；成功 `{code:0, msg:"success", data}`（plan §7 契约字段名逐字）。

### WP-D rag/memory/memory.py（AC-22~24，+4 AST 行）
- `MemoryService.save` 首行（委托 `_save` 之前）插入 3 行：`if not tasks_memory_write_allowed():` → `logger.warning("长期记忆写入被拒绝（task 所有权：子只读父写，module-087）")` → `return {"status": "blocked"}`（fail-open 不上抛）+ import 1 行。**闸只设 save 入口**：save_short（layer="short"）/session_memory 不受影响（闸设 `_save` 会误伤短期层——plan §0.3）。
- **（修复轮 v2 补）main.py `/ai/memory/save` 端点 blocked → code 1 分支**（+2 AST 行）：`result.get("status") == "blocked"` → `{"code": 1, "message": "记忆保存被拒绝（task 所有权：子只读父写）"}`（沿用本端点既有 `{"code":1,"message":...}` 错误形状）——编排者裁定"拒绝必须可见"落地；engine 侧两调用面忽略 save 返回值不受影响。

### WP-E src/config.py + tests/conftest.py（AC-25/26，+1 AST 生产行）
- config.py：`tasks_enabled: bool = True`（trace_spans_enabled 之后 1 字段；注释明确 **PW_TASKS_ENABLED 唯一口径**——088 发现-1 教训）。
- conftest.py：新增 `default_tasks_disabled` autouse fixture（钉 false，docstring 对齐 default_trace_spans_disabled；注明新测试体内显式开启）——存量 fixture 零改动（git diff tests/ 仅此纯新增）。

### WP-F tests/api/test_tasks.py（**30 项**，hermetic，新文件）
- TestDDL 2（14 列+UNIQUE+索引+COMMENT / ensure 拆分 15 条执行）/ TestPrimitives 8（开关关零落库但 var set / INSERT 11 列全字段+created_at 不在参数 / failed·completed / _SQL_FINISH 幂等 WHERE+CASE 文本 / 空 task_id no-op / 开关关 finish no-op / finished_at Python 侧 / 所有权原语五态）/ TestMiddleware 5（chat 建 task 全字段+trace_id==state.trace_id / 非白名单 /ai/memory/save 零 task / 开关关零 task+058 逐字 / trace 缺失跳过 / 429 零 task 位置锁）/ TestFinishHook 3（参数透传+tokens 汇总=18+logs 路径照常 / logs off finish 仍执行 / state 无 task_id no-op）/ TestOverview 3（obs 组装+顶层键集 / 无行 None / 只读词边界+join 条件）/ TestTaskEndpoint 4（200 契约形状逐字 / obs 三键 / 不存在 code 1 / 异常 fail-open）/ TestMemoryGate 3（默认放行 / read 拒绝+warning+不上抛 / save_short+session 不受影响）/ TestOneRequestOneTask 1（恰 1 INSERT+1 UPDATE 同 task_id，INSERT trace_id == 根 span trace_id == request_logs trace_id 三面同值）/ TestSQLHygiene 1（三 SQL 无拼接）。
- 打桩：`_capture` mock `src.tasks._spawn` 同步捕获（对齐 test_tracing `_capture_spans`，不依赖真实 task 完成）；`_FakeSession/_FakeResult/_fake_factory` 对齐 test_dashboard/test_tracing；ASGITransport 端点/中间件用例对齐 test_observability；**直调 begin_task/finish_task/所有权原语包 asyncio.run**（088 LOW-3 教训：ContextVar 直调向 pytest 共享上下文泄漏）。

## 三、行数统计（铁律 2，AST 语句口径，module-087 归属 = 当前文件 vs git HEAD 差分）

| WP | 文件 | module-087 AST 行 | 说明 |
|----|------|------------------|------|
| WP-A | src/database.py（改） | **+10**（199→209） | DDL 常量 1 + ensure 函数 6 + init_db 挂接 2 |
| WP-B | src/tasks.py（新） | **61**（0→61） | vars 2 + SQL 3 + 引用池 1 + spawn/run 13 + begin 6 + finish 4 + 所有权 5 + overview 10 + import 9；docstring/注释不计 |
| WP-C | main.py（改） | **+18**（663→681） | import 1 + 白名单 1 + 中间件块 4 + persist finish 调用 1 + 端点 9（stats 上移为既有语句移位零净增）+ 修复轮 blocked 分支 2 |
| WP-D | rag/memory/memory.py（改） | **+4**（495→499） | 闸 3 + import 1 |
| WP-E | src/config.py（改） | **+1**（122→123） | tasks_enabled 字段；conftest fixture 不计（module-073 先例） |
| **合计** | | **94 ≤ 200 ✓**（初版 92 + 修复轮 2；plan 预估 ~97） | |

方法长度（AST 语句）：新增函数全部 ≤13（get_task_overview 10 / _run_sql 8 / begin_task 6 / finish_task 4 / _spawn 4 / set_memory_write_mode 3 / memory_write_allowed 2）≤ 50 ✓；main.py rate_limit_middleware 与 persist_request_log 既有长度 +1~4 语句旁路（persist 净 +1 语句）。测试 30 项不计入生产行数。public 函数（begin_task/finish_task/set_memory_write_mode/memory_write_allowed/get_task_overview）docstring 含 Args/Returns（Raises）齐全 ✓；0 print ✓；0 裸 except——1 处 `except Exception as e` + logger.warning fail-open（_run_sql）+ 1 处 `except RuntimeError` 窄捕获静默放弃（_spawn 无运行 loop，plan WP-B 钉死语义）。

## 四、测试结果（Developer 自测，2026-09-06）

| 验证 | 命令 | 结果 |
|------|------|------|
| 定向新增 | `cd ai_service && .venv/Scripts/python.exe -m pytest tests/api/test_tasks.py -q` | **30 passed**（14.33s） |
| 受影响存量定点 | `.venv/Scripts/python.exe -m pytest tests/api/test_observability.py tests/api/test_dashboard.py tests/api/test_tracing.py tests/memory/ tests/agent/test_tool_call_logs.py -q` | **383 passed**（49.07s，存量零改动实证） |
| 语法 | `.venv/Scripts/python.exe -m py_compile src/database.py src/tasks.py main.py rag/memory/memory.py src/config.py tests/conftest.py` | **COMPILE_OK（exit 0 无输出）** |
| AST 行数复核 | `python -c "import ast; ..."`（git HEAD 差分口径，§三 表） | **92 ≤ 200 ✓**（逐文件：database +10 / tasks 61 / main +16 / memory +4 / config +1） |
| 红线核验 | `git diff --stat -- ai_service/src/observability.py ai_service/src/verify_tasks.py ai_service/rag/router.py ai_service/agent/tool_registry.py ai_service/mcp_server.py ai_service/rag/engine.py ai_service/agent/react.py ai_service/agent/langgraph_react.py ai_service/requirements.txt backend/ frontend/` | **输出为空（零 diff）**；git status 改动面 = database.py / src/tasks.py（新）/ main.py / rag/memory/memory.py / src/config.py / tests/api/test_tasks.py（新）/ tests/conftest.py，与 AC-38 清单一致 |

（全量 pytest 回归未跑——按分工归 Tester；初版预期 1638 + 30 = 1668，修复轮后预期 **1638 + 32 = 1670 passed** / 0 failed / 3 skipped，见 §八。）

## 五、与 plan 的偏离及理由

1. **AC-28 与 AC-5/WP-B 文本冲突——checkpoint 是否在 INSERT 中（已按 plan 主文裁定，申报）**：AC-5 / plan §2 WP-B（"11 绑定列"）/ WP-F 测试清单三处一致要求 INSERT 含 `checkpoint={}`；AC-28 孤例写"INSERT 不含该列（default '{}'）"。实现按 plan 主文：`_SQL_INSERT` 11 绑定列含 `checkpoint={}`（与 DDL default '{}' 同值，无行为差异）。AC-28 的实质意图（v1 零读零写零逻辑）完整满足：finish UPDATE 不触碰、overview 仅原样透传、生产代码零 checkpoint 逻辑，单测双向锁定（test_enabled_insert_all_11_columns + test_finish_sql_idempotent_where_and_case 断言 FINISH 无 checkpoint 字样）。
2. **save 生产调用面实为 4 处（plan §0.3 记 3 处），闸天然全覆盖零额外改动**：除 engine.py:662（remember_content）/ engine.py:687（extract_facts）/ main.py:909（/ai/memory/save）外，`rag/crawl/feedback_scanner.py:87`（module-080 低分题→待学笔记）同样调用 `memory_service.save`。闸设在 save 入口，第 4 处无需改动即被覆盖（该文件零 diff）；engine._persist_memory 对返回值"忽略"的声明同样适用。
3. **测试打桩踩中 module-050 兼容机制（rag.memory 旧路径别名）**：`import rag.memory.session_memory as m` 因 `rag.memory` 被旧路径别名覆盖为普通模块（rag/__init__.py 兼容机制）而 ImportError——按环境实测坑 ③ 同款方案改经 `sys.modules["rag.memory.session_memory"]` 取模块对象打桩（对齐 reranker monkeypatch 先例）。
4. **测试数 30 项（plan 预估 ~28）**：为锁 AC-8 双分支（空 task_id + 开关关）、AC-29/30（budget/parent 零写入）拆出 2 项，均在 hermetic 口径内。
5. 其余按 plan 逐字执行：白名单/中间件块位置/persist 微调/端点契约/{code,msg,data}/PW_TASKS_ENABLED 口径/编排者四项裁定（090 关联留 090、tokens 不分桶、v1 不清理）。**勘误（修复轮 v2）**：初版将"save 被拒 code 0 透传"误报为编排者裁定——实际裁定为 **code 1（拒绝可见，fail-closed 对齐 083）**；初版实现走的是 plan §8 待澄清 3 的 code 0 旧缺省且申报口径失实，修复轮 v2 已更正（main.py blocked 分支 + TestMemoryGate 端点级测试 ×2 + AC-34 勘误，详见 §八）。

## 六、遗留与明确不做

- plan §6"明确不做"逐条继承：预算熔断/超预算执法/预算 config（module-089）、checkpoint 读写逻辑（module-090）、子 Agent 编排/parent_task_id 生产写入（T5）、request_spans 加 task span、三表 ALTER/回填、任务列表端点/前端、多 task 聚合报表/tokens 分桶、save_short/session_memory 闸、ORM、新依赖、tasks 清理、新 ADR。
- **Tester 待办**（AC §5 T1~T8 + §6 命令表）：全量回归对账（1638+32=1670 预期）+ 真实 PG 对账（T1 生命周期 / T2 聚合一致 / T3 三表零迁移 / T4 缺失 header 兜底 / T5 开关关 PW_TASKS_ENABLED / T6 重启幂等 / T7 流式 finally 收口 / T8 记忆闸 hermetic 即验收）。
- 极端路径（中间件自身异常）task 悬挂 running——v1 接受并声明（AC-31，089 账本按 status 过滤）。
- logs off 时 usage 恒空 → tokens_used 恒 0（record_usage 开关短路，plan §0.1 边界如实声明）。
- `datetime.utcnow()` 按 plan 钉死采用（与全库 naive TIMESTAMP 口径一致）。

## 八、修复轮记录（Reviewer NON-PASS 退回，2026-09-06）

> 依据 `review-report.md`（1 阻塞 + 2 LOW）；红线文件未触碰（复验 git diff 仍全空），存量测试零改动（git diff tests/ 仅 conftest 纯新增不变）。

1. **阻塞 #1（编排者裁定 code 1 未落地，已修——含"误报裁定已执行"的更正）**：初版实现走的是 plan §8 待澄清 3 的 code 0 透传旧缺省，且 changelog 头部/§五.5 将其误报为"编排者裁定已执行"——实际裁定为 **code 1（拒绝必须可见，fail-closed 对齐 083 审批闸）**。三步修复：① main.py `memory_save` 补 blocked 分支（`result.get("status") == "blocked"` → `{"code": 1, "message": "记忆保存被拒绝（task 所有权：子只读父写）"}`，沿用本端点既有 `{"code":1,"message":...}` 形状；engine 侧两调用面忽略 save 返回值不受影响，+2 AST）；② TestMemoryGate 补端点级测试 ×2——`test_endpoint_save_blocked_returns_code_1`（read 模式 POST → code 1 + message 含"子只读父写" + _save 未被调；ContextVar set 与 POST 同一 asyncio.run 并复位，防 pytest 共享上下文泄漏——088 LOW-3 教训）+ `test_endpoint_save_normal_returns_code_0`（默认 write → code 0 + data.status=saved，存量透传语义逐字不变）；③ 文档勘误三处：changelog 头部裁定行、§五.5（如实写明系误报更正）、acceptance-criteria.md AC-34（code 0 → code 1 口径，注明编排者裁定取代 plan §8 待澄清 3 旧缺省）。plan.md §8 待澄清 3 系 Planner 产物未改（其"暂按 code 0 实现"表述已被本修复轮事实取代）。
2. **LOW#2（file-index.md 残留，已修）**：删除 memory/file-index.md 第 201 行孤立片段 `fJt`（3 字符，此前"勿动"指令由编排者解除；其余内容零触碰）。
3. **LOW#3（docstring 分节，已修）**：src/tasks.py `finish_task` 补 Returns 节、`set_memory_write_mode` 补 Returns 节、`memory_write_allowed` 补 Args/Returns 节——按 AC-37 字面补齐，代码逻辑零改动（docstring 为单条语句，AST 计数不变 61）。
4. **修复轮后行数与测试**：生产 **94 AST ≤ 200**（main 679→681，其余不变）；定向 **32 passed**（30 + 2 端点级）；存量广覆盖 `tests/api/ tests/agent/ tests/core/` **830 passed / 3 skipped**（= 798 基线 + 32 新增，零新增失败）；py_compile 7 文件 COMPILE OK；红线 git diff 复验仍全空。
5. **Reviewer 备忘 B1/B2 不动**（非阻塞）：B1 同请求内 resolve_identity 两次调用（plan WP-C 草案逐字，量级小）；B2 tasks_enabled=false 时 persist 侧一次空快照（plan 决策 9 已声明）——均保持备忘口径，供后续模块参考。

## 九、修复轮 2 记录（Tester 发现-1 退回，2026-09-06）

> 依据 `test-report.md` §3.1/§5 发现-1（阻塞级真实缺陷，非环境性）；红线未触碰，存量测试零改动（本轮仅改本模块自有 src/tasks.py 1 行 + test_tasks.py 1 处断言）。

1. **根因（fail-open 吞掉真实环境 100% 失败 + 单测 mock 掩盖）**：`begin_task` 经 SQLAlchemy `text()` 直传 `"checkpoint": {}`（Python dict）绑定 JSONB 列——asyncpg 驱动要求 JSONB 参数为 **str**（内部调 `.encode()`），dict 必抛 `asyncpg.exceptions.DataError`，再被 `_run_sql` 的 fail-open warning 吞掉 → **真实库上每次建 task 的 INSERT 100% 失败，tasks 表恒空，"一次请求 = 1 task" 在真实环境完全失效**。为何 Developer/Reviewer 两轮 hermetic 全绿仍漏：test_tasks.py 全量 mock `_spawn`（打桩捕获 Python 参数，dict 合法），asyncpg 驱动层序列化从未被执行；Reviewer 复跑亦仅 hermetic——AC §5 真实对账分层防线的设计目的正中此靶（Tester 原话）。参照系：observability.py request_logs 走 ORM `session.add()`（JSONB 类型装饰器自动 dumps）故线上一直正常；tracing.py 同为 raw text() 但 INSERT 无 JSONB 列故未踩。
2. **修复（1 行 + 自有测试断言同步）**：`src/tasks.py` begin_task 参数 `"checkpoint": {}` → `"checkpoint": "{}"`（JSON 字符串，与 DDL default '{}' 同值，无语义变化；行内注释固化原因）；`test_tasks.py` TestPrimitives 的 INSERT 参数断言 `p["checkpoint"] == {}` → `== "{}"`（本模块自有新测试，不在"存量测试零改动"红线内）。**读侧零改动**：JSONB 读写往返已由 Tester T4 真实验证正常（'{}' 存入 → {} dict 读回），TestOverview/_task_row 的读侧 dict 形态断言保持原样。
3. **修复后最小重验面（Tester 指定四项）**：① 定向 `pytest tests/api/test_tasks.py -q` = **32 passed**（14.12s）；② py_compile 7 文件 **COMPILE OK**；③ AST 复核 **94 ≤ 200 不变**（字面量改动零语句增减：database +10 / tasks 61 / main +18 / memory +4 / config +1）；④ 红线 `git diff --stat` **仍全空**。**未跑全量、未起服务**——T1/T2 真实落库对账 + 流式 task 侧收口 + 全量回归归 Tester 复验。
4. **可复用坑记录（后续模块写库必读）**：
   > **SQLAlchemy `text()` 路径绑定 JSONB 列必须传 JSON 字符串，不能传 dict/list**——asyncpg 驱动对 JSONB 参数直接调 `.encode()`，Python 容器必抛 `DataError`；该异常被写侧 fail-open（warning 不上抛）吞掉后主链路无感，缺陷只在真实落库面暴露。与 ORM 路径（`session.add(Model)`，JSONB 类型装饰器自动 `json.dumps`）行为不同，不可类比照搬。本仓对照先例：`tracing.py`（raw text() 无 JSONB 列，安全）/ `tasks.py`（raw text() + JSONB 列，本轮踩坑）/ `observability.py`、verify（ORM 路径，自动序列化）。**规约：凡 raw text() 写 JSONB，入参用 `json.dumps(obj)` 或 `'{}'` 字面量，且必须有真实驱动层（非 mock `_spawn`）的落库验证用例**——hermetic mock 打桩天然测不到驱动序列化。
5. **Tester 发现-2（PW_TASKS_ENABLED= 空串启动崩）不动**——pydantic bool 字段标准 fail-fast 行为（088 发现-1 同类），非本模块缺陷无需代码改动；Reviewer 备忘 B1/B2 维持非阻塞。

## 十、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~G 全量落地：tasks 表 DDL + src/tasks.py 读写两侧 + main.py 中间件 087 块/persist 收口/task 概览端点 + MemoryService.save 所有权闸 + 开关钉桩 + 30 项单测；生产行数 92 AST ≤ 200；偏离 5 项如实申报） | Developer |
| v2 | 2026-09-06 | 修复轮（Reviewer NON-PASS 退回）：阻塞 #1 /ai/memory/save blocked → code 1 分支（+2 AST）+ 端点级测试 ×2（32 项）+ changelog 头部/§五.5 与 AC-34 勘误（含"误报裁定已执行"更正）；LOW#2 file-index.md fJt 残留删除；LOW#3 tasks.py 三函数 docstring 分节补齐；行数 94 AST ≤ 200 | Developer |
| v3 | 2026-09-06 | 修复轮 2（Tester 发现-1 退回）：begin_task checkpoint 绑定 dict → "{}" JSON 字符串（text()+JSONB 路径 asyncpg 必炸 DataError 被 fail-open 吞，真实库 INSERT 100% 失败 tasks 恒空——根因与可复用坑记录如实入档 §九）+ TestPrimitives 断言同步；读侧零动；行数 94 AST 不变 | Developer |
