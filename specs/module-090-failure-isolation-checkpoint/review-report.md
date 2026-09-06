# 审查报告 — Module-090: 失败隔离 + checkpoint（子 Agent 失败不连坐 + 长任务断点恢复）

> Reviewer: 2026-09-06 | 审查对象：`specs/module-090-failure-isolation-checkpoint/`（plan.md v1 / acceptance-criteria.md / changelog.md）+ 1 个修改文件（ai_service/src/tasks.py，113 增 / 2 删）+ 1 个新增文件（ai_service/tests/api/test_checkpoint.py，423 物理行）
> 审查方法：全文件通读（tasks.py 405 行 + test_checkpoint.py 423 行均整读，不只读 diff）+ 独立测试复跑（定向 24 + 受影响存量 52 + api 全目录 257）+ git diff 逐文件红线甄别 + AST 行数差分机械化复算（git show HEAD vs 工作树独立重算）+ 三条 SQL 与 plan 草案逐字对照 + 编排者四项裁定执行核验 + changelog §五 6 项偏离逐项裁定。独立复跑数字见 §9，均与 changelog §四一致。

## 1. 审查结论

- **结论：✅ 通过（PASS）（0 阻塞 / 0 重大 / 1 LOW 非阻塞 + 2 备忘）——移交 Tester（全量回归 + T1-T6 真实 PG 对账）**

8 项重点核查全部成立并经独立复算/复跑证实：JSONB 绑定恒为字符串（json.dumps 后绑定，tasks.py:314-321，测试回读逐值断言 test_checkpoint.py:184-204）；三条 SQL 与 plan 草案逐字一致（tasks.py:89-92/96-99/104-107 对照 plan §1 裁定 2/3/4 草案，strip 串等测试锁定 test_checkpoint.py:125-142）；失败隔离契约测试真实锁得住（五 SQL 作用域子句 + DDL 无级联 + 参数作用域行为三层断言，test_checkpoint.py:144-155/384-423）；load 双解码兼容 + DB 异常上抛（tasks.py:344-350/339-343）；ContextVar 零触碰（新三原语函数体零 set/get，grep 实证；测试锁定 test_checkpoint.py:348-368）；红线 18 路径 git diff 全空（含 conftest.py 零改动）；AST 差分独立复算 **86 → 121 = +35 ≤ 200** 与声明逐字一致；24 项测试 hermetic 且断言实质（存量 test_tasks 32 + test_budget 20 零改动全过）。6 项偏离（changelog §五）逐项裁定全部成立（§3）。问题仅 1 项 LOW（load 的 str 形态非法 JSON 子分支无直接测试命中，行为 fail-safe）与 2 项备忘（真实驱动层行为归 Tester T2、全量回归归 Tester）。

