# 开发计划 — Module-072: 意图路由 Backlog 前三项（上下文改写接入 + WP-D 接线 + 改写喂路由评估）

## Agent 配置

- Developer x1（后端 Python：`rag/retrieval/query_rewrite.py` + `rag/engine.py` + `main.py` + `rag/graph/graph.py` + `rag/state.py` + `src/config.py` + 单测 + eval 快照字段）
- Reviewer x1
- Tester x1

## 1. 需求描述

- 需求来源: `docs/项目深挖/04-意图路由.md` 第十一节 #1/#2/#3（task-brief 2026-08-19 落地；注意：该文档在主 checkout 本地未跟踪目录，本 worktree 无法改动，收口动作由协调者在主 checkout 执行）
- 功能描述: 三项 backlog 落地——**#1** eval-only 的 `contextual_rewrite`（golden_multi_turn.py:134）迁入生产并入 module-049 分诊式改写链（多轮"为什么"检索落空修复）；**#2** module-063 WP-D 工具历史信号接线（router.py 已实现但三个 classify 调用点恒传 None 不生效）；**#3** `query_rewrite_enabled` 短路路由开关评测（达标才开，不预设）
- 优先级: P1（#1 高 / #2 中 / #3 中）
- 明确不在范围: L4 多轮拼接重训（#4，已降级不做，勿误入）；`router.py` 逻辑零改动（#2 只传参）

## 2. 模块拆分

### WP-A: #1 上下文改写接入生产（并入 module-049 链）

**描述**: `contextual_rewrite`（golden_multi_turn.py:134-165，eval-only LLM 改写）迁入 `rag/retrieval/query_rewrite.py` 作为 module-049 链的 history 分支——`llm_rewrite` 增加可选 `prev` 参数走上下文改写 prompt，`prepare`/`prepare_query` 增加可选 `history` 参数取最近一条 user 消息作 prev；保真预检复用 `fidelity_check`（锚点 = `f"{prev} {query}"` 拼接双锚，主题+原句）；改写失败/保真不过 → 原 query（保守零回归）。

**预估代码量**: 功能代码 ~55 行（含 config 1 行 + engine/main 接线 9 行；golden_multi_turn.py 删除本地 contextual_rewrite ~30 行净减）

**涉及文件**:
- `ai_service/rag/retrieval/query_rewrite.py` — `_CONTEXTUAL_REWRITE_PROMPT` 常量（自 golden_multi_turn.py:148-154 迁移，含"上一轮问题: {prev}"段）+ `llm_rewrite(query, prev=None)`（prev 非空走上下文 prompt；失败/超时/无变化 → None 语义不变）+ `prepare(query, retrieve_fn, history=None)` / `prepare_query(query, history=None)`（history 非空且取最近一条 user 消息 content 作 prev；保真锚点 = `f"{prev} {query}"`；precise 分支逐字不动）
- `ai_service/rag/engine.py` — `chat`（L248）prepare 调用条件 `settings.query_rewrite_enabled or settings.contextual_rewrite_enabled` + 传 `request.history`；`_retrieve`（L697）签名加 `history: list | None = None`（默认 None 向后兼容），prepare_query 调用条件同改 + 传 history
- `ai_service/main.py` — chat_stream Step 2（L545）`rag_engine._retrieve(request.query, top_k=20, history=request.history)`
- `ai_service/src/config.py` — 新增 `contextual_rewrite_enabled: bool = False`（PW_CONTEXTUAL_REWRITE_ENABLED）
- `ai_service/eval/golden/golden_multi_turn.py` — 删除本地 `contextual_rewrite`，改 `from rag.retrieval.query_rewrite import contextual_rewrite` 生产封装（**单一来源防漂移**，对齐 module-070 dual_judge 先例）；docstring"eval-only"表述更新；fixture 路径（heuristic_rewrite）逐字不动
- `ai_service/tests/retrieval/test_query_rewrite_history.py`（新）— 见 WP-D 测试清单

**依赖**: 无（与 WP-B/WP-C 独立）

**实现要点**:

