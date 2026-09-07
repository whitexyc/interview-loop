# 验收标准 — Module-091: LangGraph 复刻实验 → 转正对比报告

> Planner: 2026-09-07 | 配套：`plan.md` | 判定原则：**确定性判定，不用 LLM 评 LLM**（ADR-0017 / module-066 先例）
> 红线：`agent/` `src/` `main.py` **零 diff**；存量基线 1754/0/3 零新增失败

## 1. 功能验收

| # | 验收项 | 判据（可机械断言） |
|---|--------|--------------------|
| AC-1 | 等价性夹具跑通 | `eval/langgraph_parity.py` 对 36 条任务全部产出比对结果，无异常跳过 |
| AC-2 | 工具序列等价 | 每条任务两侧 `actual_names` **逐字相同**，等价率 = 100.0%（不一致须逐条列出 id + 两侧序列 + 归因） |
| AC-3 | 工具次数等价 | 每条 `tool_count` 一致 |
| AC-4 | 答案等价 | 每条最终 `answer` 一致（fixture 答案确定性） |
| AC-5 | 判定器四规则等价 | `coverage` / `no_extra` / `args_ok` / `pass` 四字段两侧一致 |
| AC-6 | 双 mock 点正确 | 手写侧 patch `agent.react.LLMFactory`；LangGraph 侧 patch `agent.langgraph_react.LLMFactory`；不得混用（单测断言 patch 目标字符串） |
| AC-7 | real 分支双跑 | 同一 `--sample` 子集下两条环路各跑一次，交替执行（hand, langgraph, hand…） |
| AC-8 | 三层指标齐全 | 每次运行 scores 含 `pass^1`/`pass^3`、工具正确率、tokens、步数、P50/P95，无 None 字段（除如实标注项） |
| AC-9 | 落库双 run | `agent_eval_runs` 新增两行，`config_snapshot.loop` ∈ {hand, langgraph}，`git_commit` = 运行时 HEAD |
| AC-10 | 判定确定性 | 全流程不出现"用 LLM 判断答案好坏"；Outcome 仅用 `answer_points` 关键词命中 |
| AC-11 | 采样与全量可切换 | `--sample N` 生效；报告标注本轮实际样本量与抽样方式 |
| AC-12 | 失败不掩盖 | 任一条任务运行时异常 → 记入 `fail_reason` 并在报告中列出，禁止静默重跑 |

## 2. 非功能验收

| # | 验收项 | 判据 |
|---|--------|------|
| AC-13 | 生产代码零改动 | `git diff --stat` 对 `ai_service/agent/`、`ai_service/src/`、`ai_service/main.py` 全空 |
| AC-14 | 代码量 | 新增生产侧 AST ≤ 200（预估 ~95，实测复算） |
| AC-15 | 方法/类规模 | 方法 ≤50 行、类 ≤500 行 |
| AC-16 | 文档字符串 | 新增 public 函数全部有 Docstring（Args/Returns） |
| AC-17 | 无裸异常 | 无空 `except`；确定性脚本 I/O 容错 catch 须带注释（铁律 5 豁免口径） |
| AC-18 | 报告可复现 | `parity-report.md` 含：运行命令、git commit、模型/环境版本、样本量、配置快照 |

## 3. 结论验收（本模块的灵魂）

| # | 验收项 | 判据 |
|---|--------|------|
| AC-19 | 转正判据事前定死且被执行 | 报告明确给出三条判据的逐条实测值：①等价率 100% ②`pass^1` 差 ≥ -0.05 ③tokens 与 P95 ≤ 1.20× |
| AC-20 | 结论明确 | 产出二选一的明确结论（建议转正 / 维持自研），**不得给"各有优劣"式模糊结论** |
| AC-21 | ADR-0020 落盘 | `specs/adr/0020-langgraph-parity.md` 存在，含决策、判据、实测数据、被否决方案的理由 |
| AC-22 | 不利结论如实写 | 若 LangGraph 优于自研，报告照实写（Reviewer 核查是否回避） |

## 4. Tester 对账（T1–T6，真实 PG，禁 mock 充数）

| # | 对账项 | 方法 |
|---|--------|------|
| T1 | 双 run 真实落库 | `SELECT id, config_snapshot->>'loop', git_commit FROM agent_eval_runs ORDER BY id DESC LIMIT 2` 两行且 loop 值互异 |
| T2 | 等价性 36/36 | 重跑 WP-A，等价率输出 100.0%，与报告数值逐字一致 |
| T3 | 指标可对账 | 报告中的 pass^1 / 工具正确率 / tokens / P95 能在库内 per_question 中独立复算一致 |
| T4 | 交替执行生效 | per_question 顺序或日志显示 hand/langgraph 交替（非先整段后整段） |
| T5 | 红线零 diff | `git diff` 对 agent/src/main.py 全空 |
| T6 | 清理还原 | 评测产生的 eval-* trace 行 / 临时数据按 066 先例清理，基线行数回退（如实记录删除行数） |

## 5. 可运行验证命令表

```bash
cd interview-personal/ai_service

# WP-A 等价性（零 LLM，秒级）
python -m eval.langgraph_parity --mode fixture

# WP-B 真实对比（抽样 12 条，交替执行）
python -m eval.langgraph_parity --mode real --sample 12 --pass-k 1

# 单测
python -m pytest tests/eval/test_langgraph_parity.py -q

# 全量回归（基线 1754 + 新增，零新增失败）
python -m pytest tests/ -q
```

## 6. 验收结论签署区

| 角色 | 结论 | 日期 | 备注 |
|------|------|------|------|
| Developer | ⬜ | | changelog.md |
| Reviewer | ⬜ | | review-report.md，附 文件:行号 证据 |
| Tester | ⬜ | | test-report.md，含 T1–T6 真实对账输出 |
