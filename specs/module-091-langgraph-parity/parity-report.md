# Module-091 对比报告 — LangGraph 复刻实验 → 转正对比（阶段 E）

> Developer: 2026-09-07 | 依据：`plan.md` §4 转正判据（事前定死）+ `acceptance-criteria.md` AC-18/19/20/22
> 数据来源：本文所有数字均为真实运行输出（命令见 §6），无估算值。

## 1. 结论（先行，二选一）

## **维持自研**（不建议转正 LangGraph 版本至主路径）

判据逐条实测（plan §4 事前定死，全满足才转正）：

| # | 判据 | 实测 | 判定 |
|---|------|------|------|
| ① | WP-A 等价率 = 100% | **100.0%（36/36）** | ✅ 通过 |
| ② | LangGraph pass^1 ≥ 手写 − 0.05 | 0.5833 ≥ 0.4167 − 0.05 = 0.3667（LangGraph 反高出 +0.1667） | ✅ 通过 |
| ③ | LangGraph tokens 与 P95 ≤ 手写 × 1.20 | tokens：138700 ≤ 172600.8 ✅（实测 ×0.964）；**P95：124427.5 > 121985.4（实测 ×1.224，超阈值 2.4%）** | ❌ **不通过** |

**判据③ 的 P95 项不达标 → 按事前规则建议维持自研。** 差在哪：LangGraph 版延迟 P95 为手写版 ×1.224（单次采样），P50 也高 16.3%（56922 vs 48942 ms）——StateGraph 节点调度开销是合理怀疑方向，但本轮样本量（12×2）不足以归因定论（诚实边界见 §5）。

**必须如实写的对自研不利事实（AC-22）**：真实模式下 **LangGraph 质量全面占优**——pass^1 高 16.7 个百分点（0.5833 vs 0.4167）、工具正确率高 16.7 个百分点（0.75 vs 0.5833）、Grounding 高 6.1 个百分点（0.8636 vs 0.8030）、tokens 总量低 3.6%（138700 vs 143834）。若放宽延迟阈值或做多次采样消抖，结论可能反转——这是"维持自研"结论的置信边界，不是"LangGraph 更差"的证明。

## 2. WP-A 等价性证据（fixture，零 LLM 零 DB，确定性）

- 命令：`python -m eval.langgraph_parity --mode fixture`（fixture 模式强制全量 36 条，忽略 --sample）
- 结果：**等价率 1.0000（36/36），不一致条目：无**（AC-1/2/3/4/5）
- 四维逐条比对全部逐字一致：工具名序列 `actual_names` / `tool_count` / 最终 `answer` / 判定器四规则（coverage/no_extra/args_ok/pass）

| 任务组 | 条数 | 两侧序列（一致） | 判定 |
|--------|------|------------------|------|
| at-001~017 单轮知识 | 17 | `[search_knowledge, generate_answer]` | 等价 |
| at-101~107 多轮 | 7 | 每轮 `[search_knowledge, generate_answer]` | 等价 |
| at-201/202 casual + at-301~303 realtime | 6 | `[]`（直答） | 等价 |
| at-401~403 重检 | 3 | `[search_knowledge, re_search, generate_answer]` | 等价 |
| at-501~503 记忆 | 3 | `[recall_memory, search_knowledge, generate_answer]` | 等价 |

覆盖 6 类路径 × 4 维（AC-2~5），判定确定性（AC-10：无 LLM-as-judge，答案=answer_points 确定性拼接）。

**实现要点（plan §0 事实 7）**：手写侧 mock `agent.react.LLMFactory.get_client`、LangGraph 侧 mock `agent.langgraph_react.LLMFactory.get_client`，两个 patch 目标字符串在单测逐字断言（AC-6）。**诚实更正**：两字符串解析到**同一个** `llm.client.LLMFactory` 类对象（两个模块都是 `from llm.client import LLMFactory`），因此任一 patch 点实际都替换同一类属性——"不同源"是字符串层面的，不是对象层面的。单测仍按字符串分别断言（防未来某模块改为本地工厂），功能上无混用风险（两侧串行各自 patch）。

