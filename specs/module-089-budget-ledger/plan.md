# 开发计划 — Module-089: 预算账本（任务级 token 预算 + 超预算熔断）

> Planner: 2026-09-06 | 依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 D（任务化底座）module-089 行——"**预算账本：任务级 token/成本预算 + 超预算熔断**"，验收方向"**超预算任务被熔断，成本可控**"
> 范围：预算配置（config 默认 + task 级覆盖原语）+ 预算实时累计（复用 087 usage 累积）+ 超预算熔断（工具层 + 循环层双拦截点）+ 熔断事件可观测（request_spans）；**金额换算、跨任务/全局预算、看板展示、退款/降级模型——全部不做**
> 预算：WP-A/B/C 合计 ~0.5 天 + WP-D 测试 0.5 天 + WP-E 回归 0.5 天 ≈ 1.5 天
> Agent 配置：Developer ×1（纯 Python 栈）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（Developer 勿重复调查）

### 0.1 预算数据底座（087 遗产，直接挂载点）
- **tasks 表双预算列已预留**（`src/database.py:201` TASKS_DDL，089 **一字不改**）：`budget_token_limit INTEGER NOT NULL DEFAULT 0`（COMMENT"0=不限；module-089 熔断账本用"）+ `tokens_used INTEGER NOT NULL DEFAULT 0`。`get_task_overview` 已透传两列（读侧零改动可用）。
- **begin_task 现状**（`src/tasks.py:107-133`）：INSERT 11 绑定列中 `budget_token_limit` **硬编码 0**——089 将其改为 config 解析值（默认 0 = 行为逐字不变）。
- **finish_task 收口**（`src/tasks.py:136-161`）：tokens_used = Σ usage 各供应商 prompt+completion（标量不分桶），`_SQL_FINISH` 不触碰 budget 列——089 零改动。
- **tokens_used 收口口径**（main.py:346-347）：`sum(int(u.get("prompt",0)) + int(u.get("completion",0)) for u in stats.get("usage",{}).values())`——089 预算比较必须**逐字同口径**（否则预算账与收口账对不上）。

### 0.2 实时用量数据源（预算累计的支点，零新增采集）
- **usage 实时按供应商累积**：`llm/client.py` 每次供应商响应返回处调 `_record_usage`（:94→:102 `observability.record_usage(label, usage[0], usage[1])`；调用点 :214/:250/:320/:329/:371/:380/:421 覆盖 openai/claude/deepseek/动态链）→ `src/observability.py:120-127` 写入 `_obs()["usage"]`（每请求 ContextVar，:35）。
- **只读快照**：`observability.get_request_stats()`（observability.py:141-143，返回 `dict(_obs())`）——**089 唯一数据源，只读消费不改 observability.py（红线，087 同款先例）**。
- **边界（如实声明）**：`record_usage` 首行 `if not settings.request_logs_enabled: return`（observability.py:122）→ **logs 关时 usage 恒空 → 预算永不触发**（087 tokens_used 恒 0 同源边界，AC 边界项锁定）。

### 0.3 熔断拦截点（汇聚点已探明）
- **工具层汇聚点 = `agent/react.py:342 execute_tool_with_log`**（083 五闸 + 066 落库 + 088 span 已在此汇聚；module-066"react_loop 与 langgraph 共用防漂移"——**langgraph 经共享函数自动继承，langgraph_react.py 零 diff**）。既有守门结构：`if tool is not None and (not _phase_allows(...) or not in allowed_tools)` → 拒绝文本 + result_ok=False → `elif tool is not None: tool.run`。**拒绝语义可零成本复用**：result 非空 + result_ok=False → 既有 span 三态判定（react.py:392-394）自动产出 `status="blocked"` 且 decision 附拒绝原因（`if not result_ok and result` 分支）——**预算守门无需新增任何 span 代码**。
- **循环层唯一入口 = `react.py:487-490`**：`while tool_count < budget:` 顶部 `client.chat_with_tools(...)` 是循环内 LLM 调用唯一入口；**既有 break 兜底路径**（react.py:564-575）：break → `reflector.generate_answer`（用已收集 docs 兜底生成）→ done——**熔断 break 后用户仍拿到最终答案**（"熔断不炸请求"语义的现成落点）。
- react.py **不在 089 红线清单**（088/083 均改过；089 红线 = tool_registry.py/router.py/observability.py/mcp_server.py 等）。react.py 头部已有 `from src import tracing`（:35），新增 `from src import tasks` 同款。

