# Test Report — Module-091: LangGraph 复刻实验 → 转正对比（Tester 独立验收）

> Tester: 2026-09-07 | 依据：`acceptance-criteria.md`（AC-1~22 + T1-T6）
> 方法：**不信任前序角色口头声明**——命令表全项独立复跑 + 真实 PG 对账（asyncpg 直连，一次性只读脚本用后即删）
> 环境：Python 3.11（`ai_service/.venv`）| PG 5432 ✅ 通 | Redis 6379 ✅ 通 | HEAD `45f7cb959d33c291bff8758d3305b8730dd8e9ba`

## 1. 命令表全项复跑记录

| # | 命令 | 实测输出摘要 | 判定 |
|---|------|-------------|------|
| 1 | `python -m eval.langgraph_parity --mode fixture` | 36 行全 OK（at-001~503 六类路径）；`等价率: 1.0000  (36/36)`；`不一致条目：无（全部四维逐字等价）` | ✅ 与 parity-report.md §2 逐字一致（T2） |
| 2 | `python -m pytest tests/eval/test_langgraph_parity.py -q` | **15 passed**, 2 warnings in 13.62s | ✅ 与自报 15/15 一致（T5） |
| 3 | `python -m pytest tests/ -q` | **见 §3**（junitxml 口径） | 见 §3 |
| 4 | `git diff --stat -- ai_service/agent ai_service/src ai_service/main.py` | **空**（worktree 与 index 均空） | ✅ 红线零 diff（T5/AC-13） |
| 5 | AST 复算 `ast.stmt` 计数 | `AST_stmts= 193` | ✅ 与 changelog §二 一致（AC-14） |

WP-B 真实跑批**未重跑**（LLM 跑批 23 分钟 + 供应商配额消耗 + 会产生第二组落库数据破坏 id=4/5 证据）；改用 **T1/T3/T4 库内对账**替代——三轮独立复算全部对上（见 §2），指标真实性由库内 JSONB 与 tool_call_logs 交叉证实。

## 2. T1-T6 逐项结论（真实 PG，asyncpg 直连 postgresql://localhost:5432/personal_website）

### T1 双 run 真实落库 ✅

`SELECT id, config_snapshot->>'loop', config_snapshot->>'module', git_commit, scores->>'pass_1' FROM agent_eval_runs ORDER BY id DESC LIMIT 5`：

```
id=5 loop=langgraph module=091 git_commit=45f7cb959d33 pass_1=0.5833 tokens_total=138700 p95_ms=124427.5 per_question_n=12
id=4 loop=hand      module=091 git_commit=45f7cb959d33 pass_1=0.4167 tokens_total=143834 p95_ms=101654.5 per_question_n=12
id=3/2/1: module=None loop=None（存量行，未受影响）
```

- id=4/5 两行 ✅、loop 值互异 ✅、module=091 ✅、git_commit=45f7cb95…（运行时 HEAD）✅ → **AC-9 实证**

### T2 等价性复跑 ✅

独立复跑输出 `等价率: 1.0000  (36/36)`，与 parity-report.md §2 数值逐字一致，36 行全 OK 无异常跳过 → **AC-1/2/3/4/5 实证**（四维：actual_names/tool_count/answer/判定四规则在复跑输出中逐条 OK）。

### T3 指标可对账 ✅（从库内 JSONB 独立复算）

| 指标 | 报告值 hand | 库内复算 hand | 报告值 lg | 库内复算 lg | 判定 |
|------|-----------|--------------|----------|------------|------|
| pass^1 | 0.4167 | 5/12=0.4167 | 0.5833 | 7/12=0.5833 | ✅ |
| 工具正确率 | 0.5833 | 7/12=0.5833 | 0.7500 | 9/12=0.7500 | ✅ |
| tokens 总量 | 143834 | 143834 | 138700 | 138700 | ✅ |
| P50 ms | 48942.0 | 48942.0（duration_ms 复算） | 56922.0 | 56922.0 | ✅ |
| P95 ms | 101654.5 | 101654.5（duration_ms 复算） | 124427.5 | 124427.5 | ✅ |
| Grounding | 0.8030 | 0.8030（11 trace 均值） | 0.8636 | 0.8636（11 trace 均值） | ✅ |
| 失败清单 | hand 7 败 / lg 5 败 | at-003/004/005/105/107/303/501 / at-003/004/005/303/501 | 同左 | 逐条一致 | ✅ |

