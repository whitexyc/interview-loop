# 测试报告 — Module-056: L4 意图分类器上岗（人造标注扩充 → 重训 → 真实评测达标 → 启用）

> Tester | 2026-08-12
> **结论：✅ 验收通过（AC 32/32 全过，0 阻塞）**

---

## 1. 全量回归

| 项 | 结果 |
|----|------|
| 命令 | `python -m pytest tests/ -q`（ai_service 目录，独立复跑） |
| 结果 | **700 passed / 0 failed**，149.17s，6 存量 warning（SQLAlchemy 连接池清理 SAWarning 等，与模块无关） |
| 口径 | 688 基线 + 11 新增（test_intent_dataset.py）+ 1 新增（test_golden_intent.py TestRunCompareClassifier）——与 changelog §9、Reviewer 复跑（700/0，175.81s）逐字一致；存量测试零改动 |
| 定向抽查 | `tests/test_intent_dataset.py` + `tests/test_golden_intent.py` **23/23 passed**（47.80s）——含数据集结构/三类平衡/边界 32/术语 40/口语化 24/E2E bug query 存在/query 唯一、训练/评测分离三断言（新数据集优先 + golden.json 全量进入 + 评测集 casual/realtime 零泄漏 + 训练脚本无 load_golden_intent_samples/_BUILTIN_SAMPLES）、L4 回退三路径（load 失败→LLM / 推理失败→LLM / 可用→不调 LLM）、--compare-classifier 钉住+恢复断言 |

---

## 2. 冒烟复跑（真实栈：bge-m3 本地嵌入 + deepseek LLM）

### 2.1 冒烟 1 — 分类器真实加载 + 预测（概率和 = 1）

| query | intent | probs（round 4 位） | 原始 softmax 和 |
|-------|--------|---------------------|-----------------|
| G1垃圾收集器的核心创新是什么？（E2E bug 类） | **knowledge** | casual 0.0464 / **knowledge 0.9159** / realtime 0.0378 | 1.0000000000 |
| 你好呀 | **casual_chat** | **casual 0.9414** / knowledge 0.0258 / realtime 0.0328 | 1.0000000000 |
| 现在几点了？ | **realtime** | casual 0.1245 / knowledge 0.0354 / **realtime 0.8401** | 1.0000000000 |

- G1 **0.9159** 与 changelog §6.1 冒烟数字**逐位一致**；你好呀 0.9414 与 changelog §5/Reviewer 一致。
- 原始 proba 精确和为 1（softmax 契约）；产品层 round 到 4 位后 1.0001 属舍入噪声（<1e-3），判定"概率和为 1"成立。
- 观察（非缺陷）：realtime query 概率 0.8401 vs Reviewer 首轮 0.8231——决策同为 realtime，差异源于模型落盘时间不同，非逻辑缺陷。

### 2.2 冒烟 2 — 失败回退 LLM（真实 DeepSeek）+ 启用态确认

- **回退路径**：注入 load=False 桩分类器（启用态）→ `router.classify("什么是G1垃圾收集器？")` → `intent=knowledge / confidence=1.0 / reason="用户询问G1垃圾收集器的定义，属于专业知识查询。"`（真实 LLM 语义理由，无 L4 标记）——加载失败回退 LLM 零影响 ✅
- **启用态确认**（无环境变量）：`settings.intent_classifier_enabled=True`（默认）；`router.classify(G1 query)` 真实走 L4 路径，reason=`L4 classifier {...}`、conf=0.9159——默认启用生效、分类器为决策主体 ✅

### 2.3 冒烟 3 — 重训数字与 changelog 一致性（--no-save 复现）

| 项 | changelog 声明 | Tester 复现 | 一致 |
|----|----------------|-------------|------|
| 训练样本 | 449 条（casual 105 / knowledge 244 / realtime 100） | 449 条（105/244/100） | ✅ |
| test split Accuracy | 1.0000（90 条） | **1.0000** | ✅ |
| 混淆矩阵 | [[13,0,0],[0,57,0],[0,0,20]] | [[13,0,0],[0,57,0],[0,0,20]] | ✅ |