### 0.4 可观测通道（088 既有设施，零新表）
- `tracing.record_span(name, kind, decision, status, duration_ms)`（src/tracing.py:149，fail-open 写 request_spans，decision 截 500）。
- **既有先例**：`budget_truncate` decision span（react.py:519-522，工具次数预算截断时记录 proposed/executed）——089 循环层熔断 span **对齐该先例**（name=`budget_break`，kind="decision"，decision 含 used/limit 数值）。

### 0.5 基建与测试先例（照抄模式）
- **开关先例**：config.py:162 `tasks_enabled`（注释含 env 唯一口径说明）——089 新字段 `task_budget_token_limit` 紧随其后；**env 变量名 = env_prefix `PW_` + pydantic 字段名 → 唯一口径 `PW_TASK_BUDGET_TOKEN_LIMIT`**（088 发现-1 教训：.env 写错名 extra_forbidden 启动即崩）。
- **覆盖原语先例**：`set_memory_write_mode`/`memory_write_allowed`（src/tasks.py:164-190）——"v1 无生产调用方、语义单测锁定、调用方在 T5"模式经 087 Reviewer/Tester 两轮验收接受；089 `set_task_budget` 照抄该模式。
- **conftest 钉桩先例**：conftest.py:144 `default_tasks_disabled` autouse（monkeypatch.setattr settings）——089 新增 `default_task_budget_unlimited`（钉 0；防开发者机器 OS env `PW_TASK_BUDGET_TOKEN_LIMIT` 泄漏进测试）。
- **测试打桩先例**：mock `src.tasks._spawn` 同步捕获（test_tasks.py `_capture`）；直调 begin_task/set_task_budget 等 ContextVar 入口**必须包 asyncio.run**（088 LOW-3 教训）；ASGITransport 端点/中间件用例（test_observability 模式）。
- **基线**：module-087 闭环后全量 **1670 passed / 0 failed / 3 skipped**（2026-09-06 Tester 实测）——红线：**新增 0 失败、存量测试零改动（tests/ 仅 conftest 纯新增 fixture）**。
- **085 分桶既有口径**（specs/module-085-observability-dashboard/changelog.md §二 WP-A）：`_SQL_COST` 经 `jsonb_each(usage)` 按供应商 token 分桶（读侧聚合，零新列）——**供应商细分数据已可读侧取得，089 无需为分桶加任何列**。

## 1. 关键决策（Planner 裁定）

