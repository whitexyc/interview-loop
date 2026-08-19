# Module-065 实施计划 — 入库性能验证 + E2E 复测 + 公开基准 + minor 清理

> Planner: 主会话（2026-08-15）| 范围：能做的合并批（需数据/标注的任务不在此列）
> 背景：module-064 验收后真实文档插入实测暴露 CSV 大数据集入库慢（7231 块 50 分钟）；
> reranker 优化批（P0-P3）已提交；METRICS 待办中可本地闭环的项。

## 0. Planner 已探明事实（勿重复调查）

- **嵌入写入侧探路结论（2026-08-15 实测，两条优化路径均已证伪）**：
  ① `llama_cpp.Llama.create_embedding` 支持 `List[str]`，但实测无批量加速
  （10 条 0.8x / 50 条 1.3x / 200 条 0.9x vs 循环）——内部非真 batch decode；
  ② 多进程并行嵌入（ProcessPoolExecutor，Windows spawn）实测**负优化**
  （2 进程 0.4x / 4 进程 0.3x vs 串行：spawn 重 import + 内存带宽竞争）。
  结论：**写入侧无廉价优化路径**，~110-160ms/块（bge-m3 Q8 单核推理）为固有成本。
- reranker 优化已提交（量化/粗筛/200 截断/预热，全量 1036 绿），服务未重启，E2E 未复测。
- C-MTEB/BEIR：公开标准数据集（下载即测）。环境坑：huggingface.co 不可达
  （module-050 已知），需先探 mirror（hf-mirror.com / ModelScope）。
- module-064 minor（Reviewer 第 2 轮）：① find_semantic_duplicate 候选查询未过滤
  `is_canonical`（非 canonical 副本仍存 doc_embedding，0.95 高阈值下风险低）；② 测试数
  口径漂移：project-context/ADR-0014/CONTEXT 写 66 新增，实际 **85 / 1036**。
- 测试文档已插入知识库（source=realdoc_test:2026-08-14，用户要求留存）：
  rag_survey.pdf（568 块）/ redis_docs.txt（246 块）/ world_cities.csv（7231 块）。
- 全量测试基线：**1036 passed / 0 failed**（module-064 验收数）。
- 服务需重启才能复测 E2E（deepseek API 可用性：历史上 429 风暴时段降级链慢为外部抖动）。

## 1. WP1 写入侧嵌入性能验证（探路已证伪 → 收敛为验证记录）

- **目标**：把探路结论固化为可复现的验证脚本 + 文档记录（防未来重复踩坑）。
- **产出**：
  ① `eval/benchmarks/benchmark_embed_write.py`（新建，可复跑：循环 vs List 批量 vs
     多进程 2/4，输出每档耗时表，同 2026-08-15 探路口径）；
  ② 文档记录：changelog + METRICS.md 待办⑥ 更新为"实测证伪：批量/多进程均无收益，
     写入吞吐 ~110-160ms/块 为 bge-m3 单核推理固有成本"。
- **通过标准**：脚本可复跑输出与探路一致的量级；METRICS 待办⑥ 如实更新。
- **明确不做**：改 embeddings.py / engine.py 生产代码（无可行优化，避免投机改动）。

## 2. WP2 E2E 复测（reranker 优化落地值 + 真实文档生产链路命中）

- **目标**：验证 P0-P3 优化后 TTFT/完整时长（优化前 25.3s / 28.1s，rerank 8.5-13.5s）。
- **产出**：
  ① 重启 AI 服务（后台常驻，java -jar 不适用——AI 服务是 python uvicorn）；
  ② 复用 `e2e_latency_probe.py`（tmp）测 6 次"什么是G1 GC"TTFT/完整时长（同口径对比）；
  ③ 真实文档生产链路命中：论文问题（"What are the three paradigms of RAG?"等）走完整
     chat 检索链路 → 验证 sources 含 rag_survey.pdf 块（RRF→粗筛→rerank 后仍命中）；
  ④ request_logs 分段确认 rerank 段实测耗时（对比优化前 8.5-13.5s）；
  ⑤ METRICS.md E2E 段更新为优化后数字（保留优化前对照）。
- **降级**：deepseek 429/网络故障 → 如实记录外部抖动，不伪造数字。
- **通过标准**：6 次实测记录完整（TTFT/完整/分段）；真实文档命中验证有 sources 证据；
  METRICS 更新为优化后口径。

## 3. WP3 C-MTEB/BEIR 公开基准（测通用泛化）

- **目标**：补自建集"自己考自己"的乐观偏差，测通用泛化（METRICS 待办⑤ 闭环）。
- **步骤**：
  ① 探数据源：hf-mirror.com / ModelScope 哪个可达（huggingface.co 已知不可达），
     选 1-2 个中文检索子集（如 C-MTEB T2Retrieval 子集或 BEIR 小集如 nfcorpus）；
  ② 适配：检索接口（bge-m3 embed + pgvector 或内存余弦）跑标准指标
     （Hit@5 / MRR / nDCG@10 按数据集口径）；
  ③ 落文档：METRICS 新增"公开基准"段（模型/数据集/指标/与自建集 0.9905 对比）。
- **降级**：所有数据源不可达 → 只交付评测脚本（离线可自测小集）+ 如实标注"待环境"。
- **通过标准**：≥1 个公开数据集跑出真实数字；或脚本就绪 + 环境不可达如实标注。

## 4. WP4 module-064 minor 清理

- **minor-1（代码）**：`find_semantic_duplicate` 候选查询过滤 `is_canonical=True`
  （非 canonical 副本不参与比对，防低概率误判 + 对齐"查询只出 canonical"语义）。
  单测：非 canonical 文档不出现在候选；存量测试零改动。
- **minor-2（文档口径）**：project-context.md module-064 行、ADR-0014 状态行、
  CONTEXT.md 段中"66 新增"统一修正为 **85 / 1036**（CONTEXT.md 只增不删——修正走
  追加更正行或段内修订，不删旧行）。
- **通过标准**：minor-1 单测 + 全量绿；minor-2 三处口径修正完成。

## 5. 收口（全模块）

- 全量 pytest = 1036 基线 + 新增 全绿
- changelog / review-report / test-report + memory 三件套 + 提交推送（主会话）
- 诚实边界：WP1 是证伪记录；WP3 受数据源可达性制约；WP2 受 LLM 外部抖动制约

## 6. 交付物清单

- `ai_service/eval/benchmarks/benchmark_embed_write.py`（WP1）
- `specs/module-065-*/`：plan（本文件）/ acceptance-criteria / changelog / review-report / test-report
- METRICS.md：待办⑥ 更新 + E2E 段优化后数字 + 公开基准段（如 WP3 达成）
- memory 三件套更新
