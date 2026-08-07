# Agentic RAG 技术文档知识库系统

> 全栈 Agentic RAG 知识库问答系统：三通道混合检索 + Agent 工具化 + 多层记忆
> 三层架构：React 前端 · Spring Boot 业务层 · Python FastAPI AI 推理层

## 项目架构

```
用户 → React 前端 → Vite 代理
  ├─ /api/* → Spring Boot（会话管理 · JWT 认证 · 文档管理）
  └─ /ai/*  → Python FastAPI（RAG 流水线 · Agent 问答 · 流式回答）
```

## 技术栈

| 层 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design + Vite |
| 后端 | Spring Boot 3.2 + MyBatis-Plus + JWT |
| AI 层 | Python FastAPI + LangChain/LangGraph + SQLAlchemy + pgvector |
| 数据库 | PostgreSQL 16 (pgvector + Apache AGE) + Redis |
| LLM | 多供应商降级链（DeepSeek / Claude / ModelScope，可动态调整） |
| 本地模型 | bge-m3 嵌入（GGUF + llama-cpp）· bge-reranker 重排（完全离线推理） |

## 功能

### Agentic RAG 智能问答

- **意图路由**：LLM 零样本分类（知识库 / 闲聊 / 实时），宁多检不漏检
- **三通道混合检索**：PG 全文（jieba 中文分词 + GIN 索引）+ pgvector 语义向量 + Apache AGE 知识图谱，加权归一化融合
- **语义重排**：本地 bge-reranker 精排 Top-5
- **父子两级分块**：章节级父块 + 300 字子块，兼顾召回精度与回答完整性
- **自我反思纠错**：检索不充分自动改写重查，二次结果与原始结果合并
- **Agent 工具化**：ReAct 循环 + ToolRegistry 7 个可注册工具（检索 / 图谱 / 记忆 / 生成），工具轨迹经 SSE 实时展示
- **多层记忆**：长期（LLM 自动抽取）/ 短期（TTL 滚动）/ 会话（幂等落库）三层，多用户独立上下文、互不串扰
- **HyDE 查询改写**：LLM 生成假设回答做首轮检索（结果缓存）
- **流式 SSE**：逐 token 输出 + 管线步骤实时展示
- **引用溯源**：回答 `[N]` 标注来源，点击弹出原文

### 检索评估体系

- 自建 golden 评测集 + Hit@k / Recall@k / MRR 指标体系
- eval_runs 版本化回归：git_commit + 配置快照落库，支持单通道消融，防退化

### 知识库管理

- 文档列表 / 搜索 / 删除 / 分页
- 文档上传（密码保护）

### 多会话聊天

- 多会话创建 / 切换 / 删除
- 聊天记录 PostgreSQL 持久化
- AI 回复赞 / 踩反馈

## 快速启动

### 前置依赖

- Python 3.11+
- Node.js 18+
- JDK 17+
- PostgreSQL 16（pgvector + AGE 扩展）
- Redis

### 启动服务

```bash
# 1. AI 推理层（端口 8001）
cd ai_service
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8001

# 2. Java 后端（端口 8081）
cd backend
mvn spring-boot:run

# 3. 前端（端口 3001）
cd frontend
npm install
npm run dev
```

访问 http://localhost:3001

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PW_DATABASE_URL` | PostgreSQL 连接 | `postgresql+asyncpg://postgres:postgres123@localhost:5432/personal_website` |
| `PW_REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `PW_LLM_PROVIDER` | 默认 LLM 供应商 | `fallback` |
| `PW_FALLBACK_CHAIN` | 降级链（逗号分隔） | `qwen,zhipu,deepseek` |
| `PW_DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `PW_CLAUDE_API_KEY` | Claude API Key | — |
| `PW_JWT_SECRET` | JWT 共享密钥（与 Java 后端一致，HS256） | — |
| `VITE_EDIT_PASSWORD` | 文档上传密码 | — |

## License

MIT
