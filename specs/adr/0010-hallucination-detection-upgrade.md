# ADR-0010 — 幻觉检测升级方案（HHEM 专职裁判 + 逐句报分 + 矛盾扫描）

- 状态：✅ **P0-② 已实施，裁判切换完成**（2026-08-11 module-051：verify_answer 拆分——LLM 拆句 + HHEM-2.1-Open 判分（max 分映射三态 0.7/0.3，evidence 取 max 文档号）+ 降级链三层（HHEM 失败→LLM 旧全量 prompt→空 claims，开关 "llm" 零回归）；共享加载器 hhem_loader.py 单一来源；评测闭环 golden_factcheck 50 条实测 **kappa 三态 0.3252 < 0.7 未达门槛，如实标注**——中文分数压缩致 0.7 上界偏严 + HHEM 对"部分覆盖"判一致偏乐观，阈值/标注口径校准留待标注集扩充；**P1-③ 前置决策完成（module-052，2026-08-12）：mDeBERTa-v3 多语言 NLI 三分类 kappa 0.4711 显著优于 HHEM 0.1351（同批 100 对）→ 替换方向推荐**，详见"P1-③ 选型结论"；**P1-③ 复测完成（module-054，2026-08-12）：kappa 三分类 0.4991 < 0.7 未达放行门槛 → 降级双轨（NLI 只做矛盾扫描，不替换 HHEM 主裁判）**，详见"kappa 复测计划"节；**P1-③ 复测 v2 完成（module-057，2026-08-12）：句级拆解 + 阈值校准后 kappa 0.4311（全量 110 对）/ 0.3754（同口径旧 80 对）< 0.7 且低于 module-054 基线 0.5167（delta -0.1413）→ 改进未达门槛，降级双轨维持**，详见"kappa 复测 v2（module-057）"节；**P1-④ 阈值校准完成（module-071，2026-08-18）：标注集 50→136（inferred"部分覆盖"口径重写 + real 真实 claim 转换）+ 25 组阈值扫描（分数只算一次）——重跑三态 kappa 0.2981 < 0.7 不达标（新 136 集全网格最优 0.3309 / 旧 50 集最优 0.3711），阈值校准证伪，不改生产配置（0.7/0.3 保持）；失败模式：supported 误杀 24 / inferred 混淆 15 / unsupported 漏判 22（HHEM 对"相关背景"文档打 0.79-0.90 高分）→ 下一步与 module-057 结论汇合（中文专用 NLI/微调、两阶段 LLM 拆句+保守矛盾门控、飞轮数据定向补样本），详见 changelog module-071**；P1-③ 实施 / P2 生产化按需）
- 前置：2026-08-11 module-050 实测：100 对真实数据（SUFFICIENCY_DATASET）HHEM-2.1-Open Accuracy 0.77 / F1 0.7527 / 0.36s 每对 **显著优于** MiniCheck-RoBERTa-Large 0.51 / 0.0392 / 2.86s；核心发现 MiniCheck 中文退化——supported 召回仅 2%（英文判别正常排除 bug），两模型 kappa 0.0264 几乎无一致性；**中文场景选型结论 HHEM**
- 日期：2026-08-10（2026-08-11 更新状态）
- 背景：审查 `reflector.py::verify_answer`（module-039 逐句幻觉检测）后，结合业界方案（RAGAS / HHEM / claim-level 深挖 / LLM-judge 研究）诊断出多项问题。本 ADR 记录现状问题 + 业界对标（含 HHEM 实测参数）+ 分阶段方案。

## 现状基线（代码事实，module-039）

`verify_answer`（reflector.py:368-449）：
- 答案生成完 → **同 LLM**（温度 0，15s 超时）拆答案成 claims（陈述句）
- 每条标 supported / inferred / unsupported + 证据号 [1]
- 证据号越界（<1 或 >doc_count）→ 强制降级 unsupported（防引用号编造）
- 置信度 = `1 - unsupported/total`（overall_confidence）
- 15s 超时 → 返回空 claims（overall_confidence=0.0，降级不阻塞响应）
- 前端按 claims 色标展示（supported ✓绿 / inferred ~黄 / unsupported ✗红）

