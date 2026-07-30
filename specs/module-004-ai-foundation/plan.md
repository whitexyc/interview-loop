# 开发计划 — Module-004: Python AI 层基础架构

> Planner: Claude | 日期: 2026-07-29 | 版本: v1

## 0. Agent 配置清单
- **Developer-Python ×1**（flash 模型）：FastAPI 骨架 + pgvector 连接 + LangChain 基础
- **Reviewer ×1** → 审查 Python 代码
- **Tester ×1** → Python 单元测试

## 1. 需求描述
- **需求来源**: prompt.md（双语言微服务架构）
- **功能描述**: 搭建 FastAPI AI 服务骨架，连接 pgvector 数据库，配置 LangChain 多供应商 LLM 适配层（Claude + DeepSeek）
- **优先级**: P0（阻塞 module-005 RAG 核心）
- **已确认技术决策**:
  - Java ↔ Python 通信: HTTP REST（Java HttpClient → FastAPI）
  - 数据库连接: Python 直连 PostgreSQL/pgvector
  - AI 供应商: 多供应商抽象（Claude + DeepSeek）

## 2. 模块拆分

### 子任务 1: FastAPI 项目增强
- **描述**: 增强现有 ai_service/main.py，添加配置管理、日志、CORS、健康检查
- **代码量**: ~30 行
- **涉及文件**: `ai_service/main.py` (修改)

### 子任务 2: 数据库连接 + pgvector
- **描述**: 创建 database.py（asyncpg + SQLAlchemy async），创建 pgvector extension
- **代码量**: ~50 行
- **涉及文件**:
  - `ai_service/src/database.py` (新增)
  - `ai_service/src/config.py` (新增)

### 子任务 3: LLM 多供应商适配层
- **描述**: 创建 llm/client.py，用 LangChain 封装 Claude + DeepSeek 适配器，支持运行时切换
- **代码量**: ~60 行
- **涉及文件**:
  - `ai_service/llm/client.py` (新增)

### 子任务 4: RAG 检索骨架
- **描述**: 创建 rag/engine.py 骨架（search/chat 接口桩），注册到 main.py 路由
- **代码量**: ~40 行
- **涉及文件**:
  - `ai_service/rag/engine.py` (新增)
  - `ai_service/rag/schemas.py` (新增)

## 3. 技术方案

### 新增 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ai/rag/search` | POST | RAG 检索（骨架，module-005 实现） |
| `/ai/rag/chat` | POST | RAG 问答（骨架，module-005 实现） |
| `/ai/config` | GET | 返回当前 AI 配置状态 |

### 数据库配置
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres123@localhost:5432/personal_website
```

### 依赖新增
- SQLAlchemy[asyncio] + asyncpg
- langchain-openai, langchain-community (Claude/DeepSeek)
- pydantic-settings

## 4. 验收标准
见同目录 `acceptance-criteria.md`

## 5. 风险评估
- pgvector 在 PostgreSQL 16 中需要自行启用 CREATE EXTENSION
- 多供应商 LLM 适配需处理不同 API 格式差异

## 6. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始版本 | Planner |