## 2. 重点核查表（编排者指定 8 项）

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **JSONB 绑定恒为字符串**（087 真缺陷踩坑面）+ 序列化失败 warning 不炸调用方 | ✅ | tasks.py:315 `checkpoint = json.dumps(payload, ensure_ascii=False, default=str)` → :320-321 `_spawn(_SQL_SAVE_CHECKPOINT, {"task_id": task_id, "checkpoint": checkpoint})`——绑定值必为 str，绝无 dict 直绑。测试锁定：test_checkpoint.py:197-204（`isinstance(raw, str)` + json.loads 回读逐值：step/done 中文 ensure_ascii=False/nested 三层嵌套/ts→`str(ts)` 即 default=str 兜底）+ :198（`"检索" in raw` 证明未 ascii 转义）。序列化失败窄捕获 `(TypeError, ValueError)`（循环引用属 ValueError）→ logger.warning + return 不炸调用方：tasks.py:316-319；测试 :206-215（循环引用不抛 + 零 spawn + `"序列化失败" in caplog.text`）；warning 只记 task_id 不记 payload 内容（敏感日志面见 §7） |
| 2 | **三条 SQL 与 plan 草案逐字** + resume 的 rowcount 用法（偏离 6 预授权口径）在 asyncpg 方言下正确性 | ✅ | 逐字对照（Reviewer 人工 diff plan §1 草案 vs 源码）：_SQL_SAVE_CHECKPOINT（tasks.py:89-92）=`UPDATE tasks SET checkpoint = :checkpoint / WHERE task_id = :task_id`——**无 status 条件**（覆盖语义，对齐 _SQL_BUDGET :81-84）；_SQL_LOAD_CHECKPOINT（:96-99）=`SELECT checkpoint FROM tasks / WHERE task_id = :task_id`；_SQL_RESUME（:104-107）=`UPDATE tasks SET status = 'running', finished_at = NULL / WHERE task_id = :task_id AND status IN ('failed', 'running')`——白名单子句逐字、completed 拒绝。机械锁定：test_checkpoint.py:127-136 三段 strip() 串等 + :137-142（无 `{}`/`%`/`+` 拼接残留 + `:task_id` 在位）。rowcount 口径：tasks.py:378 `return bool(result.rowcount)`——SQLAlchemy asyncpg 方言将驱动状态串（"UPDATE n"）解析入 cursor.rowcount，UPDATE 可用；completed/不存在行 → "UPDATE 0" → False；Postgres 对 WHERE 匹配但值未变的行同样计数 → 悬挂 running 重复恢复恒 True（幂等语义与 SQL 无排他条件一致，tasks.py:104-107 无 `AND status='failed'` 排他）。hermetic 层以 fake rowcount 锁语义（test_checkpoint.py:299-307 rowcount=1→True / :320-329 rowcount=0→False），真实方言行为归 Tester T2 真实对账，异常时按 plan 裁定 2 预授权两段式回退（偏离 6，§3） |
| 3 | **失败隔离契约测试锁得住**（SQL 单行作用域逐字 + 参数作用域 + 既有原语不越权触父行） | ✅ | 契约三层均有实质断言：① 作用域子句逐字——test_checkpoint.py:147-150 五条 SQL（SAVE/RESUME/BUDGET/FINISH + LOAD）均含 `WHERE task_id = :task_id`（LOAD 为只读同作用域），其中三条新 SQL 另有 :127-136 全文串等兜底（任何 SQL 文本改动必炸测试）；② 参数作用域行为——:384-394（finish_task(子 id, error=True) → 恰一条 UPDATE spawn 且 `task_id == 子 id` + `status == "failed"`）、:396-413（save_checkpoint 与 set_task_budget 各恰一条且 task_id==目标 id）；③ 机制面——:415-423（TASKS_DDL 大写化后无 REFERENCES/FOREIGN KEY/CREATE TRIGGER + `_SQL_FINISH` 不含 "checkpoint"）。tasks 表无外键无触发器（087 DDL 零 diff 实证）+ 全部写 SQL 单行作用域 → 子 task 失败无任何 SQL 路径触父行；真实父子两行双向隔离归 Tester T3 |
| 4 | **load_checkpoint dict/str 双解码兼容** + str 非法 JSON → {}（偏离 3）+ DB 异常上抛（裁定②） | ✅ | tasks.py:344 `value = (result.mappings().first() or {}).get("checkpoint")`（行缺失 None 落入 :350 非 dict 防御 → {}，偏离 4 等价实现）→ :345-349 str 形态 json.loads 兜底、loads 失败窄捕获 `(TypeError, ValueError)` → {}（JSONDecodeError 属 ValueError 子类，偏离 3）→ :350 非 dict 一律 {}。dict 直返（asyncpg 默认形态）/str 兜底/行缺失：test_checkpoint.py:242-256；三态脏数据防御（list 直返 / 合法 JSON 解出非 dict / NULL）：:263-271。DB 异常上抛：tasks.py:339-343 execute 无任何 try 包裹 → test_checkpoint.py:282-288（fake session execute_error → pytest.raises(RuntimeError)）。**备忘**：:348-349 loads 抛错子分支无测试直接命中（LOW-1，§5） |
| 5 | **ContextVar 零触碰**（save/resume/load 不污染 _task_id_var/_budget_limit_var/_memory_write_var，089 语义隔离） | ✅ | grep 实证：tasks.py:295-379 三原语函数体零 `_var.set`/`_var.get`（三 ContextVar 的 setter 仅 begin_task :157/:159、set_task_budget :289、set_memory_write_mode :215 既有位置，均不在本轮 diff 中）。测试锁定：test_checkpoint.py:348-368（同一 asyncio.run 内 set 三 var → await resume_task → 三值前后相等，坑①合规）；_reset_task_context fixture 每用例复位三 var（:41-48，含 _task_id_var） |
| 6 | **6 项偏离逐项裁定**（changelog §五） | ✅ 全部成立 | 逐项裁定见 §3 |
| 7 | **铁律**（无裸 except / public docstring Args-Returns 齐全 / 方法 ≤50 行 / AST ≤200 独立复算） | ✅ | 无裸 except：tasks.py 新代码仅两处 `except (TypeError, ValueError)`（:316/:348），grep `except:` 双 0；0 print（grep 实证）。docstring：save_checkpoint Args/Returns（:304-309）、load_checkpoint Args/Returns/Raises（:327-335）、resume_task Args/Returns/Raises（:361-368）——齐且超配（对齐 087 `memory_write_allowed` 零参先例无适用面）。方法行数：三函数物理行 27/27/26，语句数 8/12/8 均远 ≤50。AST 独立复算：git show HEAD 86 → 工作树 121 = **+35 ≤ 200**（§9 机械重算，与 changelog §三 86→121 逐字一致；分解 1+3+3+8+12+8=35 自洽） |
| 8 | **测试质量**（24 项 hermetic、_reset fixture 复位齐全、断言实质、存量零改动实证） | ✅ | 24 项分布与 changelog §二表格逐项核对一致（2+7+6+6+3）。hermetic：唯一走真实 _spawn 的 test_no_loop_spawn_silent（:227-235）在 create_task 前即 RuntimeError 放弃零 DB 访问（:117-120 既有窄捕获）；load/resume 全部 monkeypatch `src.database.async_session_factory`；全程零真实 PG。_reset_task_context（:41-48）复位三 var 齐全（含 _task_id_var）；同步原语 save_checkpoint 直调不包 asyncio.run（:166/:173/:181/:192/:213/:222/:235）、async 原语包 run 且 var 同 run（坑①②合规，:359-366）。断言实质：绑定参数逐键（:197-204/:249-250）、SQL 文本逐字（:127-136）、commit 计数（:307）、零 DB 访问计数（:280/:340/:346）、spawn 恰一条（:193/:393/:404/:413）。**存量零改动实证**：git status 中 test_tasks.py/test_budget.py 未修改，复跑 32+20=52 全过（§9）= 087/089 语义未漂移 |

