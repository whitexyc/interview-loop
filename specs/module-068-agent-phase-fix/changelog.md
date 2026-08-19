# Module-068 变更日志 — Agent 阶段推进死锁修复

> 实施：Developer（2026-08-17）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：react_loop 检索阶段死锁修复（检索命中即切 generation）+ 预算按阶段细分化
> + 066 评测重跑验证 + 回归收口。全量 pytest 基线 1102/0（module-067 交付口径）。

## 一、WP-A：死锁修复——检索命中即切 generation（核心）

**根因（066 实测 + Planner 代码核实）**：`advance_phase`（react.py）推进条件 =
"本轮调用过 generate_answer/verify_answer"，而 `schemas_for_phase` 按 ctx.phase
只暴露当前阶段工具（tool_phase_split 默认 true）——检索阶段 schema 不含生成
工具 → LLM 永远无法调用 generate_answer → 永不切 generation → 死锁在检索阶段
（预算耗尽走 reflector 兜底）。066 首跑 10 条任务 4.6 步全检索兜底、pass^1=0.1
即此盲区量化。

**实施**：
- `ai_service/agent/react.py`：
  - 模块常量 `_RETRIEVAL_HIT_TOOLS`（6 个：search_knowledge/search_fts/
    search_vector/search_graph/extract_entities/recall_memory，紧邻
    _GENERATION_GATE_TOOLS；**不含 re_search**——双组补检工具，命中判定排除）
    + `_EMPTY_RESULT_MARKERS`（"（无检索结果）"/"（无相关历史记忆）"，与
    tool_registry.py 文案耦合，红线不碰 tool_registry——耦合点注释标注 +
    单测钉住 + backlog）
  - 纯函数 `_retrieval_hit(name, result) -> bool`：工具名 ∈ 集合 + 结果非空 +
    排除空结果标记（均为非空字符串，bool(result) 误判命中坑）+ extract_entities
    json.loads 判 entities 非空（解析失败/无 entities 键按非空文本判定）。
    **零 LLM 判断**（AC-4 确定性纪律）。
  - `advance_phase(ctx, executed_names, executed_results=None)` **签名向后兼容
    扩展**：缺省 None 行为 = 旧逻辑（仅生成工具判定）——存量
    test_advance_phase_unit 单列表调用零改动；提供 results 时新增分支 `any(
    _retrieval_hit(n, r) ...)`。两条件任一满足即切 generation（原条件保留，
    兼容 tool_phase_split=false 路径）。
  - **防空转兜底**：ctx 新增 `retrieval_rounds: int = 0`；advance_phase 内
    phase 仍为 retrieval 且本轮未触发切换时递增，`>= settings.
    agent_retrieval_max_rounds`（默认 3，066 实测 4 轮预算耗尽取 3 = 预算-1）
    → 强制切 generation（参数化 PW_AGENT_RETRIEVAL_MAX_ROUNDS）。
  - react_loop 执行处同序收集 `executed_results: list[str]`（execute_tool_with_log
    返回值即得），调用点改 `advance_phase(ctx, executed_names, executed_results)`。
  - 兜底路径（预算耗尽 reflector.generate_answer）不动；执行层不校验 schema
    暴露的现状不动（at-002 症状：命中切后 generate_answer 在下一轮 schema 可见，
    自然消解）。
- `ai_service/agent/langgraph_react.py`：execute_tools 节点同构（收集 results +
  advance_phase 传参）。
- `ai_service/src/config.py`：新增 `agent_retrieval_max_rounds: int = 3`
  （PW_AGENT_RETRIEVAL_MAX_ROUNDS）。

**关键设计（死锁破法）**：推进规则 = 原条件（调过生成工具）∪ 确定性命中分支
（检索工具返回非空真实结果）∪ 防空转兜底（3 轮未命中强制切）——三条件任一
即切，单向前进不回退（generation 内 re_search 补检保留）。

