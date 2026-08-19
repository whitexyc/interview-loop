# Module-066 Task Brief：Agent 级评估体系

> 自包含执行简报（ADR-0017 落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。

## 事实（代码实测，2026-08-17）

1. `request_logs` 表（database.py:53-75）：timings JSONB（阶段耗时）+ usage JSONB（token），**无工具调用明细**——本模块核心缺口
2. `react.py` ReAct 循环：budget = `max_agent_tools=4`（config.py:86），每轮 `tool_calls[:budget - tool_count]` 截断，工具执行处是落库插入点
3. `eval/` 目录：golden（112 题）/ benchmarks（rrf_k/rerank/nli 等）/ train——全是检索/模型层，无任务级评测
4. eval_runs 版本化模式已有（git_commit + 配置快照落库），新表照抄该模式
5. 存量测试 897/0（47 个测试文件），全量回归基线

## WP-A：tool_call_logs 表 + 落库（半天）

- database.py 加 `tool_call_logs` DDL（ADR-0017 决策 2 的表结构），init_db 幂等建表
- react.py 工具执行处落库：trace_id / tool_name / args(JSONB) / result_ok / result_preview(截断 200) / duration_ms
- **只记录实际执行的 tool_calls**（预算截断掉的 LLM 提议不记，无对应结果）
- 开关 `PW_TOOL_CALL_LOGS`（默认 true），false 跳过落库（性能兜底）
- **通过标准**：单测（落库/开关/截断）+ E2E 一次 chat 后 query 到记录

## WP-B：任务级评测集（半天）

- 新建 `eval/agent_tasks.json`：**30-50 条**，每条含：
  ```json
  {
    "id": "at-001",
    "task": "什么是 RRF 融合？为什么比加权好？",  // 可含多轮追问（数组）
    "expected_tools": ["search_knowledge", "generate_answer"],
    "answer_points": ["倒数排名", "不依赖分数量纲"]
  }
  ```
- 来源：golden 112 题挑多轮/复杂题改写（20 条）+ 手工构造边界（casual_chat 直答、realtime 拒绝、检索不足重检、多轮省略句继承——module-063 能力覆盖）
- **通过标准**：30+ 条可用，覆盖 ≥6 类路径（knowledge 单轮/多轮/casual/realtime/重检/记忆）

## WP-C：评测脚本 + agent_eval_runs 落库（1 天）

- 新建 `eval/agent_tasks.py`：`python -m eval.agent_tasks --mode chat|agent --sample 10 --pass_k 3`
- 指标输出（ADR-0017 决策 1 三层）：
  - **Outcome**：pass^1（全量）/ pass^3（抽样 10 条跑 3 次全成功）
  - **Trajectory**：工具调用正确率（覆盖 + 无多调 + 参数类型，确定性判定规则见 ADR-0017 决策 4）
  - **System**：平均步数 / 平均 token / P50-P95 耗时
- 结果落 `agent_eval_runs` 表（git_commit + 配置快照 + 逐任务明细 JSONB）
- **判定器**：确定性（期望工具序列匹配 + answer_points 关键词包含），**不用 LLM-as-judge**（与项目确定性哲学一致）
- **通过标准**：脚本跑通输出全部指标；pass^1 ≥ 0.8（agent 多轮路径 ≥ 0.7）；工具正确率 ≥ 0.9；平均步数 ≤ 6；Grounding 1.0（降级链兜底不算错）

## WP-D：回归 + 文档收口

- 存量 897 全绿 + 新增单测（落库/评测脚本冒烟/判定器规则）
- 不达标 → 输出失败案例分类报告（工具选错/参数错/路径绕/答案缺要点），**不隐藏**（诚实工程惯例）
- 更新 CONTEXT.md（ADR-0017 + module-065 索引行）+ ADR-0017 状态标已实施

## 纪律项

1. 不新增不删工具、不改 react.py 循环逻辑（只在执行处加落库）
2. 不做模拟用户（τ-bench 式），那是后续演进——本期任务集是静态的
3. 判定器确定性优先，不引入 LLM judge（除非明确标注"需人工复核"）
4. chat/agent 两条路径（main.py react_loop + langgraph_react_loop）落库都要覆盖——agent 端点为主，langgraph 实验端点顺手带上
5. request_logs 不动（只加新表），存量测试零改动
