# 项目上下文记忆库

## 1. 项目概述
- 项目名称: 张三个人网站
- 项目简介: 融合简历展示与 Agentic RAG 知识库问答的个人网站系统（双语言微服务架构：Java Spring Boot + Python FastAPI + React 前端）
- 创建时间: 2026-07-29
- 最后更新: 2026-07-30

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
| module-018 | Rerank 重排修复（切换 Qwen3-Reranker） | 0.18.0-module-018 | 2026-08-01 | 👀 待审查 |

## 4. 架构决策记录（ADR）索引
| ADR 编号 | 决策标题 | 状态 | 日期 |
|----------|----------|------|------|
| — | — | — | — |

## 5. 当前迭代状态
- 当前迭代版本: v0.18.0
- 正在进行的模块: module-018（Rerank 重排修复 — 切换 Qwen3-Reranker）— 👀 待审查
- 下一个待开发模块: 待定（候选：评估闭环 / 中文FTS复活）

## 7. 关键技术决策记录
- 所有 API 返回格式统一为 {code, msg, data, timestamp, request_id}（详见 CLAUDE.md 第5节）
- 使用 JWT 进行用户认证
- 后端 Java 与 AI 层 Python 通过 HTTP RESTful 接口解耦通信
- Java 端实现熔断降级（Python 服务超时后走兜底逻辑）
- PDF 文档解析使用 Unstructured / PaddleOCR
- 检索策略：BM25 + 向量检索 混合加权 → Rerank 重排
- Agent 具备意图识别路由、自我反思与纠错能力
- Rerank 模型：Qwen3-Reranker-0.6B（本地，module-018 决策；缺权重明确报错，不回退 HF）