## 二、WP-B：预算按阶段（检索 ≤3 + 生成 ≤2，总 5）

**实施**：
- `ai_service/src/config.py`：`agent_retrieval_budget: int = 3`（PW_AGENT_
  RETRIEVAL_BUDGET）+ `agent_generation_budget: int = 2`（PW_AGENT_GENERATION_
  BUDGET）；`max_agent_tools` 默认 4→5（**不删总预算字段**，旧配置读取兼容；
  旧环境显式 PW_MAX_AGENT_TOOLS=4 时总预算仍 4，阶段预算让位取 min，行为正确）。
- `ai_service/agent/react.py` + `langgraph_react.py`：截断点改造——`total_remaining
  = max(0, budget - tool_count)`；`tool_phase_split=true` 时 `phase_remaining =
  _phase_budget(ctx.phase) - ctx.phase_count[ctx.phase]`，`allowed = tool_calls[
  : min(total_remaining, phase_remaining)]`；**开关 false → 纯总预算存量行为
  逐字**（conftest 已钉住 false，存量全量工具测试零影响）。
- ctx 新增 `phase_count: dict[str, int]`，执行工具后按**执行时 ctx.phase** 递增
  （切 generation 前执行的全部算检索阶段）。
- `if not allowed: break` 与兜底生成路径不动。
- **langgraph 专用路由**：阶段额度耗尽（allowed 空但工具数 < 总预算）时
  execute_tools 返回 `phase_exhausted=True`，route_after_tools 走 fallback——
  与手写循环 `break → 兜底` 语义对齐，防"回 llm_call 后 allowed 恒空死循环"
  （真实 LLM 随机性下也可能空转，脚本化假 LLM 下必现）。

**设计取舍（诚实记录）**：阶段预算仅 tool_phase_split=true 生效——测试环境
conftest 钉住 false，故阶段预算在生产默认配置下生效、测试环境零漂移。

## 三、WP-C：066 评测重跑（真实 LLM+DB）

命令：`python -m eval.agent_tasks --mode agent --sample 10 --pass_k 3`（与 066
首跑同口径；本模块重跑 agent_eval_runs **id=3**，commit=2e932cee，评测身份
eval-066-anon 测后清理脚本内建）。

**对比基线（DB 实证，非 task-brief 冒烟数字）**：066 首跑 agent_eval_runs id=1
（--sample 10 --pass_k 3，2026-08-16 落库）：pass^1=0.1 / 工具正确率 0.1 /
pass^3=0.1 / 平均步数 4.6 / 平均 token 11851 / P50 25608ms / P95 44745ms /
per_path: knowledge_single 0/6、knowledge_multi 0/3、realtime 1/1。
task-brief 引用的 pass^1=0.0/工具正确率 0.0 系 066 冒烟 --limit 2 口径，如实
区分。

**⚠️ 勘误重写（诚实记录，Reviewer mustFix 回修）**：初版 changelog 以两条理由
排除 id=2，经核实**均不成立**，特撤回重写：
① **时间口径错**：`agent_eval_runs.created_at` 为 PG **UTC**（`SELECT
current_setting('TimeZone')` 实测 **Etc/UTC**），id=2=2026-08-16 23:58:57 UTC
= **2026-08-17 07:58 本地**，晚于本模块代码最后修改（config.py 07:35:49 /
react.py 07:36:07 / langgraph_react.py 07:36:25，本地文件 mtime）——"早于本
模块代码落地"**不成立**（初版将 UTC 落库时间与本地 mtime 直接比对所致）。
② **轨迹口径错**：per_question 判定轨迹（attempt 1）实测 id=2 at-002=4 工具；
tool_call_logs 中的"单任务最高 8 工具"系确定性 trace_id 跨 3 次尝试累积的
既有已知属性（§六已注明），且多轮任务**按轮重置预算**（8=4+4 不超任何预算
口径），id=1/2/3 平均工具数同为 4.6——"轨迹超默认预算口径"论证**删除**。
**id=2 并列报告（详见 §六 WP-A 通过标准证据）**：id=2 为 module-068 代码落地后
的真实运行——at-101 三次尝试轨迹均含 generate_answer（检索 3 → generate_answer
→ 补检 2）且该题 pass、at-303 零工具 pass → **pass^1=0.2**，系 WP-A 真实轨迹
实证；但 config_snapshot 仅含 RAG 配置（无 agent 侧 max_agent_tools/
tool_phase_split），**id=2 环境覆盖无法确证，如实标注**。主口径仍以 **id=3**
（pass^1=0.0，§六实测）为准，数字不变；id=2/id=3 同为 068 代码的两次独立运行，
pass^1 差异（0.2 vs 0.0）归因 LLM 行为方差（与 §六 at-303 转 fail 同类）。

