# 项目文件索引

> 记录所有重要文件及其内容摘要。新 Agent 入场时先读此文件快速定位。
> 维护规则：新增重要文件时追加到对应分类，模块产出见 `specs/`（按模块目录索引）。

## 一、项目基础（初始化期，07-29）

| 文件路径 | 模块 | 类型 | 内容摘要 | 创建时间 | 最后更新 | 状态 |
|----------|------|------|----------|----------|----------|------|
| tech-stack.md | 项目初始化 | 配置 | 技术栈配置文档 | 2026-07-29 | 2026-07-29 | ✅ |
| CLAUDE.md | 项目初始化 | 规范 | Vibe Coding 闭环工作流核心规范 | 2026-07-29 | 2026-07-29 | ✅ |
| memory/project-context.md | 项目初始化 | 记忆 | 项目上下文记忆库（状态/待办/ADR索引） | 2026-07-29 | 2026-08-07 | ✅ |
| memory/agent-activity-log.md | 项目初始化 | 记忆 | Agent 活动日志索引 | 2026-07-29 | 2026-08-07 | ✅ |
| memory/file-index.md | 项目初始化 | 记忆 | 项目文件索引（本文） | 2026-07-29 | 2026-08-07 | ✅ |
| docker-compose.yml | module-001 | 配置 | PostgreSQL(pgvector) + Redis 容器编排 | 2026-07-29 | 2026-07-29 | ✅ |
| backend/pom.xml | module-001 | 配置 | Spring Boot 3.2 依赖配置 | 2026-07-29 | 2026-07-29 | ✅ |
| backend/src/main/java/.../common/CommonResult.java | module-001 | 代码 | 统一API返回格式 | 2026-07-29 | 2026-07-29 | ✅ |
| backend/src/main/java/.../common/GlobalExceptionHandler.java | module-001 | 代码 | 全局异常处理器 | 2026-07-29 | 2026-07-29 | ✅ |
| ai_service/main.py | module-001/036 | 代码 | FastAPI 入口 + 健康检查 + agent/agent-lg 会话恢复保存 | 2026-07-29 | 2026-08-02 | ✅ |
| frontend/ | module-001 | 代码 | React 前端 | 2026-07-29 | 2026-08-02 | ✅ |
| specs/module-001-scaffold/ | module-001 | 规划 | 模块开发计划/验收/变更 | 2026-07-29 | 2026-07-29 | ✅ |
| Makefile | module-001 | 工具 | 常用命令快捷方式 | 2026-07-29 | 2026-07-29 | ✅ |
| .gitignore | 项目初始化 | 配置 | Git 忽略规则 | 2026-07-29 | 2026-07-29 | ✅ |

## 二、AI 推理层核心文件（ai_service/，module-004+）

