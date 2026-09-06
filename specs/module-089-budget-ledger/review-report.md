# 审查报告 — Module-089 预算账本（任务级 token 预算 + 超预算熔断）

> Reviewer: 2026-09-06 | 审查对象：`specs/module-089-budget-ledger/`（plan.md v1 / acceptance-criteria.md / changelog.md）+ 4 个修改文件（src/config.py / src/tasks.py / agent/react.py / tests/conftest.py）+ 1 个新增文件（tests/api/test_budget.py 332 物理行）
> 审查方法：全文件通读（不只读 diff）+ 独立测试复跑（定向 20 项 + 受影响存量 415 项）+ git diff 逐文件红线甄别 + AST 行数差分机械化复算（HEAD vs 工作树，独立重算不采信声明）+ 与 main.py 收口汇总式逐字对照 + 存量 test_tasks.py 零改动核验。**特别说明：本轮 Developer 为编排者接管实现，对"自审自测"声明全部做了独立复验**（复跑数字见 §8，均与 changelog §四 一致或更精确）

## 1. 审查结论

- **结论：✅ 通过（PASS）（0 阻塞 / 0 重大 / 3 LOW 非阻塞 + 2 备忘）——移交 Tester（全量回归 + T1-T6 真实 PG 对账）**

8 项重点核查全部成立并经独立复算/复跑证实：`budget_exceeded` 四态判定矩阵正确且零 DB 访问（tasks.py:242-245）；`budget_used` 汇总式与 087 收口逐字同式（tasks.py:228-229 对照 main.py:346-347）；双拦截点零漂移（阶段/权限守门 if 降 elif 短路等价 react.py:368-383，088 span 三态代码零改动 react.py:391-403，循环层 break 落入既有兜底生成 react.py:584-595 未改）；begin_task 改造 config=0 时与 087 逐字（存量 test_tasks.py 32 项零改动全过）；红线 12 项 git diff 全空；AST 差分独立复算 **+35 ≤ 200** 与声明逐字一致；20 项测试 hermetic 且断言实质；两个 conftest fixture 的必要性均核实成立。问题仅 3 项 LOW（changelog 统计口径、docstring Args 段、1 项开关关断言缺口）与 2 项备忘（AC-15/AC-16 无专项单测，机制已代码级核验 + Tester 真实对账兜底）。