- grounding 口径勘误复现：须按 **每 trace 先算 result_ok 比例、再对任务取均值**（`agent_tasks.py:304` + `:266`），Tester 首次用全行汇总算得 0.7353/0.8286 不符，改按任务均值口径后逐字复现——**报告口径正确**。
- 复算失败原因列表与报告 §3.3 逐任务明细一致；`fail_reason` 全空（0 条运行期异常）→ **AC-12**（无静默重跑、无掩盖）。
- scores JSONB 17 字段齐全无 None（pass_1/pass_k/tool_correct_rate/args_rate/no_extra_rate/tokens_total/p50_ms/p95_ms/grounding 等）→ **AC-8**。

### T4 交替执行取证 ✅（双证据）

1. **代码结构**：`eval/langgraph_parity.py:253-256` `run_real` 外层 `for i, item in enumerate(tasks)` × 内层 `for loop in (LOOP_HAND, LOOP_LANGGRAPH)`——逐任务先 hand 后 langgraph，非先整段后整段。
2. **tool_call_logs 时间戳铁证**（09-07 当天 22 个 trace 组，UTC 08:12=本地 16:12 与 changelog 吻合）：

```
08:12:06 eval-at-002-hand-1      08:12:45 eval-at-002-langgraph-1
08:13:23 eval-at-003-hand-1      08:14:45 eval-at-003-langgraph-1
08:15:42 eval-at-004-hand-1      08:16:56 eval-at-004-langgraph-1
...（at-005/008/015/016/101 同构交替）...
08:34:09 eval-at-501-hand-1      08:34:23 eval-at-501-langgraph-1
```

严格 hand→langgraph 逐任务交替 → **AC-7 实证**。

### T5 红线复核 ✅

- `git diff --stat` 与 `git diff --cached --stat` 对 `ai_service/agent ai_service/src ai_service/main.py` **均空**（git status 仅新增文件 + memory/specs 文档修改，无 tracked 生产文件改动）→ **AC-13**
- 单测 15/15（13.62s）→ **AC-6**（patch 目标字符串断言在单测内锁定）

### T6 清理还原 ✅（删除行数如实申报）

| 清理项 | 执行 | 结果 |
|--------|------|------|
| 临时文件 10 个 | `rm -f _final_state.txt _probe_out.txt _prog.txt _rmlog.txt _rmlog2.txt _shellcheck.txt _v3.txt _verify2.txt _pytest_full.log _pytest_parity.log`（删前 `ls -la` 逐个确认：8 个 0 字节空壳 + 2 个为文件清单统计临时产物）+ Tester 自己的一次性脚本 `_t1_audit.py` | ✅ 全删；`_probe_real_mcp.py` **按要求保留**（历史遗留非 091 产物） |
| tool_call_logs 评测残留 | 删除 091 跑批行：`DELETE FROM tool_call_logs WHERE trace_id LIKE 'eval-at-%' AND created_at >= '2026-09-07'` → **DELETE 69**（536 → 467，回到 091 运行前基线） | ✅ 删 69 行 |
| agent_eval_runs id=4/5 | **保留**（按 changelog §六移交建议：验收证据；报告/ADR 引用其数据） | 如实记录：未删 |
| 评测记忆残留 | `SELECT COUNT(*) FROM documents WHERE source LIKE 'memory:eval-091-anon:%'` → **0**（脚本内 `_cleanup_eval_memory` 自清已生效） | ✅ 无残留 |
| 后台进程 | `netstat` 检查 LISTENING：仅 PG 5432 / Redis 6379 服务本体，**无 uvicorn/遗留评测进程**；无 8000/8080 监听 | ✅ |

**⚠️ Tester 发现-1（minor，见 §4）：changelog §六 的清理 SQL `DELETE FROM tool_call_logs WHERE trace_id LIKE 'eval-at-%'` 口径过宽**——库中尚有 449 行 066 先例遗留（trace_id `eval-at-002-1` 无 loop 段，2026-08-16 产生），按该 SQL 字面执行会**误删 066 历史数据**。Tester 改用加 `created_at >= '2026-09-07'` 的精确口径，仅删 091 自己产生的 69 行。建议 changelog §六 勘误 SQL。

## 3. 全量回归

`python -m pytest tests/ -q` 多次执行（首轮统计行被会话 safe-delete 钩子消息覆盖/污染退出码——pytest 运行自身产生的 Temp 垃圾文件超钩子阈值触发；清理 `pytest-of-white` 历史垃圾后干净复现）：

```
1769 passed, 3 skipped, 164 warnings in 118.20s (0:01:58)   EXIT=0
```

另一次 `--junitxml` 落盘口径：`tests=1772 failures=0 errors=0 skipped=3`（1772 = 1769 过 + 3 跳过）——与自报 **1769/0/3（基线 1754 + 新增 15）逐字一致**，零新增失败，算术自洽 ✅。

