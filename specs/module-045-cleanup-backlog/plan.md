# 功能规格说明书 — Module-045: 遗留清理批（代码修复 + 训练脚本 + 依赖补齐）

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-045 |
| 模块名称 | 遗留清理批：retriever 透传 + 043 minor + 流式 L3 + 充分性训练脚本 + requirements |
| 版本号 | 0.45.0-module-045 |
| 优先级 | P1（汇总 043/044 Reviewer minor + 数据实验前置） |
| 预估代码量 | ≤ 300 行 + 1 个训练脚本 |

---

## 2. 需求（全部来自已记录的 backlog）

| WP | 内容 | 来源 |
|----|------|------|
| WP1 | retriever 合并环 abs_cosine 透传：Step 4 双命中合并时 `merged[doc_id]["abs_cosine"] = doc["abs_cosine"]`（vec 分支，L350-355）——双命中文档不再丢字段，分数闸门覆盖提升 | 044 minor #1 |
| WP2a | router.py `_RULE_TABLE` 移除"你能做什么/你会什么"（与 golden 边界样本"你能做什么？这个系统能帮我解决什么问题？"标注 knowledge 矛盾）；更新 test_rule_table_keeps_kb_boundary_samples 断言 | 043 minor #1 |
| WP2b | engine.py ChatSteps `top_abs_cosine` 父块映射后失真（expand_to_parents 重建 dict 丢字段）——round 0 判定处把 top1_abs 与 suspected_misclassify 标记同源存档 | 043 minor #2 |
| WP2c | engine.py `_check_suspected_misclassify` 静态方法生产路径复用（chat 内联判定改调用，消除重复） | 043 minor #3 |
| WP2d | router.py L4 分类器返回的 intent 过白名单校验（非法 → knowledge，与 LLM 路径口径一致，一行） | 043 minor #4 |
| WP3 | main.py 流式端点（chat_stream）ChatSteps 补 suspected_misclassify（L3 标记接入流式路径；**不改动其他会话的去个人化文案改动**） | 044 遗留 |
| WP4 | 新建 eval/train_sufficiency_classifier.py：从 SUFFICIENCY_DATASET（100 条）训练充分性分类器，仿 train_intent_classifier.py（bge-m3 冻结 + LogisticRegression + 校准概率），落盘 models/sufficiency_clf.joblib | 用户指令 |
| WP5 | requirements.txt 补 scikit-learn + joblib（L4 分类器依赖，环境已装，声明补齐） | 044 遗留 |

### 验收场景

```
场景 1：双命中文档带 abs_cosine
  假设 FTS+向量同时命中某文档
  那么 合并结果含 abs_cosine（原始向量余弦），分数闸门不静默跳过

场景 2：规则表不再误伤边界样本
  假设 query="你能做什么？这个系统能帮我解决什么问题？"
  那么 _rule_hits 返回 False（不再被规则表否决），L2 可正确走 FTS/图谱确认

场景 3：ChatSteps 展示值真实
  假设 top-1 是父块映射结果
  那么 steps.retrieval.top_abs_cosine = round 0 判定时的真实值（非恒 0.0）

场景 4：充分性分类器可训练
  假设 跑 python -m eval.train_sufficiency_classifier
  那么 从 100 条标注集训练，输出 P/R/F1，模型落盘 sufficiency_clf.joblib

场景 5：requirements 补录
  假设 pip install -r requirements.txt
  那么 scikit-learn / joblib 可安装
```

---

## 3. 技术方案

### 3.1 涉及文件

| 文件 | 操作 | WP |
|------|------|-----|
| `ai_service/rag/retriever.py` | 修改（合并环 1 行） | WP1 |
| `ai_service/agent/router.py` | 修改（规则表 + L4 白名单） | WP2a/d |
| `ai_service/rag/engine.py` | 修改（top_abs_cosine 存档 + 静态方法复用） | WP2b/c |
| `ai_service/main.py` | 修改（流式 ChatSteps L3 标记；不动他人文案） | WP3 |
| `ai_service/eval/train_sufficiency_classifier.py` | 新建 | WP4 |
| `ai_service/requirements.txt` | 修改（+2 行） | WP5 |
| 测试 | 修改/新建 | 各 WP |

### 3.2 关键实现约束

- **WP1**：vec 分支（L348-355）在更新 vector_score 的同时补 abs_cosine；fts-only 文档保持无字段（下游按 0.0 处理，语义正确）
- **WP2b**：判定与存档同源——用同一个 top1_abs 变量既判 suspected_misclassify 又写 steps
- **WP2c**：静态方法改为返回 (flag, top1_abs)，chat 调用它，消除内联重复
- **WP3**：main.py 只加 L3 相关代码；其他会话的去个人化文案（"张三"→"个人"）不得改动/回退
- **WP4**：训练脚本结构对齐 train_intent_classifier.py（数据源 SUFFICIENCY_DATASET、class_weight=balanced、fit/predict_proba、--no-save、--model-path）；样本不足 10 明确报错

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 双命中无 abs_cosine（理论不存在，防御） | `d.get("abs_cosine", None)` 走 LLM（现有哲学） |
| 充分性分类器训练失败 | 报错退出，不影响主链路（训练是离线工具） |
| 规则表移除后边界样本 L2 行为变化 | 由 FTS/图谱确认 + L3/L4 兜底（plan 已评估） |

---

## 4. 依赖

- module-043（L2/L3/L4 基建 + 4 项 minor 来源）
- module-044（abs_cosine 字段链 + SUFFICIENCY_DATASET 100 条）
- 其他会话合理改动（react.py/langgraph_react.py 截断下沉、main.py 去个人化、faithfulness.py 文档）——本模块提交时一并纳入（已审查，均为合理功能改动）

## 5. 已知边界

- **预存失败**：已全部清零（428/428 全绿），本模块不得引入新失败
- **main.py 混合改动**：提交时包含其他会话的去个人化文案（已审查合理），一并提交
- 训练脚本产物 models/sufficiency_clf.joblib 按本地模型约定不提交仓库
