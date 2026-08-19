# Review Report — Module-057: 数据验证批（矛盾改进 + 图谱消融 + 改写增益 + RRF 扫描 + 飞轮冒烟）

> Reviewer | 2026-08-13 | 第一轮审查
> 结论：**✅ 通过（pass，0 阻塞 / 0 新引入）**

---

## 1. 审查范围与方法

- 完整阅读：plan.md / acceptance-criteria.md / changelog.md / ADR-0010（复测 v2 节）
- 完整阅读变更文件：`eval/retest_nli.py`、`eval/build_contradiction_dataset.py`、`eval/benchmark_rrf_k.py`（新）、`eval/flywheel_smoke.py`（新）、`tests/test_nli_improve.py`（新）、`tests/test_benchmark_rrf_k.py`（新）、`eval/contradiction_dataset.json`、`eval/contradiction_annotation_guide.md`
- **DB 独立核验**：eval_runs id=26/27/28/29/30 scores + per_question 重算；feedback 表 6 行
- 独立复跑：全量 pytest **740 passed / 0 failed**（166.62s，与 Developer 声明逐字一致）
- 记忆核验：project-context.md 行 75 + 头部日期 + ADR-010 索引行、agent-activity-log.md Developer 行、file-index.md 5 新行
- 前端防重机制核验：`frontend/src/components/ChatMessage.tsx:57` `RATED_FEEDBACK_KEY='rag_feedback_rated'` + 模块级 Map + localStorage 按 message_id 已评态（与 changelog 声明一致）

## 2. 验收逐条核对（对照 acceptance-criteria.md）

### WP-A1 矛盾改进（§1 功能验收）
- [x] 句级拆解：`split_claim`（。！？；!? + 换行切子句，拆不出 ≥2 子句回退整句零回归）→ 逐子句 vs 文档 + 子句两两互判（n×(n-1) 双向）→ `aggregate_sub_judgments` 最严聚合（任一矛盾→contradiction / 无矛盾有 entailment→entailment / 全 neutral→neutral）——代码核对 + 单测覆盖
- [x] 阈值校准：`SCAN_THRESHOLDS` 0.5-0.9 步长 0.05 共 9 值；低置信（max prob < t）→ neutral；一次性打分逐阈值纯 CPU 复用；最优阈值脚本自动选取 + `--threshold` 可固定（**注**：未入 src/config.py，见 minor #4）
- [x] 样本扩充：JSON 实查 86 条 = contradiction 53（claim_vs_doc 30 + internal 23 含 8 条多句"前真后假"）/ entailment 22 / neutral 11；**constructed[:56] 保持 module-054 同集**（实查首 56 = 16/15/16/9 逐项一致）；JSON 四键结构不变（86 条键集一致）；标注指南同步（含新增多句混合构造方法节）
- [x] 复测：eval_runs id=26 `eval_type='nli_retest_v2'`，**per_question 独立重算**：全量 110 对 kappa **0.4311**、同口径旧 80 对 **0.3754 < 基线 0.5167（-0.1413）**、真实子集 0.0957、最严聚合误杀 9 条、矛盾 55 判对 29/判 neutral 22——与 changelog 逐位一致，**无伪造**
- [x] 结论写回 ADR-0010（"kappa 复测 v2"节：数字表 + 归因 + 下一轮方向 ① 中文专用/更大 NLI ② 微调 ③ 两阶段拆句+保守门控 ④ HHEM 主裁判维持）；未达门槛如实标注、降级双轨维持

### WP-A2 图谱消融（§2 功能验收）
- [x] eval_runs id=27（mode=graph_only，fusion_mode=rrf）：Hit@5 **0.7333** / Recall 0.7286 / MRR 0.6752；id=28（mode=hybrid）：Hit@5 **0.9905** / Recall 0.9762 / MRR 0.9341——与 changelog 一致
- [x] `--ablate` 同跑 graph_only 0.7429 → hybrid 0.9810 = **+0.2381**；口径注明（rrf 三通道 vs 历史 hybrid 两通道 min-max 加权，仅参考不可直接比）——changelog §3 + eval_runs fusion_mode 字段双重记录
- [x] id=27/28 与 --ablate 差 ±0.01 如实声明（图谱实体提取 LLM 运行间波动）
- [ ] **delta 严格未落库**（见 minor #3：AC"delta 落 eval_runs"字面未满足，数值可追溯）

