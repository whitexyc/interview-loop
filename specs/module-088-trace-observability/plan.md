# 开发计划 — Module-088: 链路式观测（trace_id 跨进程传播 + span 树 + 决策级日志）

> Planner: 2026-09-06 | 依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 B（可观测：记录式 → 链路式）module-088 行——"链路式观测：trace_id 跨进程传播 + span 树（因果父节点）+ 决策级日志（为什么选这个工具/分支）"，验收方向"**一次请求对应一条 trace，父 span 含决策原因**"
> 范围：新表 request_spans + 6 个埋点 + 1 个读端点 + SSE done 透传 trace_id；**不引入 task 抽象（module-087 底座，trace 根 = 请求）**
> 预算：WP-A 0.5 天 + WP-B 1 天 + WP-C 0.5 天 + WP-D/E/F 1 天 + WP-G 0.5 天 + WP-H 1 天 + WP-I 回归半天 ≈ 4.5 天
> Agent 配置：Developer ×1（纯 Python 栈）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（Developer 勿重复调查）

### 0.1 现有 trace 机制（module-058，只读复用不改）
- **`ai_service/src/observability.py`（178 行）**：contextvar `_obs_var` 承载每请求观测 dict `{trace_id, timings, usage, cache_hits, cache_misses}`。关键 API：`init_request(trace_id)`（中间件调用，幂等重置）、`get_trace_id()`（**只读不惰性初始化**）、`make_trace_id()` = `uuid.uuid4().hex`、`TraceIdFilter`（日志 extra 注入）、`save_request_log`（fire-and-forget fail-open 模板）。**本模块零 diff（红线）**——spans 只消费 `get_trace_id()`。
- **中间件 `main.py:205-245` `rate_limit_middleware`（BaseHTTPMiddleware）**：L217-221 在**限流检查/身份解析之前**做 trace 初始化（`request_logs_enabled` 时 make_trace_id + init_request + `request.state.trace_id`）；L227-234 解析 client_ip/user_id；L237-243 限流 429 短路；L245 `call_next`。**058 已实证 BaseHTTPMiddleware 下 call_next 前设置的 contextvar 随 task 复制传给 downstream**（chat_stream 14 行 request_logs 的 timings 非空即证据）——spans 埋点沿用同一位置语义即可。
- **request_logs 表（database.py:57-77）**：trace_id/identity/endpoint/intent/timings JSONB/usage JSONB/cache_hits/cache_misses/error/created_at。**每行都带 trace_id 但无 span/父节点概念——查不出因果树**（本模块核心缺口）。真实库 32 行（085 Tester 终态）。
- **tool_call_logs 表（database.py:94-112，module-066/ADR-0017）**：trace_id/tool_name/args/result_ok/result_preview/duration_ms/created_at——**有 trace_id 无父节点**，且 467 行真实数据量级小。**表结构一字不改（红线）**。

### 0.2 决策级日志的天然挂点（"为什么"的现成载体）
- **工具执行唯一汇聚点 `agent/react.py:333-376 execute_tool_with_log`**：两条 ReAct 循环（react_loop/langgraph_react_loop）+ MCP exec 全走此处（084 Review 实证三路汇入）。内部已有：二维守门（`_phase_allows` 阶段 + `allowed_tools` 权限，拒绝时 result 带可读原因 L355-363）→ `tool.run` → duration 计时 → `record_tool_call`（L264-308，原生 `text()` INSERT + fail-open + 开关首行 return——**spans 写入照抄此模式**）。工具 span 放这里 = 一处改两循环 + MCP 自动继承。
- **阶段推进决策 `react.py:221-251 advance_phase`**：三分支（① 生成工具调用 → 切 generation；② 检索命中 `_retrieval_hit` → 切；③ 防空转 `retrieval_rounds >= agent_retrieval_max_rounds` 强制切）当前返回 None。**存量测试核实：test_tool_phase_split.py:135-144 + test_agent_phase_fix.py:193-209 调用后只断言 `ctx.phase`，无 `is None` 断言 → 改为返回 reason 字符串向后兼容**。调用点两处：react.py:534、langgraph_react.py:184。
- **预算截断决策 `react.py:488-499`**：`allowed = tool_calls[: min(total_remaining, phase_remaining)]`，`len(allowed) < len(tool_calls)` 即发生截断（"为什么少执行了"）；langgraph 同构截断点在 execute_tools（langgraph_react.py:135-147，phase_exhausted 标记）。
- **意图路由决策**：`engine.chat:342-396`——`intent_result` dict `{intent, confidence, reason}`，**reason 文本就是"为什么"**（router.py：短路"分诊命中 FTS 术语，短路 knowledge" / "L4 classifier {probs}" / "L2 信号确认(...)" / "工具历史信号：..." / "短句意图继承（上一轮 intent=...）" / "LLM 分类失败，保守路由"等）。chat_stream 路由在 main.py:605-609（有 intent 计时 t0）。**agent 端点不调 classify**（main.py 注释实证）。
- **检索分支决策 `engine.py:819-940 _retrieve` + engine.chat:436-527**：retrieval_mode（sag/hybrid_sag/hybrid 三分支 L919）+ retrieval_fusion_mode（L943）+ 反思改写多轮；chat 非流式循环结束处 docs 收齐（L527 ChatSteps 组装前）。

