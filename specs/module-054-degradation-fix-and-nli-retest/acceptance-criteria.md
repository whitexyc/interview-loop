# 验收标准 — Module-054: 检索降级修复 + mDeBERTa 复测

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-1 reranker 路径修复）

- [ ] 📋 reranker.py `_LOCAL_MODEL_DIR` 三级 dirname 修复（对齐 embeddings.py 修法）
- [ ] 📋 **真实加载验证**：实例化 CrossEncoder 加载 `ai_service/models/bge-reranker-v2-m3/` 并 rerank 一条真实 query 成功（非 mock）
- [ ] 📋 真实聊天路径重排恢复正常（E2E 冒烟：chat 或 stream 调用 rerank 不再抛 RerankerException）

## 2. 功能验收（WP-2 RRF 向量化降级）

- [ ] 📋 **方案 A**：hybrid/rrf/weighted 模式向量化失败 → 向量路降级为空 + warning 日志，FTS+图谱两路照常融合出结果（不抛整体异常）
- [ ] 📋 **方案 B 防御**：rrf 分支 retrieve() 抛 RetrievalException（A 未覆盖异常）→ 引擎补 graph_store.search_related 返回图结果（对齐 hybrid 图回退）
- [ ] 📋 vector_only 消融模式保持抛错（评估路径语义不变，changelog 声明差异）
- [ ] 📋 正常路径零开销（无向量化时不额外调用；代码审查确认）

## 3. 功能验收（WP-3 矛盾样本构造）

- [ ] 📋 产出 ≥30 条矛盾样本（用户指示"多一些"）：① claim vs 文档矛盾 ② claim 内部自相矛盾 两类
- [ ] 📋 含正例对照（一致样本，等量或按比例）
- [ ] 📋 标注指南落盘（"什么是矛盾"判定标准 + 构造方法）
- [ ] 📋 样本 JSON 与 golden_factcheck 结构兼容（question/claim/doc/verdict）
- [ ] 📋 人工复核：Reviewer 抽查标注一致性

## 4. 功能验收（WP-4 mDeBERTa 复测）

- [ ] 📋 真实答案句子来源：LLM 生成（deepseek 真实调用）或如实标注"待环境"用构造句子替代并声明
- [ ] 📋 DB golden 112 题真实检索片段参与复测（DB 已修复可用）
- [ ] 📋 输出 kappa 三分类 + 二值两口径
- [ ] 📋 结论：≥0.7 → 放行替换；未达 → 降级双轨（NLI 只做矛盾扫描），写回 ADR-0010

## 5. 降级验收

- [ ] 📦 LLM 环境不可用 → 如实标注 + 构造句子替代声明
- [ ] 📦 DB 检索不可用 → SUFFICIENCY 替代 + 声明（预期可用）
- [ ] 📦 kappa < 0.7 → 如实标注不伪造，结论降级双轨
- [ ] 📦 全量 pytest 648 全绿保持

## 6. 接口兼容

- [ ] 🔌 retriever 返回结构不变（向量路空 = 缺路不参与融合，已有实现兼容）
- [ ] 🔌 engine rrf 分支返回结构不变（补图兜底返回图结果列表）
- [ ] 🔌 reranker 接口/行为不变（仅路径修复）

## 7. 测试验收

- [ ] 🧪 tests/test_degradation_fix.py：reranker 路径（mock dirname 或真实加载冒烟）、方案 A（mock embedding 失败 → FTS+图谱照常）、方案 B（mock retrieve 抛异常 → 引擎补图）、vector_only 保持抛错、正常路径零额外调用
- [ ] 🧪 tests/test_contradiction_dataset.py：样本集数量/两类结构/正例对照/JSON 兼容性
- [ ] 🧪 python -m pytest tests/ -q — 全量 648+ 全绿（不改存量测试掩盖）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含复测 kappa 实测数字 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-054 行** + 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0010 状态更新（复测结论：放行/降级双轨）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
- [ ] 📝 文档类（简历/弹药）**不改**（用户指示：等优化完成后进行）
