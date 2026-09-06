# 验收标准 — Module-090: 失败隔离 + checkpoint（子 Agent 失败不连坐 + 长任务断点恢复）

> 依据：`plan.md` v1（2026-09-06）| 验收口径：全量 **1730 passed / 0 failed / 3 skipped** 基线（2026-09-06 module-086 闭环），**新增 0 失败、存量测试零改动** 红线
> roadmap 验收方向：**模拟子失败 → 父任务不失败；重启后续跑不从头**（阶段 D module-090，D 收官片）
> 命令均在 `ai_service/` 目录执行，解释器 `.venv/Scripts/python.exe`；每项 AC 的验证途径标注在条目尾（§6 命令表 / §5 T 系列 / 指定测试类）

## 1. 功能验收

### 1.1 checkpoint 原语（WP-A src/tasks.py）
- [ ] AC-1 `save_checkpoint(task_id, payload)` 同步函数 + 门控：空 task_id → no-op、`tasks_enabled=False` → no-op、**非 dict payload → no-op**（三者零 `_spawn`）——对齐 set_task_budget/set_memory_write_mode 非法值先例（验证：TestSaveCheckpoint 门控 3 项）
- [ ] AC-2 **JSONB 绑定正确（本模块核心，087 真缺陷踩坑面）**：payload dict → `json.dumps(payload, ensure_ascii=False, default=str)` JSON **字符串** → `_spawn(_SQL_SAVE_CHECKPOINT, {"task_id": ..., "checkpoint": <str>})`；捕获参数中 checkpoint 恒为 str 且 json.loads 回读与 payload 逐值相等（含中文 ensure_ascii=False / 嵌套结构 / datetime→default=str）；**绝无 dict 直绑**（验证：TestSaveCheckpoint 绑定断言 + §5 T1 真实驱动终验）
- [ ] AC-3 序列化失败 fail-open：循环引用等 (TypeError, ValueError) → logger.warning + no-op **不炸调用方**（验证：TestSaveCheckpoint）
- [ ] AC-4 `_SQL_SAVE_CHECKPOINT` = `UPDATE tasks SET checkpoint = :checkpoint WHERE task_id = :task_id`（**无 status 条件**——覆盖语义重放安全，对齐 _SQL_BUDGET；全参数化无拼接）；重复保存同 task → 后写覆盖（last-save-wins）幂等可重入（验证：TestSQLHygiene + TestSaveCheckpoint 文本/参数断言）
- [ ] AC-5 `load_checkpoint(task_id) -> dict`（async）：行不存在 → `{}`；JSONB 值 dict 形态（asyncpg 默认解码）直返；str 形态 → json.loads 兜底；解码后非 dict（防御脏数据）→ `{}`；正常 payload 往返与保存值逐值相等（验证：TestLoadCheckpoint）
- [ ] AC-6 load 读侧**不设开关闸**（`tasks_enabled=False` 仍可读——对齐 087 读端点先例）；空 task_id → `{}`；**DB 异常原样上抛**（对齐 get_task_overview，调用方定降级——plan §8 待澄清 2 缺省）（验证：TestLoadCheckpoint + fake session 异常用例）

### 1.2 恢复语义原语（WP-A resume_task，plan 裁定 1/2）
- [ ] AC-7 `resume_task(task_id) -> bool`（async）：failed 行 → **True** 且行变为 `status='running'` + `finished_at=NULL`（checkpoint/trace_id/intent/tokens_used 零触碰）；悬挂 running 行 → True **幂等**（重复调用状态不变仍 True）（验证：TestResumeTask + §5 T2）
- [ ] AC-8 **completed 终态不可复活**：resume on completed → **False 且行零改动**（白名单 `status IN ('failed','running')` 子句逐字）；行不存在 → False；空 task_id / `tasks_enabled=False` → False（验证：TestResumeTask + §5 T4）
- [ ] AC-9 resume **保留 checkpoint**（恢复后 load_checkpoint 仍取到恢复前保存的 payload——"续跑不从头"的数据前提）；`_SQL_RESUME` 文本不含 checkpoint/trace_id/intent/tokens_used 字样（验证：TestResumeTask 文本断言 + §5 T2）
- [ ] AC-10 resume **不改任何 ContextVar**（_task_id_var/_memory_write_var/_budget_limit_var 零触碰——纯行状态原语）；DB 异常上抛（对齐 get_task_overview）（验证：TestResumeTask）