### 编排者四项裁定执行核验

| 裁定 | 结论 | 证据 |
|------|------|------|
| ① resume 后旧 checkpoint 保留（审计留底） | ✅ | _SQL_RESUME 仅置 status/finished_at 两列（tasks.py:104-107），零触碰 checkpoint/trace_id/intent/tokens_used——test_checkpoint.py:352-353 四列字样零出现逐字断言；真实恢复后 load 回读归 Tester T2 |
| ② load/resume DB 异常上抛 | ✅ | tasks.py:341-343/:375-377 execute 无 try 包裹；测试 :282-288 + :370-377 双用例 pytest.raises |
| ③ completed 不可复活确认 | ✅ | 白名单 `status IN ('failed', 'running')` 逐字（tasks.py:106）+ `"completed" not in _SQL_RESUME`（test_checkpoint.py:154）+ rowcount=0 行零改动语义（:320-329） |
| ④ 一 task 多 trace 顺延 T5 | ✅ | resume 不动 trace_id（tasks.py:104-107 无 trace_id 字样 + :352-353 测试锁定）；plan §8 待澄清 4 顺延口径未被破坏 |

## 3. 六项偏离逐项裁定（changelog §五）

| # | 偏离 | 裁定 | 依据 |
|---|------|------|------|
| 1 | 模块 docstring 2 行替换（唯一非纯追加改动，diff 实证 2 删 3 增）vs AC-16"仅纯追加" | **成立，合理** | AC-22 明文要求"模块 docstring 补 090 接管说明"，与 AC-16 字面冲突时按 090 显式条款执行是正确取舍；旧文本"不实现……checkpoint 逻辑（module-090）……仅结构预留（只存不执法）"在 090 接管后确已失真。改动局限：git diff 实证全部 2 处删除即旧 docstring 行，AST 语句数中性（docstring 仍为 1 个 Expr），AC-16 的实质（既有函数逻辑零改动）未被破坏——begin_task/finish_task/set_task_budget/get_task_overview/_spawn/_run_sql 函数体均不在 diff 中 |
| 2 | AST 实际 +35 vs plan 预估 ~26 | **成立** | 独立复算 86→121=+35（§9）；差额构成核实：plan 预估未计三个 def 节点（3）、函数内延迟导入 `from src.database import ...`（2）、docstring Expr（3）与 load 防御分支——changelog §三分解 1+3+3+8+12+8=35 逐项自洽且与源码逐函数实测一致。089 同款先例（~31→+35）双轮接受；总量远低于 200，plan §3 自设的"超 200 才晒表"条款未触发 |
| 3 | load str 形态非法 JSON → {}（plan 未言明 loads 抛错行为） | **成立** | 按"防御脏数据"同款哲学处理：窄捕获 (TypeError, ValueError) → {}，与 :350 非 dict 防御同出口；DB 层异常仍上抛（裁定②不受影响——异常分层只扩了解码层）。JSONDecodeError 是 ValueError 子类，窄捕获覆盖正确。配套建议见 LOW-1（该子分支无直接测试） |
| 4 | 行缺失检查用条件表达式 `(first() or {}).get("checkpoint")` 替代两分支显式写法 | **成立** | None 行经 `.get` 得 None 后落入 :350 非 dict 防御分支返回 {}，与 plan 伪码语义等价；RowMapping 实现 Mapping 协议（.get 由 mixin 提供）——hermetic 测试以真 dict 验证了调用形状，真实 RowMapping 行为归 Tester T2 真实行对账（备忘 B1）；省 2 语句属合理精简 |
| 5 | 测试 24 项 vs plan 预估 ~20 | **成立** | 24 项逐类核对（2+7+6+6+3）全部对应显式 AC 要求（AC-19 无 loop 真实 _spawn、AC-6/18 load/resume 异常上抛各 1、AC-5 非 dict 防御合并 1 例 3 形状）；全量预期 1754=1730+24 算术自洽；测试不计生产行数（module-073 先例） |
| 6 | resume rowcount 口径按 plan 预授权执行 | **成立** | plan 裁定 2 明文预授权（"rowcount → bool。若 asyncpg 方言下 rowcount 实测异常，预授权等价偏离：先 SELECT 判定 + 再 UPDATE 两段式"）；技术上 SQLAlchemy asyncpg 方言确实解析 "UPDATE n" 状态串（§2 #2），预授权偏离未实际触发；真实驱动确认归 Tester T2，若异常按预授权回退并届时申报——流程与 plan 完全一致 |

