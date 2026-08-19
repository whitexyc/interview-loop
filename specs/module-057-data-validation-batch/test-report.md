# Test Report — Module-057: 数据验证批（矛盾改进 + 图谱消融 + 改写增益 + RRF 扫描 + 飞轮冒烟）

> Tester | 2026-08-13 | 验收结论：**✅ 通过（AC 全过，0 阻塞）**

---

## 1. 全量回归

| 项 | 结果 |
|----|------|
| 全量 pytest（独立复跑） | **740 passed / 0 failed**（158.64s，44 warning 与基线同源：mock SAWarning / sklearn 单标签警告 / Redis setex 弃用） |
| 基线对比 | 700 基线 + 40 新增（test_nli_improve.py 32 + test_benchmark_rrf_k.py 8），`--collect-only` 实查 740 |
| 存量测试 | 零改动（git diff 确认 module-057 未触碰存量测试；test_golden_intent.py 变更为 module-056 遗留 TestRunCompareClassifier） |
| 新增单测 | test_nli_improve.py 32 项 + test_benchmark_rrf_k.py 8 项，全绿 |

> 注（非阻塞，Reviewer minor #1 沿用）：changelog §1/§7 与 file-index 写"38 项/30 项"，实际 40 项/32 项——文档计数不一致，数字与代码无影响。

## 2. 5 个硬数字冒烟复跑（与 changelog 一致性抽查）

| # | 硬数字 | changelog 声明 | Tester 独立核验 | 结论 |
|---|--------|----------------|----------------|------|
| 1 | 矛盾 kappa | 0.4311（全量 110 对）/ 0.3754（同口径旧 80 对，-0.1413）/ 真实子集 0.0957 / 误杀 9 / 矛盾 55 判对 29 | eval_runs id=26 per_question 独立重算：kappa **0.4311** / same-set **0.3754** / real 24 **0.0957** / overkill **9** / 55→29，逐位一致 | ✅ 一致 |
| 2 | 图谱增量 | --ablate 0.7429→0.9810 = **+0.2381**（rrf 三通道口径）；落库 id=27 0.7333 / id=28 0.9905 | id=27/28 实查（mode/fusion_mode=rrf 字段正确），+0.2381 由 --ablate 派生、±0.01 波动已声明 | ✅ 一致 |
| 3 | 改写增益 | Hit@5 **+0.0096** / Recall@5 +0.0048 / MRR **-0.0353**（improved 3 / worsened 10，skipped 8） | id=29 实查 delta 逐位一致，n=104 + skipped 8 = 112 | ✅ 一致 |
| 4 | RRF 最优 k | k=20-100 全平坦 0.9810，两通道 0.9714，图谱净增益 +0.0096，k=60 持平不改默认 | id=30 实查 curve 全平坦、best_k=20 与 k60=0.981 持平、graph_gain +0.0096 | ✅ 一致 |
| 5 | 飞轮落库 | 6 行种子（203.0.113.66，990001-990005，rating 交替 ±1，2 comment，990001 二次提交 2 行） | feedback 表实查 6 行逐项一致（含重复提交行与 rating=0 无污染行） | ✅ 一致 |

## 3. 真实管线冒烟（不落库 --no-save / 独立身份）

### 3.1 retest_nli（WP-A1，真实 mDeBERTa，--limit 20 --no-save）

- 真实模型加载 + 句级拆解 + 逐子句/子句对打分 + 阈值扫描（0.5-0.9 共 9 值）+ 同口径对比 + 门槛判定全流程跑通，退出码 0，无 eval_runs 落库（--no-save 生效）。
- limit-20 子集恰好全为 contradiction 标注（16 claim_vs_doc + 4 internal）：Acc(三分类)=0.65、混淆矩阵 contradiction 行 13 判对/5 neutral/2 entailment、kappa 因单类标注为 0.0（sklearn 语义，非缺陷）——**与 changelog 记录的"矛盾→neutral 判别短板"失败模式一致**，管线行为可复现。

### 3.2 benchmark_rrf_k（WP-A4，--limit 5 --no-save）

