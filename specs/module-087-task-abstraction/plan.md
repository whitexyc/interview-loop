# 开发计划 — Module-087: 任务抽象（task 表 + 一次请求 = 1 task + "子只读父写"所有权）

> Planner: 2026-09-06 | 依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 D（任务化底座）module-087 行——"**任务抽象：task 表（task_id/intent/status/预算/父子链）+ 一次请求 = 1 task = N Agent = M 调用**"，验收方向"**观测聚合/预算/checkpoint 均挂在 task 上**"；关键设计约束原文"多 Agent 并发写记忆会脏写 → **'子只读父写'模型（在 module-087 任务抽象中一并落地）**"
> 范围：新表 tasks + 请求↔task 挂接（中间件建 / persist 收口）+ 既有观测三表经 trace_id 读侧关联 + task 级预算字段与 token 计数 + checkpoint 结构预留 + 记忆所有权闸；**熔断账本是 module-089、checkpoint 逻辑是 module-090、多 Agent 编排是 T5/Supervisor——全部不实现**
> 预算：WP-A 0.5 天 + WP-B 1 天 + WP-C 1 天 + WP-D 0.5 天 + WP-E/F 0.5 天 + WP-G 回归 0.5 天 ≈ 4 天
> Agent 配置：Developer ×1（纯 Python 栈）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（Developer 勿重复调查）

### 0.1 观测三表现状与红线边界
- **三表既有 DDL（本模块一字不改，红线）**：request_logs（`src/database.py:57-77` REQUEST_LOGS_DDL）/ tool_call_logs（`:94-112`）/ request_spans（`:154-180`）。写入侧 `src/observability.py`（178 行，**088 写入侧锁定，本模块零 diff**）。
- **三表天然共同关联键 = trace_id**：request_logs 每行带 trace_id；tool_call_logs 带 trace_id（module-066/ADR-0017）；request_spans.trace_id + parent_span_id（module-088）。**task 的关联维度经 `tasks.trace_id` 读侧 join 达成（裁定 1），三表不加列、零迁移**。
- `observability.get_request_stats()`（observability.py:141-143）返回观测快照 dict（usage 按供应商 `{prompt, completion}` 累积）——**tokens_used 数据源（只读消费，不改 observability.py）**。usage 累积由 `record_usage` 在 `request_logs_enabled=false` 时 no-op，故 logs 关时 tokens_used 恒 0（边界如实声明）。

### 0.2 请求收口单一汇聚点（本模块生命周期闭环的支点，重要）
- **`main.py:305-332 persist_request_log(fastapi_req, endpoint, intent="", error=False)`**：全部对话端点的请求收口点，恰好 4 个调用点——chat main.py:491（happy path，error=result.message=="internal_error"，intent=分类结果）、chat_stream main.py:664（**流生成器 finally 块**——流结束/断开/异常全覆盖）、agent main.py:809 / agent-lg main.py:887（finally 同构，intent="agent"）。**在 persist 收口 = 流式任务的 status/tokens/intent 在流真实结束时落定（比 call_next 返回时机更准，与 request_logs.usage 完全同口径）**。
- 4 个对话端点路径：`/ai/rag/chat`（main.py:464）/ `/ai/rag/chat/stream`（:668）/ `/ai/rag/chat/agent`（:740）/ `/ai/rag/chat/agent-lg`（:818）。
- **中间件 main.py:207-259 rate_limit_middleware 顺序**：058 块 L219-222（request_logs_enabled → make_trace_id + init_request + state.trace_id）→ health 早期 return L225-226 → 429 短路 L238-244 → 088 块 L251-257（trace_spans_enabled → X-Trace-Id sanitize 或自生成 + init_request 幂等覆盖 + begin_request 根 span）→ L259 `return await call_next(request)`。**087 块插在 088 块之后、call_next 之前**：trace_id 终值已定 + contextvar 随 task 快照传 downstream（058/088 已实证）+ 429/health 零 task（与 088 边界一致）。

