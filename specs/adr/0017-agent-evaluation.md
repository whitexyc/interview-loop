# ADR-0017：Agent 级评估体系（工具调用正确率 / 任务完成率 / 成本控制）

## 元信息

- 状态：✅ **已实施 module-066**（2026-08-17；执行简报 `specs/module-066-agent-evaluation/task-brief.md`；changelog `specs/module-066-agent-evaluation/changelog.md`）
- 日期：2026-08-17
- 关联：module-058（可观测性 request_logs）、agent/react.py（ReAct 循环）、eval/（golden/benchmarks）、ADR-0016（RAG 架构定位）、module-063（多轮意图路由）

## 背景：现状缺口（代码实测）

现有评估体系覆盖**检索质量**（golden 112 题 + eval_runs 版本化回归 + 消融），但**不覆盖 Agent 行为**：

1. **request_logs 只记阶段耗时**（timings JSONB：意图/分诊/检索 FTS·向量·图谱/rerank/反思/生成/幻觉检测）与 token 用量（usage JSONB），**没有工具调用明细**——调了哪个工具、参数、结果、耗时、成败，全都没落库
2. **eval 目录**（golden/benchmarks/train）全是检索/模型层面的评测，无"任务级"评测
3. react.py 的 ReAct 循环有 budget（max_agent_tools=4）与工具执行逻辑，但**正确性无人判定**——"该调的调了没、不该调的调了没、多走了几步、花了多少钱"无法回答

**一句话**：检索质量有评测闭环，Agent 行为没有——这是"Agent 不可靠是最大障碍"（LangChain 2026 调查 32% 团队）直接对应的缺口。

## 业界对标（2026 调研）

| 方案 | 做法 | 对本项目的启示 |
|---|---|---|
| **τ-bench**（Sierra） | 模拟用户 + 领域工具 API + policy 约束，最终数据库状态判定成败；**pass^k**（k 次独立尝试全成功才算对）衡量可靠性 | 模拟用户成本高，但"状态判定"与 pass^k 思想可借鉴 |
| **AgentBench**（清华） | 八环境（OS/DB/KG/网页等），Success Rate + Progress Rate + Grounding Accuracy | Grounding Accuracy（工具调用不报错比例）直接可用 |
| **freeacademy 2026 三层测量** | **Outcome**（任务完成率）+ **Trajectory**（步级正确性、效率）+ **System**（延迟/成本/步数） | ⭐ 本项目的主框架——三层全要 |
| **step-level correctness** | 每次工具调用判"工具选对没、参数对不对" | 90% 任务完成率可能隐藏"平均重试 3 次"的浪费 |
| **Grounding Accuracy** | 工具调用成功执行（无报错）的比例 | 与 verify_results/降级链天然衔接 |

**业界共识**：只测 outcome 会"成功靠蛮力"，只测 trajectory 会"优雅轨迹但用户失败"——三层缺一不可；**生产可靠性看 pass^k 不看 pass@1**。

## 决策 1：三层指标（对齐业界三层测量）

| 层 | 指标 | 定义 | 数据来源 |
|---|---|---|---|
| **Outcome** | 任务完成率 pass^1 / pass^3 | 任务目标达成（判定器确认）；pass^3 = 3 次独立尝试全成功 | 新 `agent_eval_runs` 表 |
| **Trajectory** | 工具调用正确率 | 期望工具集匹配：该调的调了、没多调、参数类型对（不判值） | 新 `tool_call_logs` 表 |
| **System** | 成本与步数 | 每任务 token 用量、工具调用步数、端到端耗时（P50/P95） | request_logs + tool_call_logs |

**判定方式**：任务成败用**确定性判定**（期望文档命中/期望工具序列匹配/答案要点包含），**不用 LLM-as-judge 自动打分**——与项目"确定性优先"哲学一致（NLI kappa 未达标教训），judge 主观性会污染评测。

## 决策 2：工具调用明细落库（最大改动点）

新表 `tool_call_logs`（对齐 request_logs 的 init_db 幂等 DDL 模式）：