### 0.3 跨进程链路现状（裁定依据，重要）
- **Java→Python 调用点不存在**：`backend/src/main/java/com/personalwebsite/` 全源码 grep `RestTemplate/WebClient/HttpClient/java.net/ai-service` 零命中；controller 仅 Auth/Conversation/Health/Resume 四个；`application.yml:32-35` 有 `ai-service.base-url` 配置但**零代码引用（死配置）**。module-080 反向闭环全在 Python 侧（feedback 表 → weak_topics → crawl），roadmap"RAG↔Java 反向闭环"指能力定位而非 HTTP 调用链。
- **当前真实跨进程调用方 = 前端**（axios `/ai` → vite proxy → Python 8000；`client.ts` 仅附加 Bearer，**不透传任何 trace header**）。
- SSE done 事件现状：chat_stream 经 `_build_done_event`（main.py:521-524）3 处调用点（L556/563/565，签名内已有 fastapi_req）+ 错误路径 bare done（L577/614/630）；agent done L777 / agent-lg done L854（json.dumps dict 直拼）。done payload 均无 trace_id。
- module-058 探针先例：`scripts/probe_request_trace.py`（trace 落库→DB 回读样例）。

### 0.4 基建与测试布局
- **幂等 DDL 先例**：database.py 每表一段 `*_DDL` 字符串常量 + `ensure_*_table()`（`DDL.split(";")` 拆分执行 + `CREATE TABLE IF NOT EXISTS`）+ `init_db()`（L273+）挂接一行——approval_requests（module-083）/verify_results（module-060）同款。
- **config 开关先例**：`request_logs_enabled`（config.py:140，默认 true）/`tool_call_logs_enabled`（L147）+ conftest autouse 钉 false 模式（conftest.py 18+ 个 `@pytest.fixture(autouse=True)`，如 default_mcp_external_disabled L273-291）。
- **测试先例**：`tests/api/test_observability.py`（ASGITransport + 中间件接线用例）、`tests/api/test_dashboard.py`（`_FakeSession` 打桩，模板 test_tool_call_logs.py:34-51）、`tests/agent/test_tool_governance.py`（execute_tool_with_log 守门断言）。测试目录按端点向放 `tests/api/`。
- **`{code, msg, data}` 端点格式先例**：083 approvals GET（main.py）+ 085 dashboard（main.py:1288-1302，fail-open code 1 不 500）。
- **基线**：module-085 闭环后全量 **1592 passed / 0 failed / 3 skipped**（2026-09-06 Tester 实测）——本模块红线：**新增 0 失败、存量测试零改动**。

## 1. 关键决策（Planner 裁定）