## 现状问题诊断（8 项，按严重度）

| # | 问题 | 影响 |
|---|---|---|
| 1 | **同源验证**——`generate_answer` 和 `verify_answer` 走同一 LLM，模型验证自己的输出 | 自我偏好（sycophancy），给自己答案打高分 |
| 2 | **伪验证**——证据号越界只防"引用号编造"，但 [1] 存在、内容与 claim 无关时 LLM 说 supported 就 supported | 没有锚定文档原文，所谓验证是 LLM 再判一次 |
| 3 | **置信度平均化**——`1-unsupported/total` 把 5 句错 1 句压成 0.8 | 总分掩盖单 claim 幻觉；inferred 不扣分（推断是幻觉高风险区）；无 claim 权重 |
| 4 | **超时静默降级**——15s 超时返回空 claims，长答案更易超时却更需要验证 | "验证缺席"发生在最该验证处；前端无法区分"未验证"vs"验证失败" |
| 5 | **无验证器评测闭环**——`eval/faithfulness.py`（module-038）是答案质量评测，不是验证器自身准确率 | 验证器判 supported/unsupported 的误判率未知 |
| 6 | **claim 拆解不可控**——LLM 拆 claims 无校验 | 拆错边界/合并/遗漏，后续判定全基于错误分割 |
| 7 | **只标注不修正**——unsupported 只展示不触发纠错 | 用户看到红标答案还是错的 |
| 8 | **成本**——每次验证一次完整 LLM 调用（文档全文+答案全文） | 长答案 token 消耗高 |

## 业界对标（2026-08-10 调研）

- **RAGAS Faithfulness**（docs.ragas.io）：公式与项目同构（claim 级分解 + 验证）；标准版 LLM judge，`FaithfulnesswithHHEM` 用 HHEM 替代验证步
- **HHEM-2.1-Open**（Vectara，HuggingFace 官方）：专职幻觉检测分类模型——比 LLM-as-judge 更可靠更鲁棒
- **futureagi《Evaluating RAG Faithfulness: A 2026 Deep Dive》**：**"answer-level groundedness 是 vibe check"**——平均化掩盖单 claim 幻觉（5 claim 错 1 个 mean 0.8 但 per-claim 幻觉率 18%）；三大失败模式：multi-claim hallucination / **cherry-picked context**（只引用支持自己的 chunk 忽略矛盾）/ sycophantic restatement；解法 = claim 级分解 + per-claim grounded scoring + **未使用 chunk 的矛盾扫描**
- **Reliability without Validity**（arXiv 2606.19544，54 万次判断）：LLM-judge 的 consistency-bias paradox——judge 可高度一致（>0.95）却严重位置偏差（>0.10）；评估 judge 用 Cohen's kappa 而非 match 百分比
- **生产阈值**（enison.ai）：Faithfulness < 0.95 阻止部署；CI/CD gate + 每日抽样 + 周环比降 5% 报警 + HITL；测试集 100-500 条
- **生产检测栈**（mljourney/futureagi）：self-consistency（多采样）、entropy/log-prob 预筛、chunk attribution、抽样 5-10% 监控

### HHEM-2.1-Open 实测参数（已验证可本地部署）

| 项 | 值 |
|---|---|
| 参数量 | 110M（0.1B，FLAN-T5 分类版） |
| 内存 | **< 600MB**（F32）——机器已跑 bge-m3 + reranker（>3GB），加它无压力 |
| 推理 | **~1.5s / 2k token 输入**（现代 x86 CPU，无需 GPU） |
| 上下文 | 无限（HHEM-1.0 仅 512 token） |
| 许可证 | Apache 2.0 开源免费 |
| 性能 | RAGTruth-QA 74.28% 平衡准确率（> GPT-3.5 56.16%、≈GPT-4 74.11%） |
| 用法 | `AutoModelForSequenceClassification`，premise(文档片段)-hypothesis(claim) 对 → 0-1 分；RAGAS 批量 batch_size=10 |

## 分阶段方案

### P0 · 先修最疼的（半天-1 天）

