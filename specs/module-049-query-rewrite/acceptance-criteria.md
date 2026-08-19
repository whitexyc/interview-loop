# 验收标准 — Module-049: 分诊式 Query 改写

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 静态分诊）

- [ ] 📋 分诊逻辑存在：FTS 术语命中（复用 jieba 分词 + `_FUNCTION_STOPWORDS` 过滤 + search_tokens 倒排）→ 精确 query 直接检索，不走改写
- [ ] 📋 分诊判据是"词表对得上"（检索质量信号），不调 LLM、不调生成
- [ ] 📋 分诊失败（DB 异常/超时）→ 保守默认"模糊"走改写路径，不中断链路
- [ ] 📋 `_kb_terms` 复用而非复制（router 提取公开接口或 engine 调 router 方法，逻辑单一来源）

## 2. 功能验收（WP2 改写路径）

- [ ] 📋 LLM 改写封装独立（改写失败/超时 → 回退原 query）
- [ ] 📋 保真预检：改写 vs 原 query 余弦 < 0.6（配置化）→ 直接用原 query 检索，跳过并行
- [ ] 📋 并行检索：原 query + 改写 query 各检索一次（gather + 单路失败降级）
- [ ] 📋 择优：改写检索 top-1 绝对余弦 > 原检索 → 用改写结果；否则回退原结果；相等/缺失 → 回退原（保守）
- [ ] 📋 择优后 abs_cosine 正常存档（对齐 module-045 双命中透传，父块映射后不丢）

## 3. 功能验收（WP3 评测闭环）

- [ ] 📋 `eval/golden_query_rewrite.py` 存在：对比"原始 vs 改写"Recall@K（K=5）/MRR
- [ ] 📋 eval_runs 落库 `eval_type='query_rewrite'`（对齐 golden_retrieval 落库函数）
- [ ] 📋 `--fixture` 模式不依赖 LLM/DB（启发式演示管线）
- [ ] 📋 LLM 改写失败/超时 → 记 skipped 不中断
- [ ] 📋 评测只度量不接线（不改生产行为）

## 4. 降级验收

- [ ] 📦 LLM 改写失败 → 回退原 query，链路行为与现状完全一致
- [ ] 📦 并行检索单路失败 → 用成功路结果
- [ ] 📦 保真预检失败 → 跳过预检直接并行（择优兜底）
- [ ] 📦 分诊 DB 不可用 → 保守走改写路径
- [ ] 📦 全量 pytest 533 全绿保持

## 5. 接口兼容

- [ ] 🔌 ChatResponse / 现有端点不变
- [ ] 🔌 check_sufficiency 反思充分性检查保留（事后兜底不删除）
- [ ] 🔌 HyDE 保留（round 0 首轮扩展，与改写正交）
- [ ] 🔌 retriever/reranker 核心不变

## 6. 测试验收

- [ ] 🧪 tests/test_query_rewrite.py：分诊命中/不命中/失败默认、保真预检回退、并行择优（改写优/原优/改写失败）、降级
- [ ] 🧪 python -m pytest tests/ -q — 全量 533+ 全绿

## 7. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md
- [ ] 📝 记忆文件更新（rag-architecture.md 等）
- [ ] 📝 ADR-0009 状态更新（📋 暂不实施 → 实施中/已完成）
