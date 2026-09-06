# 审查报告 — Module-088 链路式观测（trace_id 跨进程传播 + span 树 + 决策级日志）

> Reviewer: 2026-09-06 | 审查对象：`specs/module-088-trace-observability/`（plan.md v1 / acceptance-criteria.md / changelog.md）+ 2 个新增文件（src/tracing.py 225 物理行 / tests/api/test_tracing.py 948 物理行）+ 7 个修改文件（database.py / config.py / main.py / agent/react.py / agent/langgraph_react.py / rag/engine.py / tests/conftest.py）
> 审查方法：全文件通读 + 独立测试复跑（定向 45 项 + tests/{api,agent,core} 797 项 + py_compile 9 文件）+ git diff 逐文件红线甄别 + AST 行数差分机械化复算（HEAD vs 工作树）+ record_span 调用点全库盘点 + 存量测试 `is None` 断言独立 grep（不采信 Developer 声明）+ 偏离 1 专项裁定 + changelog §六 6 项偏离逐条复核

## 1. 审查结论

- **结论：❌ 不通过（NON-PASS）（0 阻塞 / 1 重大 / 2 minor / 2 LOW + 2 备忘）——退回 Developer 补 MAJOR-1（约 2 行埋点 + 1 项测试）后快速复审收口**

MAJOR-1：**AC-20 / plan §1 决策 2 的"chat_stream 侧意图路由 span"缺失且未在 changelog §六声明偏离**。plan §1 决策 2 明文"④ 意图路由 span（**engine.chat + chat_stream 两处**，decision=intent+router reason 原文）"，AC-20 明文"engine.chat **与 main.py chat_stream 路由后各 1 条**"，AC §5 兜底说明亦预期"T1-SSE 仍会产 root + **intent_routing** + retrieval span"——三处互证；但实现仅 engine.py:399 一处，全库盘点 `record_span(` 调用点 **main.py 为 0 处**（`_chat_stream_events` main.py:621-625 自行路由，`intent_result` 含 reason 在作用域内却未记 span）。**后果是确定性的：Tester 按 AC §5 T1（POST /ai/rag/chat/stream）产出的 trace 树 children 只有 [retrieval]，T2 断言"children 含 intent_routing（decision 非空）"必然失败**——主流式入口（前端唯一 RAG 路径）丢失"为什么路由"这一旗舰决策日志。plan §2 WP-F 细则漏列了 chat_stream 半边（仅写 engine.chat L394），Developer 按 WP-F 窄口径实现且未交叉核对决策 2/AC-20，属实现遗漏而非规格矛盾（与偏离 1 的"文档内部矛盾"性质不同）。

除该项外，其余审查面全部成立并经独立复算/复跑证实：中间件集成位置语义（429/health 零 span 双向锁）、两侧 trace_id 同源、fail-open 链完整、advance_phase 返回值零回归（存量无 `is None` 断言 grep 实证）、INSERT/SELECT 全参数化、`_build_tree` 孤儿挂根/多根容忍正确、端点契约与 plan §7 逐字一致、conftest autouse 钉 false、**AST 行数独立差分复算 126 ≤ 200 与 changelog §三逐字一致**、45 项测试 hermetic 且断言实质、红线文件与两表既有 DDL 零 diff。偏离 1 裁定：**改 AC 文档示例（文档修复），不放宽实现白名单**（详见 §3）。