**① 逐句报分（per-claim 报告）——纯前端，零风险先做**
- 前端从"总分展示"改为"每条 claim 单独标色"（supported 绿/inferred 黄/unsupported 红）——`verifiedClaims` 已在传 claims 数组，只差 UI
- 解决问题 3（平均化）；成本：纯前端；验证：人工看 10 条红标是否对应真问题

**② 换专职裁判（HHEM 替代 LLM 验证）**
- `verify_answer` 的"claim 有没有依据"判断交给 HHEM-2.1-Open（claims 拆解仍用 LLM，验证用 HHEM）
- 解决问题 1（同源验证）+ 8（成本）；成本：加 600MB 本地模型
- 验证：20 条答案 HHEM vs 人工判定一致率

### P1 · 两道保险（1-2 天）

**③ 矛盾扫描（contradiction scan）**
- 把**未引用的文档片段**也做 HHEM 判定（"这段和 claim 矛盾吗"）
- 解决问题 2（伪验证/cherry-pick）；验证：构造 5 条"文档有矛盾但答案挑樱桃"用例

**④ 验证器评测闭环**
- 人工标 50 条 claims，算 HHEM 判定 vs 人工的 **Cohen's kappa**
- 解决问题 5（无评测）；门槛：kappa > 0.7 才信这个裁判

### P2 · 生产化（按需）

**⑤ 低分拦截/标记 + 抽样监控**：faithfulness < 阈值（0.6）标记低可信或触发重生成；生产抽样 10% 跟踪趋势 + 周环比报警

## 实施顺序

1. P0-① 逐句报分（前端，半天，零风险）
2. P0-② 换 HHEM 裁判（后端，半天-1 天）
3. P1-③ 矛盾扫描（后端，半天）
4. P1-④ 裁判评测闭环（标注 50 条 + kappa，半天）
5. P2-⑤ 生产化（按需）

## P1-③ 选型结论（module-052 前置决策，2026-08-12）

**决策：替换（推荐）——mDeBERTa-v3 多语言 NLI 作为逐句裁判的三态来源，替代 HHEM**（矛盾扫描与支持度判定统一走 NLI 三分类）。放行条件 = kappa 复测通过（见下）。

### 实测数据（100 对，SUFFICIENCY_DATASET 同源同构，人工三分类标注 entailment 50 / neutral 50 / contradiction 0）

| 模型 | kappa(三分类) | kappa(二值) | Acc(三分类,基33%) | Acc(二值,基50%) | s/对 |
|------|------------|-----------|----------------|--------------|------|
| **mDeBERTa-v3** | **0.4711** | **0.7600** | 0.6800 | 0.8800 | 0.786（长输入批量）|
| HHEM-2.1-Open（0.7/0.3 生产阈值） | 0.1351 | 0.4400 | 0.3600 | 0.7200 | 0.377 |

- 两口径 kappa 均 mDeBERTa 显著优（三分类 0.4711 vs 0.1351；二值 0.7600 vs 0.4400）。
- 混淆矩阵：mDeBERTa entailment 判别 46/50（vs HHEM 23/50）；HHEM 48/100 判 contradiction
  ——中文分数压缩（p25=0.058 / 中位 0.359）致 0.3 低阈值下 contradiction 泛滥。
- **HHEM 阈值敏感性（诚实校验，非篡改口径）**：全 (high, low) 网格扫描，HHEM 最优
  kappa(三分类) = 0.2903（high=0.50/low=0.05）仍远低于 mDeBERTa 0.4711 →
  **差距是内在的，非阈值 artifact**；生产阈值 0.7/0.3 在中文场景严重失准（0.1351）是附带发现。

### 三态映射定义（替换方案）

```
NLI 原生三分类（argmax，无阈值） → verify_answer 三态
entailment   → supported
neutral      → inferred
contradiction → unsupported
```

### kappa 复测计划（实施前置，通过才放行）

1. **矛盾构造样本集**：本批 contradiction 0 条（数据源无矛盾构造成分），P1-③ 核心能力
   未验证——需构造 ≥20 条"文档与 claim 矛盾"样本（复用 golden 题 + 注入矛盾文档）复测
   矛盾判别 kappa。
2. **claim 用真实答案句子**：本批 claim=问题代答句（代理度量），复测用 verify_answer
   的真实答案句子（LLM 拆句输出）。