1. **tokens 分桶裁定：不分桶，预算单位 = 标量 token 总量**（回应 087 plan §8 待澄清 2 与 085 裁定"tokens_used 不分桶，089 定"）。理由：① 熔断执法只需一次标量比较（used vs limit），分桶对执法无用；② 供应商细分已可读侧经 `request_logs.usage` JSONB join 取得（085 `_SQL_COST` 既有口径），加列是重复建设；③ 087 收口 tokens_used 已是标量，预算账与收口账同口径才能对账。**tasks 零新列**（与裁定 3 一致）。**金额换算不做**：无价格配置（085 已核实"成本=token 数不换算金额"），085 changelog 中"金额换算留 module-089"的旧预期由编排者范围锚定明确推翻（"不做金额换算"）。
2. **tasks 表加列裁定：不加列、零 ALTER、零迁移**。`budget_token_limit` + `tokens_used` 双列 087 已预留且足够承载（limit 写入 + used 收口回写）；超预算事件进 request_spans（088 既有表，裁定 4）而非 tasks 新列。**TASKS_DDL 一字不改（089 事实红线）**，无需走 init_db 幂等 ALTER（module-061 先例用不上）。
3. **熔断拦截点裁定：双挂，全部在 react.py（非红线），tool_registry.py 零改动**：① **工具层**——`execute_tool_with_log` 新增首分支（权限/阶段守门之前）：`tasks.budget_exceeded()` 为真 → 拒绝执行返回熔断提示文本（复用既有 blocked 三态 span + decision 附因，**零 span 代码增量**）；langgraph 经共享函数自动继承（066 先例），**langgraph_react.py 零 diff**。② **循环层**——`react_loop` while 顶部（chat_with_tools 之前）：超限 → `break` → **落入既有"预算耗尽兜底生成"**（reflector.generate_answer）→ 请求正常 done——熔断只断增量成本，不断最终答案。**engine.chat 单轮生成 / 意图路由 / reflector 兜底 / 记忆提取等非循环 LLM 调用不熔断**（首次调用拦截=请求必然空答；非循环调用单次有界，循环才是成本主体——边界如实声明）。
4. **熔断可观测 = span 事件 + warning 日志，不改 tasks.status**：工具侧复用既有 span 三态（status="blocked"）；循环侧新增 `budget_break` decision span（decision=`used=<n> limit=<n>`，对齐 budget_truncate 先例）+ `logger.warning`。**不加新 status 值**（087 finish_task 语义 completed/failed 已锁定，加值是语义漂移）；编排者锚定"事件进 spans 或 task 状态标记"二选一，取 spans。
5. **预算配置 = config 默认 + task 级覆盖原语**：① config 新字段 `task_budget_token_limit: int = 0`（**0=不限，默认零行为变化**；env 唯一口径 `PW_TASK_BUDGET_TOKEN_LIMIT`）；② `begin_task` 解析 config → set `_budget_limit_var`（ContextVar[int] default 0）→ INSERT 的 budget_token_limit 参数由硬编码 0 改为解析值（**config 默认 0 时行为逐字不变；审计列落地——tasks.budget_token_limit 可查**）；③ `set_task_budget(limit)` 覆盖原语（set var + fire-and-forget `UPDATE tasks SET budget_token_limit` spawn，fail-open；负数 no-op 对齐 set_memory_write_mode；v1 无生产调用方，调用方在 T5 子任务——原语先例，语义单测锁定）。
6. **熔断语义钉死（AC 与测试的唯一口径）**：从"**已用 ≥ 上限**"之后的**下一次拦截点**开始生效（首轮 LLM 调用不拦——usage 从 0 起算，拦了必然空答）；比较用 `>=`（到达即熔断，防恰等于上限时再烧一轮）；used 计算**逐字复用 087 收口同款汇总式**（§0.1），保证预算账 == 收口账。
7. **main.py 零 diff**：begin_task/finish_task 签名不变（begin_task 内部解析 config）；persist 收口不变；无新端点（task 概览端点 087 已返回 budget_token_limit/tokens_used，够用）；无前端改动。
8. **开关依赖边界如实声明**：① `request_logs_enabled=false` → usage 恒 0 → 预算永不触发（record_usage 短路，087 同源边界）；② `tasks_enabled=false` → limit var 恒 0 + budget_exceeded 显式 gate → 不执法（无 task 即无预算主体）；③ trace_spans 关 → budget_break span 不落（record_span 首行短路，088 既有行为）——熔断执法不依赖 span 开（执法读 ContextVar+usage，与 spans 开关解耦）。

## 2. WP 拆解（含 AC 映射）

### WP-A：config 开关（src/config.py，~1 AST 行）
- `task_budget_token_limit: int = 0` 紧随 tasks_enabled 之后；注释对齐既有开关风格：语义（任务级 token 预算上限，0=不限，module-089 预算账本）、**env 唯一口径 PW_TASK_BUDGET_TOKEN_LIMIT（勿写 PW_TASK_BUDGET/PW_BUDGET_TOKENS——088 发现-1 教训）**。
- **AC 映射**：AC-1。

