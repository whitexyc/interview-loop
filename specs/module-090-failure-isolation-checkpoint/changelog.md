# 变更记录 — Module-090: 失败隔离 + checkpoint（子 Agent 失败不连坐 + 长任务断点恢复）

> Developer: 2026-09-06 | 依据：plan.md v1（WP-A~C + 7 大裁定 + 编排者四项待澄清裁定）+ acceptance-criteria.md（AC-1~23）
> 基线：module-086 闭环后全量 **1730 passed / 0 failed / 3 skipped**——红线：**新增 0 失败、存量测试零改动、database.py（TASKS_DDL）/ config.py / observability.py / main.py / engine.py / react.py / langgraph_react.py / memory.py / router.py / tool_registry.py / mcp_server.py / requirements.txt / conftest.py 零 diff**
> 编排者四项裁定执行情况：①resume 后旧 checkpoint **保留**（_SQL_RESUME 零触碰 checkpoint 列，测试锁定）②load/resume DB 异常**上抛**（对齐 get_task_overview，fake session 异常用例锁定）③completed 不可复活白名单**确认合理**（`status IN ('failed', 'running')` 子句逐字锁定）④一 task 多 trace **顺延 T5**（resume 不动 trace_id）

---

## 一、实现总览（三原语 + 失败隔离契约）

```
save_checkpoint(task_id, payload)  同步 fire-and-forget（089 set_task_budget 模式）
  门控首行：空 task_id / tasks_enabled 关 / 非 dict payload → no-op（零 spawn）
  json.dumps(payload, ensure_ascii=False, default=str) → JSON 字符串绑定 JSONB
  （087 真缺陷教训：raw text() 直绑 dict 必炸 DataError 且被 fail-open 吞）
  序列化失败 (TypeError, ValueError) → logger.warning + no-op 不炸调用方
  UPDATE 无 status 条件 = 覆盖语义 last-save-wins（与 finish_task 不触
  checkpoint 列组合 → 收口竞态下末次保存必存活）
load_checkpoint(task_id) -> dict   async 读侧，无开关闸（对齐 087 读端点先例）
  行不存在 → {}；asyncpg JSONB 默认 dict 直返 / str 兜 json.loads /
  非 dict 脏数据防御 → {}；空 task_id → {} 零 DB；DB 异常上抛
resume_task(task_id) -> bool       async 显式恢复动作（同 task_id 复用）
  UPDATE status='running', finished_at=NULL
  WHERE task_id=:task_id AND status IN ('failed','running')
  → rowcount 转 bool（True=已置回可续跑；False=不存在/completed 终态/开关关）
  checkpoint/trace_id/intent/tokens_used 零触碰；悬挂 running 重复恢复幂等
失败隔离 = 零代码补强（plan 裁定 5）：087 单行作用域 SQL（WHERE task_id）+
tasks 表无外键无触发器 = 子 task 失败无任何 SQL 路径可触父行——本模块新增
SQL 同款作用域沿用，契约测试逐字锁定 + Tester T3 父子两行真实对账
```

## 二、WP 实现说明

