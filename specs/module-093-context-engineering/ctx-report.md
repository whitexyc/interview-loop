# module-093 上下文工程 — 对拍报告（ctx-report）

> Developer: developer-093 | 2026-09-11 | 关联 plan.md / acceptance-criteria.md / ADR-0022 / changelog.md
> 三判据（质量 −0.10 / tokens ×0.70 / LLM ×1.15）**跑批前写入 ADR-0022 §4**，
> 本报告的真实逐值照实回填，不利结论不弱化（AC-21 / AC-22）。

## 1. 概述

module-093 在 Vibe Coding 四阶段闭环中实现上下文工程三件套：

- **WP-A 预算观测**（默认开，零行为变化）：`agent/ctx_manager.py` 的
  `estimate_tokens` / `classify_context`（五桶）/ `observe_context`（每轮
  `ctx_budget` span）。
- **WP-B 历史压缩**（默认关）：`compress_view` 编排——超 `ctx_token_threshold`
  则先 `clear_tool_results`（旧 tool 结果换占位符，可 `tool_call_logs` 回溯）
  再 `compact_history`（原子折叠中部轮次块为单条摘要），返回**视图副本**，
  react_loop 本地 messages 保持完整（D1）。
- **WP-C 三臂对拍**：`eval/ctx_tasks.py`（3 固定剧本 × 18 轮）+ `eval/ctx_parity.py`
  （off / clearing / clearing_compaction 三臂，复用 066 outcome_pass + 落库）。

## 2. 方法与判据

- **剧本**：3 个深挖剧本（线程池 / RAG / MySQL 索引），各 1 初始提问 + 18 轮连续
  追问，每轮 `answer_points`（2–3 关键词），入 git 可复现；要点子串命中复用 066
  `outcome_pass` 口径（expected_tools=[] 时退化为纯要点命中）。
- **指标**：① quality = 各臂 pass^1（要点命中率）；② 收益 = 各臂 history 桶
  est_tokens 总量（user+assistant+tool_results，不含 system/tools）；③ 成本 =
  各臂 LLM 调用次数（chat_with_tools 计数，经 `_InstrumentedClient` 插桩采集）。
- **三判据**（任一不满足 → 该臂不引入；② 满足且 ①③ 满足 → 建议默认开启）：
  - ① 质量：压缩臂 pass^1 ≥ off − 0.10
  - ② 收益：压缩臂 history tokens < off × 0.70
  - ③ 成本：压缩臂 LLM 次数 ≤ off × 1.15
- **公平性**：三臂逐臂跑同一剧本集，臂间唯一差异 = ctx_mode（D4）；单供应商
  `PW_LLM_PROVIDER=opencode` 三臂同批；clearing-only 臂经 `compress_view
  (compact=False)` 表达，不引入新配置项（config 三字段红线）。

## 3. AC-2 估算器误差方向（宁可高估，已验证）

`estimate_tokens` 实测对中文低估（plan 建议 1.5 系数 → 触发线偏晚、不安全），
改为 **CJK 0.8 chars/token**（偏离 plan WP-A 系数，申报 changelog）。cl100k_base
抽样 5 条（中英混合）对比：

| # | 文本类型 | est(0.8) | tiktoken | est≥tiktoken | ratio |
|---|---------|----------|----------|--------------|-------|
| 1 | 中文（线程池） | 50 | 41 | ✅ | 1.22 |
| 2 | 中文（RAG） | 59 | 56 | ✅ | 1.05 |
| 3 | 中文（MySQL） | 61 | 59 | ✅ | 1.03 |
| 4 | 英文（线程池） | 36 | 30 | ✅ | 1.20 |
| 5 | 英文（RAG） | 43 | 34 | ✅ | 1.26 |

**结论**：5/5 估算值 ≥ 真实 tiktoken，误差方向安全侧（高估），满足 AC-2。三臂
比较用同比，相对比值与系数无关。

**诚实边界（review-report MID-2 补充）**：上述"高估方向"对**中文/技术中文**成立
（抽样 5/5）；对 **ASCII 密集文本**（代码标识符/数字/术语混排，如
`RAG系统使用bge-m3嵌入模型与RRF融合排序，Hit@5达到0.9905`）实测 est=26 <
tiktoken=32（ratio 0.81，**低估**）——ASCII 段 4 chars/token 对标识符密集文本偏低。
影响：三臂同比结论不受影响（同系数）；但英文/标识符密集场景下压缩触发线可能偏晚。
如需普适高估，后续可对 ASCII 段引入按词密度分段（不在本模块范围）。

## 4. 红线守约（T5 复核）

`git diff --stat` 对以下路径**全空**（零 diff）：

- `ai_service/rag/`（检索主链路持续零改动）
- `ai_service/eval/langgraph_parity.py`、`parity_telemetry.py`、`parity_io.py`、
  `parity_events.py`（092 封板资产）
- `ai_service/main.py`