### WP-B：预算原语（src/tasks.py，~18 AST 行）
- `_budget_limit_var: ContextVar[int]`（default 0，紧随 _memory_write_var）。
- `_SQL_BUDGET`：`UPDATE tasks SET budget_token_limit = :budget_token_limit WHERE task_id = :task_id`（全参数化；不加 status 条件——覆盖语义重放安全）。
- `get_budget_limit() -> int`：返回 `_budget_limit_var.get()`。
- `budget_used() -> int`：`observability.get_request_stats()` → Σ usage 各供应商 prompt+completion（**逐字复用 main.py:346-347 收口同款汇总式**；顶部 `from src import observability` 无循环依赖——observability 仅 import src.config，已核实）。
- `budget_exceeded() -> bool`：`limit = get_budget_limit()`；`limit <= 0 or not settings.tasks_enabled → False`；否则 `budget_used() >= limit`。
- `set_task_budget(limit: int) -> None`：limit < 0 no-op（对齐 set_memory_write_mode 非法值语义）→ set var → `settings.tasks_enabled` 且 `_task_id_var.get()` 非空时 `_spawn(_SQL_BUDGET, ...)`（fire-and-forget fail-open）。docstring 注明：v1 无生产调用方（调用方 T5 子任务），语义单测锁定。
- `begin_task` 微调（既有函数 2 行改造）：函数体前部解析 `budget_limit = int(settings.task_budget_token_limit or 0)` + `_budget_limit_var.set(budget_limit)`（开关关时也 set，无害对齐 _task_id_var 先例）；INSERT 参数 `"budget_token_limit": 0` → `"budget_token_limit": budget_limit`。**finish_task/_SQL_FINISH/get_task_overview 零改动**。
- **AC 映射**：AC-2~7、AC-13。

### WP-C：熔断拦截接线（agent/react.py，~12 AST 行）
- import：`from src import tasks`（tracing import 同款，1 行）。
- **工具层守门**（execute_tool_with_log，既有 if/elif 链首插入 ~4 行）：
  ```python
  if tool is not None and tasks.budget_exceeded():
      result_ok = False
      result = "（任务 token 预算已耗尽，工具执行被熔断，module-089）"
      logger.warning("工具 %s 被任务 token 预算熔断拒绝（module-089）", name)
  elif tool is not None and (not _phase_allows(name, ctx) ...):  # 既有分支降为 elif
  ```
  既有 span 代码零改动（result 非空 + result_ok=False → status="blocked" + decision 附熔断文本，§0.3）。
- **循环层熔断**（react_loop while 顶部、chat_with_tools 之前，~6 行）：
  ```python
  if tasks.budget_exceeded():
      tracing.record_span(
          "budget_break", "decision",
          decision=f"used={tasks.budget_used()} limit={tasks.get_budget_limit()}")
      logger.warning("任务 token 预算耗尽 (used=%d limit=%d)，中断工具循环兜底生成",
                     tasks.budget_used(), tasks.get_budget_limit())
      break  # → 既有兜底生成（reflector.generate_answer，:564-575 零改动）
  ```
- **AC 映射**：AC-8~12。

### WP-D：conftest 钉桩 + 单测（tests/conftest.py + tests/api/test_budget.py 新增，不计生产行数）
- conftest：`default_task_budget_unlimited` autouse fixture（`monkeypatch.setattr(settings, "task_budget_token_limit", 0)`，docstring 对齐 default_tasks_disabled；注明新测试体内显式开启）。
- test_budget.py（~18 项，hermetic，mock `src.tasks._spawn` + asyncio.run 包 ContextVar 直调）：
  - TestConfig（~1）：字段存在、默认 0。
  - TestPrimitives（~8）：budget_used 汇总口径（多供应商/缺键兜 0，与收口同式）/ limit=0 → False / used>=limit → True（>= 边界）/ used<limit → False / tasks_enabled=False → False / set_task_budget 正数生效+UPDATE spawn 参数 / 负数 no-op / get_budget_limit 默认 0。
  - TestBeginTask（~2）：config=200 时 INSERT 捕获 budget_token_limit=200 + var 同值 / config=0（默认）INSERT 恒 0（087 行为逐字）。
  - TestToolGate（~4）：超限 → tool.run 未被调 + result 含"熔断" + result_ok=False + span status="blocked" + decision 含 module-089 文本 / 未超限正常执行 / limit=0 不拦截 / langgraph 共享路径（经 execute_tool_with_log 即覆盖，断言一次即可）。
  - TestReactLoop（~2）：超限 → chat_with_tools 不再被调（break）+ generate_answer 被调 + budget_break span（decision 含 used/limit）/ 未超限正常循环零 budget_break。
  - TestSQLHygiene（~1）：_SQL_BUDGET 参数化无拼接。
- **AC 映射**：AC-14~16。

