# 变更日志 — Module-032: JWT 登录体系（Java 后端 / 功能 1）

> 本文件记录 Java 后端的变更；React 前端与 Python AI 服务各栈 Developer 各自维护其分区。

## 变更概述

实现 JWT 登录体系的 Java 后端基础：新增 `users` 表（Flyway V032）、注册/登录接口（统一 `CommonResult` 响应）、HS256 JWT 签发/解析（payload `{sub=user_id, username, exp=7天}`）、BCrypt 密码哈希，以及用于验证 token 有效性的可选 `AuthInterceptor`（仅保护 `/api/auth/me`，登录不 gate 公开内容）。密码与 JWT 密钥均不落明文/代码，JWT_SECRET 走环境变量。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `backend/src/main/resources/db/migration/V032__create_users.sql` | 新增 | users 表 DDL（id BIGSERIAL PK、username UNIQUE、password_hash、created_at） |
| `backend/src/main/java/com/personalwebsite/model/UserEntity.java` | 新增 | 用户实体（MyBatis-Plus 注解，password_hash 映射） |
| `backend/src/main/java/com/personalwebsite/repository/UserRepository.java` | 新增 | 用户数据访问（BaseMapper，与现有 Repository 风格一致） |
| `backend/src/main/java/com/personalwebsite/service/JwtUtil.java` | 新增 | HS256 签发/解析；secret 从配置读，过短启动 fail-fast |
| `backend/src/main/java/com/personalwebsite/service/AuthService.java` | 新增 | 注册（唯一校验 + BCrypt）与登录（校验 + 签发 JWT） |
| `backend/src/main/java/com/personalwebsite/service/dto/AuthRequest.java` | 新增 | 注册/登录共用请求体 `{username, password}` |
| `backend/src/main/java/com/personalwebsite/service/dto/RegisterResult.java` | 新增 | 注册响应 `{user_id}`（@JsonProperty 锁定 key） |
| `backend/src/main/java/com/personalwebsite/service/dto/LoginResult.java` | 新增 | 登录响应 `{token, username, user_id}`（token null 时省略） |
| `backend/src/main/java/com/personalwebsite/controller/AuthController.java` | 新增 | POST /api/auth/register、POST /api/auth/login、GET /api/auth/me（受保护） |
| `backend/src/main/java/com/personalwebsite/interceptor/AuthInterceptor.java` | 新增 | Bearer token 校验，非法/过期返回 401，通过后注入 request attribute |
| `backend/src/main/java/com/personalwebsite/config/WebConfig.java` | 新增 | 拦截器注册，仅拦截 `/api/auth/me` |
| `backend/src/main/resources/application.yml` | 修改 | 新增 `jwt.secret`（`${APP_JWT_SECRET}` 环境变量覆盖，无默认值）+ `jwt.expire-days: 7` |
| `backend/pom.xml` | 修改 | 新增 jjwt-api/impl/jackson 0.12.6 + spring-security-crypto |

**新增测试**：
- `backend/src/test/java/com/personalwebsite/service/JwtUtilTest.java` — 签发/解析/过期/篡改/密钥过短
- `backend/src/test/java/com/personalwebsite/service/AuthServiceTest.java` — 注册成功(BCrypt 落库)/重复用户名/空用户名；登录成功/密码错误/用户不存在
- `backend/src/test/java/com/personalwebsite/controller/AuthControllerTest.java` — register/login/me 响应
- `backend/src/test/java/com/personalwebsite/service/dto/AuthDtoJsonTest.java` — 跨栈契约 JSON key 锁定

## 关键设计说明

### 设计决策 1: JWT HS256 + 环境变量密钥（fail-fast）
- 决策：`JwtUtil` 构造注入 `jwt.secret`，校验密钥 ≥32 字节；不足即抛 `IllegalStateException` 拒绝启动。
- 原因：plan §3.4 要求 "JWT_SECRET 缺失 → 服务启动报错（不静默）"。`application.yml` 中 `secret: ${APP_JWT_SECRET}` 无默认值，env 缺失时 Spring 占位符解析失败同样导致启动失败；双保险避免弱密钥运行时静默降级。

### 设计决策 2: BCrypt 用 spring-security-crypto 而非完整 Spring Security
- 决策：仅引入 `spring-security-crypto` 依赖，`AuthService` 内部 `new BCryptPasswordEncoder()`。
- 原因：避免引入完整 Spring Security 的默认 filter 链干扰现有无鉴权应用；BCrypt 单测可直用真实 encoder 验证哈希特性。

### 设计决策 3: 业务失败统一抛 BusinessException → CommonResult `{code:1, message}`
- 决策：重复用户名 → `BusinessException(1, "用户名已存在")`；登录失败（用户不存在或密码错误，同一 message 防枚举）→ `BusinessException(1, "用户名或密码错误")`。
- 原因：复用现有 `GlobalExceptionHandler`，保证所有接口返回统一格式；不改动既有异常处理机制。

### 设计决策 4: AuthInterceptor 不 gate 公开内容
- 决策：拦截器仅注册到 `/api/auth/me`，验证 Bearer token 有效性；非法/过期返回 401 JSON，通过后把 `userId/username` 注入 request attribute。
- 原因：plan §3.2 明确 "登录不 gate 公开内容，拦截器仅验证 token 有效性"，匿名访问零回归。

### 契约解释说明（供 Reviewer/前端对齐）
- plan §3.5 中 `message:"用户名已存在"` 的 `message` 字段，在本后端统一响应格式中实际序列化为 `msg`（见 `CommonResult.java` 既有字段，且 developer.md §2.3 约定 `{code, msg, data, timestamp, request_id}`）。本模块未改动 `CommonResult`，前端按现有 `code`/`msg` 解析即可。
- 登录失败 HTTP 状态为现有 `GlobalExceptionHandler` 对 `BusinessException` 统一的 400；验收判定以 body `code=1` 为准（acceptance-criteria 1.1 验证方式即"返回 code=1"）。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 编译 + 全量单测 | `cd backend && mvn test` | `Tests run: 37, Failures: 0, Errors: 0` / `BUILD SUCCESS`（含既有 20 个测试无回归 + 本模块 17 个新测试） |
| JSON 契约 | `AuthDtoJsonTest` | register→`{"user_id":1}`；login→`{"token":"...","username":"...","user_id":...}` |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始实现（users 表 + AuthService/JwtUtil/AuthController + AuthInterceptor + 测试） | Developer (backend) |