| 文件路径 | 模块 | 类型 | 内容摘要 | 状态 |
|----------|------|------|----------|------|
| ai_service/rag/engine.py | module-005 | 代码 | RAG 引擎编排（chat/_retrieve/缓存/记忆注入） | ✅ |
| ai_service/rag/retriever.py | module-005 | 代码 | 混合检索（FTS+向量+图三通道，mode 消融） | ✅ |
| ai_service/rag/reranker.py | module-018/030 | 代码 | 重排（bge-reranker-v2-m3，分类式） | ✅ |
| ai_service/rag/embeddings.py | module-020 | 代码 | 本地嵌入（bge-m3 GGUF + 并发锁） | ✅ |
| ai_service/rag/graph_store.py | module-016 | 代码 | Graph RAG 图操作（AGE，真实分数） | ✅ |
| ai_service/rag/graph_extractor.py | module-016 | 代码 | 图实体/关系提取 | ✅ |
| ai_service/rag/chunker.py | module-017 | 代码 | 父子两级分块 | ✅ |
| ai_service/rag/memory.py | module-023/033/034 | 代码 | 长期/短期记忆（save 语义去重 + recall 动态K + save_short/recall_short TTL + 三层 source 分层 + 格式化注入，IP/user_id 隔离） | ✅ |
| ai_service/rag/session_memory.py | module-034 | 代码 | 会话记忆持久化（source=memory:\<identity\>:session:，content_hash 幂等 + 上限滚动 + 隔离恢复） | ✅ |
| ai_service/rag/memory_extractor.py | module-033 | 代码 | 长期记忆事实提取器（extract_facts LLM 提取，importance 过滤 + 失败降级） | ✅ |
| ai_service/rag/text_tokenizer.py | module-020 | 代码 | jieba 分词工具 | ✅ |
| ai_service/agent/router.py | module-005 | 代码 | 意图路由（LLM-as-Classifier） | ✅ |
| ai_service/agent/reflector.py | module-026 | 代码 | 反思/生成（低温度 0.1 + 降级链） | ✅ |
| ai_service/agent/tool_registry.py | module-028/036 | 代码 | ToolRegistry（7 工具） | ✅ |
| ai_service/agent/react.py | module-028/036 | 代码 | ReAct 循环（手写版，client_ip→identity） | ✅ |
| ai_service/agent/langgraph_react.py | module-030/036 | 代码 | ReAct 循环（LangGraph 版，实验端点） | ✅ |
| ai_service/llm/client.py | module-028 | 代码 | LLM 多供应商 + 降级链 + 动态链 + 工具调用 | ✅ |
| ai_service/eval/golden_retrieval.py | module-019 | 代码 | 评估（Hit@k/MRR/消融/版本化） | ✅ |
| ai_service/eval/golden.json | module-019 | 数据 | golden 评测集 | ✅ |
| ai_service/src/cache.py | module-022 | 代码 | Redis 缓存（前缀失效） | ✅ |
| ai_service/src/config.py | module-028 | 配置 | 配置（max_agent_tools 等） | ✅ |
| ai_service/migrate_embedding_1024.py | module-020 | 脚本 | 嵌入维度迁移 | ✅ |
| ai_service/backfill_search_tokens.py | module-020 | 脚本 | search_tokens 回填 | ✅ |
| ai_service/backfill_graph.py | module-016 | 脚本 | 图数据补跑 | ✅ |
| ai_service/rag_metadata_tables.sql | module-018 | SQL | rag_config + document_chunk_stats | ✅ |
| ai_service/scripts/ | module-050 | 脚本 | 12 个一次性脚本迁移目录（backfill_*/create_*/migrate_*/download_model/do_all/reindex_knowledge_base/test_embedding/test_m17/test_m18/test_models） | ✅ |
| ai_service/rag/retrieval/ | module-050 | 代码 | 检索子包（retriever/reranker/chunker/embeddings/text_tokenizer/query_rewrite） | ✅ |
| ai_service/rag/graph/ | module-050 | 代码 | 图谱子包（graph/graph_extractor/graph_store） | ✅ |
| ai_service/rag/memory/ | module-050 | 代码 | 记忆子包（memory/memory_extractor/session_memory） | ✅ |
| ai_service/eval/compare_factcheck_models.py | module-050 | 代码 | HHEM vs MiniCheck 真实对比（Accuracy/F1/kappa/一致率/耗时，--limit/--skip-*） | ✅ |
| ai_service/tests/test_compare_factcheck.py | module-050 | 测试 | 对比脚本单元测试（build_pairs/指标/kappa/模型缺失报错）12 项 | ✅ |
| ai_service/rag/retrieval/hhem_loader.py | module-051 | 代码 | HHEM 共享加载器（module-050 验证路径单一来源，compare 脚本 + 裁判共用） | ✅ |
| ai_service/rag/retrieval/factcheck_judge.py | module-051 | 代码 | HHEM 裁判封装（延迟加载 + threading.Lock + to_thread + 失败返回 None） | ✅ |
| ai_service/eval/golden_factcheck.py | module-051 | 代码 | factcheck 评测（50 条三态标注 + kappa 三态/二值 + eval_runs + --fixture） | ✅ |
| ai_service/tests/test_factcheck_judge.py | module-051 | 测试 | 裁判单元测试（加载降级/三态映射/集成/降级链/开关 llm/评测脚本）32 项 | ✅ |
| ai_service/eval/compare_nli_models.py | module-052 | 代码 | mDeBERTa vs HHEM 三分类对比（数据构造复用 + 三分类标注 + 加载/打分 + kappa 两口径 + 混淆矩阵 + --smoke） | ✅ |
| ai_service/tests/test_compare_nli.py | module-052 | 测试 | NLI 对比脚本单元测试（三分类标注/阈值映射/指标/mock 模型/降级）15 项 | ✅ |
| ai_service/scripts/migrate_module053.py | module-053 | 脚本 | DB 修复迁移（documents 补 last_mentioned_at/mention_count 两列幂等 + feedback 表建表复用 FEEDBACK_DDL） | ✅ |
| ai_service/tests/test_rrf_fusion.py | module-053 | 测试 | 三通道融合单测（RRF 公式/三路融合/开关零回归/单路降级/abs_cosine 保留/加权/回退）16 项 | ✅ |
| ai_service/eval/build_contradiction_dataset.py | module-054 | 脚本 | 矛盾样本构造（56 条：contradiction 32 两类 + entailment 16 + neutral 8 + 标注指南落盘） | ✅ |
| ai_service/eval/contradiction_dataset.py | module-054 | 代码 | 矛盾样本集加载/校验 + golden_factcheck 双向转换（question/claim/doc/verdict ↔ question/documents/label） | ✅ |
| ai_service/eval/contradiction_dataset.json | module-054 | 数据 | 56 条构造矛盾样本集落盘（part=constructed） | ✅ |
| ai_service/eval/real_retrieval_pairs.json | module-054 | 数据 | 24 条真实检索对（LLM 真实答案句子 + DB golden 检索片段，人工标注 part=real_retrieval） | ✅ |
| ai_service/eval/contradiction_annotation_guide.md | module-054 | 文档 | 矛盾样本标注指南（"什么是矛盾"判定标准 + 两类构造方法 + golden_factcheck 映射） | ✅ |
| ai_service/eval/retest_nli.py | module-054 | 代码 | mDeBERTa 复测脚本（--gen-real 真实对生成 + kappa 三分类/二值 + 混淆矩阵 + 门槛判定 + eval_runs） | ✅ |
| ai_service/tests/test_degradation_fix.py | module-054 | 测试 | 降级修复单测（reranker 三级路径/方案 A 向量路空+vector_only 抛错+零开销/方案 B 图兜底）9 项 | ✅ |
| ai_service/tests/test_contradiction_dataset.py | module-054 | 测试 | 矛盾样本集单测（≥30 矛盾两类/结构/正例对照/golden_factcheck 兼容/标注指南）10 项 | ✅ |
| ai_service/eval/prompt_variants.py | module-055 | 脚本 | Prompt 变体测试（5 变体 × golden_sufficiency → 对比表 Accuracy/insuff Recall/kappa/耗时；--variant/--limit/--save 落 eval_runs eval_type='prompt_variant'/--fixture；只度量不替换生产 prompt） | ✅ |
| ai_service/tests/test_prompt_variants.py | module-055 | 测试 | 变体测试单测（prompt 注入/默认零回归/自洽同口径/变体定义/指标/CLI/对比表）12 项 | ✅ |
| specs/adr/0011-prompt-eval-optimization.md | module-055 | 文档 | ADR-0011 提示词评估优化（四维评估 + 业界工具扫描 + 四代算法三步落地：变体测试→OPRO→DSPy；第一步已实施） | ✅ |
| specs/module-055-prompt-eval/ | module-055 | 规划 | 模块文档（plan/acceptance/changelog，review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/eval/build_intent_dataset.py | module-056 | 脚本 | 人造意图训练集构造（337 条三类平衡 + 边界易混 32 含 E2E bug 类 + 专有术语 40 + 口语化 24；docstring 标注指南；build 校验含与评测集零重叠防泄漏） | ✅ |
| ai_service/eval/intent_train_dataset.json | module-056 | 数据 | 人造意图训练集落盘（337 条 [{"query","intent","note"?}]，训练/评测分离） | ✅ |
| ai_service/tests/test_intent_dataset.py | module-056 | 测试 | 数据集结构/类别平衡/边界样本/E2E bug query/训练评测分离/L4 回退三路径单测 11 项 | ✅ |
| ai_service/models/intent_clf.joblib | module-056 | 产物 | L4 分类器模型（bge-m3 冻结 + 逻辑回归，449 条训练落盘；训练产物不进仓库） | ✅ |
| specs/module-056-intent-classifier-live/ | module-056 | 规划 | 模块文档（plan/acceptance/changelog，review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/eval/benchmark_rrf_k.py | module-057 | 代码 | RRF k 扫描 + 图谱贡献归因（k=20-100 步长 10 拐点加密；两通道 vs 三通道 RRF；通道候选每题只收集一次逐 k 纯 CPU 融合；eval_runs 'rrf_k_scan'） | ✅ |
| ai_service/eval/flywheel_smoke.py | module-057 | 脚本 | 飞轮冒烟（自造对话 → 真实 HTTP chat → POST /ai/feedback 👍👎 → feedback 表落库验证 → 防重复如实记录；数据保留为飞轮种子 identity=203.0.113.66 / message_id 990000+i 构造标识） | ✅ |
| ai_service/tests/test_nli_improve.py | module-057 | 测试 | 矛盾改进单测（句切/低置信降级/最严聚合/拆解判定管线/阈值扫描/样本集扩充 ≥50 internal≥20 且首 56 保持 module-054 同集）30 项 | ✅ |
| ai_service/tests/test_benchmark_rrf_k.py | module-057 | 测试 | RRF 融合纯函数单测（公式/两三通道/缺路/k 敏感/图谱按 hybrid_score 排序）8 项 | ✅ |
| specs/module-057-data-validation-batch/ | module-057 | 规划 | 模块文档（plan/acceptance/changelog，review/test-report 由 Reviewer/Tester 产出） | ✅ |

