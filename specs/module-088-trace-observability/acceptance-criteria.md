# 验收标准 — Module-088: 链路式观测（trace_id 跨进程传播 + span 树 + 决策级日志）

> 依据：`plan.md` v1（2026-09-06）| 验收口径：全量 **1592 passed / 0 failed / 3 skipped** 基线，**新增 0 失败、存量测试零改动** 红线
> roadmap 验收方向：**一次请求对应一条 trace，父 span 含决策原因**

## 1. 功能验收

### 1.1 span 存储与写侧原语（WP-A database.py / WP-B src/tracing.py）
- [ ] AC-1 `REQUEST_SPANS_DDL` 存在且与 plan §2 WP-A 草案列一致（trace_id/span_id/parent_span_id/name/kind/identity/decision/status/duration_ms/started_at）+ `CREATE INDEX IF NOT EXISTS idx_request_spans_trace`；`ensure_request_spans_table()` 按 `DDL.split(";")` 拆分执行（对齐 request_logs 模式）；`init_db` 挂接
- [ ] AC-2 **建表幂等**：`ensure_request_spans_table()` 二次执行不报错（Tester 真实 PG 验证；单测以 SQL 文本断言 `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`）
- [ ] AC-3 **红线（git diff 核验）**：`REQUEST_LOGS_DDL` / `TOOL_CALL_LOGS_DDL` 一字不改；`src/observability.py` **零 diff**；`router.py` / `tool_registry.py` / `mcp_server.py` / `requirements.txt` / `frontend/` 零 diff
- [ ] AC-4 `trace_spans_enabled=False` → `begin_request`/`record_span` 零落库（`_spawn_insert` 不被调用；`record_span` 首行 return）
- [ ] AC-5 `record_span` 无 trace 上下文（`get_trace_id()==""`）→ 静默跳过不落库不报错
- [ ] AC-6 `_insert_span` fail-open：session 抛异常 → `logger.warning("request_spans 落库失败（fail-open...）")`，**不上抛**
- [ ] AC-7 `_SQL_INSERT` 10 列全参数化（`:xxx` 绑定，grep 无 f-string/`%`/`+` 拼 SQL）；`started_at` 由 Python 侧 `datetime.utcnow()` 传入（非 DB default）
- [ ] AC-8 `sanitize_incoming_trace`：合法 hex（≤64）→ 原样（大写归一小写）；超 64 / 空串 / None / 含白名单外字符（如 `g`、`/`、空格）→ `""`
- [ ] AC-9 `begin_request` 根 span 字段：kind=request、parent_span_id=""、status=ok、duration_ms=0、identity 透传；返回 span_id 并写入 `_parent_var`，后续 `record_span` 行的 parent_span_id == 该值

### 1.2 trace_id 跨进程传播（WP-C main.py 中间件）
- [ ] AC-10 请求带合法 `X-Trace-Id: 0123abcd`（ASGITransport）→ `request.state.trace_id == "0123abcd"` 且 observability contextvar 同值（根 span trace_id == header 值）
- [ ] AC-11 无 header / 非法 header（如 `../evil`、超 64 串）→ 自生成 uuid hex（32 位小写，058 行为兜底零回归）
- [ ] AC-12 **两侧同 trace**：`request_logs_enabled=True` + spans 开启时，request_logs 落库行的 trace_id 与 request_spans 行的 trace_id **同值**（088 块 init_request 幂等覆盖 058 块的顺序保证——单测锁定）
- [ ] AC-13 `trace_spans_enabled=False` → 中间件跳过整个 088 块：无根 span、state.trace_id / contextvar 行为与 058 现状逐字一致（存量 test_observability 全过佐证）
- [ ] AC-14 **Java 侧零改动**：`backend/` 目录 git diff 为空（plan §0.3 事实：无 Java→Python 调用点，传播为入站接收）

