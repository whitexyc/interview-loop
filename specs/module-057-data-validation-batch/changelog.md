# Changelog — Module-057: 数据验证批（矛盾改进 + 图谱消融 + 改写增益 + RRF 扫描 + 飞轮冒烟）

> Developer | 2026-08-12
> 开工前已读 `memory/project-context.md` 全文（module-001~056 清单与迭代状态，避免重复/冲突）✅

---

## 1. 模块目标与结果（5 个硬数字）

| WP | 内容 | 结果 |
|----|------|------|
| WP-A1 | mDeBERTa 矛盾改进（句级拆解 + 阈值校准 + 样本扩至 86）→ 复测 kappa 对比 0.5167 | ✅ 完成但**改进不成立**：kappa 0.4311（全量 110 对）/ **0.3754（同口径旧 80 对，< 基线 0.5167，-0.1413）**，未达门槛 0.7，降级双轨维持（eval_runs id=26） |
| WP-A2 | 图谱消融补跑（DB 已修）→ graph_only vs hybrid Hit@5 差值 | ✅ **+0.2381**（--ablate 同跑 0.7429 → 0.9810；单模式落库 id=27 0.7333 / id=28 0.9905），rrf 三通道口径 |
| WP-A3 | 改写真实增益 → 原始 vs 改写 Recall@K/MRR | ✅ Hit@5 **+0.0096** / Recall@5 +0.0048 / MRR **-0.0353**（improved 3 / worsened 10）——基线近饱和，改写无净收益（eval_runs id=29） |
| WP-A4 | RRF k 扫描（20-100）+ 两通道归因 | ✅ k 全平坦 **0.9810**（20-100 无一拐点），两通道 0.9714，**图谱净增益 +0.0096**——k=60 保持不改默认（eval_runs id=30） |
| WP-A5 | 飞轮冒烟（造对话 → 真实 chat → 👍👎 → 落库验证 → 防重复） | ✅ 5 条真实回答 + 6 行 feedback 落库（含 1 次重复提交验证）+ 422 拦截；数据保留为飞轮种子 |
| WP-A6 | 测试 + 全量回归 + 文档 + 记忆 | ✅ 新增 40 项单测；全量 pytest 全绿（见 §7） |

---

## 2. WP-A1 矛盾改进（句级拆解 + 阈值校准 + 样本扩充）

### 2.1 改动

- **`ai_service/eval/retest_nli.py`（改）**：新增句级拆解管线——`split_claim`（。！？；!? 切子句，拆不出 ≥2 子句回退整句零回归）→ 逐子句 vs 文档判定 + 内部矛盾子句两两互判（子句 i 作 doc、子句 j 作 claim，双向）→ `aggregate_sub_judgments` 最严聚合（任一 contradiction → contradiction / 无矛盾有 entailment → entailment / 全 neutral → neutral）；阈值校准——低置信降级（max softmax prob < t → neutral），扫描 0.5-0.9 步长 0.05（`scan_thresholds` 纯 CPU 复用一次性打分记录，避免 9 倍推理）；同口径旧集（constructed[:56] + real 24）逐阈值曲线；eval_runs `eval_type='nli_retest_v2'`（id=26，含 scan/same_set_scan/per_question 拆解明细；id=25 为初版运行——无 same_set_scan——与 id=26 scores 完全一致，两者并存属版本化追加，id=26 为增强版权威记录）。
- **`ai_service/eval/build_contradiction_dataset.py`（改）**：扩充 30 条追加在 module-054 首版 56 条之后（constructed[:56] 保持同集，同口径对比前提）——claim_vs_doc +14（合计 30）、internal 多句混合"前真后假" +8（合计 23 ≥ 20）、entailment 多句正例 +6、neutral 多句无关 +2；指南同步更新。
- **`ai_service/eval/contradiction_dataset.json` / `contradiction_annotation_guide.md`（重新落盘）**：86 条 = contradiction 53 / entailment 22 / neutral 11。

### 2.2 复测结果（eval_runs id=26，全量 110 对 = 构造 86 + 真实检索 24）

| 口径 | kappa(三分类) | kappa(二值) | Acc(三分类) |
|------|--------------|------------|------------|
| **module-054 基线**（argmax 无拆解无阈值，旧 80 对） | **0.5167** | 0.6176 | 0.6750 |
| **module-057 v2 同口径旧 80 对**（t=0.80） | **0.3754（-0.1413）** | 0.5276 | 0.5750 |
| v2 全量 110 对（t=0.80，扫描最优） | **0.4311** | 0.5614 | 0.6182 |