### WP-A3 改写增益（§3 功能验收）
- [x] eval_runs id=29（eval_type='query_rewrite'，fixture=False，n=104）：原始 hit 0.9808/recall 0.9712/mrr 0.9287；delta **+0.0096 / +0.0048 / -0.0353**；improved 3 / worsened 10；skipped 8（dataset 112 − evaluated 104）；不充分子集 n=6 MRR -0.1944——与 changelog 一致
- [x] 结论诚实：rrf 饱和基线下改写无净收益（MRR 为负），生产分诊改写链路保留（护栏价值）不改默认

### WP-A4 RRF k 扫描（§4 功能验收）
- [x] `eval/benchmark_rrf_k.py`（新）：K_VALUES 20-100 步长 10 + 最优 k ±5 拐点加密；三通道候选每题只收集一次、逐 k 纯 Python 融合（效率设计成立）；fuse_rrf 与 retriever._fuse_rrf 公式一致（独立实现 + 8 项单测）
- [x] eval_runs id=30（eval_type='rrf_k_scan'）：k=20-100 三通道 Hit@5 **全平坦 0.9810**、两通道 0.9714、**图谱净增益 +0.0096**、k60=0.981——与 changelog 一致
- [x] 最优 k 结论：k 不敏感，k=60 保持不改默认，**无需测试适配**（生产代码零改动，test_rrf_fusion 断言不变）
- [ ] 拐点加密仅补 k=25（见 minor #5）；图谱空候选 24/112 未落库（仅 changelog）

### WP-A5 飞轮冒烟（§5 功能验收）
- [x] **feedback 表 DB 实查 6 行**：identity=203.0.113.66（XFF 注入匿名降级口径）、message_id 990001-990005（990001 二次提交落 2 行）、rating 交替 +1/-1/+1/-1/+1、2 条 comment（990002/990004，内容与问题匹配）、created_at 正常——与 changelog 逐项一致
- [x] 自造 5 条知识库问题（G1 核心创新 / Kafka 不丢消息 / volatile 原子性 / RDB vs AOF / HashMap 树化）均属知识库域内问题（非闲聊）
- [x] 防重复如实记录：后端无幂等（module-048 设计如此）→ 同 message_id 落库 2 行；防重机制 = 前端已评态（localStorage `rag_feedback_rated`，ChatMessage.tsx:57 实查确认）；不改生产行为
- [x] message_id 构造标识 990000+i 声明（AI 层直连无 Java 消息主键）；rating=0 → 422 拦截（feedback 表无 rating=0 行，无污染）
- [x] 冒烟数据保留为飞轮种子（changelog 注明）；服务已停止（8001 无监听实查）

### §6 降级验收 / §7 接口兼容 / §8 测试验收
- [x] 复测 <0.7 → 如实标注 + 方向（ADR-0010 下一轮方向完整）
- [x] 全量 pytest **740 passed / 0 failed**（700 基线 + 40 新增），独立复跑一致；存量测试零改动（git diff 确认无存量测试文件被 module-057 修改；test_golden_intent.py 变更为 module-056 遗留，见观察 2）
- [x] 不改生产 verify_answer / 检索默认行为（生产代码零改动，k=60 保持）；retest_nli / golden_retrieval / golden_query_rewrite 既有接口兼容（纯新增函数 + 参数扩展）

### §9 文档验收（含记忆硬性约束）
- [x] changelog.md（5 硬数字 + 口径声明 + 诚实边界 §9）；review-report（本文件）/ test-report 待 Tester
- [x] **memory/project-context.md**：module-057 行（行 75）+ 头部日期（2026-08-12 module-057 完成）+ ADR-010 索引行 + 迭代状态——全部就位
- [x] **memory/agent-activity-log.md**：Developer [CODE] 行已追加（本 Reviewer 行由本文件追加）
- [x] **memory/file-index.md**：5 新行（benchmark_rrf_k.py / flywheel_smoke.py / test_nli_improve.py / test_benchmark_rrf_k.py / specs 目录）
- [x] ADR-0010 状态更新（复测 v2 节完整）
- [x] 开工前已读 project-context（changelog 第 4 行注明）
- [x] 文档类（简历/弹药）零改动；前端零改动；未 git commit

## 3. 诚实性核查（重点）