## 3. WP-B 真实模式对比（同子集、同 pass_k、交替执行）

### 3.1 环境与样本（AC-18）

- git commit：`45f7cb959d33c291bff8758d3305b8730dd8e9ba`（HEAD 45f7cb9）
- langgraph：**0.4.5** | Python 3.11 | LLM：ModelScope `Qwen/Qwen3.5-35B-A3B`（供应商偏离见 §7）
- 样本：`--sample 12`（random.Random(42) 固定种子抽样，可复现），实际 12 条：at-002/003/004/005/008/015/016/101/105/107/303/501，覆盖单轮/多轮/realtime/记忆 4 类路径
- 交替执行（AC-7/T4）：逐任务 hand→langgraph 交替，运行日志时间戳可证（16:12:33 hand → 16:13:12 langgraph → 16:14:33 hand → …）
- 诚实口径：**单次采样，非置信区间**；供应商限流/网络抖动影响延迟，交替执行摊平但不能消除

### 3.2 三层指标对比表（AC-8）

| 指标 | hand（手写） | langgraph | 差异 |
|------|------------|-----------|------|
| **Outcome** pass^1 | 0.4167（5/12） | **0.5833（7/12）** | LangGraph +0.1667 |
| **Trajectory** 工具正确率 | 0.5833 | **0.7500** | LangGraph +0.1667 |
| Grounding（result_ok 比例） | 0.8030 | **0.8636** | LangGraph +0.0606 |
| 平均工具步数 | 2.83 | 2.92 | LangGraph +0.09 |
| **System** tokens 总量 | 143834 | **138700** | LangGraph −3.6% |
| 平均 token/任务 | 11986.2 | 11558.3 | LangGraph −3.6% |
| P50 ms | **48942.0** | 56922.0 | LangGraph +16.3% |
| **P95 ms** | **101654.5** | 124427.5 | **LangGraph +22.4%（判据③不达标项）** |

### 3.3 逐任务明细（12 条 × 2 环路）

| 任务 | hand 工具序列 | hand pass | langgraph 工具序列 | lg pass |
|------|--------------|-----------|--------------------|---------|
| at-002 | sk,ga,sk | ✅ | sk,ga | ✅ |
| at-003 | sk,ga,re_search | ❌ | sk,sk,ga | ❌ |
| at-004 | sk,sk,re_search | ❌ | sk,sk,re_search | ❌ |
| at-005 | sk,sk,search_fts | ❌ | sk,sk,re_search | ❌ |
| at-008 | sk,ga | ✅ | sk,ga,ga | ✅ |
| at-015 | sk,ga | ✅ | sk,ga | ✅ |
| at-016 | sk,ga,ga | ✅ | sk,ga,ga | ✅ |
| at-101 | sk,ga | ✅ | sk,ga,ga | ✅ |
| at-105 | sk,re_search,sk,sk,re_search,sk | ❌ | sk,sk,ga,sk,sk,ga | ✅ |
| at-107 | sk,sk,search_fts,sk,re_search,sk | ❌ | sk,re_search,sk,sk,re_search,ga | ✅ |
| at-303 | [] | ❌ | [] | ❌ |
| at-501 | [recall_memory] | ❌ | [recall_memory] | ❌ |

（sk=search_knowledge，ga=generate_answer）

- 失败案例分类（不隐藏）：两侧失败主因均为**答案缺要点**与**工具选错/多调**（Qwen 3.5-35B 在本任务集上路径方差大：重复检索、提前生成）；at-303（realtime 拒答）与 at-501（记忆任务只调 recall_memory）两侧同败，系模型行为非环路差异
- **运行期异常：0 条**（24 次单边运行无 fail_reason，AC-12 无需豁免，也无静默重跑）
- 落库（AC-9，T1 对账）：`agent_eval_runs` id=**4**（loop=hand）/ id=**5**（loop=langgraph），`config_snapshot->>'module'` = "091"，git_commit 均为运行时 HEAD 45f7cb95，零新表零 ALTER

