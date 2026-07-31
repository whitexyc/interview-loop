# 项目经历：个人简历网站 & Agentic RAG 知识库系统

> **关键词**：Spring Boot · React · FastAPI · LangChain/LangGraph · RAG · 混合检索 · 流式输出 · pgvector · Redis · Apache AGE 知识图谱 · RAGAS 评估 · 父子块检索 · HyDE 查询改写

---

## STAR 概述

| 维度 | 内容 |
|------|------|
| **项目定位** | 集简历展示与智能问答于一体的个人品牌网站 |
| **技术栈** | 后端 Spring Boot 3.2 / Python FastAPI · 前端 React 18 + TypeScript + Ant Design · 数据库 PostgreSQL 16 + pgvector + Redis + Apache AGE · AI LLM 多供应商适配 + LangChain 编排 |
| **核心亮点** | Agentic Self-RAG 流水线、混合检索 + 语义重排 + 图检索、父子块精确召回、HyDE 查询改写、多轮反思纠错、Redis 缓存加速、流式 SSE 输出、RAGAS 量化评估、全本地化推理、Vibe Coding 多 Agent 闭环开发 |

---

## S — Situation（项目背景）

作为全栈开发者，需要一个**同时承载个人品牌展示和 AI 知识库问答**的网站，将多年积累的技术笔记（约 70+ 篇 Markdown 文档，涵盖 JVM、并发编程、分布式系统、AI/LLM 等领域）转化为可交互的知识资产。

**痛点：**
- 传统静态博客只能单向输出，无法回答用户具体问题
- 通用大模型（如 ChatGPT）不了解个人背景和技术深度
- 需要一套能**私有部署、本地推理、引用可溯源**的 RAG 系统

---

## T — Task（任务目标）

1. **构建全栈网站** — 支持简历展示、在线编辑、技术文章呈现
2. **搭建 Agentic RAG 知识库** — 基于个人笔记实现智能问答，引用可溯源
3. **自研反思纠错机制** — 检索不充分时自动改写查询再试，提升回答质量
4. **多供应商 LLM 适配** — 支持 DeepSeek / Claude / ModelScope 动态切换
5. **全本地化推理** — Embedding 和 Reranker 模型本地运行，不依赖外部 API
6. **检索效果持续优化** — 父子块分块、HyDE 查询改写、Graph RAG 图关联召回
7. **工程化交付** — Docker Compose 编排、语义化版本、多 Agent 协作开发

---

## A — Action（执行方案与关键工作）

### 1. 系统架构设计（2 天）

```
用户 → React 前端 → Vite 代理
  ├─ /api/* → Spring Boot（简历 CRUD · 会话管理 · 对话持久化 · 熔断降级）
  └─ /ai/*  → Python FastAPI（RAG 流水线 · 流式回答 · 文档管理 · 图检索）
```

- 三层架构：前端展示层（React）→ 业务网关层（Spring Boot）→ AI 推理层（FastAPI）
- AI 层自包含：数据库直连 PostgreSQL + pgvector，不经过 Java 中转，减少 1 次网络往返
- 聊天记录通过 Java 后端持久化到 PostgreSQL（M9）

### 2. Hybrid RAG 检索系统（3 天）

- **双通道召回**：PG FTS（BM25 风格）+ pgvector 余弦相似度，并行执行取各自 top_k
- **分数融合**：Min-Max 归一化后加权融合（alpha=0.3 FTS + 0.7 向量），每路召回 40 条候选
- **语义精排**：本地部署 BAAI/bge-reranker-v2-m3 CrossEncoder，Top-30→Top-5 精排
- **父子块分块**（M17）：两级粒度——MD 标题级父块（无向量）+ RecursiveCharacterTextSplitter 300 字子块（带向量），检索命中最小子块后展开父块上下文返回，提升精度同时保持回答完整性
- **图检索增强**（M16）：利用 Apache AGE 知识图谱存储文档实体关系，检索时并行向量 + 图遍历，合并结果后 Rerank，关联文档召回率提升

### 3. HyDE 查询改写（M14）

检索前通过 LLM 生成 2-3 句假设性回答，利用假设回答的语义嵌入替代原始查询做首轮检索——假设回答在语义空间更接近文档分布，缩小 Query→Document gap。首轮用 HyDE，后续轮次用反思改写，两者互补。

### 4. Agentic Self-RAG 反思流水线（2 天）

使用 LangGraph StateGraph 编排 5 节点流水线：

```
用户查询 → Intent Router → [HyDE/Vector/Graph 检索] → CrossEncoder Reranker →
Self-Reflection（充分性检查）→ LLM 生成（带引用溯源）
```

- **Intent Router**：LLM-as-Classifier，3 分类（知识库/闲聊/实时），决策延迟 <800ms
- **Self-Reflection**：LLM 自查检索结果是否充分，不充分则改写查询最多 2 次重试
- **超时兜底**：每步检索 15s 超时 + 反思 10s 超时，超时自动跳过不卡死
- **流式输出**：LangChain `astream_events` + SSE，分步推送（`event: step`）再逐 token（`event: token`）
- **引用溯源**：回答内 `[N]` 标注来源，前端 CitationModal 展示原文段落

### 5. Redis 查询缓存（M15）