### WP-A src/tasks.py 三原语（AC-1~10/18/19，纯追加 + docstring 2 行替换）
- `import json`（顶部字母序位）；三条 SQL 常量 `_SQL_SAVE_CHECKPOINT` / `_SQL_LOAD_CHECKPOINT` / `_SQL_RESUME` **与 plan 草案逐字一致**，插在 `_SQL_BUDGET` 之后（常量聚集区），注释注明 087 JSONB 坑与语义裁定。
- `save_checkpoint`：门控三条件首行短路（空 task_id / 开关关 / 非 dict——对齐 set_memory_write_mode / set_task_budget 非法值 no-op 先例）；`json.dumps(payload, ensure_ascii=False, default=str)` 后绑定（ensure_ascii=False 中文可读；default=str 兜 datetime 等不可序列化类型）；序列化失败窄捕获 `(TypeError, ValueError)`（循环引用属 ValueError）warning + no-op；`_spawn` fire-and-forget，无运行 loop 时 RuntimeError 窄捕获静默放弃（既有 `_spawn` 自动覆盖，零新增处理代码——AC-19）。
- `load_checkpoint`：async 读侧无闸；空 task_id → `{}` 零 DB 访问；行缺失 → `{}`（`(result.mappings().first() or {}).get("checkpoint")` 条件表达式等价实现——None 行与 `{}` 同落非 dict 防御分支）；dict 直返（asyncpg 默认解码形态）/ str 兜 `json.loads` / 解码失败或非 dict → `{}`（防御脏数据，窄捕获）；**DB 异常原样上抛**（编排者裁定②，对齐 get_task_overview）。
- `resume_task`：async 写原语（tasks.py 首个 await 型写原语）；门控首行（空 task_id / 开关关 → False 零 DB）；`text(_SQL_RESUME)` execute + **commit**（UPDATE 不 commit 等于回滚——get_task_overview 读侧无 commit 不适用）；`return bool(result.rowcount)`（plan 预授权口径；真实驱动 rowcount 行为由 Tester T2 真实对账确认，若异常触发预授权两段式等价偏离）；不改任何 ContextVar（AC-10）；DB 异常上抛。
- 模块 docstring 2 行替换（唯一非纯追加改动，见 §五.1）：090 接管后原文"checkpoint 逻辑（module-090）……仅结构预留（只存不执法）"表述失真，按 AC-22"模块 docstring 补 090 接管说明"更新。
- 既有零改动实证：begin_task / finish_task / set_task_budget / get_task_overview / set_memory_write_mode / memory_write_allowed / _spawn / _run_sql 函数体零触碰；`git diff --numstat` = **113 增 / 2 删**（2 删 = docstring 旧 2 行）。

### WP-B tests/api/test_checkpoint.py（24 项，AC-1~13/18/19 hermetic 面）
本地 fixture 照抄 089/087 先例：`_reset_task_context`（每用例复位三 ContextVar **含 _task_id_var**）+ `_capture_spawn`（同步捕获 (sql, params)）+ `_FakeSession/_FakeResult/_fake_factory`（对齐 test_tasks.py，扩展 rowcount）。坑①②规避：save_checkpoint 直调不包 asyncio.run；load/resume 包 asyncio.run 且 var 设置与被测调用同一 run。

| 测试类 | 数 | 锁定 AC |
|--------|----|---------|
| TestSQLHygiene | 2 | 三条新 SQL 草案逐字 + 全参数化无拼接（AC-4/7）；五条 SQL `WHERE task_id = :task_id` 作用域逐字 + save 无 status 条件 + resume 白名单/`finished_at = NULL`/不含 completed（AC-8/11） |
| TestSaveCheckpoint | 7 | 门控 ×3 零 spawn（AC-1）；JSON 字符串绑定回读逐值相等含中文/嵌套/datetime→str（AC-2）；循环引用 warning no-op（AC-3）；last-save-wins 可重入（AC-4）；无 loop 真实 _spawn 静默（AC-19，filterwarnings 注明 GC 良性警告成因） |
| TestLoadCheckpoint | 6 | dict 直返逐值（AC-5）；str 兜 json.loads；行缺失 {}；非 dict/str 解码出非 dict/NULL 三态防御 {}（AC-5）；读侧不设闸 + 空 id 零 DB（AC-6）；DB 异常上抛（AC-18） |
| TestResumeTask | 6 | failed→True + commit 落库（AC-7）；悬挂 running 幂等两次 True（AC-7）；completed→False 行零改动 + 白名单逐字（AC-8）；不存在/空 id/开关关→False 零 DB（AC-8）；_SQL_RESUME 零触碰四列 + ContextVar 三枚零改变（AC-9/10）；DB 异常上抛（AC-18） |
| TestIsolationContract | 3 | finish_task(子 id, error=True) 恰一条 spawn 且 task_id==子 id（AC-12）；save/set_task_budget 参数作用域同理（AC-12）；TASKS_DDL 无 REFERENCES/FOREIGN KEY/CREATE TRIGGER + _SQL_FINISH 不含 checkpoint（AC-11/13） |

