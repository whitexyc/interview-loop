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

> 每个模块目录含 plan.md / acceptance-criteria.md / changelog.md / review-report.md / test-report.md。