## 2. 重点核查表（协调者指定 10 项）

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **偏离 1 裁定**（AC §5 T1 示例 vs sanitize 白名单） | ✅ 裁定完成 | 见 §3 专节。结论：AC 文档内部矛盾（AC-8 条款 vs §5 示例值），改示例不改实现；实现 tracing.py:36 `_TRACE_ID_RE = re.compile(r"^[0-9a-f-]+$")` + L70-75 严格按 plan §1 决策 3 / AC-8 执行，未放宽（正确） |
| 2 | **中间件集成正确性** | ✅ | 088 块 main.py:246-257，位置实证：429 短路 L239-244 之后、`return await call_next(request)` L259 之前、health 早期 return L225-226 之前——429/health 零 span 双向单测锁（test_tracing.py:799-825）；`sanitize_incoming_trace(header) or make_trace_id()` L252-253 → `init_request(trace_id)` L254（幂等覆盖 058 块 L219-222 生成的 uuid，重置 dict 全字段发生在 call_next 前零计时丢失）→ `state.trace_id` L255 → `begin_request(...)` L256-257（每非 health/非 429 请求恰 1 次，无漏建/多建）。**两侧同源成立**：request_logs 记录在请求结束经 `get_request_stats()` 读同一 contextvar，与 spans 根 span 同值——test_valid_header_propagates_both_sides 断言 `save_mock.call_args[0][0]["trace_id"] == "0123abcd"`（test_tracing.py:738-754）。`identity=resolve_identity(request)` L257 读 L230-235 已注入的 state.user_id/client_ip（src/identity.py:59-72），无重复解析开销问题 |
| 3 | **fail-open 完整性** | ✅ | ① `_insert_span` 全异常 `except Exception as e: logger.warning("request_spans 落库失败（fail-open，不影响主链路）: %s", e)` 不上抛（tracing.py:104-105，文案对齐 record_tool_call react.py:316-317）；fire-and-forget 任务体内无逃逸异常 → 不会产生 "Task exception was never retrieved"；② `_spawn_insert` 无运行 loop `except RuntimeError: pass` 静默放弃（tracing.py:83-88，plan WP-B 钉死语义）；③ 开关关闭：中间件整块 main.py:251 跳过（零 sanitize/零 uuid/零 init_request 覆盖）、`record_span` 首行 return（tracing.py:155-156）、`begin_request` 开关关仍 set `_parent_var` 但不落库（L124-125，plan WP-B 明文授权）；④ 读侧异常由端点层统一 fail-open（main.py:1337-1340），`get_trace_tree` 不吞异常（tracing.py:203-224 docstring 明示 Raises） |
| 4 | **advance_phase 语义零回归** | ✅ | 签名 `-> None` 改 `-> str`（react.py:223）；三分支切换判定逐字不变：① 生成工具 `ctx.phase = "generation"` 后 `return "generation_tool_called"`（L240-241）；② `any()` 改 for 首命中即 return `retrieval_hit:<tool>`（L243-247）——短路语义等价（any 首命中短路 ↔ for 首命中 return）；③ 计数/阈值不变 + `return f"idle_force_rounds={settings.agent_retrieval_max_rounds}"`（L249-253）；未切 `return ""`（L254）。调用方 react.py:558-560 / langgraph_react.py:185-188 均 `reason = advance_phase(...); if reason: record_span(...)`——对返回值仅做空串判定，安全。**存量 `is None` 断言独立 grep 实证为零**：tests/agent/test_agent_phase_fix.py:193-209 与 test_tool_phase_split.py:135-144 调用后仅断言 `ctx.phase`，不接收返回值 |
| 5 | **decision 字段质量** | ✅（检索 span 偏薄记 LOW-2） | 截断：`(decision or "")[:500]`（tracing.py:167）+ test_decision_truncated_to_500（test_tracing.py:314-325）。intent span：`intent={intent} reason={intent_result.get('reason','')[:200]}`（engine.py:399-403）——router reason 原文（短路/L4/L2/工具历史/短句继承）即真"为什么" ✓；位置在 `intent = intent_result.get(...)` L396 之后（偏离 5 的 UnboundLocalError 修复实证，f-string 急切求值教训已消化）且在 realtime 早退 L407-409 之前（realtime 请求亦有 intent span）✓。工具 span：`phase={ctx.phase}` 恒含 + 守门拒绝附原因截 400（react.py:389-394）；三态等价性成立——拒绝路径 result 恒为非空常量（L371/373）、run 异常/tool 不存在 result 恒空（L366/380）→ `blocked if result else "error"` 判定无歧义。advance_phase：reason 枚举即原因 ✓。检索 span：`mode=... fusion=... docs=N`（engine.py:490-494 / 1089-1093）为 plan WP-F 钉死内容逐字实现，但 mode/fusion 是静态配置、docs 是结果计数，"为什么"含量低（改写/HyDE/deadline 收束真因未承载）→ LOW-2 备忘 |
| 6 | **SQL 参数化 + 树构建** | ✅ | `_SQL_INSERT` 10 列全 `:xxx` 绑定零拼接（tracing.py:40-46）；`_SQL_SELECT` 唯一绑定 `:t`（L49-55）；测试双锁（test_insert_sql_fully_parametrized test_tracing.py:339-361 逐列断言绑定参数集 + TestSQLHygiene 894-905 无 f-string/%/写关键字词边界）。`_build_tree`（tracing.py:174-200）纯函数零副作用：孤儿（parent 不在索引）与根（parent=""）同入 roots（L195-199，零丢行）、自引用防护 `parent is not node`（L196）、多根容忍返回列表；children 序 = 输入序（SQL ORDER BY started_at,id）。单测三态覆盖：单根嵌套/孤儿挂根/多根容忍（test_tracing.py:599-622）+ 集成树深断言（L914-947） |
| 7 | **trace 端点** | ✅ | main.py:1326-1346：try/except `logger.warning("trace 查询失败（fail-open）: %s")` → 200 `{"code": 1, "msg": "trace 查询失败（fail-open）"}` 不 500（L1337-1340）；`tree is None` → `{"code": 1, "msg": "trace 不存在"}`（L1341-1342）；成功 `{"code": 0, "msg": "success", "data": {trace_id, span_count, tree}}` 与 plan §7 契约字段名逐字一致（L1343-1346）；`{code,msg,data}` 格式对齐 083 approvals / 085 dashboard 先例。测试 4 项全覆盖（test_tracing.py:657-700：形状/嵌套透传/不存在/异常 fail-open） |
| 8 | **conftest fixture** | ✅ | conftest.py:130-143 `default_trace_spans_disabled`：`@pytest.fixture(autouse=True)` + `monkeypatch.setattr(settings, "trace_spans_enabled", False)`，docstring 对齐 default_mcp_external_disabled 模式；存量 fixture 零改动（git diff --stat tests/ 仅 conftest +14 新增）。存量 1592 项零漂移保证链：autouse 钉 false → 中间件 088 块整块跳过 + 所有 record_span 首行短路 + 45 项存量定点独立复跑 797 passed / 3 skipped 零新增失败实证 |
| 9 | **行数（铁律 2）** | ✅ | Reviewer 独立 AST 差分复算（HEAD vs 工作树，AC §6 节点口径）：tracing.py **79**（新文件全量）/ database.py 189→199 **+10** / config.py 121→122 **+1** / main.py 638→653 **+15** / react.py 218→231 **+13** / langgraph_react.py 160→163 **+3** / engine.py 525→530 **+5** = **126 ≤ 200**，与 changelog §三逐字一致 |
| 10 | **测试质量 + SS 泄漏面** | ✅（1 项 LOW） | 45 项（`grep -c` 实证）全 hermetic：`_FakeSession`/`_FakeResult` 打桩零真实 PG、`_capture_spans` mock `_spawn_insert` 同步捕获不依赖 task 完成、ASGITransport 端点用例不发 lifespan；断言实质（根 span 逐字段 test_tracing.py:274-290、AC-12 双侧同值经 `save_mock.call_args` 实证 L754、SQL 绑定参数集逐列 L354-361、隔离 AC-37 L827-838）。**SS 泄漏面**：生产侧安全——每个可产 span 的请求必经中间件 `begin_request` 重置 `_parent_var`（tracing.py:122-123），contextvar 按 task 拷贝隔离（AC-37 双请求用例锁）；测试侧存在 **LOW-1**：test_begin_request_root_fields（L278）在 test 体作用域（asyncio.run 之外）直接调 begin_request，`_parent_var.set` 落在 pytest 工作线程共享 context 并跨用例存续——当前被双重遏制（其余用例均在各自 asyncio.run 新 context 内 begin_request / 无 trace_id 用例首行跳过），45 项全绿不受影响，但属测试卫生隐患（未来"开 span 不 begin_request"的新用例会挂幽灵父） |

