# 开发计划 — Module-068: Agent 阶段推进死锁修复

> Planner: 2026-08-17 | 依据：`specs/module-068-agent-phase-fix/task-brief.md`（module-066 实测盲区的修复落地）
> 范围：react_loop 检索阶段死锁修复（检索命中即切 generation）+ 预算按阶段细分化 + 066 评测重跑验证 + 回归收口
> 预算：WP-A 半天 + WP-B 半天 + WP-C 半天 + WP-D 半天 ≈ 2 天
> Agent 配置：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（代码实测，勿重复调查）

- **死锁机制确认**：`advance_phase(ctx, executed_names)`（`agent/react.py:154-163`）推进条件 = `ctx.phase == "retrieval" and any(n in _GENERATION_GATE_TOOLS for n in executed_names)`（`_GENERATION_GATE_TOOLS = {"generate_answer", "verify_answer"}`，react.py:140）；`schemas_for_phase`（react.py:143-151）按 `ctx.phase` 只暴露当前阶段工具（`tool_phase_split` 默认 true，config.py:111）——检索阶段 schema 不含生成工具 → LLM 无法调用 generate_answer → 永不切 generation → 死锁（与 task-brief 事实 1 一致）。
- **advance_phase 调用点（两处）**：
  1. `react.py:389`——react_loop 每轮执行完 allowed 工具后调用
  2. `langgraph_react.py:160`——execute_tools 节点末尾（同构）
  3. **存量单测直接调用点**：`tests/agent/test_tool_phase_split.py:135-145` `test_advance_phase_unit` 以**单参数列表**调用 `advance_phase(ctx, ["search_knowledge"])` 等 4 次——**签名扩展必须向后兼容（新参数缺省 None）**，否则挂存量测试（红线）。
- **检索工具清单（tool_registry.py:348-416 归组实测）**：检索组 7 = search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory / re_search；生成组 4 = generate_answer / verify_answer / note_to_self / re_search。task-brief 命中判定清单（search_*/extract_entities/recall_memory）= **6 个**（不含 re_search——双组补检工具，命中判定排除之）。
- **执行工具处拿"返回结果"**：`react.py:382` `result = await execute_tool_with_log(name, args, tool, ctx)` 返回**结果字符串**——每工具可用；当前循环只收集 `executed_names`（react.py:366-369）**不收集 result**，需扩展同序收集。langgraph 同构（langgraph_react.py:136-153）。
  - ⚠️ **判定坑（task-brief 未覆盖，Planner 补）**：`_format_docs` 空结果返回 `"（无检索结果）"`（tool_registry.py:151）、`recall_memory` 空返回 `"（无相关历史记忆）"`（tool_registry.py:218）——**均为非空字符串**，`bool(result)` 判定会误判"命中"。命中判定必须排除空结果标记；extract_entities 返回 JSON（`{"entities": [...]}`），须解析判 entities 非空。
- **预算截断点**：`react.py:357` `allowed = tool_calls[: max(0, budget - tool_count)]`，`if not allowed: break`（:358-359）→ 预算耗尽走 `reflector.generate_answer` 兜底（:391-402）；budget 来源 `react.py:275` `settings.max_agent_tools`（config.py:104，默认 4，PW_MAX_AGENT_TOOLS 覆盖）。langgraph 同构。
- **阶段预算与开关联动（Planner 补的关键设计点）**：conftest autouse fixture 钉住 `tool_phase_split=false`（056/058/066 模式）——**阶段预算必须只在 `tool_phase_split=true` 时生效**，否则存量全量工具测试（如 test_agent_tools.py 中 budget=4 连续多工具场景，该文件不直接调 advance_phase 只经 react_agent）会被"检索阶段 ≤3"截断挂掉。开关 false 时回退纯总预算（存量行为逐字不变）。
- **基线**：**1102/0**（module-067 交付口径 = 1075 基线 + 27 新增；Reviewer 独立复跑 1102/0 确认）。`scripts/test_models.py` 1 项 module-050 遗留收集 ERROR 未触碰（沿用，不算失败）。
- **066 评测对比基准（首跑，WP-C 对标）**：pass^1=0.0 / 工具正确率 0.0 / chat 0.6667 / pass^3=0.1；命令 `python -m eval.agent_tasks --mode agent`（真实 LLM+DB，agent_eval_runs 落库）。判定器/评测集（066 产物）**不改不凑数**。
- **at-002 现象归因**：执行层 `tools.get(name)` 不校验 schema 暴露（Tester 066 独立发现）——WP-A 修复后 generate_answer 在检索命中轮之后的 schema 可见，该症状自然消解（无需额外处理）。