### 2.4 Reviewer P1 放行验证 — `--compare-classifier --no-save` 启用默认下真实重跑

| 指标 | LLM 侧 | 分类器侧 |
|------|--------|----------|
| Accuracy | **1.0000**（100 条） | **1.0000**（100 条） |
| casual_chat P/R/F1 | 1.0000/1.0000/1.0000 | 1.0000/1.0000/1.0000 |
| knowledge P/R/F1 | 1.0000/1.0000/1.0000 | 1.0000/1.0000/1.0000 |
| realtime P/R/F1 | 1.0000/1.0000/1.0000 | 1.0000/1.0000/1.0000 |
| knowledge Recall | 1.0000 | 1.0000 |
| 混淆矩阵 | 全对角（30/50/20，0 误判） | 全对角（30/50/20，0 误判） |

- 钉住生效：LLM 侧运行期间 `intent_classifier_enabled` 被钉住 False（单测 TestRunCompareClassifier 断言两次 run_eval 均观测到 False + finally 恢复原值，已通过）+ Reviewer 进程验证（钉住态 reason 为 LLM 语义理由而非 "L4 classifier"）——**"LLM vs 分类器"对比非自污染**，重跑数字与 changelog id=23/24 一致。
- 本跑使用 --no-save，未污染 eval_runs 历史记录（id=23/24 保持原状）。

---

## 3. 数据与实现抽查（对照 changelog）

| 项 | changelog 声明 | 实查 | 一致 |
|----|----------------|------|------|
| 数据集总量 | 337 条 | 337 条 | ✅ |
| 类别分布 | knowledge 132 / casual 105 / realtime 100 | 132/105/100（各 ≥80） | ✅ |
| 边界易混 | 32（含 E2E bug 类 1） | 32（31 "边界易混" + 1 "边界易混 E2E bug 类"） | ✅ |
| 专有术语 | 40 | 40 | ✅ |
| 口语化 | 24 | 24 | ✅ |
| E2E bug query | "G1垃圾收集器的核心创新是什么？" 标 knowledge | 存在，intent=knowledge，note="边界易混 E2E bug 类" | ✅ |
| query 唯一 | 是 | 337 全唯一 | ✅ |
| 与 golden_intent 评测集重叠 | 字符串零重叠 | **0 重叠**（knowledge/casual/realtime 三类均 0） | ✅ |
| golden.json 并入 | 112 题 | 112 题全部进入训练（union 449 = 337+112，无字符串交叉） | ✅ |
| 训练/评测分离 | load_golden_intent_samples/_BUILTIN_SAMPLES 移除 | 代码核对 + 测试断言（test_train_script_no_longer_reads_golden_intent） | ✅ |
| 启用开关 | intent_classifier_enabled 默认 true（config.py L115 + 达标注释） | 默认 True，无环境变量独立进程验证 | ✅ |
| 模型落盘 | models/intent_clf.joblib（gitignored 不进仓库） | 存在且可真实加载 | ✅ |
| 钉住修复 | golden_intent.py L394-400 钉住 + L439-442 finally 双恢复 + record_eval_run 快照补 intent_classifier_enabled | 代码核对 + 单测 + 真实重跑 | ✅ |
| minor 修复 | router/intent_classifier docstring + changelog 量化 1/50 全等/23/50 余弦 + train 打印 | 代码核对一致 | ✅ |
| ADR-0003 | L4 已启用 + 337 条 + 数字 | 实查 specs/adr/0003-intent-validation.md L3/L6/L69-76 | ✅ |
| git 状态 | 未 commit（主会话统一提交） | HEAD 仍 eb40e16（module-055），变更未提交 | ✅ |
| 前端/简历/弹药 | 零改动 | git status 无相关文件 | ✅ |

---

## 4. AC 逐条对照（32/32 通过）

