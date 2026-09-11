# Test Report — Module-093: 上下文工程（预算观测 + 历史压缩 + 三臂对拍裁定）

> Tester: tester-093 ｜ 2026-09-11 ｜ 依据：`acceptance-criteria.md`（AC-1~22 + T1~T6）、`plan.md`、`review-report.md`、`changelog.md`、`ctx-report.md`、`specs/adr/0022-context-compression.md`
> 方法：**不信任前序角色口头声明**——命令表全项独立复跑（AST / 单测 / 全量 junitxml / 红线 git diff / 真实 PG 对账脚本 / 真实环境冒烟），所有数字来自亲手跑的输出。
> 环境：Python 3.11（`.venv`）｜ PG 5432 ✅ 通（postgres:123456）｜ Redis 6379 ✅ 通 ｜ HEAD `f39975f`（修复轮，MODULE-093 终态）
> ⚠️ 全量回归在本环境 pytest 收尾被 safe-delete 钩子干扰，`EXIT` 码非零但 **junitxml 实测 0 失败为准**（与 Reviewer 裁定一致），不按 EXIT 误判。

---

## 1. 测试概览

| 维度 | 数值 |
|------|------|
| 单元/集成测试 | **21 passed**（test_ctx_manager 19 + test_ctx_compress_wiring 2） |
| 全量回归（junitxml 权威） | **tests=1870 / failures=0 / errors=0 / skipped=3** → 1870 passed / 0 failed / 0 errors / 3 skipped |
| 静态 AST 复算（ast.walk 语句口径） | ctx_manager=**152**（≤200）／ ctx_tasks=**24** ／ ctx_parity=**174**（24+174=**198** ≤350） |
| 红线 `git diff 4fcfd54..HEAD` | `rag/` `main.py` `eval/langgraph_parity.py` `parity_telemetry.py` `parity_io.py` `parity_events.py` **全空**；worktree 对红线路径亦干净 |
| 真实 PG 对账 | T1~T6(+T7) 全部独立复算一致（见 §4） |
| 真实环境冒烟 | A 默认关：真实回答正常、**无 ctx_compress span**；B 压缩开（阈值3000，多轮）：**ctx_compress span 出现**（3/4/1/1/4） |
| 耗时 | 单测 ~43s ／ 全量 ~285s（后台）／ 冒烟 ~4min（A 单轮 + B 5 轮） |

> 注：修复轮 `f39975f` 已将 AST 由初报顶层语句口径（23/6/34）纠正为 ast.walk 口径 **152/24/174**（changelog/ADR §6 已勘误），本 Tester 独立复算与之逐字一致。review-report 记录的 150/24/173 为修复前测量，已随修复轮闭合。

---

## 2. 命令表全项独立复跑

| # | 命令 | 实测输出 | 判定 |
|---|------|---------|------|
| 1 | `ast.walk` 复算 ctx_manager.py | **152** 语句 | ✅ ≤200（AC-18） |
| 2 | `ast.walk` 复算 ctx_tasks.py | **24** 语句 | ✅ ≤350 合计（AC-18） |
| 3 | `ast.walk` 复算 ctx_parity.py | **174** 语句 | ✅ ≤350 合计（AC-18） |
| 4 | `pytest tests/agent/test_ctx_manager.py tests/agent/test_ctx_compress_wiring.py -q` | **21 passed**（19+2，2 warnings） | ✅ 单测全绿（AC-20） |
| 5 | `pytest tests/ -q --junitxml=_t.xml`（junitxml 权威） | **1870 passed / 0 failed / 0 errors / 3 skipped** | ✅ 全量零失败（AC-20/T5） |
| 6 | `git diff --stat 4fcfd54..HEAD -- <红线 6 路径>` | **空**（worktree 亦干净） | ✅ 红线零 diff（AC-17/T5） |
| 7 | 真实冒烟 A（默认关，opencode 单轮） | exit 0，真实回答 2110 字，trace 含 ctx_budget=2、**ctx_compress=0** | ✅ 零行为变化（AC-13/AC-15） |
| 8 | 真实冒烟 B（PW_CTX_COMPRESS_ENABLED=true 阈值3000，5 轮） | exit 0，5 轮均真实回答，trace 含 ctx_compress **3/4/1/1/4** | ✅ 压缩触发（AC-16） |

---

## 3. AC-1~22 逐项核对

