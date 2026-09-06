# 验收标准 — Module-089: 预算账本（任务级 token 预算 + 超预算熔断）

> 依据：`plan.md` v1（2026-09-06）| 验收口径：全量 **1670 passed / 0 failed / 3 skipped** 基线，**新增 0 失败、存量测试零改动** 红线
> roadmap 验收方向：**超预算任务被熔断，成本可控**（阶段 D module-089）
> 命令均在 `ai_service/` 目录执行，解释器 `.venv/Scripts/python.exe`

## 1. 功能验收

### 1.1 预算配置与原语（WP-A config.py / WP-B src/tasks.py）
- [ ] AC-1 `task_budget_token_limit: int = 0` 字段存在（tasks_enabled 之后，默认 0=不限）；env 回退名 **PW_TASK_BUDGET_TOKEN_LIMIT**（文档/plan/AC 全程唯一口径——088 发现-1 教训，严禁写 PW_TASK_BUDGET 等变体）
- [ ] AC-2 `begin_task` 解析 config：config=200 → INSERT 捕获 `budget_token_limit=200` 且 `_budget_limit_var` 同值；config=0（默认）→ INSERT 恒 0（**087 行为逐字**——存量 test_tasks.py 既有 INSERT 断言零改动全过）；开关关时 var 仍 set（无害，对齐 _task_id_var 先例）
- [ ] AC-3 `budget_used()` 汇总口径与 087 收口**逐字同式**（Σ usage 各供应商 prompt+completion；缺键兜 0；空 usage → 0）——预算账 == 收口账的前提
- [ ] AC-4 `budget_exceeded()` 判定：limit ≤ 0 → False；`tasks_enabled=False` → False；`used >= limit` → True（**>= 边界：used == limit 即熔断**）；used < limit → False；**全程零 DB 访问**（纯 ContextVar + usage 快照）
- [ ] AC-5 `set_task_budget(limit)`：正数 → var 更新 + `_spawn(_SQL_BUDGET, ...)`（参数 budget_token_limit=limit、task_id 取 `_task_id_var.get()`）；负数 → no-op 保持原值零 spawn；`_SQL_BUDGET` = `UPDATE tasks SET budget_token_limit = :budget_token_limit WHERE task_id = :task_id`（全参数化，无拼接；docstring 注明 v1 无生产调用方、调用方在 T5——set_memory_write_mode 先例）
- [ ] AC-6 `get_budget_limit()` 默认 0；`_budget_limit_var` ContextVar default 0（请求间天然隔离）

### 1.2 熔断执法（WP-C agent/react.py，双拦截点）
- [ ] AC-7 **工具层熔断**（execute_tool_with_log 首分支）：超限 → `tool.run` 未被调用、返回文本含"熔断"与"module-089"、result_ok=False；既有 span 三态自动产出 `status="blocked"` 且 decision 含熔断文本（**span 代码零改动实证**）；`record_tool_call` 落库照旧（审计可见）
- [ ] AC-8 工具层不触发路径逐字：未超限 / limit=0 → 执行路径与 083/088 现状完全一致（存量 tests/agent/ 套件零改动全过佐证）
- [ ] AC-9 **循环层熔断**（react_loop while 顶部）：超限 → `chat_with_tools` 不再被调（break）→ 既有兜底生成 `reflector.generate_answer` 被调 → done 事件正常产出（**答案保证**）；`budget_break` decision span 落库（decision 含 `used=<n>` 与 `limit=<n>`）+ logger.warning
- [ ] AC-10 循环层不触发路径逐字：未超限 → 零 budget_break span；既有 budget_truncate / advance_phase / tool span 行为不受影响
- [ ] AC-11 langgraph 自动继承：langgraph execute_tools 经共享 `execute_tool_with_log` 超限同样被拒；**agent/langgraph_react.py 零 diff 实证**（git diff 核验空）
- [ ] AC-12 守门重排零回归：预算守门为 if 首分支、既有阶段/权限守门降为 elif 后行为等价——阶段拒绝文本 / 权限拒绝文本 / `allowed_tools` 语义逐字不变（存量 test_tool_phase_split / test_tool_retry_dedup / test_tool_call_logs 锁定）

### 1.3 可观测与状态语义（裁定 4）
- [ ] AC-13 熔断事件通道 = request_spans（budget_break span + 工具 blocked span 复用）；**tasks.status 恒为 087 二值（completed/failed），无新状态值**；finish_task 不因熔断改 error