- 阈值扫描：全量最优 t=0.80（kappa 0.3962→0.4311）；**同口径旧集逐阈值全部低于基线**（t=0.5 纯拆解 ≈ 0.3381，旧集最优 t=0.75 也仅 0.3923）。
- **归因（诚实）**：扣分主要来自**最严聚合误杀 9 条**（人工 entailment/neutral 被预测 contradiction）——多句 LLM 真实答案子句对（pairwise）误判互斥（如"父加载器→子加载器"互补陈述被判 contradiction）、部分子句单独判定丢上下文（整句 entailment 拆开后子句被判 contradiction）；真实检索子集 kappa 0.4700 → **0.0957**（多句答案全部触发拆解，聚合误杀集中爆发）。
- **核心短板依旧**：矛盾 55 条仅判对 29（22 判 neutral）——mDeBERTa 对"反转断言"（claim_vs_doc）与单句混合"X，但 not-X"（internal）仍倾向判 neutral；句号级拆解只覆盖多句样本，单句矛盾拆不开（逗号切分也不解决——这是模型语义理解问题）。
- **结论**：改进未达门槛且同口径下降，**句级拆解 + 最严聚合方案不成立**，降级双轨（NLI 只做矛盾扫描，不替换 HHEM 主裁判）维持。**ADR-0010 已更新**（"kappa 复测 v2"节）。下一轮方向（按性价比）：① 换中文专用/更大 NLI 并重跑同口径复测；② 针对性微调（单句混合矛盾 + 反转断言样本）；③ 两阶段 LLM 拆句（含逗号级语义子句）+ 保守矛盾门控（仅高置信 contradiction 触发）；④ HHEM 保持主裁判。

---

## 3. WP-A2 图谱消融补跑（DB 修复后 --ablate 直接跑）

运行：`python -m eval.golden_retrieval --ablate`（同进程两模式 side-by-side）+ 单模式落库。**口径注明**：评估路径直调 retriever，`fusion_mode` 全局默认 rrf（module-055 切默认）——**本次数字是 rrf 三通道口径**，与历史 hybrid 两通道 min-max 加权数字（0.9565/0.9714）为不同融合公式，仅参考不直接可比。

| 指标 | graph_only | hybrid（rrf 三通道） | delta |
|------|-----------|---------------------|-------|
| Hit@5 | 0.7429 | **0.9810** | **+0.2381** |
| Recall@5 | 0.7381 | 0.9714 | +0.2333 |
| MRR | 0.6776 | 0.9294 | +0.2518 |

- 按类：java_gc +0.4444 / agent +0.5714 / jvm +0.3333 / distributed +0.3333 / java_concurrency +0.2308（图谱在检索弱的类别增益最大）；redis +0.0000（图谱无覆盖）。
- **eval_runs 落库**：`--ablate` 本身不落库（module-038 既有行为），delta 由两次单模式运行派生——id=27（graph_only Hit@5=0.7333/Recall 0.7286/MRR 0.6752）+ id=28（hybrid Hit@5=**0.9905**/Recall 0.9762/MRR 0.9341）。id=27/28 与 --ablate 数字差约 ±0.01 系图谱实体提取 LLM 运行间波动（如实声明）。**delta 未落库说明**：+0.2381 无独立持久化字段（`--ablate` 不落库为 module-038 既有行为，id=27/28 无 delta 字段）——delta 由 id=27/28 派生记录，数值诚实可追溯；后续重跑时随 --ablate 一并落库。
- **解读**：图谱通道单打独斗能命中 74%（覆盖差的类别尤其强），但三通道 RRF 融合下 FTS+向量已近饱和（两通道 0.9714，见 WP-A4），图谱的融合边际增量 +0.0096——**图谱是"保险丝"型通道：单独不输、合则不赘**。

---

## 4. WP-A3 改写真实增益（golden_query_rewrite 真实模式）

运行：`python -m eval.golden_query_rewrite`（真实模式：LLM 改写 + DB 检索，deepseek 真实调用）。**口径**：生产默认 rrf 三通道（`hybrid_retriever.retrieve` 默认模式）。eval_runs id=29（eval_type='query_rewrite'），n=104 评估 + 8 skipped（7 no_gold_docs + 1 rewrite_failed 如实记 skipped）。

| 指标 | 原始 query | 改写 query | delta |
|------|-----------|-----------|-------|
| Hit@5 | 0.9808 | 0.9904 | **+0.0096** |
| Recall@5 | 0.9712 | 0.9760 | +0.0048 |
| MRR | 0.9287 | 0.8934 | **-0.0353** |
| improved / worsened | — | — | 3 / 10 |