| AC | 标准 | 结果 | 依据 |
|----|------|------|------|
| §1-1 | intent_train_dataset.json ≥300 条、三类平衡各 ≥80 | ✅ | 337 条（132/105/100）；测试 + 实查 |
| §1-2 | 边界易混 ≥30（含 E2E bug 类 G1 query） | ✅ | 32 条（含 "G1垃圾收集器的核心创新是什么？" 标 knowledge + note）；测试 + 实查 |
| §1-3 | 专有术语+疑问句 ≥30 + 口语化无术语 ≥20 | ✅ | 术语 40 / 口语化 24 |
| §1-4 | JSON `[{"query","intent",...}]` 可加载；构造脚本含标注指南 docstring | ✅ | build_intent_dataset.py docstring 完整标注指南 + build 强制校验；训练脚本实际加载 337 条 |
| §1-5 | 人造数据声明（非真实用户对话）入 changelog | ✅ | changelog §2.3 三条声明 |
| §2-1 | 训练脚本接入新数据集（优先级最高），训练/评测分离 | ✅ | load_training_samples：人造集→golden.json；load_golden_intent_samples/_BUILTIN_SAMPLES 移除 + 测试断言；评测集字符串零重叠（实查） |
| §2-2 | 输出 Accuracy/混淆矩阵/每类 P/R/F1，与旧 0.89 对比 | ✅ | 重训复现 Accuracy **1.0000** vs 旧 0.89，混淆矩阵 [[13,0,0],[0,57,0],[0,0,20]] 与 changelog 逐位一致 |
| §2-3 | 模型落盘 models/intent_clf.joblib（不进仓库） | ✅ | 落盘存在、真实加载成功；gitignored |
| §3-1 | golden_intent 真实模式 LLM vs 分类器同 100 条（Accuracy/每类 P/R/F1/混淆矩阵） | ✅ | 启用默认下真实重跑双 **1.0000**、全对角；changelog eval_runs id=23/24 实查（Reviewer 已做） |
| §3-2 | knowledge Recall 重点；分类器结果入 eval_runs | ✅ | knowledge Recall 双 1.0000；eval_type='intent_classifier' 落库（id=24） |
| §3-3 | LLM 不可用 → skipped，分类器单侧 | ✅ | run_compare_classifier 启发式（闲聊/实时 0 命中 → [skip-decl] 仅分类器单侧落库）+ 模型缺失 → LLM 单侧，代码核对 |
| §4-1 | 达标线明确（Acc ≥0.95 且 knowledge Recall ≥0.95 且 casual/realtime F1 ≥0.9） | ✅ | plan/AC 定义；实测 1.0000/1.0000/1.0000 全过 |
| §4-2 | 达标 → PW_INTENT_CLASSIFIER_ENABLED 默认开 + 保留开关 | ✅ | config.py L115 默认 True（无环境变量独立进程验证）；PW_INTENT_CLASSIFIER_ENABLED=false 回退注释保留 |
| §4-3 | 未达标 → 保持关闭 + 如实标注差距（不硬切） | ✅ | 达标未触发该分支；机制（数据决定 + 诚实边界声明 changelog §5.2/§2.3）在案 |
| §4-4 | 分类器加载/推理失败 → 回退 LLM（测试断言） | ✅ | TestL4Fallback 3 用例（load 失败/predict 失败/可用不调 LLM）+ 真实 DeepSeek 回退冒烟 |
| §4-5 | 真实 HTTP 冒烟：分类器路径 + 失败回退路径 | ✅ | changelog §6（uvicorn 8001：G1→knowledge conf 0.9159 + 你好呀→casual；模型改名→LLM 回退 200）；本报告冒烟 2 进程级复验 |
| §5-1 | 分类器不可用 → LLM 回退零影响 | ✅ | 冒烟 2 真实回退 + 单测 |
| §5-2 | 重训不达标 → 保持关闭如实标注 | ✅ | 达标未触发；降级设计在 plan §3.3 与 changelog 声明 |
| §5-3 | 全量 pytest 688 全绿保持 | ✅ | **700 passed / 0 failed**（149.17s） |
| §6-1 | router classify 返回结构不变（intent/confidence/reason） | ✅ | L4 路径返回同构（intent/confidence/reason="L4 classifier {probs}"）；diff 核对 |
| §6-2 | ChatResponse / 前端零改动 | ✅ | git status 无前端文件 |
| §6-3 | LLM 分类路径保留（回退用），行为不变 | ✅ | classify LLM 分支保留 + 回退冒烟真实调用 |
| §7-1 | test_intent_dataset.py：结构/平衡/边界/分离断言 | ✅ | 11 项全绿（结构/三类≥80/边界/术语/口语化/E2E/唯一/分离三断言） |
| §7-2 | 分类器加载/推理失败回退 LLM（mock）测试 | ✅ | TestL4Fallback 3 项全绿 |
| §7-3 | python -m pytest tests/ -q 全量 688+ 全绿（不改存量测试掩盖） | ✅ | 700/0；存量测试零改动（git diff 核对 + conftest autouse 钉住为新增夹具） |
| §8-1 | changelog/review-report/test-report（重训数字 + 真实对比 + 启用决定） | ✅ | changelog §3/§4/§5、review-report §2/§7、本报告 |
| §8-2 | project-context.md 模块清单 module-056 行 + 头部日期 | ✅ | 行 74 格式对齐 + 头部"2026-08-12（module-056 完成 + Review 修复）" |
| §8-3 | agent-activity-log.md：Dev/Rev/Test 各追加活动行 | ✅ | Developer[CODE]/Reviewer/Developer[FIX]/Reviewer-2 四行在案 + **Tester 行本次追加** |
| §8-4 | file-index.md 新文件行（只追加） | ✅ | 5 新行（build_intent_dataset.py / intent_train_dataset.json / test_intent_dataset.py / intent_clf.joblib / specs 目录） |
| §8-5 | ADR-0003 状态更新（L4 启用 + 数据量） | ✅ | 实查 specs/adr/0003-intent-validation.md（L4 已启用 + 337 条 + 数字） |
| §8-6 | 开工前必读 project-context.md（changelog 注明） | ✅ | changelog 头部"开工前已读…✅" |
| §8-7 | 文档类（简历/弹药）不改 | ✅ | git status 无相关文件 |