### 0.3 长期记忆写入单一入口（"子只读父写"挂点）
- **`rag/memory/memory.py:291 MemoryService`**：`save`（:309，长期层 source='memory:\<identity\>:'，委托 `_save(layer="")`，返回 `{"id","title","status":"saved"}` 或 `{"status":"updated"}`，异常 ValueError/RuntimeError）；`save_short`（:332，短期层）；recall/recall_short（读侧，不动）。
- **save 的全部生产调用面（3 处全汇入单一入口）**：`rag/engine.py:662`（remember_content）+ `:687`（extract_facts 事实提取，均经 engine._persist_memory fire-and-forget）+ `main.py:909`（/ai/memory/save 手动保存端点，返回 `{"code":0,"data":result}` dict 透传）。**闸设 save 首行即全覆盖，拒绝返回 `{"status":"blocked"}` 对两类调用方均兼容**（engine 忽略返回值；端点透传进 data）。
- 短期/会话记忆：save_short（memory.py:332，委托同一 `_save`——**闸必须设在 `save` 入口而非 `_save`，否则短期层被误伤**）/ session_memory.py（会话层）。

### 0.4 基建与测试先例（照抄模式）
- **幂等 DDL**：REQUEST_SPANS_DDL（database.py:154）+ `ensure_request_spans_table()`（:183，`DDL.split(";")` 拆分执行）+ `init_db()`（:316+）挂接两行（ensure + 日志）——同款照抄。
- **fire-and-forget 引用池**：tracing.py:86-96 `_pending_tasks` 集合 + `add_done_callback(discard)`（防 GC，088 minor-1 修复沉淀）——tasks.py 照抄；`asyncio.create_task` 无运行 loop 时 RuntimeError 窄捕获静默放弃。
- **开关先例**：config.py:140 request_logs_enabled / :147 tool_call_logs_enabled / :154 trace_spans_enabled + conftest.py:131 `default_trace_spans_disabled` autouse fixture（monkeypatch.setattr settings）。**env 变量名 = env_prefix `PW_` + pydantic 字段名**（088 Tester 发现-1 教训：本模块文档口径唯一写法 **PW_TASKS_ENABLED**（字段 tasks_enabled），.env 写错名 extra_forbidden 启动即崩）。
- **端点契约**：`{code, msg, data}` + fail-open（铁律 7）——088 `GET /ai/observability/trace/{trace_id}`（main.py:1335）与 085 dashboard（main.py:1314）同款照抄。
- **测试打桩**：mock `src.tasks._spawn` 同步捕获（对齐 test_tracing.py `_capture_spans`，不依赖真实 task 完成）；`_FakeSession`（test_dashboard.py）；ASGITransport（test_observability.py）；**直调 begin_task/persist 类同步入口必须包 `asyncio.run`**（088 LOW-3 教训：ContextVar 直调会向 pytest 共享上下文泄漏"幽灵 task"）。
- **基线**：module-088 闭环后全量 **1638 passed / 0 failed / 3 skipped**（2026-09-06 Tester 实测）——红线：**新增 0 失败、存量测试零改动（tests/ 仅 conftest 新增 fixture）**。
- 命名事实：新表 `tasks`（PG 无保留字冲突）；新模块 `src/tasks.py`——与既有 `src/verify_tasks.py`（module-060 异步 verify 任务）、tests 侧 agent_tasks（module-066 静态评测任务集）、`verify_results.task_id` 列（module-060 的 verify 任务 id）**概念均不同、零代码冲突**，后者不迁移不关联（声明，防混淆）。

## 1. 关键决策（Planner 裁定）