- 不充分子集（module-044 标注交叉引用，n=6）：Hit 1.0000→1.0000，MRR 1.0000→**0.8056（-0.1944）**——连改写价值最大的不充分场景也无增益。
- **结论（诚实）**：rrf 三通道基线（Hit@5 0.98）已近饱和，改写仅把 1 题带进 top5（+0.0096），却因改写扰动排序使 MRR -0.0353（fidelity 0.72-0.96 说明改写引入扰动）。**当前生产口径下查询改写无净收益**——生产分诊改写链路保留（保真护栏 + 不充分场景重写仍作为护栏），不改生产默认行为；module-049 的 hybrid 口径增益数字随基线提升已不再成立，简历/文档引用改写增益需用本次 rrf 口径数字。

---

## 5. WP-A4 RRF k 扫描 + 图谱归因（eval/benchmark_rrf_k.py 新建）

**效率设计**：三通道候选与 k 无关——每题 FTS/向量/图谱只收集一次（图谱实体提取 LLM 每题 1 次），逐 k 的 RRF 融合纯 Python 完成（`fuse_rrf` 独立实现公式 score(d) = Σ 1/(k+rank)），k 扫描 10 值只付出 1 次检索成本。

| k | 三通道 Hit@5 | Recall@5 | MRR | 两通道 Hit@5 | 图谱增益 |
|----|------------|----------|-----|-------------|---------|
| 20/25/30/40/50/60/70/80/90/100 | **0.9810**（全平坦） | 0.9714 | 0.9294 | 0.9714 | **+0.0096** |

- **k 曲线全平坦**：k=20-100 三通道 Hit@5 恒 0.9810——本场景 k 不敏感（候选深度 10、通道重叠度高，RRF 排名对 k 稳健），**无拐点可扫描**。如实修正：脚本"拐点加密"仅补 k=25（最优 k=20 的 ±5 范围内唯一合法点），未扫 35/45/55/65/75/85/95——曲线全平坦故无实际影响。
- **最优 k 结论**：保持 k=60 业界默认（与最优无差别），**不改 `rrf_constant_k` 默认、无需测试适配**（test_rrf_fusion 断言 k=60 保持）。
- **两通道归因**：两通道 RRF 0.9714 vs 三通道 0.9810 → **图谱净增益 +0.0096**（105 题中 1 题靠图谱进 top5）；图谱通道空候选 24/112 题（实体提取失败或图无覆盖，如实标注；该数字仅记录于 changelog，脚本打印未落库——eval_runs id=30 无此字段）。与 WP-A2 的 +0.2381 是不同归因口径：+0.2381 = 图谱单通道能力 vs 融合系统；+0.0096 = 图谱在两通道基础上的融合边际增量。
- eval_runs id=30（eval_type='rrf_k_scan'，scores 含 curve/best_k/k60 对比/口径声明）。

---

## 6. WP-A5 飞轮冒烟（eval/flywheel_smoke.py 新建）

按用户指示"自己造一些对话然后根据回答点击"，端到端验证飞轮链路。运行：`python -m eval.flywheel_smoke`（自动拉起 uvicorn 8001 → 冒烟 → 停服）。

- **① 自造 5 条知识库问题**（G1 核心创新 / Kafka 不丢消息 / volatile 原子性 / RDB vs AOF / HashMap 树化）→ 真实 HTTP `/ai/rag/chat` 全部 200，真实回答引用真实文档（555-1527 字）。
- **② 模拟点击**：POST /ai/feedback 5 次（rating 交替 +1/-1，2 条带 comment）→ 全部 HTTP 200 `{"status": "ok"}`。
- **③ 落库验证**：feedback 表 identity=203.0.113.66（XFF 注入，匿名降级口径）共 6 行——message_id/rating/comment/identity/created_at 全部正确。
- **④ 非法输入**：rating=0 → HTTP 422（Pydantic 校验拦截，防落库污染）。
- **⑤ 防重复验证（如实记录）**：同一 message_id 二次提交（rating 翻转模拟"改主意"）→ 后端**无幂等**（module-048 设计如此），落库 2 行；防重机制是**前端已评态**（ChatMessage.tsx localStorage `rag_feedback_rated` 按 message_id 记录不重复提交，grep 确认）——本模块不改生产行为，如实记录为已知边界。
- **message_id 声明**：AI 层直连 chat 无 Java 后端消息主键（message_id 来自 Java 消息表主键），按规划降级用**构造标识 990000+i**（远离真实主键范围，不冲突），Java 侧回填口径待真实链路（经 Java 后端 chat）验证。
- **冒烟数据保留为飞轮种子**（changelog 注明）：6 行 feedback（身份 203.0.113.66，message_id 990001-990005），作为层 4 分类器（intent/充分性）重训数据源的第一批积累；服务已停止。