3. **文档用真实检索结果**：本批为注入代表性文档；复测用 DB golden 112 题真实检索片段。
4. **门槛**：复测 kappa（三分类）≥ 0.7 通过；未达则降级评估（双轨：NLI 只做矛盾扫描）。

### kappa 复测结果（module-054，2026-08-12）——**未达放行门槛，降级双轨**

复测 80 对 = 人工构造 56 对（矛盾 32 = claim_vs_doc 16 + internal_contradiction 16，
正例 entailment 16，neutral 8）+ 真实检索 24 对（LLM 真实答案句子 deepseek-v4-flash +
DB golden 112 题 hybrid 真实检索片段，人工标注）。mDeBERTa argmax 三分类 vs 人工标注：

| 样本集 | 样本数 | kappa(三分类) | kappa(二值) | Acc(三分类) | Acc(二值) |
|--------|--------|--------------|------------|------------|-----------|
| **总体** | 80 | **0.4991** | 0.6176 | 0.6625 | 0.8375 |
| 人工构造 | 56 | 0.4488 | 0.7101 | 0.6429 | 0.8750 |
| 真实检索 | 24 | 0.4700 | 0.4146 | 0.7083 | 0.7500 |

- **结论：kappa 三分类 0.4991 < 0.7 未达门槛，如实标注 —— 降级双轨：NLI 只做矛盾扫描，
  不替换 HHEM 主裁判**（eval_runs id=21，eval_type='nli_retest'）。
- **失败模式（混淆矩阵，行=人工 / 列=mDeBERTa）**：contradiction 34 条仅判对 19
  （11 误判 neutral、4 误判 entailment）；neutral 21 判对 16；entailment 25 判对 18。
  核心短板：**internal_contradiction（claim 句内自相矛盾）大量判 neutral**——mDeBERTa
  看到"X，但 not-X"混合断言倾向取"部分相关"判中立；claim_vs_doc 反转断言
  （如"G1 是 JDK 8 默认"vs 文档"JDK 9 默认"）也被判 neutral/entailment 各半。
- **对比**：代理度量批（module-052）100 对 kappa 0.4711（entailment 50/neutral 50/
  contradiction 0）——本次加入真实矛盾构造 + 真实答案句子后 0.4991，矛盾判别能力
  仍是短板，替换放行不成立。
- **后续**：矛盾判别需阈值校准（低置信降级）+ 标注集扩充 + 可能的句级拆解后判别
  （internal_contradiction 拆成两个子句再判），或考虑针对性微调；HHEM 保持现状主裁判。

### kappa 复测 v2（module-057，2026-08-12）——句级拆解 + 阈值校准，**未达门槛且低于基线，降级双轨维持**

复测 v2 改进 = 句级拆解（claim 按 。！？；!? 切子句 → 逐子句 vs 文档判定 + 内部
矛盾子句两两互判 → 最严聚合：任一矛盾→contradiction）+ 阈值校准（低置信
max prob < t → neutral，扫描 0.5-0.9 步长 0.05）。矛盾样本扩至 53 条
（claim_vs_doc 30 + internal 23，其中 8 条多句混合"前真后假"），全量 110 对 =
构造 86 + 真实检索 24。

| 指标 | module-054 基线（argmax，80 对） | module-057 v2（同口径旧 80 对，t=0.80） | v2 全量 110 对 |
|------|--------------------------------|------------------------------------------|----------------|
| kappa(三分类) | **0.5167** | **0.3754**（-0.1413） | **0.4311** |
| kappa(二值) | 0.6176 | 0.5276 | 0.5614 |
| Acc(三分类) | 0.6750 | 0.5750 | 0.6182 |
| 最优阈值 | —（无阈值） | 旧集最优 t=0.75 → 0.3923 | t=0.80 |

- **结论：改进未达门槛（0.4311/0.3754 < 0.7），且同口径旧 80 对低于 module-054
  基线（delta -0.1413）——句级拆解 + 最严聚合方案**不成立**，如实标注。