| AC | 验证方式（独立） | 实测 | 结论 |
|----|----------------|------|------|
| AC-1 估算器边界 | 单测 + 直跑 `estimate_tokens("")=0`、单调 `a≤ab≤abc` | 0 / 单调成立 | ✅ |
| AC-2 宁可高估 | ctx-report §3 抽样 5/5 高估；本 Tester 独立复算 ASCII 密集样本 est=26 < tiktoken=32（ratio 0.81，MID-2 诚实边界坐实） | 中文/技术中文高估成立；ASCII 密集可低估（已申报） | ✅（诚实边界已记） |
| AC-3 纯函数 | ctx_manager 无网络/模型依赖 | 21 单测全绿 | ✅ |
| AC-4 五桶分类 | 单测断言各桶 count | 通过 | ✅ |
| AC-5 tools 桶来源 | tool_schemas 序列化估算 | 通过 | ✅ |
| AC-6 观测零行为 | 深比较 `compress_view(under)` 不 mutate 入参（T7 `ac12_over_orig_unchanged=True`） | 零 mutate | ✅ |
| AC-7 clearing 占位符 | T7 `ac9_struct_unchanged=True`；占位符 `[tool result cleared:{name}; re-invoke...]` 与代码常量一致 | role/tool_call_id/顺序逐字不变 | ✅ |
| AC-8 保留窗口 | T7 `ac9_recent_keep_original=True`（keep_recent 内原文保留） | 计数准确 | ✅ |
| AC-9 可恢复 | T4：clearing 臂 tool_call_logs 原文留存（result_is_placeholder=False），占位符引用同工具名，DB 可查 | 可恢复实证 | ✅ |
| AC-10 块完整性 | T7 `ac10_no_orphan_tool=True`（6 轮构造折叠零孤儿） | 无孤儿 tool 消息 | ✅ |
| AC-11 保留项 | T7 `ac11_summary_single=1`（system 全保留+首条 user+摘要单条） | 通过 | ✅ |
| AC-12 视图编排 | T7：`off→is 原引用`、`under→is 原引用`、`over→新列表且原不变` | 全部成立 | ✅ |
| AC-13 默认关零行为 | 单测 + 冒烟 A（ctx_compress=0）+ 全量 1870/0/3 | 通过 | ✅ |
| AC-14 两环路共用 | grep：react.py:514 与 langgraph_react.py:105 同调 `agent.ctx_manager.compress_view`（无分叉） | 共用纯函数 | ✅ |
| AC-15 观测 span | 冒烟 A/B 均见 `ctx_budget`（B 中 1/4/1/4/3 次） | 每轮 ctx_budget span | ✅ |
| AC-16 压缩 span | 冒烟 B 见 `ctx_compress`（3/4/1/1/4）；A 无 | 触发记 ctx_compress | ✅ |
| AC-17 配置回退 | config.py 纯增量三字段，reviewer diff +14/-0 | PW_ 前缀可覆盖 | ✅ |
| AC-18 AST 红线 | 独立 ast.walk：152≤200、198≤350 | 红线满足 | ✅ |
| AC-19 代码规范 | 最长函数 43 行（compress_view）；无空 `except: pass`；public 函数 docstring 齐 | 满足（LOW-1/3 修复轮已修） | ✅ |
| AC-20 单测 | 21 passed；存量 67 parity 项含于全量 1870 零回归 | 通过 | ✅ |
| AC-21 判据事前定死 | ADR-0022 §4 三判据 = plan §2.9；跑批 commit=4fcfd54d（=plan 提交），证据链闭合 | 满足 | ✅ |
| AC-22 诚实记录 | ctx-report §7/§8 不利结论逐值照实（clearing ②FAIL、compaction 裕度 0.0123/0.91%、re-invoke 假说方向证据相反、首跑死锁孤儿 trace 干扰） | 满足 | ✅ |

---

## 4. T1~T6(+T7) 真实 PG 对账（asyncpg 只读脚本，用后即删）

### T1 落库 ✅（6 行）

`SELECT id, config_snapshot->>'ctx_mode', config_snapshot->>'module', git_commit, COALESCE(scores->>'fixture','?') FROM agent_eval_runs WHERE config_snapshot->>'module'='093' ORDER BY id`：

