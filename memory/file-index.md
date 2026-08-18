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
| ai_service/mcp_server.py | module-067 | 代码 | MCP 适配层（READ_ONLY_TOOLS 6 名显式白名单 + build_server(registry, groups=None) 动态注册 + exec 动态参数模型（JSON Schema→type hints，必填排前可选排后 + None 剔除）+ 轻量 SimpleNamespace ctx（identity="mcp"）+ 截断 2000 + mcp_http_lifespan（Mount 不转发 lifespan 的任务组复刻）+ stdio 入口；FastMCP 1.26.0 适配：stateless_http/json_response 构造参数/streamable_http_path="/"/无 version/DNS rebinding 关闭） | ✅ |
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
| ai_service/eval/benchmark_rrf_k.py | module-057 | 代码 | RRF k 扫描 + 图谱贡献归因（k=20-100 步长 10，最优 k±5 邻域补 k=25；曲线全平坦无拐点；两通道 vs 三通道 RRF；通道候选每题只收集一次逐 k 纯 CPU 融合；eval_runs 'rrf_k_scan'） | ✅ |
| ai_service/eval/flywheel_smoke.py | module-057 | 脚本 | 飞轮冒烟（自造对话 → 真实 HTTP chat → POST /ai/feedback 👍👎 → feedback 表落库验证 → 防重复如实记录；数据保留为飞轮种子 identity=203.0.113.66 / message_id 990000+i 构造标识） | ✅ |
| ai_service/tests/test_nli_improve.py | module-057 | 测试 | 矛盾改进单测（句切/低置信降级/最严聚合/拆解判定管线/阈值扫描/样本集扩充 ≥50 internal≥20 且首 56 保持 module-054 同集）32 项 | ✅ |
| ai_service/tests/test_benchmark_rrf_k.py | module-057 | 测试 | RRF 融合纯函数单测（公式/两三通道/缺路/k 敏感/图谱按 hybrid_score 排序）8 项 | ✅ |
| specs/module-057-data-validation-batch/ | module-057 | 规划 | 模块文档（plan/acceptance/changelog，review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/src/observability.py | module-058 | 代码 | 请求可观测性（contextvar 观测上下文：trace_id/timing/usage/cache 计数 + save_request_log fail-open 落库 + TraceIdFilter/install_trace_id_filter 日志 record.trace_id 注入；PW_REQUEST_LOGS 默认 true 关闭零埋点零落库；不引入新依赖） | ✅ |
| ai_service/scripts/probe_prefix_cache.py | module-058 | 脚本 | WP-B 前缀缓存探测（真实 deepseek：单文档 <1024 token 未达缓存门槛 / 多文档 3001 token 同 docs 二次生成 billed miss -98% 命中；verify 口径核实 LLM 只拆句） | ✅ |
| ai_service/scripts/probe_request_trace.py | module-058 | 脚本 | WP-C 真实 trace 样例（init_db 幂等建 request_logs + 真实 chat 全阶段计时/token 采集 + 落库查回；清理探测身份记忆行保留样例行） | ✅ |
| ai_service/tests/test_prompt_order.py | module-058 | 测试 | prompt 区块顺序单测（sections→docs→query 顺序/标签格式不变/空 sections 零漂移/历史段仍最前）6 项 | ✅ |
| ai_service/tests/test_tool_phase_split.py | module-058 | 测试 | 工具阶段切分单测（检索组 7/生成组 4/re_search 双组/group 元数据/初始 phase/advance_phase 单元/schemas_for_phase/调生成后下一轮切 generation/re_search 不回退/开关 false 全量 10/预算路径不变/langgraph 同步/_SYSTEM_PROMPT）18 项 | ✅ |
| ai_service/tests/test_observability.py | module-058 | 测试 | 可观测性单测（timing/usage 累积/缓存命中计数/engine.chat 全阶段计时/request_logs 幂等落库/fail-open/端点 trace 接线/开关零埋点 + Review 修复：TraceIdFilter 日志 record.trace_id 注入/install 幂等/chat_with_tools 用量按供应商标签）16 项 | ✅ |
| specs/module-058-retrieval-chain-opt/ | module-058 | 规划 | 模块文档（plan/acceptance/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/src/verify_tasks.py | module-060 | 代码 | verify 后台任务池 + verify_results 表读写（submit_verify_task 先插 pending → create_task 调度返回 task_id + _run_verify 成功/失败落库 + get_verify_task 读 DB 为准；内存池只持执行期中间态、done callback 释放、DB 结果不清理飞轮数据源；PW_VERIFY_ASYNC 开关关闭返回 None） | ✅ |
| ai_service/tests/test_verify_tasks.py | module-060 | 测试 | verify 异步化单测（submit 返回 uuid/pending 落库/后台执行/释放/异常 failed/开关关 None/pending 落库失败 fail-open/get 读 DB 四态/DDL 幂等/轮询端点状态机 pending/done/failed/404/chat_stream 开关两分支）17 项 | ✅ |
| specs/module-060-verify-async/ | module-060 | 规划 | 模块文档（plan/acceptance/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| specs/adr/0013-verify-async.md | module-060 | 文档 | ADR-0013 verify 异步化决策（轮询送达 + 落库持久化 + 非流式保持同步 + 计时口径变化；✅ 已实施 2026-08-13） | ✅ |
| ai_service/rag/memory/nli_loader.py | module-061 | 代码 | mDeBERTa NLI 本地加载器（镜像 eval compare_nli_models 已验证 transformers 5.x 路径单一来源，HF_HUB_OFFLINE + AutoModelForSequenceClassification fp32 + id2label 从 config；require_nli_model 缺文件明确报错；顶层零重依赖） | ✅ |
| ai_service/rag/memory/nli_judge.py | module-061 | 代码 | 记忆冲突 NLI 裁判封装（MemoryNLIJudge：延迟加载 557MB + threading.Lock + to_thread + 20s 超时 + 失败/超时返回 None 降级；复用 nli_loader；对齐 factcheck_judge 模式） | ✅ |
| ai_service/eval/memory_conflict_dataset.py | module-061 | 代码 | 记忆冲突 NLI 评测（30 条五类标注集：改口/迁移/过时/升级冲突/正例中性 + contradiction P/R/F1 + 达标判定 Recall≥0.8 且 Precision≥0.8 + --fixture 关键词启发式 + eval_runs 'memory_conflict'；真实 baseline id=31 Accuracy 0.60/P 1.0000/R 0.5000 未达门槛） | ✅ |
| ai_service/tests/test_memory_correction.py | module-061 | 测试 | 记忆纠错单测（P0 升级留短期副本/superseded 标记与幂等/召回过滤 + P1 三分类分流/矛盾 SUPERSEDED+新增/一致追加/NLI None 降级/开关关零回归 + nli_judge 封装 + 评测基线一致性，mock NLI 不加载真实模型）27 项 | ✅ |
| ai_service/scripts/migrate_module061.py | module-061 | 脚本 | DB 迁移（documents 补 superseded/updated_at 两列幂等，查 information_schema 已存在则跳过 + 校验输出；本地开发库 schema 未迁移先决，module-046 经验） | ✅ |
| specs/module-061-memory-correction/ | module-061 | 规划 | 模块文档（plan/acceptance/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/rag/memory/memory_type_clf.py | module-062 | 代码 | 记忆类型分类器（MemoryTypeClassifier：bge-m3 冻结特征 + LR 三分类 preference/fact/event + resolve_memory_type 按 memory_type_mode(clf/llm/none) 生产注入，clf 失败回退 llm_type→fact；落盘 models/memory_type_clf.joblib） | ✅ |
| ai_service/rag/memory/memory_conflict_clf.py | module-062 | 代码 | 记忆矛盾分类器（MemoryConflictClassifier：新旧两条 bge-m3 嵌入→拼接+差值+绝对差 4096 维 + LR 二分类 contradiction/non_conflict；落盘 models/memory_conflict_clf.joblib） | ✅ |
| ai_service/eval/build_memory_type_dataset.py | module-062 | 脚本 | 人造记忆类型训练集构造（120 条 40/40/40，与评测集零重叠校验强制，落盘 memory_type_train_dataset.json） | ✅ |
| ai_service/eval/memory_type_dataset.py | module-062 | 评测 | 记忆类型评测（30 条 10/10/10 + clf vs LLM 同集对比 Accuracy/P/R/F1 + 达标判定 Accuracy≥0.8 + --fixture/--clf-only + eval_runs 'memory_type' 含 model 字段；实测 clf 1.0000/LLM 1.0000 id=32/33） | ✅ |
| ai_service/eval/build_memory_conflict_train.py | module-062 | 脚本 | 人造记忆矛盾训练集构造（142 条 contradiction 82/non_conflict 60，与评测集零重叠校验强制，落盘 memory_conflict_train_dataset.json） | ✅ |
| ai_service/scripts/train_memory_type_clf.py | module-062 | 脚本 | 记忆类型分类器训练（人造 120 条，bge-m3+LR，落盘 models/memory_type_clf.joblib，test split Accuracy 1.0000） | ✅ |
| ai_service/scripts/train_memory_conflict_clf.py | module-062 | 脚本 | 记忆矛盾分类器训练（人造 142 条，落盘 models/memory_conflict_clf.joblib，test split contradiction Precision 0.90/Recall 0.95） | ✅ |
| ai_service/scripts/migrate_module062.py | module-062 | 脚本 | DB 迁移（documents 补 type/last_recalled_at 两列幂等，查 information_schema 已存在则跳过；本地库已执行） | ✅ |
| ai_service/tests/test_memory_evolution2.py | module-062 | 测试 | 记忆进化 2 单测（extract_facts type/分类器推理/resolve_memory_type 三模式/类型化半衰期/冷降权系数·下限·存量·开关·DB 失败·重排·刷新/recall 集成/save 写 type/类型注入/裁判切换/评测基线一致性/DDL 幂等/配置）70 项 | ✅ |
| specs/module-062-memory-evolution2/ | module-062 | 规划 | 模块文档（plan/acceptance/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/eval/golden/golden_multi_turn.py | module-063 | 评测 | 多轮追问评测（12 对三指标：自包含清晰度/意图保持（多轮路由 vs 单句对照）/检索提升（prev 检索作锚点重叠度）；--fixture 启发式改写+意图 / --no-save / eval_type='multi_turn' 落库；真实 deepseek+DB 实测意图保持 12/12、检索 +0.4363） | ✅ |
| ai_service/tests/agent/test_multi_turn_routing.py | module-063 | 测试 | 多轮意图路由单测（WP-A 空历史零回归/LLM 上下文/L4 prev 拼接 2048 维/L4+L2 修正 + WP-B 去语气词/短句继承/话题漂移不继承/单轮不继承/有特征正常路由/链式继承/history[-6:] + WP-C engine 改写喂路由/precise 短路/失败回退/默认关零回归/流式+LangGraph 接 history + WP-D 工具信号/轨迹不可得跳过）35 项 | ✅ |
| ai_service/tests/eval/test_golden_multi_turn.py | module-063 | 测试 | golden_multi_turn 评测脚本单测（数据集校验/启发式改写+意图/重叠度/三指标纯函数/fixture 运行/非法集校验）19 项 | ✅ |
| specs/module-063-multi-turn-intent-routing/ | module-063 | 规划 | 模块文档（plan/acceptance/task-brief/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| ai_service/rag/retrieval/document_parser.py | module-064 | 代码 | 统一文档解析层（parse_document(bytes,filename)→Markdown；格式识别读字节魔数 anydoc.format_from_bytes + 扩展名兜底；AnyDoc 主解析 + PyMuPDF PDF 回退 + docx/xlsx/csv 轻量回退 + pptx/epub 明确报错；错误变体 Unsupported/Malformed/Encrypted 映射中文提示；SUPPORTED_EXTENSIONS 8 格式） | ✅ |
| ai_service/rag/retrieval/document_cleaner.py | module-064 | 代码 | 五步清洗层（clean 白名单哲学按块类型作用：code/math/table/body 四区域 + 正文内联 ⟦N⟧ 占位符保护；格式清理/冗余过滤/⭐结构恢复合并 PDF 断行/语义修复 OCR_TYPO_MAP 空表/分块准备 `#`→`##`）+ 无损归一化（normalize NFKC/去零宽/统一空白/表格保持 MD/超长截断） | ✅ |
| ai_service/rag/retrieval/image_pipeline.py | module-064 | 代码 | PDF 内嵌图片三层开关（PW_IMAGE_OCR / PW_IMAGE_CAPTION / PW_PDF_ENGINE=mineru 全默认关 + 占位符替换 + 图片价值过滤 image_value_filter 接口 + fail-open；扫描版无文本层如实附"图片未解析"提示） | ✅ |
| ai_service/rag/retrieval/document_dedup.py | module-064 | 代码 | 文档去重三级（L1 exact_hash 文档级 sha256 / L2 find_semantic_duplicate bge-m3 绝对余弦≥0.95 标簇 + strip_boilerplate 先剥离 / L3 simhash_lsh 接口预留；compute_doc_embedding async await embed_text） | ✅ |
| ai_service/rag/retrieval/document_ingest.py | module-064 | 代码 | ingestion 管线编排（parse→图片→clean→normalize→L1 去重→原件落盘 save_original→L2 标簇→rag_engine.add_document；各层失败 fail-open 不阻断入库；无有效文本明确报扫描版/纯图片无 OCR） | ✅ |
| ai_service/scripts/migrate_module064.py | module-064 | 脚本 | DB 迁移（documents 补 original_path/doc_content_hash/duplicate_cluster_id/is_canonical 四列 + 2 索引幂等；本地库已执行） | ✅ |
| ai_service/tests/core/test_document_parser.py | module-064 | 测试 | 解析层单测（格式识别/纯文本解码/AnyDoc mock/错误映射/分层回退/上传端点接线）21 项 | ✅ |
| ai_service/tests/core/test_document_cleaner.py | module-064 | 测试 | 清洗层 + 归一化单测（白名单不误伤/页码含 PyMuPDF 分页标记/断行合并/标题规范化/NFKC/表格保持/截断/chunker 零破坏）26 项 | ✅ |
| ai_service/tests/core/test_document_dedup.py | module-064 | 测试 | 去重三级单测（exact_hash/boilerplate/余弦/语义命中与 miss/fail-open/跨源排除/SimHash 预留）15 项 | ✅ |
| ai_service/tests/core/test_document_ingest.py | module-064 | 测试 | ingestion 管线单测（成功字段透传/L1 exact 丢弃/L2 语义标簇/无有效文本报错/入库侧向量剥离 Boilerplate 同查询侧口径）5 项 | ✅ |
| ai_service/tests/core/test_document_image.py | module-064 | 测试 | PDF 图片三层开关直接单测（Review 修复轮补齐：extract_image_refs Markdown/HTML 提取去重 + image_value_filter 三阈值 + 三层默认关原样返回 + L1/L2 缺失占位符替换附注 fail-open + L3 MinerU 未装降级 + 扫描版"图片未解析"提示）18 项 | ✅ |
| specs/module-064-document-parsing-cleaning/ | module-064 | 规划 | 模块文档（plan/acceptance/task-brief/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| specs/adr/0014-document-parsing-cleaning.md | module-064 | 文档 | ADR-0014 多格式解析 + 清洗 + 去重决策（✅ 已实施 2026-08-14：AnyDoc 统一解析 + 五步清洗白名单 + 无损归一化 + PDF 图片三层默认关 + original_path 原件留存 + 去重三级 + canonical 抑制） | ✅ |
| ai_service/eval/benchmarks/benchmark_embed_write.py | module-065 | 脚本 | 写入侧嵌入性能基准（WP1 探路证伪固化：循环 vs List 批量 10/50/200 + 串行 vs 多进程 2/4×200，--quick/--no-mp；实测批量 ~1.0x 无加速、多进程 0.4x/0.3x 负优化——写入吞吐为 bge-m3 Q8 固有成本，生产零改动） | ✅ |
| ai_service/eval/benchmarks/benchmark_public_retrieval.py | module-065 | 脚本 | 公开基准检索评测（WP3：BEIR nfcorpus / C-MTEB EcomRetrieval 中文；hf-mirror 直链下载缓存 eval/datasets/public/ gitignored + bge-m3 余弦暴力检索 + Hit@5/MRR/nDCG@10 trec 口径 + eval_runs 落库；--corpus-sample 固定种子抽样代理口径，--corpus-sample 0 全量待 GPU 环境） | ✅ |
| ai_service/rag/retrieval/document_dedup.py | module-065 | 代码 | WP4 minor-1：find_semantic_duplicate 候选查询过滤 is_canonical=True（非 canonical 副本不参与比对，对齐检索抑制语义） | ✅ |
| ai_service/tests/core/test_document_dedup.py | module-065 | 测试 | WP4 minor-1 单测（+1：is_canonical IS true SQL 编译捕获断言，15→16 项） | ✅ |
| specs/module-065-ingest-perf-and-e2e/ | module-065 | 规划 | 模块文档（plan/acceptance/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| specs/module-066-agent-evaluation/ | module-066 | 规划 | 模块文档（plan/acceptance/changelog 已产出 2026-08-17；review-report 已产出 2026-08-17 Reviewer ✅ Pass；test-report 由 Tester 产出）。产出文件：ai_service/src/database.py（tool_call_logs 表 DDL + ensure + init_db 挂接）/ ai_service/agent/react.py + langgraph_react.py（execute_tool_with_log 执行处落库）/ ai_service/src/config.py（tool_call_logs_enabled PW_TOOL_CALL_LOGS 默认 true）/ ai_service/eval/agent_tasks.json（36 条任务集六类路径）/ ai_service/eval/agent_tasks.py（三层指标评测 + agent_eval_runs 落库）/ ai_service/tests/agent/test_tool_call_logs.py（12 项）/ ai_service/tests/eval/test_agent_tasks.py（26 项） | ✅ |
| ai_service/src/database.py | module-066 | 代码 | +TOOL_CALL_LOGS_DDL + ensure_tool_call_logs_table + init_db 挂接（对齐 feedback/request_logs 幂等模式，ADR-0017 决策 2 结构一字不改） | ✅ |
| ai_service/src/config.py | module-066 | 配置 | +tool_call_logs_enabled（PW_TOOL_CALL_LOGS，默认 true，与 request_logs 同生命周期） | ✅ |
| ai_service/agent/react.py | module-066 | 代码 | +execute_tool_with_log/record_tool_call（计时包住 run + result_ok 语义 + fail-open 落库；react_loop 与 langgraph 共用防漂移）+ react_loop 执行处接线（循环逻辑/事件格式零改动） | ✅ |
| ai_service/agent/langgraph_react.py | module-066 | 代码 | execute_tools 节点同构接线（复用 execute_tool_with_log） | ✅ |
| ai_service/eval/agent_tasks.json | module-066 | 数据 | Agent 任务级评测集 36 条（六类路径：knowledge 单轮 17/多轮 7/casual 3/realtime 3/重检 3/记忆 3；id/task（可数组）/expected_tools/answer_points） | ✅ |
| ai_service/eval/agent_tasks.py | module-066 | 代码 | Agent 任务级评估脚本（三层指标 pass^k·工具正确率·步数/token/P50-P95 + 判定器四规则确定性 + --mode chat|agent/--sample 种子 42/--pass_k/--limit/--no-save/--fixture 假 LLM 回放 + agent_eval_runs 落库 eval_type='agent_eval' + 评测身份 eval-066-anon 测后清理） | ✅ |
| ai_service/tests/agent/test_tool_call_logs.py | module-066 | 测试 | tool_call_logs 落库单测（DDL 幂等/成功落库/截断 200/args 兜底/开关 false 零开销/fail-open/result_ok 语义/react+langgraph 接线只记实际执行/trace_id contextvar）12 项 | ✅ |
| ai_service/tests/eval/test_agent_tasks.py | module-066 | 测试 | 任务集 schema 校验/六类路径/阶段顺序/判定器四规则/outcome/失败分类/指标聚合/percentile/fixture 全量确定性/chat 无轨迹/grounding 读回/清理/agent_eval_runs 落库/CLI no-save 26 项 | ✅ |
| ai_service/tests/api/test_mcp_server.py | module-067 | 测试 | MCP 单测 27 项（build_server 注册遍历/只读过滤 4 非只读不在列/显式 groups/description 透传/schema 三变体+未知 type+default/截断 3/执行 8（结果/ctx/失败包装/None 剔除/ToolError 校验）/HTTP 认证 6（无/错/对 401-401-200 + 307 + 空 token 恒 401 + 改 token 即时生效）/lifespan fail-closed raise） | ✅ |
| ai_service/rag/retrieval/document_parser.py | module-069 | 代码 | 新增 `_reorder_columns(page)` 纯函数（双栏中线重组：get_text("blocks") + 双栏检测左右各>=2 + 跨中线块置顶 + 跨栏表格 | 跳过）+ `_parse_pdf_pymupdf` 开关 pdf_fallback_md（true=pymupdf4llm.to_markdown() / false=旧 get_text()）+ 延迟导入降级 | ✅ |
| ai_service/src/config.py | module-069 | 配置 | +pdf_fallback_md（PW_PDF_FALLBACK_MD，默认 true，false 回退旧 get_text()） | ✅ |
| ai_service/tests/conftest.py | module-069 | 测试 | +default_pdf_fallback_md_disabled autouse fixture（钉住测试环境 false） | ✅ |
| ai_service/tests/core/test_document_parser.py | module-069 | 测试 | +15 项（TestReorderColumns 7 + TestPdfFallbackMdSwitch 5 + TestColumnReorderIntegration 3，21→36 项） | ✅ |
| specs/module-069-pdf-fallback-upgrade/ | module-069 | 规划 | 模块文档（plan/acceptance/task-brief/changelog；review/test-report 由 Reviewer/Tester 产出） | ✅ |
| specs/module-067-mcp-integration/ | module-067 | 规划 | 模块文档（plan/acceptance/task-brief/changelog 已产出 2026-08-17 Developer；review-report 已产出 2026-08-17 Reviewer ✅ Pass，test-report 由 Tester 产出）。产出文件：ai_service/mcp_server.py / ai_service/main.py（+挂载 /ai/mcp + _mcp_auth_middleware + lifespan fail-closed + mcp_http_lifespan 接入）/ ai_service/src/config.py（+mcp_token）/ ai_service/requirements.txt（+mcp==1.26.0）/ ai_service/tests/api/test_mcp_server.py（27 项） | ✅ |