**开发期测试脚手架修复 2 轮（第 1 轮 7 failed / 第 2 轮 1 failed，均为打桩层 bug 非生产代码）**：① `_FakeSession.__init__` 行列表包装层级错位（`list(dict)` 取键名）+ rowcount 缺省结果对象未建；② "开关关"用例漏置回 `tasks_enabled=False`。根因归档：fake session 泛化包装时入参形状必须文档化在 helper docstring。

### WP-C 回归与文档收口
- 见 §四 自测结果；全量回归未跑（Tester 活），预期 **1754 = 1730 + 24 / 0 failed / 3 skipped**。
- changelog.md（本文）→ 记忆三件套 module-090 追加 → 移交 Reviewer。

## 三、行数统计（铁律 2，AST 语句口径 vs HEAD 基线 86）

| 项 | 文件/函数 | AST 语句 |
|----|-----------|---------|
| import | src/tasks.py `import json` | 1 |
| SQL 常量 | _SQL_SAVE_CHECKPOINT / _SQL_LOAD_CHECKPOINT / _SQL_RESUME | 3 |
| 函数定义 | save_checkpoint / load_checkpoint / resume_task（def 节点） | 3 |
| save_checkpoint 函数体 | 含 docstring Expr | 8 |
| load_checkpoint 函数体 | 含 docstring Expr | 12 |
| resume_task 函数体 | 含 docstring Expr | 8 |
| **合计** | | **+35 ≤ 200 ✓**（全文 86 → 121） |

新增函数最长 `load_checkpoint` 12 语句 ≤ 50 ✓（AC-21）。测试 24 项不计入（module-073 先例）；本地 fixture 不计入。plan 预估 ~26 vs 实际 +35 的偏差构成见 §五.2。

## 四、自测结果（2026-09-06，Developer 自测）

| 验证 | 命令 | 结果 |
|------|------|------|
| 语法 | `.venv/Scripts/python.exe -m py_compile src/tasks.py tests/api/test_checkpoint.py` | **exit 0 无输出** |
| 定向新增 | `.venv/Scripts/python.exe -m pytest tests/api/test_checkpoint.py -q` | **24 passed**（11.51s；2 warnings 均 starlette PendingDeprecationWarning 环境预存，与本模块无关） |
| 受影响存量 | `.venv/Scripts/python.exe -m pytest tests/api/test_tasks.py tests/api/test_budget.py -q` | **52 passed**（32+20，存量测试文件零改动 = 087/089 语义未漂移实证） |
| api 全目录加保 | `.venv/Scripts/python.exe -m pytest tests/api/ -q` | **257 passed / 0 failed** |
| AST 复算 | `ast.walk` 全文语句数 | tasks.py **121**（HEAD 基线 86，+35 ≤ 200）；逐函数 8/12/8 |
| 红线 | `git diff --stat` 18 红线路径（config/database/observability/verify_tasks/main/engine/react/langgraph/memory/router/tool_registry/mcp_server/requirements/conftest/backend/frontend 等） | **全空**；`git status ai_service/` 仅 `M src/tasks.py` + `?? tests/api/test_checkpoint.py` |
| 全量回归 | 未跑（Tester 活）——预期 **1754 = 1730 + 24 / 0 failed / 3 skipped** | — |

## 五、与 plan 偏离清单（6 项，如实申报）

