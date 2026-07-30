# 审查报告 — Module-001: 项目脚手架搭建

## 1. 审查结论

- 结论: **不通过**（1 个阻塞问题需修复）
- 审查时间: 2026-07-29
- 审查人: Reviewer
- 项目路径: D:\AgentCoding\interview-personal

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `CommonResult.java` | L32 | `requestId` 字段序列化为 JSON 时 key 是 `requestId`（camelCase），不符合 CLAUDE.md 第5节规范要求的 `request_id`（snake_case） | 阻塞 | 在字段上添加 `@JsonProperty("request_id")` 注解，或使用 `@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)` 在类级别统一转换 |

### 2.2 高优先级问题

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 2 | `specs/.../plan.md` | L25-26 | plan.md 仍描述 MySQL + Milvus，但实际实现已改为 PostgreSQL + pgvector。plan vs 实现不一致 | 高 | 更新 plan.md 的"模块拆分"和"技术方案"章节，改为 PostgreSQL + pgvector |

### 2.3 建议改进（不阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 3 | `CorsConfig.java` | L21 | `setAllowedOriginPatterns("*")` 过于宽松，acceptance-criteria 要求"仅允许前端域名" | 中 | 开发阶段可保留，但应在生产环境通过环境变量限制具体域名，如 `config.setAllowedOrigins(List.of("http://localhost:3000"))` |
| 4 | `application.yml` | L34 | MyBatis-Plus `id-type: auto` 应为大写 `AUTO`（MyBatis-Plus 枚举值） | 低 | 改为 `id-type: auto` → 实际上是支持的（不区分大小写），无需修改 |
| 5 | `GlobalExceptionHandler.java` | L30 | 异常日志未包含 `request_id`，无法追踪链路 | 低 | 后续模块引入 Filter/Interceptor 自动注入 request_id 后再优化 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| Java 统一返回格式 `{code,msg,data,timestamp,request_id}` | CommonResult.java:L19-32 | ❌ | JSON key 为 `requestId` 非 `request_id` |
| 命名符合 CLAUDE.md 规范 | 全部文件 | ✅ | Java PascalCase/camelCase, Python snake_case |
| 无跨层调用 | HealthController → 无 Service → 无 Repository | ✅ | 健康检查无需 Service 层 |
| 无硬编码密码 | application.yml:L10 | ✅ | 使用 `${DB_PASSWORD:postgres123}` 环境变量 |
| public 方法有 Javadoc | CommonResult, HealthController, GlobalExceptionHandler | ✅ | 全部覆盖 |
| 无空 catch | 全部文件 | ✅ | |
| 方法 ≤ 50 行 | 全部方法 | ✅ | 最长方法 ~15 行 |
| 类 ≤ 500 行 | 全部类 | ✅ | 最长类 ~70 行 |
| 编译通过 | mvn compile | ✅ | BUILD SUCCESS |
| Docker Compose 启动 | docker-compose.yml | ⚠️ | 结构正确，需 Docker 环境验证 |
| 前端骨架完整 | frontend/ | ✅ | Vite + React + TS + Ant Design |
| Python AI 服务骨架 | ai_service/main.py | ✅ | FastAPI + /ai/health |

## 4. 架构评估

- **分层正确性**: ✅ Controller → Service → Repository 三层结构已定义，HealthController 无需 Service（合理）
- **依赖方向**: ✅ 无反向依赖或跨层调用
- **DTO 约束**: ✅ 无 Entity 泄漏到 Controller（本模块无 Entity）
- **新增依赖**: ✅ 所有依赖在 plan.md 中声明

## 5. 安全评估

- [x] SQL 注入防护: N/A（本模块无 SQL 操作）
- [x] XSS 防护: N/A（本模块无用户输入）
- [x] 密码安全: ✅ 使用环境变量注入
- [x] CORS: ⚠️ 开放所有源（开发阶段可接受）
- [x] 敏感信息日志: ✅ 异常日志仅打印 message，不打印敏感参数

## 6. 架构决策记录（ADR）

暂无。

## 7. 审查检查清单

- [x] 命名符合规范（snake_case / camelCase）
- [x] 接口返回统一格式 `{code, msg, data}` → ⚠️ `request_id` 字段名不符（需修复）
- [x] Controller / Service / Repository 分层正确
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch
- [x] 关键操作有日志记录
- [x] 敏感信息处理正确
- [x] 代码长度在限制内
- [x] API 端点命名 kebab-case (`/api/v1/health` ✅)
- [x] 安全性检查通过
