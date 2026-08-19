# Module-072 测试报告 — 意图路由 Backlog 前三项（上下文改写接入 + WP-D 接线 + 改写喂路由评估）

> Tester：2026-08-19 | 验收基线：plan.md / acceptance-criteria.md / changelog.md / review-report.md
> Review 结论：✅ PASS（二轮复审，进 Tester）
> **验收结论：✅ 通过（全量回归 + 新增单测 + DB 直查 + 真实评测复跑四重独立验证，数字与 changelog 逐字一致）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1225 passed / 0 failed（199.73s）** = 1183 基线 + 42 新增 |
| 新增单测（WP-A） | `tests/retrieval/test_query_rewrite_history.py` **26 项全绿** |
| 新增单测（WP-B） | `tests/agent/test_tool_history_wiring.py` **12 项全绿** |
| 新增单测（WP-C） | `test_golden_intent.py` +2（短路测量）+ `test_golden_multi_turn.py` +2（快照契约）全绿 |
| 存量 WP-D 3 项 | `test_multi_turn_routing.py -k tool_history` **4 passed, 31 deselected**（3 项直调 + 1 相关项全绿，零改动） |
| 存量受影响套件 | test_multi_turn_routing + test_golden_multi_turn + test_query_rewrite + test_tool_call_logs + test_golden_intent 合计 **116 passed** |
| 存量测试改动 | 仅 `conftest.py`（+14 行 autouse fixture）+ `test_golden_intent.py` 快照断言扩展（plan WP-C 明确许可"或既有快照断言处（扩展）"）；其余存量测试 **零改动**（git diff tests/ 核对） |
| 新增单测 mock 性 | 全 mock 零真实 LLM/DB/模型（fixture 模式零依赖） |
| warnings | 147 条与基线同源（Redis setex 弃用 / SAWarning 连接清理，非本模块引入） |

## 二、任务清单逐项核对（新增单测覆盖点）

| 任务要求 | 覆盖文件 | 结果 |
|----------|----------|------|
| llm_rewrite 上下文分支：prev 传入 | `test_query_rewrite_history.py::TestLlmRewritePrev`（6 项：上下文 prompt 含"上一轮问题/当前省略句"段 + prev=None 走 049 原模板逐字零回归） | ✅ |
| llm_rewrite 保真双锚 | `TestPrepareHistory`（prepare/prepare_query/contextual_rewrite 三路径锚点 = `f"{prev} {query}"` 断言；无 history → 锚点 = query） | ✅ |
| llm_rewrite 回退 None | 超时（monkeypatch 0.01s）/异常/空/无变化四态 → None 断言 | ✅ |
| resolve_tool_history join 正确性 | `test_tool_history_wiring.py::TestResolveToolHistory`：SQL 形态（request_logs 按 identity + endpoint IN ('agent','agent-lg') LIMIT 1 → tool_call_logs 按 trace_id）+ 全参数化绑定断言 | ✅ |
| resolve_tool_history fail-open None | 无记录/无工具/DB 异常/TimeoutError → None；空 identity 零 DB 访问 | ✅ |
| resolve_tool_history 2s 超时 | `asyncio.wait_for(2s)` 同源 TimeoutError → None 断言（代码 `_TOOL_HISTORY_TIMEOUT = 2.0` 核对） | ✅ |
| 三处 classify 传参 | `TestClassifyWiring`：engine.chat 默认分支 + 改写分支（`tool_history=["search_knowledge"]` 透传断言）、chat_stream（main.py L523-525）、graph.classify_intent（`state.get("tool_history")` + 未设置 None） | ✅ |
| 开关默认 false | **生产默认已按 WP-C 四跑达标改 true**（config.py 注释含决策理由，PW_ 回退保留）；测试环境 conftest autouse `default_rewrite_switches_disabled` 钉住两开关 false（hermetic，存量引擎测试以改写前行为为准）——与 acceptance §1.4"conftest 新增 autouse fixture 钉 contextual_rewrite_enabled=False"一致 | ✅ |

## 三、真实评测复跑（Tester 独立执行，未采信 changelog 数字）

### 3.1 DB 直查（四跑落库 id=53-56，与 changelog 逐字核对）

| eval_runs id | 评测集 | qr 快照 | accuracy / 意图保持 | 检索提升 | 短路统计 |
|---|---|---|---|---|---|
| 53 | intent（100） | False | 1.0000 | - | fired=0 |
| 54 | intent（100） | True | 1.0000 | - | **fired=50 / correct=50 / accuracy=1.0** |
| 55 | multi_turn（12） | False | 意图 1.0000 | **+0.6000** | - |
| 56 | multi_turn（12） | True | 意图 1.0000 | **+0.6000** | - |