## 四、WP-D：回归 + 文档收口

**测试**：
- 新增单测 **14 项**：`tests/agent/test_agent_phase_fix.py`——WP-A ① 检索命中
  即切 generation（tools_seen 序列断言生成组 4）② 3 轮未命中第 4 轮强制切 +
  阈值参数化 ③ generation 内 re_search 不回退（带 results 版本）④ 旧签名单
  列表调用存量行为 + 提供 results 命中分支 ⑤ `_retrieval_hit` 纯函数边界 8 例
  ⑥ langgraph 同构命中切；WP-B ① 检索阶段 3 次后第 4 次截断 → 兜底 ② 生成
  阶段 2 次后第 3 个截断 → 兜底 ③ 总预算兜底（budget=2 收紧场景）④ 开关 false
  阶段预算失效（纯总预算）⑤ phase_count 按执行时阶段计数 + langgraph 阶段
  截断 fallback 路由（phase_exhausted）。
- **存量测试更新 6 处（⚠️ plan 矛盾点，详见 §五）**：`tests/agent/
  test_tool_phase_split.py` 6 个用例的 schema 序列断言（tools_seen[1] 由
  RETRIEVAL_7 → GENERATION_4）——module-068 推进规则改变后第 1 轮检索命中即
  切，断言的是"第 2 轮仍在检索组"的旧时序；仅改断言值与注释，其余断言与
  预算路径测试（tool_count/兜底答案）逐字保持。
- `tests/conftest.py`：新增 autouse fixture 钉住 `max_agent_tools=4`（生产默认
  已 4→5，存量 react/langgraph 测试断言 budget==4——test_agent_tools.py 3 处 +
  test_rerank_langgraph.py 1 处；钉住使存量断言逐字保持，对齐 056/058/066
  conftest 模式；新测试显式传 budget 覆盖）。
- 全量 pytest：**1116 passed / 0 failed**（= 1102 基线 + 14 新增；`scripts/
  test_models.py` 1 项 module-050 遗留收集 ERROR 未触碰，沿用）。

**验证命令**：
| 验证项 | 命令（工作目录 ai_service/） | 结果 |
|--------|------------------------------|------|
| 新增单测 | `python -m pytest tests/agent/test_agent_phase_fix.py -q` | 14/0 ✅ |
| 阶段切分存量回归 | `python -m pytest tests/agent/test_tool_phase_split.py tests/agent/test_agent_tools.py -q` | 全绿 ✅ |
| 全量回归 | `python -m pytest -q` | 1116/0 ✅ |
| 066 评测重跑 | `python -m eval.agent_tasks --mode agent --sample 10 --pass_k 3` | §三 |
| 真实 E2E 冒烟 | 真实 agent chat 工具轨迹 | §三/§六 |

**真实 E2E 冒烟**：（WP-C 一并验证——见下节）

## 五、⚠️ plan 矛盾点与处理（诚实记录，供 Reviewer 裁定）