1. **span 模型 = 新表 `request_spans`，一张表一个模型；不建 traces 表、不建 decision_logs 表**。一次请求 = 一条 trace = N spans：根 span（kind=request，parent_span_id=''）即 trace 锚，无独立 traces 表（省一次 join，"一次请求一条 trace"由 AC-23 根唯一 + 全体同 trace_id 锁定）。decision 原因落 `decision` 列（TEXT 截断 500），**不建独立 decision_logs**（决策级日志是 span 的一种，分表反而查树要多 join）。写入 = **每 span 即时 INSERT fire-and-forget fail-open**（照抄 record_tool_call 模式：原生 `text()` INSERT 不建 ORM 模型、开关首行 return 零埋点、异常 logger.warning 不上抛）——一次请求 ~5-10 行写放大在本地单机量级（现状 32/467 行）完全可接受，批量缓冲的复杂度不值。表名带 `request_` 前缀：表达"trace 根 = 请求"，与 module-087 将来的 task 表（task_id 父子链）天然区分不抢活。**无 ORM 模型**（tool_call_logs 先例，raw INSERT）。
2. **埋点面 v1 = 6 个（最小闭环）**：① 根 span（中间件，name=endpoint 路径，含 identity）；② 工具 span（execute_tool_with_log 汇聚点，含"为什么能执行/被拒"：phase/计数/守门状态）；③ advance_phase 阶段切换 span（决策原因枚举，见 §2 WP-D）；④ 意图路由 span（engine.chat + chat_stream 两处，decision=intent+router reason 原文）；⑤ 检索 span（chat 循环后 + _retrieve 返回前，decision=retrieval_mode/fusion/docs 数）；⑥ 预算截断 span（仅手写 react_loop）。**langgraph 不单加埋点**——经 execute_tool_with_log/advance_phase 共享函数自动继承②③（v1 边界如实声明）。
3. **传播方向 = Python 作接收方（HTTP header `X-Trace-Id` 入站）**。事实驱动（§0.3）：Java 无调用点，改 Java 是没有链路的空转；前端/网关/curl/未来 Java 侧注入 header 即插即用。sanitize：strip+lower、长度 ≤64、字符白名单 `[0-9a-f-]`，非法/缺失 → 回退 `make_trace_id()` 自生成（058 行为零回归）。**不做响应回传 header、不做 W3C traceparent 标准头**（自定义 X-Trace-Id 够用，upgrade 留后续）。
4. **查询/展示 = 只出端点 `GET /ai/observability/trace/{trace_id}`（树形 JSON），前端页面/085 看板入口不做**。验收方向是"一次请求对应一条 trace，父 span 含决策原因"——数据面正确性可由单测 + Tester 真实 PG 对账闭环；085 看板加"点请求看链路"入口需请求列表 UI + 前端 ~150 行，v1 不做留后续（SSE done 已带 trace_id，入口数据就绪）。
5. **SSE done 事件带 trace_id：做**（5 处：chat_stream 3 个 `_build_done_event` 调用点 + agent/agent-lg 2 个 dict 直拼点）。改动 ~5 行，让"点请求看链路"有数据入口；错误路径 bare done（`data:{}`）不带（fail-open 边界如实声明）；非流式 chat JSON 响应 schema 零改动。
6. **行数与测试**：生产代码按 AST 可执行行口径预估 **~135 行 ≤200 ✓**（§8 对照表）；测试 `tests/api/test_tracing.py` ~30 项 hermetic（假 session/ASGITransport/mock，对齐 test_dashboard/test_observability 模式；conftest autouse 钉 `trace_spans_enabled=false` 存量零漂移）；**真实 PG 对账留 Tester**（§AC 命令表给 SQL：单 trace 行数/根唯一/decision 非空/request_logs join 同 trace_id/uvicorn 冒烟带 header）。
7. **开关 `trace_spans_enabled`（PW_TRACE_SPANS_ENABLED，默认 true； Tester 发现-1 勘误：原规格误写 PW_TRACE_SPANS，实际生效名 = env_prefix PW_ + 字段 trace_spans_enabled）独立于 request_logs_enabled**（对齐 066 独立开关先例）；false 时中间件块/所有埋点首行短路，058 行为逐字不变。与 request_logs_enabled=true 的交互：088 中间件块在 058 块之后执行，`init_request(最终 trace_id)` 幂等覆盖——**request_logs.trace_id 与 request_spans.trace_id 恒同值**（AC-12 锁定）。

## 2. WP 拆解（含 AC 映射）