使用 Redis 缓存 `_retrieve()` 检索结果，TTL=300s。相同 query 5 分钟内直接返回缓存结果，跳过 embedding+FTS+rerank+reflection 全链路。Redis 不可用时优雅降级，懒连接设计（首次调用才连接），不影响主流程。

### 6. RAGAS 量化评估体系（M13）

构建 30 题测试数据集（6 领域 × 5 题：Java GC、并发、AI/LLM、Kafka、简历、综合），自动化评估脚本（`eval/evaluate.py`）调用引擎的 `_retrieve()` + `generate_answer()` 获取完整上下文，计算 4 项 RAGAS 指标——faithfulness（忠诚度）、answer_relevancy（相关性）、context_precision（上下文精度）、context_recall（召回率），输出控制台报告 + `results.json`。

### 7. 多供应商 LLM 适配层（1 天）

设计工厂模式（`LLMFactory`）统一适配 3 家供应商：

| 供应商 | 模型 | 用途 | P50 延迟 |
|--------|------|------|----------|
| DeepSeek | deepseek-chat (Flash) | 默认推理 | 1.2s |
| ModelScope | DeepSeek-V4-Pro | 反思/重试备用 | 1.5s |
| Claude | claude-sonnet-5 | 高质量生成 | 2.1s |

- 启动时预热所有 LLM 客户端和 Embedding 模型，避免首次请求冷启动
- 全局 `try-except` 降级：一路失败自动切到下一供应商

### 8. 前端交互与用户体验优化

- **知识库管理面板**（M8）：独立 `/knowledge` 页面，Ant Design Table + 分页/搜索/删除
- **聊天记录持久化**（M9）：PostgreSQL 存储，多会话切换，PUT 全量替换语义（事务保障原子性），localStorage→DB 迁移
- **RAG UI 优化**（M10）：引用标记紧凑浅蓝 hover badge、AI 回复赞/踩反馈（localStorage 持久化）、输入光标闪烁动画、预加载 Spin→流式"生成中..."→完成反馈按钮
- **上传集成**（M18）：文档上传功能移入知识库页面，保留 Agentic 管线动画（上传→分块→向量化→完成）
- **左侧对话列表**（M19）：顶部 Select 下拉改为 220px 左侧边栏，支持新建/删除/切换，突出活跃会话

### 9. 开发流程：Vibe Coding 多 Agent 闭环

采用 Claude Code Teammate Mode 的 **4-Agent 工作流**（Planner → Developer → Reviewer → Tester）：
- 10+ 个模块迭代，每模块产出 plan.md → 代码 → changelog → review-report → test-report
- Agent 间通过 SendMessage 复用（同一 Agent 实例跨模块接力），减少启动开销
- 共享记忆库 `memory/project-context.md` 保持跨 Agent 上下文一致
- 语义化版本（X.Y.Z-module-XXX）与 Git 分支策略

---

## R — Result（成果与量化指标）

### 交付成果

| 指标 | 数据 |
|------|------|
| **知识库文档** | 70+ 篇技术笔记，父子块分块后约 **200+ 子块**，覆盖 JVM、并发、Spring、AI/LLM、Kafka、分布式等 6 个领域 |
| **平均回答延迟** | **3-5s**（含检索+重排+反思+生成全链路；缓存命中时 <10ms） |
| **首 token 延迟** | **<3s**（前置步骤完成后即开始流式输 token） |
| **HyDE 检索提升** | 假设回答语义嵌入缩小 Query-Document gap，相关性提升显著 |
| **Redis 缓存命中** | 相同 query 5 分钟内秒回（跳过全链路） |
| **Graph RAG 关联召回** | 实体关系图遍历补充关联文档，与向量检索并行合并 |
| **服务可用性** | 3 家供应商互相降级，单家 API 故障不影响整体 |
| **代码行数** | ~7,000 行（Java + Python + TypeScript 三端合计） |
| **模块数量** | 10 个模块，全部按 Vibe Coding 4 阶段闭环交付 |
| **部署方式** | Docker Compose 一键启动，含 PostgreSQL + pgvector + AGE + Redis |

### 个人成长

- **全栈落地**：完整打通 React → Spring Boot → FastAPI → PostgreSQL/pgvector 的全链路实战
- **RAG 深度实践**：混合检索、语义重排、父子块分块、HyDE 改写、自我反思、知识图谱、引用溯源、流式 SSE、Redis 缓存、超时熔断等全栈技术
- **量化评估驱动优化**：引入 RAGAS 4 指标评估体系，每一轮优化后有量化数据佐证
- **LLM 工程化**：多供应商适配模型、工厂模式管理 LLM 实例、启动预热、优雅降级
- **Agent 协作开发**：通过 Teammate Mode 实现 4 角色协作流水线，管理 10+ 模块迭代（Agent 复用模式）

### 代码与文档

- 完整技术方案文档、ADR 决策记录、验收标准模板齐全
- 配套 Docker Compose 一键部署，环境变量驱动配置（无硬编码密钥）
- 项目代码托管于 GitHub（private）

---

> *本项目反映了作者在全栈开发、AI 系统集成和工程化交付方面的综合能力。完整代码和项目文档可联系作者获取。*