| 数字 | 声明 | 独立核验 |
|------|------|----------|
| kappa 0.4311（全量 110 对） | changelog/ADR/project-context | ✅ per_question 重算一致 |
| kappa 0.3754（同口径旧 80 对，-0.1413） | changelog/ADR | ✅ 重算 0.3754；same_set_scan 逐阈值全部 < 0.5167 |
| 真实子集 0.0957 / 误杀 9 条 / 矛盾 55 判对 29 | changelog/ADR | ✅ 三者全部重算一致 |
| 图谱 +0.2381（--ablate）| changelog | ✅ id=27/28 单模式落库支撑（0.7333→0.9905），±0.01 波动已声明 |
| 改写 +0.0096 / MRR -0.0353 | changelog | ✅ id=29 scores 逐位一致 |
| k 全平坦 0.9810 / 两通道 0.9714 / +0.0096 | changelog | ✅ id=30 curve 一致 |
| feedback 6 行（身份/rating/comment/created_at）| changelog | ✅ feedback 表实查逐项一致 |

**改进不成立（负结果）如实呈现**：kappa 低于基线、MRR 为负、k 无最优、后端无幂等——全部如实标注，未美化；"矛盾最严聚合误杀"量化并写入 ADR 下一轮方向。诚实性 ✅。

## 4. 主要发现（major）

无。

## 5. 次要发现（minor，非阻塞）

1. **changelog/file-index 单测计数不一致**（`changelog.md` §1 WP-A6"新增 38 项单测"、§7"test_nli_improve.py 30 项"；`file-index.md`"30 项"）——`pytest --collect-only` 实查 **40 项 = test_nli_improve 32 + test_benchmark_rrf_k 8**。project-context 与 activity log 的"40/32"正确。建议 changelog 与 file-index 修正为 32/8/40。
2. **eval_runs 重复落库**：id=25 与 id=26 均为 nli_retest_v2 且 scores 完全一致（id=25 为初版无 same_set_scan，id=26 为增强版）；changelog 仅引 id=26，id=25 未说明（activity log 有提"初版/增强版"）。建议 changelog 补一句说明，避免后续读 eval_runs 困惑。
3. **WP-A2"delta 落 eval_runs"字面未满足**：+0.2381 未持久化（--ablate 不落库是 module-038 既有行为，delta 由 changelog/ADR 派生记录；id=27/28 亦无 delta 字段）。数值诚实可追溯，建议后续若重跑 --ablate 将 delta 一并落库。
4. **"最优阈值配置化"字面未满足**（AC §1）：最优阈值在脚本内自动选取 + `--threshold` 可固定，但未入 `src/config.py`。鉴于复测结论为负（无生产接线需求）且本模块为评估侧，合理；如实记录为字面差距。
5. **拐点加密仅补 k=25**（best_k=20±5 的范围内只有 25 合法），未扫 35/45/55/65/75/85/95；曲线全平坦故无实际影响，但"拐点加密"名不副实；另"图谱通道空候选 24/112"仅 changelog 记录未落 eval_runs。

## 6. 观察（非本模块）

1. 工作树存在 **module-056 遗留未提交改动**：`ai_service/agent/router.py`（docstring 口径同步）、`ai_service/tests/test_golden_intent.py`（TestRunCompareClassifier 契约）、`specs/module-033-long-term-memory/changelog.md`（审查期间跨模块缺陷清单附录）——均为 module-056 内容非本模块写入，主会话统一提交时注意区分。
2. 历史未跟踪产物：`eval/faithfulness.json`、`eval/golden_expanded.json`（2026-08-07 时间戳，module-038 时期）、根目录 `module-033-loop.js`——非本模块产生，建议后续清理。
3. 头条 A2 数字 +0.2381 取 --ablate 同跑（0.7429→0.9810，未落库），与落库的 id=27/28（0.7333→0.9905 = +0.2572）差约 ±0.01——changelog 已如实声明波动来源，审阅无异议。

## 7. 结论

**✅ 通过（pass）**：5 个硬数字全部 DB 独立核验一致（含 per_question 重算），负结果如实呈现无伪造；句级拆解/聚合/阈值/样本扩充/同口径复测方法学符合 plan；全量 pytest 740/0 独立复跑；记忆三文件硬约束就位；前端/简历/弹药零改动。0 阻塞，5 项 minor（计数修正 + 落库完善类）+ 3 项观察。**Tester 放行提示**：验收重点复验 WP-A5 链路（可在保留种子数据前提下另造身份验证）与全量 pytest。