1. **task 关联维度不加列（读侧 join）**：任务包中"新表新列均可"与红线"三表既有 DDL 零改动"并存——**取保守可行侧：request_logs/tool_call_logs/request_spans 三表零 ALTER、零新列**，tasks 表自带 trace_id 列，观测聚合 = `tasks.trace_id` 与三表读侧 join。理由：① 红线字面优先；② request_logs 写侧在 observability.py（088 锁定零 diff），加列也无人能写 task_id（旁路 UPDATE 属双写复杂度，不值）；③ v1 一次请求 = 1 task，task↔trace 1:1，join 语义等价且既有埋点数据零迁移；④ 085 读侧聚合先例（零新表零加列出指标）。090 长任务跨请求时再议关联表（见 §8 待澄清）。
2. **task 覆盖面 = 对话四端点白名单**（`_TASK_ENDPOINTS` frozenset，精确对齐 persist_request_log 既有调用面）：roadmap"一次请求 = 1 task"的"请求"指 AI 对话请求；白名单保证**每个 task 必有唯一收口点**（无悬挂 running、无双闭合竞态）；429/health/其余端点（memory/documents/crawl/feedback 等）零 task（边界如实声明，089 账本同面对齐）。
3. **生命周期：中间件建（INSERT status=running）→ persist 收口（UPDATE intent/status/tokens_used/finished_at，`WHERE status='running'` 天然幂等）**。收口在流 finally → 流式任务终态/耗时/token 与 request_logs 完全同快照同口径。极端路径（中间件自身异常）task 悬挂 running——v1 接受并声明（089 账本按 status 过滤）。
4. **预算 = 只留结构不执法**：`budget_token_limit` 列（INTEGER，0=不限，089 熔断账本的挂载列）+ `tokens_used` 计数（收口回写 = usage 各供应商 prompt+completion 之总和，标量不分桶）。**零 enforcement、零预算 config、零熔断**（module-089）。
5. **checkpoint = 纯结构预留**：`checkpoint` JSONB 列 DEFAULT '{}'，v1 零读零写零逻辑（module-090 断点续跑）。
6. **"子只读父写"三层落地（roadmap 关键设计约束，非投机功能）**：① tasks.`memory_write` 列（结构声明：父 task='write'，子 task='read'）；② `src/tasks.py` 运行时原语——`_memory_write_var: ContextVar[str]`（default 'write'）+ `set_memory_write_mode(mode)`（仅接受 read/write，非法 no-op）+ `memory_write_allowed()`；contextvar 快照继承机制 058/088 已实证（未来子 Agent 派生 task 时置 read 即继承生效）；③ `MemoryService.save` 入口闸（约 3 行：not allowed → `logger.warning("长期记忆写入被拒绝（task 所有权：子只读父写，module-087）")` + `return {"status": "blocked"}`，fail-open 不上抛）。**v1 无生产调用方置 read（默认 write = 现状行为逐字不变），原语语义由单测锁定，调用方出现在 T5 子 Agent 编排**。save_short/save_session 不设闸——脏写风险在共享长期沉淀层（语义去重/冲突判定/进化全在长期层），短期/会话层按 identity 隔离且生命周期短（边界如实声明）。
7. **开关 `tasks_enabled`（PW_TASKS_ENABLED，默认 true，对齐 088 trace_spans_enabled 先例）**，独立于 request_logs_enabled/trace_spans_enabled；conftest autouse 钉 false → 存量测试零漂移。**trace 缺失（logs+spans 全关 → state.trace_id 不存在）→ 跳过建 task**（聚合锚缺失，边界声明）。收口独立于 request_logs_enabled（finish_task 调用在 gate 之前）。
8. **读端点 = `GET /ai/observability/task/{task_id}`**：单条 SQL 标量子查询聚合三表计数（全参数化，对齐 085 SQL 先例），`{code,msg,data}` + fail-open（088 trace 端点同构）。无任务列表端点、无前端改动、无新依赖。
9. **persist_request_log 微调（唯一既有函数行为面变化）**：`stats = observability.get_request_stats()` 上移到 request_logs gate 之前（收口需要 usage）；logs off 时多一次空 dict 快照（`_obs()` 惰性初始化，observability.py 模块文档明示安全），无行为变化；test_observability 16 项存量全绿锁定。

## 2. WP 拆解（含 AC 映射）

