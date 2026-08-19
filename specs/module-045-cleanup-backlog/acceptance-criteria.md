# 验收标准 — Module-045: 遗留清理批

> 汇总 043/044 Reviewer minor + 用户指令。图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 retriever 透传）

- [ ] 📋 FTS+向量双命中文档合并结果含 abs_cosine（原始向量余弦，非 0.0）
- [ ] 📋 fts-only 文档保持无该字段（下游 0.0 语义不变）
- [ ] 📋 hybrid_score 计算不受影响（纯字段补透，零回归）

## 2. 功能验收（WP2 043 四项 minor）

- [ ] 📋 规则表不再含"你能做什么/你会什么"；`_rule_hits("你能做什么？这个系统能帮我解决什么问题？")` 返回 False
- [ ] 📋 边界样本测试断言更新并覆盖（test_rule_table_keeps_kb_boundary_samples）
- [ ] 📋 ChatSteps.retrieval.top_abs_cosine 在 top-1 为父块映射结果时为 round 0 真实值（非恒 0.0）
- [ ] 📋 `_check_suspected_misclassify` 被 chat 生产路径调用（消除内联重复）
- [ ] 📋 L4 分类器返回的 intent 过白名单（非法 → knowledge，与 LLM 路径口径一致）

## 3. 功能验收（WP3 流式 L3 标记）

- [ ] 📋 chat_stream 的 ChatSteps 含 suspected_misclassify（与 engine.chat 非流式路径一致）
- [ ] 📋 main.py 其他会话的去个人化文案改动未被改动/回退

## 4. 功能验收（WP4 充分性分类器训练脚本）

- [ ] 📋 `python -m eval.train_sufficiency_classifier` 从 SUFFICIENCY_DATASET（100 条）训练成功
- [ ] 📋 输出 P/R/F1（重点 insufficient Recall）+ Accuracy
- [ ] 📋 模型落盘 models/sufficiency_clf.joblib（--no-save 不落盘）
- [ ] 📋 样本不足 10 条明确报错退出；--model-path 可配

## 5. 功能验收（WP5 requirements）

- [ ] 📋 requirements.txt 含 scikit-learn + joblib 声明

## 6. 接口兼容

- [ ] 🔌 retriever 返回结构不变（多一个字段，读取方 get() 兼容）
- [ ] 🔌 check_sufficiency / classify() / ChatSteps 旧字段不变
- [ ] 🔌 10 个 Agent 工具不受影响

## 7. 测试验收

- [ ] 🧪 新增/更新测试：retriever 双命中透传、规则表边界样本、top_abs_cosine 存档、L4 白名单、充分性训练脚本（mock 特征）
- [ ] 🧪 python -m pytest tests/ -q — 全量 **428 全绿保持**（0 失败，不得引入新失败）

## 8. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md
- [ ] 📝 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）
- [ ] 📝 训练脚本用法文档（docstring）
