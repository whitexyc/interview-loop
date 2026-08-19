# 验收标准 — Module-065: 入库性能验证 + E2E 复测 + 公开基准 + minor 清理

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. WP1 写入侧嵌入性能验证（证伪记录）

- [ ] 📋 `eval/benchmarks/benchmark_embed_write.py` 可复跑：循环 vs List 批量 vs
      多进程 2/4 三组对比（输出每档耗时 + 倍率表）
- [ ] 📝 运行输出与 2026-08-15 探路口径一致（批量无加速 / 多进程负优化）
- [ ] 📝 METRICS.md 待办⑥ 更新为"实测证伪"结论（写入吞吐 ~110-160ms/块 为固有成本）
- [ ] 📋 **不改生产代码**（embeddings.py / engine.py 零改动——无可行优化不做投机改动）

## 2. WP2 E2E 复测

- [ ] 🔌 AI 服务重启后可用（uvicorn 后台常驻）
- [ ] 📋 "什么是G1 GC" 6 次实测：TTFT / 完整时长（同口径对比优化前 25.3s / 28.1s）
- [ ] 📋 真实文档生产链路命中：论文问题走完整 chat → sources 含 rag_survey.pdf 块
- [ ] 📋 request_logs 分段：rerank 段实测耗时（对比优化前 8.5-13.5s）
- [ ] 📝 METRICS.md E2E 段更新为优化后数字（保留优化前对照）

## 3. WP3 C-MTEB/BEIR 公开基准

- [ ] 🔌 数据源可达性探测（hf-mirror / ModelScope 至少一个通）
- [ ] 📋 ≥1 个公开数据集跑出真实检索指标（Hit@5 / MRR / nDCG@10 按口径）
- [ ] 📝 METRICS 新增公开基准段（数据集/指标/与自建集对比 + 乐观偏差解读）

## 4. WP4 module-064 minor 清理

- [ ] 📋 `find_semantic_duplicate` 候选查询过滤 `is_canonical=True` + 单测
- [ ] 📝 project-context / ADR-0014 / CONTEXT.md 三处测试数口径修正为 85 / 1036
      （CONTEXT.md 只增不删）

## 5. 收口

- [ ] 🧪 全量 pytest = 1036 基线 + 新增 全绿（存量零改动）
- [ ] 📝 changelog / review-report / test-report + memory 三件套
- [ ] 📝 诚实边界：WP1 证伪记录；WP3 受数据源制约；WP2 受 LLM 外部抖动制约

## 6. 降级验收

- [ ] 📦 C-MTEB/BEIR 数据源全不可达 → 评测脚本交付 + "待环境"如实标注（不伪造数字）
- [ ] 📦 deepseek 429/网络故障 → 如实记录外部抖动，不伪造 E2E 数字
- [ ] 📦 服务无法重启/端口占用 → 如实记录，E2E 复测顺延（不假报）
