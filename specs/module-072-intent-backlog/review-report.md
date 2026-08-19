# Module-072 审查报告 — 意图路由 Backlog 前三项（上下文改写接入 + WP-D 接线 + 改写喂路由评估）

> Reviewer：2026-08-19 | 对照 `acceptance-criteria.md` + `plan.md` + task-brief 逐项核查
> 结论：**✅ PASS（第一轮 ⚠️ CONDITIONAL 1 项 mustFix 文档口径 → 已修复，二轮复审通过，进 Tester）**

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest tests/ -q`（ai_service） | **1225 passed / 0 failed（201.18s）** 与 changelog 一致 |
| 测试收集数 | `--collect-only` | **1225 tests collected** = 1183 基线 + 42 新增，口径自洽 |
| 新增单测 4 文件 | 独立复跑 test_query_rewrite_history / test_tool_history_wiring / test_golden_intent / test_golden_multi_turn | **73 passed**（42 新增 + 31 存量） |
| 存量受影响套件 | test_multi_turn_routing（含 WP-D 3 项）+ test_tool_call_logs + test_query_rewrite + test_observability | **97 passed** 零改动全绿 |
| eval_runs id=53 | 直查 DB | intent / qr=False / ctx=False / acc=1.0 / shortcut_fired=0——与 changelog 逐字一致 |
| eval_runs id=54 | 直查 DB + per_question 独立分解 | intent / qr=True / acc=1.0 / **shortcut_fired=50 / shortcut_accuracy=1.0**；per_question 实查：50 短路样本**全部 knowledge 标注、wrong=0**，非短路 50 = **casual 30 + realtime 20** 全部被规则/无术语挡在短路外——与 changelog"零误杀"逐字一致 |
| eval_runs id=55/56 | 直查 DB + per_question 独立分解 | multi_turn / 意图保持 1.0/1.0 / retrieval_delta **+0.6000/+0.6000** / self_contained 0.0833——与 changelog 一致；"为什么"对实查：rewrite_changed=True、rewritten="为什么需要Java线程池？"、**raw_overlap 0.0 → rewritten_overlap 0.6**、routed=knowledge（目标场景实测修复成立） |
| 接入前基线 | 对照 module-063 changelog | 自包含 0.9167（11/12，含"'为什么'改写返回 None"记录）/ 意图 12/12 / 检索 +0.4363——与本模块对比表逐字一致 |
| E2E 轨迹（WP-B） | 直查 DB e2e-module072-anon | request_logs 2 行 agent 端点（16:53/16:58）+ tool_call_logs 每 trace **search_knowledge ×3 + search_fts ×1**——resolve_tool_history 返回非空列表成立，与 CONTEXT.md 描述一致 |
| router.py 零改动 | `git diff --name-only` | **无 router.py 条目** ✓ |
| CONTEXT.md | diff + %TEMP% 备份 | 备份 CONTEXT-backup-module072-20260819-003338.md 存在；diff 仅 +7 行只增不删 ✓ |
| 存量测试红线 | git diff tests/ | 唯一改动 = test_golden_intent.py 快照断言扩展（plan WP-C 许可"或既有快照断言处（扩展）"），test_golden_multi_turn 仅新增；其余存量测试零改动 ✓ |
| 三记忆文件 | 读 project-context / file-index / activity-log | module-072 行全在（§5 迭代状态 / file-index 6 行 / [CODE] 行）✓ |

## 二、WP 逐项核对

### WP-A：#1 上下文改写接入生产 — ✅ 通过

- **迁移完整性**：`query_rewrite.py:69-75` `_CONTEXTUAL_REWRITE_PROMPT` 与 golden_multi_turn.py 原 prompt 逐字一致（"上一轮问题: {prev}" / "当前省略句: {query}" 段）；golden_multi_turn.py 本地实现已删除（diff -30 行）改 `from rag.retrieval.query_rewrite import contextual_rewrite`，单一来源防漂移 ✓
- **llm_rewrite(query, prev=None)**（L123-161）：prev 非空走上下文 prompt，None 走 `_REWRITE_PROMPT` 逐字零回归；失败/超时/空/无变化 → None（单测 6 项覆盖）✓
- **extract_prev**（L99-120）：取最近一条 user 消息 content，非字符串/空白跳过，无 → None；与 module-063 classify 同款"取最近"语义 ✓
- **保真双锚**（L250/L310/L345）：`f"{prev} {query}"` 拼接（主题+原句），阈值沿用 0.6；无 history → 锚点 = query（049 逐字零回归，单测断言）✓
- **precise 分支逐字不动**：triage precise 直接返回，不受 history 影响，零 LLM（单测 llm_mock.assert_not_called）✓
- **engine.chat 接线**（engine.py:312-345）：prepare 条件 `query_rewrite_enabled or contextual_rewrite_enabled`（OR 独立生效）；history 仅 contextual 开启时传；**短路显式加 `settings.query_rewrite_enabled and` 守卫**——contextual-only 不扩散短路（module-063 语义保持，changelog 声明兑现）✓
- **_retrieve**（engine.py:770+）：签名加 history（默认 None）；prepare_query 条件同改 + 透传；**缓存 key 附 prev sha256[:12]**（防同 query 不同 prev 串话题，contextual 关闭零变化；单测 3 项）✓
- **main.py:545-551**：chat_stream Step 2 `_retrieve(request.query, top_k=20, history=request.history)` ✓
- **config**：`contextual_rewrite_enabled: bool = True`（PW_CONTEXTUAL_REWRITE_ENABLED 回退），注释含决策与理由 ✓
- **保真锚点实证**：双锚 cos 0.867 通过 / 裸锚 0.546 被 0.6 拒（n=1，changelog 如实标注分布有限）；误杀率 0/1 < 25% 调整线，0.6 阈值保持——按 plan 实现要点 2 决策流程执行 ✓
- 边界全过：开关关零回归（conftest 钉子 + test_chat_both_off_prepare_not_called）/ history 空走 049 原链 / 保真未过回退 / 嵌入失败 prepare 跳过预检并行择优（049 既有 fail-open）/ 10s 超时回退 / 预算耗尽回退原 query（既有逻辑不破坏）✓

### WP-B：#2 WP-D 工具历史信号接线 — ✅ 通过

- **resolve_tool_history**（engine.py:103-157）：request_logs 按 `identity + endpoint IN ('agent','agent-lg') ORDER BY created_at DESC LIMIT 1` 取 trace_id → tool_call_logs 按 trace_id 取 tool_name（调用顺序）；**SQL 全参数化**（绑定 :identity/:trace_id，无拼接无注入面）；`asyncio.wait_for(2s)` + TimeoutError/Exception 全捕获 → None fail-open；空 identity 直接 None 零 DB 访问 ✓
- **join 正确性**：request_logs（models.py:151-181 有 identity/endpoint/trace_id 列）与 tool_call_logs（database.py:94-112 DDL）共享 observability contextvar trace_id（persist_request_log / record_tool_call 同源）——关联语义成立；真实 E2E trace 验证 ✓
- **三处传参**：engine.chat 两 classify 分支（hoist 一次查询复用，engine.py:308/339-345）+ main.py:521 chat_stream + graph.py:91-93 classify_intent 经 `state.get("tool_history")`；precise 短路分支不调 classify ✓
- **RAGState**：新增可选 `tool_history: Optional[list]`；`make_initial_state` 不设默认（`.get()` 取 None 零回归，单测断言不含该键）✓
- **router.py 零改动** ✓；agent 端点不调 classify 的差异声明（main.py:815"agent 端点无独立意图分类"）与落地形态（持久化轨迹查询）在 changelog/CONTEXT 声明，满足 CONTEXT.md:235 原始设计 ✓
- 单测 12 项全 mock（SQL 形态/无记录/无工具/异常/超时/空 identity + 三处传参断言）✓；存量 WP-D 3 项零改动全绿 ✓

### WP-C：#3 改写喂路由开关评估 — ⚠️ 达标判定通过，1 项口径 mustFix（见 §三）

- **快照两键**：golden_intent.py:322-326 / golden_multi_turn.py:370-371 各补 `query_rewrite_enabled` + `contextual_rewrite_enabled`（对齐 intent_classifier_enabled 先例）；单测契约 4 项 ✓
- **短路测量**：golden_intent.py run_eval 短路条件（triage precise AND NOT _rule_hits → knowledge）与 engine.chat 逐字一致（含 reason 字符串）；shortcut_fired/correct/accuracy 落 scores；非短路样本无 reason 标记 ✓
- **四跑数字**：DB 直查与 changelog 表逐字一致（见 §一）✓
- **达标线判定**（plan §WP-C 实现要点 3 逐条执行）：Accuracy on 1.0 ≥ off 1.0 − 0.01 ✅ / 意图保持 1.0 ≥ 1.0 − 0.01 ✅ / 检索 +0.6 ≥ +0.6 − 0.01 ✅ / 短路 50 > 0 且判对率 100% ✅ → **query_rewrite_enabled 默认 true**（config.py:256，注释含决策与理由，PW_ 回退保留）——数据支撑充分 ✓
- **contextual 独立决策**：意图 12/12 不降 + 检索 +0.60 ≥ 接入前 +0.4363 + vague 句改写能力 0/1→1/1（module-063 实测"为什么"改写返回 None，本模块 id=55/56 改写成功）→ 默认 true——功能面全达标；**self_contained 0.9167→0.0833 数字下降为 triage-precise 度量口径（plan 实现要点 4/5 已预言），差异声明完整**；但 acceptance 字面线"self_contained 不降"未达成，需补口径注释（mustFix，见 §三）✓
- **两开关独立**：独立评测独立决策独立生效（短路只随 query_rewrite_enabled）✓

### WP-D：回归 + 文档收口 — ✅ 通过

- 全量 **1225/0**（独立复跑 201.18s）✓；新增 42 项全 mock 零真实 LLM/DB/模型 ✓
- conftest autouse `default_rewrite_switches_disabled` 钉住两开关 false（对齐 056/058/066 模式；生产默认 true 后存量引擎测试以改写前行为为准必须钉）✓
- changelog.md 完整（四跑对比表/达标线判定/差异声明/诚实边界 8 项/E2E 首跑超时如实标注）✓
- CONTEXT.md 备份先行只增不删 +7 行 / METRICS.md 待办 #9/#10/#11 标记完成 / 三记忆文件 ✓
- 04 文档标记完成交接（协调者主 checkout 执行）如实标注 ✓
- 无新依赖、无新表（只读 request_logs + tool_call_logs）✓

## 三、发现问题

### 3.1 阻塞问题（mustFix，修复后通过）

| # | 文件 | 位置 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | specs/module-072-intent-backlog/acceptance-criteria.md | §1.3 WP-C contextual 独立决策行 | **验收字面线"self_contained 不降"未达成**（0.9167 → 0.0833，Developer 按 plan 实现要点 4/5 的 triage-precise 度量口径解释为"改写能力不降：vague 句 0/1→1/1"）。裁定：接受该解释（11/12 precise 句改写被拒系 plan 设计的 precise 零 LLM 语义，生产接入前这些句子也从无生产改写、raw_overlap 0.2-0.6 不落空；意图/检索零回归；目标场景实测修复），但**验收契约需与裁定对齐**——Tester 将以 acceptance-criteria.md 为检查单，字面线未更新会导致验收误判 | 阻塞（文档口径） | 在 acceptance WP-C 该行补口径注释：self_contained 按"改写能力不降"判定（vague 句 0/1→1/1 提升），全量数字下降为 triage-precise 语义（plan 实现要点 4/5），并记录本裁定；changelog 差异声明已齐，无需改动 |

### 3.2 建议改进（不阻塞）

| # | 文件 | 位置 | 问题描述 | 建议 |
|---|------|------|----------|------|
| 1 | ai_service/rag/engine.py | L308 | `resolve_tool_history(identity)` 在 chat 入口**无条件 await**——precise 短路分支（命中时 result 不被使用）与 casual/realtime 快捷路径也各付一次查询；DB 不可达时最坏 +2s（wait_for 上限）。plan 原设计为"短路分支不接线"，实现为 hoist 前置 | 将 resolve 移入两个 classify 分支内（或短路判定后），短路命中/快捷路径零查询；若保持 hoist，至少在注释说明该成本为有界可接受 |
| 2 | ai_service/eval/golden/golden_multi_turn.py | L227 | eval 检索侧 `contextual_rewrite()` 调用**不受 settings.contextual_rewrite_enabled 门控**——id=55/56 快照 ctx=False 但检索改写实际执行（delta 0.6 两跑一致，属正确对照）；快照两键仅描述路由侧状态，未来读者可能误读"ctx=False = 检索改写关闭" | 脚本 docstring 或快照注释补一句：检索改写恒度量生产封装（settings 无关），快照仅记录路由侧开关 |
| 3 | specs/module-072-intent-backlog/changelog.md | §三 | 检索提升对比 n=1（12 对仅 1 对触发改写）统计功效弱——已如实标注（诚实边界 #1）且方向与 module-063 归因一致，无需修改 | 仅记录：后续 golden 若新增省略句样本（无术语 vague 型），重跑可增强统计功效 |
| 4 | ai_service/rag/engine.py | L339/343 | 两 classify 分支复用同一 hoist 结果——若未来需按分支差异化（如 precise 分支不查询），hoist 结构需调整 | 仅记录，当前语义正确 |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| router.py 逻辑零改动 | git diff --name-only 无 router.py | ✅ |
| 存量测试零改动（改了 = FAIL） | 唯一改动 = test_golden_intent 快照断言扩展（plan WP-C 许可"或既有快照断言处（扩展）"） | ✅（许可内） |
| 上下文改写必须走保真预检（无保护 LLM 调用） | llm_rewrite 后一律 fidelity_check 双锚门控（prepare/prepare_query/contextual_rewrite 三路径）；prepare_query 预检不可得 → 保守回退 | ✅ |
| 判定器确定性优先、不引入 LLM-as-judge | 短路 = triage（FTS 术语）+ _rule_hits 纯确定性信号零 LLM | ✅ |
| L4 多轮拼接（#4）不在范围 | intent_classifier_multi_turn 零改动；无多轮拼接重训改动 | ✅ |
| 无新依赖 / 无新表 | 零新增依赖；只读查询 request_logs + tool_call_logs | ✅ |
| 开关默认值不预设、达标才开 | 四跑实测达标后改默认 true；conftest 钉 false 保 hermetic | ✅ |

## 五、架构与代码质量评估

- **复用而非重造**：上下文改写并入 module-049 链（triage/llm_rewrite/fidelity_check/prepare 全复用，零新机制）；eval 单测 mock 栈对齐 test_multi_turn_routing 既有模式；conftest autouse 钉开关对齐 056/058/066 先例 ✓
- **单一来源防漂移**：contextual_rewrite 生产封装供 eval 调用（对齐 module-070 dual_judge 先例）；`_CONTEXTUAL_REWRITE_PROMPT` 单点定义 ✓
- **分层**：resolve_tool_history 放 engine.py 模块级同层引用；无跨层/反向依赖；无新 import 环（main.py 从 rag.engine 导入函数已验证）✓
- **缓存正确性**：_retrieve 缓存 key 附 prev 哈希防串话题；chat 主路径 prepare 并行择优不受缓存影响 ✓
- **fail-open 哲学**：改写链任何一环失败 = 回退原 query；resolve_tool_history 超时/异常/无记录 = None（与现状"恒 None"逐字一致）✓
- **代码量**：WP-A+WP-B 功能代码 ~110-120 行（含注释），符合 plan 预估 ≤110（注释豁免口径）与验收"默认 ≤200 达标"✓
- **安全**：SQL 全参数化（无注入面）；只读 SELECT 不写库；日志截断（identity[:50]/query[:50]）；无敏感信息 ✓

## 六、结论

**⚠️ CONDITIONAL（1 项 mustFix 文档口径，修复后 PASS）**。WP-A 迁移完整、接线零回归；WP-B SQL/join/fail-open 全验证、三处传参正确、router.py 零改动；WP-C 四跑数字与 DB 逐字一致、达标线判定流程执行、短路 50/100 零误杀实证；WP-D 全量 1225/0 独立复跑确认。唯一阻塞项为 acceptance-criteria 字面线"self_contained 不降"未达成需补口径注释（文档-only 修复，Developer 的裁定有 plan 依据 + 数据分解 + 差异声明，本审查裁定接受）。§三.2 四项 LOW 非阻塞。修复后复审即 PASS，可进 Tester。

**需 Tester 关注**：新增 42 项单测全 mock 的 hermetic 边界；两开关默认 true 后存量引擎行为由 conftest 钉子保证；真实 E2E 依赖 LLM/DB 环境（首跑改写超时属外部抖动已有先例）。

## 七、二轮复审（2026-08-19，Review 修复验证，结论 **✅ PASS**）

> Developer 已按 mustFix#1 完成修复（文档-only：acceptance-criteria.md §1.3 补口径注释 + changelog.md §七/§八）。本复审全部独立重查，不采信 changelog。

### 7.1 mustFix#1 修复验证

- **acceptance-criteria.md §1.3 contextual 独立决策行（L63）补口径注释**：`self_contained 按"改写能力不降"判定——唯一 vague 句改写能力 0/1→1/1 提升即不降 ✅；全量数字下降（0.9167→0.0833）为 plan 实现要点 4/5 的 precise 零 LLM 语义（12 对中 11 对含 FTS 术语自包含句不改写，改写能力口径 1/1 未下降），非生产回归；意图保持 12/12 + 检索提升 +0.60 ≥ 接入前 +0.4363 零回归` + 记录"2026-08-19 Reviewer 裁定接受"——与上轮裁定逐字对齐，Tester 检查单口径已闭环 ✅
- **changelog.md §七 Review 修复段**：差异声明已齐零改动确认 + 代码零改动声明；**§八 变更记录 v2 行**（2026-08-19 Review 修复（文档-only））——两者与事实一致 ✅

### 7.2 修复轮范围独立验证（代码零改动确证）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 修复轮改动文件 | 全文件 mtime 比对 | 代码 9 文件 mtime 00:21-00:47（一轮实现时点），spec 两文档 01:17（修复时点）——修复轮仅动 2 个 spec 文档，与 Developer 声明一致 ✅ |
| specs/ 未跟踪说明 | git check-ignore | `specs/` 在 .gitignore L41（"Project docs / specs"），module-071 同款未跟踪——声明属实，文档留工作树由协调者批量提交合理 ✅ |
| 全量 pytest | 独立复跑 `python -m pytest tests/ -q`（ai_service） | **1225 passed / 0 failed（204.83s）** 与上轮基线一致（上轮 201.18s，波动正常）——文档-only 修复无代码影响实证 ✅ |
| 新增单测 2 文件 | 独立复跑 test_query_rewrite_history + test_tool_history_wiring | **38 passed**（26 + 12）✅ |
| 存量受影响套件 | test_multi_turn_routing + test_golden_multi_turn + test_golden_intent + test_query_rewrite + test_tool_call_logs + test_tool_phase_split | **134 passed** 零改动全绿 ✅ |
| eval_runs 数字 | 直查 DB id=53/54/55/56 | 53（intent, qr=F, acc=1.0, shortcut 0）/ 54（qr=T, acc=1.0, **shortcut 50/50=100%**）/ 55/56（intent 1.0, retrieval_delta +0.6, self_contained 0.0833）——与 changelog 及上轮一致，四跑结论不变 ✅ |
| 短路零误杀复证 | id=54 per_question 独立分解 | 短路 50 全 knowledge wrong=0（reason 字符串与 engine.chat 逐字一致）；非短路 50 = casual 30 + realtime 20 wrong=0 ✅ |
| E2E 轨迹（WP-B） | 直查 DB e2e-module072-anon | request_logs 2 行 agent 端点，tool_call_logs 每 trace [search_knowledge ×3 + search_fts ×1] ✅ |
| router.py 零改动 | git diff --name-only | 无 router.py 条目 ✅ |

### 7.3 上轮 4 项 LOW 状态

| # | 上轮位置 | 状态 | 说明 |
|---|----------|------|------|
| 1 | engine.py L308 resolve_tool_history 无条件 await | 保持（非阻塞） | 最坏 +2s 有界，fail-open 安全；上轮已裁定 LOW 可接受 |
| 2 | golden_multi_turn L227 eval 检索改写不受开关门控 | 保持（非阻塞） | 快照仅描述路由侧、正确对照成立；上轮已裁定 LOW |
| 3 | 检索提升 n=1 统计功效弱 | 保持（已诚实标注） | changelog 诚实边界 #1 |
| 4 | hoist 结构记录 | 保持（仅记录） | 语义正确 |

### 7.4 二轮结论

**✅ PASS（进 Tester）**。mustFix#1 已按裁定修复：acceptance-criteria §1.3 补 triage-precise 口径注释（Tester 检查单口径闭环），changelog 差异声明零改动 + §八 v2 记录；修复轮代码零改动（mtime 实证），全量 1225/0 独立复跑（204.83s）与上轮一致；四跑 eval_runs id=53-56 数字、短路 50/100 零误杀、E2E 轨迹全部复证不变。上轮 4 项 LOW 维持非阻塞。验收结论由 Tester 在 acceptance-criteria.md §4 签署。