---

## 7. 测试

- **`ai_service/tests/test_nli_improve.py`（新，32 项）**：句切（全标点/回退整句/空串/换行）、低置信降级（边界相等不清零）、最严聚合（子句矛盾/子句对矛盾/entailment 分支/全 neutral/子句对 entailment 不算数）、拆解判定管线（整句形态/多句 sub+pair/双向/3 子句 6 对）、阈值扫描（0.5-0.9 步长/逐阈值行/分布/最优选择/低置信偏移）、样本集（contradiction ≥50、internal ≥20 且多句混合 ≥5、**constructed[:56] 保持 module-054 同集**、JSON 结构不变）——全部假 scorer 注入，不加载模型。
- **`ai_service/tests/test_benchmark_rrf_k.py`（新，8 项）**：fuse_rrf 公式（单通道/已知 rank/两通道/三通道图谱提升/k 敏感/空通道/图谱按 hybrid_score 排序/通道键对齐）。
- 存量测试零改动；全量 pytest 结果见验收汇总（700 基线 + 40 新增）。

---

## 8. 文档与记忆

- **ADR-0010**：新增"kappa 复测 v2（module-057）"节（数字 + 归因 + 下一轮方向），状态行同步。
- **memory/project-context.md**：module-057 行 + 头部日期 + ADR-010 索引行 + 迭代状态。
- **memory/agent-activity-log.md** / **memory/file-index.md**：Developer 活动行 + 新文件行（只追加）。
- 前端/简历/弹药类文档零改动（用户指示：等优化完成后进行）。
- 未 git commit（主会话统一提交）。

---

## 9. 诚实边界（汇总）

1. WP-A1 样本为人工构造（方向性验证），复测 v2 **改进不成立**（0.3754 < 0.5167）——如实标注不伪造；阈值在评估集上扫描选择（in-sample 乐观偏差），生产阈值需独立集确认。
2. 句级拆解最严聚合误杀 9 条（kappa 说话）——"任一子句矛盾 → 整句矛盾"在真实多句答案上过激，已量化并写入 ADR 下一轮方向。
3. WP-A2/A3 是 **retriever 口径**（评估直调 retriever，不含引擎层 round 0/1 编排差异）；rrf 三通道 vs 历史 hybrid 两通道为不同融合公式，对比已注明。
4. WP-A2/A4 图谱数字含 LLM 实体提取运行间波动（±0.01，如实标注）；图谱空候选 24/112。
5. WP-A5 飞轮数据为**自造**（非真实用户），验证链路 + 种子数据；真实飞轮仍靠用户点击积累；message_id 为构造标识非 Java 主键；后端无幂等（防重在前端已评态）如实记录。
6. 改写增益在 rrf 饱和基线下为负（MRR -0.0353），不改生产改写链路（护栏价值保留）。

---

## 10. Minor 修复记录（Reviewer 5 条，2026-08-13）

1. 单测计数修正（pytest 实查 40 = test_nli_improve 32 + test_benchmark_rrf_k 8）：§1 WP-A6"38 项"→"40 项"、§7 test_nli_improve"30 项"→"32 项"、"700 基线 + 38 新增"→"+ 40 新增"、file-index"30 项"→"32 项"。
2. eval_runs id=25 说明补充（§2.1）：id=25 为初版运行（无 same_set_scan），id=26 为增强版权威记录，两者 scores 完全一致，并存属版本化追加。
3. WP-A2 delta 未落库说明补充（§3）：+0.2381 无独立持久化字段——`--ablate` 不落库为 module-038 既有行为、id=27/28 无 delta 字段——delta 由 id=27/28 派生记录，数值诚实可追溯；后续重跑时一并落库。
4. WP-A1 阈值配置化字面差距如实记录（§2）：最优阈值在 retest_nli.py 内自动选取 + `--threshold` 可固定，未入 src/config.py（无生产接线）——因复测结论为负且本模块为评估侧边界，合理。
5. WP-A4"拐点加密"描述修正（§5 + file-index）：脚本仅补 k=25（最优 k=20 的 ±5 范围内唯一合法点），未扫 35/45/55/65/75/85/95——曲线全平坦无拐点故无实际影响；图谱空候选 24/112 为 changelog 记录非 eval_runs 字段（id=30 无此字段）。
