# 变更记录 — Module-089: 预算账本（任务级 token 预算 + 超预算熔断）

> Developer: 2026-09-06（编排者接管实现——平台子 agent 派发连续容量故障，经用户授权"直接跑"；Planner 产出为验尸接续恢复的子 agent 成果）| 依据：plan.md v1（WP-A~E + 8 大裁定）+ acceptance-criteria.md（AC-1~27）
> 基线：module-087 闭环后全量 **1670 passed / 0 failed / 3 skipped**——红线：**新增 0 失败、存量测试零改动、observability.py / TASKS_DDL / router.py / tool_registry.py / mcp_server.py / requirements.txt / main.py / engine.py / langgraph_react.py 零 diff**

---

## 一、实现总览（预算执法链路）

```
配置：PW_TASK_BUDGET_TOKEN_LIMIT=<N>（0=不限，默认）
建 task：begin_task 解析 config → _budget_limit_var + tasks.budget_token_limit=N（审计可查）
执法判定：tasks.budget_exceeded() = tasks_enabled 且 limit>0 且 budget_used() >= limit
  （budget_used = Σ usage 各供应商 prompt+completion，与 087 收口逐字同式，零 DB 访问）
双拦截点（均 agent/react.py）：
  ① 工具层 execute_tool_with_log 首分支 → 拒绝执行返回熔断文本（span 复用既有
     三态 status="blocked" + decision 附熔断文本；tool_call_logs result_ok=false 审计）
  ② 循环层 react_loop while 顶部 → budget_break span + warning → break 落入既有
     "预算耗尽兜底生成"（reflector.generate_answer）→ 请求正常 done（答案保证）
覆盖原语：set_task_budget(limit)（负数 no-op；UPDATE tasks.budget_token_limit fail-open）
```

## 二、WP 实现说明

### WP-A config（AC-1）
- `task_budget_token_limit: int = 0`（tasks_enabled 之后）；注释写明 env 唯一口径 **PW_TASK_BUDGET_TOKEN_LIMIT**（088 发现-1 教训：变体名 .env 启动即崩）。默认 0 = 行为与 087 逐字一致。

### WP-B src/tasks.py 原语（AC-2~7，AST +25）
- `_budget_limit_var: ContextVar[int]`（default 0）+ `_SQL_BUDGET`（UPDATE budget_token_limit，无 status 条件——覆盖语义重放安全；无 JSONB 列，087 JSONB 直绑坑不适用但已按规矩全标量绑定）。
- `budget_used()`：`observability.get_request_stats()` 只读快照 → Σ usage prompt+completion（**逐字复用 main.py 收口同款汇总式**——预算账 == 收口账的前提）；缺键兜 0；空 usage → 0。边界：logs 关时 record_usage 短路 → 恒 0（087 同源边界，如实声明）。
- `budget_exceeded()`：`limit <= 0 or not tasks_enabled → False`；否则 `budget_used() >= limit`（到达即熔断，>= 边界）。纯 ContextVar + 快照，**零 DB 访问**。
- `set_task_budget(limit)`：负数 no-op（对齐 set_memory_write_mode）；var 更新 + tasks_enabled 且已建 task 时 `_spawn(_SQL_BUDGET)` fail-open。v1 无生产调用方（调用方 T5），语义单测锁定（087 原语先例第三次沿用）。
- `begin_task` 两行改造：解析 config → `_budget_limit_var.set` → INSERT 参数 `budget_token_limit` 由硬编码 0 改解析值（config 默认 0 时逐字等价）；开关关时 var 仍 set（无害，对齐 _task_id_var 先例）。**finish_task/_SQL_FINISH/get_task_overview 零改动**。