## 3. 偏离 1 专项裁定（协调者指定）

**裁定：改 AC 文档示例（文档修复，推荐路径采纳）；不放宽实现白名单。**

| 项 | 内容 |
|----|------|
| 矛盾本体 | AC §5 T1/T2/T3/T4/T5 示例 header/查询 id `088tester0123456789abcdef0123456789` 含 `t`/`s`/`r`，不在 sanitize 白名单 `[0-9a-f-]`（plan §1 决策 3 / AC-8 钉死）内 → 按 AC-8/AC-39 该 header 必被拒并回退自生成 32 位 hex，T2 按原 id 查询将返回 code 1 "trace 不存在" |
| 实现侧核实 | tracing.py:36 白名单正则 + L70-75（strip+lower、≤64、`_TRACE_ID_RE.match` 失败 → ""→ 中间件回退 `make_trace_id()`）；测试 5 项白名单行为锁（test_tracing.py:209-239）；实现未放宽 ✓（changelog §六-1 如实声明且立场正确） |
| 裁定理由 | ① 白名单是 plan §1 决策 3 钉死的**安全默认**（plan §4"上游伪造 trace_id（低）：白名单 sanitize"）——trace_id 会落库、进日志（TraceIdFilter）、进 SSE done 回显，放宽字符集即扩大注入面，为迁就一个文档示例值削弱安全默认属本末倒置；② 矛盾双方在同一份 AC 文档内部：AC-8 是行为条款、§5 T1 是示例工件，条款优先，修示例零风险；③ Developer 已用纯 hex `0887e57e0123456789abcdef0123456789`（"088tester" 的 leet 同形变体，全字符在白名单内）完成真实 PG 冒烟全链路验证，替换成本为零 |
| 处置建议 | Planner 将 AC §5 T1/T2/T3/T4/T5 中的 `088tester0123456789abcdef0123456789` 统一替换为 `0887e57e0123456789abcdef0123456789`（T6 非法 header 用例保持不变）；实现零改动。归属：文档勘误（Planner 侧），非 Developer 缺陷 |