### WP-A：request_spans 表（database.py，~10 AST 行）
- `REQUEST_SPANS_DDL` 常量（照抄 request_logs 拆分执行模式；**给 DDL 草案，Developer 照做**）：
  ```sql
  CREATE TABLE IF NOT EXISTS request_spans (
      id              BIGSERIAL    PRIMARY KEY,
      trace_id        VARCHAR(64)  NOT NULL,
      span_id         VARCHAR(32)  NOT NULL,
      parent_span_id  VARCHAR(32)  NOT NULL DEFAULT '',
      name            VARCHAR(128) NOT NULL,
      kind            VARCHAR(32)  NOT NULL DEFAULT 'decision',
      identity        VARCHAR(256) NOT NULL DEFAULT '',
      decision        TEXT         NOT NULL DEFAULT '',
      status          VARCHAR(16)  NOT NULL DEFAULT 'ok',
      duration_ms     INTEGER      NOT NULL DEFAULT 0,
      started_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_request_spans_trace ON request_spans (trace_id);
  COMMENT ON TABLE request_spans IS '请求链路 span（module-088：一次请求一条 trace = N spans，根 span kind=request）';
  COMMENT ON COLUMN request_spans.trace_id IS '请求追踪 ID（关联 request_logs；上游 X-Trace-Id 优先）';
  COMMENT ON COLUMN request_spans.span_id IS 'span ID（uuid4 hex 截 16）';
  COMMENT ON COLUMN request_spans.parent_span_id IS '父 span ID（根 span 为空串）';
  COMMENT ON COLUMN request_spans.name IS 'span 名（端点路径/工具名/决策点名/检索）';
  COMMENT ON COLUMN request_spans.kind IS 'span 类型：request/tool/decision/retrieval';
  COMMENT ON COLUMN request_spans.identity IS '请求身份（仅根 span 填，user_id 优先 client_ip 兜底，对齐 048 口径）';
  COMMENT ON COLUMN request_spans.decision IS '决策原因（为什么选这个工具/分支；截断 500）';
  COMMENT ON COLUMN request_spans.status IS 'span 状态：ok/error/blocked（守门拒绝）';
  COMMENT ON COLUMN request_spans.duration_ms IS '耗时毫秒（决策点可为 0）';
  COMMENT ON COLUMN request_spans.started_at IS 'span 开始时间（Python 侧 utcnow，请求内排序）';
  ```
  + `ensure_request_spans_table()` + `init_db` 挂接 2 行（带 module-088 注释）。
- 通过标准：AC-1/2/3。
- **AC 映射**：AC-1、AC-2、AC-3（红线）。

### WP-B：span 原语 + 读侧树 `src/tracing.py` 新模块（核心，~60 AST 行）
- 模块 docstring：链路式观测（module-088）；写侧每 span 即时 INSERT fail-open；读侧组树；不引入 task 抽象（module-087）；不引新依赖。
- **`_parent_var: ContextVar[str]`（default ""）**：当前根 span_id（begin_request 压入，downstream task 经 contextvar 快照继承——058 已实证该机制可用）。
- `sanitize_incoming_trace(value) -> str`：strip+lower；空/超 64/含非 `[0-9a-f-]` 字符 → `""`；合法原样返回。
- `begin_request(trace_id, endpoint, identity) -> str`：生成 span_id（uuid4 hex 截 16）→ 即时写根 span（kind=request、parent=''、status=ok、duration_ms=0）→ `_parent_var.set(span_id)` → 返回 span_id。开关关时仍 set（无害）但不落库。
- `record_span(name, kind, decision="", status="ok", duration_ms=0) -> None`：开关首行 return → `get_trace_id()` 空则静默跳过 → 组 row（span_id 新生成、parent=`_parent_var.get()`、decision 截 500、started_at=`datetime.utcnow()`）→ `_spawn_insert`。
- `_spawn_insert(row)`：`asyncio.create_task(_insert_span(row))`，无运行 loop（RuntimeError）静默放弃（fail-open）。
- `_insert_span(row)`：`async_session_factory()` + `text(_SQL_INSERT)` 单条参数化 INSERT + commit；**全异常 logger.warning 不上抛**（照抄 record_tool_call L307-308 文案风格）。
- `_SQL_INSERT` 常量（10 列全参数化 `:xxx`，无拼接）。
- 读侧：`get_trace_tree(trace_id) -> dict | None`——`SELECT ... WHERE trace_id = :t ORDER BY started_at, id`（`mappings()` 取行）→ 空返回 None → `{"trace_id", "span_count", "tree": _build_tree(rows)}`；`_build_tree(rows)` **纯函数**：每行 dict 加 `children=[]`，按 span_id 建索引，parent 非空且存在 → 挂父 children，否则入 roots；返回 roots 列表（正常恰 1 个根，异常数据多根容忍）。
- 通过标准：AC-4~9、AC-24~28 的原语侧。