### WP-C agent/react.py 双拦截点（AC-7~12，AST +9）
- import `from src import tasks`（tracing 同款，1 行）。
- **工具层**：`execute_tool_with_log` 既有 if（阶段/权限守门）降为首 elif，其前插入预算首分支（4 行）——超限 → result_ok=False + 熔断文本 + warning；**既有 span 代码零改动**（result 非空 + result_ok=False → status="blocked" + decision 附熔断文本的 088 三态判定自动覆盖）；langgraph 经共享函数自动继承（066 先例），langgraph_react.py 零 diff。
- **循环层**：`react_loop` while 顶部（chat_with_tools 之前）超限 → `budget_break` decision span（decision=`used=<n> limit=<n>`，对齐 budget_truncate 先例）+ warning → **break 落入既有兜底生成**（reflector.generate_answer，:564-575 零改动）→ 请求正常 done。**熔断只断增量成本，不断最终答案**（plan §1 决策 3/6，编排者裁定确认）。
- 非（循环）LLM 调用（engine.chat 单轮/意图路由/reflector 兜底/记忆提取）不熔断——首次调用拦截必空答，单次调用有界，循环才是成本主体（plan 边界声明）。

### WP-D conftest + 测试（AC-14~16，不计生产行数）
- conftest：`default_task_budget_unlimited` autouse（钉 0，防 OS env 泄漏进测试）。
- `tests/api/test_budget.py` **20 项**（plan 预估 ~18，TestPrimitives 拆出 spawn 路径补充 1 + 边界用例 1）：TestConfig 1 / TestPrimitives 8 / TestBeginTask 2 / TestToolGate 3 / TestReactLoopGate 2 / TestSQLHygiene 1 + fixture。
- **开发期实测坑（入档，比 plan 新增两条）**：
  ① **ContextVar 跨 asyncio.run 不继承**——测试 setup 里 set 的预算 var 在另一个 asyncio.run 的被测代码里读不到（每次 run 全新上下文）；预算 var 设置与被测代码必须同一 asyncio.run。工具层/循环层用例第一版 10 failed 的根因。
  ② **set_task_budget 是同步函数，严禁 `asyncio.run()` 包裹**——同步调用先于 run 执行、var 落 pytest 共享上下文（泄漏污染"默认 0"断言），且 None 传给 asyncio.run 直接 ValueError。配套 `_reset_task_context` autouse fixture 每用例后复位三 var（088 LOW-3 的测试侧工程化收敛）。

## 三、行数统计（铁律 2，AST 差分口径 vs HEAD）

| WP | 文件 | AST Δ |
|----|------|-------|
| WP-A | src/config.py | +1 |
| WP-B | src/tasks.py | +25 |
| WP-C | agent/react.py | +9 |
| **合计** | | **+35 ≤ 200 ✓**（plan 预估 ~31，tasks.py 原语 docstring 外实句偏多） |

测试 20 项不计入；新增方法最长 `budget_exceeded` 8 语句 ≤ 50。

## 四、自测结果（2026-09-06，编排者接管 Developer 自测）

| 验证 | 命令 | 结果 |
|------|------|------|
| 定向 | `pytest tests/api/test_budget.py -q` | **20 passed**（12.34s） |
| 受影响存量 | `pytest tests/api/test_tasks.py tests/api/test_observability.py tests/api/test_tracing.py -q` | **94 passed** |
| 受影响存量 | `pytest tests/agent/ tests/api/test_main.py -q` | **321 passed**（含 react 循环面 test_tool_phase_split / test_agent_phase_fix / test_tool_retry_dedup / test_tool_call_logs） |
| py_compile | 4 变更文件 | OK |
| 红线 | git diff observability/database/router/tool_registry/mcp_server/requirements/main/engine/langgraph_react | **全空** |
| 行数 | AST 差分 | +35 ≤ 200 ✓ |
| 全量回归 | 未跑（Tester 活）——预期 ≈1690 = 1670 + 20 | — |

## 五、遗留与声明

- usage 依赖 request_logs_enabled（logs 关 → 预算失效）——087 同源边界，plan 决策 8 声明。
- 循环层首轮 LLM 放行 → used 终值可 > N（固有超出，编排者裁定①"成本可控+答案保证"）。
- 熔断不改 task 终态（裁定②）；T5 父子分账（裁定③）。
- langgraph 循环层不单记 budget_break（工具层已继承，plan 明确不做）。
- **待 Tester**：全量回归 + T1-T6 真实对账（真实驱动层熔断验证——AC §5，禁止 mock 充数）。