- **短路零误杀独立分解（id=54 per_question 直查）**：50 条短路样本 reason 均含"分诊命中 FTS 术语，短路 knowledge"，**label 全部 knowledge、correct 全部 True（wrong=0）**；非短路 50 条无 reason 标记。
- **目标场景"为什么"实测（id=55/56 per_question 直查）**：follow_up="为什么" prev="什么是Java线程池？核心参数有哪些？" → rewrite_changed=True、rewritten="为什么需要Java线程池？"、**raw_overlap 0.0 → rewritten_overlap 0.6**、routed=knowledge（多轮"为什么"检索落空实测修复）。

### 3.2 真实复跑（真实 DeepSeek + Docker PG/Redis + bge-m3，2026-08-19 本日）

**golden_multi_turn 两态复跑**（on = 生产默认 `query_rewrite_enabled=True`，off = `PW_QUERY_REWRITE_ENABLED=false`）：

| 新落库 id | 开关态 | self_contained | 意图保持 | raw_intent | 检索提升 |
|---|---|---|---|---|---|
| 57 | on（生产默认） | 0.0833 | **1.0000（12/12）** | 0.9167 | **+0.6000** |
| 58 | off | 0.0833 | **1.0000（12/12）** | 0.9167 | **+0.6000** |

- 两态与 id=55/56 逐字一致（含"为什么"对 overlap 0.00→0.60、改写文本生成成功）；意图保持 off/on 均 12/12 → `on ≥ off − 0.01` 达标线成立。
- 注：id=57 快照 ctx=True（当前生产默认）、id=58 ctx=True；id=55/56 当时快照 ctx=False（开关默认改 true 之前）——eval 检索侧 contextual_rewrite 恒度量生产封装（不受 settings 门控，Reviewer LOW#2 已记录口径），两态对照正确。

**golden_intent 复跑（短路判对率）**：见 §三.3（落库 id 以实跑输出为准）。

### 3.3 golden_intent 短路复跑（on 态，生产默认，落库 id=59）

```
Dataset: 100 queries | Evaluated: 100 | Skipped: 0
Accuracy: 1.0000
短路路由（module-072 WP-C，确定性零 LLM）: 触发 50 条，判对 50/50 （判对率 1.0000）
Confusion Matrix: casual 30/0/0 | knowledge 0/50/0 | realtime 0/0/20（零误分类）
Per-Class P/R/F1: 三分类全 1.0000
```

与 id=54 逐字一致（Accuracy 1.0000 + 短路 50/100 判对率 100% + 30 casual / 50 knowledge / 20 realtime 零误杀）——短路为纯确定性信号（triage FTS 术语 + `_rule_hits`，零 LLM），复跑稳定复现。

## 四、实现抽查（与 changelog 一致）

| 项 | 抽查结果 |
|----|----------|
| llm_rewrite prev 分支 | query_rewrite.py L123-161：prev 非空 → `_CONTEXTUAL_REWRITE_PROMPT`（自 golden_multi_turn 迁移，含"上一轮问题/当前省略句"段）；None → `_REWRITE_PROMPT` 逐字零回归；失败/超时/空/无变化 → None | ✓ |
| 保真双锚 | prepare L250 / prepare_query L310 / contextual_rewrite L345 均 `f"{prev} {query}"`，阈值 `rewrite_fidelity_threshold` 0.6；无 history 锚点 = query | ✓ |
| precise 不受 history 影响 | prepare L237-239 直接返回零 LLM（单测 llm_mock.assert_not_called） | ✓ |
| contextual_rewrite 单一来源 | golden_multi_turn.py L227 `from rag.retrieval.query_rewrite import contextual_rewrite`（eval-only 本地实现已删，diff -30 行） | ✓ |
| engine.chat 接线 | L308 hoist `resolve_tool_history(identity)` → L312 prepare 条件 OR → L332 短路显式加 `settings.query_rewrite_enabled and` 守卫（contextual-only 不扩散短路）→ L339/L343 两 classify 分支传 `tool_history` | ✓ |
| _retrieve 接线 | 签名 history=None 默认；L811 缓存 key 附 prev sha256[:12]（防串话题）；L837 prepare_query 条件同改 | ✓ |
| main.py chat_stream | L523-525 classify 传 tool_history；L550 `_retrieve(request.query, top_k=20, history=request.history)` | ✓ |
| graph.py | L91-93 classify_intent 传 `state.get("tool_history")`；RAGState 可选字段（state.py L26-27），make_initial_state 不设默认 | ✓ |
| config | `query_rewrite_enabled=True` + `contextual_rewrite_enabled=True`，注释含四跑决策与理由，PW_ 回退保留 | ✓ |
| conftest 钉子 | autouse `default_rewrite_switches_disabled` 钉两开关 false（对齐 056/058/066 模式） | ✓ |
| router.py 零改动 | `git diff --name-only` 无 router.py 条目 | ✓ |
| 代码改动范围 | 16 文件 457+/68-，含文档（CONTEXT/METRICS/记忆三件套）；代码 9 文件 + 测试 5 文件，与 changelog 声明一致 | ✓ |