---

## 5. 记忆文件硬核查（硬性约束）

| 文件 | 要求 | 核查 |
|------|------|------|
| memory/project-context.md | module-056 行存在且格式对齐 + 头部"最后更新"日期 | ✅ 行 74（含 Review 修复说明，格式与相邻行对齐）+ 行 7 日期"2026-08-12（module-056 完成 + Review 修复）"+ ADR 索引行 adr-003 更新 |
| memory/agent-activity-log.md | Developer/Reviewer/Tester 各一条 | ✅ Developer[CODE]（行 141）+ Reviewer（行 142）+ Developer[FIX]（行 143）+ Reviewer-2（行 144）+ **Tester（行 145，本次追加）** |
| memory/file-index.md | 新文件行（只追加） | ✅ 5 新行（行 80-84） |

---

## 6. 非阻塞观察（不影响验收）

1. realtime query "现在几点了" 分类器概率 0.8401 vs Reviewer 首轮实测 0.8231——决策同为 realtime，差异源于模型落盘时间不同，非缺陷（changelog 未声明该数字，仅 Reviewer 进程内记录）。
2. 产品层 predict_proba round 4 位后概率和 1.0001（原始 softmax 精确为 1）——四舍五入噪声，契约"和为 1"在原始层成立。
3. 全量 6 个 SAWarning（SQLAlchemy 连接池清理告警）为存量，与模块无关。
4. 环境备注（沿用 changelog §9）：仓库根 `python -m pytest -q` 会额外收集 scripts/test_models.py（module-004 遗留）导致集合错误——既有环境性产物，本模块全量口径沿用 `tests/` 目录。

---

## 7. 结论

全量回归 700/0 全绿、三类冒烟（真实加载预测 / 失败回退 / 重训复现）全部 PASS、--compare-classifier 启用默认下真实重跑确认钉住生效（LLM vs 分类器对比非自污染）、数据/实现与 changelog 逐项一致、记忆文件硬核查齐全。**AC 32/32 通过，模块标记 ✅ 完成。**