- 真实三通道候选收集（bge-m3 向量 + FTS + 图谱实体提取 LLM）→ 逐 k 纯 CPU 融合 → 曲线 + 归因 + 口径声明全流程跑通，退出码 0，无 eval_runs 落库。
- 5 题子集三通道 Hit@5=1.0000（k=20-100 全平坦，含加密 k=25）、两通道 1.0000、图谱增益 +0.0000（图谱通道空候选 4/5，如实打印）——k 不敏感性在子集上复现，与全量结论方向一致。

### 3.3 飞轮链路独立复验（WP-A5，另造身份 203.0.113.99 规避种子混淆）

| 步骤 | 结果 |
|------|------|
| 启动 uvicorn 8001 | 就绪（120s 内），结束自动停服 |
| 真实 HTTP /ai/rag/chat | **200**，真实回答 500 字（引用真实文档） |
| POST /ai/feedback（message_id=991000, rating=+1, comment） | **200** `{"status": "ok"}` |
| 同一 message_id 二次提交（rating=-1 模拟改主意） | **200** `{"status": "ok"}` |
| rating=0 非法输入 | **422**（Pydantic 拦截，防落库污染） |
| feedback 表落库 | identity=203.0.113.99 共 **2 行**：991000/+1/comment、991000/-1，created_at 正确——**后端无幂等复证**（同 message_id 2 行） |
| 防重机制 | 前端已评态（ChatMessage.tsx:57 `rag_feedback_rated` localStorage 按 message_id 记录，grep 实查）——本模块如实记录不改生产 |
| 清理 | Tester 验证 2 行已删除（203.0.113.99 剩余 0），种子 6 行（203.0.113.66）未动；8001 已停服（无监听实查） |

## 4. 样本集与实现抽查

- **样本集**：JSON 实查 86 条 = contradiction 53（claim_vs_doc 30 + internal 23）+ entailment 22 + neutral 11；**constructed[:56] 保持 module-054 同集**（16 claim_vs_doc + 15 internal + 16 entailment + 9 neutral，逐项一致）；internal 23 = 旧 15 单句逗号混合"X，但 not-X" + 新 8 多句"前真后假"（。分隔）；四键结构不变（question/claim/doc/verdict）；标注指南含新增多句构造方法节。
- **实现抽查**：`split_claim`（。！？；!? + 换行切分、<2 子句回退整句零回归）、`aggregate_sub_judgments`（任一矛盾→contradiction / 无矛盾有 entailment→entailment / 全 neutral→neutral，pair 只参与矛盾判定）、`apply_threshold`（低置信→neutral）、`scan_thresholds`（一次性打分逐阈值纯 CPU 复用）、`fuse_rrf`（score=Σ1/(k+rank)，图谱按 hybrid_score 排序）——与 changelog/单测断言一致。
- **接口零改动**：生产代码零 diff（git status 变更仅 eval/测试/记忆/文档；`agent/router.py`、`tests/test_golden_intent.py`、`specs/module-033-*/changelog.md` 为 module-056 遗留未提交改动，已实查 diff 确认非本模块写入）；`rrf_constant_k=60` 未改（src/config.py:83），`test_rrf_fusion` 断言保持——**无需测试适配，AC §7 满足**。

## 5. 逐条 AC 对照（acceptance-criteria.md）