## 三、前端核心文件（frontend/，module-003+）

| 文件路径 | 模块 | 类型 | 内容摘要 | 状态 |
|----------|------|------|----------|------|
| frontend/src/pages/ChatPage.tsx | module-006/029 | 代码 | 聊天页（流式 + Agent 工具轨迹） | ✅ |
| frontend/src/components/PipelinePanel.tsx | module-010/029 | 代码 | 管线面板（含工具轨迹步骤） | ✅ |
| frontend/src/components/LLMChainPanel.tsx | module-029 | 代码 | LLM 供应商排序 UI | ✅ |
| frontend/src/services/ragService.ts | module-006/029 | 代码 | RAG API（chatStream/agentStream/chain） | ✅ |
| frontend/src/pages/KnowledgePage.tsx | module-008 | 代码 | 知识库管理 | ✅ |
| frontend/src/pages/ResumePage.tsx | module-003 | 代码 | 简历展示 | ✅ |

## 四、模块产出（specs/，按模块目录索引）

| 模块 | 目录 | 状态 |
|------|------|------|
| module-001 ~ 017 | specs/module-0XX-*/ | ✅ 基础 + RAG 核心 |
| module-018 | specs/module-018-rerank-fix/ | ✅ Rerank 修复 |
| module-019 | specs/module-019-eval-golden/ | ✅ 评估闭环 |
| module-020 | specs/module-020-fts-chinese/ | ✅ 中文 FTS |
| module-021 | specs/module-021-graph-score/ | ✅ 图分数 |
| module-022 | specs/module-022-cache-fix/ | ✅ 缓存修复 |
| module-023 | specs/module-023-memory/ | ✅ 长期记忆 |
| module-024 | specs/module-024-latency/ | ✅ 延迟优化 |
| module-025 | specs/module-025-stream-memory/ | ✅ 流式记忆 |
| module-026 | specs/module-026-retriever-reflector/ | ✅ 并发+Reflector |
| module-027 | specs/module-027-embedding-lock/ | ✅ 嵌入并发 |
| module-028 | specs/module-028-agent-tools/ | ✅ Agent 工具化 |
| module-029 | specs/module-029-frontend-enhance/ | ✅ 前端增强 |
| module-030 | specs/module-030-rerank-langgraph/ | ✅ 重排+LangGraph |
| module-031 | specs/module-031-knowledge-reindex/ | ✅ 知识库重建 + chunker Option C |
| module-032 | specs/module-032-jwt-login/ | ✅ JWT 登录体系（HS256 显式签名修复后 40/40） |
| module-033 | specs/module-033-long-term-memory/ | ✅ 长期记忆自动写入（Tester 验收 40/40，含真实 HTTP 端点 E2E 复验，2026-08-06） |
| module-034 | specs/module-034-short-session-memory/ | ✅ 短期记忆+会话记忆（Tester 验收 36/36，2026-08-06） |
| module-035 | specs/module-035-score-calibration/ | ✅ 分数口径校准（Tester 验收通过，35 项 32 通过 + 3 P3 不适用，2026-08-06） |
| module-036 | specs/module-036-agent-memory/ | ✅ Agent 端点接入会话记忆（Tester 验收 29/29，全量 298/0 + 真实 E2E，2026-08-07） |
| module-050 | specs/module-050-factcheck-compare/ | ✅ 幻觉检测模型对比（HHEM 0.77 vs MiniCheck 0.51；MiniCheck 中文退化）+ WP5 目录细分（rag 三子包 + scripts/），全量 579/0（2026-08-11） |
| module-051 | specs/module-051-hhem-judge/ | ✅ verify_answer 接入 HHEM 专职裁判（LLM 拆句 + HHEM 判分三态 + 降级链 + kappa 评测），kappa 0.3252 未达门槛如实标注，全量 611/0（2026-08-11） |
| module-052 | specs/module-052-nli-contradiction-scan/ | ✅ NLI 矛盾扫描前置决策（mDeBERTa-v3 中文实测 kappa 0.4711 vs HHEM 0.1351 → 替换方向推荐，ADR-0010 P1-③ 选型结论），全量 645/0（2026-08-12 Tester 复跑；在途快照 628/1 系 module-053 并行改造，非本模块回归） |
| module-053 | specs/module-053-rrf-fusion/ | ✅ 检索融合升级（RRF 三通道消融验证：基线复测 0.9714 + RRF 0.9905 放行推荐启用 + 加权两组持平否决 + DB 修复 + 嵌入路径回归修复），全量 645/0（2026-08-12） |

> 每个模块目录含 plan.md / acceptance-criteria.md / changelog.md / review-report.md / test-report.md。
