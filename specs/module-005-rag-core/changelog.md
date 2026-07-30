# 变更日志 — Module-005: Agentic RAG 知识库核心

## 变更概述
实现完整企业级 RAG 链路：多源混合检索（BM25+向量）→ Rerank 重排 → 意图识别路由 → 自我反思纠错 → 精准引用溯源。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/models.py | 新增 | Document ORM（pgvector embedding 字段） |
| ai_service/rag/embeddings.py | 新增 | EmbeddingService（OpenAI 兼容 API 嵌入） |
| ai_service/rag/retriever.py | 新增 | HybridRetriever（FTS+向量加权混合检索） |
| ai_service/rag/reranker.py | 新增 | Reranker 基类 + ModelScopeReranker |
| ai_service/rag/engine.py | 修改 | 完整 RAG 链路（search+chat） |
| ai_service/agent/__init__.py | 新增 | agent 包标记 |
| ai_service/agent/router.py | 新增 | RouterAgent 意图分类（knowledge/casual_chat/realtime） |
| ai_service/agent/reflector.py | 新增 | Reflector 自我反思+Query改写+答案生成 |
| ai_service/src/config.py | 修改 | 添加 ModelScope/embedding/hybrid 配置 |
| ai_service/requirements.txt | 修改 | 添加 pgvector 依赖 |

## RAG 完整链路
```
用户 Query → [Router Agent] 意图分类
  ├─ 闲聊 → 直接 LLM（DeepSeek Flash）
  ├─ 实时数据 → 🔜 module-006
  └─ 知识库 → [BM25 + pgvector] 混合检索 Top 20
                → [Rerank] → Top 5
                → [Self-Reflection] 检查充分性
                    ├─ 充分 → [LLM 生成] 答案 + 引用
                    └─ 不充分 → 改写 Query → 二次检索
```

## 验证命令
| 验证项 | 命令 | 预期 |
|--------|------|------|
| 语法检查 | `cd ai_service && python -m py_compile main.py` | ✅ 通过 |
| import 检查 | `cd ai_service && python -c "from rag.engine import rag_engine"` | import OK |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现 | Developer-Python ×2 |