1. **模块 docstring 2 行替换（唯一非纯追加改动）**：AC-22 显式要求"模块 docstring 补 090 接管说明"，而原文（087 写就）"不实现……checkpoint 逻辑（module-090）……仅结构预留（只存不执法）"在 090 接管后已失真。与 AC-16"git diff 仅纯追加"存在字面张力，按 AC-22 执行：仅动模块 docstring 字符串（AST 语句数中性、全部函数体零改动），实句数 2 行删 3 行增。
2. **AST 实际 +35 vs plan 预估 ~26**：构成 = 三函数 docstring（AC-22 要求 Args/Returns/Raises 齐全）3 Expr + load 防御分支（str 兜底 try/except + 非 dict 条件表达式）。先例：089 plan ~31 → 实际 +35，Reviewer/Tester 双轮接受。总量 121 ≤ 200 无压力。
3. **load_checkpoint str 形态 json.loads 失败 → `{}`**：plan 仅钉"str → json.loads 兜底；非 dict → {}"，未言明 loads 抛错（非法 JSON 字符串）时的行为。按"防御脏数据"同款哲学处理：窄捕获 `(TypeError, ValueError)` → `{}`（JSONDecodeError 属 ValueError 子类）。DB 异常仍上抛（编排者裁定②不变——只影响解码层不影响 DB 层）。
4. **行缺失检查用条件表达式**：`(result.mappings().first() or {}).get("checkpoint")` 等价替代 plan 伪码的 `mappings().first() → None → {}` 两分支显式写法——None 行经 `.get` 得 None 后落入非 dict 防御分支返回 `{}`，语义等价（RowMapping 实现 Mapping 协议 `.get` 可用）；省 2 语句。
5. **测试 24 项 vs plan 预估 ~20**：全部对应显式 AC 要求——AC-19 无 loop 真实 _spawn 锁定 1 + AC-6/18 DB 异常上抛 load/resume 各 1 + load 非 dict 防御合并为 1 案例 3 子形状。算术：全量预期 1754 = 1730 + 24 自洽。
6. **resume rowcount 口径按 plan 预授权执行**：hermetic 层以 fake rowcount 验证语义；真实 asyncpg 方言 rowcount 行为（UPDATE 返回 "UPDATE n"）由 Tester T2 真实对账确认（resume 返 True + status 翻转 running + finished_at IS NULL），若实测异常即触发 plan 裁定 2 预授权的两段式等价偏离（届时如实申报）。

## 六、Reviewer 重点核查建议（证据链：plan → 测试 → 实证）

| 核查点 | 佐证 |
|--------|------|
| JSONB 绑定正确性（AC-2 核心） | test_json_string_binding_roundtrip：checkpoint 恒 str + json.loads 回读逐值（中文 ensure_ascii=False / 嵌套 / datetime→default=str）；真实驱动层往返归 Tester T1（禁 mock 充数） |
| 三 SQL 与 plan 草案逐字 | test_three_new_sqls_verbatim_and_parameterized 三段 strip() 全等断言 |
| 覆盖语义无 status 条件（裁定 3） | `assert "status" not in tasks._SQL_SAVE_CHECKPOINT`（AC-4）+ finish 不触 checkpoint 列组合（AC-13） |
| completed 不可复活（裁定③） | 白名单子句逐字 + `"completed" not in _SQL_RESUME` + rowcount=0 行零改动（AC-8） |
| resume 零副作用 | _SQL_RESUME 四列字样零出现 + 三 ContextVar 前后相等（AC-9/10） |
| 失败隔离零补强（裁定 5） | TestIsolationContract 3 项：作用域子句五 SQL 逐字 + DDL 无 REFERENCES/FOREIGN KEY/CREATE TRIGGER + 参数作用域恰一条；真实父子对账归 Tester T3 |
| 红线零漂移 | §四 git diff 全空 + numstat 113/2（2 删 = §五.1 docstring）+ conftest 零 diff |
| 异常分层（AC-18） | save 落库 fail-open（既有 _spawn/_run_sql 链）vs load/resume 上抛 vs 序列化 warning no-op 三层各一用例 |

> **待 Tester**：全量回归（预期 1754/0/3）+ T1-T6 真实对账（§5 AC 文档：T1 JSONB 真实往返 / T2 断点恢复跨 asyncio.run 重启模拟 / T3 父子两行双向隔离 / T4 幂等边界 / T5 开关关边界 / T6 探针清理）。本模块无真实 PG 探针（Developer 全程 hermetic，零 DB 写入）。

## 七、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A 三原语 +35 AST / WP-B 24 项契约测试 / WP-C 自测全绿；偏离 6 项申报） | Developer |
