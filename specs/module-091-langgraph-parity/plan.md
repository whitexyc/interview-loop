# 开发计划 — Module-091: LangGraph 复刻实验 → 转正对比报告（阶段 E）

> Planner: 2026-09-07 | 依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 E
> 范围：同一评测集下「手写 ReAct 循环 vs LangGraph StateGraph」的等价性 + 质量/成本对比，产出**可复现结论**
> 预算：WP-A 半天 + WP-B 1 天（含真实跑批等待）+ WP-C 半天 ≈ 2 天
> **红线：生产代码零改动**（`agent/` `src/` `main.py` 全部零 diff），本模块只加 `eval/` 脚本 + 测试 + 报告

## 0. Planner 已探明事实（勿重复调查）

| # | 事实 | 证据 |
|---|------|------|
| 1 | 阶段 E 是官方路线图最后一块，验收方向=「框架 vs 自研，同一评测集，含耗时/成本/成功率，结论可复现」 | `knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` §阶段 E |
| 2 | LangGraph 版已存在且非玩具：4 节点 StateGraph（llm_call / execute_tools / finalize / fallback），复用 `ReactContext`、`ToolRegistry`、`execute_tool_with_log`、`advance_phase` | `agent/langgraph_react.py:280-308`（`build_react_graph`） |
| 3 | LangGraph 版有**非流式测试入口** `langgraph_react_agent(query, history, identity, budget, tools)`，返回 `{answer, tool_count, tool_trace}` —— 与手写版可直接对拍 | `agent/langgraph_react.py:382-421` |
| 4 | 手写版主路径 `react_loop`，595 行；LangGraph 版 421 行；两者事件协议一致（token/tool_call/tool_result/done） | `agent/react.py`（595 行）、`langgraph_react.py:337-342` docstring |
| 5 | 066 评测基建可直接复用：`load_agent_tasks` / `run_eval` / `compute_scores` / `outcome_pass` / `save_agent_eval_run` / `_FixtureClient` | `eval/agent_tasks.py:94, 448, 233, 193, 544, 507` |
| 6 | 任务集 36 条，字段 `{id, task, expected_tools, answer_points}`，`task` 可为数组（多轮） | `eval/agent_tasks.json`（实测 36 条） |
| 7 | **fixture 假 LLM 补丁点不同源**：手写版 patch `agent.react.LLMFactory`；LangGraph 版 LLM 调用在 `agent/langgraph_react.py::llm_call`，须 patch `agent.langgraph_react.LLMFactory` | `eval/agent_tasks.py:368` vs `langgraph_react.py:98-101` |
| 8 | `agent_eval_runs` 表有 `config_snapshot` JSONB 列 → 用 `config_snapshot.loop` 区分两条环路，**零新表零 ALTER** | `eval/agent_tasks.py:544-572` |
| 9 | 存量测试基线 **1754 passed / 0 failed / 3 skipped**（module-090 验收，2026-09-06） | `memory/project-context.md` §5 |
| 10 | 066 判定先例：**确定性判定，不用 LLM 评 LLM**（Outcome 用 answer_points 关键词命中） | `eval/agent_tasks.py:193` `outcome_pass` |

## 1. 目标与非目标

**目标**：把「参考 LangGraph 自研」从**定位声明**变成**有数据的结论**——两份证据：
1. **行为等价性**（确定性、零 LLM）：同一假 LLM 计划下，两条环路的工具序列逐字一致
2. **质量/成本对比**（真实模式）：同任务集、同 k 下的 pass^k、工具正确率、tokens、延迟 P50/P95

**非目标（明确不做）**：
- 不做主路径切换（结论出来前不动 `/ai/rag/chat/agent` 与 `engine.chat`，切换若被建议也归下一模块）
- 不引入 LangGraph 新依赖（`langgraph` 已在 requirements 内，`langgraph_react.py:31` 在用）
- 不做多 Agent 编排（路线图标注 T5 明确不做）
- 不重写两条循环的内部逻辑（只观测、不改）

## 2. WP-A：等价性夹具（半天，零 LLM，最硬的证据）

- **目标**：证明 LangGraph 版与手写版在**相同输入**下行为一致——这是"复刻"成立的底线。
- **新增文件**：`ai_service/eval/langgraph_parity.py`（唯一新增生产侧脚本）
- **设计**：
  ```python
  async def run_pair(item: dict, k: int) -> dict:
      """同一任务同一 fixture 计划，分别驱动两条环路，比对工具序列"""
  ```
  - fixture 计划 = `item["expected_tools"]` 逐次回放（复用 `eval/agent_tasks._args_for` + `_fixture_registry` 思路）
  - 手写侧：`mock.patch("agent.react.LLMFactory.get_client", ...)` + `react_loop`
  - LangGraph 侧：`mock.patch("agent.langgraph_react.LLMFactory.get_client", ...)` + `langgraph_react_loop`
  - 比对维度（全部确定性，不用 LLM）：
    1. 工具名序列 `actual_names` **逐字相同**
    2. 工具调用次数 `tool_count` 相同
    3. 最终答案相同（fixture 答案为 `answer_points` 拼接，确定性）
    4. 判定器四规则（coverage / no_extra / args_ok / pass）结果相同
  - 输出：36 条 × 4 维的逐条比对表 + 一致率
