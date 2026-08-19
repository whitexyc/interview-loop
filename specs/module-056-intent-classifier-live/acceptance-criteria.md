# 验收标准 — Module-056: L4 意图分类器启用

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-1 数据扩充）

- [ ] 📋 `eval/intent_train_dataset.json` 存在：≥300 条人造标注（三类平衡：每类 ≥80 条）
- [ ] 📋 边界易混样本 ≥30 条（"你们网站有什么功能"类 + E2E bug 类"G1垃圾收集器的核心创新是什么？"）
- [ ] 📋 专有术语+疑问句 ≥30 条（G1/JVM/Redis/GC 等）+ 口语化无术语知识问题 ≥20 条
- [ ] 📋 JSON 结构 `[{"query", "intent"}, ...]` 可被训练脚本加载；构造脚本含标注指南 docstring
- [ ] 📋 人造数据声明（非真实用户对话）入 changelog

## 2. 功能验收（WP-2 重训）

- [ ] 📋 `train_intent_classifier.py` 接入新数据集（优先级最高），训练/评测分离（golden_intent 100 条不动防泄漏）
- [ ] 📋 输出新 Accuracy/混淆矩阵/每类 P/R/F1，与旧 0.89 对比（提升或如实标注）
- [ ] 📋 模型落盘 `models/intent_clf.joblib`（训练产物不进仓库）

## 3. 功能验收（WP-3 真实对比）

- [ ] 📋 golden_intent 真实模式：LLM vs 分类器同 100 条对比（Accuracy/每类 P/R/F1/混淆矩阵）
- [ ] 📋 重点看 knowledge Recall（漏检率）；分类器结果入 eval_runs
- [ ] 📋 LLM 不可用 → 记 skipped，分类器单侧（如实声明）

## 4. 功能验收（WP-4 启用判定）

- [ ] 📋 达标线明确（建议 Accuracy ≥0.95 且 knowledge Recall ≥0.95 且 casual/realtime F1 ≥0.9）——数据决定
- [ ] 📋 达标 → `PW_INTENT_CLASSIFIER_ENABLED` 默认开（config）+ 保留开关可回退
- [ ] 📋 未达标 → 保持关闭 + 如实标注差距与扩充方向（不硬切）
- [ ] 📋 分类器加载失败/推理失败 → 回退 LLM 分类（已有设计，测试断言）
- [ ] 📋 真实 HTTP 冒烟：启用后 chat 正常（分类器路径 + 失败回退路径）

## 5. 降级验收

- [ ] 📦 分类器不可用 → LLM 回退零影响
- [ ] 📦 重训不达标 → 保持关闭如实标注
- [ ] 📦 全量 pytest 688 全绿保持

## 6. 接口兼容

- [ ] 🔌 router classify 返回结构不变（intent/confidence/reason）
- [ ] 🔌 ChatResponse / 前端零改动
- [ ] 🔌 LLM 分类路径保留（回退用），行为不变

## 7. 测试验收

- [ ] 🧪 tests/test_intent_dataset.py：数据集结构/类别平衡/边界样本存在性/训练集评测集分离断言
- [ ] 🧪 分类器加载/推理失败回退 LLM（mock）测试
- [ ] 🧪 python -m pytest tests/ -q — 全量 688+ 全绿（不改存量测试掩盖）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含重训数字 + 真实对比 + 启用/未启用决定）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-056 行** + 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0003 状态更新（L4 启用/未启用 + 数据量）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
- [ ] 📝 文档类（简历/弹药）**不改**（用户指示：等优化完成后进行）