plan §0 对存量测试的兼容分析只覆盖了 `test_advance_phase_unit`（135-145 行
直接单列表调用，签名向后兼容已保住），**未覆盖同文件 6 个循环级用例**——它们
断言"第 2 轮 schema 仍为检索组"的旧推进时序（检索命中前的等待语义）。module-068
核心特性（检索命中即切）与这些断言**互斥**（逐轮推演实证：第 1 轮
search_knowledge 返回非空 docs → 命中 → 第 2 轮 schema 必为生成组）：
- 受影响用例：test_react_loop_retrieval_schema_7_then_generation_4 /
  test_verify_answer_switches_to_generation / test_re_search_in_generation_
  no_regression / test_budget_exhausted_fallback_unchanged / test_langgraph_
  phase_switch / test_langgraph_re_search_in_generation_no_regression。
- 处理：**仅更新 6 处 schema 序列断言值（RETRIEVAL_7 → GENERATION_4）+ 注释
  说明 module-068 语义，零其他改动**；tool_count/兜底答案/预算路径断言逐字
  保持。若严格红线"存量测试零改动（改了=FAIL）"，则本模块核心特性不可实现
  （矛盾），需 Reviewer 裁定：按本变更（推荐，对齐 module-058/061/062 "按验收
  许可更新"先例）或回退特性。
- 另：conftest 新增钉住 max_agent_tools=4 亦为默认值变更（4→5）与存量断言
  （budget==4）矛盾的化解，采用"测试环境钉住 + 生产新默认"双轨（module-066
  conftest 加 autouse 先例）。

## 六、WP-C 实测（2026-08-17 补录）

**重跑结果（agent_eval_runs id=3，2026-08-17 01:16:12 UTC = 09:16 本地落库，默认配置 max_agent_tools=5 + tool_phase_split=true）**：

| 指标 | id=1（066 首跑） | id=3（068 重跑） | 变化 |
|------|------------------|------------------|------|
| pass^1 | 0.1 | **0.0** | 未提升（如实记录） |
| 工具正确率 | 0.1 | 0.1 | 持平 |
| 无多调率 | 0.1 | 0.2 | +0.1 |
| 参数正确率 | 1.0 | 1.0 | 持平 |
| Grounding | — | 1.0 | 读回正常 |
| 平均步数 | 4.6 | 4.6 | 持平（≤6 ✅） |
| 平均 token | 11851 | 16556.6 | +39.7%（预算 4→5） |
| 耗时 P50/P95 | 25608/44745ms | 24543.5/37367ms | 略降 |
| knowledge_single | 0/6 | 0/6 | 持平 |
| knowledge_multi | 0/3 | 0/3 | 持平 |
| realtime | 1/1 | **0/1** | at-303 转 fail（LLM 答案方差） |
| 失败分类 | 工具选错 ×9 | 工具选错 ×8 + 工具漏调 ×1 + 答案缺要点 ×1 | 分类细化 |

**结构性修复已生效（实证，与 pass^1 持平并行不悖）**：
- 单测 14 项 + 存量 test_tool_phase_split/test_agent_tools 80 项全绿——schema 切换/防空转兜底/阶段预算逻辑正确。
- 真实轨迹显示阶段推进确实发生：单轮任务工具序列呈"检索 2 + 生成阶段 2"形态
  （如 at-002=[search_knowledge, extract_entities, search_knowledge,
  search_knowledge]——第 1 轮检索命中切 generation 后，第 2 轮 2 个工具按生成
  阶段计数被阶段预算截断），对比 066 首跑"4 轮全检索"，阶段状态机真实生效。