### WP-E：回归 + 文档收口
- py_compile 4 文件（src/tasks / src/config / agent/react / tests/conftest）；定向 test_budget.py 全绿；受影响存量定点：tests/api/test_tasks.py + test_observability.py + test_tracing.py + tests/agent/（react 循环面：test_tool_phase_split / test_agent_phase_fix / test_tool_retry_dedup / test_tool_call_logs）+ tests/api/test_main.py。
- 全量 `python -m pytest -q` = **1670 基线 + ~18 新增全绿 / 0 failed / 3 skipped——新增 0 失败**（预期 ≈1688）。
- 文档：changelog.md（Developer）→ review-report.md（Reviewer）→ test-report.md（Tester）；记忆三件套。

## 3. 行数对照（铁律 2，AST 可执行行口径）

| WP | 文件 | 预估 AST 行 |
|----|------|------------|
| WP-A | src/config.py（1 字段；注释不计） | ~1 |
| WP-B | src/tasks.py（var 1 + SQL 1 + 四原语 ~13 + begin_task 改造 ~3） | ~18 |
| WP-C | agent/react.py（import 1 + 工具守门 4 + 循环熔断 7） | ~12 |
| 合计 | | **~31 ≤ 200 ✓** |

测试 ~18 项不计入。main.py / rag/engine.py / agent/langgraph_react.py / agent/tool_registry.py / src/observability.py / src/database.py **零改动**（裁定 2/3/7）。若实际超 200，按先例晒行数对照表申请放宽（本轮预估余量极大，不预期触发）。

## 4. 风险评估

- **begin_task INSERT 参数改造回归（低）**：仅 budget_token_limit 一个绑定参数的取值来源变化（硬编码 0 → config 解析值，config 默认 0 时逐字等价）；test_tasks.py 既有 INSERT 断言（budget_token_limit=0）在 conftest 钉 0 下全过——存量零改动实证。
- **execute_tool_with_log 分支重排回归（低，重点复核）**：既有阶段/权限守门 if 降为 elif，预算不超限时短路表达式 `tasks.budget_exceeded()` 为 False → 走原分支，行为逐字；test_tool_retry_dedup / test_tool_phase_split / test_tool_call_logs 存量锁定 + WP-D TestToolGate 反向锁。
- **熔断误触发（低）**：config 默认 0=不限 → 生产默认零执法零行为变化；触发需显式设 env 或 set_task_budget——"开关默认关"的安全侧选择。
- **usage 依赖 request_logs_enabled（中，边界如实声明）**：logs 关时预算失效（usage 恒 0）——087 tokens_used 同源边界，plan §1 决策 8 声明 + AC 边界项锁定；v1 不做独立采集（改 record_usage = 动 observability.py 红线，不值）。
- **循环层检查位于首轮 LLM 之后生效（低，语义钉死）**：首轮调用在 used=0 时放行是设计使然（决策 6）；极端单轮超大盘请求（单次 LLM 超预算数十倍）不在 v1 防护范围（声明）。
- **env 变量名（中，088 教训）**：全文档唯一口径 **PW_TASK_BUDGET_TOKEN_LIMIT**；Tester .env 对账写该名（PW_TASK_BUDGET_TOKEN_LIMIT= 值；空串会启动崩——pydantic bool/int fail-fast，087 发现-2 同类）。
- **ContextVar 测试泄漏（低）**：直调 begin_task/set_task_budget 包 asyncio.run（088 LOW-3 教训）；_budget_limit_var default 0 天然复位。