### WP-C：main.py 接线（~28 AST 行）
- **中间件新增块**：插在限流短路（L243）之后、`return await call_next(request)`（L245）之前——identity 已解析（L227-234）且 429 短路请求零 span（限流请求不进链路，边界如实声明）：
  ```python
  # module-088：链路式观测——上游 X-Trace-Id 优先（跨进程传播），缺失/非法
  # 回退自生成（058 行为）；建根 span（kind=request）。块位置在 call_next
  # 之前（contextvar 随 task 快照传给 downstream，058 已实证）。
  if settings.trace_spans_enabled:
      trace_id = tracing.sanitize_incoming_trace(
          request.headers.get("X-Trace-Id", "")) or observability.make_trace_id()
      observability.init_request(trace_id)
      request.state.trace_id = trace_id
      tracing.begin_request(trace_id=trace_id, endpoint=request.url.path,
                            identity=resolve_identity(request))
  ```
  （`observability`/`resolve_identity` main.py 已 import；新增 `from src import tracing` 1 行。058 的 L217-221 块不动——088 块的 init_request 幂等覆盖，request_logs 与 spans 同 trace_id。）
- **SSE done 带 trace_id（5 处）**：`_stream_generate_verify` 内 3 个 `_build_done_event` 调用加 `trace_id=getattr(fastapi_req.state, "trace_id", "")`（**extra 吸收，_build_done_event 签名不改**）；agent done（L777）/ agent-lg done（L854）dict 加 `'trace_id': getattr(fastapi_req.state, 'trace_id', '')`。错误路径 bare done 不动。
- **新端点** `GET /ai/observability/trace/{trace_id}`（对齐 085 dashboard 端点风格 ~13 行）：
  ```python
  @app.get("/ai/observability/trace/{trace_id}")
  async def get_observability_trace(trace_id: str):
      """单请求链路 span 树（module-088；只读 fail-open）"""
      try:
          tree = await tracing.get_trace_tree(trace_id)
      except Exception as e:
          logger.warning("trace 查询失败（fail-open）: %s", e)
          return {"code": 1, "msg": "trace 查询失败（fail-open）"}
      if tree is None:
          return {"code": 1, "msg": "trace 不存在"}
      return {"code": 0, "msg": "success", "data": tree}
  ```
- 通过标准：AC-10~14、AC-24/27/28/29 端点侧、AC-30/31/33。
- **AC 映射**：AC-10~14、AC-24、AC-27、AC-28、AC-29、AC-30、AC-31、AC-33、AC-34、AC-39。

### WP-D：react.py 埋点（~18 AST 行）
- **advance_phase 返回 reason（枚举写死）**：`generation_tool_called`（分支①）/ `retrieval_hit`（分支②，可带首个命中工具名 `retrieval_hit`）/ `idle_force_rounds={settings.agent_retrieval_max_rounds}`（分支③）/ `""`（未切换）。docstring 补 Returns 段。三分支 return 改 `return "..."`。
- **react_loop 调用处（L534）**：`reason = advance_phase(...)`；`if reason: record_span("advance_phase", "decision", decision=reason)`（reason="" 零 span 防噪音）。
- **execute_tool_with_log 汇聚点**（两循环 + MCP 自动继承）：在 `record_tool_call` 调用旁新增工具 span——守门拒绝分支 → `record_span(name, "tool", decision=<拒绝原因（阶段/权限）>, status="blocked", duration_ms=duration_ms)`；正常分支 → `record_span(name, "tool", decision=f"phase={ctx.phase}", status="ok" if result_ok else "error", duration_ms=duration_ms)`。
- **预算截断 span（react_loop L495-499 后）**：`if len(allowed) < len(tool_calls): record_span("budget_truncate", "decision", decision=f"proposed={len(tool_calls)} executed={len(allowed)}")`。
- 通过标准：AC-15~19、AC-23。
- **AC 映射**：AC-15、AC-16、AC-17、AC-18、AC-19、AC-23。

