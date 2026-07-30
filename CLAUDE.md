# CLAUDE.md — Vibe Coding 闭环工作流项目规范

> 本文件是整个 Vibe Coding 工作流的核心规范文件，所有 Agent（Planner、Developer、Reviewer、Tester）必须严格遵循本文件定义的规则和流程。

## 目录

| 章节 | 标题 | 简要描述 |
|------|------|----------|
| 1 | [项目概述](#1-项目概述) | 项目背景、核心方法论与 4 Agent 角色概览 |
| 2 | [技术栈](#2-技术栈) | 技术栈配置文档机制与项目初始化确认项 |
| 3 | [目录结构规范](#3-目录结构规范) | 项目完整目录结构定义（含 memory/、templates/、.claude/） |
| 4 | [命名规范](#4-命名规范) | 各语言（Java/Python/TypeScript）文件、变量、类命名规则 |
| 5 | [接口规范（统一返回格式）](#5-接口规范统一返回格式) | API 统一响应结构、状态码、分页与错误响应格式 |
| 6 | [分层架构约束](#6-分层架构约束) | 三层架构（Controller/Service/Repository）与依赖规则 |
| 7 | [编码强制规则](#7-编码强制规则) | 注释覆盖率、异常捕获、日志输出、代码长度、安全编码 |
| 8 | [版本管理规范](#8-版本管理规范) | 语义化版本号（X.Y.Z-module-XXX）与 Git 分支策略 |
| 9 | [Vibe Coding 工作流闭环](#9-vibe-coding-工作流闭环) | 4 Agent 角色定义、闭环流程、完工终审、ADR 规则、快速审查通道 |
| 10 | [共享记忆库规范](#10-共享记忆库规范) | 项目上下文、Agent 活动日志、文件索引与新 Agent 入场流程 |
| 11 | [验收标准模板](#11-验收标准模板) | 模块验收标准的字段结构（功能/接口/代码质量/测试/文档） |
| 12 | [模块开发计划模板](#12-模块开发计划模板) | 模块 plan.md 的字段结构（元信息/需求/技术方案/依赖/风险） |
| 13 | [AI / Agent 开发规范](#13-ai--agent-开发规范) | LLM 调用、Agent 编排、Function Calling / Tool 规范 |
| 14 | [快速启动清单](#14-快速启动清单) | 新项目启动的 8 步操作清单 |
| 15 | [附录：常用命令](#15-附录常用命令) | 构建、测试、Git、数据库迁移、Docker 常用命令 |

---

## 1. 项目概述

本项目基于 Claude Code Teammate Mode 搭建闭环 Vibe Coding 工作流，通过 4 个专业化 Agent 角色协同完成软件需求的完整生命周期。

### 1.1 核心方法论

| 原则 | 说明 |
|------|------|
| **规范前置** | 工程化流程先行，规则/规范定义在编码之前 |
| **分步迭代** | 每个功能模块独立拆分，逐模块交付 |
| **版本管理** | 每次变更生成唯一版本号，支持回退 |
| **模块拆分** | 单一模块默认 ≤ 200 行，特殊情况可在 plan.md 说明理由后调整 |
| **共享记忆** | 统一记忆库 `memory/project-context.md` 保持上下文同步 |
| **验收驱动** | 每个模块定义明确的验收标准，通过后进入下一模块 |

---

## 2. 技术栈

### 2.1 技术栈配置文档

项目技术栈**不预设固定选项**，由用户在项目初始化时填写 `tech-stack.md`（模板见 `templates/tech-stack-template.md`）。

**填写方式**（二选一）：
1. 用户直接填写 `tech-stack.md` 后启动工作流
2. 启动时与 Planner 沟通确认技术栈，由 Planner 代为填写

**文档内容**：后端框架、前端框架、数据库、缓存、消息队列、ORM、AI 集成、API 文档工具、测试框架、CI/CD、部署方式，以及所有中间件及其配置参数。

**更新规则**：技术栈变更时必须更新 `tech-stack.md` 并记录 ADR。

### 2.2 项目初始化确认项

在启动首个模块前，Planner 必须确认 `tech-stack.md` 已填写完整：
- [x] 后端框架及版本（Spring Boot 3.2.x）
- [x] 数据库类型及版本（MySQL 8.x + Milvus 2.4.x）
- [x] 中间件清单及配置（Redis 7.x）
- [x] 前端框架及版本（React 18 + TypeScript + Vite）
- [x] AI 模型供应商（OpenAI / Claude API）
- [ ] CI/CD 工具（GitHub Actions - 待配置）
- [ ] 部署方式（Docker Compose - 待 module 配置）

---

## 3. 目录结构规范

```
interview-personal/
├── CLAUDE.md                          # 本规范文件（所有 Agent 的入口引用）
├── README.md                          # 项目说明
├── tech-stack.md                      # 技术栈配置文档
├── memory/                            # 共享记忆库
│   ├── project-context.md             # 项目上下文
│   ├── agent-activity-log.md          # Agent 活动日志
│   └── file-index.md                  # 项目文件索引
├── templates/                         # 模板文件目录
├── specs/                             # 模块开发产出
│   └── module-XXX-<name>/
│       ├── plan.md
│       ├── acceptance-criteria.md
│       ├── review-report.md
│       ├── test-report.md
│       └── changelog.md
├── docs/                              # 文档目录
│   ├── adr/
│   ├── api/
│   └── requirements/
├── backend/                           # 后端代码（Spring Boot + Java）
│   ├── src/main/java/com/personalwebsite/
│   │   ├── controller/
│   │   ├── service/
│   │   ├── repository/
│   │   ├── model/
│   │   ├── config/
│   │   ├── common/
│   │   └── ai/
│   └── src/main/resources/
├── frontend/                          # 前端代码（React + TypeScript）
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── hooks/
│       ├── services/
│       ├── types/
│       └── utils/
├── ai_service/                        # AI 推理层（Python + FastAPI）
│   ├── src/
│   ├── agent/
│   ├── prompt/
│   ├── llm/
│   ├── memory/
│   ├── tool/
│   └── config/
├── docker-compose.yml
├── .gitignore
├── .claude/
│   ├── agents/
│   │   ├── planner.md
│   │   ├── developer.md
│   │   ├── reviewer.md
│   │   └── tester.md
│   └── workflows/
│       └── vibe-coding-loop.md
└── Makefile
```

---

## 4-15 章节内容

> 以下章节（4-15）与 `<home>\.claude\skills\vibe-coding-workflow\CLAUDE.md` 完全一致，包括：
> - 第4节：命名规范（Java/Python/TypeScript）
> - 第5节：接口规范（统一返回格式、状态码、分页、错误响应）
> - 第6节：分层架构约束（三层架构、依赖规则、DTO约束、AI集成层）
> - 第7节：编码强制规则（注释、异常、日志、代码长度、安全编码）
> - 第8节：版本管理规范（语义化版本号、Git分支策略、提交规范）
> - 第9节：Vibe Coding 工作流闭环（Agent角色、闭环流程、回退重试、快速审查、ADR）
> - 第10节：共享记忆库规范（project-context.md、活动日志、文件索引）
> - 第11节：验收标准模板
> - 第12节：模块开发计划模板
> - 第13节：AI / Agent 开发规范
> - 第14节：快速启动清单
> - 第15节：附录（常用命令）

## 项目特有规范

### 项目架构

```
┌─────────────────────────────────────────────────────────────┐
│                    前端 (React + TypeScript)                   │
│                 简历展示 + RAG 知识库 UI                      │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP RESTful API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│             后端业务层 (Java Spring Boot 3.2)                  │
│   用户管理 / 文件上传 / 元数据管理 / 请求转发 / 熔断降级         │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP RESTful API
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              AI 推理层 (Python FastAPI + LangChain)            │
│   RAG 知识库 / 多源检索 / Rerank / 意图路由 / 自我反思 / 引用溯源 │
└─────────────────────────────────────────────────────────────┘
```

### 熔断降级机制
- Java 端调用 Python AI 服务时实现熔断降级
- Python 服务超时后 Java 返回"系统繁忙"或走纯 LLM 兜底