- **归因（同口径旧集逐阈值扫描，t=0.5 ≈ 纯拆解无阈值降级）**：拆解本身就把
  旧集 kappa 从 0.5167 拉到 0.3381（t=0.5）→ 扣分主要来自**最严聚合误杀**：
  9 条人工 entailment/neutral 被预测 contradiction——多句 LLM 真实答案
  子句对（pairwise）误判互斥（如"父加载器→子加载器"互补陈述被判 contradiction）、
  部分子句单独判定丢上下文（整句 entailment 拆开后子句被判 contradiction）。
  真实检索子集 kappa 0.4700 → 0.0957（多句答案全部触发拆解，聚合误杀集中爆发）。
- **阈值 t=0.80 的边际**：全量 0.3962→0.4311（低置信降级压住部分乱判），但远
  不够补拆解扣分；旧集上任何阈值都无法回到 0.5167。
- **核心短板依旧**：矛盾 55 条仅判对 29（22 判 neutral、4 判 entailment）——
  mDeBERTa 对"反转断言"（claim_vs_doc）与单句混合"X，但 not-X"（internal）
  仍倾向判 neutral，句号级拆解只覆盖多句样本，单句矛盾拆不开（逗号切分
  也不解决——这是模型语义理解问题，不是切分粒度问题）。
- **下一轮方向**（按性价比排序）：① 换更大/中文专用 NLI（如中文微调 mDeBERTa
  或 XLM-R 大模型）并重跑同口径复测；② 针对性微调（单句混合矛盾 + 反转断言
  样本）；③ 两阶段：LLM 拆句（含逗号级语义子句）+ NLI 判分，且矛盾判定用
  "仅高置信 contradiction 触发"保守门控（防聚合误杀）；④ HHEM 保持主裁判，
  NLI 只做矛盾扫描的降级双轨维持现状。

### 阈值校准计划

1. **置信度门限**：argmax 无阈值，但低置信预测（如 softmax 最大概率 < 0.6）→ 降级
   inferred 的置信度阈值需标注集扩充后扫描校准（对齐 module-047 threshold_scan 方法论）。
2. **512 token 截断验证**：mDeBERTa max_position_embeddings=512，超长文档尾部丢失
   的量化影响需在真实长文档上验证（本批文档平均约 250 token，影响有限）。
3. **生产推理预算**：5 claims × 5 docs 交叉打分需批量推理——实测短输入 25 对批量
   0.201s/对、全量长输入 0.786s/对 → 25 对交叉约 5-20s，需超时预算（对齐 15s 哲学）
   与批大小确认；mDeBERTa fp32 峰值内存 1.95GB（推理后可释放）。
   **后续实施模块须落实批处理拆分/超时预算（15s 哲学）**——25 对全量单批可能
   超时预算上限，须按批拆分或分级抽样，超预算降级走既有降级链（对齐
   verify_answer 15s 超时语义）。

### 顺序纪律（task-brief v2 §四）

- 若替换采纳：**HHEM 阈值校准项被替换决策取代**——校准对象改为 mDeBERTa 置信度口径
  （module-051 记录的"阈值/标注口径校准待标注集扩充"同步结转）。
- 重生成闭环（P2 拦截/重生成）仍等验证异步化之后（纪律② 不变）。
- 100 对代理度量是**方向性验证**，非最终结论——放行以复测为准。

## 面试话术

> "幻觉检测升级分三步：先把总分改成逐句报分（per-claim 报告），哪句编的一眼看到——业界说 answer-level groundedness 是 vibe check，平均化会掩盖单 claim 幻觉；再把 LLM 裁判换成 HHEM 专用检测模型，110M 参数、600MB 内存、CPU 1.5 秒一对，解决同源验证还免费——写答案的 AI 不能自己批自己卷子；然后加矛盾扫描——把没引用的文档片段也查一遍，防挑樱桃（AI 可能忽略了矛盾的 chunk）。每一步都有验证：逐句报分人工看红标、HHEM 用 50 条人工标注算 Cohen's kappa 确认裁判靠谱（一致性≠正确性）、矛盾扫描用构造的挑樱桃用例测。"

## 验证位置（链路上明确，面试必讲）