### WP-E：langgraph_react.py 透传（~4 AST 行）
- L184 `advance_phase(...)` 返回值接收 + `if reason: record_span(...)`（与 react_loop 同构）；自身不新增其它埋点（截断 span v1 仅手写循环——如实声明）。
- **AC 映射**：AC-16（langgraph 侧）、AC-22。

### WP-F：engine.py 埋点（~8 AST 行）
- **意图路由 span（engine.chat L394 `observability.timing("intent", ...)` 后）**：`record_span("intent_routing", "decision", decision=f"intent={intent} reason={intent_result.get('reason', '')[:200]}", duration_ms=int((time.perf_counter() - _t0) * 1000))`。
- **检索 span（engine.chat 检索循环结束后、ChatSteps 组装前）**：`record_span("retrieval", "retrieval", decision=f"mode={settings.retrieval_mode} fusion={settings.retrieval_fusion_mode} docs={len(all_docs)}", duration_ms=int((time.perf_counter() - _loop_t0) * 1000))`。
- 通过标准：AC-20/21（engine.chat 侧）。
- **AC 映射**：AC-20、AC-21。

### WP-G：config + conftest（~2 + 5 行）
- config.py：`trace_spans_enabled: bool = True`（PW_TRACE_SPANS_ENABLED 回退——发现-1 勘误；注释对齐 request_logs_enabled 风格——默认 true 与 058/066 同生命周期，false 零埋点零落库，测试 conftest 钉 false）。
- conftest.py：新增 `default_trace_spans_disabled` autouse fixture（monkeypatch.setattr settings + docstring 对齐 default_mcp_external_disabled 模式）。
- **AC 映射**：AC-4、AC-13、AC-36、AC-44。

### WP-H：单测 `tests/api/test_tracing.py` 新增（~30 项，不计入生产行数）
- TestSanitize（~4）：合法 hex/大写归一/超 64/非法字符与 None。
- TestSpanPrimitives（~6）：开关关零落库/无 trace 上下文跳过/begin_request 根 span 字段（kind=request parent=''）/record_span parent==根/fail-open（session 抛错不上抛）/INSERT SQL 参数化断言（无 f-string）。
- TestAdvancePhaseReason（~5）：三分支枚举 + 未切空串 + 存量语义（test_agent_phase_fix 同款断言补 return 值）。
- TestToolSpan（~3）：execute_tool_with_log 正常/blocked（守门拒绝）/error 三态 + decision 文本。
- TestBudgetTruncateSpan（~1）：假 LLM 提议 2 执行 1 → span 存在。
- TestTraceEndpoint（~5）：ASGITransport 200 code 0 形状/树嵌套/_build_tree 纯函数（单根/孤儿挂根/多根容忍）/trace 不存在 code 1/异常 fail-open code 1。
- TestPropagation（~4）：带合法 X-Trace-Id → state.trace_id==header；非法 → 自生成；开关关 → 058 行为逐字；request_logs 与 spans trace_id 同值。
- TestSSETraceId（~2）：mock 循环 done payload 含 trace_id（agent 端点最轻路径）。
- TestSQLHygiene（~2）：INSERT/SELECT 无拼接只读 + 开始时间非 DB default（Python 侧 utcnow 传入）。
- 打桩模式：`_FakeSession` 照抄 test_dashboard.py；端点用例 ASGITransport 照抄 test_observability.py；fire-and-forget 时序——单测直接 `await tracing._insert_span(row)` 或 mock `_spawn_insert` 记录（不依赖真实 task 完成）。

### WP-I：回归 + 文档收口
- py_compile 4 文件（tracing/database/react/main + langgraph/engine）；定向 test_tracing.py 全绿；受影响存量定点：test_observability / test_dashboard / test_tool_call_logs / test_tool_phase_split / test_agent_phase_fix / test_tool_governance / test_tool_retry_dedup / test_mcp_client（execute_tool_with_log 与中间件面）。
- 全量 `python -m pytest -q` = **1592 基线 + N 新增全绿 / 0 failed / 3 skipped——新增 0 失败**。
- 文档：changelog.md（Developer）→ review-report.md（Reviewer）→ test-report.md（Tester）；记忆三件套。