### 1.4 开关与测试钉桩（WP-D conftest.py）
- [ ] AC-14 conftest 新增 `default_task_budget_unlimited` autouse fixture（`monkeypatch.setattr(settings, "task_budget_token_limit", 0)`，防 OS env 泄漏）；存量 fixture 零改动（git diff tests/ 仅 conftest 纯新增 + test_budget.py 新文件）
- [ ] AC-15 **logs 关边界**：`request_logs_enabled=False` → usage 恒空 → `budget_exceeded()` 恒 False（record_usage 开关短路同源边界，plan §1 决策 8①）
- [ ] AC-16 **执法与 span 解耦**：`trace_spans_enabled=False` → budget_break span 不落（record_span 首行短路）但熔断执法仍生效（超限工具仍被拒）

## 2. 边界条件验收
- [ ] AC-17 **DDL 零改动（089 事实红线）**：TASKS_DDL 与 087 交付逐字一致（14 列，**零 ALTER 零新列**——裁定 2）；REQUEST_LOGS_DDL / TOOL_CALL_LOGS_DDL / REQUEST_SPANS_DDL 一字不改
- [ ] AC-18 **默认零行为变化**：config 默认（0）下生产行为与 module-087 闭环基线逐字——零执法、零 budget_break、零 blocked、tasks.budget_token_limit 恒 0
- [ ] AC-19 finish_task / _SQL_FINISH / get_task_overview **零改动**（overview 透传 budget_token_limit/tokens_used 照旧）；checkpoint 列 089 不触碰（090 预留）
- [ ] AC-20 **收口账 == 预算账**：finish_task 的 tokens_used 与 `budget_used()` 同式同源；used 终值可 > limit（首轮 LLM 放行 + 兜底答案的固有超出——plan §1 决策 6 钉死语义，**如实声明非缺陷**）
- [ ] AC-21 **改动面收口**：main.py / rag/engine.py / agent/langgraph_react.py / agent/tool_registry.py / rag/router.py / mcp_server.py / src/observability.py / src/database.py / src/verify_tasks.py / requirements.txt / frontend/ / backend/ 零 diff；改动面恰为 src/tasks.py / src/config.py / agent/react.py / tests/api/test_budget.py（新）/ tests/conftest.py

## 3. 异常场景验收
- [ ] AC-22 DB 不可用：set_task_budget 的 UPDATE fail-open（`_spawn` → `_run_sql` warning 不上抛）；`budget_exceeded()` 不受 DB 影响（零 DB 访问，AC-4）
- [ ] AC-23 **熔断不炸请求**：超限请求正常走完（兜底答案 + done 事件 + persist 收口 status=completed / error=false），HTTP 200（真实对账 T2 实证）

## 4. 非功能验收
### 4.1 向后兼容零回归
- [ ] AC-24 全量回归：`python -m pytest -q` = **1670 基线 + ~18 新增全绿 / 0 failed / 3 skipped**（预期 ≈1688，新增 0 失败）
- [ ] AC-25 行数：生产代码 AST 合计 **~31 ≤ 200**（plan §3 对照表）；新增函数全部 ≤50 行
- [ ] AC-26 代码质量：新 public 函数（get_budget_limit / budget_used / budget_exceeded / set_task_budget）docstring Args/Returns 齐全；0 print；0 裸 except；react.py 新增分支无新 except

### 4.2 红线总核验
- [ ] AC-27 `git diff --stat` 实证：AC-17/AC-21 清单全空 + tests/ 仅 conftest 纯新增 fixture + 新文件 test_budget.py

## 5. Tester 真实对账方案（"超预算任务被熔断"实质，hermetic 单测的分层补充）

> uvicorn 8010 真实起服（.env 真实凭据；tasks_enabled 默认 true）+ 一次性 asyncpg/psql 只读 SQL；**全部对账走真实驱动层（真实 INSERT/UPDATE + 真实 span 落库），禁止 mock `_spawn` 充数**（087 Tester 发现-1 教训：hermetic mock 测不到驱动序列化）；对账脚本用后即删、探针数据清理（module-085/087/088 先例）。

