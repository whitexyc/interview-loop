# ADR-0022 上下文工程：预算观测 + 历史压缩（视图模式）

> 状态：**已采纳（真实裁定：clearing 不引入 / clearing+compaction 引入-灰度默认关，module-093）**
> 提出：2026-09-11 | 关联：plan.md / acceptance-criteria.md（module-093）
> 红线守约：rag/ 与 092 封板资产（eval/langgraph_parity.py、parity_telemetry.py、
> parity_io.py、parity_events.py）零 diff；main.py 零 diff；config 仅纯增量三字段。

## 1. 背景与问题

既有上下文工程只做了三层记忆（Write 块），Compress 与预算治理空白（09-11 盘点）。
长多轮深挖对话下，发给 LLM 的上下文随轮次无界累积，带来：

1. **成本/延迟无界增长**：history 桶 token 随轮次线性膨胀，无观测、无上限。
2. **质量退化风险**：超长上下文淹没关键信息（lost-in-the-middle），且旧工具结果
   占位冗长。
3. **不可恢复焦虑**：直接原地裁剪会破坏 OpenAI tool_call_id 引用链（请求 400）且
   丢失可回溯原文。

## 2. 决策

引入两份能力，落地于 `agent/ctx_manager.py` 纯函数集，两环路（手写 react_loop /
langgraph_react_loop）各自在调 LLM 前调用同一函数（D4 公平）：

- **WP-A 预算观测（默认开，零行为变化）**：`estimate_tokens`（启发式，宁可高估）
  + `classify_context`（五桶 system/tools/user/assistant/tool_results）+ `observe_context`
  （每轮 `record_span("ctx_budget","observe")`）。默认开，只读，存量行为逐字不变。
- **WP-B 历史压缩（默认关）**：`compress_view` 编排——估算 → 超 `ctx_token_threshold`
  则先 `clear_tool_results`（旧 tool 结果换占位符，role/tool_call_id/顺序逐字不变，可
  `tool_call_logs` 回溯）→ 仍超则 `compact_history`（原子折叠中部轮次块为单条摘要
  user 消息）→ 返回**视图副本**，react_loop 本地 messages 保持完整（D1）。

配置（src/config.py 纯增量三字段）：
`ctx_compress_enabled=False`（默认关）/ `ctx_token_threshold=24000` /
`ctx_keep_recent=6`。

## 3. 设计决策（事前定死）

| # | 决策 | 理由 |
|---|------|------|
| D1 | 压缩用"视图"不原地改 | 原始上下文零丢失（可恢复）；对拍公平（三臂同源）；tool_call_id 不被破坏 |
| D2 | clearing 在前，compaction 在后 | clearing 零推理成本、机械替换、可重取，最安全；compaction 有损只做兜底 |
| D3 | compaction 折叠必须整块 | assistant(含 tool_calls)+配对 tools 原子单元；破坏配对=请求 400（AC-10 单测锁定） |
| D4 | 两环路共用 ctx_manager 同一函数集 | 对拍公平：三臂差异只来自 ctx_mode，不来自实现分叉 |
| D5 | 行为开关默认 false，观测默认开 | 存量测试逐字不变 → 全量回归零破坏（基线 1849/0/0/3 零新增失败已确认） |
| D6 | 摘要 v1 规则式（不引入 LLM 摘要） | 避免额外推理成本与不确定；保真局限如实写入报告（见 §5） |

## 4. 三臂对拍裁定（判据**跑批前定死**，结果不利照实写）

脚本：`eval/ctx_tasks.py` 3 个固定剧本（线程池 / RAG / MySQL 索引）× 18 轮连续
追问，入 git 可复现；每轮 `answer_points` 复用 066 `outcome_pass` 要点子串口径。

三臂（臂间唯一差异 = ctx_mode，D4）：
- `off`：ctx_compress_enabled=False（无压缩）
- `clearing`：enabled=True，仅 clearing（compaction 经 `compress_view(compact=False)`
  关闭，不引入新配置项，红线 config 三字段）
- `clearing_compaction`：enabled=True，clearing+compaction（生产默认路径）