### 1.3 失败隔离语义契约（WP-B TestIsolationContract，plan 裁定 5——零代码补强）
- [ ] AC-11 **SQL 作用域逐字锁定**：`_SQL_FINISH` 含 `WHERE task_id = :task_id` 与 `status = 'running'`；`_SQL_SAVE_CHECKPOINT` / `_SQL_RESUME` / `_SQL_BUDGET` 各含 `WHERE task_id = :task_id`；TASKS_DDL 文本不含 REFERENCES / FOREIGN KEY / CREATE TRIGGER——**子 task 失败无任何 SQL 路径可触父行**（机制 = 087 既有单行作用域 + 无级联约束，本模块新增 SQL 同款沿用）（验证：TestIsolationContract）
- [ ] AC-12 **参数作用域行为**：finish_task(子 id, error=True) → 恰一条 spawn 且参数 task_id == 子 id；save_checkpoint / set_task_budget 同理——调用只作用目标任务行，父行零触达（验证：TestIsolationContract 参数断言 + §5 T3 真实行为）
- [ ] AC-13 **finish 不吞 checkpoint**：`_SQL_FINISH` 文本不含 "checkpoint" 字样（087 收口语义保持——断点进度不因任务收口丢失）（验证：TestIsolationContract）

## 2. 边界条件验收
- [ ] AC-14 **DDL 零改动（红线）**：TASKS_DDL 与 087 交付逐字一致（14 列含 checkpoint JSONB DEFAULT '{}'，零 ALTER 零新列）；REQUEST_LOGS_DDL / TOOL_CALL_LOGS_DDL / REQUEST_SPANS_DDL / CRAWL_CANARIES_DDL 一字不改（验证：§6 红线 git diff + AST/文本核对）
- [ ] AC-15 **默认零行为变化 + 零 config**：config.py 零新增字段、零新开关/新 env 变量；三原语 v1 无生产调用方——存量生产行为与 090 前逐字（089 set_task_budget 同款"原语先行"模式）；存量调用面（begin/finish/persist 收口/端点）零漂移（验证：受影响存量 test_tasks.py + test_budget.py 全绿 + 红线 git diff）
- [ ] AC-16 **既有原语逻辑零改动**：begin_task / finish_task / set_task_budget / get_task_overview / set_memory_write_mode / _spawn / _run_sql 函数体零改动（git diff tasks.py 仅纯追加：import json + 三 SQL 常量 + 三函数）（验证：§6 git diff 核验）
- [ ] AC-17 **改动面收口**：生产改动恰为 src/tasks.py 纯追加；测试恰为 tests/api/test_checkpoint.py（新）；**conftest.py 零 diff**（fixture 本地化）；main.py / src/config.py / src/database.py / src/observability.py / rag/engine.py / agent/react.py / agent/langgraph_react.py / rag/memory/memory.py / rag/router.py / agent/tool_registry.py / mcp_server.py / requirements.txt / frontend/ / backend/ 零 diff（验证：§6 红线 git diff）

## 3. 异常场景验收
- [ ] AC-18 **DB 不可用分层**：save_checkpoint 落库 fail-open（`_spawn` → `_run_sql` warning 不上抛——既有链路）；load_checkpoint / resume_task DB 异常**上抛**（读侧/恢复侧语义，与 get_task_overview 一致——v1 无生产调用方，主链路零影响）；序列化失败 warning no-op（AC-3）（验证：TestSaveCheckpoint/TestLoadCheckpoint/TestResumeTask + fake session 异常用例）
- [ ] AC-19 **无运行事件循环**：save_checkpoint 在无 loop 上下文调用 → `_spawn` RuntimeError 窄捕获静默放弃（既有先例自动覆盖，零新增处理代码）（验证：TestSaveCheckpoint 或既有 _spawn 行为锁定）