- **但 LLM 行为性残余（pass^1 未提升的根因）**：生成阶段 schema（GENERATION_4）
  下 deepseek 仍持续输出 search_*/extract_entities 调用——`_SYSTEM_PROMPT`
  全量列出 10 个工具名（react.py:44-67）+ 执行层不校验 schema 暴露（at-002
  现象，module-066 Tester 已记录）→ 模型"信息足够后调 generate_answer"的
  行为门槛多数时候不满足，持续补检至阶段预算截断 → 兜底生成 → **判定轨迹
  （attempt 1）全部缺 generate_answer → 覆盖规则全败**（28 条尝试轨迹中仅 2 条
  含 generate_answer：at-016-2、at-101-3，见下"WP-A 通过标准证据"）。plan §6
  已预判此类残余（"强制切 generation 后 LLM 仍可能不调 generate_answer（行为性
  残余）"），如实兑现。

**WP-A 通过标准证据（plan §1 通过标准 = 单测全绿 + 真实轨迹出现 generate_answer
调用，不再全检索兜底；AC-7）**——本模块两次真实运行均满足"真实轨迹出现
generate_answer"：
- **id=2（23:58:57 UTC = 08-17 07:58 本地，代码落地后运行，§三并列报告）**：
  27 条尝试轨迹中 5 条含 generate_answer——at-101 三次尝试全部为"检索 3 →
  generate_answer → 补检 2"、at-002-3 / at-016-2 各 1 次；判定轨迹 at-101
  （attempt 1）经 generate_answer 达 pass（coverage=true；tool_correct 仍
  false——判定器期望 2 工具严格口径）+ at-303 零工具 pass → **pass^1=0.2**。
- **id=3（01:16:12 UTC = 09:16 本地，主口径）**：28 条尝试轨迹中 2 条含
  generate_answer（at-016-2、at-101-3），但 10 条判定轨迹（attempt 1）全部缺
  generate_answer → 覆盖规则全败 → pass^1=0.0（数字不变）。
- **同代码两次运行 pass^1 0.2 vs 0.0**：generate_answer 是否进入判定轨迹
  （id=2 5/27 vs id=3 2/28 尝试）系 deepseek 行为方差——**修复消除结构性死锁
  （检索命中即切 + generate_answer 真实可达轨迹），pass^1 未提升的残余为 LLM
  行为性**（与本节结论一致）。id=2 的 agent 侧配置（max_agent_tools/
  tool_phase_split）config_snapshot 未记录，环境覆盖无法确证，如实标注。

**残余失败分类（判定器四规则口径，不隐藏）**：
- 工具选错 ×8：知识类任务实际轨迹缺 generate_answer 且多调（期望
  [search_knowledge, generate_answer]，实际 3-8 个检索调用）——**全部是
  "schema 不引导调用"残余**：schema 已含生成工具，LLM 行为性不调。
- 工具漏调 ×1（at-016）：4 个 search_knowledge 纯重复调用，零其他工具
  （判定轨迹 attempt 1 口径；尝试 2 实际调过 generate_answer 仍未判 pass，
  见上 WP-A 证据）。
- 答案缺要点 ×1（at-303 realtime）：零工具直接回答，答案未覆盖 answer_points
  ——id=1 该题 pass，本批转 fail 系 LLM 答案方差（非本模块回归，如实记录）。

**真实 E2E 冒烟（WP-C 一并验证，证据均来自 id=3 落库可复现数据）**：eval 运行
日志确认全链路真实（deepseek 200 + 真实图检索 entities 2-5 + 阶段截断触发
"工具预算耗尽 (budget=5) 用 N 篇已收集文档兜底生成"）；per_question 轨迹（
agent_eval_runs id=3 per_question JSONB）与 budget=5+阶段预算 3/2 完全吻合——
单轮任务 ≤4 工具（如 at-002=[search_knowledge, extract_entities,
search_knowledge, search_knowledge]：第 1 轮检索 2 + 第 2 轮生成阶段 2 截断）、
双轮任务 ≤8（两轮各 ≤3 检索 + ≤2 生成阶段）——**阶段状态机与截断真实生效**。
（注：tool_call_logs 中 eval-at-105-1 等 24-25 行系 id=1/2/3 三次运行共用确定性
trace_id 的累积，非单次超预算——066 已知属性。）**结论：修复消除结构性死锁
（检索阶段 schema 含生成工具可达），但真实 pass^1 未提升——行为性残余须
结构性手段（执行层校验 schema 暴露 / 提示词与阶段 schema 对齐），入 backlog。**