### WP-A：tasks 表（src/database.py，~10 AST 行）
- `TASKS_DDL` 常量（照抄 REQUEST_SPANS_DDL 拆分执行模式；**DDL 草案，Developer 照做**）：
  ```sql
  CREATE TABLE IF NOT EXISTS tasks (
      id                 BIGSERIAL    PRIMARY KEY,
      task_id            VARCHAR(32)  NOT NULL UNIQUE,
      parent_task_id     VARCHAR(32)  NOT NULL DEFAULT '',
      trace_id           VARCHAR(64)  NOT NULL DEFAULT '',
      endpoint           VARCHAR(128) NOT NULL DEFAULT '',
      intent             VARCHAR(32)  NOT NULL DEFAULT '',
      status             VARCHAR(16)  NOT NULL DEFAULT 'running',
      budget_token_limit INTEGER      NOT NULL DEFAULT 0,
      tokens_used        INTEGER      NOT NULL DEFAULT 0,
      memory_write       VARCHAR(16)  NOT NULL DEFAULT 'write',
      checkpoint         JSONB        NOT NULL DEFAULT '{}',
      identity           VARCHAR(256) NOT NULL DEFAULT '',
      created_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
      finished_at        TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_tasks_trace ON tasks (trace_id);
  COMMENT ON TABLE tasks IS '任务抽象（module-087：一次请求=1 task，观测聚合/预算/checkpoint 挂载点）';
  COMMENT ON COLUMN tasks.task_id IS '任务 ID（uuid4 hex 32）';
  COMMENT ON COLUMN tasks.parent_task_id IS '父任务 ID（父子链；根任务为空串，v1 恒根，生产写入方在 T5）';
  COMMENT ON COLUMN tasks.trace_id IS '请求追踪 ID（关联 request_logs/tool_call_logs/request_spans 的读侧 join 键）';
  COMMENT ON COLUMN tasks.endpoint IS '创建任务的端点路径（对话四端点白名单内）';
  COMMENT ON COLUMN tasks.intent IS '任务意图（chat 分类结果；agent 端点=agent；请求收口时回写）';
  COMMENT ON COLUMN tasks.status IS '任务状态：running/completed/failed';
  COMMENT ON COLUMN tasks.budget_token_limit IS 'token 预算上限（0=不限；module-089 熔断账本用，本模块只存不执法）';
  COMMENT ON COLUMN tasks.tokens_used IS '已用 token 总量（usage 各供应商 prompt+completion 汇总，收口回写）';
  COMMENT ON COLUMN tasks.memory_write IS '记忆写所有权（子只读父写：父=write 子=read，module-087 关键设计约束）';
  COMMENT ON COLUMN tasks.checkpoint IS '断点续跑检查点（module-090 预留，v1 零读零写）';
  COMMENT ON COLUMN tasks.identity IS '请求身份（user_id 优先 client_ip 兜底，对齐 048 口径）';
  COMMENT ON COLUMN tasks.finished_at IS '任务收口时间（NULL=仍 running）';
  ```
  + `ensure_tasks_table()` + `init_db` 尾部挂接 2 行（ensure + "tasks 表已就绪（module-087 任务抽象）"日志）。INSERT 不含 created_at（DB default）；finished_at 由收口 UPDATE 传 Python 侧 `datetime.utcnow()`。
- **AC 映射**：AC-1、AC-2、AC-3（红线）。

### WP-B：task 原语 + 读侧聚合 `src/tasks.py` 新模块（核心，~55 AST 行）
- 模块 docstring：任务抽象（module-087）；写侧 fire-and-forget fail-open 对齐 tracing.py；读侧聚合；不实现熔断（089）/checkpoint 逻辑（090）/子 Agent 编排（T5）。
- `_task_id_var: ContextVar[str]`（default ""）+ `_memory_write_var: ContextVar[str]`（default "write"）。
- `_pending_tasks: set` 引用池 + `_spawn(sql, params)`：`asyncio.create_task(_run_sql(...))`，RuntimeError 窄捕获静默放弃，引用池 + done_callback discard（照抄 tracing.py:89-96）。
- `_run_sql(sql, params)`：`async_session_factory()` + `text(sql)` execute + commit；**全异常 logger.warning 不上抛**（文案对齐 "tasks 落库失败（fail-open，不影响主链路）"）。
- `_SQL_INSERT`（11 绑定列全参数化 `:xxx`）/ `_SQL_FINISH`（UPDATE SET intent=CASE WHEN :intent <> '' THEN :intent ELSE intent END, status=:status, tokens_used=:tokens_used, finished_at=:finished_at WHERE task_id=:task_id AND status='running'）/ `_SQL_OVERVIEW`（task 行 13 列 + 3 个标量子查询 `(SELECT COUNT(*) FROM request_logs r WHERE r.trace_id = t.trace_id)` 等，全参数化只读）。
- `begin_task(trace_id, endpoint, identity) -> str`：task_id = uuid4().hex → `_task_id_var.set` → 开关关 return（对齐 begin_request 先例）→ INSERT spawn。
- `finish_task(task_id, intent="", error=False, tokens_used=0) -> None`：空 task_id 或开关关首行 return → status = "failed" if error else "completed" → UPDATE spawn（finished_at=utcnow）。
- `set_memory_write_mode(mode) -> None`（仅 'read'/'write' 接受，非法 no-op）/ `memory_write_allowed() -> bool`（`_memory_write_var.get() != "read"`）。
- `get_task_overview(task_id) -> dict | None`：单 SQL 查询（`mappings()` 取行）→ 无行 None → 三计数键 pop 进 `obs` 子 dict → 返回 task dict（异常原样上抛，端点层统一 fail-open）。
- **AC 映射**：AC-4~9、AC-17~19 原语侧、AC-21。