### 1.3 埋点面（WP-D react.py / WP-E langgraph / WP-F engine.py）
- [ ] AC-15 `advance_phase` 返回 reason 枚举：生成工具切换 → `"generation_tool_called"`；检索命中 → 以 `"retrieval_hit"` 开头；防空转强制切 → `"idle_force_rounds=3"`（值取 settings）；未切换 → `""`；三分支切换语义（ctx.phase 变化）与存量逐字一致
- [ ] AC-16 两循环（react_loop / langgraph_react_loop）advance_phase 切换时（reason 非空）各记 1 条 span：name="advance_phase"、kind="decision"、decision==reason；reason=="" 零 span
- [ ] AC-17 `execute_tool_with_log` 每次调用记 1 条工具 span：name=工具名、kind="tool"；正常执行 → status=ok；run 异常 → status=error；守门拒绝（阶段/权限）→ status=**blocked** 且 decision 含拒绝原因；langgraph/MCP 经共享函数自动继承（AC-22）
- [ ] AC-18 工具 span decision 含 `phase=<ctx.phase>`；duration_ms == execute_tool_with_log 实测耗时
- [ ] AC-19 预算截断：`len(allowed) < len(tool_calls)` 时记 1 条 span（name="budget_truncate"、kind="decision"、decision 含 `proposed=N executed=M`）；未截断零 span（仅手写 react_loop，v1 边界）
- [ ] AC-20 意图路由 span：engine.chat 与 main.py chat_stream 路由后各 1 条（name="intent_routing"、kind="decision"），decision 含 `intent=<intent>` 与 router reason 原文（短路/L4 classifier/L2 信号确认/工具历史信号/短句继承/保守路由等任一来源）；duration_ms == 意图路由耗时
- [ ] AC-21 检索 span：engine.chat 检索循环结束后 1 条（name="retrieval"、kind="retrieval"），decision 含 `mode=<retrieval_mode>` 与 `docs=<N>`；流式 `_retrieve` 路径 1 条同构
- [ ] AC-22 langgraph_react.py 自身改动仅 reason 接收 + span 记录（~4 行），工具/阶段 span 经共享函数继承；langgraph 存量测试（test_rerank_langgraph 等）零改动全过
- [ ] AC-23 **验收方向终证（集成）**：一次 agent 请求产生的全部 span 同 trace_id、根 span（kind=request）恰 1 个、树深度 ≥2 且 decision 类 span（advance_phase）decision 非空——"一次请求对应一条 trace，父 span 含决策原因"

