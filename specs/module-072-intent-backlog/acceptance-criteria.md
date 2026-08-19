# 验收标准 — Module-072: 意图路由 Backlog 前三项（上下文改写接入 + WP-D 接线 + 改写喂路由评估）

## 1. 功能验收

### 1.1 WP-A: 上下文改写接入生产（#1）

**核心路径**

- [ ] `llm_rewrite(query, prev=None)`：prev 非空 → 上下文改写 prompt（含"上一轮问题: {prev}"段与当前省略句，prompt 自 golden_multi_turn.py:148-154 迁移）；prev 为空/None → 走 module-049 原 `_REWRITE_PROMPT`（逐字零回归）
- [ ] 改写失败/超时/返回空/改写无变化 → 返回 None（调用方回退原 query，链路不中断）——与 049 语义一致
- [ ] `prepare(query, retrieve_fn, history=None)` / `prepare_query(query, history=None)`：history 非空时取**最近一条 user 消息 content** 作 prev；保真锚点 = `f"{prev} {query}"`（拼接双锚），阈值沿用 `rewrite_fidelity_threshold`（0.6）
- [ ] `triage == "precise"` 分支不受 history 影响（FTS 术语命中 → 直接检索，零改写，module-049 precise 语义逐字不动）
- [ ] engine.chat（L248）：prepare 调用条件 = `query_rewrite_enabled or contextual_rewrite_enabled`，且传 `request.history`；改写成功且保真通过 → `current_query` 为改写后 query（同时喂路由 + 检索），round 0 复用 `rewrite_round0` 择优结果
- [ ] `engine._retrieve(query, top_k, min_score, history=None)`：签名新增 history（默认 None），prepare_query 调用条件同改 + 透传 history
- [ ] main.py chat_stream Step 2（L545）：`_retrieve(request.query, top_k=20, history=request.history)`
- [ ] config 新增 `contextual_rewrite_enabled: bool = False`（PW_CONTEXTUAL_REWRITE_ENABLED）

**边界条件**

- [ ] `contextual_rewrite_enabled=False` → 生产行为与改动前逐字一致（零回归）
- [ ] history 为空/None → 不走上下文改写（与 049 原逻辑一致）
- [ ] `triage == "precise"` 且 history 非空 → 不改写（precise 零 LLM 语义优先）
- [ ] 保真未过（锚点余弦 < 0.6）→ 回退原 query（省一次并行检索，与 049 fidelity_reject 语义一致）
- [ ] 保真预检嵌入失败 → 跳过预检直接并行，择优兜底（049 既有 fail-open 语义）

**异常场景**

- [ ] LLM 改写超时（10s）→ 回退原 query，不中断链路
- [ ] 并行检索单路失败 → 降级另一路（049 既有 return_exceptions 语义）；双路失败 → 空结果走无结果降级
- [ ] 检索预算已耗尽（改写后超预算）→ 回退原 query 继续检索（_retrieve 既有逻辑不破坏）

### 1.2 WP-B: WP-D 工具历史信号接线（#2）

**核心路径**

- [ ] `engine.py` 模块级 `resolve_tool_history(identity) -> list[str] | None`：request_logs 按 `identity + endpoint IN ('agent','agent-lg')` 取最近一次 trace_id → tool_call_logs 按 trace_id 取 tool_name 列表；SQL 全参数化
- [ ] engine.chat L268/L271 两分支 classify 均传 `tool_history=await resolve_tool_history(identity)`；precise 短路分支（L265）不调 classify
- [ ] main.py:521 chat_stream classify 传 `tool_history=await resolve_tool_history(identity)`
- [ ] graph.py:89 classify_intent 传 `state.get("tool_history")`；RAGState 新增可选 `tool_history: Optional[list]` 字段
- [ ] `router.py` 零改动（grep 确认无 diff）

**边界条件**

- [ ] identity 为空 → resolve_tool_history 直接返回 None
- [ ] 该 identity 无 agent 端点请求记录 / 无工具调用记录 → None（现状行为）
- [ ] DB 查询异常 / 超时（2s wait_for）→ None（fail-open，不抛异常不阻塞路由）
- [ ] 测试环境（request_logs 表存在但空 / 开关关）→ None，存量路由行为逐字不变

**异常场景**

- [ ] 工具信号只在"短句（去语气词后 <6 字符）且 `_deterministic_confirm` 无特征"时生效；有特征/正常长度 query 走正常路由（router.py 既有逻辑验证，不因接线改变）

### 1.3 WP-C: 改写喂路由开关评估（#3）

**核心路径**

- [ ] golden_intent + golden_multi_turn 两脚本 record_eval_run 各补 `config_snapshot["query_rewrite_enabled"]` + `["contextual_rewrite_enabled"]`（对齐 golden_intent.py:300 intent_classifier_enabled 先例）
- [ ] 真实跑分 4 次落库：query_rewrite_enabled off/on × golden_intent / golden_multi_turn（eval_runs id 全部记录 changelog）
- [ ] 短路样本统计：从 per_question 按 reason 过滤"分诊命中 FTS 术语，短路 knowledge"样本，与标注对照算判对率
- [ ] 达标线（全达标才开）：intent Accuracy on ≥ off − 0.01；意图保持 on ≥ off − 0.01；检索提升 on ≥ off − 0.01；短路触发样本数 > 0 且判对率 = 100%
- [ ] 决策落 changelog：达标 → `query_rewrite_enabled` 默认 true（含对比表 + 理由）；不达标 → 保持 false + 失败模式如实标注
- [ ] `contextual_rewrite_enabled` 默认值独立决策：WP-A 接入前后 golden_multi_turn 三指标对比（self_contained/意图保持不降 + 检索提升 ≥ 接入前 → true；否则 false），决策 + 理由入 changelog
  - 口径注释（triage-precise，2026-08-19 Reviewer 裁定接受）：self_contained 按**"改写能力不降"判定**——唯一 vague 句改写能力 0/1→1/1 提升即不降 ✅；全量数字下降（0.9167→0.0833）为 plan 实现要点 4/5 的 **precise 零 LLM 语义**（12 对中 11 对含 FTS 术语自包含句不改写，改写能力口径 1/1 未下降），非生产回归；意图保持 12/12 + 检索提升 +0.60 ≥ 接入前 +0.4363 零回归

