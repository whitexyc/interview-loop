# 开发计划 — Module-002: 简历数据模型与API

> Planner: Claude (Planner角色) | 日期: 2026-07-29 | 版本: v1

## 0. Agent 配置清单

本模块为纯后端模块，使用 flash 模型节省成本：
- **Developer ×1**（flash 模型）

---

## 1. 需求描述

- **需求来源**: 个人信息.md（张三个人简历）
- **功能描述**: 创建 PostgreSQL 简历数据表、Java 实体类、Repository、Service、Controller，提供 RESTful API 供前端展示简历
- **优先级**: P0

---

## 2. 模块拆分

### 子任务 1: 数据库迁移脚本
- **描述**: 创建 Flyway 迁移脚本 V1__create_resume_tables.sql，包含简历主表（education、project 等用 JSONB 字段存储，保持灵活）
- **预估代码量**: ~50 行
- **涉及文件**:
  - `backend/src/main/resources/db/migration/V1__create_resume_tables.sql` (新增)

### 子任务 2: Resume 实体与 Repository
- **描述**: 创建 ResumeEntity（映射 resume_profiles 表）、ResumeRepository（MyBatis-Plus 接口）
- **预估代码量**: ~40 行
- **涉及文件**:
  - `backend/src/main/java/com/personalwebsite/model/ResumeEntity.java` (新增)
  - `backend/src/main/java/com/personalwebsite/repository/ResumeRepository.java` (新增)

### 子任务 3: Resume Service
- **描述**: 创建 ResumeService，提供获取简历 / 初始化数据的方法。简历数据从 JSON 配置文件或数据库初始化
- **预估代码量**: ~60 行
- **涉及文件**:
  - `backend/src/main/java/com/personalwebsite/service/ResumeService.java` (新增)
  - `backend/src/main/java/com/personalwebsite/service/dto/ResumeDTO.java` (新增)

### 子任务 4: Resume Controller
- **描述**: 创建 ResumeController，提供 GET /api/v1/resume 接口返回完整简历数据
- **预估代码量**: ~30 行
- **涉及文件**:
  - `backend/src/main/java/com/personalwebsite/controller/ResumeController.java` (新增)

---

## 3. 技术方案

### 涉及数据表

```sql
CREATE TABLE resume_profiles (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(50)  NOT NULL,
    gender          VARCHAR(10),
    phone           VARCHAR(20),
    email           VARCHAR(100),
    job_intent      VARCHAR(200),
    github          VARCHAR(200),
    education       JSONB,
    honors          JSONB,
    skills          JSONB,
    projects        JSONB,
    self_evaluation TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/resume` | GET | 获取简历完整数据 |

### 外部依赖
无（复用 module-001 基础设施）

---

## 4. 验收标准
见同目录下的 `acceptance-criteria.md`

## 5. 风险评估

- **低风险**: 纯后端 CRUD，无复杂业务逻辑
- JSONB 字段使用 PostgreSQL 原生支持，无需额外依赖

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始版本 | Planner |