## 3. 行数对照（铁律 2，AST 可执行行口径）

| WP | 内容 | 预估 AST 行 |
|----|------|------------|
| WP-A | database.py（DDL 常量 + ensure + init_db 挂接） | ~10 |
| WP-B | src/tracing.py（原语 5 + 写侧 3 + SQL 2 + 读侧 2 + sanitize） | ~60 |
| WP-C | main.py（中间件块 8 + done 5 处 ~5 + trace 端点 ~13 + import 1） | ~27 |
| WP-D | react.py（advance_phase reason ~6 + 工具 span ~6 + 截断 span ~3 + 调用 ~2） | ~17 |
| WP-E | langgraph_react.py（reason 接收 + span） | ~4 |
| WP-F | engine.py（intent span 2 + retrieval span 2 + 取整余量） | ~8 |
| WP-G | config.py 1 字段（+conftest fixture 5 行不计生产） | ~1 |
| 合计 | | **~127 ≤ 200 ✓** |

测试 ~30 项不计入；conftest fixture 不计入生产行数（module-073 先例）。若实际超 200，按 module-080 先例晒行数对照表 + 申请 `GATE_MAX_MODULE_LINES` 放宽。

## 4. 风险评估

- **BaseHTTPMiddleware contextvar 传播（中，已论证可控）**：spans 埋点全在 `call_next` 之前的请求 task 内设置/读取 contextvar（058 chat_stream timings 正常落库已实证该机制）；新增块必须保持在该位置（AC-34 锁 429 零 span 反向验证位置正确）。风险残留：若未来中间件重构为纯 ASGI，位置语义需复核——记入 changelog 提示。
- **init_request 覆盖顺序（低）**：058 块先生成 trace_id，088 块按 header/自生成覆盖（init_request 幂等重置 dict 全字段）——request_logs/persist 读 contextvar 最终值，两侧 trace_id 恒一致（AC-12 单测锁）。无 header 时 058 块生成的 uuid 被 088 块新 uuid 覆盖，浪费一次 uuid4 无害。
- **fire-and-forget 写入时序（低）**：spans 落库不 await，请求结束瞬间进程退出可能丢尾部 span——与 save_request_log/record_tool_call 同等语义（v1 接受，如实声明）；单测不依赖 task 完成（直接 await _insert_span）。
- **decision 文本隐私（低）**：router reason 是判定原因不含完整 query（073 隐私原则：正常路径截断）；decision 统一截 500；工具 args 不进 spans（tool_call_logs 已有，不重复）。
- **上游伪造 trace_id（低）**：白名单 sanitize；上游权威覆盖自生成是传播语义本身；不做响应回传。
- **agent 端点无意图路由 span（边界，如实声明）**：agent/agent-lg 不调 classify（058 起现状）——其"为什么"由工具 span（phase/守门）+ advance_phase span 承载；验收"父 span 含决策原因"在 agent 链路由 advance_phase span 满足。
- **429 与 /health 零 span（边界）**：块位置在限流短路后（429 不进链路）、/health 早期 return 前——如实声明非缺陷。
- **存量测试零漂移（低）**：conftest 钉 trace_spans_enabled=false → 新埋点首行短路；advance_phase 返回值无存量 is None 断言（已核实 §0.2）；execute_tool_with_log 仅追加旁路调用不改动存量分支。
- **JSON 序列化 started_at（低）**：datetime 由 FastAPI jsonable_encoder 自动 ISO 化，端点直接返回 dict 即可。

