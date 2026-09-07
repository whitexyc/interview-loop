# ADR-0020：LangGraph 复刻实验转正裁定（维持自研）

## 元信息

- 状态：✅ **已裁定：维持自研**（2026-09-07；module-091 阶段 E；对比报告 `specs/module-091-langgraph-parity/parity-report.md`）
- 日期：2026-09-07
- 关联：ADR-0012（工具治理阶段切分）、ADR-0017（Agent 评估体系）、module-030（LangGraph 实验端点 `/ai/rag/chat/agent-lg`）、module-066（评测基建）、`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 E

## 背景

主路径 ReAct 循环为手写 while 循环（`agent/react.py::react_loop`，生产主路径）；module-030 并存了一份 LangGraph StateGraph 复刻（`agent/langgraph_react.py`，4 节点，实验端点）。官方路线图阶段 E 要求：同一评测集下给出「框架 vs 自研」的**可复现结论**（含耗时/成本/成功率），把"参考 LangGraph 自研"从定位声明变成数据结论。

module-091 建立了等价性夹具（fixture 假 LLM 回放，零 LLM 零 DB）+ 真实模式交替对比（同子集同 pass_k，逐任务 hand→langgraph 交替），指标复用 066 三层口径（Outcome/Trajectory/System）。

## 判据（事前定死，防事后找补）

全部满足才建议转正：

1. WP-A 等价率 = 100%（fixture 下工具序列/次数/答案/判定四维逐字一致）
2. LangGraph pass^1 ≥ 手写 pass^1 − 0.05
3. LangGraph tokens 与 P95 均 ≤ 手写 × 1.20

## 实测数据（2026-09-07，commit 45f7cb95，样本 12 条固定种子，单次采样）

| 指标 | hand（手写） | langgraph |
|------|------------|-----------|
| 等价率（fixture 36 条） | — | **100%（36/36）** |
| pass^1 | 0.4167 | **0.5833** |
| 工具正确率 | 0.5833 | **0.7500** |
| Grounding | 0.8030 | **0.8636** |
| tokens 总量 | 143834 | **138700**（×0.964） |
| P50 ms | **48942** | 56922（×1.163） |
| P95 ms | **101654.5** | 124427.5（**×1.224**） |

落库：`agent_eval_runs` id=4（loop=hand）/ id=5（loop=langgraph），config_snapshot 带 `{"loop","module":"091"}`。

## 决策：**维持自研**

- 判据①②通过；**判据③的 P95 项不通过**（×1.224 > ×1.20，超阈值 2.4%；P50 同向 +16.3%，非纯尾部噪声）
- 按事前规则"任一不满足 → 维持自研"执行

**必须照实记录的对自研不利事实**：LangGraph 版质量全面占优（pass^1 +0.1667、工具正确率 +0.1667、Grounding +0.06、tokens −3.6%）。等价性 36/36 也证明实验分支未失修。维持自研的依据**仅是延迟阈值超标**，且为单次采样——若后续多次采样复测 P95 落回阈值内，转正议题可重启，数据基础已就绪（本 ADR + agent_eval_runs id=4/5 + `eval/langgraph_parity.py` 可复现）。

## 被否决的方案与理由

1. **转正 LangGraph 到主路径**（判据③不达标）：P95 ×1.224 超阈值，且 StateGraph 调度开销未做根因归因；在延迟达标前不动 `/ai/rag/chat/agent` 与 `engine.chat`
2. **删除 LangGraph 实验分支**：质量指标占优 + 等价性 100%，删除等于丢掉已验证的替代实现；保留实验端点并在 README 标注"实验分支，对比结论见 module-091"
3. **引入更多 LangGraph 能力（多 Agent 编排/T5 子任务）**：路线图明确 T5 不做多 Agent 编排，本轮证据不足以支撑扩大框架面
4. **放宽延迟阈值后转正**：阈值系事前定死，事后放宽即"找补"；如确需放宽，须新开模块重新定判据并复测

## 后续

- 维持 `agent/react.py` 主路径不变；`agent-lang` 实验端点保留
- 若重启转正：多次采样（≥3）复测延迟 + StateGraph 开销归因（节点调度 vs 供应商方差）→ 新模块走同一判据框架
- 评测脚本 `eval/langgraph_parity.py` 留作回归工具（`--mode fixture` 秒级可验结构等价不漂移）

## 面试话术

> "框架 vs 自研我不拍脑袋：我用同一评测集做了两层对拍——先 fixture 假 LLM 回放证明结构等价（36 条工具序列逐字一致，零 LLM 零 DB 秒级可复现），再真实模式同子集交替跑两条环路摊平限流抖动。结果很有意思：LangGraph 版质量全面占优（pass^1 0.58 对 0.42），tokens 还省 3.6%，但 P95 延迟超了我事前定死的 1.20 倍阈值（实测 1.224）。规则是事先定的，任一条不满足就维持自研——所以我维持了自研，但同时如实记录 LangGraph 质量占优这个对我原方案不利的事实，转正议题留了重启条件：多次采样复测延迟。结论可复现：脚本在 eval/langgraph_parity.py，两次落库在 agent_eval_runs 表。"