1. **触发条件（省略句判定零新逻辑）**：不新增"省略句/指代句判定器"——触发 = `contextual_rewrite_enabled AND history 非空 AND triage(当前句)==vague`。triage 是 module-049 既有静态分诊（FTS 术语命中 → precise → 直接检索）：省略句/指代句天然无术语 → vague → 走上下文改写；有术语的句子（"那CMS呢"含 CMS → precise）直接检索即可自含主题，无需上下文。precise 分支零改动（保 module-049"precise 零 LLM"设计）。
2. **保真预检锚点决策**：049 链的 `fidelity_check(original, rewritten)` 对裸省略句（"为什么"3 字无信息量）做锚会系统性误杀上下文改写（改写后 query 必然更具体、与裸句余弦偏低）——**锚点改为 `f"{prev} {query}"` 拼接串**（主题+原句双锚：防 LLM 漂移到无关话题 + 防丢失原句意图），阈值沿用 `rewrite_fidelity_threshold` 0.6。Developer 真实重跑时记录每对余弦分布入 changelog；若 0.6 误杀率 > 25% → 按数据调整口径/阈值（changelog 记录，不预设）。
3. **engine.chat 的 round 0 复用**：contextual 改写走 prepare 完整链（triage→改写→保真→并行择优），`rewrite_round0` 直接用作 round 0 检索结果（与 049 全链同构，零新增分支）；`current_query` 为改写后 query 时同时喂路由（改写后 query 更自包含，路由更准，与 module-063 WP-C 语义一致）。
4. **eval 迁移口径**：golden_multi_turn 真实模式改调生产 `contextual_rewrite`（带保真门控）——eval 的 self_contained 记 0 语义变为"改写被保真拒绝也算失败"，与生产行为一致（这正是"接入前 vs 接入后"对比的正确口径）。
5. **已知边界（如实标注）**：precise 但含指代词的句子（如"它们各自的适用场景呢"若 FTS 命中"适用场景"）不触发上下文改写——precise 零 LLM 语义优先，12 对评测覆盖后数据说话。

### WP-B: #2 WP-D 工具历史信号接线

**描述**: 三个 classify 调用点（engine.chat 268/271、main.py:521、graph.py:89）全部补传 `tool_history`——轨迹来源为持久化的 agent 工具轨迹（module-066 `tool_call_logs` JOIN module-058 `request_logs` 按 identity 取最近一次 agent 端点请求），查询不可得/失败 → None（fail-open 现状行为）；`router.py` 逻辑零改动。

**预估代码量**: 功能代码 ~45 行（`resolve_tool_history` ~28 + 三处接线 ~9 + RAGState 字段 2 + config 注释）

**涉及文件**:
- `ai_service/rag/engine.py` — 模块级 `async def resolve_tool_history(identity: str) -> list[str] | None`：request_logs 子查询（`identity=:id AND endpoint IN ('agent','agent-lg') ORDER BY created_at DESC LIMIT 1` 取 trace_id）→ tool_call_logs 按 trace_id 取 tool_name 列表；`asyncio.wait_for(2s)` + try/except 全捕获 → None（fail-open）；空 identity 直接 None；SQL 全参数化
- `ai_service/rag/engine.py` — `chat` L268/L271 两分支 classify 各加 `tool_history=await resolve_tool_history(identity)`（engine.chat 有 identity 参数）；precise 短路分支（L265）不调 classify，无需接线
- `ai_service/main.py` — chat_stream L521 classify 加 `tool_history=await resolve_tool_history(identity)`（identity 已在 L508 resolve）
- `ai_service/rag/state.py` — RAGState 加可选 `tool_history: Optional[list]` 字段；`make_initial_state` 不设默认（`.get()` 取用，零回归）
- `ai_service/rag/graph/graph.py` — classify_intent（L89）传 `state.get("tool_history")`（休眠管线：无生产端点调用，接线为一致性 + 单测对齐，如实标注）

**依赖**: 无（与 WP-A/WP-C 独立）

**实现要点**:

