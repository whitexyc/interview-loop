# 验收标准 — Module-057: mDeBERTa 矛盾判别改进

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-1 句级拆解）

- [ ] 📋 claim 按中文句切拆子句（复用 _pre_chunk 模式）→ 逐子句与文档判 → 聚合
- [ ] 📋 聚合规则明确：任一子句 contradiction → claim 判 contradiction（最严）；无矛盾但有 entailment → entailment；全 neutral → neutral
- [ ] 📋 内部矛盾：子句两两互判，任一矛盾 → internal contradiction
- [ ] 📋 拆句失败（无标点）→ 回退整句判（零回归）

## 2. 功能验收（WP-2 置信度校准）

- [ ] 📋 扫描 contradiction 阈值（0.5-0.9 步长 0.05）+ 低置信（max prob < 阈值 → neutral）
- [ ] 📋 输出 kappa vs 阈值曲线，最优阈值配置化（如 `nli_contradiction_threshold`）
- [ ] 📋 校准方法学可复现（步长入 changelog）

## 3. 功能验收（WP-3 标注扩充）

- [ ] 📋 矛盾样本扩充至 ≥50 条（internal 重点 ≥20 条多句混合样本）
- [ ] 📋 claim_vs_doc 反转样本补充 + 正例对照按比例
- [ ] 📋 JSON 结构不变（question/claim/doc/doc_title/verdict/contradiction_type/note/part）
- [ ] 📋 标注指南同步更新（含多句 claim 拆解口径）；Reviewer 抽查一致性

## 4. 功能验收（WP-4 复测）

- [ ] 📋 扩充样本 + 句级拆解 + 校准阈值重跑 → kappa 三分类对比 0.5167
- [ ] 📋 eval_runs 落库（eval_type='nli_retest_v2'）
- [ ] 📋 结论写回 ADR-0010：≥0.7 → 放行矛盾扫描实施；未达 → 如实标注 + 下一轮方向

## 5. 降级验收

- [ ] 📦 拆句失败 → 回退整句判（零回归）
- [ ] 📦 复测仍 < 0.7 → 如实标注不伪造，记录下一轮方向
- [ ] 📦 全量 pytest 700 全绿保持

## 6. 接口兼容

- [ ] 🔌 不改生产 verify_answer 行为（本模块评估侧 + 数据扩充）
- [ ] 🔌 retest_nli.py 既有模式兼容（新样本集可加载，旧数字可对比）

## 7. 测试验收

- [ ] 🧪 tests/test_nli_improve.py：句切/聚合规则（任一矛盾/无矛盾有entailment/全neutral/拆句失败回退）、内部矛盾两两互判、阈值扫描逻辑、标注结构（≥50 矛盾/internal≥20）
- [ ] 🧪 python -m pytest tests/ -q — 全量 700+ 全绿（不改存量测试掩盖）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含复测 kappa 实测 + 校准表 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-057 行** + 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0010 状态更新（复测结论：放行/未达 + 下一轮方向）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
- [ ] 📝 文档类（简历/弹药）**不改**（用户指示：等优化完成后进行）