- **通过标准**：等价率 100%；**任何一条不一致都必须逐条列出并归因**（不允许静默通过）
- **明确不做**：不修改 `eval/agent_tasks.py`（只 import 复用其纯函数），不 patch 生产代码

## 3. WP-B：真实模式对比（1 天）

- **目标**：同任务集、同 `pass_k`、同 `--sample` 子集，两条环路各跑一次，产出三层指标。
- **涉及文件**：`ai_service/eval/langgraph_parity.py`（复用 WP-A 的运行器，加 real 分支）
- **指标（对齐 066 三层 + 补延迟）**：
  | 层 | 指标 | 来源 |
  |----|------|------|
  | Outcome | pass^1 / pass^3 | `outcome_pass`（关键词命中，确定性） |
  | Trajectory | 工具正确率（coverage + no_extra + args_ok 全过） | `eval/agent_tasks.compute_scores` |
  | System | tokens 总量、工具步数、延迟 P50/P95 | `_sum_usage` + `_percentile` |
- **落库**：两次 `save_agent_eval_run`，`config_snapshot` 增 `{"loop": "hand"|"langgraph", "module": "091"}`，`git_commit` 记录当前 HEAD
- **诚实边界（必须写进报告）**：
  - 真实 LLM 有随机性 → 单轮结果不具统计显著性，须标注"单次采样，非置信区间"
  - 供应商限流/网络抖动会影响延迟 → 两条环路**交替执行**（hand, langgraph, hand, langgraph…）以摊平时段影响，不得先跑完一条再跑另一条
  - 成本口径：tokens 不分桶（沿用 085/089 口径），不换算金额
- **通过标准**：两条 run 均成功落库且指标字段完整；若任一条报错，如实记录失败原因，不重跑掩盖

## 4. WP-C：对比报告 + ADR-0020（半天）

- **产出**：
  - `specs/module-091-langgraph-parity/parity-report.md`：等价性表（36 条）+ 真实模式对比表 + **明确结论**
  - `specs/adr/0020-langgraph-parity.md`：架构决策（转正 / 维持自研），含判据与结论
- **转正判据（事前定死，防事后找补）**——全部满足才建议转正：
  1. WP-A 等价率 = 100%
  2. LangGraph `pass^1` ≥ 手写 `pass^1 - 0.05`
  3. LangGraph tokens ≤ 手写 × 1.20 且 延迟 P95 ≤ 手写 × 1.20
  - 任一不满足 → **建议维持自研**，并写清差在哪
- **无论结论如何，报告如实写**——结论对自研不利（LangGraph 更好）也必须照实写，这是本模块的信用所在

## 5. 代码量预估

| 文件 | 性质 | 预估 AST |
|------|------|----------|
| `eval/langgraph_parity.py` | 新增（评测脚本） | ~95 |
| `tests/eval/test_langgraph_parity.py` | 新增（单测） | 不计生产口径 |
| `parity-report.md` / `0020-langgraph-parity.md` | 文档 | 不计 |

合计 **~95 AST ≤ 200** ✅；生产代码（`agent/` `src/` `main.py`）**零改动**。

## 6. 风险与应对

| 风险 | 应对 |
|------|------|
| 真实跑批耗时/成本高 | 默认 `--sample 12`（36 条抽样），全量跑为可选项；交替执行摊平抖动 |
| LangGraph 版长期未维护，可能有漂移 | 等价性夹具会直接暴露；若 fixture 就跑不通，结论写"实验分支已失修" |
| recursion_limit / TypedDict 与 LangGraph 版本不兼容 | WP-A 先跑通一条再全量；版本信息写进报告环境段 |
| 结论对自己不利 | 照实写（见 §4） |

## 7. 依赖与顺序

- 前置：module-090 已收官 ✅；066 评测基建 ✅；LangGraph 版已存在 ✅
- 顺序：WP-A（确定性，先跑通）→ WP-B（真实跑批）→ WP-C（报告 + ADR）
- 后续（不属本模块）：若结论=转正，另开模块做主路径切换；若结论=维持，实验端点保留并在 README 标注"实验分支，对比结论见 091"
