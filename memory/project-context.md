# 项目上下文记忆库

## 1. 项目概述
- 项目名称: personal-interview-website
- 项目简介: 融合简历展示与 Agentic RAG 知识库问答的个人网站系统（双语言微服务架构：Java Spring Boot + Python FastAPI + React 前端）
- 创建时间: 2026-07-29
- 最后更新: 2026-08-02

## 2. 技术栈
> 详见 `tech-stack.md`，此处仅保留摘要。
- 后端 (Java): Spring Boot 3.2 + MyBatis-Plus + PostgreSQL
- 前端: React 18 + TypeScript + Vite + Ant Design
- AI 层 (Python): FastAPI + LangChain + pgvector
- 中间件: Redis
- 向量库: pgvector (PostgreSQL 扩展)
- AI 供应商: OpenAI / Claude API
- 部署: Docker Compose

## 3. 已完成模块清单
| 模块编号 | 模块名称 | 版本号 | 完成时间 | 状态 |
|----------|----------|--------|----------|------|
| module-001 | 项目脚手架搭建 | 0.1.0-module-001 | 2026-07-29 | ✅ |
| module-002 | 简历数据模型与API | 0.2.0-module-002 | 2026-07-29 | ✅ |
| module-003 | 简历展示前端页面 | 0.3.0-module-003 | 2026-07-30 | ✅ |
| module-004 | Python AI 层基础架构 | 0.4.0-module-004 | 2026-07-30 | ✅ |
| module-005 | Agentic RAG 知识库核心 | 0.5.0-module-005 | 2026-07-30 | ✅ |
| module-006 | 前端知识库问答界面 + 文档上传 | 0.6.0-module-006 | 2026-07-30 | ✅ |
| module-008 | 知识库文档管理面板 | 0.8.0-module-008 | 2026-07-30 | ✅ |
| module-009 | 聊天记录持久化 | 0.9.0-module-009 | 2026-07-30 | ✅ |
| module-010 | RAG UI 优化 | 0.10.0-module-010 | 2026-07-30 | ✅ |
| module-013 | RAGAS Evaluation System | 0.13.0-module-013 | 2026-07-30 | ✅ |
| module-014 | HyDE Query Rewriting | 0.14.0-module-014 | 2026-07-30 | ✅ |
| module-015 | Redis Query Cache | 0.15.0-module-015 | 2026-07-30 | ✅ |
| module-016 | Graph RAG | 0.16.0-module-016 | 2026-07-30 | ✅ |
| module-017 | 父子分块检索 | 0.17.0-module-017 | 2026-07-31 | ✅ |
| module-018 | Rerank 重排修复（切换 Qwen3-Reranker） | 0.18.0-module-018 | 2026-08-01 | ✅ |
| module-019 | 评估闭环（Golden 检索集 + Hit@k/MRR + 消融） | 0.19.0-module-019 | 2026-08-01 | ✅ |
| module-020 | 中文 FTS 复活（jieba 预分词） | 0.20.0-module-020 | 2026-08-01 | ✅ |
| module-021 | 图分数归一化（graph_score 真实相关度） | 0.21.0-module-021 | 2026-08-01 | ✅ |
| module-022 | 检索缓存修复（key 参数化 + 失效策略） | 0.22.0-module-022 | 2026-08-01 | ✅ |
| module-023 | 长期记忆（跨会话记忆沉淀） | 0.23.0-module-023 | 2026-08-01 | ✅ |
| module-024 | 检索延迟优化（超时收敛 + HyDE 缓存 + 提前终止） | 0.24.0-module-024 | 2026-08-01 | ✅ 完成（测试通过 2026-08-01） |
| module-025 | 流式记忆接入（chat_stream 记忆注入） | 0.25.0-module-025 | 2026-08-01 | ✅ 完成（测试通过 2026-08-01） |
| module-026 | 检索并发修复 + Reflector 改造（低温度 + 走降级链） | 0.26.0-module-026 | 2026-08-01 | ✅ 完成（测试通过 2026-08-01） |
| module-027 | 嵌入并发修复 + backlog 收敛 | 0.27.0-module-027 | 2026-08-02 | ✅ 完成（测试通过 2026-08-02） |
| module-028 | Agent 工具化（ToolRegistry + ReAct 循环） | 0.28.0-module-028 | 2026-08-02 | ✅ 完成（测试通过 2026-08-02） |

## 4. 架构决策记录（ADR）索引
| ADR 编号 | 决策标题 | 状态 | 日期 |
|----------|----------|------|------|
| — | — | — | — |

