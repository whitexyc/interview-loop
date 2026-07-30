# 项目经历：个人简历网站 & Agentic RAG 知识库系统

> **关键词**：Spring Boot · React · FastAPI · LangChain/LangGraph · RAG · 混合检索 · 流式输出 · pgvector

---

## STAR 概述

| 维度 | 内容 |
|------|------|
| **项目定位** | 集简历展示与智能问答于一体的个人品牌网站 |
| **技术栈** | 后端 Spring Boot 3.2 / Python FastAPI · 前端 React 18 + TypeScript + Ant Design · 数据库 PostgreSQL 16 + pgvector + Redis · AI LLM 多供应商适配 + LangChain 编排 |
| **核心亮点** | Agentic Self-RAG 流水线、混合检索 + 语义重排、多轮反思纠错、流式 SSE 输出、全本地化推理 |

---

## S — Situation（项目背景）

作为全栈开发者，需要一个**同时承载个人品牌展示和 AI 知识库问答**的网站，将多年积累的技术笔记（约 70+ 篇 Markdown 文档，涵盖 JVM、并发编程、分布式系统等领域）转化为可交互的知识资产。

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
6. **工程化交付** — Docker Compose 编排、语义化版本、多 Agent 协作开发

---

## A — Action（执行方案与关键工作）

### 1. 系统架构设计（2 天）

```
用户 → React 前端 → Vite 代理
  ├─ /api/* → Spring Boot（简历 CRUD · 请求转发 · 熔断降级）
  └─ /ai/*  → Python FastAPI（RAG 流水线 · 流式回答 · 文档管理）
```

- 三层架构：前端展示层（React）→ 业务网关层（Spring Boot）→ AI 推理层（FastAPI）
- AI 层自包含：数据库直连 PostgreSQL + pgvector，不经过 Java 中转，减少 1 次网络往返

### 2. Hybrid RAG 检索系统（3 天）

- **双通道召回**：PG FTS（BM25 风格）+ pgvector 余弦相似度，并行执行取各自 top_k
- **分数融合**：Min-Max 归一化后加权融合（alpha=0.3 FTS + 0.7 向量），每路召回 40 条候选
- **语义精排**：本地部署 BAAI/bge-reranker-v2-m3 CrossEncoder，Top-30→Top-5 精排
- **分块策略**：LangChain MarkdownHeaderTextSplitter，按 `##` 标题分块，保留层级结构

**量化效果**：混合检索相较纯向量召回，关键术语匹配提升约 **40%**（个人测试集：30 个技术问答）

### 3. Agentic Self-RAG 反思流水线（2 天）

使用 LangGraph StateGraph 编排 5 节点流水线：

```
用户查询 → Intent Router → Hybrid Retriever → CrossEncoder Reranker →
Self-Reflection（充分性检查）→ LLM 生成（带引用溯源）
```

- **Intent Router**：LLM-as-Classifier，3 分类（知识库/闲聊/实时），决策延迟 <800ms
- **Self-Reflection**：LLM 自查检索结果是否充分，不充分则改写查询最多 2 次重试
- **超时兜底**：每步检索 15s 超时 + 反思 10s 超时，超时自动跳过不卡死
- **流式输出**：LangChain `astream_events` + SSE，分步推送（`event: step`）再逐 token（`event: token`）
- **引用溯源**：回答内 `[N]` 标注来源，前端 CitationModal 展示原文段落

**量化效果**：反思纠错使二次检索召回率提升 **22%**（30 次测试中 7 次补充了有效信息）

### 4. 多供应商 LLM 适配层（1 天）

设计工厂模式（`LLMFactory`）统一适配 3 家供应商：

| 供应商 | 模型 | 用途 | P50 延迟 |
|--------|------|------|----------|
| DeepSeek | deepseek-chat (Flash) | 默认推理 | 1.2s |
| ModelScope | DeepSeek-V4-Pro | 反思/重试备用 | 1.5s |
| Claude | claude-sonnet-5 | 高质量生成 | 2.1s |

- 启动时预热所有 LLM 客户端和 Embedding 模型，避免首次请求冷启动
- 全局 `try-except` 降级：一路失败自动切到下一供应商

### 5. 前端交互与流式 UI（2 天）

- **PipelinePanel**：可视化展示 RAG 各步骤（意图→检索→Rerank→反思→生成），含耗时和文档预览
- **ChatMessage + CitationModal**：流式打字效果、引用 `[N]` 解析、点击弹出原文
- **UploadPanel + PasswordGuard**：文档上传受密码保护（环境变量），sessionStorage 鉴权
- **IP 会话管理**：每次问答自动保存到 IP 缓存，刷新页面恢复历史，配合限流（20 次/min/IP）

### 6. 开发流程：Vibe Coding 多 Agent 闭环

采用 Claude Code Teammate Mode 的 **4-Agent 工作流**（Planner → Developer → Reviewer → Tester）：
- 12+ 个模块迭代，每模块产出 plan.md → 代码 → review-report → test-report
- 共享记忆库 `memory/project-context.md` 保持跨 Agent 上下文一致
- 语义化版本（X.Y.Z-module-XXX）与 Git 分支策略

---

## R — Result（成果与量化指标）

### 交付成果

| 指标 | 数据 |
|------|------|
| **知识库文档** | 70+ 篇技术笔记，分块后约 **200+ chunk**，覆盖 JVM、并发、Spring、分布式等 6 个领域 |
| **平均回答延迟** | **3-5s**（含检索+重排+反思+生成全链路） |
| **首 token 延迟** | **<3s**（前置步骤完成后即开始流式输 token） |
| **检索 Top-5 准确率** | 基线 ~70%，反思重试后提升至 **~85%** |
| **服务可用性** | 3 家供应商互相降级，单家 API 故障不影响整体 |
| **代码行数** | ~5,000 行（Java + Python + TypeScript 三端合计） |
| **部署方式** | Docker Compose 一键启动，含 PostgreSQL + pgvector + Redis |

### 个人成长

- **全栈落地**：完整打通 React → Spring Boot → FastAPI → PostgreSQL/pgvector 的全链路实战
- **RAG 深度实践**：混合检索、语义重排、自我反思、引用溯源、流式 SSE、超时熔断等生产级技术
- **LLM 工程化**：多供应商适配模型、工厂模式管理 LLM 实例、启动预热、优雅降级
- **Agent 协作开发**：通过 Teammate Mode 实现 4 角色协作流水线，管理 12+ 模块迭代

### 代码与文档

- 完整技术方案文档、ADR 决策记录、验收标准模板齐全
- 配套 Docker Compose 一键部署，环境变量驱动配置（无硬编码密钥）
- 项目代码托管于 GitHub（private）

---

> *本项目反映了作者在全栈开发、AI 系统集成和工程化交付方面的综合能力。完整代码和项目文档可联系作者获取。*
