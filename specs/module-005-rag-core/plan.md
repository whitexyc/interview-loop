# 开发计划 — Module-005: Agentic RAG 知识库核心

> Planner: Claude | 日期: 2026-07-29 | 版本: v1

## 0. Agent 配置清单
- **Developer-RAG ×2**（并行）：子任务 1-2 + 子任务 3-4
- **Reviewer ×1**
- **Tester ×1**

## 1. 需求描述
- **需求来源**: prompt.md（Agentic RAG 知识库模块，要求"多做高级功能"）
- **功能描述**: 实现企业级 RAG 知识库核心链路：多源混合检索（BM25+向量）→ Rerank 重排 → 意图识别路由 → 自我反思纠错 → 精准引用溯源
- **AI 供应商**: DeepSeek Flash（默认）+ ModelScope DeepSeek-V4-Pro（高性能，可切换）
- **优先级**: P0（核心 AI 能力）

## 2. 模块拆分

### 子任务 1: 向量化管道 + 混合检索
- **描述**: 创建 embedding 服务（接入 Claude/OpenAI embedding），将文档向量化存入 pgvector；实现 BM25（全文检索）与向量检索的加权混合召回
- **代码量**: ~180 行
- **涉及文件**:
  - `ai_service/rag/embeddings.py` (新增) — embedding 服务
  - `ai_service/rag/retriever.py` (新增) — 混合检索器（BM25 + 向量加权）
  - `ai_service/rag/models.py` (新增) — SQLAlchemy ORM 模型（documents 表）

### 子任务 2: Rerank 重排
- **描述**: 引入 BGE-reranker 对 Top 20 召回结果重排，输出最精准 Top 5；支持 Cohere Rerank API 作为备选
- **代码量**: ~80 行
- **涉及文件**:
  - `ai_service/rag/reranker.py` (新增) — Rerank 适配器（BGE / Cohere）

### 子任务 3: 意图识别路由 (Router Agent)
- **描述**: Agent 先判断用户问题类型（查知识库、查实时数据、闲聊），分别路由到不同管道，避免无效检索。基于 LLM 分类器（DeepSeek Flash）
- **代码量**: ~100 行
- **涉及文件**:
  - `ai_service/agent/router.py` (新增) — 意图识别路由
  - `ai_service/agent/__init__.py` (新增)

### 子任务 4: 自我反思 + 引用溯源 + 主引擎集成
- **描述**: Agent 给出答案前自动检查检索内容是否充分，不充分则改写 Query 二次检索；每次回答带原文片段、文档ID；集成所有组件到 RAGEngine。使用 DeepSeek-V4-Pro（来自 ModelScope）作为反思/生成模型
- **代码量**: ~200 行
- **涉及文件**:
  - `ai_service/agent/reflector.py` (新增) — 自我反思与 Query 改写
  - `ai_service/rag/engine.py` (修改) — 集成完整 RAG 链路

## 3. 技术方案

### PostgreSQL 数据表（通过 SQLAlchemy ORM 创建）
```sql
-- documents: 文档存储
CREATE TABLE documents (
    id          SERIAL PRIMARY KEY,
    title       TEXT,
    content     TEXT NOT NULL,
    source      TEXT,          -- 来源文件
    page_num    INTEGER,
    metadata    JSONB,
    embedding   vector(1536),  -- pgvector
    created_at  TIMESTAMP DEFAULT NOW()
);

-- 全文检索索引
CREATE INDEX idx_documents_content_fts ON documents
  USING GIN (to_tsvector('simple', content));
```

### API 端点更新

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ai/rag/search` | POST | 完整检索流程：混合检索 → Rerank → 返回结果（带引用） |
| `/ai/rag/chat` | POST | 完整问答流程：意图识别 → 检索 → 反思 → LLM生成 → 返回答案+引用 |
| `/ai/rag/documents` | POST | 添加文档（供 Java 端文件上传后调用） |

### 检索管线
```
用户 Query
  → [Router Agent] 意图分类（知识库/闲聊/实时）
    ├─ 闲聊 → 直接 LLM 回答，不检索
    ├─ 实时 → 🔜 module-006 实现
    └─ 知识库 → [BM25 + 向量] 混合检索 Top 20
                  → [Rerank] → Top 5
                  → [Self-Reflection] 检查是否充分
                      ├─ 充分 → [LLM] 生成答案 + 引用
                      └─ 不充分 → 改写 Query → 二次检索
```

## 4. 验收标准
见同目录 `acceptance-criteria.md`

## 5. 风险评估
- BGE-reranker 模型需要额外下载（~1GB），建议上线前预缓存
- BM25 需要构建倒排索引，首次加载可能慢
- 意图识别精度依赖 LLM 质量，后续可收集测试集优化

## 6. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始版本 | Planner |