## 4. AC 覆盖抽查

| AC | 要求 | 结论 | 证据 |
|----|------|------|------|
| AC-20 | engine.chat **与** main.py chat_stream 路由后各 1 条 intent span | ❌ **MAJOR-1** | engine.chat 侧 ✓（engine.py:399-403）；chat_stream 侧 ✗——`_chat_stream_events` main.py:621-625 自行 `router_agent.classify` + `intent = intent_result.get(...)` + `observability.timing("intent", ...)`，全库盘点 main.py `record_span(` 为 **0 处**；changelog §六 6 项偏离未含此项（未声明）；AC §5 兜底说明"T1-SSE 仍会产 root + intent_routing + retrieval span"与 T2 断言"children 含 intent_routing"双重预期落空 |
| AC-23 | 一次请求一条 trace / 根唯一 / 树深 ≥2 / 决策非空 | ✅ | TestOneRequestOneTrace（test_tracing.py:911-947）：全 span 同 trace_id + 根恰 1 + 树深 ≥2 + advance_phase decision 非空 + 零噪音断言 |
| AC-30/31 | done 事件 5 处带 trace_id | ✅ | 3 处 `_build_done_event` 调用点 diff 实证（main.py:570/575/577 区域，签名未改 extra 吸收 `_build_done_event(sources, verified=False, **extra)` L535-538）+ agent/agent-lg dict 直拼 2 处（main.py:793-794 / 871-872）；测试：extra 吸收机制（test_tracing.py:847-853）+ agent 端点端到端 payload==header（L855-885）；agent-lg 直拼与 agent 逐字同构（备忘 B2，无独立用例可接受） |
| AC-33 | 非流式 chat JSON schema 零改动 | ✅ | engine.chat 返回/ChatResponse 零 diff；797 存量复跑含 chat 响应测试全过 |
| AC-34 | health / 429 零 span（位置锁） | ✅ | 中间件位置（§2 #2）+ test_health_zero_span / test_429_zero_span 双向单测（test_tracing.py:799-825） |
| AC-36 | 开关矩阵 ①②③ | ✅（③备忘 B1） | ① test_disabled_058_behavior_verbatim（L770-783：零根 span + 058 自生成逐字）② test_matrix_spans_on_logs_off（L785-797）；③ 双双 false 无显式用例（①②组合平凡，非阻塞） |
| AC-41/42 | 存量测试零改动 / conftest 仅新增 fixture | ✅ | git diff --stat tests/ 仅 conftest.py +14；797/3 复跑零新增失败 |
| AC-45 | py_compile 全部改动文件 exit 0 | ✅ | 9 文件 COMPILE OK（§7 复跑输出） |