## 4. AC 覆盖核对（AC-1~23）

| AC | 要求 | 状态 | 证据（文件:行号） |
|----|------|------|------------------|
| AC-1 | save 门控三条件 → 零 spawn | ✅ | tasks.py:311-313 首行短路；test_checkpoint.py:162-182 三用例（空 id/开关关/非 dict 四形态）均 `calls == []` |
| AC-2 | JSON 字符串绑定 + 回读逐值相等 + 绝无 dict 直绑 | ✅ | tasks.py:315/:320-321；test_checkpoint.py:184-204（str 断言 + 中文/嵌套/datetime→str 逐值）；真实驱动往返归 Tester T1（禁 mock 充数） |
| AC-3 | 序列化失败 fail-open warning no-op | ✅ | tasks.py:316-319；test_checkpoint.py:206-215（循环引用不抛 + 零 spawn + caplog 断言） |
| AC-4 | save SQL 逐字无 status 条件 + last-save-wins | ✅ | tasks.py:89-92；test_checkpoint.py:127-129（串等）+ :152（`"status" not in`）+ :217-225（两次保存参数各自、task_id 恒定） |
| AC-5 | load 行缺失 {} / dict 直返 / str 兜底 / 非 dict 防御 | ✅ | tasks.py:344-350；test_checkpoint.py:242-271（dict/str/缺失/三态防御） |
| AC-6 | load 读侧不设闸 + 空 id {} + DB 异常上抛 | ✅ | tasks.py:337-338（无 tasks_enabled 判断）/:341-343 无 try；test_checkpoint.py:273-280（开关关 False 仍读到值 + 空 id 零 SQL）+ :282-288 |
| AC-7 | failed→True 置 running+finished_at=NULL；悬挂 running 幂等 | ✅ | tasks.py:104-107/:374-378；test_checkpoint.py:295-307（True + SQL 断言 + commit=1）+ :309-318（两次 True + executed==2） |
| AC-8 | completed 不可复活 + 不存在/空 id/开关关→False | ✅ | tasks.py:106/:370-371；test_checkpoint.py:320-329（rowcount=0→False）+ :331-346（三 False 形态 + 空 id 零 SQL + 开关关零 SQL） |
| AC-9 | resume 保留 checkpoint + SQL 不含四列字样 | ✅ | tasks.py:104-107；test_checkpoint.py:352-353（checkpoint/trace_id/intent/tokens_used 零出现）；恢复后真实 load 回读归 Tester T2 |
| AC-10 | resume 不改 ContextVar + DB 异常上抛 | ✅ | grep 实证 :295-379 零 var 触达；test_checkpoint.py:355-368（三 var 前后相等）+ :370-377（异常上抛） |
| AC-11 | SQL 作用域逐字锁定 + DDL 无 REFERENCES/FOREIGN KEY/CREATE TRIGGER | ✅ | test_checkpoint.py:144-155（五 SQL 子句 + FINISH status='running'）+ :415-422（DDL 三字样零出现；DDL 零 diff 为根本实证） |
| AC-12 | 参数作用域行为（finish/save/budget 恰一条且 task_id==目标） | ✅ | test_checkpoint.py:384-394/:396-413；真实父子两行对账归 Tester T3 |
| AC-13 | _SQL_FINISH 不含 checkpoint 字样 | ✅ | test_checkpoint.py:423（"checkpoint" not in _SQL_FINISH）；_SQL_FINISH 本体 tasks.py:56-61 零 diff |
| AC-14 | DDL 零改动（14 列一字不改） | ✅ | git diff src/database.py 为空（§9）；TASKS_DDL 文本断言为辅助锁（:415-422） |
| AC-15 | 默认零行为变化 + 零 config | ✅ | config.py/main.py 等 18 路径 git diff 全空（§9）；grep 实证三原语 v1 零生产调用方（仅 tasks.py 内定义 + docstring 提及）；存量 52 全过 |
| AC-16 | 既有原语逻辑零改动（git diff 仅纯追加） | ✅* | diff 实证唯一非追加为 docstring 2 行替换（偏离 1，§3 裁定成立）；全部函数体零触碰 |
| AC-17 | 改动面收口（tasks.py + test_checkpoint.py + conftest 零 diff） | ✅ | git status：M src/tasks.py + ?? tests/api/test_checkpoint.py；conftest.py/requirements.txt/frontend/backend 等零 diff（§9） |
| AC-18 | DB 不可用分层（save fail-open / load-resume 上抛 / 序列化 warning） | ✅ | 三层各有用例：save 落库走既有 _run_sql warning 链（tasks.py:125-139 零改动）；load :282-288；resume :370-377；序列化 :206-215 |
| AC-19 | 无运行事件循环 → _spawn RuntimeError 窄捕获静默 | ✅ | tasks.py:117-120 既有窄捕获（零新增处理代码）；test_checkpoint.py:227-235 走真实 _spawn 路径（不 mock），filterwarnings 注明 GC 良性警告成因 |
| AC-20 | 全量回归 1730+24≈1754 / 0 failed / 3 skipped | ⏳ Tester | 本轮未跑（Tester 活）；定向/存量/api 三层复跑全绿（§9）支持预期成立 |
| AC-21 | AST ≤200 + 函数 ≤50 语句 | ✅ | 独立复算 86→121=+35；最长 load_checkpoint 12 语句 |
| AC-22 | docstring Args/Returns 齐 + 0 print + 0 裸 except + SQL 参数化 + 模块 docstring 补 090 说明 | ✅ | §2 #7；模块 docstring :14-16 已述三原语接管（即偏离 1 的执行结果） |
| AC-23 | 红线总核验 | ✅ | §9 git diff 全空输出；tests/ 仅新增 test_checkpoint.py |

