# 变更日志 — Module-001: 项目脚手架搭建

## 变更概述
搭建双语言微服务架构的项目脚手架：Docker Compose (PostgreSQL+pgvector+Redis)、Spring Boot 后端骨架、React 前端骨架、FastAPI AI 服务骨架。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| docker-compose.yml | 新增 | PostgreSQL(pgvector) + Redis 容器编排 |
| Makefile | 新增 | 常用命令快捷方式 |
| backend/pom.xml | 新增 | Spring Boot 3.2 + PostgreSQL + Redis 依赖 |
| backend/src/main/java/.../PersonalWebsiteApplication.java | 新增 | Spring Boot 入口 |
| backend/src/main/java/.../common/CommonResult.java | 新增 | 统一API返回格式 {code, msg, data, timestamp, request_id} |
| backend/src/main/java/.../common/BusinessException.java | 新增 | 业务异常基类 |
| backend/src/main/java/.../common/GlobalExceptionHandler.java | 新增 | 全局异常处理器 |
| backend/src/main/java/.../config/CorsConfig.java | 新增 | 跨域配置 |
| backend/src/main/java/.../controller/HealthController.java | 新增 | 健康检查 GET /api/v1/health |
| backend/src/main/resources/application.yml | 新增 | 应用配置 |
| ai_service/requirements.txt | 新增 | Python AI 服务依赖 |
| ai_service/main.py | 新增 | FastAPI 入口 + /ai/health 健康检查 |
| frontend/package.json | 新增 | React 18 + Vite + Ant Design 依赖 |
| frontend/vite.config.ts | 新增 | Vite 配置 + API 代理 |
| frontend/tsconfig.json | 新增 | TypeScript 配置 |
| frontend/index.html | 新增 | 入口 HTML |
| frontend/src/main.tsx | 新增 | React 入口 |
| frontend/src/App.tsx | 新增 | 根组件 + 路由骨架 |
| frontend/.env.development | 新增 | 开发环境变量 |

## 关键设计说明

### 决策 1: PostgreSQL + pgvector 一体方案
- **决策**: 使用 PostgreSQL 16 + pgvector 扩展，同时承载业务数据和向量检索
- **原因**: 减少依赖，docker-compose 仅需 3 个容器（PG + Redis + Python），避免 Milvus 重量级依赖链

### 决策 2: 统一返回格式
- **决策**: 所有 API 返回 `{code, msg, data, timestamp, request_id}`
- **原因**: 遵循 CLAUDE.md 第5节规范，确保前后端交互一致

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| Docker 启动 | `docker-compose up -d` | postgres + redis running |
| 后端编译 | `cd backend && mvn compile` | BUILD SUCCESS ✅ |
| 前端安装 | `cd frontend && npm install` | 无错误 |
| 前端构建 | `cd frontend && npm run build` | 无错误 |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始实现：全部骨架代码 | Developer |