1. **轨迹来源决策（与 task-brief 措辞的差异声明）**：brief"agent 端点（react_loop）有轨迹 → 传工具名列表"——实测 **agent 端点（/ai/rag/chat/agent、agent-lg）不调用 classify**（main.py:809 注释"agent 端点无独立意图分类，intent='agent'"），轨迹无法在请求内直达 classify。落地形态 = **持久化轨迹查询**：agent 轮的工具调用已落库（tool_call_logs），按 identity（request_logs 关联）取最近一次 agent 轮的工具名列表传给本轮 classify。这同时满足 CONTEXT.md:235 原始设计"待 agent 轨迹持久化后接线"（持久化已具备）。
2. **engine.chat 与 brief"传 None（现状）"的关系**：brief 描述的是无轨迹场景（现状）；接线后查询不可得时仍传 None（逐字现状），有轨迹时新增生效——与 E2E 通过标准（agent 轮后短 query 强制 knowledge 可观测）自洽。
3. **陈旧信号边界（如实声明）**：只取最近一次 agent 请求（LIMIT 1，无时间窗过滤）；跨话题会话理论上有陈旧信号风险，但工具信号只在"短句 + `_deterministic_confirm` 无特征"时生效（有 FTS/图谱/规则特征走正常路由防话题漂移），风险已被既有机制天然收敛。
4. **新增单测（全部 mock，零真实 DB）**：resolve_tool_history 的 SQL 形态/无记录 None/异常 None/空 identity None/超时 None + 三处调用点传参断言（mock resolve_tool_history 返回值 → 断言 classify 收到同一列表）。

### WP-C: #3 改写喂路由开关评估

**描述**: 双评测集 × 双开关态真实跑分对比，数据驱动 `query_rewrite_enabled` 默认值决策（达标才开，不预设）。同时为 WP-A 的 `contextual_rewrite_enabled` 默认值决策提供检索侧数据。

**预估代码量**: 功能代码 ~10 行（两脚本快照字段 4 行 + 短路统计辅助 6 行）+ 真实跑分（不改生产逻辑）

**涉及文件**:
- `ai_service/eval/golden/golden_intent.py` — record_eval_run（L300 后）补 `config_snapshot["query_rewrite_enabled"] = str(settings.query_rewrite_enabled)` + `["contextual_rewrite_enabled"]`（对齐 module-056 intent_classifier_enabled 先例，使 eval_runs 两态可区分）
- `ai_service/eval/golden/golden_multi_turn.py` — record_eval_run 同样补两键
- `ai_service/tests/eval/test_golden_multi_turn.py`（扩展）+ `ai_service/tests/eval/test_intent_dataset.py` 或既有快照断言处（扩展）— 快照注入 2 项
- `ai_service/src/config.py` — 不预设：`query_rewrite_enabled` 保持 false，跑分达标后 Developer 改默认 true（决策 + 理由入 changelog）

**依赖**: 无（评测只度量不接线；WP-A/WP-B 代码落地后同环境跑分，数据可交叉印证）

**实现要点**:

1. **评测口径（短路路由对比集）**：golden_intent（100 条，eval_type='intent'）+ golden_multi_turn（12 对，eval_type='multi_turn'）双集、`query_rewrite_enabled` off/on 各跑一次（共 4 次落库，id 标注 changelog）。golden_intent 为真实知识库问题，FTS 术语命中率高 → 短路触发样本可实测统计。
2. **短路样本统计（确定性后处理）**：从 per_question 中按 reason 含"分诊命中 FTS 术语，短路 knowledge"过滤短路样本，与 expected 标注对照算判对率（短路路径 = precise AND NOT rule_hits → knowledge，纯确定性规则，预期 100%）。
3. **达标线（无破坏 + 有收益）**：
   - golden_intent Accuracy on ≥ off − 0.01（LLM 波动容差，module-057 先例 ±0.01）
   - golden_multi_turn 意图保持 on ≥ off − 0.01；检索提升 on ≥ off − 0.01
   - 短路触发样本数 > 0 且判对率 = 100%（确定性零 LLM）
   - 全达标 → `query_rewrite_enabled` 默认 true；任一不达标 → 保持 false + 失败模式入 changelog
4. **WP-A 默认值决策联动**：`contextual_rewrite_enabled` 默认值由 WP-A 独立评测决定（接入前 vs 接入后 golden_multi_turn 三指标对比：self_contained/意图保持不降 + 检索提升 ≥ 接入前 → true；否则 false）；**两个开关独立评测独立决策**（与 brief"决策留给 Developer 基于 WP-C 评测数据"措辞的差异声明：contextual 是检索侧增益、短路是路由侧成本收益，风险面独立，分开开关更清晰——实现上 `contextual_rewrite_enabled` 可独立生效，不绑 `query_rewrite_enabled`）。

### WP-D: 回归 + 文档收口

**描述**: 全量基线 + 新增单测全绿（存量测试零改动红线）+ conftest 钉子 + changelog/CONTEXT/三记忆文件。

**预估代码量**: 测试 ~170 行（含注释口径，自动豁免）+ 文档