## 5. 问题列表

### LOW（1 项，非阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/tests/api/test_checkpoint.py | 263-271（对照 ai_service/src/tasks.py:346-349） | load_checkpoint 的 str 形态**非法 JSON** 子分支（json.loads 抛 JSONDecodeError → 窄捕获 → {}）无测试直接命中：test_non_dict_defense 三形状分别是 list 直返（不进 loads）、`json.dumps("plain")` 即 `'"plain"'`（**合法** JSON 解出非 dict）、None（不进 loads）——tasks.py:348-349 的 `except (TypeError, ValueError): return {}` 分支当前零覆盖。行为 fail-safe（异常路径返回 {} 与 AC-5 防御语义同出口）且 AC-5 条文未列举该子分支，故不阻塞 | LOW（测试覆盖缺口） | test_non_dict_defense 增补第 4 形状 `"{oops"`（非法 JSON 字符串）断言返回 {}；随 Tester 轮或下轮变更顺手补，不单独打回 |

### 备忘（2 项，非缺陷、留痕）

| # | 主题 | 说明 |
|---|------|------|
| B1 | 真实驱动层两项行为归 Tester T2 对账（偏离 4/6 的预授权兜底） | ① resume 的 `result.rowcount` 真实 asyncpg 方言行为（UPDATE 状态串解析）；② `(RowMapping or {}).get("checkpoint")` 真实行形态。两者 hermetic 层均以 fake 验证调用形状，机制层面技术上成立（§2 #2/#4），T2 真实 DB 对账（resume 返 True + status 翻转 + load 回读 payload 逐值）即可双双闭环；若 rowcount 实测异常按 plan 裁定 2 预授权两段式回退并申报 |
| B2 | AC-20 全量回归未跑（Tester 活） | 预期 1754 = 1730 + 24 / 0 failed / 3 skipped；Reviewer 已按派发完成定向 24 + 存量 52 + api 全目录 257 三层复跑全绿，全量收敛归 Tester |