## 1. WP-A：死锁修复——检索命中即切 generation（半天）

- **目标**：打破"检索阶段 schema 无生成工具 → LLM 无法调 generate_answer → 永不切 generation"的鸡生蛋死锁；推进条件增加确定性规则"任一检索工具本轮返回非空结果 → 下一轮切 generation"（零 LLM 判断，066 已证 LLM 行为性不可靠）。
- **涉及文件**：
  - `ai_service/agent/react.py`（advance_phase 扩展 + `_retrieval_hit` 纯函数 + ctx 字段 + react_loop 收集 results）
  - `ai_service/agent/langgraph_react.py`（execute_tools 调用点同构传参）
  - `ai_service/src/config.py`（新增 `agent_retrieval_max_rounds: int = 3`，PW_AGENT_RETRIEVAL_MAX_ROUNDS）
  - `ai_service/tests/agent/test_agent_phase_fix.py`（新增单测文件）
- **实现要点**：
  1. 模块常量 `_RETRIEVAL_HIT_TOOLS = {"search_knowledge", "search_fts", "search_vector", "search_graph", "extract_entities", "recall_memory"}`（6 个，紧邻 `_GENERATION_GATE_TOOLS`）。
  2. 纯函数 `_retrieval_hit(name: str, result: str) -> bool`：name 不在集合 → False；result 空串 → False；result 含空结果标记 `"（无检索结果）"` / `"（无相关历史记忆）"` → False；extract_entities 尝试 `json.loads` 判 `entities` 非空（解析失败按非空文本判定）；其余 → True。
  3. **签名向后兼容扩展**：`advance_phase(ctx, executed_names, executed_results=None)`——`executed_results` 缺省 None 时行为 = 旧逻辑（仅生成工具判定），存量 `test_advance_phase_unit` 单列表调用零改动；提供时新增判定 `any(_retrieval_hit(n, r) for n, r in zip(executed_names, executed_results))`。两条件任一满足即切 generation（原条件保留，兼容 tool_phase_split=false 路径）。
  4. **防空转兜底**：ctx 新增 `retrieval_rounds: int = 0`；advance_phase 内 phase 仍为 retrieval 时 `ctx.retrieval_rounds += 1`，且 `if ctx.retrieval_rounds >= settings.agent_retrieval_max_rounds` → 强制切 generation（参数化；066 实测 4 轮预算耗尽，取 3 = 预算-1）。阈值判定在"本轮未因其他条件切换"之后，避免重复切换。存量 `test_advance_phase_unit` 4 次调用序列逐次推演：调用 3（generate_answer）已切 generation，调用 4 时 phase=generation 不再递增，断言全保持。
  5. react_loop 内收集 `executed_results: list[str]`（与 executed_names 同序，execute_tool_with_log 返回值即得），调用点改为 `advance_phase(ctx, executed_names, executed_results)`；langgraph_react.py:160 同构。
  6. 兜底路径（预算耗尽 reflector.generate_answer）不动；执行层不校验 schema 暴露的现状不动（修复后自然消解）。
