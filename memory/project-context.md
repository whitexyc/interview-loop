# 项目上下文记忆库

## 1. 项目概述
- 项目名称: 张三个人网站
- 项目简介: 融合简历展示与 Agentic RAG 知识库问答的个人网站系统（双语言微服务架构：Java Spring Boot + Python FastAPI + React 前端）
- 创建时间: 2026-07-29
- 最后更新: 2026-08-01

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

## 4. 架构决策记录（ADR）索引
| ADR 编号 | 决策标题 | 状态 | 日期 |
|----------|----------|------|------|
| — | — | — | — |

## 5. 当前迭代状态
- 当前迭代版本: v0.21.0
- 正在进行的模块: 无（module-021 已测试验收完成）
- 下一个待开发模块: 待定（候选：缓存修复 / 长期记忆）

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