### WP-C：main.py 接线（~27 AST 行）
- 顶部 `from src import tasks` 1 行 + `_TASK_ENDPOINTS = frozenset({"/ai/rag/chat", "/ai/rag/chat/stream", "/ai/rag/chat/agent", "/ai/rag/chat/agent-lg"})` 1 行。
- **中间件 087 块**（插在 088 块 L251-257 之后、`return await call_next(request)` L259 之前）：
  ```python
  # module-087：任务抽象——一次对话请求 = 1 task（观测聚合/预算/checkpoint 挂载点）。
  # 块位置在 088 块之后（trace_id 终值已定）、call_next 之前（contextvar 快照传
  # downstream，058/088 已实证）；429/health 不建 task（同 088 边界）。trace 缺失
  # （logs+spans 全关）跳过——聚合锚缺失。覆盖面 = persist_request_log 调用面
  # （对话四端点），保证每个 task 恰有一个收口点。
  if settings.tasks_enabled and request.url.path in _TASK_ENDPOINTS:
      _trace_id = getattr(request.state, "trace_id", "")
      if _trace_id:
          request.state.task_id = tasks.begin_task(
              trace_id=_trace_id, endpoint=request.url.path,
              identity=resolve_identity(request))
  ```
- **persist_request_log 收口块**（`stats = get_request_stats()` 上移到 gate 前 + gate 前插入，~6 行）：
  ```python
  # module-087：任务收口——status/tokens_used/intent 一次 UPDATE（fire-and-forget
  # fail-open；独立于 request_logs_enabled，tasks_enabled 自有开关；流式请求在
  # 流 finally 收口 → 终态与 request_logs 同口径）。
  tasks.finish_task(
      getattr(fastapi_req.state, "task_id", ""),
      intent=intent, error=error,
      tokens_used=sum(int(u.get("prompt", 0)) + int(u.get("completion", 0))
                      for u in stats.get("usage", {}).values()))
  ```
- **新端点** `GET /ai/observability/task/{task_id}`（088 trace 端点同构 ~12 行）：try/except `logger.warning("task 查询失败（fail-open）: %s")` → `{"code": 1, "msg": "task 查询失败（fail-open）"}`；None → `{"code": 1, "msg": "task 不存在"}`；成功 `{"code": 0, "msg": "success", "data": task}`。
- **AC 映射**：AC-10~16、AC-17/18 端点侧。

### WP-D：长期记忆所有权闸（rag/memory/memory.py，~4 AST 行）
- `MemoryService.save` 首行（委托 `_save` 之前）插入：
  ```python
  if not tasks_memory_write_allowed():
      logger.warning("长期记忆写入被拒绝（task 所有权：子只读父写，module-087）")
      return {"status": "blocked"}
  ```
  import：`from src.tasks import memory_write_allowed as tasks_memory_write_allowed` 1 行。**闸只设在 `save`，`_save`/`save_short` 不动**（save_short 委托 `_save`，闸设 `_save` 会误伤短期层——§0.3 事实）。
- **AC 映射**：AC-22~24。