允许改动：`agent/ctx_manager.py`（新）、`eval/ctx_tasks.py`/`eval/ctx_parity.py`
（新）、`agent/react.py`/`agent/langgraph_react.py`（各 ≤20 行接入）、
`src/config.py`（纯增量三字段）、`tests/`（新）。

## 5. 全量回归与单测

- **全量回归**（junitxml 权威）：tests=1870 / failures=0 / errors=0 / skipped=3
  （基线 1849/0/0/3，零新增失败）。
- **新增单测**：`tests/agent/test_ctx_manager.py`（19 项：估算边界/五桶/占位符/
  块完整性/默认关零行为/视图不改原列表）+ `tests/agent/test_ctx_compress_wiring.py`
  （2 项：两环路 compress_view 为副本、本地 messages 完整、ctx_compress span
  触发）= **21 项全绿**。

## 6. 夹具管线验证（零 LLM/DB，验证机制与落库）

`--mode fixture` 全量（3 剧本 × 3 臂）落库成功（agent_eval_runs id 对应
`config_snapshot->>'module'='093'` + ctx_mode 三值齐全，T1 满足）。观测：

- off == clearing（fixture 无工具调用 → clearing 无可清 tool 结果，符合预期）；
- clearing_compaction 臂 history tokens 低于 off（compaction 折叠生效，机制正确）；
- 三臂 LLM 次数相等（压缩不引发额外重试，③ 结构成立）。
- 小样本下 compaction 桶 token 降幅未达 30%（fixture 答案短、折叠收益有限），
  真实长答案场景降幅更大——见 §8 真实数据。

## 7. 真实对拍结果

> 真实跑批：`PW_LLM_PROVIDER=opencode`，3 剧本 × 3 臂全量，单供应商三臂同批；
> 阈值 `ctx_token_threshold=3000`、`ctx_keep_recent=6`。逐值回填：

| 臂 | pass_1 | history tokens 总量 | LLM 次数 | ① | ② | ③ | 裁定 |
|----|--------|---------------------|----------|----|----|----|------|
| off | 0.5614 | 628,892 | 121 | — | — | — | 基线 |
| clearing | 0.5439 | 826,136 | 117 | OK | **FAIL** | OK | 不引入（②反升 31%） |
| clearing_compaction | 0.4737 | 436,213 | 134 | OK | OK | OK | 建议引入（默认开，质量边缘） |

判据门槛（off 为基线）：① off−0.10 = 0.4614；② off×0.70 = 440,224；③ off×1.15 = 139.15。
三臂均从 `agent_eval_runs` id=39(off)/40(clearing)/41(clearing_compaction)，
`fixture=False`，`git_commit=4fcfd54d`，42.3 min 真实落库复算。

### 7.1 三臂逐剧本明细（pass_1，来自 per_question 按 19 轮/臂切分；整体=57 轮）

| 臂 \ 剧本 | G1 线程池深潜 | G2 RAG 深潜 | G3 MySQL索引深潜 | 整体 |
|-----------|--------------|------------|------------------|------|
| off | 0.6842 (13/19) | 0.4737 (9/19) | 0.5263 (10/19) | 0.5614 (32/57) |
| clearing | 0.6842 (13/19) | 0.3684 (7/19) | 0.5789 (11/19) | 0.5439 (31/57) |
| clearing_compaction | 0.6842 (13/19) | 0.2632 (5/19) | 0.4737 (9/19) | 0.4737 (27/57) |

**观察**：G1 线程池三臂恒稳（0.6842），质量损失集中在 **G2 RAG 深潜**
（off 0.4737 → clearing 0.3684 → compaction 0.2632），与「压缩剥离检索原文后
RAG 答案最易失锚」的机理一致。per-script history tokens / LLM 次数未单列
（token_sink 跨剧本共享，scores 仅存总量）。

**每调用视图 token（history 总量 ÷ LLM 次数，反映单轮发给 LLM 的上下文体量）**：
off ≈ 5,198；clearing ≈ 7,062（**+36%**）；clearing_compaction ≈ 3,255（**−37%**）。
clearing 臂 LLM 次数与 off 基本持平（117 vs 121），token 反升来自**每调用视图膨胀**，
而非调用/工具次数增多（见 §8 归因）。

### 7.2 ctx_compress span 触发（request_spans，call 级计数）

`ctx_compress` span 在 `compress_view` 产出被改写的视图时记录（react.py:517，
`compacted or cleared` 任一为真即触发），故 clearing 臂计数=纯 clearing 事件，
clearing_compaction 臂=clear+compact 事件。计数为**调用级**（深挖剧本每轮多 LLM
调用，约 3–4 span/轮），非轮次级；span 不存轮次序数，轮次精确触发点不可从 span 还原。

| 臂 \ 剧本 | G1 | G2 | G3 |
|-----------|----|----|----|
| clearing | 74 | 45 | 56 |
| clearing_compaction | 82 | 54 | 54 |

