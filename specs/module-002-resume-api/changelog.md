# 变更日志 — Module-002: 简历数据模型与API

## 变更概述
创建 PostgreSQL 简历数据表、Java 实体/Repository/Service/Controller，提供 `GET /api/v1/resume` 接口，启动时自动初始化种子数据。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| backend/pom.xml | 修改 | 添加 Flyway 依赖 |
| backend/src/main/resources/db/migration/V1__create_resume_tables.sql | 新增 | Flyway 迁移脚本（resume_profiles 表，JSONB 字段） |
| backend/src/main/java/.../model/ResumeEntity.java | 新增 | 简历实体（嵌套 EducationItem/SkillItem/ProjectItem） |
| backend/src/main/java/.../repository/ResumeRepository.java | 新增 | MyBatis-Plus Repository |
| backend/src/main/java/.../service/dto/ResumeDTO.java | 新增 | 数据传输对象 + fromEntity() |
| backend/src/main/java/.../service/ResumeService.java | 新增 | 业务逻辑 + 种子数据初始化 |
| backend/src/main/java/.../controller/ResumeController.java | 新增 | GET /api/v1/resume |
| backend/src/main/java/.../config/MyBatisPlusConfig.java | 新增 | 自动填充 created_at/updated_at |

## 关键设计说明

### 决策 1: JSONB 存储结构化数据
- **决策**: 简历中的教育/荣誉/技能/项目经历使用 PostgreSQL JSONB 存储
- **原因**: 数据结构相对固定但嵌套深度不一，JSONB 保持灵活且支持索引查询

### 决策 2: MyBatis-Plus JacksonTypeHandler
- **决策**: 使用 `@TableField(typeHandler = JacksonTypeHandler.class)` 自动序列化/反序列化 JSONB
- **原因**: 零配置，自动映射，无需手写 TypeHandler

### 决策 3: 种子数据 @PostConstruct 初始化
- **决策**: 启动时自动检查并初始化简历数据
- **原因**: 开发/演示环境快速启动，无需手动执行 INSERT

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 编译 | `cd backend && mvn compile -q` | BUILD SUCCESS |
| 测试 | `cd backend && mvn test` | Tests run: 20, Failures: 0 |
| 接口 | `curl http://localhost:8080/api/v1/resume` | `{"code":0,"data":{"name":"张三",...}}` |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-29 | 初始实现 | Developer |