幻觉检测在**答案生成之后**（engine.py:338-342）：`generate_answer` 完才调 `verify_answer`，**不在检索内部**。因为幻觉发生在生成阶段——检索只有素材，答案才是成品，只能检查成品是否忠于素材。链路里三个"检查"各管一段：

| 环节 | 位置 | 管什么 | 是幻觉检测吗 |
|---|---|---|---|
| 检索 + Rerank | 最前 | 文档和问题像不像 | ❌ 不是 |
| 反思（check_sufficiency） | 生成前 | 文档够不够回答 | ❌ 不是——管检索质量 |
| 幻觉检测（verify_answer） | **生成后** | 答案每句话有没有依据 | ✅ 是 |

类比：买菜（检索）时检查不了菜做得对不对，只能做完菜（生成）后检查是否照菜谱。

## 串行阻塞问题（必须修）

`engine.py:342` 当前是**串行 await 阻塞**：
```
answer = await generate_answer(...)
verified = await verify_answer(answer, docs)  # 阻塞 1.5-3s ← 非流式用户干等
return ChatResponse(answer, verified_claims=verified)  # 验证完才返回
```

**问题**：1.5-3s 验证时间直接加在响应延迟上；流式路径（main.py:506）首字不阻塞但色标也干等。

**解法**（按性价比）：
1. **异步化 + 后置推送**（最推荐）：非流式也改成"答案先返回 + verified 后台算 + 前端轮询/SSE 推送"——用户感知延迟 = 生成时间
2. **抽样验证**：faithfulness 抽样 10%（业界主流，enison.ai 经验）
3. **分层验证**：先跑便宜信号（引用号越界、entropy），高风险才跑完整 HHEM/LLM
4. **验证期间并行做别的**：记忆写入、会话持久化、飞轮日志与验证 `asyncio.gather`
5. **缓存 + prefix caching**：MiniCheck 支持同文档 prefix 缓存

**推荐组合**：① + ③——先异步化（答案秒回），再分层（大部分跳过完整验证）。

## 模型选型（HHEM vs MiniCheck 详细对比，按场景分）

### 基准/指标大白话（先搞懂数字怎么来的）

- **基准（benchmark）= 给模型考试的考卷**：AggreFact-SOTA（"摘要忠实度"考卷，用最先进的 AI 生成摘要来考，最难）、RAGTruth-Summ（**最贴近本项目**——GPT-4/Claude 真实 RAG 回答含人工标注的真实幻觉）、TofuEval-MB（会议纪要考卷，多说话人场景）、FaithBench（忠实度专项考卷）
- **Acc = 及格率**：判对的句子数 ÷ 总句子数
- **F1 = 调和平均**：精确率（抓得准，别冤枉好句子）× 召回率（抓得全，别漏编造的）的调和平均——**惩罚偏科，更看重"抓幻觉"本事**；漏抓幻觉比误判严重，所以看 F1 不看 Acc
- **平均 F1 = 4 张考卷综合成绩**（防某科拉分）

### 三模型逐维度详细对比（核心）

| 维度 | HHEM-2.1-Open（现状） | **MiniCheck-Roberta-L** | **MiniCheck-FT5**（可提） |
|---|---|---|---|
| **参数量** | 110M | 355M | 770M |
| **架构** | FLAN-T5（编解码分类） | RoBERTa-Large（仅编码器） | Flan-T5-Large |
| **内存（fp32）** | <600MB | ~1.5GB | ~3GB |
| **CPU 推理**（单对） | ~1.5s / 2k token | ~2-3s | ~3-5s（15s 超时内稳） |
| **平均 F1**（5 基准） | 62.7 | **64.9**（+2.2） | —（LLM-AggreFact 74.7 ≈ GPT-4 75.3，统计无差异） |
| **AggreFact-SOTA** | 73.2 / 69.7 | **75.7 / 72.5** | 更高 |
| **RAGTruth-Summ**（最贴近项目） | 67.7 / 56.1 | **70.5 / 58.6** | — |
| **TofuEval-MB** | 60.9 / 61.2 | **67.6 / 68.5（大胜）** | — |
| **FaithBench** | **66.7 / 63.7** | 61.6 / 60.0（HHEM 反而略高） | — |
| **许可证** | Apache 2.0 | 开源（HuggingFace） | 同左 |