## 6. 架构评估

- **分层/依赖方向**：✅ 无新依赖（`import json` 为标准库，requirements.txt 零 diff）、无循环依赖。三原语挂 src/tasks.py 与既有任务原语同层；顶层仅 src.config，`src.database.async_session_factory` 保持函数内延迟导入（tasks.py:339/:372，对齐既有 get_task_overview :394 与 _run_sql :133 先例）；无端点改动、无前端改动、无消费方（v1 原语先行，grep 实证零生产调用方）。
- **结构零侵入**：✅ 写侧照抄 089 set_task_budget 母本（同步 fire-and-forget + 非法值 no-op + UPDATE 无 status 条件覆盖语义）；读侧照抄 087 get_task_overview 先例（async + 异常上抛）；SQL 常量插在 _SQL_BUDGET 之后常量聚集区（:86-107），函数插在 set_task_budget 之后、get_task_overview 之前（:295-378），与 plan WP-A 位置指令一致。
- **DTO/契约**：✅ 无 schema 变更；checkpoint 列为 087 预留挂载点（DDL 零 diff），get_task_overview 既有 13 列透传零改动复用。
- **ADR**：本次无新 ADR——无新外部依赖、无偏离 plan 的架构决策（plan §6 明确不做新 ADR；6 项偏离均为实现层细节且 plan 预授权/AC 条款冲突按显式条款执行，裁定见 §3）。