## 4. 非功能验收
### 4.1 向后兼容零回归
- [ ] AC-20 全量回归：`python -m pytest -q` = **1730 基线 + ~20 新增全绿 / 0 failed / 3 skipped**（预期 ≈1750，以实际新增数算术自洽为准，**新增 0 失败**）（验证：§6 全量命令）
- [ ] AC-21 行数：生产代码 AST 合计 **~26 ≤ 200**（plan §3 对照表：import 1 + SQL 3 + save 6 + load 10 + resume 6）；新增函数全部 ≤50 语句（验证：§6 AST 复核命令）
- [ ] AC-22 代码质量：新 public 函数（save_checkpoint / load_checkpoint / resume_task）docstring Args/Returns 齐全；0 print；0 裸 except（except 均窄类型 (TypeError, ValueError)）；SQL 全参数化无拼接；模块 docstring 补 090 接管说明（验证：Reviewer 目检 + AST 命令）
- [ ] AC-23 **红线总核验**：`git diff --stat` 实证 AC-14/AC-17 清单全空 + tests/ 仅新增 test_checkpoint.py（conftest.py 零 diff）（验证：§6 红线命令）

## 5. Tester 真实对账方案（roadmap 验收方向实质，hermetic 单测的分层补充）

> **核心两条：模拟子失败 → 父任务不失败（T3）；写 checkpoint → 进程内"重启"模拟 → load 恢复不从头（T2）。** 全部对账走真实驱动层（真实 PG INSERT/UPDATE/SELECT），**禁止 mock `_spawn`/fake session 充数**（087 Tester 发现-1 教训：hermetic mock 测不到驱动序列化——本模块 JSONB 绑定坑正是 mock 测不出的）。载体：一次性 asyncpg 脚本（`asyncio.run`，解释器 .venv/Scripts/python.exe；tasks_enabled 默认 true 直连 .env 真实凭据），无需 uvicorn 起服（三原语不经 HTTP）；脚本用后即删、探针行精确清理（module-085/087/088/089 先例）。
> **"进程内重启模拟"定义（T2 硬性口径）**：保存 checkpoint 与恢复 load 必须处于**不同 asyncio.run 上下文**（推荐独立子进程脚本，次选同脚本内第二次 asyncio.run）——ContextVar 跨 asyncio.run 天然归零（089 实测坑①），恢复只能来自 DB 而非内存；**同一 asyncio.run 内 save→load 不算数**。

- **T1 checkpoint 真实落库往返（真实驱动层 JSONB 写读实证，AC-2 终验）**：脚本内 `begin_task(trace_id=<一次性 32hex>, endpoint="/ai/rag/chat")` 真实 INSERT（等待落库，轮询 `SELECT status FROM tasks WHERE task_id=...` 至 running）→ `save_checkpoint(task_id, {"step": 5, "done": ["检索", "改写"], "ts": datetime.utcnow()})` → 轮询后 SQL `SELECT checkpoint FROM tasks WHERE task_id='<id>'` → **逐值等于 payload**（step=5 / done 两元素中文无损 / ts 为 ISO 字符串）——asyncpg 驱动 JSONB 写读双向实证
- **T2 断点恢复不从头（核心验收 ①，AC-7/9 实质）**：T1 基础上 `finish_task(task_id, error=True)` → SQL 确认 `status='failed'` → **新"进程"**（独立子进程或新 asyncio.run，口径见上）→ `resume_task(task_id)` 返回 **True** → SQL 确认 `status='running' AND finished_at IS NULL` → `load_checkpoint(task_id)` == T1 payload 逐值（**跨会话从 DB 恢复非内存——续跑起点 = checkpoint 内容而非从头**）→ 续跑模拟：`save_checkpoint(task_id, {"step": 6})` 覆盖 → `finish_task(task_id)` 正常收口 → SQL 确认 completed
- **T3 模拟子失败父不连坐（核心验收 ②，AC-11/12 实质）**：真实 PG 建父行（begin_task）+ 子行（测试侧直接 INSERT，parent_task_id=父 id，复用 _SQL_INSERT 同款参数化）→ `finish_task(子 id, error=True)` → SQL 断言：**子行 status='failed' 且父行逐列不变**（status='running' / finished_at IS NULL / tokens_used=0 / checkpoint='{}'）→ 再 `finish_task(父 id)`（error=false）→ **父行 completed 而子行保持 failed**——"子失败父不失败、父收口不改子终态"双向隔离实证
- **T4 幂等与边界（AC-4/8 实质）**：同 payload save×2 → 列值一致；不同 payload save×2 → 后写生效；resume×2 幂等（两次 True、状态不变）；resume on completed 行 → **False 且行逐列不变**；`load_checkpoint('不存在id')` → {}
- **T5 开关关边界（AC-1/6 实质）**：`PW_TASKS_ENABLED=false` 环境下（脚本 monkeypatch settings 或 OS env 重启脚本）→ save/resume no-op（零 SQL 变更 / resume False）；load 仍可读 T2 遗留行（读侧不设闸实证）——变量名逐字 **PW_TASKS_ENABLED**（勿写变体，088 发现-1 教训）
- **T6 探针清理与基线还原**：一次性脚本用后即删；本模块探针产生的 tasks 行按 task_id 精确 DELETE（087 Tester 先例）；.env 终态还原（本模块理想零改动）；若有 8010 占用杀净；清理后 `SELECT COUNT(*) FROM tasks WHERE task_id IN (<探针ids>)` = 0