## 5. 问题列表

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/main.py（缺埋点）vs changelog | 621-625（对照 plan §1 决策 2 / AC-20 / AC §5 T1-T2） | **chat_stream 侧 intent_routing span 缺失且未声明偏离**：plan §1 决策 2 明文"engine.chat + chat_stream 两处"、AC-20 明文"各 1 条"、AC §5 兜底说明预期流式链产 intent_routing span；实现仅 engine.py:399 一处，`_chat_stream_events` 的 `intent_result`（含 reason）在作用域内未记 span；changelog §六 6 项偏离未声明此项。**Tester 按 AC §5 T1 流式请求产出的树 children 仅 [retrieval]，T2 断言"children 含 intent_routing（decision 非空）"确定性失败**——主流式入口丢失"为什么路由"决策日志（恰是 roadmap"父 span 含决策原因"的核心展示面）。plan §2 WP-F 细则漏列 chat_stream 半边系 Planner 笔误，但决策 2/AC-20/AC §5 三处互证，属实现遗漏非规格矛盾 | **MAJOR** | 二选一并经协调者确认：**(a) 推荐**——main.py:622 `intent = intent_result.get(...)` 之后补 1 处 `tracing.record_span("intent_routing", "decision", decision=f"intent={intent} reason={intent_result.get('reason', '')[:200]}", duration_ms=int((_t() - t0) * 1000))`（~2 行 + test_tracing 补 1 项流式断言；注意偏离 5 教训：decision 引用的 `intent` 必须在 L622 赋值之后求值）；(b) 不推荐——按偏离收口修订 AC-20/T2 并 changelog §六补声明（削弱主流式入口的决策日志验收） |
| 2 | ai_service/src/tracing.py | 83-88 | `_spawn_insert` 用 `asyncio.create_task(_insert_span(row))` **未保留任务引用**——asyncio 官方文档明示"须保存返回引用，否则任务可能在完成前被 GC"（风险窗口在 await DB I/O 挂起期间）；仓库内 verify_tasks.py:78-79 已认知并修复同问题（"任务引用存入池防 GC"），save_request_log（main.py:332）同模式未留引用。后果：极端时序下静默丢 1 条 span（fail-open 语义内，树少一节点，不崩不挂） | minor | 对齐 verify_tasks 模式加模块级任务引用集（`task.add_done_callback(tasks.discard)`），或在 changelog §五如实声明"与 save_request_log 同等 fire-and-forget 语义，极端时序可能丢尾部 span"为 v1 边界 |
| 3 | specs/module-088-trace-observability/changelog.md | §三 末段 | "0 裸 except（**3 处 except 均带 `as e` + logger** + fail-open/bound 性质注释）✓"与实况不符：tracing.py:87 `except RuntimeError:` **无 `as e` 亦无 logger**（静默 pass）。实现本身正确——plan WP-B 明文钉死"无运行 loop（RuntimeError）静默放弃（fail-open）"，且系窄类型非裸 `except:`——仅 changelog 概括失实 | minor（文档） | changelog 勘误为"3 处 except：2 处 `except Exception as e` + logger.warning fail-open；1 处 `except RuntimeError` 静默放弃（plan WP-B 钉死语义，非裸 except）" |
| 4 | ai_service/tests/api/test_tracing.py | 278 | test_begin_request_root_fields 在 test 体作用域（asyncio.run 之外）直接调 `tracing.begin_request` → `_parent_var.set` 落在 pytest 工作线程共享 context 并跨用例存续（泄漏"幽灵父"）。当前被双重遏制：其余捕获用例均在各自 asyncio.run 新拷贝 context 内 begin_request（task context 拷贝不回写），无 trace_id 用例首行跳过——45 项全绿实证不受影响；但未来若新增"开 span 不 begin_request"用例会挂到幽灵父产生误导断言 | LOW | 该调用包进 `asyncio.run(...)`，或在 conftest fixture  teardown 中 `tracing._parent_var.set("")` 复位 |
| 5 | ai_service/rag/engine.py | 490-494 / 1089-1093 | 检索 span decision=`mode=<静态配置> fusion=<静态配置> docs=<计数>`——"为什么"含量低：多轮反思轮数、HyDE/改写是否生效、预算 deadline 提前收束等真因未承载（对照 intent/tool/advance_phase 三类真含原因）。plan WP-F 钉死该内容且实现逐字一致，**非缺陷**，记决策质量备忘 | LOW（备忘级） | 后续模块可在 decision 追加 `rounds=N rewrite=<mode>` 等真因（decision 截 500 余量充足），无需本轮动作 |
| B1 | ai_service/tests/api/test_tracing.py | — | （备忘）AC-36 矩阵③（request_logs=false + spans=false 双双关）无显式 hermetic 用例（①由 test_disabled_058_behavior_verbatim 覆盖 spans 侧、②test_matrix_spans_on_logs_off 覆盖；③为两者平凡组合） | 备忘 | 可选补 1 项（关闭状态下断言 rows==[] 且 save_mock 未调用），不阻塞 |
| B2 | ai_service/main.py | 871-872 | （备忘）agent-lg done trace_id 直拼点与 agent 侧（main.py:793-794）逐字同构但无独立测试用例（机制由 agent 端点端到端用例 + 代码同构覆盖） | 备忘 | 可接受；如补可复制 test_agent_done_carries_trace_id 改端点路径 |

## 6. 铁律合规检查

| 铁律 | 检查结果 | 证据 |
|------|----------|------|
| #2 新增生产代码 ≤200 行 | ✅ | AST 差分独立复算 **126 ≤ 200**（§2 #9），与 changelog §三逐字一致 |
| #3 方法 ≤50 | ✅（按新增/改写口径） | 新增/改写函数最长 execute_tool_with_log 23 语句（changelog 声明，Reviewer 抽验 diff 结构相符）；`react_loop`(65)/`chat`(93)/`_retrieve`(115) 系 module-088 之前存量超长（本模块各 +2~4 语句旁路埋点，未新增超长函数，changelog §三如实声明） |
| #4 public 函数 docstring | ✅ | sanitize_incoming_trace / begin_request / record_span / get_trace_tree（Args/Returns，get_trace_tree 另含 Raises）/ _build_tree 全齐（tracing.py:58-75/108-121/141-153/203-214/174-185）；端点 get_observability_trace 含 Args/Returns（main.py:1328-1335） |
| #5 禁空 catch / 吞异常 | ✅ | tracing.py 2 处 except：`except Exception as e` + logger.warning fail-open（L104-105）+ `except RuntimeError` 静默放弃（L87，plan WP-B 钉死、窄类型带注释，非裸 except——changelog 概括失实见 minor-3）；main.py 端点 except 带 logger + fail-open 注释（main.py:1337-1338）；grep 全部 088 新增代码 0 处 print |
| #8 日志禁敏感信息 | ✅ | warning 仅记录异常消息 e；decision 不含工具 args/完整 query（工具 args 归 tool_call_logs，router reason 为判定原因文本，module-073 隐私原则沿用） |
| #9 禁 SQL 拼接 | ✅ | `_SQL_INSERT`/`_SQL_SELECT` 纯常量全参数化（§2 #6）；DDL 13 语句纯静态文本（COMMENT 字符串内为全角"；"不干扰 split(";")） |
| #11 记忆收口 | ⏸ 按 NON-PASS 流程 | 仅出本报告 + activity-log [REVIEW] 行；file-index / project-context PASS 状态待 MAJOR-1 收口复审后更新 |

