# 开发计划 — Module-090: 失败隔离 + checkpoint（子 Agent 失败不连坐 + 长任务断点恢复）

> Planner: 2026-09-06 | 依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md`（<repo-root>\knowledge-interview\，注意不在本仓库内）阶段 D module-090 行——"**失败隔离 + checkpoint：子 Agent 失败不连坐 + 长任务断点恢复**"，验收方向"**模拟子失败 → 父任务不失败；重启后续跑不从头**"。阶段 D 最后一片，完成后 D 全收官（版本号 v0.90.0，按实际模块序，Tester 收口时更新）。
> 范围：接管 087 预留的 tasks.checkpoint JSONB 列——save/load 检查点原语 + resume 恢复语义原语 + 失败隔离语义契约测试锁定。**零新表零加列零 config；v1 无生产接线（长任务消费方在 T5/Supervisor）——089 set_task_budget 同款"原语先行"模式（v1 无生产调用方 + 语义单测锁定 + 真实驱动层验证）**
> 预算：WP-A 0.5 天 + WP-B 0.5 天 + WP-C 0.5 天 ≈ 1.5 天
> Agent 配置：Developer ×1（纯 Python 栈）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（Developer 勿重复调查）

### 0.1 checkpoint 列与 tasks 表现状
- **TASKS_DDL（ai_service/src/database.py:201-232）14 列，checkpoint JSONB NOT NULL DEFAULT '{}'（:213）**——087 结构预留（v1 零读零写零逻辑），COMMENT 已标"module-090 预留，v1 零读零写"（:229）。本模块**零 ALTER 零新列**（DDL 一字不改，红线）。
- **DDL 无 FOREIGN KEY、无 CREATE TRIGGER**：parent_task_id 纯 VARCHAR(32) DEFAULT ''（:205），父子链在数据库层无任何级联/触发路径。
- `get_task_overview`（src/tasks.py:270）13 列已透传 checkpoint 与 status——恢复进度的读侧观测面已存在，本模块零端点改动。

### 0.2 src/tasks.py 现状（293 行，本模块唯一生产改动面）
- **写侧基建**：`_spawn`（:90，fire-and-forget + `_pending_tasks` 引用池防 GC + RuntimeError 窄捕获静默放弃）+ `_run_sql`（:100，全异常 logger.warning 不上抛 fail-open）。
- **begin_task（:117）**：INSERT 11 列，**checkpoint 绑定已传 "{}" JSON 字符串（:144）**——087 Tester 修复轮实证：raw `text()` 写 JSONB 列传 dict 必炸 DataError 且被 fail-open 吞。本模块 save_checkpoint 是该坑的直接踩坑面，必须 json.dumps 后绑定。
- **finish_task（:149）**：`UPDATE ... WHERE task_id = :task_id AND status='running'`（单收口幂等）；`_SQL_FINISH`（:54-59）**不含 checkpoint 字样——收口不触碰 checkpoint 列**（087 语义，本模块锁定）。
- **set_task_budget（:248，module-089）**：同步原语 + 非法值 no-op + `_SQL_BUDGET` UPDATE **无 status 条件**（覆盖语义重放安全，:77-82）——本模块三原语照此模式；"v1 无生产调用方 + 语义单测锁定 + 调用方 T5"已被 Reviewer/Tester 三轮验收接受。
- **get_task_overview（:270）**：async 读侧先例——DB 异常**原样上抛**、端点层统一 fail-open。
- ContextVar 三枚（task_id :33 / memory_write :35 / budget_limit :37）；开关 `tasks_enabled`（PW_TASKS_ENABLED，config.py:162）管写入面（begin/finish/set_task_budget 均门控）。

### 0.3 失败隔离现状核实（本模块核心结论：天然成立，零代码补强）
- **全部 task 写路径的 SQL 均为 `WHERE task_id = :task_id` 单行作用域**（finish_task :58 / set_task_budget _SQL_BUDGET :82 / 本模块新增两条同款）；tasks 表无触发器无外键无级联；parent_task_id 除 INSERT 常量 '' 外无任何 SQL 逻辑引用。
- 结论：**子 task finish_task(error=True) 在行级天然不可能改动父 task 状态行**——不存在任何"连坐"通道。v1 生产一次请求 = 1 task（无子 task 写入方，生产写入方在 T5），父子场景目前只能由测试/脚本构造。
- 交付形态 = **显式语义契约测试锁定**（hermetic：SQL 作用域子句逐字断言 + spawn 参数作用域断言）+ Tester 真实 PG 行为对账（父子两行实测双向隔离）——**不写任何"隔离"代码**（裁定 5）。

### 0.4 测试基建与环境坑（直接照抄/规避，全部为既往实测）
- conftest `default_tasks_disabled` autouse 钉关（tests/conftest.py:145）——新测试文件体内显式开启；本模块 **conftest.py 零改动**（fixture 全部本地化）。
- tests/api/test_budget.py:35 `_reset_task_context` 本地 fixture（每用例复位三 ContextVar）+ :44 `_capture_spawn`（monkeypatch `tasks._spawn` 同步捕获 (sql, params)）——照抄。
- tests/api/test_tasks.py:94 `_capture` 同款打桩 + 直调同步入口不包 asyncio.run / async 原语包 asyncio.run——照抄。
- **坑① ContextVar 跨 asyncio.run 不继承**（每次 run 全新上下文，089 实测 10 failed 根因）：async 原语测试中 var 设置与被测调用必须同一 asyncio.run；**坑①同时是"进程内重启模拟"的天然机制**——新 asyncio.run = 内存上下文归零，恢复只能走 DB。
- **坑② 同步原语严禁 asyncio.run 包裹**（var 落 pytest 共享上下文泄漏）——save_checkpoint 直调；load/resume 为 async 才包裹。
- **坑③ raw text() 写 JSONB 必须 JSON 字符串**（asyncpg dict 必炸且被 fail-open 吞）——save_checkpoint json.dumps 后绑定 + 真实驱动层 T1 终验。
- **坑④ asyncpg 读侧 JSONB 默认解码为 dict（非 str）**——load_checkpoint 双兼容 dict/str（T 系列确认）。
- 基线：**1730 passed / 0 failed / 3 skipped**（2026-09-06 module-086 闭环）——红线：**新增 0 失败、存量测试零改动（tests/ 仅新增 test_checkpoint.py）**。
- pytest 在 ai_service/ 目录跑，解释器 `.venv/Scripts/python.exe`；git 仓库根即 interview-personal/。

## 1. 关键决策（Planner 裁定）

1. **恢复语义 = 同 task_id 复用（resume_task 原语），非"新 task 带父指针"**。理由：checkpoint 就存在 task 行上，复用同 task_id 进度天然延续；新建 task 需复制 checkpoint 且引入新父子链语义（T5 范畴）；"重启后续跑不从头"自然表达为"同一任务行从 failed/悬挂 running 置回 running 并续读 checkpoint"。resume_task 不触碰 trace_id/intent/tokens_used（087 plan §8 待澄清 1 顺延：一 task 多 trace 关联留 T5）。
2. **resume_task 为 async 原语（tasks.py 首个 await 型写原语），返回 bool**。理由：恢复是显式恢复动作，调用方需要成功与否决定后续（load + 续跑）——fire-and-forget 会让"恢复"变猜、测试得 sleep 同步（不稳定）；恢复不在请求热路径上（进程重启后的显式操作），真实 DB 往返可接受；async 读写对称（对齐 get_task_overview 读侧先例）。SQL（草案，Developer 照做）：
   ```sql
   UPDATE tasks SET status = 'running', finished_at = NULL
   WHERE task_id = :task_id AND status IN ('failed', 'running')
   ```
   状态白名单语义：**failed（失败收口）与 running（进程死亡遗留的悬挂行，087 接受的边界）可恢复；completed 是终态不可复活（返回 False）**——"复活已完成任务"属调用方 bug，白名单挡住；悬挂 running 恢复幂等（重复调用状态不变返回 True）。rowcount → bool。若 asyncpg 方言下 rowcount 实测异常，**预授权等价偏离**：先 SELECT status 判定 + 再 UPDATE 两段式（语义契约不变，如实申报 changelog §偏离）。
3. **save_checkpoint：同步 fire-and-forget（089 set_task_budget 模式）+ UPDATE 无 status 条件（覆盖语义）**。理由：若加 `WHERE status='running'`，与 finish_task 的 fire-and-forget 乱序竞态（spawn 先于 finish、落库晚于 finish）会吞掉末次 checkpoint，损害"续跑不从头"契约；finish_task 本就不触 checkpoint 列，无状态冲突面。**json.dumps(payload, ensure_ascii=False, default=str) 后绑定**（ensure_ascii=False 中文可读；default=str 兜 datetime 等不可序列化类型）；**非 dict payload → no-op**（对齐 set_memory_write_mode/set_task_budget 非法值语义）；**序列化失败（循环引用 ValueError 等）→ logger.warning + no-op 不炸调用方**（fail-open 边界：检查点保存永不crash任务主链路）。SQL（草案）：
   ```sql
   UPDATE tasks SET checkpoint = :checkpoint WHERE task_id = :task_id
   ```
4. **load_checkpoint：async 读侧 + 无开关闸**。行不存在 → {}；JSONB 解码结果 dict 直返（asyncpg 默认）/ str 兜 json.loads / 非 dict（防御脏数据）→ {}；DB 异常**上抛**（对齐 get_task_overview，调用方定降级——v1 无生产调用方，恢复侧降级策略 T5 定）。读侧不设闸（对齐 087 读端点先例）：开关管写入面（save/resume 门控），load 不门控。SQL（草案）：
   ```sql
   SELECT checkpoint FROM tasks WHERE task_id = :task_id
   ```
5. **失败隔离 = 契约测试锁定，零代码补强**（§0.3 核实结论）。hermetic 层：锁四条 UPDATE/INSERT SQL 的 `WHERE task_id = :task_id` 作用域子句逐字 + TASKS_DDL 无 REFERENCES/FOREIGN KEY/CREATE TRIGGER + spawn 参数 task_id 作用域断言 + `_SQL_FINISH` 不含 checkpoint 字样；真实层：Tester T3 父子两行行为验证。隔离的机制保证是 087 既有单行作用域 SQL——本模块新增 SQL 沿用同款作用域即延续保证。
6. **恢复/隔离事件不接 record_span（088 通道）**。v1 无生产调用方，恢复多发生在请求上下文外（进程重启后无 trace_id）→ record_span 的 get_trace_id() 空会静默跳过，接线即死代码；可观测 = tasks 行状态本身（status/finished_at/checkpoint 经既有 get_task_overview 端点可查）+ logger.info。T5 接线时再议。
7. **零 config 零新开关零新依赖**。tasks_enabled 既有开关管写入面（save/resume 门控 + 空 task_id no-op）；无新 env 变量（无 088 发现-1 式变量名风险面）；无新表无 ALTER；main.py / engine / react / langgraph / database / config / memory.py 零改动。

## 2. WP 拆解（含 AC 映射）

### WP-A：src/tasks.py 三原语（~26 AST 行，唯一生产改动面，既有行零改动）
插在 set_task_budget 之后、get_task_overview 之前（写侧原语聚集、读侧在后；位置 Developer 可调，既有行零改动是硬约束）。顶部 import `json`（1 行）。

**三条 SQL 常量**（草案逐字，全参数化无拼接；注释对齐既有风格并注明 087 JSONB 坑）：
```python
# checkpoint 保存（module-090：JSONB 列必须传 JSON 字符串——087 真缺陷教训，
# 绝不直绑 dict；无 status 条件 = 覆盖语义重放安全（对齐 _SQL_BUDGET），
# finish_task 不触碰 checkpoint 列 → 末次保存必存活）
_SQL_SAVE_CHECKPOINT = """
    UPDATE tasks SET checkpoint = :checkpoint
    WHERE task_id = :task_id
"""

