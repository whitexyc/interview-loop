# 测试报告 — Module-090: 失败隔离 + checkpoint（子 Agent 失败不连坐 + 长任务断点恢复）

> Tester: 2026-09-06 | 测试对象：`specs/module-090-failure-isolation-checkpoint/`（plan v1 / AC-1~23 / changelog v1）+ Reviewer PASS 报告（1 LOW + 2 备忘）
> 测试方法：命令表全量独立复跑（不采信任何声明）+ Reviewer LOW-1 防御用例补测 + 全量回归 + T1-T6 真实 PG 对账（asyncpg 裸连接 + SQLAlchemy 双通道，一次性脚本用后即删）
> 基线：module-086 闭环后 **1730 passed / 0 failed / 3 skipped**；本轮预期 1754 = 1730 + 24

## 0. 测试概览

| 维度 | 结果 |
|------|------|
| 全量回归 | **1754 passed / 0 failed / 3 skipped**（117.91s）——= 基线 1730 + 本模块 24，算术自洽，新增 0 失败 |
| 定向新增 | 24 passed（test_checkpoint.py；含 LOW-1 补测形状） |
| 受影响存量 | test_tasks 32 + test_budget 20 = 52 passed（存量文件零改动实证 087/089 语义未漂移） |
| api 全目录 | 257 passed / 0 failed |
| T1-T6 真实对账 | **28 项断言全部 PASS**（4 个一次性脚本，基线还原 0 行） |
| AC 签署 | AC-1~23 全部 ✅（AC-20 由本轮全量收口） |
| 失败归因 | 对账脚手架自身 bug 3 轮（Tester 侧，详见 §3）；被测代码 0 缺陷 |

## 1. 验证命令执行结果（独立复跑，ai_service 目录，.venv/Scripts/python.exe）

```
1) pytest tests/api/test_checkpoint.py -q
   → 24 passed, 2 warnings in 12.46s（LOW-1 补测后复跑；2 warnings = starlette
     PendingDeprecationWarning 环境预存，与本模块无关）

2) pytest tests/api/test_tasks.py tests/api/test_budget.py -q
   → 52 passed, 2 warnings in 14.76s（存量测试文件零改动 = 087/089 语义未漂移）

3) pytest tests/api/ -q
   → 257 passed, 2 warnings in 17.90s

4) pytest tests/ -q（全量回归，超时 600s 内完成）
   → 1754 passed, 3 skipped, 163 warnings in 117.91s
     算术自洽：1730 基线 + 24（test_checkpoint.py）= 1754；新增 0 失败 ✓

5) pytest tests/ -q -rs（skip 原因甄别）
   → 3 skipped 全部为 tests/core/test_document_parser.py:510/546/566
     "测试 PDF 文件不存在（主 checkout 路径）"——086 基线即存在的环境性跳过，
     与本模块零关联，非新增静默跳过（Tester 纪律：甄别后放行）

6) python -m py_compile src/tasks.py tests/api/test_checkpoint.py
   → exit 0 无输出

7) AST 复算（ast.stmt 口径）
   → src/tasks.py 全文 121 语句（HEAD 基线 86，+35 ≤ 200，与 changelog §三一致）

8) 红线核验
   → git diff --stat 18 红线路径（config/database/observability/verify_tasks/main/
     engine/react/langgraph_react/memory/router/tool_registry/mcp_server/requirements/
     sanitize/conftest/backend/frontend/knowledge-interview）输出为空（零 diff）✓
   → git status --short knowledge-interview backend frontend 无输出 ✓
   → git status ai_service/ 恰 = M src/tasks.py + ?? tests/api/test_checkpoint.py ✓
   → git diff --numstat src/tasks.py = 113 增 / 2 删（2 删 = docstring 旧 2 行，
     Reviewer 偏离 1 已裁定）；物理行 293 → 404 自洽（293 + 113 − 2 = 404）✓
   → conftest.py 零 diff（--numstat 空输出）✓
```

### 1.1 全量回归差异逐根因归类