## 4. 判据复核与结论推导

1. **等价性（判据①）**：fixture 下 36/36 逐字等价 → "复刻"在确定性口径下成立。注意这证明的是**结构等价**（相同 LLM 决策 → 相同行为），真实模式下 LLM 自主决策本身有方差，两侧轨迹不同属预期（066 已证）。
2. **质量（判据②）**：LangGraph pass^1 显著更优。**单样本 +0.1667 也不具统计显著性**（12 条任务，翻转 2 条即抹平），但至少证明 LangGraph 版**没有质量劣化**——这排除了"实验分支失修"风险（plan §6 风险 2）。
3. **成本/延迟（判据③）**：tokens 达标（×0.964），**P95 超标（×1.224）**。P50 也 +16.3%，方向一致，不像纯尾部噪声——StateGraph 每轮 ainvoke 的图调度开销是合理怀疑，但未做归因实验（非本模块范围）。

**结论：维持自研。** 判据①②过、③的 P95 项实测 ×1.224 > ×1.20。同时明确记录：LangGraph 版质量指标全面占优、tokens 更省，若后续（a）多次采样消抖复测延迟、（b）或放宽延迟阈值的决策被接受，转正议题可重启——数据基础（本报告 + agent_eval_runs id=4/5）已就绪。

## 5. 诚实边界

1. pass^1/tokens/P95 均为**单次采样**（12 任务 × 1 次 × 2 环路），非置信区间；延迟受供应商时段抖动影响，交替执行只摊平不消除
2. 本轮 LLM 为 ModelScope Qwen/Qwen3.5-35B-A3B（主配置 deepseek 401 失效，见 §7）——指标绝对值与生产配置不可直接外推，但两侧同模型对比的**相对结论**有效
3. 等价性是 fixture 口径（假 LLM 回放计划），证明结构等价；真实 LLM 自主决策的方差两侧共用
4. P95 超标未做根因归因（图调度开销 vs 模型方差），"维持自研"不依赖归因结论
5. 成本口径：tokens 不分桶不换算金额（085/089 先例）

## 6. 可复现命令（AC-18）

```bash
cd interview-personal/ai_service

# WP-A 等价性（零 LLM/DB，秒级）
.venv/Scripts/python.exe -m eval.langgraph_parity --mode fixture
# → 等价率: 1.0000  (36/36)，不一致条目：无

# WP-B 真实对比（抽样 12，交替执行，两次落库）
PW_LLM_PROVIDER=qwen .venv/Scripts/python.exe -m eval.langgraph_parity --mode real --sample 12 --pass-k 1
# → agent_eval_runs id=4 (hand) / id=5 (langgraph)

# 单测（15 项）
.venv/Scripts/python.exe -m pytest tests/eval/test_langgraph_parity.py -q
```

配置快照：`agent_eval_runs.config_snapshot`（rag_config + `{"loop","module"}`），库内可查。

## 7. 偏离 plan 项（如实申报，详见 changelog §五）

1. **LLM 供应商**：`.env` 主配置 deepseek key 401 失效；fallback 链 qwen/zhipu/deepseek 均不可用（modelscope 端点上 DeepSeek-V4-Pro 非 stream 带 tools 返回空 choices、GLM-5.2 同）。改用 `PW_LLM_PROVIDER=qwen`（Qwen3.5-35B-A3B，实测工具调用可用）——环境变量级切换，零代码改动
2. **fixture 默认全量**：`--sample` 默认 12 但 fixture 模式强制全量 36（AC-1 要求），real 模式默认 12
3. **mock 点"不同源"更正**：两个 patch 字符串解析到同一 LLMFactory 类对象（§2）