## 7. 独立复跑输出（Reviewer，2026-09-06，不采信 Developer 声明）

```
定向：     .venv/Scripts/python.exe -m pytest tests/api/test_tracing.py -q
           → 45 passed, 2 warnings in 13.33s（与声明一致）
受影响存量：.venv/Scripts/python.exe -m pytest tests/api/ tests/agent/ tests/core/ -q
           → 797 passed, 3 skipped, 5 warnings in 65.89s（与声明一致；3 skip 为存量环境性）
py_compile：src/tracing.py src/database.py src/config.py main.py agent/react.py
           agent/langgraph_react.py rag/engine.py tests/conftest.py tests/api/test_tracing.py
           → COMPILE OK（exit 0）
行数审计：  AST 差分脚本（AC §6 节点口径，HEAD vs 工作树）
           → tracing.py 79 / database 189→199(+10) / config 121→122(+1) / main 638→653(+15)
             / react 218→231(+13) / langgraph 160→163(+3) / engine 525→530(+5) = 126 ≤ 200
红线核验：  git diff --stat -- src/observability.py rag/router.py agent/tool_registry.py
           mcp_server.py requirements.txt backend/ frontend/ → 全空（零 diff）
           git diff -- database.py | grep REQUEST_LOGS_DDL|TOOL_CALL_LOGS_DDL → 零触碰
           git diff --stat -- tests/ → 仅 conftest.py +14（存量测试零改动）
关键 grep： record_span( 全库盘点 → langgraph 1 / react 3（tool/budget/advance_phase）
           / engine 3（intent + chat 检索 + _retrieve 检索）/ main.py 0 ← MAJOR-1 实证
           存量 advance_phase 测试 is None 断言 → 0 处（test_agent_phase_fix:193-209
           / test_tool_phase_split:135-144 只断言 ctx.phase）
未执行项： 全量回归（Tester 的活，预期 1592+45=1637 passed / 0 failed / 3 skipped）、
           真实 PG 对账 T1-T8、uvicorn 冒烟（不启动长驻服务）
```

## 8. 审查总结

### 8.1 成立面（逐项独立证实）
1. **写入侧原语**（src/tracing.py）：sanitize 白名单/begin_request 根 span/record_span 首行短路 + decision 截 500/_spawn_insert fail-open/_insert_span 全参数化 + 全异常 warning，与 plan WP-B 逐条对齐；`_build_tree` 孤儿挂根/自引用防护/多根容忍正确且零丢行。
2. **中间件集成**：088 块位置语义（429 后/call_next 前/health 后）三重单测锁；`init_request` 幂等覆盖使 request_logs 与 request_spans trace_id 恒同源（`save_mock.call_args` 实证）；开关关闭 058 行为逐字（矩阵①测试锁）。
3. **埋点面**：工具 span 三态（ok/blocked/error + 守门原因）经 execute_tool_with_log 单点两循环+MCP 自动继承；advance_phase 返回值语义零回归（三分支逐字 + 存量无 is None 断言 grep 实证）；预算截断 span 仅手写循环（v1 边界如实）。
4. **读侧与传播**：端点 {code,msg,data} 契约与 plan §7 逐字 + fail-open code 1 不 500；SSE done 5 处带 trace_id（签名不改 extra 吸收）。
5. **收口**：126 AST ≤ 200 差分复算一致；45 项测试 hermetic 断言实质；红线零 diff（observability.py/两表 DDL/router/tool_registry/mcp_server/requirements/backend/frontend + 存量测试）；changelog §六偏离 2-6（for 循环取首命中/工具 span 单点合并/_retrieve 计时起点/intent span 位置/45 项测试数）复核全部正当且记录如实。

