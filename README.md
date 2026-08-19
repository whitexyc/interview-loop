# Agentic RAG 技术文档知识库系统

> 全栈 Agentic RAG 知识库问答系统：**三通道融合检索 + Agent 工具化编排 + 多层记忆 + 幻觉检测**
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
| LLM | 多供应商降级链（配置默认 qwen → zhipu → deepseek；运行时可动态调序，实际顺序以 Redis 持久化结果为准） |
| 本地模型 | bge-m3 嵌入（GGUF + llama-cpp）· bge-reranker-v2-m3 重排 · HHEM 幻觉裁判（全部离线推理） |

## 功能

### Agentic RAG 智能问答

- **意图识别**：先判断问题类型（知识库问答 / 闲聊 / 实时信息）——本地轻量分类器毫秒级响应，识别失败自动回退大模型判断，宁可多检索不漏检
- **三通道混合检索**：关键词全文 + 语义向量 + 知识图谱三路并行检索后融合排序（评测命中率 Top-5 = 99.05%），支持加权融合回退
- **语义重排**：本地重排模型对召回结果精排 Top-5，截断超长文档防止推理卡顿
- **父子两级分块**：按章节切父块（完整语义）+ 约 300 字子块（重叠 50 字符）——小块检索精准、大块回答完整
- **自我反思纠错**：检索结果不充分时自动改写查询重检（最多 3 轮），新结果与旧结果合并
- **Agent 工具化**：10 个工具由模型自主编排调用（检索 / 图谱 / 记忆 / 重检 / 生成 / 逐句验证 / 笔记），**按执行阶段分组暴露**——检索命中即切生成阶段（检索 3 轮未命中强制切），避免死锁、节省 token；工具调用过程实时展示
- **幻觉检测**：逐句验证答案是否被检索文档支持（有依据 / 可推断 / 无依据三档），前端逐句色标；验证异步进行——答案先返回、验证结果后台补充，不阻塞阅读
- **多层记忆**：长期记住用户偏好（自动抽取、永久保存）/ 短期记住近期内容（30 天自然衰减、反复提及自动升级为长期）/ 会话记住完整对话（刷新恢复 + 长对话自动摘要），按用户隔离互不串扰；记忆纠错——升级留底可回溯、**双判共识冲突检测**（nli+clf 都判矛盾才标废弃，Precision 0.94，宁可漏检也不错标）
- **流式 SSE**：逐 token 输出 + 管线步骤实时展示
- **引用溯源**：回答 `[N]` 标注来源，点击弹出原文
- **MCP 标准工具服务**：ToolRegistry 工具经官方 MCP SDK（FastMCP）暴露为标准 MCP Server——**6 个只读检索工具**（混合/全文/向量/图谱检索 + 实体提取 + 记忆召回）双传输对外提供：**stdio**（本地 Cursor / Claude Code / Claude Desktop 即插即用）与 **Streamable HTTP**（挂载 `/ai/mcp`，Bearer token 认证）；工具定义单一事实源（ToolRegistry），改描述 MCP 自动同步；HTTP 模式 `PW_MCP_TOKEN` 未配置拒绝启动（fail-closed，宁可不用不能裸奔）；stdio 为本地进程模式零认证（安全边界如实声明）；工具返回自动截断 2000 字符

### 工程实践

- **1225 项自动化测试**（50+ 个测试文件）+ 真实环境端到端验证
- **评估闭环**：检索层 112 题评测集 + 命中率 / 排序质量指标 + 单通道消融；**Agent 行为层**（066）工具调用明细落库 + 36 条任务集 + 三层指标（任务完成率 pass^1/pass^3、工具正确率、成本步数），判定全确定性不用 LLM 评 LLM；**幻觉检测**（071）136 条三态标注 + 阈值校准（kappa 0.33 天花板如实标注）
- **可观测性**：每次请求全链路可追踪（各阶段耗时 / token 用量 / 缓存命中）+ Agent 工具调用明细（trace_id / 参数 / 成败 / 耗时），可回答"单问题成本"与 P50/P95 延迟
- **架构决策记录**：18 份关键选型留档（检索 / 分块 / 记忆 / 幻觉检测 / 工具治理 / Agent 评估 / MCP 集成等）
- **数据飞轮**：用户反馈与验证结果落库，作为模型再训练数据源
- 📊 **评估指标总览**：检索 Hit@5/MRR + 三通道消融 + 意图/充分性/幻觉检测等完整量化指标见 [METRICS.md](METRICS.md)

## 本地模型下载

生产链路 3 个本地模型 + 1 个评估可选模型，统一放 `ai_service/models/`（不随仓库分发）：

| 模型 | 目录 | 用途 | 来源 |
|------|------|------|------|
| bge-m3（GGUF q8_0） | `ai_service/models/bge-m3-gguf/bge-m3-q8_0.gguf` | 语义向量嵌入 | HuggingFace bge-m3 GGUF 量化版（llama-cpp 加载，完全离线） |
| bge-reranker-v2-m3 | `ai_service/models/bge-reranker-v2-m3/` | 检索重排精排 | HuggingFace `BAAI/bge-reranker-v2-m3`（safetensors ~2.17GB） |
| HHEM-2.1-Open | `ai_service/models/hhem-2.1-open/` | 幻觉检测裁判 | HuggingFace Vectara 官方发布（hhem-2.1-open，110M 参数，约 418MB，含自定义 modeling 文件） |
| mDeBERTa-v3-base-xnli（可选） | `ai_service/models/mdeberta-nli/` | 文本矛盾/蕴含判断（评估实验，非生产链路） | HuggingFace mDeBERTa-v3-base-xnli 多语言系列 |

国内网络建议走镜像下载：

```bash
# 示例：重排模型（其余模型同理，替换 repo 与 --local-dir 路径）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download BAAI/bge-reranker-v2-m3 \
  --local-dir ai_service/models/bge-reranker-v2-m3
```

> 缺模型行为：**嵌入/重排**缺权重会明确报错并提示路径（各自校验文件存在性与大小，不回退在线加载）；**HHEM 幻觉裁判**缺失/加载失败/超时会降级回 LLM 判分（有 warning 日志），保证验证链路可用。

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
| `PW_MCP_TOKEN` | MCP HTTP 模式访问 token（`/ai/mcp`，Bearer 认证；**未设置拒绝启动**，fail-closed） | — |
| `VITE_EDIT_PASSWORD` | 文档上传密码 | — |
| `PW_RETRIEVAL_FUSION_MODE` | 检索融合模式：`rrf`（默认）/ `hybrid` / `weighted` | `rrf` |
| `PW_INTENT_CLASSIFIER_ENABLED` | 意图分类器开关 | `true` |
| `PW_TOOL_PHASE_SPLIT` | 工具阶段分组开关（检索组/生成组） | `true` |
| `PW_VERIFY_ASYNC` | 幻觉验证异步化开关（答案先回、后台验证） | `true` |
| `PW_REQUEST_LOGS` | 可观测性落库开关（trace / 阶段耗时 / token） | `true` |

## License

MIT