## 5. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-058 observability.py + request_logs | **只读复用零 diff（红线）**：get_trace_id/make_trace_id/init_request/TraceIdFilter 原样消费；request_logs 与 spans 同 trace_id 互补（记录式聚合行 ↔ 链路式因果树） |
| module-066/ADR-0017 tool_call_logs | 表结构一字不改（红线）；spans 是其上叠加的因果层（工具 span 与 tool_call_logs 行 1:1 同事件，trace_id 可互查，v1 不做行级 join） |
| module-087 任务抽象（后续底座） | **不抢活**：不建 task 表/父子 Agent 链，trace 根 = 请求（kind=request）；087 落地后可把根 span 换挂 task_id（本表 parent_span_id 结构天然兼容） |
| module-085 可视化看板 | 分工互补：085 窗口聚合（记录式），088 单请求因果树（链路式）；trace 端点 `{code,msg,data}` + fail-open 风格对齐 dashboard 端点；看板页"点请求看链路"入口留后续（done 已带 trace_id） |
| module-068 advance_phase | 返回值从 None → reason 字符串（向后兼容，无存量 is None 断言已核实）；三分支语义零改动 |
| module-083 execute_tool_with_log 二维守门 | 守门拒绝路径记 status=blocked span——越权尝试进链路（审计可见），守门逻辑零改动 |
| module-073 日志隐私 | decision 截断 500、正常路径不含完整 query 原则沿用 |
| module-064 前端先例 | 本模块前端零改动（v1 只出端点），无前端验收项 |
| module-080 反向闭环 | Java 侧零改动（无调用点事实驱动，§0.3）；未来 Java 注入 X-Trace-Id 即接入 |

## 6. 明确不做

- **Java 侧任何改动**（无 Java→Python 调用点，传播做了没链路；`ai-service.base-url` 死配置不顺手接线）
- **前端"点请求看链路"页面 / 085 看板入口**（~150 行前端，v1 验收方向不含 UI，留后续模块）
- **task 表 / 父子 Agent span / 多 Agent 树**（module-087 底座，本模块以 request 为根）
- **verify 异步任务 span**（submit_verify_task 后台 task 不在请求链路埋点面内，v1 不做）
- **W3C traceparent 标准 header / 响应回传 X-Trace-Id**
- **独立 decision_logs 表 / ORM 模型**（一张表一个模型，raw INSERT 对齐 record_tool_call）
- **OpenTelemetry 等重型 tracing 框架 / 新依赖**（058 决策延续：不引入）
- **span 采样 / 清理 / 归档策略**（与 request_logs 同现状：量级小不清理）
- **非流式 chat JSON 响应加 trace_id 字段**（响应 schema 不动）
- **langgraph 预算截断 span / 检索 span 流式 _retrieve 每轮记录**（v1 只 round 0 收尾一处；langgraph 仅继承共享埋点）
- **tool span 与 tool_call_logs 行级 join / span_id 写入 tool_call_logs**（表结构红线）
- **批量缓冲/合并写入**（每 span 即时 INSERT，本地量级无性能问题）
- **新 ADR**（无架构分歧：决策表 = span 模型单表 + 接收方传播，理由与事实依据记录于本 plan 与 changelog）

## 7. 响应契约（GET /ai/observability/trace/{trace_id}，Developer 勿改字段名）

```json
{
  "code": 0, "msg": "success",
  "data": {
    "trace_id": "3f2a...",
    "span_count": 7,
    "tree": {
      "span_id": "a1b2c3d4e5f60718", "parent_span_id": "",
      "name": "/ai/rag/chat", "kind": "request", "identity": "user-1",
      "decision": "", "status": "ok", "duration_ms": 0,
      "started_at": "2026-09-06T12:00:00.123456", "children": [
        {"span_id": "...", "parent_span_id": "a1b2...", "name": "intent_routing",
         "kind": "decision", "identity": "",
         "decision": "intent=knowledge reason=L4 classifier {...}",
         "status": "ok", "duration_ms": 420, "started_at": "...", "children": []},
        {"name": "retrieval", "kind": "retrieval",
         "decision": "mode=hybrid fusion=rrf docs=8", "children": []},
        {"name": "search_knowledge", "kind": "tool",
         "decision": "phase=retrieval", "status": "ok", "duration_ms": 1500, "children": []},
        {"name": "advance_phase", "kind": "decision",
         "decision": "retrieval_hit", "children": []}
      ]
    }
  }
}
```
（trace 不存在 → `{"code": 1, "msg": "trace 不存在"}`；DB 异常 → `{"code": 1, "msg": "trace 查询失败（fail-open）"}`；tree 为列表——正常恰 1 根。）

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~I 拆解 + span 模型/传播方向/埋点面/查询面/SSE 透传 5 大裁定 + DDL 草案 + 响应契约 + 行数对照 + 风险与既有机制关系） | Planner |
