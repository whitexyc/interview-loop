# 开发计划 — Module-092: 对比评测深化（多轮采样 + 分阶段遥测 + 冷启动）

> Planner: 2026-09-07 | 依据：用户指令「多测试几次，各阶段数据都要看，冷启动对比也要，要详细（时间/token/工具调用次数）」
> 前置：module-091 已验收（v0.91.0，等价率 100%，维持自研）；本模块是 091 的**数据深化轮**，不改结论框架
> 红线：**生产代码零改动**（`agent/` `src/` `main.py` 零 diff，与 091 同款）；`eval/langgraph_parity.py` 可继续扩展或新建 `eval/parity_telemetry.py`

## 0. Planner 已探明事实（勿重复调查）

| # | 事实 | 证据 |
|---|------|------|
| 1 | 091 脚本 CLI 已有 `--mode/--sample/--pass-k/--limit/--no-save`；real 模式固定种子 `random.Random(42)` 抽样 | `eval/langgraph_parity.py:335-361` |
| 2 | `chat_with_tools` 返回 `{"content","tool_calls","message"}`，**不含 usage**；usage 由模块级 `_record_usage(label, raw)` 在 client 内部逐次上报（含 prompt/completion 拆分） | `llm/client.py:235, 278, 94-140` |
| 3 | → **逐次 LLM 调用的 tokens 可经 eval 层拦截 `_record_usage` 捕获**（mock.patch 包装原函数 + 追加到 eval 本地列表），零生产 diff | 同上 |
| 4 | `tool_call_logs` 每工具行有 `duration_ms`/`result_ok`/`tool_name` → 工具阶段耗时/次数/失败可直查 | `src/database.py`（091 已用） |
| 5 | `request_spans` 有 `duration_ms/started_at/kind`（088 span 树）→ 备用数据源 | `src/database.py:154-166` |
| 6 | **冷启动测量点**：`agent/langgraph_react.py:312` 模块级 `react_graph = build_react_graph()`（import 即编译图）；手写版 import 无图编译 → 进程级冷启动差异可测 | `agent/langgraph_react.py:311-312` |
| 7 | 091 单轮成本基线：24 次运行 tokens 合计 ≈28.3 万（≈1.2 万/次）→ 本模块默认 `--repeat 3 × --sample 12 × 2 环路 = 72 次 ≈ 84 万 tokens`，成本显著，须有 `--repeat 1` 逃生口并如实报告 | 091 parity-report.md |
| 8 | 091 遗留：3 函数 docstring 缺 Args/Returns（Tester minor ②）——本模块顺带修（同文件内，不新增模块） | test-report.md |

## 1. WP-A：多轮采样（核心诉求①）

- **目标**：消除"单次采样无统计效力"的诚实边界——同一任务集重复跑 N 轮，输出聚合统计。
- **设计**：新增 `--repeat N`（默认 3）；每轮 = 完整的 sample 抽样 + 交替双跑；轮与轮之间任务顺序重洗（不同种子，防顺序效应）但**抽样集合固定**（同一 12 条，保证跨轮可比）。
- **聚合输出**（每指标）：mean ± std、min、max、逐轮明细表；`pass^1` 按轮报告 + 汇总"3 轮中 LangGraph 优于手写的轮数"。
- **落库**：每轮一对 `save_agent_eval_run`（config_snapshot 增 `{"repeat": i, "repeat_of": N}`），可对账。
- **通过标准**：`--repeat 3` 产出 3×2=6 条 run；聚合表含 mean/std/min/max；报告明确"多轮采样后 P95 结论是否翻转"。

## 2. WP-B：分阶段遥测（核心诉求②）

- **目标**：把每次运行的总耗时拆成 **LLM 轮次 / 工具执行 / 编排开销** 三段，逐环路对比——这正是 ADR-0020 留下的"StateGraph 开销归因"钥匙。
- **数据源（全部 eval 层拦截，零生产 diff）**：
  1. **LLM 轮次**：timing proxy 包装 client（计每次调用耗时）+ 拦截 `llm.client._record_usage`（计每次 prompt/completion tokens）→ 每环路：调用次数、总/mean/P50 耗时、tokens 合计与逐次分布
  2. **工具执行**：`tool_call_logs` 按 `tool_name` 分组：次数、总/mean/P50 `duration_ms`、失败数
  3. **编排开销** = 请求总 `duration_ms` − ΣLLM 耗时 − Σ工具耗时 → **两条环路对比此值即 StateGraph 调度开销归因**
- **输出表**：每环路 × 每阶段（LLM/工具/编排）的耗时绝对值 + 占比 + 两侧差值；工具级明细表（10 工具 × 2 环路）。
- **通过标准**：三段之和与总时长闭合（误差 <2%，超出须解释）；两环路的编排开销差值有明确数字。

## 3. WP-C：冷启动对比（核心诉求③）

- **目标**：量化"冷启动之后的对比"——首次调用开销 vs 预热后。
- **测量点**：
  1. **进程级编译冷启动**：独立子进程分别 `import agent.react` 与 `import agent.langgraph_react`，计时（后者含图编译）——差异即"框架编译冷启动"
  2. **首次调用 vs 预热**：每轮 repeat 的第 1 条任务记为 cold，其余 warm；报告 cold 与 warm 中位的比值 × 2 环路
  3. **公平性声明（必须写）**：本地模型加载（bge-m3/reranker）在两环路共享（同一进程内工具复用），属共同成本不计入环路差异；LLM 连接建立（首次网络握手）对两环路同为一次
- **通过标准**：编译冷启动差值有毫秒级数字；cold/warm 比值 × 2 环路成表。

## 4. WP-D：报告与遗留清理

- `specs/module-092-parity-telemetry/deep-telemetry-report.md`：多轮聚合表 + 分阶段拆解表 + 冷启动表 + **结论复核**（多轮数据下 ADR-0020 的"维持自研"是否仍成立——若 P95 多轮均值落回 1.20 内，按 ADR-0020 预留的重启条件如实提请复核，不擅自改判）
- 顺带修 091 遗留：`print_equivalence/print_real/main` 3 函数 docstring 补 Args/Returns（Tester minor ②）
- changelog.md：AST 复算、偏离申报、命令输出

## 5. 代码量与约束

- 预估：`eval/` 内新增/扩展 ~150 AST ≤ 200（遥测代理 + 聚合 + 冷启动子进程计时 + 报告打印）
- 红线：`agent/` `src/` `main.py` 零 diff；单测 `tests/eval/test_parity_telemetry.py`（拦截器、三段闭合、聚合统计、cold/warm 判定）
- 全量回归基线 **1769/0/3** 零新增失败

## 6. 风险与成本

| 风险 | 应对 |
|------|------|
| 真实跑批 72 次耗时 ~40-60 分钟、tokens ~84 万 | 默认 repeat=3；`--repeat 1 --limit 2` 冒烟先行；报告如实报总成本 |
| 限流 429（deepseek key 已 401，qwen 为主） | 沿用 091 先例：qwen shell 环境变量；失败如实记 fail_reason 不重跑 |
| 三段闭合对不齐（异步计时重叠） | 工具耗时与 LLM 耗时天然不重叠（串行 await），闭合校验兜底 |
| 多轮结果波动大 | 这本身就是数据——如实报 std，不做"挑好看的一轮" |