## 7. 安全评估

| 项 | 结论 | 说明 |
|----|------|------|
| SQL 注入 | ✅ 通过 | 三条新 SQL 全参数化（tasks.py:89-92/96-99/104-107，仅 :checkpoint/:task_id 绑定），无 f-string/%/拼接（test_checkpoint.py:137-142 机械锁定）；task_id 值域为 uuid hex/调用方传入，均走绑定 |
| XSS | ✅ 不适用 | 零前端改动（frontend/ 零 diff） |
| 密码/API Key | ✅ 通过 | 无凭据触达；.env 零改动（红线核验 §9） |
| 敏感日志 | ✅ 通过 | 序列化失败仅记 task_id（tasks.py:317-318），不记 payload 内容（checkpoint 可能含业务进度数据，未落日志）；无新增 print |
| 危险兜底/静默失败 | ✅ 通过 | fail-open 面均为设计内且声明：save 落库走既有 _spawn→_run_sql warning 链（tasks.py:125-139，087 既有，本轮零改动）；序列化失败 warning 可观测（caplog 断言）非静默；load/resume 恢复侧异常上抛不吞（裁定②）——三层分层与 plan 裁定逐条一致，无新增吞异常点（新代码仅两处窄捕获且均显式返回安全值） |
| 权限/越权 | ✅ 不适用 | 三原语为行状态原语，v1 无调用方；resume 白名单挡 completed 复活（调用方 bug 面），单行作用域杜绝跨行触达 |

## 8. 铁律合规检查

- **铁律 1（读全文件）**：src/tasks.py 405 行、tests/api/test_checkpoint.py 423 行整文件通读；plan.md/acceptance-criteria.md/changelog.md 全读；test_tasks.py/test_budget.py 先例与 conftest.py:145 钉桩定点核验（不重读全文件，未改动）。
- **铁律 2（行数 ≤200）**：AST 差分独立复算 **+35 ≤ 200**（§9，机械重算非采信声明）；新增函数最长 12 语句 ≤50。
- **SQL 全参数化**：三条新 SQL 零拼接 ✅（测试机械锁定）。
- **0 裸 except / 0 print**：grep 实测双 0 ✅；新代码仅两处窄捕获 (TypeError, ValueError) ✅。
- **public docstring**：三新函数 Args/Returns（load/resume 另有 Raises）齐全 ✅（089 LOW-2 缺 Args 段问题本轮不存在）。
- **存量测试零改动**：git status 实证 tests/ 仅新增 test_checkpoint.py，conftest.py 零 diff；test_tasks 32 + test_budget 20 零改动全过 ✅。
- **红线零 diff**：18 路径逐项实测全空 ✅（§9，含 src/database.py TASKS_DDL、observability.py、rag/router.py、agent/tool_registry.py、mcp_server.py、requirements.txt、main.py、rag/engine.py、agent/react.py、agent/langgraph_react.py、rag/crawl/sanitize.py、tests/conftest.py、frontend/、backend/）。

## 9. 独立复跑输出（Reviewer，2026-09-06，不采信 Developer 声明；ai_service 目录，.venv/Scripts/python.exe）