## 6. 可运行验证命令表

```bash
# 定向新增（Developer/Reviewer/Tester）
cd ai_service && .venv/Scripts/python.exe -m pytest tests/api/test_checkpoint.py -q
# 预期：~20 passed

# 受影响存量定点（存量零改动实证：087/089 语义未漂移）
.venv/Scripts/python.exe -m pytest tests/api/test_tasks.py tests/api/test_budget.py -q
# 预期：全绿零失败（存量测试文件零改动）

# 语法
.venv/Scripts/python.exe -m py_compile src/tasks.py tests/api/test_checkpoint.py
# 预期：exit 0 无输出

# AST 行数复核（Reviewer 口径，与 plan §3 对照表一致，~26 ≤ 200）
.venv/Scripts/python.exe -c "import ast; print(sum(isinstance(n, ast.stmt) for n in ast.walk(ast.parse(open('src/tasks.py', encoding='utf-8').read()))))"
# 预期：tasks.py 全文语句数与 changelog §三声明一致（本模块纯追加 ~26）

# 红线核验（AC-14/AC-17/AC-23）
git diff --stat -- src/config.py src/database.py src/observability.py src/verify_tasks.py main.py rag/engine.py agent/react.py agent/langgraph_react.py rag/memory/memory.py rag/router.py agent/tool_registry.py mcp_server.py requirements.txt backend/ frontend/ tests/conftest.py
# 预期：输出为空（零 diff）；另核 git diff src/tasks.py 为纯追加（无既有行删改）

# 全量回归（Tester，基线 1730/0/3 零新增失败）
.venv/Scripts/python.exe -m pytest -q
# 预期：1730 + ~20 ≈ 1750 passed / 0 failed / 3 skipped（以实际新增数算术自洽）

# 真实对账（Tester，§5 T1~T6：一次性 asyncpg 脚本，用后即删；T2 须跨 asyncio.run/子进程）
```

---

## 7. 验收签署

| 角色 | 结论 | 日期 | 签署 |
|------|------|------|------|
| Developer | 待实现 | — | — |
| Reviewer | 待审查 | — | — |
| Tester | **通过（PASS）**：AC-1~23 全签；全量 **1754/0/3**（1730+24 算术自洽，新增 0 失败）；T1-T6 真实 PG 对账 **28 断言全过**（T2 跨进程断点恢复逐值不从头 / T3 父子双向隔离 / T5 开关关 / T6 基线还原 0 行）；LOW-1 已补测（非法 JSON 第 4 形状）；B1①② 真实驱动行为闭环。详见 test-report.md | 2026-09-06 | Tester |
