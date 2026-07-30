# 技术栈配置文档

> 项目初始化时填写。技术栈变更时必须更新此文档并记录 ADR。

---

## 1. 项目信息

- **项目名称**：张三个人网站（Personal Website）
- **项目简介**：融合简历展示与 Agentic RAG 知识库问答的个人网站系统
- **创建时间**：2026-07-29
- **最后更新**：2026-07-29 22:35

---

## 2. 后端技术栈（Java）

| 维度 | 选型 | 版本 | 配置说明 |
|------|------|------|----------|
| 语言 | Java | 21 | JDK 路径: D:\JAVA1\JDK\jdk-21 |
| 框架 | Spring Boot | 3.2.x | |
| 构建工具 | Maven | 3.9+ | |
| ORM | MyBatis-Plus | 3.5.x | |
| API 文档工具 | SpringDoc OpenAPI | 2.3.x | |
| 数据库连接池 | HikariCP | 内置 | |

### 后端中间件配置

| 中间件 | 用途 | 版本 | 配置参数 |
|--------|------|------|----------|
| Redis | 缓存/会话管理 | 7.x | maxmemory=512mb, eviction=allkeys-lru |

---

## 3. 前端技术栈

| 维度 | 选型 | 版本 | 配置说明 |
|------|------|------|----------|
| 框架 | React | 18.x | |
| 语言 | TypeScript | 5.x | |
| 构建工具 | Vite | 5.x | |
| UI 组件库 | Ant Design | 5.x | |
| 状态管理 | Zustand | 4.x | |
| HTTP 客户端 | Axios | 1.x | |
| 路由 | React Router | 6.x | |

---

## 4. 数据库

| 维度 | 选型 | 版本 | 配置说明 |
|------|------|------|----------|
| 主数据库 | PostgreSQL + pgvector | 16 | 连接池20，pgvector 扩展用于向量检索 |
| 数据库迁移工具 | Flyway | 9.x | |

### 数据库连接配置

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=personal_website
DB_USER=postgres
DB_PASSWORD=123456
DB_POOL_SIZE=20
```

---

## 5. AI 集成（Python）

| 维度 | 选型 | 配置说明 |
|------|------|----------|
| AI 模型供应商 | DeepSeek API + ModelScope | |
| SDK / 框架 | LangChain | |
| 向量库 | pgvector (PostgreSQL 扩展) | 向量检索 |
| 重排模型 | Cohere / BGE-reranker | Rerank Top20→Top5 |
| 文档解析 | Unstructured / PaddleOCR | PDF/图片版面分析 |
| 搜索引擎 | BM25 + 向量检索 | 混合加权召回 |
| 运行时 | FastAPI | 向 Java 端提供 HTTP 接口 |

### AI 模型配置

| 供应商 | API Key | 模型 | 用途 |
|--------|---------|------|------|
| DeepSeek | 见 .env | deepseek-flash | 默认推理 |
| ModelScope（魔搭） | 见 .env | deepseek-ai/DeepSeek-V4-Pro | 高性能推理 |

---

## 6. 基础设施

| 维度 | 选型 | 配置说明 |
|------|------|----------|
| 容器化 | Docker | |
| 编排 | Docker Compose | MySQL + Milvus + Redis |
| CI/CD | GitHub Actions | |
| 部署方式 | 云服务器 | |
| 日志收集 | ELK / Loki | |

---

## 7. 测试框架

| 类型 | 框架 | 版本 | 配置说明 |
|------|------|------|----------|
| 单元测试 | JUnit 5 + pytest | | |
| 集成测试 | TestContainers | | |
| Mock 工具 | Mockito / pytest-mock | | |

---

## 8. 变更记录

| 日期 | 变更内容 | ADR 编号 |
|------|----------|----------|
| 2026-07-29 | 初始化技术栈 | — |