- **单测（新增，测试内显式 `setattr settings.tool_phase_split = True`，对齐 test_tool_phase_split 模式）**：
  ① 检索命中（mock hybrid_retriever 返回非空 docs）→ 下一轮 tools_seen schema 含 generate_answer（生成组 4）
  ② 3 轮未命中（mock 返回 `"（无检索结果）"`）→ 第 4 轮 schema 强制为生成组（兜底生效）
  ③ generation 内 re_search 不回退（回归，带 results 参数版本）
  ④ 原条件仍生效（旧签名单列表调用 advance_phase 直接断言，存量行为）
  ⑤ `_retrieval_hit` 纯函数边界：空串 / 空结果标记 / extract_entities JSON 空实体 / 非检索工具名 / re_search 排除
  ⑥ langgraph_react_agent 同构冒烟（检索命中 → 下一轮生成组）
- **通过标准**：单测全绿 + 真实 agent E2E 轨迹出现 generate_answer 调用（不再全检索兜底）。
- **明确不做**：不改 tool_registry.py / engine.py / 检索链路（红线）；不引入"LLM 自报检索完成"机制（零 LLM 判断纪律）。

## 2. WP-B：预算按阶段（半天）

- **目标**：`max_agent_tools=4` 语义细化为阶段预算——**检索阶段 ≤3 次 + 生成阶段 ≤2 次**（总 5；检索 3 轮覆盖 1-2 次检索 + 记忆/实体，生成 2 轮留一次 re_search 补检余量）。
- **涉及文件**：
  - `ai_service/src/config.py`（`agent_retrieval_budget: int = 3` PW_AGENT_RETRIEVAL_BUDGET + `agent_generation_budget: int = 2` PW_AGENT_GENERATION_BUDGET；`max_agent_tools` 默认 4→5，PW_MAX_AGENT_TOOLS 覆盖保留作总兜底）
  - `ai_service/agent/react.py`（截断点 :357 改造 + ctx 阶段计数）
  - `ai_service/agent/langgraph_react.py`（同构截断改造）
  - `ai_service/tests/agent/test_agent_phase_fix.py`（单测并入）
- **实现要点**：
  1. **不删总预算字段**（兼容旧配置读取）；总预算 = `max_agent_tools`（默认值 4→5）。旧环境显式设 PW_MAX_AGENT_TOOLS=4 时总预算仍 4，阶段预算让位（截断取 min），行为正确、诚实记录。
  2. **阶段预算仅 tool_phase_split=true 时生效**（开关 false → 纯总预算，存量零影响——conftest 已钉住 false）。
  3. ctx 新增 `phase_count: dict[str, int] = {"retrieval": 0, "generation": 0}`，执行工具后按执行时 `ctx.phase` 递增（切 generation 前执行的全部算检索阶段）。
  4. **复用现有截断点**（react.py:357）：`phase_remaining = phase_budget(ctx.phase) - ctx.phase_count[ctx.phase]`；`allowed = tool_calls[: max(0, min(budget - tool_count, phase_remaining))]`。langgraph 同构。
  5. `if not allowed: break` 与兜底生成路径不动。
- **单测**：
  ① 检索阶段 3 次后即使总预算剩 2 也不放检索工具（第 4 次检索调用被截断 → 兜底/回答）
  ② 生成阶段 2 次截断（生成组内第 3 个工具被截断）
  ③ 总预算兜底仍生效（PW_MAX_AGENT_TOOLS=2 收紧场景，阶段预算让位）
  ④ 开关 false 阶段预算失效（纯总预算，存量行为逐字）
  ⑤ phase_count 按执行时阶段计数正确（检索命中切 generation 后新执行计生成）
- **通过标准**：单测全绿 + 066 评测重跑平均步数 ≤6（AC 既有标准）。

## 3. WP-C：066 评测重跑验证（半天）

- **目标**：`python -m eval.agent_tasks --mode agent` 重跑（真实 LLM+DB，建议 `--sample 10 --pass_k 3` 与 066 首跑同口径），对比首跑数字。
- **涉及文件**：无代码改动（仅运行 + 报告）；结果记录到 `specs/module-068-agent-phase-fix/changelog.md`。
- **执行步骤**：
  1. `cd ai_service && python -m eval.agent_tasks --mode agent --sample 10 --pass_k 3`（真实 LLM+DB，agent_eval_runs 落库；评测身份 eval-068-anon 测后清理）
  2. 对比 066 首跑：pass^1=0.0 → 新数字 / 工具正确率 0.0 → 新数字 / chat 0.6667 → 新数字 / pass^3=0.1 → 新数字
  3. 更新失败分类报告（预期 9/9 失败中大部分转 pass——4 轮全检索兜底的 now 检索命中即切 → generate_answer 可达；残余失败分类更新）
  4. **不达标不隐藏**：如实记录新数字，残余问题入 backlog（如 LLM 强制切后仍不调生成工具的行为性样本）