## 5. 当前迭代状态
- 当前迭代版本: v0.28.0
- 正在进行的模块: 无（module-028 已完成验收）
- 下一个待开发模块: 待定（候选：降级链动态调序 / LangGraph 接入）

## 7. 关键技术决策记录
- 所有 API 返回格式统一为 {code, msg, data, timestamp, request_id}（详见 CLAUDE.md 第5节）
- 使用 JWT 进行用户认证
- 后端 Java 与 AI 层 Python 通过 HTTP RESTful 接口解耦通信
- Java 端实现熔断降级（Python 服务超时后走兜底逻辑）
- PDF 文档解析使用 Unstructured / PaddleOCR
- 检索策略：BM25 + 向量检索 混合加权 → Rerank 重排
- Agent 具备意图识别路由、自我反思与纠错能力
- Rerank 模型：Qwen3-Reranker-0.6B（本地，module-018 决策；缺权重明确报错，不回退 HF）
- Qwen3-Reranker 调用约束（module-018）：生成式重排模型（Qwen3ForCausalLM），predict 需传 user 角色 chat 消息 `[{"role":"user","content":"<query>\n<doc>"}]` + `add_generation_prompt=True`，不可传 (query, doc) 裸 pair（本地 chat template 会渲染成空串崩溃）
- 技术债务（module-018 验收记录）：① 测试环境缺 `pytest-asyncio`，`tests/test_engine.py` 2 个 async 用例无法在 pytest 下收集运行（既有问题，非 module-018 回归）；② 外部 embedding API（ModelScope）当前返回 502，端到端检索联调受阻（既有问题，含容错降级）
- 检索基线（module-019 首次评估，2026-08-01）：FTS 通道中文查询 Hit@5=0（PG 'simple' 分词限制，既有问题，module-020 中文FTS修复的量化基线）；graph_only 通道 Hit@5=0.50 / Recall@5=0.4375 / MRR=0.2361；vector_only 因 embedding 502 无法评估；golden 集 30 题中 23 题有 gold 标注，7 题（简历类 5 + HTTP/2 + Docker）知识库无覆盖标注为空并跳过
- 中文 FTS 方案（module-020，2026-08-01）：jieba 预分词 → documents.search_tokens 列（TEXT，空格连接）→ `to_tsvector('simple', search_tokens)`；查询侧同用 jieba（plainto_tsquery）；只对子块分词（检索只查子块，父块不写）；GIN 索引 `idx_documents_search_tokens`；旧文档用 `backfill_search_tokens.py` 回填（幂等，可重跑）。实施后 fts_only Hit@5 从 0.0 → 0.4348
- 环境注意（module-020）：本机 pip 装 sdist 会因 uv 管理 Python 的 setuptools/_distutils_hack 兼容 bug 失败，需 `cmd /c "set SETUPTOOLS_USE_DISTUTILS=stdlib&& pip install <pkg>"`；Windows ProactorEventLoop 下同一 asyncpg 连接池不可跨 `asyncio.run()` 复用（脚本需单 loop 内完成迁移+回填）
- 图检索真实分数方案（module-021，2026-08-01）：`graph_store.search_related` 的 `hybrid_score` 由硬编码 0.6 改为「命中实体数」驱动。每篇 doc 的相关度 = 被「查询实体 e ∪ 一跳邻居 related」多少个实体引用（Cypher UNWIND + `count(DISTINCT ename)`），Python 层 min-max 归一化到 [0,1]，全同分/单结果保底 0.6（复用 `retriever._normalize` 范式但保底值不同，故独立实现 `_normalize_graph_scores`）；排序用真实命中数降序取 top_k，Cypher `LIMIT top_k*2`。接口 `search_related(entities, top_k=10)` 不变。候选池由旧 COALESCE（仅 e 无关系时含 e.doc_ids）扩大为同时含 e 与 related 的 doc_ids，召回不降
- AGE 方言坑（module-021）：Cypher `ORDER BY` 对聚合别名排序报 `could not find rte for hits`，必须用 `count(DISTINCT ename)` 表达式；AGE 支持 UNWIND（1.6.0 实测通过）
- 环境阻塞（module-021）：ModelScope LLM API（qwen/zhipu）2026-08-01 当日 429 配额超限，完整 `graph_only` 评估无法运行（实体提取失败全题跳过）。替代验证：golden doc 有图实体引用的 19 题真实引用实体查询 Hit@5=1.0000；固定实体 A/B 新实现 0.6957 > 旧行为 0.6522 ≥ 基线 0.50。配额恢复后需重跑 `python -m eval.golden_retrieval --mode graph_only` 复核
- 检索缓存方案（module-022，2026-08-01）：① cache_key 由 `rag:retrieve:{sha256(query)[:12]}` 改为 `rag:retrieve:{sha256(query + str(top_k) + str(min_score))[:16]}`（提取纯函数 `engine._retrieve_cache_key`），不同参数不同 key；② `cache.delete_by_prefix(prefix)` 用 Redis SCAN cursor 分批 + DEL 前缀失效（避免 KEYS 阻塞），失败降级返回 False；③ `add_document`/`delete_document` 数据变更成功后全量失效 `rag:retrieve:`（文档增删影响所有查询候选集，简单正确）。cache.get/set 接口不变
- 检索延迟优化（module-024，2026-08-01）：engine._retrieve 四项优化——① round 0 向量/图检索 `asyncio.gather(..., return_exceptions=True)` 单路降级（向量超时→仅图结果，图超时→仅向量结果，两路都失败→空，不整链路崩；图检索新增 wait_for(15s) 超时）；② HyDE 缓存 `rag:hyde:{sha256(query)[:12]}`（TTL 300s，注意用 sha256 而非内置 hash()——PYTHONHASHSEED 跨进程不稳定会导致 Redis 永远 miss；key 前缀与检索缓存 `rag:retrieve:` 独立）；③ 整链路预算 30s（deadline 在 HyDE 前设定，每轮循环检查超预算用已收集 docs 提前结束）；④ 提前终止强化 round 0 ≥3 篇文档跳过反思与后续轮次。`_retrieve` 返回格式不变，hybrid Hit@5=0.9130 ≥ 0.91 基线。实现/单测见 `ai_service/tests/test_engine_latency.py`
- module-024 测试结论（2026-08-01，Tester）：① 单测 13/13 通过；② 全量回归 96 passed，2 个既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归）；③ golden_retrieval hybrid Hit@5=0.9130 与基线持平；④ 延迟实测：检索结果缓存命中 0.003s、提前终止跳过反思（真实链路日志确认）、HyDE 缓存单测通过。**环境阻塞**：ModelScope LLM 当日 429 配额超限，HyDE/实体提取/反思真实链路均降级（降级路径验证正确）；**环境观察（既有问题，非 module-024）**：retriever._execute 用 gather 在单 asyncpg 连接上并发跑 FTS+向量，连接 provisioning 时偶发 `concurrent operations are not permitted`，导致冷缓存 `_retrieve` 结果不一致（0 vs 2 docs），建议后续模块给两路独立 session 或串行化
- 流式记忆接入（module-025，2026-08-01）：chat_stream Step 5 生成前调用 `rag_engine._recall_memory(query, client_ip)`（复用 module-023，5s 超时 + 失败返回空串），结果传给 `reflector.generate_answer_stream(..., memory=memory)`；client_ip 从 `request.state.client_ip` 获取（与 chat 端点同款 `getattr(..., "unknown")`），取不到默认 'unknown'（此时 _recall_memory 内部直接返回空串）。无记忆时 memory 为空串零回归；casual_chat / 无 docs 分支在 Step 5 前提前 return 不触发召回。SSE 事件格式不变。单测见 `ai_service/tests/test_stream_memory.py`（httpx ASGITransport + mock 全链路）
- module-025 测试结论（2026-08-01，Tester）：① 单测 5/5 通过（test_stream_memory.py：有记忆注入 / 无记忆零回归 / 召回失败契约 / client_ip 透传 / casual_chat 跳过）；② 全量回归 101 passed，2 个既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归）；③ 半真实 E2E 通过（真实保存记忆到 PG + 本地 bge-m3 → 真实 chat_stream 端点 → 真实 `_recall_memory` 从真实库召回 `"历史记忆:\n- ..."` → 传入 generate_answer_stream，SSE 事件 step×4/token×2/done 正常；无记忆 IP memory 空串零回归；测试记忆已清理）。**环境阻塞**：LLM 当日 429 配额超限（qwen/zhipu）+ deepseek 未配 key，完整 LLM 端到端无法运行，按任务指引验证逻辑正确性（记忆检索 + 参数传递）；配额恢复后可补跑「保存记忆 → 真实流式对话 → 回答引用记忆」完整端到端
- 检索并发修复 + Reflector 低温度（module-026，2026-08-01）：① `retriever._execute` 并发修复——旧实现用 gather 在单 asyncpg 连接上并发跑 FTS+向量，偶发 `concurrent operations are not permitted`（冷缓存 0 vs 2 篇，module-024 环境观察）；改为未传外部 session 时给 FTS/向量各开独立 `async_session_factory()` session 仍 gather 并行（保留性能），外部 session 共享连接串行，独立 session 创建失败降级单共享串行，单路失败互不影响（`_search_serial` 辅助）；`retrieve` 接口不变。② Reflector 改造——`_provider` 由硬编码 `"deepseek"` 改为 `"fallback"`（消除单点），反思 `temperature=0.1`（结构化 JSON 稳定），生成保持 0.7；`LLMFactory.get_client(provider, temperature=None)` 按 `(provider, temperature)` 缓存，`None`=0.7 不影响其他调用方；`FallbackClient` 温度透传降级链各供应商（低温度贯穿）。③ 链序取舍：采用全局 `PW_FALLBACK_CHAIN`（qwen,zhipu,deepseek），deepseek 未配 key 实际主模型为 qwen，与现状一致，未改全局默认链（改动会无谓影响 casual chat/HyDE/graph 调用方）。实现/单测见 `ai_service/tests/test_retriever_concurrency.py` + `test_reflector_temperature.py`
- module-026 测试结论（2026-08-01，Developer 自测）：① 新增单测 13/13 通过；② 全量回归 114 passed，2 个既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归，101+13 无新增失败）；③ 真实 DB 并发 smoke：5 次冷缓存 hybrid 检索均 3 篇且 ids 一致 [17,47,48]，无 concurrent operations；④ 温度验证：reflector._provider=fallback、反思 0.1、生成 0.7、default 0.7、qwen/zhipu 反思实例 0.1
- module-026 测试结论（2026-08-01，Tester）：① 新增单测 13/13 通过；② 全量回归 114 passed / 2 既有 async 技术债务失败（与基线一致，无新增）；③ 并发稳定性真实 DB：5 次串行冷缓存 ids 全部一致 [17,47,48] + 16 路并发 `_execute`（32 连接）全部一致，无 concurrent operations、无死锁（超出 review #5 理论死锁窗口实测）；④ Reflector 温度（读 LLMFactory 客户端 temperature 属性）：provider=fallback、反思 FallbackClient._temperature=0.1、生成=0.7、默认=0.7、链上 qwen/zhipu 反思实例 _llm.temperature=0.1；⑤ 降级链：deepseek 未配 key 构造抛 LLMException（不可用），qwen/zhipu 可用，真实调用日志确认链遍历 qwen→zhipu→deepseek 正确（外部 ModelScope 429 配额超限属环境阻塞，机制经 mock 单测确认）；⑥ py_compile 5 变更文件 OK。验收 35/35 通过（2 项附注 non-blocking：低温度构造失败实现为 fail-soft、retriever._execute 方法 >50 行）。**环境观察（既有，非本模块）**：本地 bge-m3 嵌入单 Llama 实例并发复用会触发 llama-cpp GGML_ASSERT 原生崩溃（module-020 引入，建议后续模块嵌入层加锁/串行化）。**模块标记 ✅ 完成**
- 嵌入并发修复（module-027，2026-08-02）：本地 bge-m3 单 Llama 实例被 asyncio.to_thread 并发调用触发 GGML_ASSERT 崩溃（module-026 环境观察，见上条），引入 `threading.Lock`（**非 asyncio.Lock**——to_thread 在真线程执行，asyncio.Lock 无法跨线程）。`_embed_sync` / `_embed_documents_sync` 内 `with self._lock:` 包住 `_lazy_load` + `create_embedding`（lazy_load 双加载竞态一并覆盖），批量内部循环整批持锁；归一化在锁外（无状态 numpy，减少持锁时间）。接口签名/返回格式/维度（1024）不变。空 query 防护（module-022 遗留）收敛：`engine._retrieve` 入口（Redis 缓存检查之前）对空/空白 query 提前返回 []，不生成缓存 key。实现/单测见 `ai_service/tests/test_embedding_concurrency.py`
- module-027 测试结论（2026-08-02，Developer 自测）：① 新增单测 6/6 通过（16 路并发 embed_text max_active==1 串行、8 路并发 embed_documents 整批串行、空文本抛 EmbeddingException、空列表返回空、空/空白 query 防护）；② 全量回归 120 passed，2 个既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归，114+6 无新增失败）；③ 真实模型 16 路并发 embed_text 不崩、16 条均 1024 维；④ 真实模型 8 路并发 embed_documents 不崩、每批 2 条均 1024 维；⑤ py_compile 3 变更文件 OK。
- module-027 审查结论（2026-08-02，Reviewer）：**审查通过**。核对结论：① threading.Lock 正确（to_thread 真线程，asyncio.Lock 无法跨线程）；② 代码库仅 2 处 create_embedding 均持锁（embeddings.py L93/L105），批量内部循环整批持锁；③ 归一化在锁外（L94/L106）；④ 空 query 防护位于缓存检查前，单测 mock cache.get 断言不被调用；⑤ 接口签名/返回格式/1024 维不变。Reviewer 实测：新单测 6/6 passed；全量 120 passed / 2 既有 async 技术债务失败（与 Developer 自测一致，无新增）。无阻塞问题，3 项低级别建议（150 行预算口径、空 query warning 日志降噪、测试 import 耗时）记录于 review-report.md。报告：`specs/module-027-embedding-lock/review-report.md`。**模块状态 ✅ 审查通过，待 Tester 验收**
- module-027 测试结论（2026-08-02，Tester）：**验收通过**。① 新增单测 6/6 通过（16 路并发 embed_text max_active==1、8 路并发 embed_documents 整批串行、空文本抛 EmbeddingException、空列表返回空、空/空白 query 防护 mock cache.get 断言不被调用）；② 真实 bge-m3 模型 16 路并发 embed_text 不崩、16 条均 1024 维；8 路并发 embed_documents 不崩、每批 3 条均 1024 维；③ 空 query 防护真实引擎验证：''/'   '/'  \t  ' 均返回 [] 且 0 次缓存调用；④ 全量回归 120 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归，120+6 无新增失败）；⑤ 检索链路 23 passed（test_engine_latency/retriever_concurrency/fts/engine）；⑥ 非空 query 缓存 key 生成正常（同参同 key、不同 top_k 不同 key）；⑦ py_compile 3 变更文件 OK；grep create_embedding 仅 2 处均持锁。验收 30/30 通过。报告：`specs/module-027-embedding-lock/test-report.md`。**模块标记 ✅ 完成**
- Agent 工具化（module-028，2026-08-02）：把固定流水线升级为 Agentic ReAct 循环。① `agent/tool_registry.py`：ToolRegistry 注册 7 个内置工具（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/generate_answer），包装现有 hybrid_retriever/graph_store/graph_extractor/engine._recall_memory/reflector；工具 func 签名 `async def (ctx, args)`，ctx（ReactContext：query/client_ip/history/累积 docs/记忆）由循环注入，注册表无状态可并发复用。② `llm/client.py`：基类新增 chat_with_tools——**关键设计**：ChatOpenAI 系（deepseek/qwen/zhipu）走底层 OpenAI 兼容客户端 `async_client.create` 保留 `reasoning_content`（deepseek-v4-flash thinking 模式要求回传否则 400 `reasoning_content must be passed back`，LangChain bind_tools 会丢弃该字段，langchain-openai 1.4.1 实测），返回原始 assistant 消息 dict 供循环原样回传；Claude 走 bind_tools；FallbackClient 覆写遍历降级链。③ `agent/react.py`：ReAct 循环——react_agent（非流式，返回 {answer, tool_count, tool_trace}）+ react_loop（异步生成器共用，事件 tool_call/tool_result/token/done）；预算=总调用次数上限（while tool_count < budget），预算耗尽用 reflector.generate_answer(ctx.docs) 兜底，预算=0 LLM 直接 chat 回答，工具失败返回空串由 LLM 判断继续/放弃；assistant 工具调用消息只含实际执行的 tool_calls（预算截断时避免无对应 tool 结果的孤立声明）。④ `main.py`：新增 POST /ai/rag/chat/agent（SSE，事件 tool_call/tool_result/token/done/error），引用溯源基于循环累积 docs。⑤ `src/config.py`：新增 max_agent_tools（默认 4，开发可调大）。现有 /ai/rag/chat、/ai/rag/chat/stream 并存不变。实现/单测见 `ai_service/tests/test_agent_tools.py`（21 个）
- module-028 测试结论（2026-08-02，Developer 自测）：① 新增单测 21/21 通过（ToolRegistry 7 工具注册/chat_with_tools 原始路径+reasoning_content 回传+Claude bind 路径/ReAct 循环工具→直接回答、预算耗尽兜底、预算=0、工具失败返回空继续、docs 累积、reasoning_content 回传、SSE 端点事件序列）；② 全量回归 138 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归，120+18 无新增失败）；③ ToolRegistry 注册验证通过（7 工具，顺序一致）；④ 真实 DeepSeek ReAct：'Java线程池核心参数' 工具次数 3-4 ≤ budget 4，thinking 模式 reasoning_content 回传修复后无 400、不再降级 qwen；⑤ 真实 SSE E2E：/ai/rag/chat/agent 200，事件 tool_call/tool_result/token/done 齐全，done 含 answer+sources(5)+tool_count+budget；⑥ qwen（ModelScope）原始路径工具调用兼容验证通过（直接回答路径）；⑦ py_compile 6 变更文件 OK。**环境观察（既有，非本模块）**：本机 langchain-openai 实际安装版本 1.4.1（requirements 声明 0.1.7 已过时），bind_tools 不保留 reasoning_content 是本模块关键修正的根因。
- module-028 审查结论（2026-08-02，Reviewer）：**审查通过**。完整阅读全部变更文件 + 独立复现 Developer 自测：① 新增单测 21/21 passed；② 全量回归 141 passed / 2 既有 async 技术债务失败（与 Developer 自测一致，无新增）；③ ToolRegistry 注册 7 工具顺序一致；④ 关键机制独立验证：ChatOpenAI 暴露 async_client.create（langchain-openai 1.4.1 / openai 2.50.0 / pydantic 2.13.4），ChatCompletionMessage.model_config extra=allow 使 `reasoning_content` 额外字段可属性读取——DeepSeek thinking 回传机制成立；⑤ 依赖签名核对：hybrid_retriever.retrieve(query, top_k, mode) / engine._recall_memory(query, client_ip, top_k) / graph_extractor.extract_from_query / graph_store.search_related(entities, top_k) / reflector.generate_answer(query, documents, history, memory) 与工具包装全部匹配；⑥ 工具失败统一捕获返回空串、assistant 消息只含实际执行 tool_calls（预算截断防孤立声明）、预算=0 直接 chat、预算耗尽 reflector 兜底——逻辑核对无缺。无阻塞问题，5 项建议记录于 review-report.md（react_loop 约 90 行超 50 行限制、FallbackClient.chat_with_tools 降级链无专门单测、预算截断路径无专门单测、SSE token 粗粒度且答案双通道下发、agent 端点未持久化 IP 会话）。报告：`specs/module-028-agent-tools/review-report.md`。**模块状态 ✅ 审查通过，待 Tester 验收**
- module-028 测试结论（2026-08-02，Tester）：**验收通过（44/44）**。① 新增单测 21/21 通过（ToolRegistry 7 工具 / chat_with_tools OpenAI 原始路径+Claude bind 路径+reasoning_content 保留 / ReAct 预算/兜底/预算=0/失败继续/docs 累积/reasoning 回传 / SSE 端点事件序列）；② 全量回归 141 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 起记录，非本模块回归，0 新增失败）；③ ToolRegistry 注册验证 7 工具顺序一致；④ 真实 DeepSeek ReAct：'Java线程池核心参数' 工具次数 4 ≤ budget 4，真实 search_knowledge/search_fts 工具调用，reasoning_content 回传无 400，真实带引用答案（26.1s）；⑤ 真实 SSE E2E：/ai/rag/chat/agent 200，事件 tool_call×4/tool_result×4/token×2/done×1 齐全、0 error，done 含 answer+sources(5)+tool_count(4)+budget(4)；⑥ FallbackClient.chat_with_tools 降级链独立 mock 验证：qwen 失败→zhipu 成功即返回、全失败→LLMException 遍历完整链（补 Reviewer 建议 #2）；⑦ 现有 /ai/rag/chat 无回归：main.py diff 纯新增端点、全量回归通过、真实 E2E（真实 LLM+真实检索，重排 mock）200/message=ok/answer/5 sources；⑧ py_compile 6 变更文件 OK。**环境观察（既有，非本模块）**：本机 Qwen3-Reranker-0.6B（生成式重排模型，module-018）CPU 评分 batch（20→5）运行 >20 分钟无进展，真实 /ai/rag/chat 全链路 E2E 受其阻塞，已用重排 mock 验证端点链路。报告：`specs/module-028-agent-tools/test-report.md`。**模块标记 ✅ 完成**