| 差异 | 数量 | 根因归类 |
|------|------|----------|
| passed 1730 → 1754 | +24 | 本模块新文件 tests/api/test_checkpoint.py 24 项（TestSQLHygiene 2 + TestSaveCheckpoint 7 + TestLoadCheckpoint 6 + TestResumeTask 6 + TestIsolationContract 3）——预期内新增 |
| failed | 0 | 无任何新增失败；存量 1730 项零漂移 |
| skipped | 3（持平） | test_document_parser.py PDF 缺失（主 checkout 路径），086 基线同源环境性跳过，与本模块无关 |
| 存量测试文件改动 | 0 | git status 实证 tests/ 仅新增 test_checkpoint.py；conftest.py 零 diff |

## 2. Reviewer 移交项处理（LOW-1 + 备忘 B1/B2）

| 项 | 处理与结果 |
|----|-----------|
| LOW-1（load str 形态非法 JSON 子分支零覆盖，tasks.py:348-349） | **已补测**：test_checkpoint.py `test_non_dict_defense` 增补第 4 形状 `"{oops"`（非法 JSON 字符串 → json.loads 抛 JSONDecodeError → 窄捕获 → {}），断言返回 {}。复跑定向 24 passed（用例数不变、形状 +1，全量算术保持 1754 自洽）。该文件为本模块新测试文件，不违反存量零改动红线 |
| B1①（resume 真实 rowcount 行为） | **T2 闭环**：真实 asyncpg 方言下 resume_task 返回 True（bool，非 int 非 rowcount 对象），status 翻转 running + finished_at NULL；completed 行返回 False。预授权两段式回退**未触发** |
| B1②（真实行形态 (RowMapping or {}).get） | **T2 闭环**：SQLAlchemy asyncpg 方言真实行上 load_checkpoint 返回与保存 payload 逐值相等；另实测本机 asyncpg 裸连接 JSONB 原始形态为 **str**（见 §5 发现-1），str 兜底分支为真实必经路径 |
| B2（AC-20 全量回归） | **本轮收口**：1754 / 0 / 3 ✓ |

## 3. 失败详情（含失败类别——Tester 对账脚手架波折，如实申报）

本轮**被测生产代码与测试代码零缺陷、零失败**。以下 3 项均为 Tester 自备一次性对账脚本的自身问题，修复后全部通过，不涉及被测模块：

| # | 现象 | 失败类别 | 根因与修复 |
|---|------|----------|-----------|
| 1 | 对账脚本 1 首轮：begin_task 后 12s 轮询行不存在（TimeoutError） | **脚本自身 bug（非环境、非被测代码）** | 复合因素：冷进程首次 engine 建连慢于轮询窗口（环境性成分）+ 深层 bug 见 #2；当时误判环境 |
| 2 | 脚本 1 二轮：30s 轮询仍超时（**稳定复现** → 排除环境） | **脚本自身 bug** | `begin_task` 在函数体内 `uuid4().hex` 生成 task_id 并以返回值交付，脚本 v1 丢弃返回值、用自预生成 uuid 轮询——恒空。插桩实验（COUNT 判定）反证 `_spawn` 正常 0.5-0.6s 落库。v2 改用返回值后一次全过。**归档价值：T5 编排调用方必须接收 begin_task 返回值**（见 §5 发现-2） |
| 3 | 脚本 4 首跑 NameError: pg 未定义 | **脚本笔误** | 函数漏定义，内联 asyncpg.connect 修复复跑 |
| — | 插桩/实验/失败遗留孤儿探针行 5 行（含 087 教训外的本窗产生的 4 行 + 诊断 1 行） | Tester 清理责任 | 全程按 task_id 精确 DELETE（DELETE 2 / DELETE 1 / DELETE 2 分批），终态 `SELECT COUNT(*) FROM tasks` = 0（基线还原实证见 T6） |

环境性失败汇总：0（PG 全程可达、无端口/依赖问题；首轮 12s 建连延迟经插桩实测正常路径 0.5s，未复现，归入 #1 复合因素存档）。

## 4. 真实 PG 对账（T1-T6，"子失败父不连坐 + 断点恢复不从头"验收实质）

> 载体：4 个一次性 asyncpg 脚本（临时目录 <home>\AppData\Local\Temp\m090_probe\，用后即删）。写侧走 src.tasks 真实原语（`_spawn` → `_run_sql` → SQLAlchemy text() + asyncpg 驱动层，与生产逐字同路径，全程禁 mock）；验证读侧走 asyncpg 裸连接（绕开 SQLAlchemy 双向实证）；T2 后半为**独立 python 进程**（最强跨 asyncio.run 重启口径——ContextVar 天然归零，恢复只能来自 DB）。**结果：28 项断言全部 PASS，基线还原 0 行。**