### WP-E：config + conftest（~1 AST 生产行）
- config.py：`tasks_enabled: bool = True`（trace_spans_enabled 之后 1 字段；注释对齐既有开关风格，**明确写 PW_TASKS_ENABLED**——088 发现-1 教训）。
- conftest.py：新增 `default_tasks_disabled` autouse fixture（monkeypatch.setattr settings.tasks_enabled=False，docstring 对齐 default_trace_spans_disabled；注明新测试 test_tasks.py 体内显式开启）。
- **AC 映射**：AC-25、AC-26。

### WP-F：单测 `tests/api/test_tasks.py` 新增（~28 项，不计入生产行数）
- TestDDL（~2）：DDL 文本 14 列 + UNIQUE(task_id) + idx_tasks_trace + COMMENT；ensure 拆分执行语句数断言。
- TestPrimitives（~8）：begin_task 开关关不落库但 set var / 开关开 INSERT 参数全字段（11 列含 parent=""/memory_write=write/status=running/checkpoint={}）/ finish_task error→failed、正常→completed / UPDATE 含 WHERE status='running'（幂等文本断言）/ intent 空串不覆盖（CASE 文本）/ 空 task_id no-op / tokens 汇总口径 / set_memory_write_mode 非法值 no-op + allowed 默认 True。
- TestMiddleware（~5）：ASGITransport tasks on + chat 路径 → state.task_id 32hex + INSERT 捕获（trace_id==state.trace_id、endpoint、identity）/ 非 chat 路径（/ai/memory/save）零 task / tasks off 零 task / logs+spans off 零 task（trace 缺失边界）/ 429 零 task（位置锁）。
- TestFinishHook（~3）：persist_request_log 直调（asyncio.run 包裹 + mock tasks._spawn 捕获）finish 参数正确（intent/error/tokens）/ logs off 时 finish 仍执行（独立开关）/ state 无 task_id no-op。
- TestOverview（~3）：_FakeSession 形状断言（含 obs 子 dict 组装）/ 不存在 None / _SQL_OVERVIEW 只读词边界。
- TestEndpoint（~4）：ASGITransport 200 code 0 契约形状字段逐字 / 不存在 code 1 / 异常 fail-open code 1 不 500 / data.obs 三键。
- TestMemoryGate（~3）：save 默认放行（_save 被调）/ monkeypatch read → save 返回 {"status":"blocked"} 且 _save 不被调 + warning / save_short 与 session_memory 在 read 模式下不受影响。
- TestOneRequestOneTask（~1）：ASGITransport chat 最轻链（对齐 088 TestOneRequestOneTrace 模式）→ INSERT 与 finish 同 task_id + trace_id 一致。
- TestSQLHygiene（~1）：三条 SQL 无 f-string/`%`/`+` 拼接。
- 打桩：对齐 088 `_capture`（mock `src.tasks._spawn` 同步捕获）；直调同步入口包 asyncio.run；持久化函数测试模式照抄 test_observability。

### WP-G：回归 + 文档收口
- py_compile 6 文件（database / src/tasks / main / rag/memory/memory / src/config / tests/conftest）；定向 test_tasks.py 全绿；受影响存量定点：tests/api/test_observability.py + test_dashboard.py + test_tracing.py（中间件/persist 面）+ tests/memory/（save 闸面：test_memory.py、test_memory_correction.py、test_memory_extractor.py 等）+ tests/agent/test_tool_call_logs.py。
- 全量 `python -m pytest -q` = **1638 基线 + ~28 新增全绿 / 0 failed / 3 skipped——新增 0 失败**（预期 ≈1666）。
- 文档：changelog.md（Developer）→ review-report.md（Reviewer）→ test-report.md（Tester）；记忆三件套（file-index 两行 + activity-log 两行 + project-context 状态行）。

## 3. 行数对照（铁律 2，AST 可执行行口径）