**涉及文件**:
- `ai_service/tests/conftest.py` — 新增 autouse fixture 钉 `contextual_rewrite_enabled=False`（对齐 056/058/066 模式；`query_rewrite_enabled` 生产默认已 false 无需钉）
- `specs/module-072-intent-backlog/changelog.md`（Developer 产出，含 WP-A 保真锚点余弦分布 / WP-B 接线差异声明 / WP-C 对比表 + 两开关默认值决策 + 理由）
- `CONTEXT.md`（只增不删先备份）
- `METRICS.md` — 待办区 #1/#2/#3 相关行标记完成（如达标）
- `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`
- `docs/项目深挖/04-意图路由.md` — **该目录未 git 跟踪且仅主 checkout 存在，本 worktree 无法触达**：第十一节 #1/#2/#3 标记完成由协调者/用户在主 checkout 执行（plan 如实标注）

**依赖**: WP-A + WP-B + WP-C

**实现要点**:
1. 全量 `pytest tests/ -q` 基线 1183/0（task-brief 口径；project-context module-071 记 1182/0 有 1 项出入——实施前 `pytest --collect-only` 实测校正，以实测为准）+ 新增全绿
2. 存量测试兼容分析（已核实）：
   - `test_multi_turn_routing.py` WP-D 3 项（test_kb_tool_history_forces_knowledge / test_generate_tool_history_forces_knowledge / test_non_kb_tool_history_normal_path）直调 classify 传 tool_history —— 零改动
   - `test_chat_stream_passes_history` / `test_langgraph_classify_intent_passes_history`（fake_classify 签名已含 `tool_history=None` 形参）——接线后兼容；resolve_tool_history 在测试中真查 DB（request_logs 表 init_db 幂等建过但空）→ None，断言只查 query/history 不受影响；若测试环境 DB 不可达 → fail-open None 同样成立
   - `test_golden_multi_turn.py` 无 contextual_rewrite 直接断言（仅 heuristic/指标/fixture）——迁移 eval 脚本后零影响
3. 无新 ADR（改写链参数演化 + 既有信号接线，非新架构/新依赖）

## 3. 技术方案

- 涉及数据表: 无新增表、无 schema 改动（只读 `request_logs` + `tool_call_logs`，全参数化查询）
- API 端点: 无新增；chat/chat_stream/agent/agent-lg 端点签名零改动
- 外部依赖: 无新增（复用 LLMFactory 降级链 + 本地 bge-m3 fidelity_check）
- 环境变量: `PW_CONTEXTUAL_REWRITE_ENABLED`（新增，默认 false，达标后切 true）；`PW_QUERY_REWRITE_ENABLED`（存量，默认 false，WP-C 达标后切 true）；`PW_REWRITE_FIDELITY_THRESHOLD`（存量 0.6，锚点口径调整时可校准）

## 4. 验收标准

见同目录下的 `acceptance-criteria.md`

## 5. 风险评估

- **保真锚点口径变化**: 上下文改写锚点 = `prev + query` 拼接（与 049 的裸 query 锚语义不同）——单测锁定锚点拼接逻辑；真实重跑记录余弦分布，0.6 误杀 >25% 按数据校准（changelog 记录，不预设）
- **LLM 改写非确定性**: 单测全 mock 确定性；真实跑分多态对比（off/on 各一次），达标线含 ±0.01 波动容差（module-057 先例）；deepseek 429 限流为外部抖动（module-055 先例如实标注）
- **resolve_tool_history DB 依赖**: 2s 超时 + 全异常捕获 → None fail-open（现状行为逐字不变）；只读查询无新注入面；测试环境表存在但空 → None
- **存量测试兼容**: WP-D 3 项直调零改动；chat_stream/langgraph 测试 fake_classify 签名兼容；conftest 新增钉子后存量用例零漂移；**任何存量用例改动 = FAIL（红线）**
- **两开关耦合误判**: contextual 独立生效（prepare 调用条件 OR），不绑 query_rewrite_enabled——两开关独立评测独立决策，changelog 记录与 brief 措辞的差异声明
- **graph.py 休眠管线**: classify_intent 接线为一致性 + 单测对齐，无生产入口如实标注；不扩展 RAGState 输入来源
- **基线数字出入**: 1182 vs 1183 以实施前实测 collect 数为准
- **04 文档触达**: docs/项目深挖 未跟踪 + 主 checkout 独有，本 worktree 不可改——收口由协调者主 checkout 执行

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-19 | 初始版本 | Planner |