### 4.1 T1 checkpoint 真实落库往返（脚本 1，13 PASS，AC-2 终验）

| 断言 | 结果 | 实证 |
|------|------|------|
| begin_task 真实 INSERT status=running | PASS | `_spawn` fire-and-forget 落库，裸连接轮询确认 |
| save_checkpoint 落库非默认 '{}' | PASS | 裸连接 `SELECT checkpoint` 读回原始形态 = **str**（asyncpg 无默认 JSON 解码，见 §5 发现-1） |
| 逐值一致 step/done中文/nested/ts→ISO | PASS | step=5、done=['检索','改写']、nested={'a':[1,2,{'b':True}]}、ts='2026-09-06 12:00:00'（default=str） |
| 中文无损（ensure_ascii=False）/ 嵌套无损 | PASS | 逐值比对 |

### 4.2 T2 断点恢复不从头（核心验收①，脚本 1 前半 + 脚本 2 后半，AC-7/9 实质）

| 断言 | 结果 | 实证 |
|------|------|------|
| finish_task(error=True) → failed 且 checkpoint 不被触碰 | PASS | 裸连接确认 failed；checkpoint 原值存活（AC-13 真实行为面） |
| **跨进程** resume_task 返回 True | PASS | **B1① 闭环**：真实 rowcount → bool 正确；预授权两段式未触发 |
| resume 后 status=running AND finished_at IS NULL | PASS | 裸连接 SQL 确认 |
| **load_checkpoint 恢复原 payload 逐值（续跑不从头）** | PASS | **B1② 闭环**：新进程 load 返回 == T1 payload（step/done中文/nested/ts 逐值）——恢复只能来自 DB（跨进程 ContextVar 归零），续跑起点 = checkpoint 内容而非从头 |
| 续跑模拟：save {"step":6} → finish → completed | PASS | completed + 末次保存存活（finish 不吞 checkpoint 组合语义） |

### 4.3 T3 模拟子失败父不连坐（核心验收②，脚本 1，AC-11/12 实质）

| 断言 | 结果 | 实证 |
|------|------|------|
| 子行直插（_SQL_INSERT 同款参数化，parent_task_id=父 id，checkpoint='{}' JSON 字符串） | PASS | 裸连接确认关联与 running |
| **子失败后父行逐列零变化** | PASS | finish_task(子, error=True) → 子 failed；父行 10 业务列快照前后相等（status=running / finished_at=None / tokens_used=0 / checkpoint={} 等） |
| **父收口后子行保持 failed（双向隔离）** | PASS | finish_task(父) → 父 completed（intent 回写正常）而子行仍 failed |

### 4.4 T4 幂等与边界（脚本 1 写侧 + 脚本 2 恢复侧，AC-4/8 实质）

| 断言 | 结果 | 实证 |
|------|------|------|
| 同 payload save×2 列值一致 | PASS | 裸连接列值逐值 |
| 不同 payload save×2 后写生效（last-save-wins） | PASS | {"step":1} → {"step":42} |
| resume×2 幂等（悬挂 running 行两次 True 状态不变） | PASS | r1=True r2=True，status 恒 running |
| resume on completed → False 且行逐列不变 | PASS | 10 业务列快照前后相等 |
| load_checkpoint 行不存在 → {} | PASS | 返回 {} |

### 4.5 T5 开关关边界（脚本 3，AC-1/6 实质；PW_TASKS_ENABLED 逐字，进程级 env）

| 断言 | 结果 | 实证 |
|------|------|------|
| env PW_TASKS_ENABLED=false → settings.tasks_enabled=False | PASS | pydantic 实例化读 env 确认 |
| save_checkpoint no-op（checkpoint 列零变更） | PASS | 2s 调度窗口后列值保持 {"step": 42} |
| resume_task → False 且行状态不变 | PASS | 返回 False，status 恒 running（与 completed 拒绝可区分） |
| **load 读侧不设闸**（开关关仍读到 T2 遗留行） | PASS | 返回 {'step': 6} |

### 4.6 T6 探针清理与基线还原（脚本 4）