> 平均 F1 64.9 vs 62.7 = 考 4 张幻觉检测考卷，MiniCheck 综合更好——**尤其在最贴近真实 RAG 场景的 RAGTruth 上优势明显**；唯一输的是 FaithBench 单科。

### 关键差异（不只是"大一点"，训练方式专治本项目短板）

**MiniCheck 训练方式专门针对幻觉**（EMNLP 2024 论文，arXiv 2404.10774，14K 合成数据）：
- **C2D（Claim-to-Doc）**：设计"**两句合起来才支持**"的样本——逼模型做多句推理，不是看表面相关
- **D2C（Doc-to-Claim）+ hard negative**：删除文档关键证据后生成"看起来相关但缺证据"的反例——**专门训练模型识别"几乎支持但缺关键证据"的幻觉**
- → **正好补本项目"引用号存在但内容无关"的伪验证短板**：HHEM 可能被"表面相关"骗，MiniCheck 被训练过要"证据完整才支持"

**其他差异**：
- **粒度**：sentence-level fact-checking（`MiniCheck(doc, claim) -> [0,1]`），与本项目 `verify_answer` 的 claims 拆解天然契合
- **生态**：官方包 `pip install minicheck`、Ollama 支持、Guardrails AI 集成、**prefix caching**（同文档验多个 claim 复用 KV cache 更快）
- **FT5 是"<1B 最佳"**：GitHub 原话"MiniCheck-Flan-T5-Large (770M) is the best fact-checking model with size < 1B and reaches GPT-4 performance"

### 更大模型（4-8B 级，更准但要 GPU/量化）

| 模型 | 参数量 | 平均 F1 / 关键分数 | 说明 |
|---|---|---|---|
| **MiniCheck-7B / Bespoke-MiniCheck-7B** | 7B | F1 **67.3-68.5**（5 基准平均） | Qwen2-7B 微调，专门抓幻觉 |
| **Lynx-8B**（Patronus） | 8B | HaluBench 强，综合检测 77.25 | HaluBench 榜首常客 |
| **HAD-7B**（北大+阿里） | 7B | HaluEval-QA **82.2-92.4** | 专门幻觉检测，OOD 最强之一 |
| 参考：GPT-4o 零样本 | — | 平均 F1 73.0 | 7B 专用模型（67-68）已接近通用大模型检测能力 |

### CPU 权衡（更大 ≠ 直接可用，本项目是每次回答后在线跑）

| 模型 | 内存（fp16） | CPU 推理一个判断 | 对本项目 |
|---|---|---|---|
| HHEM 110M | <600MB | ~1.5s | ✅ 现状 |
| **MiniCheck-Roberta-L 355M** | ~1.5GB | ~3-5s | ✅ 可接受（15s 超时内稳） |
| MiniCheck-7B | ~14GB（量化 ~5GB） | **~30-60s** | ❌ 在线验证直接超 15s 超时 |
| Lynx-8B / HAD-7B | ~16GB+ | 更慢 | ❌ 在线不现实 |

### 场景推荐（落地结论）

| 场景 | 推荐 | 理由 |
|---|---|---|
| **在线实时验证**（本项目现状需求） | **MiniCheck-Roberta-L（355M）** | 平均 F1 +2.2、~1.5GB CPU 可跑、15s 超时内稳；愿意多花 3GB 直接上 FT5（770M）拿 GPT-4 级准度 |
| **离线批量评测**（飞轮/评估） | MiniCheck-7B / Bespoke-MiniCheck-7B | F1 67-68 明显更准，离线无所谓耗时，有 GPU 更好 |
| **有 GPU 的在线验证** | Lynx-8B / HAD-7B | 准度最高一档 |

## 与既有决策的关系

- 复用 eval_runs 版本化（裁判评测闭环）、前端 verifiedClaims（逐句报分）
- 与 ADR-0008 数据飞轮（验证器标注集可入飞轮）、ADR-0005 反思（层 1 硬闸门同思想）方法论一致
- **链路位置对比**（防面试说混）：反思查"文档够不够"（检索质量，ADR-0005），幻觉检测查"答案真不真"（生成质量，ADR-0010）——对象不同