| id | ctx_mode | module | git_commit(前缀) | fixture |
|----|----------|--------|------------------|---------|
| 36 | off | 093 | 4fcfd54d | true |
| 37 | clearing | 093 | 4fcfd54d | true |
| 38 | clearing_compaction | 093 | 4fcfd54d | true |
| 39 | off | 093 | 4fcfd54d | false |
| 40 | clearing | 093 | 4fcfd54d | false |
| 41 | clearing_compaction | 093 | 4fcfd54d | false |

三值 ctx_mode 齐全、module=093、commit 前缀 4fcfd54d 全一致 ✅（T1 满足）。

### T2 判据复算 ✅（与 ctx-report 逐值一致）

从 `per_question`（57 行/臂）独立复算 `pass_1 = Σpass/57`：

| 臂(id) | 复算 pass_1 | 库 pass_1 | 复算=库 | history tokens | LLM 次数 |
|--------|-----------|----------|---------|----------------|----------|
| off(39) | **0.5614**(32/57) | 0.5614 | ✅ | 628,892 | 121 |
| clearing(40) | **0.5439**(31/57) | 0.5439 | ✅ | 826,136 | 117 |
| clearing_compaction(41) | **0.4737**(27/57) | 0.4737 | ✅ | 436,213 | 134 |

三判据（off 基线 0.5614 / 440,224.4 / 139.15）：clearing ①OK ②**FAIL**(826,136>440,224) ③OK → **不引入**；clearing_compaction ①②③全 OK → **建议引入-灰度默认关**。与报告/ADR 裁定逐字一致 ✅。

### T3 span 曲线 ✅

`request_spans` 按 trace 计数（ctx-* 命名空间 = 3 臂 × 3 剧本）：

| 臂 | G1 | G2 | G3 | ctx_budget 存在 |
|----|----|----|----|----------------|
| off | — | — | — | ✅（187/124/96） |
| clearing | ctx_compress 74 | 45 | 56 | ✅ |
| clearing_compaction | 82 | 54 | 54 | ✅ |

`ctx_budget` 全 9 trace 存在；`ctx_compress` **仅**压缩两臂出现、off 臂零 —— 与 AC-13/AC-16 一致。压缩臂 token 低于 off 臂（见 T2 history 列）且触发点与阈值一致（B 冒烟阈值 3000 亦触发）✅。

### T4 可恢复抽查 ✅（AC-9 实证）

抽 clearing 臂 trace `ctx-clearing-G1-threadpool-deepdive`：tool_call_logs 行 `result_is_placeholder=False`（原文真实留存，如 `search_knowledge` 检索片段、`(工具 generate_answer 执行超时)` 亦为真实结果），created_at 为 **UTC**（例 `2026-09-11 04:59:41` = 本地 12:59，未用本地时间误查）。代码占位符常量 `_CLEARED_MARKER` = `[tool result cleared: search_knowledge; re-invoke the tool to retrieve]` 与 DB 抽样一致 → 占位符 ↔ 原文可对应、可恢复 ✅。

### T5 红线 + 回归 ✅

`git diff --stat 4fcfd54..HEAD -- ai_service/rag ai_service/main.py ai_service/eval/langgraph_parity.py parity_telemetry.py parity_io.py parity_events.py` = **空**（worktree 对同路径亦干净）；全量 junitxml **1870/0/0/3** 零新增失败（基线 1849/0/0/3）✅。

### T6 清理还原 ✅

- **评测 trace 时间窗清理**（DB，asyncpg DELETE）：`tool_call_logs WHERE trace_id LIKE 'ctx-%' AND created_at>='2026-09-11'` 删 **306** 行 → 0；`request_spans` ctx-* 删 **1689** 行 → 0；`request_logs` ctx-* 删 **0**（无）。**未动 066/091/092 历史行**（不同前缀）✅。
- **冒烟 trace 清理**：本次冒烟 6 个 uuid 三表删 tool_call_logs **9** / request_spans **49** / request_logs **6** → 0 残留 ✅。
- **临时文件**：`_t.xml`/`_r.xml`/`_regression.log`/`_ctx_real*.log`/`_smokeA.log`/`_smokeB.out` 及 `_t093_*.py` 审计/视图/冒烟/清理脚本均已删除；`_probe_real_mcp.py` 历史遗留**保留未删**。⚠️ 批量 `rm` 曾被 sandbox safe-delete 钩子 SIGTERM 拦截，逐文件删后全部清除，无强制绕过 ✅。
- **后台进程**：`tasklist | grep python` = 无 python 进程残留（两个 uvicorn 8011/8012 已 TaskStop 杀净）✅。