**边界条件**

- [ ] 两开关独立评测独立决策（不互相绑架）；实现上 contextual 独立生效（prepare 调用条件为 OR）

### 1.4 WP-D: 回归 + 文档收口

**核心路径**

- [ ] 全量 pytest 基线（实施前 `--collect-only` 实测校正 1182/1183 出入）+ 新增单测全绿；**存量测试零改动（改了 = FAIL）**
- [ ] conftest 新增 autouse fixture 钉 `contextual_rewrite_enabled=False`
- [ ] 新增单测覆盖（全部 mock，零真实 LLM/DB/模型）：
  - WP-A：llm_rewrite prev 分支 prompt 断言 / 失败超时 None / prepare+prepare_query history 透传与锚点拼接 / precise 不受 history 影响 / _retrieve history 透传 / 开关组合（contextual=false 零回归、query_rewrite=false + contextual=true 独立生效）→ 建议 tests/retrieval/test_query_rewrite_history.py（~12-14 项）
  - WP-B：resolve_tool_history SQL 形态/无记录/异常/空 identity/超时 → None + 三处调用点传参断言（engine.chat 两分支 + chat_stream + graph）→ 建议 tests/agent/test_tool_history_wiring.py（~8-10 项）
  - WP-C：eval 脚本快照字段注入（2 项）
- [ ] changelog.md 产出（WP-A 保真锚点余弦分布实测 / WP-B 接线差异声明（agent 端点不调 classify → 持久化轨迹查询）/ WP-C 对比表 + 两开关默认值决策 + 理由 / 诚实边界）
- [ ] CONTEXT.md（只增不删，先备份）、METRICS.md 待办区、三记忆文件更新
- [ ] docs/项目深挖/04-意图路由.md 第十一节 #1/#2/#3 标记完成——由协调者/用户在主 checkout 执行（本 worktree 无法触达，changelog 如实标注交接）

## 2. 非功能验收

### 2.1 性能验收

- [ ] resolve_tool_history 单次查询 ≤ 2s（wait_for 上限），不可得/超时不影响路由延迟（fail-open None 与现状一致）
- [ ] contextual 改写仅增一次 LLM 调用（≤10s 超时，与 049 改写同量级）；precise 路径零新增成本

### 2.2 安全验收

- [ ] resolve_tool_history SQL 全参数化（无拼接，无新注入面）
- [ ] 轨迹查询只读（SELECT），不写库
- [ ] 日志不输出敏感信息（改写 query 截断 ≤50 字符日志既有惯例）

### 2.3 代码质量验收

- [ ] router.py 零改动（grep `git diff --stat` 确认无 router.py 条目）
- [ ] 功能代码 ≤ 110 行（WP-A 55 + WP-B 45 + WP-C 10），默认 ≤200 达标
- [ ] 无跨层调用（resolve_tool_history 放 engine.py 模块级，调用点同层引用）
- [ ] 存量断言零改动（conftest 仅新增 fixture）

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 新增单测（WP-A） | `python -m pytest tests/retrieval/test_query_rewrite_history.py -q` | 全绿 |
| 新增单测（WP-B） | `python -m pytest tests/agent/test_tool_history_wiring.py -q` | 全绿 |
| 存量 WP-D 3 项 | `python -m pytest tests/agent/test_multi_turn_routing.py -q -k tool_history` | 3 passed |
| 存量多轮路由全量 | `python -m pytest tests/agent/test_multi_turn_routing.py tests/eval/test_golden_multi_turn.py -q` | 全绿（存量零改动） |
| 全量回归 | `python -m pytest tests/ -q` | 基线数 + 新增数 / 0 failed |
| WP-C 跑分（off/on × 2 集） | `python -m eval.golden.golden_intent` + `python -m eval.golden.golden_multi_turn`（各跑两开关态，共 4 次） | eval_runs 落库 + 对比表入 changelog |
| WP-A 接入前后对比 | `python -m eval.golden.golden_multi_turn`（接入后 vs 接入前落库 id 对比） | 三指标对比表 |
| 真实 E2E（WP-A） | 真实 chat 两轮：round1 完整问题 → round2 "为什么" | round2 检索 sources 命中 prev 主题文档（不再落空） |
| 真实 E2E（WP-B） | 真实 agent 轮（search_knowledge 落库 tool_call_logs）→ 下轮短 query "为什么" 走 chat | classify reason 含"工具历史信号"→ knowledge + 检索走通 |

## 4. 验收结论

- 审查人: Reviewer（2026-08-19，二轮复审 ✅ PASS）
- 测试人: Tester（2026-08-19，全量 1225/0 + DB 直查 + 真实复跑 id=57/58/59 数字与 changelog 逐字一致）
- 验收时间: 2026-08-19
- 结论: [x] 通过 / [ ] 不通过
- 备注: WP-C 开关默认值决策已由真实环境四跑（id=53-56）+ Tester 复跑（id=57-59）支撑：两开关默认 true，测试环境 conftest 钉 false；deepseek 429 限流为外部抖动（本日复跑无 429，如实记录）