### 8.2 偏离 1 裁定（结论重申）
AC §5 示例值与 AC-8 白名单系**文档内部矛盾**：**改 AC 示例为纯 hex（`0887e57e0123456789abcdef0123456789`，T1-T5 统一替换），不放宽实现白名单**——白名单是 plan 钉死的安全默认，trace_id 落库/进日志/SSE 回显三处消费面不容扩大注入口径；实现零改动。

### 8.3 结论
**NON-PASS（1 MAJOR / 2 minor / 2 LOW + 2 备忘）**。唯一阻塞路径为 MAJOR-1：chat_stream 侧 intent_routing span 缺失（plan §1 决策 2 + AC-20 + AC §5 T1/T2 三处互证，main.py record_span 盘点为 0），将确定性导致 Tester T2 对账失败；推荐处置 (a)（main.py:622 后补 ~2 行埋点 + 1 项流式测试，注意偏离 5 的 f-string 急切求值教训）。该项收口后其余各面已全部验证成立，复审可快速通过并移交 Tester。

**建议 Tester 重点复核**（MAJOR-1 收口后）：① AC-40 全量回归（预期 1637 passed / 0 failed / 3 skipped 零新增失败）；② AC §5 T1-T8 真实 PG 对账——重点 T2 流式树 children 同时含 intent_routing（decision 含 intent= 与 reason=）与 retrieval（decision 含 mode=）、T3 单 trace 根唯一、T5 request_logs join 同 trace_id；③ T6 非法 header（`<script>alert(1)</script>`）回退 32 位 hex 落库；④ T8 服务重启建表幂等；⑤ 开关矩阵③真实环境（PW_TRACE_SPANS=false 起服）零 span 零落库。Reviewer 环境未启动 uvicorn、未跑全量回归（不越权代跑 Tester 项）。

## 9. 第二轮复审（post-fix，2026-09-06）——✅ 通过（PASS）

> Reviewer 第二轮（格式对齐 module-069 二轮先例）| 范围：一轮 4 项发现（1 MAJOR / 2 minor / 1 LOW）+ 偏离 1 执行的聚焦复验，不重复全量重审（一轮 10 项核查结论维持）
> **结论：✅ PASS（0 阻塞 / 0 重大 / 遗留 1 LOW 备忘 + 2 备忘，全部非阻塞）——移交 Tester**

### 9.1 一轮发现逐项复验

| # | 一轮发现 | 修复内容 | 复验结论 | 证据（文件:行号） |
|---|----------|----------|----------|------------------|
| 1 | **MAJOR-1** chat_stream 侧 intent_routing span 缺失 | main.py `_chat_stream_events` 补 1 处 record_span + 1 项流式测试 | ✅ 成立 | ① **位置正确**：main.py:627-631，在 `intent = intent_result.get(...)`（L622）与 `observability.timing("intent", ...)`（L623）**之后**——f-string 引用的 `intent`/`intent_result` 均已赋值，无 UnboundLocalError 风险（偏离 5 教训已消化，注释明示）；且在 casual_chat 早退（L634）之前——闲聊路径亦有 intent span，与 engine.chat 侧行为一致；② **与 engine.chat 侧同构**：decision 同式 `intent={intent} reason={intent_result.get('reason','')[:200]}` + duration_ms 同式（engine.py:399-403 对照，时钟差 monotonic vs perf_counter 均单调钟语义等价）；③ **测试实质**（test_tracing.py:847-891 `test_chat_stream_intent_routing_span`）：ASGITransport 真 POST /ai/rag/chat/stream 带 header + mock classify（reason="L4 classifier {knowledge: 0.97}"）+ `_retrieve→[]` 无 docs 兜底最轻链——断言 200 + **root 同 header trace_id**（L885）+ **恰 1 条 intent_routing**（L886-887）+ kind=decision + **decision 以 intent=knowledge 开头且含 "L4 classifier" reason 原文**（L889-890）+ **parent_span_id == root span_id 挂根**（L891）——四要素全锁非空跑。全库盘点 main.py record_span 由 0 → 1，AC-20 双路径闭合 |
| 2 | minor-1 `_spawn_insert` 无任务引用池 | 新增模块级 `_pending_tasks` 引用池 | ✅ 成立 | tracing.py:86 `_pending_tasks: set = set()` + L92-96：`task = asyncio.create_task(...)`（引用保存）→ `_pending_tasks.add(task)` → `task.add_done_callback(_pending_tasks.discard)`（完成自清理，**集合不随请求无限增长**）；`except RuntimeError → return` 保留 plan WP-B 钉死的无 loop 静默放弃语义；模式与 verify_tasks.py:78-79 先例同构（含同款防 GC 注释 L84-85） |
| 3 | minor-2 changelog §三 except 概括失实 | 勘误措辞 | ✅ 成立 | changelog §三（L90）改为"0 裸 except——3 处 except 勘误表述（minor-2）：**2 处 `except Exception as e` + logger.warning fail-open**（tracing.py `_insert_span` / main.py trace 端点）+ **1 处 `except RuntimeError` 静默放弃**（tracing.py `_spawn_insert`，plan WP-B 钉死语义，窄类型非裸 except，代码不动）"，与 Reviewer 建议措辞一致；§六补 minor-2 条目（L128）+ §七 v2 变更行（L139）记录修复轮全过程 |
| 4 | LOW-3 test 体作用域 `_parent_var` 泄漏 | begin_request 直调包进 asyncio.run | ✅ 成立 | test_tracing.py test_begin_request_root_fields：`sid = tracing.begin_request(...)` 移入 `async def run()` 内经 `asyncio.run(run())` 执行——`_parent_var.set` 落在 task 上下文拷贝，不再写入 pytest 工作线程共享 context；注释明示修复动机；`parent == sid` 断言语义保持（task 上下文内取值） |
| 5 | **偏离 1 执行**（AC 示例 vs 白名单） | AC §5 示例值换纯 hex | ✅ 成立 | AC §5 T1/T2/T3/T4/T5 六处（T1 curl header / T2 curl 查询 / T3-T5 SQL 字面量）`088tester...` 已全部替换为 `0887e57e0123456789abcdef0123456789`（grep 实证 `088tester` 零残留）；**T6 非法用例未动**（L84 仍为 `<script>alert(1)</script>` 回退口径）；**实现白名单零改动**（tracing.py:36 `_TRACE_ID_RE = re.compile(r"^[0-9a-f-]+$")` 原样）——裁定"改文档不改实现"如实落地 |