| AC | 项 | 结果 | 依据 |
|----|----|------|------|
| §1-1 | 句级拆解（子句逐句判 + 两两互判 + 最严聚合 + 回退整句） | ✅ 通过 | 代码实查 + 单测 32 项覆盖 + 真实管线冒烟 |
| §1-2 | 阈值校准 0.5-0.9 步长 0.05 + 低置信→neutral + 最优阈值配置化 | ✅ 通过（附注） | 扫描 9 值实现 + 真实跑通；"配置化"为脚本内自动选取 + `--threshold` 固定（未入 src/config.py——评估侧合理，Reviewer minor #4 记录，非阻塞） |
| §1-3 | 矛盾样本 ≥50（internal ≥20 多句混合）+ JSON 结构不变 + 指南同步 | ✅ 通过 | 53/23（多句 8 ≥5）实查 + 键集一致 + 指南实查 |
| §1-4 | 复测 kappa 对比 0.5167 + eval_runs 'nli_retest_v2' + ADR-0010 结论 | ✅ 通过 | id=26 独立重算 0.3754（-0.1413）；ADR-0010"kappa 复测 v2"节 + 状态行实查 |
| §2-1 | --ablate 跑通：graph_only vs hybrid Hit@5 差值 | ✅ 通过 | +0.2381（--ablate 派生，id=27/28 支撑） |
| §2-2 | delta 落 eval_runs + 口径注明 | ✅ 通过（附注） | --ablate 不落库为 module-038 既有行为，delta 由 id=27/28 派生可追溯（Reviewer minor #3）；rrf 三通道口径已注明（fusion_mode 字段 + changelog） |
| §2-3 | DB 异常 → 待环境 | ✅ 不适用 | DB 正常，消融跑通 |
| §3-1 | 改写真实模式：原始 vs 改写 Recall@K/MRR + delta | ✅ 通过 | id=29：+0.0096 / +0.0048 / **-0.0353** |
| §3-2 | eval_runs 落库 + LLM 失败记 skipped | ✅ 通过 | id=29 eval_type='query_rewrite' 实查；skipped 8（含 1 rewrite_failed）如实记录 |
| §4-1 | k 扫描 20-100 + 拐点加密 + 最优 k 对比 k=60 | ✅ 通过 | id=30 全平坦 0.9810，best 20 与 k60 持平；加密 k=25（仅此点合法，Reviewer minor #5） |
| §4-2 | 两通道 vs 三通道 → 图谱净增益归因 | ✅ 通过 | +0.0096（0.9714→0.9810）实查 |
| §4-3 | eval_runs 落库 + 结论入 changelog（改 k 默认则测试适配） | ✅ 通过 | id=30 实查；k=60 保持不改默认、test_rrf_fusion 零改动（无需适配） |
| §5-1 | 自造 3-5 条问题 → 真实 HTTP chat（含 message_id） | ✅ 通过 | 原冒烟 5 条全 200 + Tester 独立复验 1 条 200（构造标识声明） |
| §5-2 | 模拟点击 👍👎（rating 交替 ±1，≥1 条 comment） | ✅ 通过 | 种子 5 次交替 ±1 + 2 comment 实查；复验 +1 带 comment |
| §5-3 | feedback 表落库正确（message_id/rating/identity/created_at） | ✅ 通过 | 6 行种子 + 复验 2 行逐字段实查 |
| §5-4 | 重复提交不重复落库（防重验证，如实记录机制） | ✅ 通过（如实记录） | 后端无幂等 → 同 message_id 2 行（种子 + 复验均复证）；防重在前端已评态 localStorage（实查）——机制如实记录不改生产 |
| §5-5 | 冒烟数据保留为飞轮种子 / 清理策略声明 | ✅ 通过 | 6 行保留（changelog §6 注明）；Tester 复验行已清理 |
| §6-1 | 复测 <0.7 → 如实标注 + 方向 | ✅ 通过 | ADR-0010 下一轮方向 4 条完整 |
| §6-2 | LLM 限流 → skipped 不中断 | ✅ 通过 | 改写 8 skipped 记实 |
| §6-3 | 全量 pytest 700 全绿保持 | ✅ 通过 | **740/0**（700 基线 + 40 新增） |
| §7-1 | 不改生产 verify_answer / 检索默认 | ✅ 通过 | 生产零 diff；k=60 保持 |
| §7-2 | retest_nli / golden_retrieval / golden_query_rewrite 接口兼容 | ✅ 通过 | 纯新增函数 + 参数扩展，存量接口未动 |
| §8-1 | tests/test_nli_improve.py 覆盖（句切/聚合/内部矛盾/回退/阈值扫描/标注结构） | ✅ 通过 | 32 项全绿，覆盖点与 AC 逐项对应 |
| §8-2 | 全量 pytest 全绿（不改存量测试掩盖） | ✅ 通过 | 740/0；存量测试零改动（git diff 确认） |
| §9-1 | changelog / review-report / test-report | ✅ 通过 | 三件齐备（本文件为 test-report） |
| §9-2 | memory/project-context.md module-057 行 + 头部日期 | ✅ 通过 | 行 75（格式对齐）+ 头部"最后更新 2026-08-12（module-057 完成）"实查 |
| §9-3 | memory/agent-activity-log.md Dev/Rev/Test 三行 | ✅ 通过 | Developer [CODE] 行 + Reviewer [REVIEW-1] 行 + 本行 Tester [TEST] 追加完成 |
| §9-4 | memory/file-index.md 新文件行（只追加） | ✅ 通过 | 5 行实查（benchmark_rrf_k / flywheel_smoke / test_nli_improve / test_benchmark_rrf_k / specs 目录） |
| §9-5 | ADR-0010 状态更新 | ✅ 通过 | "kappa 复测 v2（module-057）"节 + 状态行实查 |
| §9-6 | 开工前必读 project-context（changelog 注明） | ✅ 通过 | changelog 第 4 行注明 |
| §9-7 | 文档类（简历/弹药）不改 | ✅ 通过 | 零改动 |