| WP | 文件 | 预估 AST 行 |
|----|------|------------|
| WP-A | src/database.py（DDL 常量 1 + ensure ~6 + init_db 挂接 2） | ~10 |
| WP-B | src/tasks.py（新：vars 2 + SQL 3 + spawn/run 11 + begin 8 + finish 9 + 所有权 5 + overview 9 + import ~6） | ~55 |
| WP-C | main.py（import 1 + 白名单 1 + 中间件块 ~7 + persist 块 ~6 + 端点 ~12） | ~27 |
| WP-D | rag/memory/memory.py（闸 3 + import 1） | ~4 |
| WP-E | src/config.py（1 字段；conftest fixture 不计——module-073 先例） | ~1 |
| 合计 | | **~97 ≤ 200 ✓** |

测试 ~28 项不计入。rag/engine.py / agent/react.py / agent/langgraph_react.py **零改动**（意图不回写——intent 由 persist 收口参数承载，engine 不需要动）。若实际超 200，按 module-080 先例晒行数对照表 + 申请 `GATE_MAX_MODULE_LINES` 放宽。

## 4. 风险评估

- **persist_request_log 微调回归（低，已论证）**：仅 stats 上移 + gate 前追加旁路调用；058 语义（record 字段/开关短路）逐字不变；test_observability 16 项 + WP-F TestFinishHook 锁定。
- **流式 tokens_used 口径（低）**：收口在流 finally → 与 request_logs.usage 同一 stats 快照，**比 088 call_next 时机更准**；logs off 时 usage 恒空 → tokens_used=0（record_usage 开关短路，如实声明）。
- **UPDATE 幂等/竞态（低）**：`WHERE status='running'` 单收口点无并发双写；重放安全。
- **记忆闸"死代码"观感（中，roadmap 授权）**：v1 无生产调用方置 read——这是 roadmap 关键设计约束"在 module-087 任务抽象中一并落地"的结构性交付（列 + 原语 + 闸三层），调用方在 T5；单测锁语义防退化；非投机功能（plan §1 决策 6）。
- **budget/checkpoint 空转列（低）**：089/090 接管，DDL COMMENT 已标归属；AC-28/29 锁零读写。
- **env 变量名（中，088 教训）**：全文档唯一口径 **PW_TASKS_ENABLED**；Developer/Tester 勿写 PW_TASKS（.env 写错名 extra_forbidden 启动崩 / OS env 静默无效）。
- **tasks_enabled 默认 true 写放大（低）**：每对话请求 1 INSERT + 1 UPDATE（本地单机量级）；开关逃生口。
- **contextvar 测试泄漏（低）**：直调包 asyncio.run（088 LOW-3 教训，WP-F 已注明）。
- **命名混淆（低）**：tasks 表 / src/tasks.py 与 verify_tasks、agent_tasks（评测任务集）、verify_results.task_id 概念区分——§0.5 声明，Reviewer 甄别红线归属时注意（verify_tasks.py 本模块零 diff）。

## 5. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-058/088 observability.py | **零 diff（红线）**：只读消费 `get_request_stats()`/state.trace_id；task 不写观测上下文 |
| request_logs / tool_call_logs / request_spans 三表 | **既有 DDL 一字不改（红线）**：task 关联 = tasks.trace_id 读侧 join（裁定 1）；三表既有行零迁移零回填 |
| module-088 request_spans 树 | **结构与语义零改动**：根 span kind=request 不动、不新增 span 行、"每 trace 恰 1 根"不变；088 声明的"换挂 task_id（parent_span_id 结构天然兼容）"预留**保留给多 Agent 时代**，v1 以 tasks.trace_id 关联而非改 request_spans |
| module-085 dashboard | 分工互补：085 窗口聚合（记录式）/ 087 单任务概览（任务锚）；端点 fail-open 契约与 SQL 参数化先例照抄 |
| module-089 预算账本（后续） | budget_token_limit 列 + tokens_used 计数是其数据底座；**本模块零执法零 config** |
| module-090 checkpoint（后续） | checkpoint JSONB 列预留；长任务跨请求的 trace 关联问题留 090 规划（§8 待澄清） |
| module-060 verify_tasks / verify_results.task_id | 概念区分（异步 verify 任务 ≠ 087 task）；src/verify_tasks.py 零 diff |
| module-066 tool_call_logs（ADR-0017） | "M 调用"计数 = tool_call_logs WHERE trace_id join（读侧），写入侧零改动 |
| module-033/046/061/070 长期记忆链 | save 单一入口闸（3 处调用面全覆盖）；默认 write 存量行为逐字；拒绝 = fail-open blocked |
| module-083 execute_tool_with_log | 本模块**不触碰**（react.py 零 diff）；工具调用经 tool_call_logs.trace_id 进 task 聚合 |
| T5/Supervisor 多 Agent 编排（后续） | parent_task_id 生产写入方 + set_memory_write_mode('read') 调用方 + N Agent 实体——全部 T5 范畴，v1 只留结构 |

