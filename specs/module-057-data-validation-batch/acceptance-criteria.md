# 验收标准 — Module-057: 数据验证批

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-A1 矛盾改进）

- [ ] 📋 句级拆解：claim 切子句逐句判 → 聚合（任一矛盾→contradiction / 无矛盾有entailment→entailment / 全neutral→neutral）；内部矛盾子句两两互判；拆句失败回退整句
- [ ] 📋 阈值校准：扫描 0.5-0.9 步长 0.05 + 低置信→neutral；最优阈值配置化
- [ ] 📋 矛盾样本 ≥50 条（internal ≥20 条多句混合），JSON 结构不变，指南同步
- [ ] 📋 复测 kappa 三分类对比 0.5167（eval_runs 'nli_retest_v2'）；结论写回 ADR-0010（≥0.7 放行 / 未达 + 方向）

## 2. 功能验收（WP-A2 图谱消融）

- [ ] 📋 `--ablate` 跑通（DB 已修）：graph_only vs hybrid Hit@5 差值（+X.X）
- [ ] 📋 delta 落 eval_runs；**口径注明**（rrf 三通道 vs 历史 hybrid 两通道）
- [ ] 📋 DB 异常 → 如实标"待环境"

## 3. 功能验收（WP-A3 改写增益）

- [ ] 📋 golden_query_rewrite 真实模式跑通：原始 vs 改写 Recall@K/MRR 对比 + delta
- [ ] 📋 eval_runs 落库（eval_type='query_rewrite'）；LLM 失败记 skipped

## 4. 功能验收（WP-A4 RRF k 扫描 + 归因）

- [ ] 📋 k 扫描（20-100，拐点加密）→ Hit@5 vs k 曲线 + 最优 k（对比 k=60）
- [ ] 📋 两通道 RRF vs 三通道 RRF → 图谱净增益归因
- [ ] 📋 eval_runs 落库；最优 k 结论入 changelog（改 `rrf_constant_k` 默认则测试适配注明）

## 5. 功能验收（WP-A5 飞轮冒烟）

- [ ] 📋 自己造 3-5 条知识库问题 → 真实 HTTP chat 获取回答（含 message_id）
- [ ] 📋 模拟点击 👍👎（POST /ai/feedback，rating 交替 ±1，≥1 条带 comment）
- [ ] 📋 feedback 表新增对应记录（message_id/rating/identity/created_at 正确）
- [ ] 📋 重复提交同一 message_id → 不重复落库（防重复验证，如实记录机制）
- [ ] 📋 冒烟数据保留为飞轮种子（changelog 注明）或清理策略声明

## 6. 降级验收

- [ ] 📦 复测 < 0.7 → 如实标注 + 方向
- [ ] 📦 图谱/改写 LLM 限流 → skipped 不中断
- [ ] 📦 全量 pytest 700 全绿保持

## 7. 接口兼容

- [ ] 🔌 不改生产 verify_answer / 检索默认行为（A4 改 k 默认则注明）
- [ ] 🔌 retest_nli/golden_retrieval/golden_query_rewrite 既有接口兼容

## 8. 测试验收

- [ ] 🧪 tests/test_nli_improve.py：句切/聚合/内部矛盾/回退/阈值扫描/标注结构（≥50 矛盾 internal≥20）
- [ ] 🧪 python -m pytest tests/ -q — 全量 700+ 全绿（不改存量测试掩盖）

## 9. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含 5 个硬数字 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-057 行** + 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0010 状态更新（矛盾复测结论）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
- [ ] 📝 文档类（简历/弹药）**不改**（用户指示：等优化完成后进行）