```sql
CREATE TABLE IF NOT EXISTS tool_call_logs (
    id           BIGSERIAL    PRIMARY KEY,
    trace_id     VARCHAR(64)  NOT NULL,
    tool_name    VARCHAR(64)  NOT NULL,
    args         JSONB        NOT NULL DEFAULT '{}',
    result_ok    BOOLEAN      NOT NULL DEFAULT TRUE,
    result_preview VARCHAR(200) NOT NULL DEFAULT '',  -- 截断，防大文档撑爆
    duration_ms  INTEGER      NOT NULL DEFAULT 0,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

写入点：react.py 执行工具处（budget 截断逻辑旁），每条实际执行的 tool_call 一行；不记录 LLM 提出但被预算截断的调用（无对应结果）。**默认开关 `PW_TOOL_CALL_LOGS`（true），与 request_logs 同生命周期**。

## 决策 3：任务级评测集（不引入模拟用户）

τ-bench 的 simulated user 成本高（双模型），本项目采用**轻量任务集**：

- 新建 `agent_tasks.json`（30-50 条），每条含：任务描述（用户问题，可含多轮追问）、期望工具序列（如 `["search_knowledge", "generate_answer"]`）、期望答案要点（1-3 个关键词/实体）
- 来源：golden 112 题中挑多轮/复杂题改写 + 手工构造（含边界：casual_chat 直答、realtime 拒绝、检索不足重检路径）
- 跑法：`python -m eval.agent_tasks --mode chat|agent`，结果落 `agent_eval_runs` 表（git_commit + 配置快照，复用 eval_runs 模式）
- 指标输出：pass^1 / pass^3（抽样 10 条跑 3 次）、工具调用正确率、平均步数、平均 token、P50/P95

**通过标准（首次跑）**：pass^1 ≥ 0.8（多轮 agent 路径 ≥ 0.7）；工具调用正确率 ≥ 0.9；平均步数 ≤ 6；无工具调用报错（Grounding = 1.0，降级链兜底不算错）。

## 决策 4：工具调用正确率判定规则（确定性）

对每条任务，对比实际 tool_calls 序列与期望序列：

1. **覆盖**：期望中的每个工具都被调用了（顺序可放宽，最后一轮前调用即算）
2. **无多调**：实际调用的工具都在期望集合内（或明确豁免：re_search 双组设计允许生成阶段补检）
3. **参数类型**：args 的 key 与 args_schema 必填字段一致（不判值，值语义判不了）
4. **Grounding**：result_ok 比例（工具执行无异常）

**预期坑**：LLM 路径选择有天然方差（可能 search_knowledge 直接命中不再调 search_fts）——所以"覆盖"只要求期望工具都出现，不要求精确顺序；豁免清单写入评测脚本注释。

## 诚实边界（面试防御）

1. 任务集 30-50 条人工构造，**不是模拟用户**——多轮对话的动态性覆盖有限（τ-bench 才做）；这是"轻量版"，演进方向是 τ-bench 式 simulated user
2. pass^3 只抽样 10 条（成本考虑），不是全量 3 次
3. 工具调用正确率不判参数"值"的语义——比如 search_knowledge(query="RRF") 与 query="rff" 语义等价但字符串不同，判不了（需 LLM 判定，不引入）
4. **不预设成功**：首次跑通过标准不达标就如实标注并列出失败案例分类（工具选错/参数错/路径绕），作为下一轮优化输入

## 面试话术

> "我的项目有检索质量评测闭环（112 题 golden + 版本化回归），但 Agent 行为是盲区——request_logs 只记了阶段耗时，没记工具调用明细。所以我补了 Agent 级评估三层：Outcome 任务完成率（pass^1/pass^3，对齐 τ-bench 的可靠性思想，k 次全成功才算对）、Trajectory 工具调用正确率（该调的调了、没多调、参数类型对，确定性判定不用 LLM judge）、System 成本与步数（每任务 token/步数/P50-P95）。实现上新增 tool_call_logs 表（react 循环每次执行落一行），自建 30-50 条任务集（含多轮追问、casual 直答、检索不足重检等路径），复用 eval_runs 版本化回归。我清楚边界：没上 τ-bench 的模拟用户（成本高，双模型），参数值语义不判——这是诚实标注的演进方向。"

## 验收标准

1. `tool_call_logs` 表建表（init_db 幂等）+ react.py 落库生效（E2E 一次 chat 能看到记录）
2. `agent_tasks.json` 30-50 条 + `eval/agent_tasks.py` 跑通，输出 pass^1/pass^3/工具正确率/步数/token/P50-P95
3. 结果落 `agent_eval_runs`（git_commit + 配置快照）
4. 存量 897 测试全绿 + 新增单测（tool_call_logs 落库、评测脚本冒烟）
5. 通过标准不达标 → 输出失败案例分类报告（不隐藏）
