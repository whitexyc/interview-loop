# 开发计划 — Module-001: 项目脚手架搭建

> Planner: Claude (Planner角色) | 日期: 2026-07-29 | 版本: v1

## 0. Agent 配置清单

本模块为全栈脚手架搭建，配置如下：
- **Developer ×1**：统一开发（项目脚手架无前后端分离冲突）

---

## 1. 需求描述

- **需求来源**: prompt.md + 个人信息.md
- **功能描述**: 搭建双语言微服务架构的项目脚手架，包括 Docker Compose 编排、Spring Boot 后端骨架、FastAPI AI 服务骨架、React 前端骨架
- **优先级**: P0（阻塞所有后续模块）

---

## 2. 模块拆分

### 子任务 1: Docker Compose 编排
- **描述**: 创建 `docker-compose.yml`，编排 PostgreSQL 16 (pgvector) + Redis 容器，配置网络和卷
- **预估代码量**: ~30 行（docker-compose.yml）
- **涉及文件**:
  - `docker-compose.yml` (新增)

### 子任务 2: Spring Boot 后端骨架
- **描述**: 创建 Spring Boot 3.2 项目，包含 pom.xml、Application 入口、统一返回格式 CommonResult、全局异常处理、Health API
- **预估代码量**: ~80 行
- **涉及文件**:
  - `backend/pom.xml` (新增)
  - `backend/src/main/java/com/personalwebsite/PersonalWebsiteApplication.java` (新增)
  - `backend/src/main/java/com/personalwebsite/common/CommonResult.java` (新增)
  - `backend/src/main/java/com/personalwebsite/common/GlobalExceptionHandler.java` (新增)
  - `backend/src/main/java/com/personalwebsite/config/CorsConfig.java` (新增)
  - `backend/src/main/resources/application.yml` (新增)

### 子任务 3: React 前端骨架
- **描述**: 创建 Vite + React + TypeScript 项目，包含 package.json、vite.config.ts、App.tsx 入口、简单路由结构
- **预估代码量**: ~60 行
- **涉及文件**:
  - `frontend/package.json` (新增)
  - `frontend/vite.config.ts` (新增)
  - `frontend/tsconfig.json` (新增)
  - `frontend/index.html` (新增)
  - `frontend/src/main.tsx` (新增)
  - `frontend/src/App.tsx` (新增)

### 子任务 4: FastAPI AI 服务骨架
- **描述**: 创建 FastAPI 项目，包含 requirements.txt、main.py 入口、Health API
- **预估代码量**: ~30 行
- **涉及文件**:
  - `ai_service/requirements.txt` (新增)
  - `ai_service/main.py` (新增)

---

## 3. 技术方案

### 涉及数据表
无（本模块不涉及数据库建表）

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/health` | GET | Java 后端健康检查 |
| `/ai/health` | GET | Python AI 服务健康检查 |

### 外部依赖

| 依赖 | 用途 |
|------|------|
| Docker + Docker Compose | 容器化本地开发环境 |
| PostgreSQL 16 + pgvector | 主数据库 + 向量检索 |
| Redis 7.x | 缓存/会话 |
| Spring Boot 3.2.5 | Java 后端框架 |
| FastAPI 0.111.x | Python AI 服务框架 |
| Vite 5.x + React 18 | 前端构建 |

---

## 4. 验收标准
见同目录下的 `acceptance-criteria.md`

---

## 5. 风险评估

- **低风险**: 脚手架不涉及复杂业务逻辑，以配置为主
- **Docker 环境差异**: Windows 平台可能遇到卷挂载路径问题，使用相对路径

---

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始版本 | Planner |