## 三、前端核心文件（frontend/，module-003+）

| 文件路径 | 模块 | 类型 | 内容摘要 | 状态 |
|----------|------|------|----------|------|
| frontend/src/pages/ChatPage.tsx | module-006/029 | 代码 | 聊天页（流式 + Agent 工具轨迹） | ✅ |
| frontend/src/components/PipelinePanel.tsx | module-010/029 | 代码 | 管线面板（含工具轨迹步骤） | ✅ |
| frontend/src/components/LLMChainPanel.tsx | module-029 | 代码 | LLM 供应商排序 UI | ✅ |
| frontend/src/services/ragService.ts | module-006/029 | 代码 | RAG API（chatStream/agentStream/chain） | ✅ |
| frontend/src/pages/KnowledgePage.tsx | module-008 | 代码 | 知识库管理 | ✅ |
| frontend/src/pages/ResumePage.tsx | module-003 | 代码 | 简历展示 | ✅ |
| frontend/src/pages/ChatPage.tsx | module-006/029/060 | 代码 | 聊天页（流式 + Agent 工具轨迹 + **verify 异步轮询**：verifying 状态 + startVerifyPolling 2s/30 次上限 + done 更新 verifiedClaims + failed/404 fail-open + 生命周期清理；handleRetry 补齐与 doSend 一致） | ✅ |
| frontend/src/services/ragService.ts | module-006/029/060 | 代码 | RAG API（chatStream/agentStream/chain + **chatStream 解析 done verify_task_id + fetchVerifyResult 轮询接口 404 归一化 failed**） | ✅ |
| frontend/src/types/rag.ts | module-006/060 | 代码 | RAG 类型（**ChatResponse.verifyTaskId + VerifyTaskResult**） | ✅ |
| frontend/src/types/conversation.ts | module-009/060 | 代码 | 消息类型（**MessageDTO.verifying**） | ✅ |
| frontend/src/components/ChatMessage.tsx | module-006/048/060 | 代码 | 消息气泡（👍👎 反馈 + **verifying prop "正在验证…"提示**） | ✅ |

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
| module-060 | specs/module-060-verify-async/ | ✅ verify 异步化（ADR-0013：chat_stream 异步 verify + done 带 verify_task_id + 前端轮询补结果 + verify_results 表持久化），单测 17/0 + 前端 58/0 + build PASS；真实 E2E 待环境（本机无 PostgreSQL）（2026-08-13 Developer 产出） |
| module-061 | specs/module-061-memory-correction/ | ✅ 记忆纠错（ADR-0007 P0+P1：P0 升级留后悔药——升级不删短期副本 + 长期 superseded/updated_at + 召回过滤；P1 写路径冲突消解——mDeBERTa NLI 判矛盾 → 旧父块 SUPERSEDED 不删除 + 新内容正常新增，PW_MEMORY_CONFLICT 默认 false 评测达标才启用；真实 baseline id=31 Accuracy 0.60/P 1.0000/R 0.5000 未达门槛如实标注），全量 824/0 = 797 基线 + 27 新增 + 存量 2 项按验收许可更新（2026-08-13 Developer 产出） |
| module-062 | specs/module-062-memory-evolution2/ | ✅ 记忆进化 2（ADR-0007 P2 类型化衰减——documents.type + _evolve_recall 按 type 半衰期 preference 30/event 1/其余 3 + 类型来源 clf 1.0000/LLM 1.0000 同分取 clf memory_type_mode=clf + P3 冷记忆降权——documents.last_recalled_at + 长期层久未召回 ×0.3-1.0 不删除 + 刷新升温 + WP4 矛盾检测启用——142 案例 clf Precision 0.9048 vs mDeBERTa Precision 1.0，按用户规则取 Precision 高者 → PW_MEMORY_CONFLICT=true + JUDGE=nli），全量 895/0 = 825 基线 + 70 新增 + 存量 test_memory_extractor 3 处精确结构断言按验收许可补 type 字段（2026-08-13 Developer 产出） |
| module-063 | specs/module-063-multi-turn-intent-routing/ | ✅ 多轮对话意图路由升级（ADR-0015：会话级路由 classify(query,history[-6:]) + LLM 上下文 + L4 拼接 2048 维（未重训默认关）+ 短句继承（去语气词 <6 无特征零 LLM）+ 改写提前喂路由（非流式）+ 工具历史信号 + L4 路径补 L2 确定性信号 + golden_multi_turn 12 对三指标实测：意图保持 12/12 / 检索 +0.4363），全量 **951/0** = 897 基线 + 54 新增（test_multi_turn_routing 35 + test_golden_multi_turn 19，存量零改动），真实 E2E 两轮"为什么"→knowledge 走检索链路（2026-08-14 Developer 产出） |
| module-066 | specs/module-066-agent-evaluation/ | ✅ Agent 级评估体系（ADR-0017：tool_call_logs 工具明细落库（react/langgraph 两循环执行处）+ agent_tasks.json 36 条六类路径 + eval/agent_tasks.py 三层指标 pass^k·工具正确率·步数/token/P50-P95 + agent_eval_runs 版本化落库 + 确定性判定），全量 **1075/0** = 1037 基线 + 38 新增（test_tool_call_logs 12 + test_agent_tasks 26，存量零改动仅 conftest 加 autouse 钉住开关）；真实冒烟发现 generate_answer 在默认阶段切分下循环内不可达（Agent 行为盲区如实标注；Tester 实测归因修正为"schema 不引导调用"）（2026-08-17 Developer 产出） |
| module-067 | specs/module-067-mcp-integration/ | ✅ MCP 集成（ADR-0018：ToolRegistry → 标准 MCP Server），全量 **1102/0** = 1075 基线 + 27 新增（test_mcp_server.py，存量零改动；scripts/test_models.py 1 项 module-050 遗留 ERROR 未触碰）；真实冒烟全过（stdio client 6 工具 + search_knowledge 真实检索 / HTTP 401-401-200 / fail-closed 启动拒绝 / mcp dev 可启）；产出：ai_service/mcp_server.py（READ_ONLY_TOOLS 白名单 + build_server + exec 参数模型 + 轻量 ctx + 截断 2000 + mcp_http_lifespan + stdio 入口）+ main.py 挂载/认证/fail-closed + config mcp_token + requirements mcp==1.26.0（2026-08-17 Developer 产出，待 Reviewer 审查） |
| module-068 | specs/module-068-agent-phase-fix/ | ✅ Agent 阶段推进死锁修复（Developer 产出 + Reviewer 第二轮复审通过（PASS）2026-08-17，plan.md + acceptance-criteria.md + changelog.md + review-report.md 已产出；第一轮 mustFix 1 项（changelog §三 勘误两处论证与硬证据矛盾须重写并列报告 id=2）Developer v3 已修复并经验证；plan 矛盾点 §五 6 处存量断言更新 Reviewer 已裁定接受；待 Tester 验收）。产出文件：specs/module-068-agent-phase-fix/changelog.md（WP-A~D + plan 矛盾点 §五 + WP-C 实测 §六 + §三勘误）。代码改动：ai_service/agent/react.py（_RETRIEVAL_HIT_TOOLS 6 清单 + _EMPTY_RESULT_MARKERS + _retrieval_hit 纯函数 + _phase_budget + advance_phase 向后兼容扩展（executed_results=None 缺省）+ ctx.retrieval_rounds/phase_count + react_loop 收集 results + 截断点 min(总剩余,阶段剩余)）/ ai_service/agent/langgraph_react.py（execute_tools 同构 + phase_exhausted 路由防死循环）/ ai_service/src/config.py（agent_retrieval_max_rounds=3/agent_retrieval_budget=3/agent_generation_budget=2 + max_agent_tools 4→5）/ ai_service/tests/agent/test_agent_phase_fix.py（新增 14 项）/ ai_service/tests/conftest.py（autouse 钉住 max_agent_tools=4）/ ai_service/tests/agent/test_tool_phase_split.py（6 处 schema 序列断言按新推进语义更新，plan 矛盾点如实记录）。**WP-C 实测**：agent_eval_runs id=3（2026-08-17 09:16 本地=01:16 UTC，默认配置 budget=5）pass^1=0.0 未提升如实记录——结构性修复生效（单测 + 轨迹阶段截断形态）但 deepseek 行为性残余（生成阶段 schema 下仍调 search_*，generate_answer 未入轨迹）；**§三勘误（Reviewer 复核纠正）**：id=2（23:58:57 UTC = 08-17 07:58 本地）晚于代码落地（react.py mtime 07:36）且多轮按轮预算 8=4+4——排除理由不成立，id=2 系 module-068 代码后运行（at-101 经 generate_answer 达 pass，pass^1=0.2），须并列报告 |
| module-069 | specs/module-069-pdf-fallback-upgrade/ | ✅ Reviewer **Pass**（第二轮 post-fix 2026-08-17；P1 文档同步已修复 + 4 项 minor 非阻塞；全量 1131/0；review-report.md 已更新；待 Tester）。产出文件：ai_service/rag/retrieval/document_parser.py（+`_reorder_columns` 纯函数 + `_parse_pdf_pymupdf` pymupdf4llm 开关改造）/ ai_service/src/config.py（+`pdf_fallback_md` PW_PDF_FALLBACK_MD 默认 true）/ ai_service/requirements.txt（+pymupdf4llm AGPL-3.0）/ ai_service/tests/conftest.py（+autouse 钉住 false）/ ai_service/tests/core/test_document_parser.py（+15 项 21→36） |

> 每个模块目录含 plan.md / acceptance-criteria.md / changelog.md / review-report.md / test-report.md。