## 6. 明确不做

- **预算熔断/超预算执法/预算 config（PW_TASK_BUDGET_* 等）/ 成本金额换算**（module-089 账本）
- **checkpoint 任何读写逻辑/断点恢复**（module-090）
- **子 Agent 编排 / parent_task_id 生产写入 / 子 task 创建 / N Agent 实体表**（T5/Supervisor）
- **request_spans 加 task span / 根 span 换挂 task_id / 树语义改动**（088 结构预留保留，多 Agent 时代议）
- **三表任何 ALTER/新列/数据回填**（裁定 1：读侧 join）
- **任务列表端点 / 前端 UI / 085 看板入口**（v1 只出单 task 概览端点）
- **多 task 聚合报表 / tokens 按供应商分桶列**（089 规划时裁定）
- **save_short / session_memory 所有权闸**（裁定 6 边界）
- **ORM 模型**（raw INSERT 对齐 tool_call_logs/request_spans 先例）
- **新依赖 / OpenTelemetry / 批量缓冲**（058/088 决策延续）
- **tasks 表清理/归档策略**（与 request_logs 同现状：量级小不清理）
- **新 ADR**（无架构分歧：决策记录于本 plan 与 changelog）

## 7. 响应契约（GET /ai/observability/task/{task_id}，Developer 勿改字段名）

```json
{
  "code": 0, "msg": "success",
  "data": {
    "task_id": "087a4f2e6b7d4c1a9e3f5a8b2c6d0e4f",
    "parent_task_id": "",
    "trace_id": "0887e57e0123456789abcdef0123456789",
    "endpoint": "/ai/rag/chat",
    "intent": "knowledge",
    "status": "completed",
    "budget_token_limit": 0,
    "tokens_used": 1234,
    "memory_write": "write",
    "checkpoint": {},
    "identity": "user-1",
    "created_at": "2026-09-06T12:00:00.123456",
    "finished_at": "2026-09-06T12:00:03.456789",
    "obs": {"request_logs": 1, "request_spans": 7, "tool_calls": 3}
  }
}
```
（task 不存在 → `{"code": 1, "msg": "task 不存在"}`；DB 异常 → `{"code": 1, "msg": "task 查询失败（fail-open）"}`。obs 三键 = 标量子查询计数，v1 经 trace_id 关联。）

## 8. 待澄清（不阻塞开发，Developer 按本 plan 缺省执行）

1. **090 长任务跨请求的 trace 关联**：tasks.trace_id 当前单值（v1 1:1 成立）；090 断点续跑产生"一 task 多 trace"时需 task_traces 关联表或复议三表加列——090 规划时裁定。
2. **tokens_used 是否按供应商分桶**：当前标量汇总；089 账本若需分桶，由 089 决定加列或读 request_logs.usage JSONB。
3. **/ai/memory/save 被 blocked 时的响应语义**：当前透传 `{"code":0,"data":{"status":"blocked"}}`（fail-open，存量调用方零破坏）；若编排者认为应改 code 1（fail-closed 可见失败）请批示，Developer 暂按 code 0 实现。
4. **tasks 表保留策略**：与 request_logs 同现状不清理；若需 TTL 清理由后续模块统一处理。

## 9. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~G 拆解 + 8 大裁定：读侧 join 不加列 / 四端点白名单 / persist 单收口 / 预算结构预留 / checkpoint 结构预留 / 子只读父写三层落地 / 独立开关 / 单 task 概览端点；DDL 草案 + 响应契约 + 行数对照 ~97 + 风险与既有机制关系） | Planner |