```
1) pytest tests/api/test_checkpoint.py -q
   → 24 passed, 2 warnings in 11.77s                     [= changelog §四 24/24 ✓；warnings 为 starlette 环境预存]

2) pytest tests/api/test_tasks.py tests/api/test_budget.py -q
   → 52 passed, 2 warnings in 12.57s                     [= changelog §四 52 ✓；分项复核 32 + 20 ✓]

3) pytest tests/api/ -q
   → 257 passed, 0 failed in 17.45s                      [= changelog §四 257 ✓]

4) py_compile src/tasks.py tests/api/test_checkpoint.py
   → exit 0 无输出                                        [2 文件全过]

5) 红线 git diff --stat（18 路径：config/database/observability/verify_tasks/main/engine/react/
   langgraph_react/memory.py/router/tool_registry/mcp_server/requirements/sanitize/conftest/
   backend/frontend 等）
   → 输出为空（零 diff）✓；git status 变更面恰 M src/tasks.py + ?? tests/api/test_checkpoint.py
     （另 memory/*.md 与 specs/module-090-* 系角色产出物非代码）

6) AST 差分独立复算（git show HEAD vs 工作树，ast.stmt 口径）：
   src/tasks.py   86 → 121   +35 ≤ 200 ✓（与 changelog §三逐字一致；
                  逐函数分解 save 8 / load 12 / resume 8 + def×3 + SQL×3 + import×1 = 35 自洽）

7) grep 实证：三原语零生产调用方（仅 tasks.py 定义）；tasks.py 新代码段零 _var.set/_var.get；
   0 裸 except；0 print
```

## 10. 五轴评分

| 轴 | 分 | 依据 |
|----|----|------|
| 正确性 | 5 | 三 SQL 与 plan 草案逐字 + 门控/白名单/双兼容/异常分层全对；JSONB 字符串绑定（087 真缺陷面）实现正确且有机械锁；rowcount 预授权口径技术上成立；存量 52 + api 257 全绿 = 087/089 语义零漂移 |
| 完整性 | 4 | AC-1~23 代码侧全落地、编排者四项裁定全执行、6 偏离全部申报且裁定成立；扣 1 分：load 非法 JSON str 子分支无直接测试（LOW-1，fail-safe 不阻塞） |
| 清晰性 | 5 | 注释带坑位与条款引用（087 教训/089 先例/plan 裁定号）；docstring Args/Returns/Raises 齐全（089 的 LOW-2 类问题本轮不存在）；changelog §六核查建议表与实际证据链对得上 |
| 可维护性 | 5 | 严格复用 087/089 既有型（fire-and-forget/非法值 no-op/读侧上抛先例/_capture_spawn/_FakeSession）；conftest 零改动 fixture 全本地化；开发期脚手架修复 2 轮根因已归档 changelog §二 |
| 安全性 | 5 | SQL 全参数化无注入面、敏感数据不入日志、无新增吞异常点、fail-open 边界与 plan 声明一致、completed 复活面被白名单挡住 |

## 11. 审查总结

- **通过**。实现与 plan v1 的 7 大裁定及编排者四项待澄清裁定逐条吻合；Developer 自测声明全部独立复验（定向 24/24、存量 52/52、api 257/257、py_compile、AST 86→121=+35、红线全空）——**未发现虚报**。6 项偏离（changelog §五）逐项裁定全部成立，其中偏离 1（docstring 2 行替换）系 AC-16 与 AC-22 条款冲突按 AC-22 显式条款执行、局限 docstring 字符串且函数体零触碰，裁定合理。
- **给 Tester 的重点测试项**：① 全量回归预期 **1754 passed = 1730 + 24 / 0 failed / 3 skipped**；② T1 JSONB 真实落库往返（中文/嵌套/datetime 逐值，AC-2 终验，禁 mock 充数）；③ T2 断点恢复跨 asyncio.run 重启模拟——**顺带闭环 B1 两项**：resume 返 True 真实 rowcount 行为 + 真实 RowMapping `.get("checkpoint")` 形态（异常时按 plan 裁定 2 预授权两段式回退并申报）；④ T3 父子两行双向隔离；⑤ T4 幂等边界（save×2 / resume×2 / completed→False 行零改动）；⑥ T5 开关关边界（变量名逐字 `PW_TASKS_ENABLED`，load 读侧不设闸实证）；⑦ T6 探针清理还原。
- **给 Developer 的非阻塞遗留**（可随下轮变更顺手处理，不单独打回）：LOW-1 test_non_dict_defense 增补非法 JSON 字符串第 4 形状（锁定 tasks.py:348-349 分支）。
- **记忆三件套**已按 PASS 态更新（project-context 090 行 + file-index review-report.md 登记 + activity-log [REVIEW]/[HANDOFF] 行）。