| 断言 | 结果 | 实证 |
|------|------|------|
| 清理前探针行恰在库 | PASS | 4/4 |
| 按 task_id 精确 DELETE 还原 | PASS | DELETE 4；IN 计数 = 0 |
| 对账前后全表计数一致（基线还原） | PASS | 基线 0 → 对账后 0；临时脚本目录已删 |

## 5. Tester 新发现（非缺陷，归档价值）

1. **本机 asyncpg 版本 JSONB 裸读原始形态 = str（非 dict）**：裸连接 `SELECT checkpoint` 返回 JSON 字符串。结合 T2 B1②（SQLAlchemy text() 路径 load 逐值成功），证实 AC-5 的 dict/str 双兼容设计中 **str 兜底分支是本机真实必经路径**——changelog 偏离 3 的 `json.loads` 窄捕获不是理论防御而是生产主路径。给 T5 调用方：load_checkpoint 返回的 dict 来自 json.loads 兜底，形态预期按此设定。
2. **begin_task 的 task_id 只能从返回值取得**（函数内部 uuid4().hex 生成，无入参注入）：本轮对账脚本 v1 丢弃返回值导致两轮空转（§3 #2）。T5 子 Agent 编排落地时调用方必须接收返回值——建议写入 T5 的 plan 前置注意项。

## 6. 环境申报（如实）