## 五、诚实边界与观察（非阻塞）

1. **检索提升 n=1 统计功效**：12 对仅 1 对（"为什么"）触发改写，delta 基于单对——本日复跑两态同口径复现 +0.6000，方向与 module-063 归因一致，如实标注（changelog 诚实边界 #1）。
2. **self_contained 度量口径**：0.9167→0.0833 为 triage-precise 语义（11/12 含 FTS 术语自包含句不改写），acceptance §1.3 已补口径注释（Reviewer 裁定接受），Tester 检查单按"改写能力不降"口径（vague 句 0/1→1/1）判定 ✅。
3. **id=57/58 与 id=55/56 的 ctx 快照差异**：默认开关时序差异（四跑在改默认前），eval 检索侧不改写行为不受影响（对照正确）。
4. **resolve_tool_history 陈旧信号**：LIMIT 1 无时间窗过滤，风险被 router 短句 + `_deterministic_confirm` 无特征才生效的条件天然收敛（router.py 既有逻辑零改动）。
5. **LLM 非确定性**：本日复跑 deepseek 无 429 抖动；"为什么"改写文本两跑不同（"为什么需要Java线程池？"/"为什么Java线程池需要这些核心参数？"）但保真/检索/路由结果一致——非确定性如实标注（改写温度 0.1 + 保真门控收敛）。
6. **单测 hermetic 边界**：新增 42 项全 mock 零真实 LLM/DB/模型；conftest autouse 钉住两开关保证存量引擎测试不触发真实改写。

## 六、AC 逐条对照（关键项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| §1.1 llm_rewrite prev 分支 / 回退 None | ✅ | 单测 6 项 + 实现核对 |
| §1.1 prepare/prepare_query history 透传 + 双锚 | ✅ | 单测 5 项（锚点逐字断言） |
| §1.1 triage precise 不受 history 影响 | ✅ | 单测 llm_mock.assert_not_called |
| §1.1 engine.chat / _retrieve / main 接线 | ✅ | 实现核对 + 单测 7 项（开关组合 + 缓存 key） |
| §1.1 contextual_rewrite_enabled=False 零回归 | ✅ | conftest 钉子 + 存量全量 1225/0 |
| §1.2 resolve_tool_history（SQL/参数化/超时/fail-open/空 identity） | ✅ | 单测 6 项（SQL 形态 + 绑定参数断言） |
| §1.2 三处 classify 传参（engine 两分支 + chat_stream + graph） | ✅ | 单测 6 项透传断言 |
| §1.2 router.py 零改动 | ✅ | git diff --name-only 无 router.py |
| §1.3 快照两键 | ✅ | 两脚本 record_eval_run 补键 + 快照契约单测 4 项 |
| §1.3 四跑落库 + 达标线 | ✅ | DB 直查逐字一致；on ≥ off − 0.01 三线 + 短路 50/100 判对率 100% 全达标 |
| §1.3 两开关独立决策 | ✅ | 独立评测独立决策；短路只随 query_rewrite_enabled（engine L332 守卫） |
| §1.4 全量回归 基线+新增 / 存量零改动 | ✅ | Tester 独立复跑 1225/0；git diff tests/ 仅许可内改动 |
| §2.1 resolve_tool_history ≤2s | ✅ | wait_for 2s 上限 + fail-open（代码核对） |
| §2.2 SQL 全参数化 / 只读 | ✅ | 单测绑定参数断言 + SELECT-only |
| §2.3 功能代码 ≤110 行 | ✅ | WP-A 55 + WP-B 45 口径（Reviewer 复核 ~110-120 含注释，验收"默认 ≤200 达标"） |

## 七、结论

**验收通过。** 关键验证点：
1. 全量 1225/0 独立复跑全绿（199.73s），存量测试零改动（仅 conftest autouse + plan 许可的快照断言扩展）；
2. 新增 42 项单测（26 + 12 + 2 + 2）全部覆盖任务清单（llm_rewrite prev 分支/双锚/回退 None、resolve_tool_history join/fail-open/2s 超时、三处 classify 传参、开关钉子），全 mock hermetic；
3. 存量 WP-D 3 项直调单测保持绿（-k tool_history 4 passed）；
4. eval_runs id=53-56 DB 直查与 changelog 逐字一致（含短路 50/100 零误杀、目标场景 0.00→0.60 实测修复）；
5. 真实评测复跑（Tester 独立执行）：golden_multi_turn on/off 两态（id=57/58）+ golden_intent on 态，数字与 changelog 一致；
6. 开关默认值：两开关生产默认 true 系 WP-C 四跑达标后决策（acceptance §1.3 决策流程执行），测试环境 conftest 钉 false 保 hermetic——与任务清单"开关默认 false"的差异为计划内决策演进（达标才开），changelog/review 已记录。

**模块状态：✅ 验收通过（待 Developer 提交推送后协调者收口 + 主 checkout 04 文档标记）**