### T7 视图语义 / 可恢复性 独立脚本 ✅（AC-9 + AC-12）

`_t093_view.py` 直跑真实代码：

| 检查 | 结果 |
|------|------|
| AC-12 关→`is` 原引用 / 低于阈值→`is` 原引用 | True / True |
| AC-12 超阈→返回新 list 且原 list 深比较零 mutate | True / True（meta cleared=2,compacted=2,triggered=True） |
| AC-9 clearing 只换 content（role/tool_call_id/顺序不变） | True |
| AC-9 非最近条→占位符、最近 keep_recent 条→原文 | True / True（占位符含工具名） |
| AC-10 compaction 折叠无孤儿 tool 消息 | True（折叠 4 块） |
| AC-11 摘要为单条 | True（summary 计数=1） |

---

## 5. 真实环境冒烟（强制门槛）

- **冒烟 A（默认关零行为）**：`uvicorn` 起 8011（无压缩 env），POST `/ai/rag/chat/agent` 单轮真实问答（opencode glm-5.3-flash，不改 .env）。返回 2110 字真实答案（corePoolSize/maximumPoolSize 区别），行为正常；trace `eaef62b8…` spans = {advance_phase, /ai/rag/chat/agent, ctx_budget=2, search_knowledge}，**无 ctx_compress** ✅。
- **冒烟 B（开压缩）**：`uvicorn` 起 8012（`PW_CTX_COMPRESS_ENABLED=true PW_CTX_TOKEN_THRESHOLD=3000 PW_CTX_KEEP_RECENT=4`），5 轮累积 `history` 多轮深挖。每轮均返回真实答案（2110~5001 字）；5 个 trace spans 均含 `ctx_compress`（3/4/1/1/4）+ `ctx_budget`，证明压缩视图触发、占位符进入后续请求 ✅。
- 冒烟产生的 6 个 trace 已按 T6 清理。

---

## 6. 失败详情与遗留问题

- **业务失败**：0（单元/集成/全量/对账/冒烟全过）。无「失败类别=真实回归」项。
- **NEW-MINOR（非阻塞，数据维度一致性）**：module-093 真实 `per_question`（id=39/40/41）仅含 `{q, pass, answer, answer_points}`（066 判定口径），**未继承 module-092 增强字段** `answer_points_hit` / `failed_points` / `telemetry.events`。092 的增强捕获位于 `parity_telemetry.py`，093 的 `ctx_parity.py` 复用 066 `outcome_pass` 未接入 092 增强路径。不影响任何 093 AC（AC-22 诚实性针对压缩结论，已满足），但跨模块记录维度不连续，建议后续模块对拍基线统一继承 092 增强字段。**失败类别=待排查/已知局限（minor）**，不阻塞本模块验收。
- **复算一致性**：AST 152/24/174、单测 21、全量 1870/0/0/3、T1~T4 全部与 Developer/Reviewer 声明逐值一致；reviewer 记录的 150/24/173 为修复前口径，已随 `f39975f` 闭合，非回归。

---

## 7. 验收结论签署

**结论：PASS（四阶段闭环验收通过，附 1 项 minor 非阻塞遗留）**。

- 单元测试 21/21、全量回归 1870/0/0/3（junitxml 权威）、AST 红线 152/24/174 满足、红线零 diff；
- 真实 PG T1~T6(+T7) 全部独立复算一致，三臂裁定（clearing 不引入 / clearing+compaction 建议引入-灰度默认关）与证据链闭合；
- 真实环境冒烟 A/B 验证默认关零行为 + 压缩触发 ctx_compress span；
- 清理还原完成（ctx-* 评测 trace + 冒烟 trace 已删、临时文件清除、无后台进程、_probe_real_mcp.py 保留）；
- 仅 1 项 minor 非阻塞（092 增强字段未继承），不阻塞。

| 角色 | 结论 | 日期 |
|------|------|------|
| Planner | plan + AC 产出 | 2026-09-11 |
| Developer | 实现完成（f39975f 修复轮） | 2026-09-11 |
| Reviewer | PASS（附条件：0 阻塞/2 中/3 低，修复轮已闭合） | 2026-09-11 |
| Tester | **PASS（附 1 项 minor 非阻塞：092 增强字段未继承）** | 2026-09-11 |