## 5. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-087 tasks 表/src/tasks.py | **直接挂载点**：budget_token_limit 列启用（INSERT 写 config 解析值 + set_task_budget UPDATE）+ tokens_used 收口口径复用；finish_task/_SQL_FINISH/overview **零改动**；TASKS_DDL 一字不改（裁定 2） |
| module-087 set_memory_write_mode 原语 | set_task_budget 照抄"v1 无生产调用方 + 语义单测锁定 + 调用方 T5"模式（Reviewer/Tester 已接受两次） |
| module-083 execute_tool_with_log 五闸 | 预算守门为**第 4 维守门**（阶段/权限/预算 + tool.run），同汇聚点零结构变化；tool_registry.py 红线零 diff |
| module-088 tracing.record_span/request_spans | 熔断事件通道（budget_break span + 工具 blocked 三态复用）；零新表零新列 |
| module-085 dashboard/cost 口径 | 供应商分桶维持读侧 jsonb_each 聚合（089 不分桶裁定，§1 决策 1）；看板零改动 |
| module-058 observability usage 累积 | 只读消费 get_request_stats()（红线零 diff）；record_usage 短路边界如实声明 |
| module-058/068 工具次数预算（max_agent_tools/阶段预算） | **正交不合并**：次数预算防循环步数失控（既有），089 token 预算防单任务成本失控（新增）；两者独立判断独立 span（budget_truncate vs budget_break） |
| module-090 checkpoint | 零交集（checkpoint 列 089 不触碰） |
| T5/Supervisor 多 Agent 编排 | set_task_budget 生产调用方 + 子任务差异化预算——T5 范畴，v1 只留原语 |

## 6. 明确不做

- **金额换算 / 价格配置**（无价格数据源；085"金额换算留 089"旧预期由编排者范围锚定推翻）
- **跨任务/全局/日级预算、预算汇总报表**（任务级为 v1 唯一粒度）
- **看板/前端展示预算信息**（085 看板零改动；task 概览端点已含两列）
- **tokens 按供应商分桶列**（读侧 join 可得，裁定 1）
- **tasks.status 新增 budget_exceeded 等状态值**（087 语义锁定，裁定 4）
- **engine.chat 单轮/路由/reflector/记忆提取 LLM 调用熔断**（决策 3 边界）
- **langgraph_react.py 循环层单独加检查**（实验端点；工具层经共享函数自动继承，循环层边界声明）
- **独立于 request_logs 的用量采集**（动 observability.py 红线，不值）
- **request_logs/tool_call_logs/request_spans 三表 + TASKS_DDL 任何 ALTER/新列/回填**（裁定 2）
- **退款/重试降级/预算预警（80% 提醒）等花活**
- **新依赖 / 新 ADR**（无架构分歧：决策记录于本 plan）

## 7. 行为契约（熔断语义，Developer 勿改口径）

```
配置：PW_TASK_BUDGET_TOKEN_LIMIT=<N>（0=不限，默认）
建 task：begin_task 解析 config → tasks.budget_token_limit=N（审计可查）+ 上下文 var
执法（两拦截点，均 tasks.budget_exceeded() = used >= N 且 N>0 且 tasks_enabled）：
  ① 工具层 execute_tool_with_log：拒绝执行 → 返回"（任务 token 预算已耗尽，
     工具执行被熔断，module-089）"喂回 LLM；span status=blocked；tool_call_logs
     result_ok=false 照常落库（审计可见）
  ② 循环层 react_loop 顶部：break → 既有兜底生成 → 请求正常 done（答案保证）；
     budget_break span（decision=used=<n> limit=<n>）+ warning
收口：finish_task 照旧（tokens_used = 最终实际用量，可 > N——首轮放行 + 兜底答案
     的固有超出，如实声明）
可观测对账：request_spans 按 trace_id 查 budget_break/blocked span；
     GET /ai/observability/task/{task_id} 返回 budget_token_limit=N + tokens_used
```

## 8. 待澄清（不阻塞开发，Developer 按本 plan 缺省执行）

1. **首轮 LLM 调用不拦导致的固有超出**（used 终值可 > N）：若编排者要求"硬封顶"（连兜底答案都拦、返回错误），需改兜底路径行为——v1 按"成本可控 + 答案保证"缺省执行（决策 3/6）。
2. **预算超限是否应使 task 终态标记 failed**：v1 维持 087 语义（error 参数决定，熔断本身不改 error）——若编排者认为熔断任务应可见 failed，请批示（当前靠 span 审计可见）。
3. **T5 子任务的预算继承/分账语义**（父子任务预算如何分摊）：T5 规划时裁定，v1 parent_task_id 恒 ""。

## 9. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~E 拆解 + 8 大裁定：tokens 不分桶 / tasks 不加列 / 双拦截点挂 react.py / span 事件可观测 / config 默认+覆盖原语 / 熔断语义钉死 / main.py 零 diff / 开关边界声明；行数对照 ~31 ≤ 200；风险 + 既有机制关系 + 待澄清 3 项） | Planner |