# checkpoint 读取（module-090 读侧；行不存在由调用方兜 {}；asyncpg 对 JSONB
# 默认解码为 dict——load 侧双兼容 dict/str）
_SQL_LOAD_CHECKPOINT = """
    SELECT checkpoint FROM tasks
    WHERE task_id = :task_id
"""

# 恢复（module-090：同 task_id 复用置回 running + finished_at 复位 NULL；
# 白名单 failed/悬挂 running——completed 终态不可复活；checkpoint/trace_id/
# intent/tokens_used 零触碰；幂等：重复调用状态不变）
_SQL_RESUME = """
    UPDATE tasks SET status = 'running', finished_at = NULL
    WHERE task_id = :task_id AND status IN ('failed', 'running')
"""
```

**三个函数**（语义钉死；docstring Args/Returns 齐全，风格对齐 set_task_budget）：
- `def save_checkpoint(task_id: str, payload: dict) -> None`：门控首行（空 task_id / not tasks_enabled / 非 dict payload → return）→ try json.dumps(ensure_ascii=False, default=str) except (TypeError, ValueError) → logger.warning + return → `_spawn(_SQL_SAVE_CHECKPOINT, {"task_id": task_id, "checkpoint": <json str>})`。
- `async def load_checkpoint(task_id: str) -> dict`：空 task_id → {} → async_session_factory + text execute → mappings().first() → None → {} → 值双兼容（str → json.loads；非 dict → {}）→ 返回 dict。DB 异常上抛。
- `async def resume_task(task_id: str) -> bool`：门控首行（空 task_id / not tasks_enabled → False）→ async_session_factory + text execute + commit → `return bool(result.rowcount)`（True=已置回可续跑状态；False=不存在/completed 终态/开关关）。DB 异常上抛。不改任何 ContextVar。
- **AC 映射**：AC-1~10、AC-18、AC-19。

### WP-B：tests/api/test_checkpoint.py 新增（~20 项，不计生产行数；conftest.py 零改动）
本地 fixture：`_reset_task_context`（照抄 test_budget.py:35，每用例复位三 ContextVar）+ `_capture_spawn`（照抄 :44）。直调 save_checkpoint 不包 asyncio.run；load/resume 包 asyncio.run（坑①②）。
- **TestSQLHygiene（~2）**：三条新 SQL 无 f-string/`%`/`+` 拼接；与 `_SQL_FINISH`/`_SQL_BUDGET` 的作用域子句逐字断言。
- **TestSaveCheckpoint（~6）**：门控 ×3（空 task_id / 开关关 / 非 dict → 零 spawn）；JSON 字符串绑定断言（params["checkpoint"] 为 str 且 json.loads 回读相等，含中文/嵌套/datetime→str）；序列化失败（循环引用）warning + no-op；无 status 条件文本断言（覆盖语义）；重复保存参数断言（last-save-wins 可重入）。
- **TestLoadCheckpoint（~4）**：正常往返（fake session 返回 dict 形态——asyncpg 解码形态）；str 形态 json.loads 兜底；行不存在 → {}；非 dict 防御 → {}；开关关仍可读（读侧不设闸）。
- **TestResumeTask（~5）**：failed → True（fake rowcount=1；SQL 含白名单子句与 finished_at=NULL）；悬挂 running → True 幂等；completed → False（rowcount=0，行零改动语义）；不存在/空 id/开关关 → False；resume 后 checkpoint 保留断言（_SQL_RESUME 文本不含 checkpoint 字样）+ ContextVar 零触碰断言。
- **TestIsolationContract（~3）**：finish_task(子 id, error=True) → spawn 参数 task_id == 子 id 恰一条（单行作用域）；save_checkpoint/set_task_budget 同理参数作用域；TASKS_DDL 文本不含 REFERENCES/FOREIGN KEY/CREATE TRIGGER + _SQL_FINISH 不含 "checkpoint" 字样。
- **AC 映射**：AC-11~13、AC-20~23 的 hermetic 面（真实层归 WP-C/Tester）。

### WP-C：回归 + 文档收口
- py_compile 2 文件（src/tasks.py + tests/api/test_checkpoint.py）；定向 `pytest tests/api/test_checkpoint.py -q` 全绿；受影响存量定点：tests/api/test_tasks.py + tests/api/test_budget.py（tasks.py 原语面——存量零改动全绿即 087/089 语义未漂移实证）；全量 `pytest -q` = **1730 基线 + ~20 新增 / 0 failed / 3 skipped，新增 0 失败**（预期 ≈1750，算术自洽）。
- 文档：changelog.md（Developer）→ review-report.md（Reviewer）→ test-report.md（Tester）；记忆三件套追加 module-090 记录。
- **AC 映射**：AC-14~17、AC-20~23。

## 3. 行数对照（铁律 2，AST 语句口径）

| WP | 文件 | 预估 AST 行 |
|----|------|------------|
| WP-A | src/tasks.py（import json 1 + 三 SQL 常量 3 + save_checkpoint ~6 + load_checkpoint ~10 + resume_task ~6） | ~26 |
| 合计 | | **~26 ≤ 200 ✓** |

测试 ~20 项不计入（module-073 先例）；本地 fixture 不计入。**零改动面**：main.py / src/config.py / src/database.py / src/observability.py / rag/engine.py / agent/react.py / agent/langgraph_react.py / rag/memory/memory.py——比 089（+35）更小，预估远低于上限。若实际超 200，按 module-080 先例晒行数对照表申请放宽。

## 4. 风险评估

- **JSONB 直绑坑（高关注，本模块核心踩坑面）**：raw text() 写 JSONB 传 dict 必炸且被 fail-open 吞（087 真缺陷）——save_checkpoint json.dumps 后绑定 + T1 真实驱动层往返终验（禁 mock 充数）。begin_task "{}" 字符串先例证明绑定路径可行。
- **asyncpg 读侧 JSONB 解码形态（中）**：默认解码为 dict 而非 str——load_checkpoint 双兼容 dict/str + 非 dict 防御；T 系列真实驱动确认形态。
- **rowcount 语义（低，已预授权）**：SQLAlchemy asyncpg 方言 UPDATE rowcount 应可用（返回 status "UPDATE n"）；实测异常时按裁定 2 预授权偏离两段式，语义契约不变。
- **覆盖语义 vs 收口竞态（低，已论证）**：save 无 status 条件是刻意裁定（裁定 3）——末次保存必存活；Reviewer 勿按"应加 WHERE status='running'"误判。
- **ContextVar 测试泄漏（低，坑①②有解）**：本地 _reset fixture + 同一 asyncio.run + 同步原语不包裹。
- **"死代码"观感（中，roadmap 授权）**：三原语 v1 无生产调用方——roadmap module-090 行的结构性交付 + 089 set_task_budget 同款模式已三轮接受；单测锁语义防退化；生产接线 T5。
- **悬挂 running 恢复语义（低）**：白名单含 running 是刻意的（进程死亡遗留行可恢复）；completed 不可复活由测试锁定——勿混淆两类状态。
- **全量基线漂移（低）**：1730/0/3 红线；存量测试零改动（仅新增文件）。

## 5. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-087 任务抽象 | checkpoint 列（:213）本模块接管（首次读写）；begin_task/finish_task/get_task_overview **零改动**；finish 不触 checkpoint 列的 087 语义由契约测试锁定（AC-13）；悬挂 running 边界（087 接受）成为 resume 白名单输入 |
| module-089 set_task_budget 原语 | **模式母本**：同步原语 + 非法值 no-op + fire-and-forget UPDATE + "v1 无生产调用方，调用方 T5"——save_checkpoint 逐字沿用；_SQL_BUDGET 无 status 条件的覆盖语义被裁定 3 引用 |
| module-088 record_span 观测通道 | **不接线**（裁定 6）：恢复多发生在请求上下文外（无 trace_id → 静默跳过 = 死代码）；可观测走 tasks 行状态 + logger；隔离事件同理 |
| module-085/087 读侧聚合 | get_task_overview 已透传 checkpoint/status——恢复进度的观测面零改动复用；读侧异常上抛先例被 load/resume 沿用 |
| 087 plan §8 待澄清 1（一 task 多 trace） | **顺延不解决**：resume 不动 trace_id，恢复跑的观测关联留 T5（新关联表或复议加列，届时裁定） |
| T5/Supervisor（未来） | 三原语的生产调用方：子 Agent 失败处置（隔离契约的真实消费场景）+ 长任务断点续跑（save/resume/load 编排）；parent_task_id 生产写入方亦在 T5 |
| 存量测试 | tests/api/test_tasks.py + test_budget.py 零改动全绿 = 087/089 语义未漂移实证；conftest.py 零 diff |

## 6. 明确不做

- **T5 Supervisor 编排 / 多 Agent 派生 task 的生产接线 / parent_task_id 生产写入**（生产调用方全部 T5——不发明不存在的长任务场景硬塞生产链路）
- **跨进程迁移恢复**（进程快照/内存状态迁移不做——恢复 = 同 PG 落库状态，新进程只认 DB）
- **checkpoint 压缩/加密/版本化/历史链/大小限制**（JSONB 单值覆盖语义，last-save-wins）
- **record_span 恢复/隔离事件接线**（裁定 6）
- **恢复状态看板/端点**（get_task_overview 已透传，零改动）
- **resume 清空 checkpoint**（保留为缺省，见 §8 待澄清 1）
- **新 config/新开关/新 env 变量/新依赖/新表/ALTER**
- **main.py / config.py / database.py / observability.py / engine / react / langgraph / memory.py 任何改动**
- **任务列表端点 / tasks 表清理归档策略**（087 已声明不清理）
- **新 ADR**（无架构分歧：决策记录于本 plan 与 changelog）

## 7. 待澄清（不阻塞开发，Developer 按缺省执行）

1. **resume 后旧 checkpoint 保留 vs 清空**：缺省**保留**（进度历史可查、重复恢复安全；T5 若需清空可 `save_checkpoint(task_id, {})` 覆盖）——如编排者要求恢复即清空请批示。
2. **load/resume 的 DB 异常上抛 vs fail-open**：缺省**上抛**（对齐 get_task_overview 读侧先例，调用方定降级）——若编排者认为恢复路径应 fail-open（返回 {}/False）请批示。
3. **completed 不可复活（白名单裁定）**是否符合 T5 预期：若 T5 需要"重跑已完成任务"语义，届时加显式 restart 原语而非放开白名单。
4. **一 task 多 trace 关联**（087 §8 待澄清 1 顺延）：resume 后 trace_id 保持首跑值；恢复跑的 request_logs/spans 关联留 T5 规划。

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~C 拆解 + 7 大裁定：同 task_id 复用恢复 / resume async 返回 bool + 状态白名单 / save 覆盖语义 + JSON 字符串绑定 / load 读侧无闸 + 双兼容 / 隔离零代码补强契约锁定 / 不接 record_span / 零 config 零新表；SQL 草案 + 行数对照 ~26 + Tester T1-T6 真实对账含断点恢复与父子隔离） | Planner |