触发频率高且贯穿各剧本，说明压缩在长多轮深潜中持续生效；阈值 `ctx_token_threshold=3000`
与两臂触发一致（clearing_compaction 因 compaction 折叠后视图回缩，触发数略高于纯 clearing）。

> 注：上述 span / tool_call_logs 的 `ctx-*` trace 行**不含 run_id**，与第一次被
> stdout 死锁终止的真实跑批、以及 fixture 验证行（id=36/37/38，同 `ctx-{arm}-{剧本}`
> 前缀）共用同一 trace 命名空间；评测 trace 清理归 Tester T6。故 §7.2 / §8 的
> ctx-* 计数**不能逐行归属到 id=39/40/41**，仅作量级与方向参考。

### 7.3 失败任务（来自 per_question，pass=False）

per_question 存 `{q, answer_points, answer[:300], pass}`，失败=要点子串未命中
（答案已产出但未覆盖 2–3 个关键词之一），无独立 fail_reason 字段。各臂失败轮数：

- off：25/57（G1 6 / G2 10 / G3 9）
- clearing：26/57（G1 6 / G2 12 / G3 8）
- clearing_compaction：**30/57（G1 6 / G2 14 / G3 10）**——失败集中于 G2 RAG 深潜。

失败非异常中断（answer 非空），均为要点命中不足；与 §7.1 G2 退化一致。

## 8. 诚实记录（AC-22）

- **规则式摘要保真局限（D6）**：`_summarize_rounds` 取每轮 user[:80] +
  assistant[:120] 拼接，对"短轮次密集"对话可能引入摘要开销（fixture 小样本
  下 compaction 桶不降反略升），仅对"长答案轮次"有效降本；有损，不保证要点
  完整——质量损失由判据 ① 兜底。
- **估算系数偏离**：CJK 1.5 → 0.8（AC-2 要求宁可高估，已抽样验证），申报于
  changelog「已知局限」。
- **clearing 臂 tokens 反升 31% 归因（如实，未坐实 re-invoke 假设）**：
  - 真实数据：clearing history=826,136 vs off=628,892（**+31.6%**），
    但 clearing LLM 次数=117 ≈ off=121（调用数未增）。每调用视图 token：
    clearing ≈ 7,062 vs off ≈ 5,198（**+36%**）——token 反升来自**单轮视图膨胀**，
    非调用/工具次数增多。
  - 用 `tool_call_logs` 抽证 re-invoke 假设：原始 ctx-* trace 计数
    off=169 / clearing=60 / clearing_compaction=77（三剧本合计）。**该计数不能验证
    re-invoke 假设**——原因有二：(a) trace_id 不含 run_id，与第一次被 stdout 死锁
    终止的真实跑批、fixture 验证行（id=36/37/38）共用 `ctx-{arm}-{剧本}` 前缀，
    off 臂 169 很可能混入被终止首跑的孤儿 trace，无法作为干净基线；(b) 即便取原始数，
    clearing(60) < off(169) 方向也**反而否定**"占位符诱发 re-invoke 工具→重取→
    再进 history"的假设。结论：re-invoke 循环假设**未经证实，且方向证据相反**。
  - 更成立的机理（与干净数据一致）：clearing 仅清空工具结果、保留 tool_call 调用，
    模型失去检索/工具原文锚点 → 每轮以更长自然语言重写/复述上下文 → 该更长 assistant
    消息进入 history 后**逐轮复利放大**后续视图。佐证：质量退化集中于 G2 RAG 深潜
    （依赖被剥离的检索原文，off 0.4737 → clearing 0.3684 → compaction 0.2632），
    而 G1 线程池三臂恒稳（0.6842，不依赖工具原文）。**该机理为基于干净分数+剧本
    退化的推论，标记 hypothesis，非 span 直接证实**（ctx-* span 属 T6 清理范畴）。
- **clearing_compaction 质量仅距红线 0.012（如实标注）**：pass_1=0.4737，判据 ①
  门槛 off−0.10=0.4614 → 仅余 **0.0123** 裕度；判据 ② 门槛 off×0.70=440,224，
  本臂 436,213 → 仅低 **4,011 token（0.91%）**，裕度极薄。两项均"过线但未留安全垫"，
  「建议引入（默认开）」须附**质量边缘警示**：单批次供应商波动即可击穿判据 ①。
- **失败任务**：各臂失败轮数见 §7.3（per_question 仅存 pass/answer[:300]/answer_points，
  无独立 fail_reason 字段）；失败均为要点子串未命中、非中断，集中于 G2 RAG 深潜，
  与压缩剥离检索原文机理一致，不隐藏。
- **第一次真实跑批被终止（环境坑，非代码）**：首跑因 stdout 死锁被编排者终止重跑；
  非本模块代码缺陷，已在 §7.2/§8 注明其孤儿 trace 对计数归因的干扰。
- **供应商批次波动**：同 092 教训，单批次结论如实标注；本实验三臂同批次同供应商
  （opencode），臂间差异仅来自 ctx_mode，可归因。