- **T1 预算配置真实落库（真实驱动层 INSERT 实证）**：.env 写 `PW_TASK_BUDGET_TOKEN_LIMIT=200` 重启 → `curl -s -X POST http://127.0.0.1:8010/ai/rag/chat -H "Content-Type: application/json" -d '{"query":"什么是RAG"}'` → SQL `SELECT task_id, budget_token_limit, tokens_used, status FROM tasks ORDER BY id DESC LIMIT 1` → 新行 **budget_token_limit=200**（begin_task INSERT 写入实证）、tokens_used>0、status=completed
- **T2 超预算熔断真实触发（agent 端点 + 小预算）**：.env 改 `PW_TASK_BUDGET_TOKEN_LIMIT=50` 重启 → `curl -s -X POST http://127.0.0.1:8010/ai/rag/chat/agent -H "Content-Type: application/json" -d '{"query":"什么是RAG"}'` → ① SQL `SELECT name, kind, status, decision FROM request_spans WHERE trace_id='<该请求 trace_id>' AND (name='budget_break' OR status='blocked')` → **≥1 行**（循环层 budget_break decision 含 used=/limit=，或工具层 blocked decision 含熔断文本）；② 同请求 tasks 行 budget_token_limit=50；③ 该请求 request_logs 行 error=false、HTTP 200、答案非空（**兜底生成实证——熔断不炸请求**，AC-23）。注：若首轮 LLM 直答无工具调用（无 budget_break 属正常路径），换检索型 query 重试一次并如实记录
- **T3 零预算零熔断（默认行为逐字，AC-18 实证）**：.env 移除 PW_TASK_BUDGET_TOKEN_LIMIT（或 =0）重启 → 同样 agent 请求 → budget_break / blocked span **零行**、tasks.budget_token_limit=0——与 087 闭环基线行为逐字
- **T4 分桶裁定对账（不加列 + 读侧可得，AC-17/裁定 1 实证）**：① `SELECT column_name FROM information_schema.columns WHERE table_name='tasks'` → 恰 087 DDL 14 列（**零新列**）；② 供应商细分仍可查：对该请求 trace_id 跑 085 `_SQL_COST` 口径 SQL（`jsonb_each(usage)`）→ 供应商桶非空——"分桶走读侧"实证
- **T5 开关关边界（AC-15 同源实证）**：.env 写 `PW_TASK_BUDGET_TOKEN_LIMIT=50` + `PW_TASKS_ENABLED=false` 重启 → agent 请求 → 零熔断（budget_break/blocked 零行）；恢复 `PW_TASKS_ENABLED=true` 还原（**两个变量名逐字，勿写变体**）
- **T6 探针清理与基线还原**：对账一次性脚本用后即删；本模块探针产生的 tasks/request_spans/request_logs 行按 trace_id 精确 DELETE（087 Tester 先例）；.env 终态还原；8010 进程杀净

## 6. 可运行验证命令表

```bash
# 定向新增（Developer/Reviewer/Tester）
cd ai_service && .venv/Scripts/python.exe -m pytest tests/api/test_budget.py -q
# 预期：~18 passed

# 受影响存量定点（存量零改动实证）
.venv/Scripts/python.exe -m pytest tests/api/test_tasks.py tests/api/test_observability.py tests/api/test_tracing.py tests/api/test_main.py tests/agent/ -q
# 预期：全绿零失败（存量测试文件零改动）

# 语法
.venv/Scripts/python.exe -m py_compile src/tasks.py src/config.py agent/react.py tests/conftest.py tests/api/test_budget.py
# 预期：exit 0 无输出

# AST 行数复核（Reviewer 口径，与 plan §3 对照表一致，diff 口径 ~31 ≤ 200）
.venv/Scripts/python.exe -c "import ast,sys; [print(f, sum(isinstance(n,ast.stmt) for n in ast.walk(ast.parse(open(f,encoding='utf-8').read())))) for f in ['src/tasks.py','src/config.py','agent/react.py']]"

# 红线核验（AC-17/AC-21）
git diff --stat -- src/observability.py src/database.py src/verify_tasks.py rag/router.py agent/tool_registry.py mcp_server.py rag/engine.py agent/langgraph_react.py main.py requirements.txt backend/ frontend/
# 预期：输出为空（零 diff）

# 全量回归（Tester，基线 1670/0/3 零新增失败）
.venv/Scripts/python.exe -m pytest -q
# 预期：1670 + ~18 ≈ 1688 passed / 0 failed / 3 skipped

# 真实冒烟 + 对账（Tester，§5 T1~T6）
# uvicorn main:app --port 8010（.env 真实凭据 + PW_TASK_BUDGET_TOKEN_LIMIT 按各 T 步骤）+ §5 SQL 逐条
```

---

## 7. 验收签署

| 角色 | 结论 | 日期 | 签署 |
|------|------|------|------|
| Developer | 自测通过，移交 Reviewer（定向 20/20 + 受影响存量 415 全绿 + 红线零 diff，见 changelog §四） | 2026-09-06 | 编排者接管实现 |
| Reviewer | PASS（0 阻塞 / 0 重大 / 3 LOW + 2 备忘非阻塞），移交 Tester，见 review-report.md | 2026-09-06 | 已签署 |
| Tester | **PASS（AC-1~27 全部通过，四阶段闭环）**——命令表独立复跑全过（定向 20/20 + 存量 415/415 + 全量 1690/0/3 零新增失败）+ T1-T6 真实 PG 对账全过（双拦截点真实熔断 + 熔断不炸请求 + 收口账==预算账逐值精确 + 探针清理还原基线）；3 LOW + 2 备忘属实非阻塞；详见 test-report.md。注：§6 `uvicorn main:app` 实为 `main:app`（文档偏差已申报） | 2026-09-06 | Tester 已签署 |