- PG：本机 localhost:5432（postgres/******，personal_website）全程可达；对账前 tasks 表 0 行（干净），对账后还原 0 行。
- 对账载体：4 个一次性脚本于 %TEMP%\m090_probe\，T6 后整目录删除；无 uvicorn 起服（三原语不经 HTTP，AC §5 口径）；T5 开关用进程级环境变量（非 monkeypatch）。
- pytest warnings：定向/存量/api 各 2（starlette PendingDeprecationWarning，环境预存）；全量 163-164 同源累计。无 collection warning、无非预期 skip。
- 3 skipped 与 086 基线同源（PDF 文件缺失，主 checkout 路径），甄别后放行（§1 #5）。
- git 环境注意：仓库提示 LF→CRLF 换行警告（line-ending 配置性提示，非内容 diff），不影响红线判定。
- LOW-1 补测使 test_checkpoint.py 较 Reviewer 审查版多 1 处形状断言（+5 物理行），已在上表数字中体现。

## 7. 验收标准核对（AC-1 ~ AC-23 逐项签署）

### 7.1 功能验收

| AC | 要求 | 结果 | 测试证据 |
|----|------|------|----------|
| AC-1 | save 门控三条件零 `_spawn` | ✅ | TestSaveCheckpoint 空id/开关关/非dict×4 形态零 spawn；T5 真实开关关 no-op |
| AC-2 | JSONB 绑定恒 str + 回读逐值（087 坑面） | ✅ | hermetic：isinstance str + json.loads 回读逐值（中文/嵌套/datetime→str）；**T1 真实驱动终验**：落库读回逐值一致 |
| AC-3 | 序列化失败 fail-open warning no-op | ✅ | 循环引用不抛 + 零 spawn + caplog "序列化失败" |
| AC-4 | save SQL 逐字无 status 条件 + last-save-wins | ✅ | 串等断言 + `"status" not in`；T4 真实 save×2 幂等/后写生效 |
| AC-5 | load 双解码 + 行缺失 {} + 非 dict 防御 | ✅ | dict/str/缺失/防御 4 形状（含 LOW-1 补测非法 JSON）；str 兜底经 T1/T2 证实为真实主路径 |
| AC-6 | load 读侧不设闸 + 空 id {} 零 DB + DB 异常上抛 | ✅ | 开关关仍读到值（hermetic + T5 真实）+ 空 id 零 SQL + pytest.raises |
| AC-7 | failed→True 置 running+finished_at=NULL；悬挂 running 幂等 | ✅ | hermetic + **T2 跨进程真实**：True + SQL 确认；**T4 resume×2 真实**：两次 True |
| AC-8 | completed 不可复活 + 不存在/空id/开关关→False | ✅ | 白名单逐字 + rowcount=0；**T4/T5 真实**：completed→False 行零改动、开关关→False |
| AC-9 | resume 保留 checkpoint + SQL 不含四列字样 | ✅ | 四字样零出现断言；**T2 跨进程 load 逐值恢复 = "续跑不从头" 数据前提实证** |
| AC-10 | resume 不改 ContextVar + DB 异常上抛 | ✅ | 三 var 前后相等（同 run 断言）+ pytest.raises |
| AC-11 | SQL 作用域逐字 + DDL 无 REFERENCES/FOREIGN KEY/CREATE TRIGGER | ✅ | 契约测试逐字锁定 + DDL 零 diff 根本实证；**T3 真实父子隔离** |
| AC-12 | 参数作用域恰一条且 task_id==目标 | ✅ | finish/save/budget 各恰一条断言；**T3 真实**：finish(子) 父行 10 列快照零变化 |
| AC-13 | _SQL_FINISH 不含 checkpoint | ✅ | 文本断言 + **T2 前半真实**：failed 收口后 checkpoint 原值存活 |

### 7.2 边界条件验收

| AC | 要求 | 结果 | 测试证据 |
|----|------|------|----------|
| AC-14 | DDL 零改动（14 列一字不改） | ✅ | git diff src/database.py 空；TASKS_DDL 文本断言辅助锁 |
| AC-15 | 默认零行为变化 + 零 config | ✅ | 18 红线路径零 diff；三原语零生产调用方（grep）；存量 52 + api 257 全过 |
| AC-16 | 既有原语逻辑零改动 | ✅ | diff 实证唯一非追加 = docstring 2 行替换（Reviewer 偏离 1 裁定成立，AC-22 显式条款）；全部函数体零触碰 |
| AC-17 | 改动面收口（conftest 零 diff） | ✅ | git status 恰两项（M tasks.py + ?? test_checkpoint.py）；本轮唯一测试侧改动 = 本模块新文件内 LOW-1 补测 |

### 7.3 异常场景验收

| AC | 要求 | 结果 | 测试证据 |
|----|------|------|----------|
| AC-18 | DB 不可用分层（save fail-open / load-resume 上抛 / 序列化 warning） | ✅ | 三层各一用例（fake session 异常 pytest.raises ×2 + caplog）；T5 真实 save no-op |
| AC-19 | 无运行事件循环 → _spawn 窄捕获静默 | ✅ | 真实 _spawn 路径用例（不 mock）不抛 |

### 7.4 非功能验收

| AC | 要求 | 结果 | 测试证据 |
|----|------|------|----------|
| AC-20 | 全量回归 1730+24/0/3 | ✅ | **1754 passed / 0 failed / 3 skipped**（本轮收口，§1 #4） |
| AC-21 | AST ≤200 + 函数 ≤50 语句 | ✅ | 121 = 86 + 35 ≤ 200；最长 load_checkpoint 12 语句 |
| AC-22 | docstring/0 print/0 裸 except/参数化/模块 docstring 090 说明 | ✅ | Reviewer 复核 + 本轮 py_compile/AST 复算证实；grep 双 0 维持 |
| AC-23 | 红线总核验 | ✅ | §1 #8：18 路径零 diff + tests/ 仅新增 test_checkpoint.py + conftest 零 diff |

## 8. 验收结论

- **✅ 通过（PASS）。** AC-1~23 全部签署通过；全量回归 1754/0/3 与预期精确一致（新增 0 失败、存量零改动、3 skipped 基线同源）；T1-T6 真实 PG 对账 28 项断言全过——两大核心验收（T2 断点恢复不从头、T3 子失败父不连坐）在真实驱动层跨进程实证成立；Reviewer 移交项全部闭环（LOW-1 已补测、B1①② 真实驱动行为确认、B2 全量收口）。
- **版本演进：v0.90.0（module-090 收口，阶段 D 全收官）。**
- 给后续轮次的非阻塞归档：§5 发现-1（asyncpg JSONB str 形态为真实主路径）与发现-2（begin_task 返回值是 task_id 唯一来源）建议进入 T5 编排模块的 plan 前置注意项。

---

## 9. 验收签署

| 角色 | 结论 | 日期 | 签署 |
|------|------|------|------|
| Developer | 实现完成（changelog v1，偏离 6 项申报） | 2026-09-06 | Developer |
| Reviewer | 通过（PASS：0 阻塞 / 1 LOW + 2 备忘） | 2026-09-06 | Reviewer |
| Tester | **通过（PASS）：AC-1~23 全签 + 全量 1754/0/3 + T1-T6 28 断言全过 + LOW-1 补测 + B1/B2 闭环** | 2026-09-06 | Tester |