## 2. 重点核查表（编排者指定 8 项）

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **budget_exceeded 判定矩阵**（limit<=0 / tasks_enabled=False / used>=limit / used<limit 四态）+ 零 DB 访问 | ✅ | tasks.py:242-245——`limit = get_budget_limit()`（纯 ContextVar `_budget_limit_var` tasks.py:37-38）→ `if limit <= 0 or not settings.tasks_enabled: return False` → `return budget_used() >= limit`（>= 边界：used==limit 即 True）。零 DB 访问实证：函数体仅 ContextVar 读 + `budget_used()`（tasks.py:215-229，`observability.get_request_stats()` observability.py:141-143 返回 `dict(_obs())` 内存快照）——无 `_spawn`/`async_session_factory` 触达。四态单测齐：test_budget.py:106-109（limit=0 恒 False）、:111-116（used==limit True）、:118-123（used<limit False）、:125-130（tasks_enabled=False False，且 :129 断言钉桩前提成立） |
| 2 | **budget_used 与 087 收口逐字同式** | ✅ | tasks.py:228-229 `sum(int(u.get("prompt", 0)) + int(u.get("completion", 0)) for u in (stats.get("usage") or {}).values())` 对照 main.py:346-347 `sum(int(u.get("prompt", 0)) + int(u.get("completion", 0)) for u in stats.get("usage", {}).values())`——算术表达式逐字相同；唯一差异是容器访问 `(stats.get("usage") or {})` 比 main.py 的 `stats.get("usage", {})` 多一层 None 防御（usage 为 None 时本式得 0、main.py 式会 AttributeError；observability `_obs()` 恒初始化 usage 为 dict，该分支不可达）——**语义等价且更防御，非口径漂移**。缺键兜 0/空 usage 单测：test_budget.py:88-104 |
| 3 | **双拦截点零漂移** | ✅ | ① 工具层 react.py:368-374 新首分支（超限 → result_ok=False + 熔断文本 + warning）；既有阶段/权限守门降为 elif react.py:375-383——`tasks.budget_exceeded()` 为 False 时 `tool is not None and False` 短路 → elif 条件与原 if 逐字（diff 对照 HEAD 实证仅 `if`→`elif` 一词 + 7 行插入），tool 为 None 时两级短路路径亦逐字等价；② **088 span 三态代码零改动**：react.py:391-403 不在 diff 中，`result` 非空 + `result_ok=False` → `status="blocked"`（:400-402）+ decision 附 `result[:400]` 含 module-089 文本（:398-399）自动覆盖熔断拒绝，`record_tool_call` :392 照常落库；③ **循环层**：react.py:501-507 顶部判定（chat_with_tools :510 之前）→ `break` 落入既有兜底路径 react.py:584-595（`reflector.generate_answer` 调用点零改动，diff 实证）→ done 事件带兜底答案；budget_break span :502-504 对齐 budget_truncate 先例（:539-542 同 kind="decision"）；④ langgraph_react.py 零 diff（红线核验 §8），工具层经共享 `execute_tool_with_log` 自动继承 |
| 4 | **begin_task 改造**（config=0 时与 087 逐字 + 开关关 var 仍 set 无害） | ✅ | tasks.py:133-134 `budget_limit = int(settings.task_budget_token_limit or 0)` + `_budget_limit_var.set(budget_limit)`——set 位于 `if not settings.tasks_enabled` 早退（:135-136）**之前**，开关关时 var 仍 set（无害性：`budget_exceeded` 对 tasks_enabled=False 显式短路 tasks.py:243，var 残值不可能触发执法，对齐 _task_id_var 先例）；INSERT 参数 :140 `"budget_token_limit": budget_limit`——config=0 时与 087 硬编码 0 逐字。**存量零改动实证**：git status 中 tests/api/test_tasks.py 未修改，其 32 项在 conftest 钉 0 下全过（§8 复跑 94 内）；新增 test_config_default_zero_insert_unchanged（test_budget.py:191-202）锁 INSERT 恒 0；config=200 双断言（INSERT 值 + var 同值）：test_budget.py:175-189 |
| 5 | **红线甄别** | ✅ | 逐文件 git diff 实测（§8 输出）：src/observability.py / src/database.py / rag/router.py / agent/tool_registry.py / mcp_server.py / requirements.txt / main.py / rag/engine.py / agent/langgraph_react.py / src/verify_tasks.py 十文件 diff 行数全 0，frontend/ + backend/ 零 diff；TASKS_DDL 双预算列仍在位（database.py:210-211 + COMMENT :226，零 diff）。变更面恰 4 修改 + 1 新增（git status 实证，另有 memory/*.md 与 specs/module-089-budget-ledger/ 系角色产出物非代码） |
| 6 | **铁律**（_SQL_BUDGET 参数化 / 无裸 except / docstring / AST ≤200） | ✅（docstring 1 项 LOW-2） | _SQL_BUDGET tasks.py:79-82 仅 `:budget_token_limit`/`:task_id` 两绑定零拼接（不加 status 条件——覆盖语义重放安全，plan WP-B 逐字），TestSQLHygiene 精确串等断言 test_budget.py:328-332；新代码 0 print、0 裸 except（grep 实测双 0；新函数无任何 try/except，既有 `_run_sql` except Exception+warning tasks.py:113-114 未触碰）；AST 差分独立复算 config 123→124 **+1** / tasks 61→86 **+25** / react 232→241 **+9** = **+35 ≤ 200**（§8，与 changelog §三逐字一致）；新增函数最大 7 语句 ≤50（§8） |
| 7 | **测试质量 + fixture 必要性** | ✅ | 20 项全 hermetic：`_capture_spawn` 同步捕获（test_budget.py:44-49，不依赖 task 完成）、`_patch_usage` 只 mock 读侧快照 :52-56（不 mock 写入侧 record_usage）、`_capture_spans` :63-68、LLM/reflector/record_tool_call 全打桩、零真实 PG/LLM。断言实质：spawn 绑定参数逐键（:162-166）、INSERT 逐键（:187-189）、`tool.run.assert_not_awaited()`（:231）、span status+decision（:232-233）、`chat_with_tools.assert_not_called()`（:303）、done 答案值（:305-306/:318-319）。**default_task_budget_unlimited 必要性成立**（conftest.py:158-169）：防开发者机器 OS env `PW_TASK_BUDGET_TOKEN_LIMIT` 泄漏致预算意外执法（否则 TestBeginTask config=0 用例与全部存量 test_tasks 断言随环境漂移）；**_reset_task_context 必要性成立**（test_budget.py:34-41）：set_task_budget 是同步函数，test 体作用域直调（如 :115/:128/:136/:142）时 `var.set` 落 pytest 共享上下文——不复位则 `test_get_budget_limit_default_zero`（:146-148）等"默认 0"断言按用例序漂移，三 var 全复位（:39-41）是必要防御非冗余 |
| 8 | **AC 覆盖抽查**（AC-4 / AC-7 / AC-9~11 / AC-16） | ✅（2 备忘） | AC-4 判定矩阵：test_budget.py:106-130 四态齐（见 #1）；AC-7 工具层：:218-233（tool.run 未调 + "熔断"/"module-089" 文本 + span blocked + decision 含 089 + record_tool_call 打桩照常路径）；AC-9 循环层：:299-309（chat_with_tools 不再调 + fallback 恰一次 + done="兜底答案" + budget_break decision 含 `used=100`/`limit=100`）；AC-10 负向：:311-319（零 budget_break + 零 fallback + chat_with_tools 恰一次）；AC-16 SQL 卫生：:328-332。**备忘 B1**：acceptance-criteria.md:31 的 AC-16（"trace_spans_enabled=False → span 不落但执法仍生效"）无专项单测——机制已代码级核验（react.py:501-507 执法判定先于/独立于 record_span；budget_exceeded 全程无 tracing 调用），record_span 首行短路系 088 既有行为（tracing.py），Tester T2 真实对账兜底；**备忘 B2**：AC-15（logs 关 → 恒 False）为分段拼合覆盖（空 usage→0 :101-104 + used<limit→False :118-123），无 limit>0+空 usage 直接组合断言——Tester T5 真实对账兜底 |

## 3. AC 覆盖抽查（补充核对）

| AC | 要求 | 结论 | 证据 |
|----|------|------|------|
| AC-1 | config 字段存在、默认 0、env 唯一口径 | ✅ | config.py:169 `task_budget_token_limit: int = 0` 紧随 tasks_enabled（:162）；注释含 `PW_TASK_BUDGET_TOKEN_LIMIT` 唯一口径 + 088 教训警示（:167-168）；全库 grep 无 PW_TASK_BUDGET/PW_BUDGET_TOKENS 变体 |
| AC-5 | set_task_budget 语义 + _SQL_BUDGET 形状 | ✅ | 负数 no-op tasks.py:262-263；正数/0 set var（:264）+ tasks_enabled 且已建 task 才 spawn（:265-267，task_id 取 `_task_id_var.get()`）；docstring 注明 v1 无生产调用方/调用方 T5（:253-254）。测试：正数生效 :132-137、负数 no-op :139-144、spawn 参数 :150-166 |
| AC-6 | get_budget_limit 默认 0 / ContextVar default 0 | ✅ | tasks.py:37-38（default=0）+ :206-212；test_budget.py:146-148 |
| AC-8/AC-12 | 不触发路径逐字 + 守门重排等价 | ✅ | 负向单测 :235-248/:250-261/:311-319 + 存量 tests/agent/（test_tool_phase_split / test_agent_phase_fix / test_tool_retry_dedup / test_tool_call_logs）与 test_main 321 项零改动全过（§8） |
| AC-13 | 熔断不改 task 终态 | ✅ | finish_task/_SQL_FINISH 零改动（tasks.py:149-174/:54-59 不在 diff）；新代码零 status 写入；无新 status 值 |
| AC-14 | conftest 仅纯新增 fixture | ✅ | git diff tests/ 仅 conftest.py +13（default_task_budget_unlimited :158-169，插入于 default_tasks_disabled 与 default_verify_async_disabled 之间，存量 fixture 零触碰）+ 新文件 test_budget.py |
| AC-17~19 | DDL/收口/overview 零改动 | ✅ | database.py/verify_tasks.py 零 diff；TASKS_DDL 14 列原样（database.py:210-211）；finish_task/_SQL_FINISH/get_task_overview 零改动（tasks.py diff 仅新增块 + begin_task 两行） |
| AC-26 | 新 public 函数 docstring Args/Returns 齐全 | ⚠️ LOW-2 | set_task_budget Args/Returns 齐（tasks.py:256-260）；get_budget_limit（:206-212）/ budget_used（:215-229）/ budget_exceeded（:232-241）三个零参函数缺 Args 段——同文件 087 先例 `memory_write_allowed` 有 `Args: 无（…）`（tasks.py:196-198），AC-26 按字母亦要求。逻辑零影响 |
| AC-27 | git diff --stat 红线实证 | ✅ | §8 逐文件输出全 0；git status 变更面恰 4+1 |

## 4. 问题列表

### LOW（3 项，均非阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | specs/module-089-budget-ledger/changelog.md | §二 WP-D / §三 末段 | 测试类拆分计数与实况不符：`TestConfig 1 / TestPrimitives 8 / TestBeginTask 2 / TestToolGate 3 / TestReactLoopGate 2 / TestSQLHygiene 1` 合计 17，与"20 项"总数矛盾——实际 TestPrimitives 为 **11** 项（test_budget.py:88-166，11 个方法），1+11+2+3+2+1=20 才自洽；同段"新增方法最长 `budget_exceeded` 8 语句"与 AST 复算不符（实际最长 `set_task_budget` 7 语句，budget_exceeded 6） | LOW（文档） | changelog 勘误：TestPrimitives 8→11；"最长 budget_exceeded 8 语句"→"最长 set_task_budget 7 语句"。总 20 与 +35 两处关键数字本身正确，无需动 |
| 2 | ai_service/src/tasks.py | 206-212 / 215-229 / 232-241 | 三个零参 public 函数（get_budget_limit / budget_used / budget_exceeded）docstring 缺 Args 段——AC-26 明文"Args/Returns 齐全"，且同文件 087 先例对零参函数写了 `Args: 无（只读当前上下文 _memory_write_var，不修改任何状态）`（tasks.py:196-198）。087 一轮复审曾以 docstring 补齐为修复项，标准应对齐 | LOW | 三函数 docstring 补 `Args:\n    无（只读 …，零 DB 访问/不修改状态）` 一节；逻辑零改动（AST +3 注释外零变化，docstring 不计 AST） |
| 3 | ai_service/tests/api/test_budget.py | 174-202 | AC-2 尾句"开关关时 var 仍 set"无专项断言——TestBeginTask 两例均显式 monkeypatch tasks_enabled=True；087 同款先例有对应用例（test_tasks.py:206 `test_disabled_zero_rows_but_var_set` 断言 _task_id_var 开关关仍 set）。行为本身已代码核验（tasks.py:134 set 在 :135 早退之前）且无害（#4 判定矩阵对 tasks_enabled=False 短路），仅缺回归锁 | LOW | test_budget.py 补 1 项：默认钉桩（tasks_enabled=False）下 begin_task → `tasks.get_budget_limit() == 0` 且零 INSERT spawn；或顺带断言显式 config 正数 + tasks_enabled=False 时 var 同值零 spawn。随 Tester 轮或下轮变更顺手补，不单独打回 |

### 备忘（2 项，非缺陷、留痕）

| # | 主题 | 说明 |
|---|------|------|
| B1 | AC-16（acceptance-criteria 口径：执法与 span 解耦）无专项单测 + 编号引用错位 | test_budget.py 文件头 :14 与 TestSQLHygiene 节标 :322-324 将"SQL 卫生"标注为 AC-16，而 acceptance-criteria.md:31 的 AC-16 实为"trace_spans_enabled=False → span 不落但执法仍生效"，_SQL_BUDGET 参数化在 AC 文档属 AC-5（acceptance-criteria.md:14）——该错位源自 plan.md:96 WP-D"AC 映射：AC-14~16"的粗粒度映射与编排者派发词同款（"AC-16（SQL 卫生）"），非 Developer 单方过错。SQL 卫生断言本身强（精确串等 :330-332）；AC-16 真义的解耦机制已代码级核验（执法判定 react.py:501-507 先于/独立于 record_span，budget_exceeded 零 tracing 调用），record_span 首行短路系 088 既有行为，Tester T2 真实对账兜底。建议文档侧（Planner/编排者）统一 AC 编号引用，勿改代码 |
| B2 | AC-15（logs 关 → budget_exceeded 恒 False）为分段拼合覆盖 | 空 usage→0（test_budget.py:101-104）+ used<limit→False（:118-123）两段各自成立，组合情形（limit>0 + usage 空）无直接断言——机制为平凡推论（0 >= limit 仅当 limit<=0，而 limit>0 时 False）。Tester T5 真实环境对账兜底。可选补 1 项组合用例，不要求 |

## 5. 架构评估

- **分层/依赖方向**：✅ 无新依赖、无循环依赖。src/tasks.py 新原语仅依赖 src.config（顶层）+ src.observability（**函数内延迟导入** tasks.py:225，observability 顶层仅 import src.config——plan §2 WP-B 预先核实，独立复核成立）；agent/react.py 消费方向 `react → tasks` 与既有 `react → tracing`（088 先例 react.py:38）同构。tasks.py 不反向依赖 agent 层。
- **结构零侵入**：✅ execute_tool_with_log 保持"守门 if/elif 链 + 统一计时 + record_tool_call + span 三态"原结构，预算守门为第 4 维插入（083 五闸语义的既有汇聚点）；react_loop 兜底生成路径复用不复制。tasks.py 新增与 087 原语同型（ContextVar + fire-and-forget _spawn + 引用池复用 `_pending_tasks` tasks.py:87-97，088 minor-1 防 GC 先例）。
- **DTO/契约**：✅ 无新端点、无 schema 变更、无前端改动；tasks 表消费既有 budget_token_limit 列（087 预留挂载点），overview 端点透传照旧。
- **ADR**：本次无新 ADR——无新外部依赖、无偏离 plan 的架构决策（3 项待澄清均已由编排者裁定且实现按裁定执行：used 终值可 >N 为固有超出如实声明 changelog §五；熔断不改 task 终态；T5 分账未做）。

## 6. 安全评估

| 项 | 结论 | 说明 |
|----|------|------|
| SQL 注入 | ✅ 通过 | _SQL_BUDGET 全参数化（tasks.py:79-82，仅 :budget_token_limit/:task_id 两绑定，值域 int/uuid hex）；无任何字符串拼接/f-string SQL；TestSQLHygiene 精确串等锁（test_budget.py:328-332） |
| XSS | ✅ 不适用 | 零前端改动（frontend/ 零 diff） |
| 密码/API Key | ✅ 通过 | 无凭据触达；无 .env 改动（本轮未触） |
| 敏感日志 | ✅ 通过 | 新增 2 处 logger.warning 仅含工具名/token 计数（react.py:374/:505-506），无用户数据/凭据 |
| 危险兜底/静默失败 | ✅ 通过 | 新代码无 try/except（不新增吞异常点）；落库走既有 _spawn→_run_sql fail-open（warning 不上抛，AC-22）；执法判定零 DB 零异常面。熔断拒绝文本显式可见（喂回 LLM + span decision + tool_call_logs result_ok=false），非静默 |
| 权限/越权 | ✅ 不适用 | 预算执法为成本控制非鉴权；负数 limit no-op（tasks.py:262-263）+ limit<=0 零执法，无"配置注入放大执法"面 |

## 7. 铁律合规检查

- **铁律 1（读全文件）**：src/tasks.py 293 行、agent/react.py 595 行（两改造函数 + 兜底路径全读）、src/config.py 相关段、tests/conftest.py、tests/api/test_budget.py 332 行全文件通读；main.py 收口式、observability.py 快照/record_usage 短路、test_tasks.py 先例定点核验。
- **铁律 2（行数 ≤200）**：AST 差分独立复算 **+35 ≤ 200**（§8，机械重算非采信声明）；新增函数最大 7 语句 ≤50。
- **SQL 全参数化**：_SQL_BUDGET 两绑定零拼接 ✅。
- **0 裸 except / 0 print**：grep 实测双 0 ✅；新增分支无新 except ✅（AC-26）。
- **public docstring**：4 新函数全有 docstring；Args 段缺 3 处记 LOW-2（Returns 齐全，语义描述充分）。
- **存量测试零改动**：git status 实证 tests/ 仅 conftest.py +13 纯新增 + test_budget.py 新文件；test_tasks.py 等 415 项存量零改动全过 ✅。
- **红线零 diff**：12 项清单逐文件实测全 0 ✅（§8）。

## 8. 独立复跑输出（Reviewer，2026-09-06，不采信 Developer 声明；ai_service 目录，.venv/Scripts/python.exe）

```
1) pytest tests/api/test_budget.py -q
   → 20 passed, 2 warnings in 12.69s                     [= changelog §四 20/20 ✓]

2) pytest tests/api/test_tasks.py tests/api/test_observability.py tests/api/test_tracing.py -q
   → 94 passed, 2 warnings in 13.88s                     [= changelog §四 94 ✓；含 test_tasks 32 存量零改动]

3) pytest tests/agent/ tests/api/test_main.py -q
   → 321 passed, 2 warnings in 50.45s                    [= changelog §四 321 ✓；含 react 循环面四套件]

   受影响存量合计 94+321=415 ✓（与派发基线一致）；不跑全量回归（Tester 活）

4) py_compile src/tasks.py src/config.py agent/react.py tests/conftest.py tests/api/test_budget.py
   → exit 0 无输出                                        [5 文件全过]

5) 红线 git diff 逐文件（diff 行数）：observability.py 0 / database.py 0 / router.py 0 /
   tool_registry.py 0 / mcp_server.py 0 / requirements.txt 0 / main.py 0 / engine.py 0 /
   langgraph_react.py 0 / verify_tasks.py 0 / frontend+backend 0      [全空 ✓]

6) AST 差分独立复算（git show HEAD vs 工作树，ast.stmt 口径）：
   src/config.py  123 → 124   +1
   src/tasks.py    61 →  86  +25
   agent/react.py 232 → 241   +9
   合计 +35 ≤ 200 ✓（与 changelog §三逐字一致）
   新增函数语句数：get_budget_limit 3 / budget_used 5 / budget_exceeded 6 / set_task_budget 7（均 ≤50）
```

## 9. 五轴评分

| 轴 | 分 | 依据 |
|----|----|------|
| 正确性 | 5 | 判定矩阵四态正确 + >= 边界钉死；汇总式与收口逐字同式（对账前提成立）；双拦截点短路等价零漂移（存量 415 全过 + diff 逐行核对）；break 兜底路径复用正确 |
| 完整性 | 4 | AC-1~27 代码侧全落地、编排者 3 项裁定全执行；扣 1 分：AC-2 开关关 var-set 子句、AC-15/AC-16（AC 文档口径）三项无专项单测（机制代码级核验 + Tester 兜底，记 LOW-3/B1/B2） |
| 清晰性 | 4 | 注释带 plan 条款引用（config.py:163-168、react.py:369-371/:496-500）；测试文件头覆盖映射表；扣分点：3 函数缺 Args 段（LOW-2）、test 文件头 AC-16 标注错位（B1） |
| 可维护性 | 5 | 严格复用 087/088 既有型（ContextVar 原语/fire-and-forget 引用池/span 三态/decision span 先例）；零结构变化零新表；开发期两个环境坑（ContextVar 跨 run 不继承、同步 set_task_budget 不可包 asyncio.run）已入档 changelog §二 并工程化为 fixture |
| 安全性 | 5 | SQL 全参数化、无注入面、无敏感日志、无新增吞异常点、fail-open 边界与 plan 声明一致、无配置注入放大面 |

## 10. 审查总结

- **通过**。本轮为编排者接管实现，按派发要求对"自审自测"声明全部独立复验：定向 20/20、受影响存量 415/415、py_compile 5 文件、红线 12 项全空、AST +35 逐文件重算——**全部与 changelog §四 一致，未发现虚报**。实现与 plan v1 的 8 大裁定及 §7 行为契约逐条吻合（含首轮 LLM 放行、used 终值可 >N、熔断不改终态、T5 不做）。
- **给 Tester 的重点测试项**：① 全量回归预期 **1690 passed = 1670 + 20 / 0 failed / 3 skipped**（AC §6 旧预期 ≈1688 系 plan ~18 项估值的陈旧口径，实际 20 项）；② T1 真实落库（budget_token_limit=config 值）；③ T2 熔断真实触发（budget_break/blocked span + 兜底答案 + HTTP 200 + error=false，AC-23）——用检索型 query 保证多轮；④ T3 默认零执法；⑤ T5 开关关边界（`PW_TASKS_ENABLED=false`，变量名逐字）；⑥ 顺带覆盖 Reviewer 无单测的三项：AC-15（logs 关）、AC-16（spans 关执法仍在）、AC-2 开关关 var-set。
- **给 Developer/Planner 的非阻塞勘误**（可随下轮变更顺手处理，不单独打回）：changelog 计数勘误（LOW-1）、3 处 docstring Args 段（LOW-2）、可选补开关关断言（LOW-3）、AC 编号引用错位由文档侧统一（B1）。
- **记忆三件套**已按 PASS 态更新（project-context 089 行 + file-index 089 行 + activity-log [REVIEW]/[HANDOFF] 各 1 行）。