## 4. Tester 新发现问题（分级）

| # | 级别 | 描述 | 处置 |
|---|------|------|------|
| 1 | minor | changelog §六 T6 清理 SQL 口径过宽（`eval-at-%` 会误删 066 遗留 449 行），实际 trace_id 前缀模式未区分 loop 段 | Tester 已用 `created_at >= '2026-09-07'` 精确口径执行；建议 changelog §六 勘误 |
| 2 | minor | AC-16 严格口径：`print_equivalence`(:214)/`print_real`(:305)/`main`(:335) 3 个 public 函数 docstring 存在但缺 `Args:/Returns:` 段（签名自明的打印/CLI 函数） | 非阻塞；可下轮补齐或豁免口径声明 |

（其余对账偏差：grounding 首算不符系 Tester 用错汇总口径，改任务均值口径后逐字复现，非产物问题。）

## 5. AC 签署表（AC-1~22）

| AC | 验收项 | 判据与实测 | 结论 |
|----|--------|-----------|------|
| AC-1 | 等价性夹具跑通 | T2 复跑 36 行全 OK 无跳过 | ✅ |
| AC-2 | 工具序列等价 | 等价率 1.0000 (36/36) 逐字一致 | ✅ |
| AC-3 | 工具次数等价 | 36 条 tool_count 全 OK | ✅ |
| AC-4 | 答案等价 | 36 条 answer 全 OK | ✅ |
| AC-5 | 判定器四规则等价 | coverage/no_extra/args_ok/pass 全 OK | ✅ |
| AC-6 | 双 mock 点正确 | 单测 15/15（patch 目标字符串断言）；同对象勘误已在报告 §2 如实申报，AC-2 有效性不动摇（Reviewer 实例隔离核查成立） | ✅ |
| AC-7 | real 分支双跑交替 | T4 双证据（代码结构 + trace 时间戳） | ✅ |
| AC-8 | 三层指标齐全 | scores JSONB 17 字段无 None | ✅ |
| AC-9 | 落库双 run | T1：id=4/5、loop 互异、module=091、commit=45f7cb95 | ✅ |
| AC-10 | 判定确定性 | 无 LLM-as-judge，outcome 用 answer_points 确定性命中 | ✅ |
| AC-11 | 采样可切换 | per_question n=12 = `--sample 12`（random.Random(42)），报告标注 | ✅ |
| AC-12 | 失败不掩盖 | fail_reason 全空（0 异常），失败清单逐条可复算 | ✅ |
| AC-13 | 生产代码零改动 | git diff worktree+index 全空 | ✅ |
| AC-14 | 代码量 | AST 复算 193 ≤ 200 | ✅ |
| AC-15 | 方法/类规模 | max 函数体 21 语句 ≤50；无类 | ✅ |
| AC-16 | 文档字符串 | 12 函数有 docstring，3 个打印/CLI 函数缺 Args/Returns 段 | ✅（附 minor-2） |
| AC-17 | 无裸异常 | bare except=0；2 处 `except Exception` 均带注释 + fail-open 日志 | ✅ |
| AC-18 | 报告可复现 | 命令/commit/模型版本/样本量/配置快照齐备（§6/§3.1/§7） | ✅ |
| AC-19 | 三判据实测 | ①100% ✅ ②0.5833≥0.3667 ✅ ③tokens ×0.964 ✅ / P95 ×1.224 ❌——逐条实测值在报告 §1 | ✅ |
| AC-20 | 结论明确 | "维持自研"二选一，无模糊 | ✅ |
| AC-21 | ADR-0020 落盘 | 决策/判据/实测数据/被否决方案 4 要素齐备 | ✅ |
| AC-22 | 不利结论如实写 | LangGraph 质量全面占优（pass^1/工具正确率/Grounding/tokens）已写入报告 §1 与 ADR §决策，无回避 | ✅ |

**Tester 结论：22/22 通过（2 项附 minor 非阻塞备忘），T1-T6 全过，验收通过。**

## 6. 验收结论签署区

| 角色 | 结论 | 日期 | 备注 |
|------|------|------|------|
| Developer | ✅ | 2026-09-07 | changelog.md |
| Reviewer | ✅ | 2026-09-07 | review-report.md，PASS（0 阻塞 2 LOW） |
| Tester | ✅ **验收通过** | 2026-09-07 | test-report.md：T1-T6 全过、AC 22/22、全量 1769/0/3、清理删 69 行 trace + 10 临时文件；2 minor 备忘（清理 SQL 口径 / 3 函数 Args/Returns）非阻塞 |
