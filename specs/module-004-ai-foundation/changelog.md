# 变更日志 — Module-004: Python AI 层基础架构

## 变更概述
搭建 FastAPI AI 服务骨架：配置管理、pgvector 数据库连接、LLM 多供应商适配（Claude + DeepSeek）、RAG 骨架引擎。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/main.py | 修改 | 添加 lifespan/pgvector 初始化、/ai/config、rag 路由 |
| ai_service/requirements.txt | 修改 | 添加 sqlalchemy[asyncio]/asyncpg/pydantic-settings/langchain-anthropic |
| ai_service/src/__init__.py | 新增 | src 包标记 |
| ai_service/src/config.py | 新增 | pydantic-settings 配置管理（PW_ 前缀） |
| ai_service/src/database.py | 新增 | SQLAlchemy async + asyncpg + pgvector extension |
| ai_service/llm/__init__.py | 新增 | llm 包标记 |
| ai_service/llm/client.py | 新增 | LLM 多供应商适配器（Claude + DeepSeek） |
| ai_service/rag/__init__.py | 新增 | rag 包标记 |
| ai_service/rag/schemas.py | 新增 | 请求/响应 Pydantic 模型 |
| ai_service/rag/engine.py | 新增 | RAG 引擎骨架（module-005 实现） |

## 设计说明

### 适配器模式（LLMClient）
- LLMClient 抽象基类 → ClaudeClient / DeepSeekClient
- LLMFactory 工厂单例，通过 `PW_LLM_PROVIDER` 切换
- 异常统一封装为 LLMException

### 配置管理
- 使用 pydantic-settings + `PW_` 前缀环境变量
- 支持 `.env` 文件
- 配置端点不暴露密钥

## 验证命令
| 验证项 | 命令 | 预期 |
|--------|------|------|
| Python 语法 | `cd ai_service && python -m py_compile main.py` | 无错误 |
| import 验证 | `cd ai_service && python -c "from src.config import settings"` | import OK |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始实现 | Developer-Python |