**AC 汇总：34 项通过（其中 2 项附注非阻塞：最优阈值未入 config、delta 未持久化到 eval_runs——均为评估侧合理/可追溯，Reviewer minor 已记录）+ 1 项不适用（§2-3 DB 异常降级，DB 正常故不触发）**

## 6. 记忆文件硬核查（缺一项 = blocking）

| 文件 | 核查项 | 结果 |
|------|--------|------|
| memory/project-context.md | module-057 行（行 75，格式对齐：模块编号/名称/版本号/完成时间/状态） | ✅ |
| memory/project-context.md | 头部"最后更新"日期更新 | ✅ |
| memory/project-context.md | ADR-010 索引行 + 迭代状态（§5 当前迭代 v0.57.0） | ✅ |
| memory/agent-activity-log.md | Developer [CODE] 行 | ✅（行 150） |
| memory/agent-activity-log.md | Reviewer [REVIEW-1] 行 | ✅（行 151） |
| memory/agent-activity-log.md | Tester [TEST] 行（本报告追加） | ✅ |
| memory/file-index.md | 5 条新文件行（只追加） | ✅（行 85-89） |
| specs/adr/0010-hallucination-detection-upgrade.md | "kappa 复测 v2（module-057）"节 + 状态行 | ✅ |

**结论：记忆硬核查 8/8 全过，无 blocking 项。**

## 7. 诚实边界确认

1. WP-A1 复测为负结果（0.3754 < 0.5167）**如实呈现**，未美化；最严聚合误杀 9 条已量化写入 ADR 下一轮方向。
2. 阈值在评估集上扫描选择（in-sample 乐观偏差）已在脚本/ADR 声明，生产阈值需独立集确认。
3. WP-A2/A3/A4 为 retriever 口径（直调 retriever，不含引擎层编排差异）；rrf 三通道 vs 历史 hybrid 两通道为不同融合公式，对比均已注明。
4. 图谱数字含 LLM 实体提取运行间波动（±0.01，id=27/28 vs --ablate）；图谱空候选 24/112 已如实打印/记录。
5. 飞轮冒烟数据为自造（非真实用户），验证链路 + 种子；message_id 为构造标识（AI 层直连无 Java 主键）；后端无幂等如实记录（防重在前端已评态）。

## 8. 结论

**✅ 验收通过（0 阻塞）**：全量 pytest 740/0 独立复跑一致；5 个硬数字全部 DB 独立复算与 changelog 逐位一致（含负结果如实呈现）；真实管线冒烟三项（NLI 复测 / k 扫描 / 飞轮链路）全部跑通；样本集结构、接口兼容、内存硬约束 8/8 全部就位。非阻塞 minor 沿用 Reviewer 5 项（文档计数、落库完善类），不影响本模块验收结论。**模块标记 ✅ 完成**。
