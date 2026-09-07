# 验收标准 — Module-092: 对比评测深化（多轮采样 + 分阶段遥测 + 冷启动）

> Planner: 2026-09-07 | 配套 plan.md | 红线：`agent/` `src/` `main.py` 零 diff；基线 1769/0/3 零新增失败

## 1. 功能验收

| # | 验收项 | 判据（可机械断言） |
|---|--------|--------------------|
| AC-1 | 多轮采样 | `--repeat 3` 产出 3 轮 × 2 环路完整运行，轮间抽样集合相同（同一任务 id 集）、任务顺序重洗 |
| AC-2 | 聚合统计 | 每指标（pass^1/工具正确率/tokens/P50/P95）输出 mean±std/min/max + 逐轮明细 |
| AC-3 | 落库可对账 | 6 条 run 入 agent_eval_runs，config_snapshot 含 repeat/repeat_of；`git_commit` 逐条记录 |
| AC-4 | LLM 阶段遥测 | 每环路：调用次数、总/mean/P50 耗时、tokens 合计（prompt/completion 拆分）——来自 client proxy + `_record_usage` 拦截 |
| AC-5 | 工具阶段遥测 | 每环路按 tool_name 分组：次数、总/mean/P50 duration_ms、失败数（tool_call_logs 直查） |
| AC-6 | 编排开销归因 | 编排开销 = 总时长 − ΣLLM − Σ工具，两环路各自成值且差值有明确数字（StateGraph 归因） |
| AC-7 | 三段闭合 | 每次运行三段之和 vs 总 duration_ms 误差 <2%；超限逐条列出并解释 |
| AC-8 | 编译冷启动 | 独立子进程计时 `import agent.react` vs `import agent.langgraph_react`（后者含 build_react_graph），差值毫秒级成表 |
| AC-9 | cold/warm 对比 | 每轮首条任务记 cold、其余 warm；cold 与 warm 中位比值 × 2 环路成表 |
| AC-10 | 公平性声明 | 报告写明：本地模型加载为两环路共同成本不计入差异；LLM 首次握手同为一次 |
| AC-11 | 判定确定性 | 全流程无 LLM 评判；数据全部来自计时/库表/拦截器 |
| AC-12 | 失败不掩盖 | 任一次运行异常记 fail_reason 列出；不重跑挑数据；多轮 std 如实报 |

## 2. 非功能验收

| # | 验收项 | 判据 |
|---|--------|------|
| AC-13 | 生产代码零改动 | `git diff --stat` 对 agent/src/main.py 全空 |
| AC-14 | 代码量 | 本模块新增 AST ≤ 200（实测复算）；顺带修 091 遗留 3 函数 docstring（Args/Returns） |
| AC-15 | 方法/类规模 | 方法 ≤50 行 |
| AC-16 | 单测 | `tests/eval/test_parity_telemetry.py`：拦截器捕获、三段闭合计算、聚合统计、cold/warm 判定，全绿 |
| AC-17 | 全量回归 | 1769/0/3 零新增失败 |
| AC-18 | 报告可复现 | 报告含运行命令、commit、repeat/sample 参数、总成本（tokens 与墙钟） |

## 3. 结论验收

| # | 验收项 | 判据 |
|---|--------|------|
| AC-19 | 结论复核 | 明确回答：多轮数据下 ADR-0020"维持自研"是否仍成立（P95 多轮均值 vs 1.20 阈值）；若翻转，**如实提请复核**，不擅自改判也不回避 |
| AC-20 | StateGraph 归因 | 给出编排开销差值的数字与解释（节点调度/状态拷贝/路由），无法归因的部分如实标"未定位" |

## 4. Tester 对账（T1-T6）

| # | 对账项 | 方法 |
|---|--------|------|
| T1 | 6 条 run 落库 | SQL 查 config_snapshot->>'repeat' 0/1/2 × loop 两值，逐条 commit 一致 |
| T2 | 逐轮数字对账 | 任抽 1 轮：报告逐轮明细 vs 库内 per_question 复算一致 |
| T3 | 三段闭合抽验 | 任抽 3 次运行独立复算三段之和 vs 总时长 |
| T4 | 冷启动复现 | 独立跑子进程 import 计时，数字与报告同量级（±30% 内，进程噪声如实标注） |
| T5 | 红线零 diff + 单测全绿 + 全量 1769/0/3 | 独立复跑 |
| T6 | 清理还原 | 评测 trace 精确清理（**时间窗口径**，091 勘误先例），行数还原如实记录；无临时文件残留 |

## 5. 可运行命令表

```bash
cd interview-personal/ai_service
# 冒烟（快，先跑）
.venv/Scripts/python.exe -m eval.langgraph_parity --mode real --repeat 1 --sample 2 --limit 2 --no-save
# 正式（默认 3 轮 × 12 任务 × 2 环路）
.venv/Scripts/python.exe -m eval.langgraph_parity --mode real --repeat 3
# 单测 + 全量
python -m pytest tests/eval/test_parity_telemetry.py -q
python -m pytest tests/ -q
```

## 6. 验收结论签署区

| 角色 | 结论 | 日期 | 备注 |
|------|------|------|------|
| Developer | ⬜ | | changelog.md |
| Reviewer | ⬜ | | review-report.md |
| Tester | ⬜ | | test-report.md（T1-T6） |