判据（任一不满足 → 该臂"不引入"；② 满足且 ①③ 满足 → 建议默认开启）：
- **① 质量**：压缩臂 pass^1 ≥ off 臂 − 0.10（允许小幅损失）
- **② 收益**：压缩臂 history 桶 est_tokens 总量 < off 臂 × 0.70
- **③ 成本**：压缩臂 LLM 次数 ≤ off 臂 × 1.15（压缩不得引发更多重试）

## 5. 真实对拍结果（回填）

> 真实跑批：`PW_LLM_PROVIDER=opencode`，3 剧本 × 3 臂全量，单供应商三臂同批
> （公平性）。结果逐值见 `specs/module-093-context-engineering/ctx-report.md`。

| 臂 | pass_1 | history tokens 总量 | LLM 次数 | ① | ② | ③ | 裁定 |
|----|--------|---------------------|----------|----|----|----|------|
| off | 0.5614 | 628,892 | 121 | — | — | — | 基线 |
| clearing | 0.5439 | 826,136 | 117 | OK | **FAIL** | OK | 不引入 |
| clearing_compaction | 0.4737 | 436,213 | 134 | OK | OK | OK | 建议引入（默认开，质量边缘） |

判据门槛（off 基线）：① off−0.10=0.4614；② off×0.70=440,224；③ off×1.15=139.15。
来源：`agent_eval_runs` id=39/40/41，`fixture=False`，`git_commit=4fcfd54d`，42.3 min
真实跑批（逐值见 `ctx-report.md` §7）。

### 5.1 最终裁定

- **clearing 单独：不引入。** 判据 ② FAIL——history tokens 826,136 > off×0.70
  （440,224），且**反升 31.6%**；①/③ 虽过，但收益判据是引入前提，故否决。反升机理
  见 `ctx-report.md` §8：clearing 清空工具结果致模型失锚、每轮视图复利膨胀，非
  re-invoke 循环（tool_call_logs 方向证据相反，且 trace 归因受首跑死锁干扰不可证）。
- **clearing+compaction：建议引入（默认开），但质量边缘、谨慎默认开。**
  三判据全过，history 降 30.6%（436,213 < 440,224，裕度仅 0.91%）+ LLM 次数受控
  （134 ≤ 139.15）。**质量仅距红线 0.0123**（0.4737 vs 0.4614），且退化集中于 RAG
  深潜（G2 0.2632）——单批次供应商波动即可击穿判据 ①。
- **是否建议默认开启（明确结论）：建议「引入但默认关 / 灰度开启」，而非无保留默认开。**
  理由：① 质量裕度极薄（0.0123），违反"默认开需留安全垫"的稳健预期；② 收益裕度
  亦薄（0.91%）。推荐路径：clearing+compaction 作为可选压缩档位落地，默认
  `ctx_compress_enabled=False`（保持零行为变化红线），经生产长多轮观测确认收益稳定、
  且 RAG 深潜质量退化解后再行默认开。本 ADR 状态据此更新为**已采纳（真实裁定：
  clearing 不引入 / clearing+compaction 引入-灰度，非默认开）**。

**规则式摘要保真局限（D6 诚实标注）**：`_summarize_rounds` 取每轮 user[:80] +
assistant[:120] 拼接，对"短轮次密集"对话可能引入摘要开销（fixture 小样本下
compaction 桶 token 不降反略升），仅对"长答案轮次"有效降本；有损，不保证要点
完整——真实质量损失由判据 ① 兜底，且本次 compaction 臂已逼近 ① 红线，印证该局限。

## 6. 影响与回滚

- 新增文件：`agent/ctx_manager.py`（≤200 AST）、`eval/ctx_tasks.py`、
  `eval/ctx_parity.py`（两文件合计 ≤350 AST，plan §5 预申请）。
- 改动：`agent/react.py`、`agent/langgraph_react.py` 各 ≤20 行接入；`src/config.py`
  纯增量三字段。
- 回滚：将 `ctx_compress_enabled` 置 False（默认即 False）即零行为变化；观测 span
  默认开但只读，可经 `trace_spans_enabled` 静音。
- 落库：`agent_eval_runs` 新增 `config_snapshot->>'module'='093'` + `ctx_mode` 三值
  （复用 066 基建，零新表）。