### 9.2 独立复跑输出（第二轮，2026-09-06）

```
定向：     pytest tests/api/test_tracing.py -q   → 46 passed, 2 warnings in 15.16s（45+1 新增流式用例）
受影响存量：pytest tests/api/ tests/agent/ tests/core/ -q → 798 passed, 3 skipped in 65.51s
           （= 一轮 797 + 新增 1；3 skip 为存量环境性，零新增失败）
py_compile：tracing/database/config/main/react/langgraph_react/engine/conftest/test_tracing → COMPILE OK
行数审计：  AST 差分复算 → tracing.py **82**（79+3：_pending_tasks AnnAssign + add/discard 2 Expr）
           / main.py 638→654（+16：一轮 +15 + 二轮 record_span 1 语句）/ database +10 / config +1
           / react +13 / langgraph +3 / engine +5 → 合计 **130 ≤ 200** ✓
红线核验：  git diff --stat -- observability.py router.py tool_registry.py mcp_server.py
           requirements.txt backend/ frontend/ → 全空（零 diff）；sanitize 白名单 regex 零改动
测试计数：  grep -c test_ → 46（与声明一致）
```

### 9.3 遗留备忘（全部非阻塞，移交 Tester 参考）

| # | 内容 | 处置 |
|---|------|------|
| LOW-2（保留） | 检索 span decision=mode+fusion+docs 系 plan WP-F 钉死内容，"为什么"含量低（改写/HyDE/收束轮数真因未承载） | 后续模块可在 decision 追加真因，本轮不动 |
| B1（保留） | AC-36 矩阵③（双双 false）无显式 hermetic 用例（①②已锁） | 可选补充，不阻塞 |
| B2（保留） | agent-lg done trace_id 直拼与 agent 同构无独立用例 | 可接受（代码同构 + agent 端端到端覆盖） |

### 9.4 第二轮结论

一轮 4 项发现全部修复且经独立复验成立，偏离 1 按裁定执行（改文档不改实现）。**module-088 审查通过（PASS）**——生产行数 130 AST ≤ 200、定向 46/46 + 受影响存量 798/3 零新增失败、红线零 diff、AST 复算与声明一致。**移交 Tester**：① AC-40 全量回归（预期 **1592 + 46 = 1638 passed / 0 failed / 3 skipped** 零新增失败）；② AC §5 T1-T8 真实 PG 对账（**注意：T1-T5 示例 id 已改纯 hex `0887e57e0123456789abcdef0123456789`，T6 非法用例保持不变**）——重点 T2 流式树 children 同时含 intent_routing（decision 含 intent= 与 L4/短路等 reason 原文）与 retrieval（decision 含 mode=）、T3 单 trace 根唯一、T5 request_logs join 同 trace_id；③ uvicorn 冒烟带 header + T8 重启幂等；④ 开关矩阵③（PW_TRACE_SPANS=false）零 span 零落库真实环境验证。