- **通过标准**：pass^1 显著提升（≥0.8 更好，**如实记录数字即可**，不预设成功）；工具正确率提升；平均步数 ≤6。
- **明确不做**：判定器/评测集（066 产物）不改不凑数；不调 `--fixture`（假 LLM 回放无法验证真实修复）。

## 4. WP-D：回归 + 文档收口（半天）

- **目标**：全量绿 + 文档闭环。
- **涉及文件**：
  - `ai_service/tests/agent/test_agent_phase_fix.py`（新增单测，WP-A/B 并入）
  - `specs/module-068-agent-phase-fix/changelog.md`（新增，项目模板，参考 `specs/module-066-agent-evaluation/changelog.md`）
  - `CONTEXT.md`（补 module-068 行 + 推进规则变更说明——**只增不删，先备份**，项目红线）
  - `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`（三记忆更新）
- **验证点**：全量 pytest = **1102 基线 + 新增全绿**、存量测试零改动（红线：react.py 仅 advance_phase/阶段相关 + config.py 预算字段可动；tool_registry.py / engine.py / 检索链路 / 066 判定器 / 评测集一律不碰）；真实 agent E2E 冒烟记录（工具轨迹出现 generate_answer）。
- **明确不做**：新 ADR（行为修复非架构决策；推进规则变更记录在 changelog，ADR-0012 方案 A 未推翻——只是推进条件增加确定性分支）；前端/Java 零改动。

## 5. 技术方案汇总

- **数据表**：无新增。
- **API 端点**：无新增。
- **外部依赖**：无新增（复用既有 LLM/检索链路）。
- **配置字段**（config.py，均带 PW_ 环境变量覆盖）：
  - `agent_retrieval_max_rounds: int = 3`（WP-A 防空转兜底）
  - `agent_retrieval_budget: int = 3` / `agent_generation_budget: int = 2`（WP-B 阶段预算）
  - `max_agent_tools` 默认 4→5（总兜底，PW_MAX_AGENT_TOOLS 兼容）
- **行数口径**：WP-A ~50 行（advance_phase 扩展 + _retrieval_hit + ctx 字段 + 两循环收集 results）+ WP-B ~35 行（config + 两循环截断改造）≈ 功能代码 85 行内（不含单测），符合 ≤200 行默认上限；单测新增 ~150 行（test_agent_phase_fix.py）。

## 6. 风险评估

- **命中判定字符串耦合**（"（无检索结果）"等空结果标记硬编码于 react.py）：与 tool_registry 文案耦合，若未来改文案判定失效——应对：判定规则单测钉住 + 注释标注耦合点；彻底解耦（工具层结构化信号）需碰 tool_registry，违反红线，记 backlog。
- **存量测试零改动红线**：双保险——① advance_phase 签名向后兼容（executed_results 缺省 None = 旧行为）；② 阶段预算联动 tool_phase_split 开关（conftest 钉住 false → 存量全量工具测试零影响）。
- **LLM 行为方差**（强制切 generation 后 LLM 仍可能不调 generate_answer）：循环继续至预算耗尽走既有 reflector 兜底，行为可接受；WP-C 如实记录此类残余失败样本。
- **deepseek 429 限流风暴**（历史观察）：降级链慢为外部抖动，如实记录，可重跑。
- **真实评测成本**（36 条任务集 × LLM 多轮）：`--sample 10` 控制；pass^3 只抽样（对齐 066 口径）。

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始版本（WP-A~D 拆解 + 代码实测事实 + 通过标准） | Planner |
