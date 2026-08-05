# 变更日志 — Module-032: JWT 登录体系

> 汇总三栈变更；各栈详细设计见 `changelog-backend.md` / `changelog-frontend.md` / `changelog-python.md`。

## 变更概述

新增完整 JWT 登录体系（跨三栈），作为记忆隔离身份基础设施（供 module-033/034 使用）：

- **Java 后端**：users 表（Flyway V032）+ 注册/登录接口（CommonResult 统一响应）+ HS256 JWT 签发/解析（payload `{sub=user_id, username, exp=7天}`）+ BCrypt 密码 + AuthInterceptor（仅保护 /api/auth/me，不 gate 公开内容）+ JWT_SECRET fail-fast。
- **React 前端**：登录/注册页（LoginPage）+ 登录态管理（AuthContext，localStorage 持久化 + 启动恢复）+ 统一请求封装 api/client.ts（/api 与 /ai 自动附 `Authorization: Bearer <token>`，SSE fetch 走 authHeader）+ AppLayout 登录入口（不强制登录）。
- **Python AI 服务**：JWT 解析中间件（src/identity.py：parse_jwt + resolve_identity，user_id 优先否则 client_ip）+ 记忆 source 改 `memory:<identity>:`（匿名降级零回归）+ 各端点经 resolve_identity 传身份。

## 文件变更列表（三栈汇总）

### Java 后端
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `backend/src/main/resources/db/migration/V032__create_users.sql` | 新增 | users 表 DDL |
| `backend/src/main/java/com/personalwebsite/model/UserEntity.java` | 新增 | 用户实体 |
| `backend/src/main/java/com/personalwebsite/repository/UserRepository.java` | 新增 | 用户数据访问 |
| `backend/src/main/java/com/personalwebsite/service/JwtUtil.java` | 新增 | HS256 签发/解析 |
| `backend/src/main/java/com/personalwebsite/service/AuthService.java` | 新增 | 注册/登录业务 + BCrypt |
| `backend/src/main/java/com/personalwebsite/service/dto/{AuthRequest,RegisterResult,LoginResult}.java` | 新增 | 认证 DTO |
| `backend/src/main/java/com/personalwebsite/controller/AuthController.java` | 新增 | /api/auth/register|login|me |
| `backend/src/main/java/com/personalwebsite/interceptor/AuthInterceptor.java` + `config/WebConfig.java` | 新增 | token 校验拦截器 |
| `backend/src/main/resources/application.yml` | 修改 | jwt.secret（${APP_JWT_SECRET}）+ expire-days |
| `backend/pom.xml` | 修改 | jjwt 0.12.6 + spring-security-crypto |
| `backend/src/test/.../JwtUtilTest/AuthServiceTest/AuthControllerTest/AuthDtoJsonTest.java` | 新增 | 17 个新测试 |

### React 前端
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `frontend/src/api/client.ts` | 新增 | 统一请求封装（getToken/setToken/authHeader/createHttp/apiHttp/aiHttp） |
| `frontend/src/auth/AuthContext.tsx` | 新增 | 登录态管理（token/user 持久化 + login/register/logout） |
| `frontend/src/pages/LoginPage.tsx` | 新增 | 登录/注册页（antd） |
| `frontend/src/components/AppLayout.tsx` | 修改 | 顶部登录入口/用户名·退出 |
| `frontend/src/App.tsx` | 修改 | AuthProvider + /login 路由 |
| `frontend/src/services/{resume,conversation,rag}Service.ts` | 修改 | 复用 apiHttp/aiHttp（自动带 token）；SSE fetch 加 authHeader |
| `frontend/src/__tests__/{client,AuthContext,LoginPage}.test.*` | 新增 | 17 个新测试 |

### Python AI 服务
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/src/identity.py` | 新增 | parse_jwt + resolve_identity（user_id 优先否则 client_ip） |
| `ai_service/src/config.py` | 修改 | 新增 jwt_secret（PW_JWT_SECRET） |
| `ai_service/main.py` | 修改 | rate_limit_middleware 注入 user_id；端点用 resolve_identity；lifespan JWT_SECRET fail-fast |
| `ai_service/rag/memory.py` | 修改 | source `memory:<identity>:`；参数 ip→identity |
| `ai_service/rag/engine.py` | 修改 | chat/_recall_memory 参数 client_ip→identity |
| `ai_service/requirements.txt` | 修改 | pyjwt>=2.8.0 |
| `ai_service/.env` / `.env.example` | 修改 | PW_JWT_SECRET（.env 已 gitignore） |
| `ai_service/tests/test_identity.py` | 新增 | 20 个新测试 |

## 关键设计说明

### 跨栈契约（Reviewer 专项核对项）
1. **`message` vs `msg` 偏差**：plan §3.5 原始契约写 `message`，但后端统一响应实际为 `CommonResult.msg`（既有字段，未改动）。前端 AuthContext 已兼容两种失败形态（HTTP 200 code=1 + HTTP 4xx msg）。**建议修正 plan §3.5 契约措辞为 `msg`**。
2. **共享密钥按值对齐**：Java `APP_JWT_SECRET`（application.yml env）与 Python `PW_JWT_SECRET`（.env）**必须同值**。E2E 需以 .env 值设置 Java 环境变量；.env.example 已文档化占位。
3. **登录失败 HTTP 400**：后端 BusinessException 统一 400，验收以 body `code=1` 为准。

### 各栈关键决策（详见分片）
- Backend：JWT HS256 + secret fail-fast；BCrypt 仅引 spring-security-crypto；业务失败统一 BusinessException；拦截器不 gate 公开内容。
- Frontend：统一请求封装双通道带 token（axios 拦截器 + SSE authHeader）；token/user 双持久化；注册即登录；失败兼容 HTTP 200/4xx。
- Python：身份解析独立模块；复用现有限流中间件注入 user_id；记忆隔离键 user_id 优先；memory 安全模型升级（LIKE 元字符拒绝）；JWT_SECRET fail-fast。

## 验证命令（三栈 Developer 自测已过）

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| Java | `cd backend && mvn test` | 37 run / 0 fail（既有 20 无回归 + 新 17） |
| 前端 | `cd frontend && npm run build && npx vitest run` | build ✓；31/34（3 既有 ChatPage 失败，git stash 基线验证与本模块无关） |
| Python | `cd ai_service && python -m pytest tests/ -q` | **215 passed / 0 failed**（基线 195 + 新 20，零回归） |
| 语法 | `python -m py_compile main.py src/config.py src/identity.py rag/memory.py rag/engine.py` | 通过 |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 三栈 JWT 登录实现（后端 auth / 前端登录页 / AI 身份解析）+ 测试 | Developer ×3（并行） |