**待办（backlog）**：
1. **执行层校验 schema 暴露**（拒绝非当前阶段工具调用）——066 at-002 已记录，
   本模块实测再次确认是行为性残余根因之一；属结构性约束，需碰执行层循环。
2. **`_SYSTEM_PROMPT` 与阶段 schema 对齐**——全量工具清单与阶段过滤不一致，
   模型从提示词知道全部工具名；改提示词按阶段动态生成或明确"仅可调用 API
   提供 schemas 的工具"。
3. **生成阶段 LLM 连续不调 generate_answer 的强制兜底**（与防空转兜底同构：
   生成阶段轮次 ≥N 未调生成工具 → 直接走 reflector 兜底，省预算不省功能）。
4. at-303 realtime 答案缺要点为 LLM 方差，重跑观察。

## 七、明确不做（纪律确认）

- tool_registry.py / engine.py / 检索链路零改动（git diff 核对）。
- 066 判定器 / 评测集（agent_tasks.json / agent_tasks.py）不改不凑数。
- 无新 ADR（行为修复非架构决策；ADR-0012 方案 A 未推翻，推进规则增加确定性
  分支，记录于本 changelog）。
- 前端 / Java 零改动。
- 未引入"LLM 自报检索完成"机制（零 LLM 判断纪律）。

## 八、已知边界与 backlog

- **空结果标记字符串耦合**："（无检索结果）"/"（无相关历史记忆）"硬编码于
  react.py，与 tool_registry 文案耦合——未来改文案判定失效；应对：判定规则
  单测钉住 + 注释标注；彻底解耦（工具层结构化信号）需碰 tool_registry 违反
  红线，记 backlog。
- **search_graph 空实体标记**："（图检索：未提取到实体）"不在排除标记清单内
  （plan 只列 2 个标记）——图无实体时切 generation 属轻度次优（生成组仍有
  re_search 补检口），如实声明，未扩大 plan 范围。
- LLM 行为方差：强制切 generation 后 LLM 仍可能不调 generate_answer（行为性
  残余）——循环继续至预算耗尽走既有 reflector 兜底，可接受；WP-C 如实记录
  此类残余失败样本。
- deepseek 429 限流风暴（历史观察）：降级链慢为外部抖动，如实记录，可重跑。

## 九、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始实现（WP-A 死锁修复 + WP-B 阶段预算 + 14 单测 + 存量 6 断言按新语义更新 + conftest 钉住） | Developer |
| v2 | 2026-08-17 | WP-C 实测补录（id=3 重跑：pass^1=0.0 未提升如实记录 + 结构性生效实证 + 行为性残余分类 + backlog）+ §三勘误（id=2 非本模块重跑，不采信） | Developer |
| v3 | 2026-08-17 | Review 回修（Reviewer mustFix ①②③）：§三勘误重写——created_at 为 PG UTC（`SELECT current_setting('TimeZone')` 实测 Etc/UTC），id=2=08-17 07:58 本地晚于代码落地（07:35-07:36 mtime），"早于"不成立；删除"轨迹超预算"论证（多轮按轮重置预算 + "8 工具"系 trace_id 累积误读）；id=2 并列报告（pass^1=0.2，at-101 经 generate_answer 达 pass，config_snapshot 无 agent 配置环境覆盖无法确证如实标注），id=3 主口径数字不变；§六补 WP-A 通过标准证据（id=2/id=3 真实轨迹 generate_answer 实证 5/27 vs 2/28）+ "从未入轨迹"按判定轨迹（attempt 1）口径澄清 | Developer |
