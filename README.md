# 个人网站 — Agentic RAG 知识库系统

> 全栈个人品牌网站：简历展示 + Agentic RAG 智能问答

## 项目架构

```
用户 → React 前端 → Vite 代理
  ├─ /api/* → Spring Boot（简历 CRUD · 会话管理 · 熔断降级）
  └─ /ai/*  → Python FastAPI（RAG 流水线 · 流式回答 · 文档管理）
```

## 技术栈

| 层 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Ant Design + Vite |
| 后端 | Spring Boot 3.2 + MyBatis-Plus |
| AI 层 | Python FastAPI + LangChain + pgvector |
| 数据库 | PostgreSQL 16 (pgvector + Apache AGE) + Redis |
| LLM | ModelScope 多模型降级链（Qwen → GLM → DeepSeek） |
| 嵌入 | ModelScope 云端 bge-m3（1024 维） |

## 功能

### 简历展示
- 在线简历展示 + 编辑
- 个人信息、教育背景、项目经历、技能图谱

### Agentic RAG 知识库问答
- **混合检索**: PG FTS + pgvector 余弦相似度并行召回
- **云端嵌入**: ModelScope bge-m3，1024 维向量
- **语义重排**: 本地 CrossEncoder 精排 Top-5
- **父子块分块**: MD 标题级父块 + 300 字符子块精确召回
- **HyDE 查询改写**: LLM 生成假设回答做首轮检索
- **Self-Reflection**: 自我反思纠错，最多 2 次重试改写
- **Graph RAG**: Apache AGE 知识图谱实体关联召回
- **LLM 降级链**: Qwen → GLM → DeepSeek 自动切换，避免单点故障
- **Redis 缓存**: 相同查询 5 分钟缓存
- **流式 SSE**: 逐 token 输出 + 管线步骤动画

### 知识库管理
- 文档列表 / 搜索 / 删除 / 分页
- 文档上传（密码保护）

### 多会话聊天
- 多会话创建 / 切换 / 删除
- 聊天记录 PostgreSQL 持久化
- 引用溯源（`[N]` 标记弹出原文）
- AI 回复赞/踩反馈

## 快速启动

### 前置依赖
- Python 3.11+
- Node.js 18+
- JDK 17+
- PostgreSQL 16 (pgvector + AGE 扩展)
- Redis

### 启动服务

```bash
# 1. AI 推理层
cd ai_service
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# 2. Java 后端
cd backend
mvn spring-boot:run

# 3. 前端
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PW_DATABASE_URL` | PostgreSQL 连接 | `postgresql://postgres:123456@localhost/personal_website` |
| `PW_REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `PW_LLM_PROVIDER` | 默认 LLM 供应商 | `deepseek` |
| `PW_DEEPSEEK_API_KEY` | DeepSeek API Key | — |
| `PW_CLAUDE_API_KEY` | Claude API Key | — |
| `VITE_EDIT_PASSWORD` | 文档上传密码 | `` |




## License

MIT