### 1.4 读侧端点（WP-B/WP-C GET /ai/observability/trace/{trace_id}）
- [ ] AC-24 `GET /ai/observability/trace/<有数据 trace_id>` → 200 `{"code": 0, "msg": "success", "data": {"trace_id", "span_count", "tree"}}`，字段名与 plan §7 契约逐字一致
- [ ] AC-25 树节点字段：span_id/parent_span_id/name/kind/identity/decision/status/duration_ms/started_at/**children**；children 为嵌套数组
- [ ] AC-26 `_build_tree` 纯函数：parent_span_id 为空串或父不存在（孤儿）→ 视为根；children 按 started_at,id 序；单根正常、多根容忍返回列表
- [ ] AC-27 trace 无数据 → `{"code": 1, "msg": "trace 不存在"}`，不 500
- [ ] AC-28 读侧异常 fail-open：`get_trace_tree` 抛异常（mock）→ 200 `{"code": 1, "msg": "trace 查询失败（fail-open）"}` + logger.warning，不 500；SELECT 只读（SQL 文本断言无 INSERT/UPDATE/DELETE）
- [ ] AC-29 端点 `{code, msg, data}` 格式对齐 083 approvals / 085 dashboard 先例

### 1.5 SSE done 透传（WP-C）
- [ ] AC-30 chat_stream done 事件 payload 含 `trace_id`（`_build_done_event` 3 处调用点：verify_async 分支 / 同步 verified 分支 / 无 claims 分支；`_build_done_event` 签名不改，extra 吸收）
- [ ] AC-31 agent / agent-lg done 事件 payload 含 `trace_id`（2 处 dict 直拼点）
- [ ] AC-32 错误路径 bare done（`event: done\ndata: {}`）不带 trace_id——fail-open 边界如实声明（验收为"不崩"）
- [ ] AC-33 非流式 chat JSON 响应 schema 零改动（不加 trace_id 字段，存量 chat 响应测试全过）

## 2. 边界条件验收
- [ ] AC-34 `/ai/health` 与限流 429 请求零 span（088 中间件块位于限流短路之后 / health 早期 return 之前——位置语义反向锁）
- [ ] AC-35 decision 截断 500：超长 reason（>500 字符）落库截断不撑爆不报错
- [ ] AC-36 开关组合矩阵：①request_logs=true + spans=false → request_logs 行为逐字不变；②request_logs=false + spans=true → spans 照常落库（trace_id 由 088 块生成）；③双双 false → 零埋点零落库
- [ ] AC-37 并发隔离：两并发请求（不同 X-Trace-Id）各自 span trace_id 不串（ASGITransport 并发用例或两顺序请求 + contextvar 重置断言）

## 3. 异常场景验收
- [ ] AC-38 **DB 不可用**：span 落库 fail-open（主链路/工具执行不受影响，logger.warning）；trace 端点 fail-open code 1 不 500
- [ ] AC-39 上游注入恶意/超长 X-Trace-Id → sanitize 兜底自生成，请求正常处理不崩

## 4. 非功能验收

### 4.1 向后兼容零回归
- [ ] AC-40 全量 `python -m pytest -q` = **1592 基线 + N 新增全绿 / 0 failed / 3 skipped——新增 0 失败**（预期 passed = 1592 + 新增测试数，Tester 按实际 collect 数对账）
- [ ] AC-41 存量测试零改动：test_observability.py / test_dashboard.py / test_tool_call_logs.py / test_tool_phase_split.py / test_agent_phase_fix.py / test_tool_governance.py / test_tool_retry_dedup.py / test_mcp_client.py 全过（git diff tests/ 仅 conftest 新增 fixture + test_tracing.py 新文件）
- [ ] AC-42 conftest 新增 `default_trace_spans_disabled` autouse fixture（钉 false，docstring 对齐 default_mcp_external_disabled 模式）；存量 fixture 零改动

### 4.2 代码质量验收（铁律）
- [ ] AC-43 生产行数 **AST 口径 ≤200**（预估 ~127：tracing.py ~60 + main.py ~27 + react.py ~17 + database.py ~10 + engine.py ~8 + langgraph ~4 + config 1），changelog 晒逐文件行数对照表
- [ ] AC-44 最长方法 ≤50 行；新增公共函数（sanitize_incoming_trace/begin_request/record_span/get_trace_tree/_build_tree）docstring 齐全；0 print、0 裸 except（fail-open 均 `except Exception as e` + logger）
- [ ] AC-45 py_compile 全部改动文件 exit 0

## 5. Tester 真实对账方案（"数据与落库一致"实质，hermetic 单测的分层补充）

> 前置：真实 PG 可达 + uvicorn 起服（参照 085 Tester 冒烟模式；端口/进程用后杀净）。

| # | 对账项 | 命令 / SQL |
|---|--------|-----------|
| T1 | 带上游 header 发起真实请求（SSE 流式） | `curl -sN -X POST http://127.0.0.1:8001/ai/rag/chat/stream -H "Content-Type: application/json" -H "X-Trace-Id: 0887e57e0123456789abcdef0123456789" -d '{"query":"测试链路","history":[]}'` —— 观察 done 事件 payload 含 `"trace_id": "0887e57e..."` |
| T2 | trace 树端点 | `curl -s "http://127.0.0.1:8001/ai/observability/trace/0887e57e0123456789abcdef0123456789"` —— code=0、span_count≥2、tree 根 kind=request、children 含 intent_routing（decision 非空）与 retrieval（decision 含 mode=） |
| T3 | **一次请求一条 trace** | `SELECT count(*) AS rows, count(DISTINCT trace_id) AS traces, sum(CASE WHEN kind='request' THEN 1 ELSE 0 END) AS roots FROM request_spans WHERE trace_id = '0887e57e0123456789abcdef0123456789';` —— traces=1 且 roots=1 |
| T4 | **父 span 含决策原因** | `SELECT name, kind, decision, status FROM request_spans WHERE trace_id = '0887e57e0123456789abcdef0123456789' AND decision <> '' ORDER BY started_at, id;` —— intent_routing / retrieval 行 decision 非空；agent 请求则 advance_phase 行非空 |
| T5 | 与 request_logs 同 trace | `SELECT r.trace_id, r.endpoint, count(s.id) AS spans FROM request_logs r JOIN request_spans s ON s.trace_id = r.trace_id WHERE r.trace_id = '0887e57e0123456789abcdef0123456789' GROUP BY r.trace_id, r.endpoint;` —— 恰 1 行 request_logs 且 spans≥2 |
| T6 | 非法 header 回退自生成 | `curl -sN -X POST .../chat/stream -H "X-Trace-Id: <script>alert(1)</script>" ...` → 请求正常；`SELECT trace_id FROM request_spans ORDER BY id DESC LIMIT 1` —— trace_id 为 32 位 hex（非注入串） |
| T7 | agent 链路决策 span（可选，LLM 行为性尽力项） | agent 端点一次真实对话后 T3/T4 复跑，tool span（phase=）与 advance_phase span 存在 |
| T8 | 建表幂等 | 服务二次重启（init_db 重复执行）无报错、数据不丢 |

- 真实 LLM 不可用（凭证/网络）时如实标注：T1-SSE 仍会产 root + intent_routing + retrieval（或空 docs 分支）span（fail-open 链不阻断），T4 判定改以"存在 span 且根 span decision 结构正确"为准——与 module-084 Tester 环境受限标注同口径。

## 6. 可运行验证命令表

```bash
# 定向新增（Developer/Reviewer/Tester）
cd ai_service && python -m pytest tests/api/test_tracing.py -v
# 受影响存量定点
python -m pytest tests/api/test_observability.py tests/api/test_dashboard.py tests/agent/test_tool_call_logs.py tests/agent/test_tool_phase_split.py tests/agent/test_agent_phase_fix.py tests/agent/test_tool_governance.py tests/agent/test_tool_retry_dedup.py tests/agent/test_mcp_client.py -q
# 语法
python -m py_compile src/tracing.py src/database.py src/config.py main.py agent/react.py agent/langgraph_react.py rag/engine.py
# AST 行数复核（Reviewer 口径）
python -c "import ast,sys; [print(f, sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Assign,ast.AugAssign,ast.AnnAssign,ast.Expr,ast.Return,ast.If,ast.For,ast.While,ast.With,ast.AsyncWith,ast.Try,ast.Raise,ast.Assert,ast.Import,ast.ImportFrom,ast.Pass,ast.Break,ast.Continue,ast.Delete,ast.Global,ast.Nonlocal)) for n in ast.walk(ast.parse(open(f,encoding='utf-8').read())))) for f in ['src/tracing.py','src/database.py','src/config.py','main.py','agent/react.py','agent/langgraph_react.py','rag/engine.py']]"
# 全量回归（Tester，基线 1592/0/3 零新增失败）
python -m pytest -q
# 真实冒烟（Tester，§5 T1/T2/T6）
uvicorn main:app --port 8001 &  # 或既有启动方式
curl -s "http://127.0.0.1:8001/ai/observability/trace/<trace_id>"
```

## 7. 验收结论

| 角色 | 结论 | 日期 | 签署 |
|------|------|------|------|
| Developer | 自测通过，移交 Reviewer | — | — |
| Reviewer | — | — | — |
| Tester | — | — | — |
