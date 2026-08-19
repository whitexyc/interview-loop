# 功能规格说明书 — Module-056: L4 意图分类器启用（人造数据扩充 + 重训 + 达标切换）

> Planner | 2026-08-12

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-056 |
| 模块名称 | L4 意图分类器上岗：人造标注扩充 → 重训 → 真实评测达标 → 启用 |
| 版本号 | 0.56.0-module-056 |
| 优先级 | P0（用户指示"自己造一些数据，让分类器能用起来"；LLM 分类贵/慢/不稳定是 E2E bug 根源，分类器本地毫秒级是治本） |
| 预估代码量 | 数据构造 + 评测对比 + 配置 + 测试，≤ 400 行（数据构造为主） |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-1 人造数据扩充 | **自己造标注数据**（用户指示）：意图标注集从 ~100 条扩到 **300+ 条**——knowledge / casual_chat / realtime 三类平衡 + 边界易混样本（"你们网站有什么功能"类）+ 专有术语+疑问句样本（E2E bug 类：G1/JVM/Redis）；落盘为独立数据文件，训练脚本接入 | 用户指示 + ADR-0003 L4 |
| WP-2 重训 | 复用 `train_intent_classifier.py`（接入新数据集）→ bge-m3 冻结 + LogisticRegression(balanced) → Accuracy/混淆矩阵对比（旧 0.89 → 新） | ADR-0003 L4 |
| WP-3 真实评测对比 | golden_intent 真实模式跑 **LLM vs 分类器** 对比（Accuracy/每类 P/R/F1/混淆矩阵）——数据决定是否达标切换 | module-047 真实评测模式 |
| WP-4 启用 | 达标（如 Accuracy ≥0.95 且 knowledge Recall ≥0.95 且无致命漏检）→ `PW_INTENT_CLASSIFIER_ENABLED` 默认开；分类器失败自动回退 LLM（已有设计）；未达标如实标注保持关闭 | ADR-0003 L4 上线流程 |
| WP-5 测试 + 回归 | tests/test_intent_dataset.py（数据集结构/类别平衡/边界样本）+ 分类器加载/回退测试；全量 pytest 688+ 全绿 | AC |

### 验收场景

```
场景 1：数据扩充
  假设 跑数据构造脚本
  那么 产出 300+ 条标注（三类平衡 + 边界易混 + 专有术语样本），JSON 结构可被训练脚本加载

场景 2：重训提升
  假设 python -m eval.train_intent_classifier
  那么 输出新 Accuracy/混淆矩阵；与旧 0.89 对比（提升或如实标注）

场景 3：真实对比
  假设 golden_intent 真实模式 LLM vs 分类器
  那么 输出两边 Accuracy/每类 P/R/F1——数据说话决定切换

场景 4：启用
  假设 达标 → PW_INTENT_CLASSIFIER_ENABLED 默认开
  那么 分类器加载失败/推理失败 → 自动回退 LLM 分类（零影响）；真实 HTTP 冒烟正常

场景 5：未达标
  假设 不达标
  那么 保持关闭，如实标注差距与扩充方向（不硬切）
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-1 | `ai_service/eval/intent_train_dataset.json`（新：300+ 条人造标注，类别平衡）+ 构造脚本 `ai_service/eval/build_intent_dataset.py`（新，标注指南入 docstring） | 新建 |
| WP-2 | `ai_service/eval/train_intent_classifier.py`（加载新数据集，优先级最高） | 修改 |
| WP-3 | `ai_service/eval/golden_intent.py`（真实模式 LLM vs 分类器对比输出，若已有则适配） | 修改 |
| WP-4 | `ai_service/src/config.py`（PW_INTENT_CLASSIFIER_ENABLED 默认值，达标才改） | 修改 |
| WP-5 | `ai_service/tests/test_intent_dataset.py`（新）+ 分类器回退测试 | 新建/修改 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0003 状态更新 | 修改 |

### 3.2 关键实现约束

- **WP-1 数据**：三类平衡（每类 ≥80 条，总 ≥300）；边界易混样本 ≥30 条（"你们网站有什么功能"/"G1垃圾收集器的核心创新是什么？"——E2E bug 类）；专有术语+疑问句 ≥30 条（G1/JVM/Redis/GC 等）；口语化无术语知识问题 ≥20 条（"内存老是溢出咋办"类——LLM 理解力场景）；人造数据声明（非真实用户对话，方向性验证）；JSON 结构：`[{"query", "intent"}, ...]`，训练脚本 load 接入（优先级高于 golden_intent？——**训练/评测分离**：评测集 golden_intent 100 条不动（独立验证），训练集扩充——防数据泄漏，changelog 声明）
- **WP-2 重训**：`IntentClassifier.fit(samples)` 复用；`class_weight="balanced"` 抗不平衡；输出新 Accuracy/混淆矩阵/每类 P/R/F1；与旧 0.89 对比（提升或如实标注）；模型落盘 `models/intent_clf.joblib`（训练产物不进仓库）
- **WP-3 对比**：golden_intent 真实模式——LLM 分类 vs 分类器分类同 100 条对比；重点看 knowledge Recall（漏检率，最高风险）；分类器结果入 eval_runs（eval_type='intent' 或 'intent_classifier'）
- **WP-4 启用判定**：达标线（建议）：Accuracy ≥0.95 且 knowledge Recall ≥0.95 且 casual/realtime 无明显塌陷（F1 ≥0.9）——数据决定；达标 → config 默认开（PW_INTENT_CLASSIFIER_ENABLED=true）；**分类器加载失败/推理失败 → 回退 LLM 零影响**（已有设计，测试断言）；保持 PW_ 开关可回退
- **诚实边界**：人造数据是方向性验证（非真实用户分布）；分类器 Accuracy 是 test split 内评估，真实分布可能不同（golden_intent 100 条真实评测是外部队列）；未达标如实标注不硬切
- **不改 LLM 分类主路径行为**（分类器启用前默认仍 LLM；启用后失败回退 LLM）；不改前端
- 全量 pytest 688+ 全绿；不改存量测试掩盖

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 分类器加载失败/推理失败 | 回退 LLM 分类（已有设计 + 测试断言） |
| 重训 Accuracy 不达 0.95 | 如实标注，保持关闭；扩充方向（更多边界/口语样本）入 changelog |
| golden_intent 真实评测 LLM 不可用 | 记 skipped，分类器单侧对比（如实声明） |
| 数据集构造工作量超预期 | 300+ 条必须完成（方向性验证需量级）；标注指南先行 |

---

## 4. 依赖

- ADR-0003 L4（分类器设计 + 上线流程）、module-043（L4 实现 + golden_intent）、module-047（真实评测模式）、module-048（飞轮数据源预留）、module-055（E2E 边界样本——G1 query 类）
- 环境：bge-m3 本地嵌入、sklearn/joblib 已装、模型落盘路径 models/intent_clf.joblib

## 5. 已知边界

- 人造数据非真实用户分布（方向性验证）；真实飞轮（👍👎）数据积累后仍可增量重训（fit 接口已预留）
- 训练集/评测集分离防泄漏（golden_intent 100 条不动）
- 分类器启用后 LLM 退居兜底（失败回退），仍保留 PW_ 开关
- 文档类（简历/弹药）不改（用户指示：等优化完成后进行）
- 全量 pytest 688 全绿保持（本模块新增 +N）
