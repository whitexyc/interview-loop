# 代码审查报告 — Module-032: JWT 登录体系

> 审查人：Reviewer | 审查日期：2026-08-05 | 审查轮次：第 1 轮
> 关联 plan：`specs/module-032-jwt-login/plan.md`
> 关联提交：`fffbc5d`（当前 worktree `worktree-m8-knowledge-panel`）
> 提交人：Developer ×3（backend / frontend / python 并行）

---

## 一、审查结论

- [x] ✅ 通过
- [ ] ❌ 不通过
- [x] ⚠️ **有条件通过** — 契约对齐与安全无阻塞项；存在少量非阻塞建议（详见 §四），并需在收尾阶段补齐文档同步

三栈实现与 plan §3 技术方案、§3.5 跨栈契约一致；跨栈契约专项核对全部通过；安全审查通过（BCrypt、密钥不进仓库、LIKE 注入双保险、日志无敏感信息）；三栈测试独立复现全部通过。无阻塞问题，可进入 Tester 验收阶段。

---

## 二、跨栈契约专项核对（本模块核心风险）

| # | 契约项 | 核对结果 | 证据 |
|---|--------|----------|------|
| 1 | JWT 算法 HS256；payload `{sub=user_id, username, exp=7天}` | ✅ | Java `JwtUtil.generateToken`：`.subject(String.valueOf(userId)).claim("username",...).expiration(...)`，jjwt 对 HMAC 密钥强制 HS256；Python `parse_jwt`：`jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])` 读取 `sub`。两端 sub 均为字符串，`exp` 由 pyjwt 自动校验。alg=none 攻击被 `algorithms=["HS256"]` 白名单阻断 |
| 2 | 共享密钥按值对齐（Java `APP_JWT_SECRET` = Python `PW_JWT_SECRET`） | ✅ | Java `application.yml` `secret: ${APP_JWT_SECRET}`（无默认值，缺失启动失败）；Python `config.py` `jwt_secret`（env_prefix=`PW_` → `PW_JWT_SECRET`）。本地 `ai_service/.env` 已设 64 字节值（≥32 要求）。**E2E 需以 .env 值设置 Java 环境变量**（两值必须一致，否则 AI 解析失败） |
| 3 | 响应格式：后端 `CommonResult` 用 `msg`（非 plan 的 `message`） | ✅ | `CommonResult.java` 既有字段为 `msg`（本模块未改动）。前端 `AuthContext.errorMessage` 优先取 `message`、回退 `msg`，并兼容 HTTP 200 `code=1` 与 HTTP 4xx 两种失败形态（`authErrorMessage` 读 `err.response.data`）。契约漂移已被前端吸收 |
| 4 | 记忆 source：`memory:<identity>:`（user_id 优先否则 client_ip） | ✅ | `memory.py` `save`：`source = f"memory:{identity}:"`（尾冒号防前缀重叠泄漏）；`recall` 用 `memory:<identity>:%` LIKE 过滤。user_id 非空优先，否则 client_ip（`resolve_identity`） |
| 5 | `memory.py` `_normalize_identity` 防 LIKE 注入 | ✅ | `_LIKE_META_RE = [%_\\]` 拒绝含元字符的身份 → 降级 `'unknown'`；另 `_escape_like` 双保险；SQL 用参数化绑定 `source LIKE :source_pattern`（`retriever._source_condition`），三重复防护。单测 `TestNormalizeIdentity` 覆盖 `%`/`_`/`\` |
| 6 | 匿名降级：无/非法 token → user_id="" → client_ip（零回归） | ✅ | 中间件 `rate_limit_middleware` 注入 `request.state.user_id = parse_jwt(...)`（health 早退不解析）；`resolve_identity` 空 user_id 回退 client_ip；无 IP 兜底 `'unknown'`。中间件链路单测覆盖合法/无/非法 token 三态 |

### 契约说明（已文档化、前端已兼容）
- plan §3.5 原始契约写失败 `{code:1, message}`，后端实际序列化为 `CommonResult.msg`（HTTP 400）。前端 `AuthContext`/`LoginPage` 测试显式覆盖了 `msg` 与 `message` 两形态，功能无影响。**建议**在 plan §3.5 措辞修订为 `msg`（changelog 已标注）。
- 登录失败 HTTP 状态为 `GlobalExceptionHandler` 对 `BusinessException` 统一的 400，验收判定以 body `code=1` 为准。

---

## 三、安全检查

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 密码 BCrypt（非明文） | ✅ | `AuthService` 用 `spring-security-crypto` 的 `BCryptPasswordEncoder`，DB 列 `password_hash VARCHAR(100)`；`AuthServiceTest` 断言落库值非明文且 `matches` 通过 |
| JWT_SECRET 不进仓库 | ✅ | `ai_service/.env`、`backend/.env` 均被 gitignore（`git check-ignore` 确认）；`git ls-files` 无 `.env`。`application.yml`/`.env.example` 仅为 `${APP_JWT_SECRET}` 占位符，无真实密钥硬编码 |
| 密钥缺失 fail-fast | ✅ | Java `JwtUtil` 构造校验 ≥32 字节，不足抛 `IllegalStateException`；`application.yml` 无默认值，env 缺失 Spring 占位符解析失败即拒绝启动。Python lifespan `if not settings.jwt_secret: raise RuntimeError` |
| LIKE 注入防护 | ✅ | 见 §二 契约 #5：`_normalize_identity` 拒绝元字符 + `_escape_like` 双保险 + SQL 参数化绑定 |
| 日志无敏感信息 | ✅ | 后端 `AuthService`/`JwtUtil` 仅记录 userId/username/expireDays，不记录密码与 token；Python `main.py`/`identity.py` 不记录 token/secret |
| 响应体不返敏感字段 | ✅ | `LoginResult`/`RegisterResult` 仅 `token/username/user_id`，无密码、无哈希 |

---

## 四、发现的问题

### 阻塞问题
无。

### 建议问题（非阻塞）
| 序号 | 严重程度 | 问题描述 | 所在文件 | 修复建议 |
|------|----------|----------|----------|----------|
| 1 | 🟡 建议 | plan §3.5 契约措辞写 `message`，后端实际为 `msg`（前端已兼容两形态，功能无影响，但规格文档与实现不一致） | `specs/module-032-jwt-login/plan.md` | 修订 §3.5 失败响应字段为 `msg` |
| 2 | 🟡 建议 | `AuthService.register` 先 `selectCount` 再 `insert`，并发重复注册存在 TOCTOU 竞态：两个并发请求同时通过计数检查，唯一约束冲突抛 DB 异常 → 500 而非 `code=1`（个人站并发极低，风险可忽略） | `backend/.../AuthService.java` | 捕获 `DuplicateKeyException` 转 `BusinessException(1,"用户名已存在")`，或在 DB 层兜底 |
| 3 | 🟡 建议 | `AuthInterceptor` Bearer 前缀大小写敏感（要求精确 `"Bearer "`），Python `parse_jwt` 大小写不敏感；当前唯一客户端前端恒发 `"Bearer"`，无实际影响 | `backend/.../AuthInterceptor.java` | 可改为 `equalsIgnoreCase` 统一两端行为 |
| 4 | 🟡 建议 | Agent 路径 `ReactContext.client_ip` 字段名已承载 identity（user_id 或 client_ip）值，命名语义过时（changelog 已注明未改 agent 文件） | `ai_service/agent/react.py`、`tool_registry.py` | module-033/034 重构 agent 时可更名为 `identity` |
| 5 | 🟡 建议 | 文档同步滞后：`memory/project-context.md` 行 58 仍为"规划完成，待 DEVELOP 派发"，`memory/file-index.md` 行 83 仍为"规划中"；agent-activity-log 已更新 | `memory/project-context.md`、`memory/file-index.md` | 收尾阶段（task #9）补齐状态行 |

### 技术债务
- plan §3.5 `message`/`msg` 措辞（建议随本模块收尾一并修订）。

---

## 五、验收标准核对（对照 acceptance-criteria.md）

### 功能验收
- [x] 1.1 Java 后端认证：注册可用（BCrypt 落库）、重复用户名报错、登录签发 JWT、密码错误 401/code=1、JWT 校验（AuthInterceptor 保护 `/api/auth/me`）— 代码与单测覆盖
- [x] 1.2 React 前端：登录/注册页（LoginPage）、登录态持久化（localStorage + 启动恢复）、Authorization 附加（client.ts 统一 axios 拦截器 + SSE `authHeader()`）、退出登录、未登录可用（无路由守卫）
- [x] 1.3 Python AI 服务：JWT 解析中间件注入 `request.state.user_id`、无/非法 token 降级 client_ip、记忆 source `memory:<identity>:`、匿名零回归
- [x] 1.4 记忆隔离 E2E：A/B 用户隔离（source 前缀隔离，recall 按身份过滤；真实 E2E 留 Tester 执行）

### 接口契约
- [x] JWT HS256 `{sub, username, exp=7天}` 三栈一致
- [x] 共享密钥 `APP_JWT_SECRET`=`PW_JWT_SECRET`（按值对齐，均不进仓库）
- [x] 登录/注册响应 `{code, data:{token, username, user_id}}`（实际含 `msg/timestamp/request_id`，前端按 `code/data` 解析）
- [x] 前端 /ai 请求带 Bearer 头；AI 无 token 降级 client_ip

### 代码质量
- [x] 注释覆盖（public 方法 Javadoc/Docstring 齐全）
- [x] 命名规范（Java camelCase / Python snake_case / React PascalCase）
- [x] 单方法 ≤50 行、单类 ≤500 行、模块生产代码 ≤600 行（plan 声明调整）
- [x] 编译通过：`mvn test` 编译 ✓、`npm run build`（tsc+vite）✓、Python py_compile 无语法问题
- [x] 无未使用 import / 无未计划依赖（新增 jjwt 0.12.6、spring-security-crypto、pyjwt≥2.8.0，均为 plan §5.1 声明）

### 安全
- [x] 密码 BCrypt 哈希（非明文）
- [x] JWT_SECRET 不进代码/仓库（env 配置）

---

## 六、独立复现记录（Reviewer 实跑）

| 验证项 | 命令 | 实际结果 | 结论 |
|--------|------|----------|------|
| Java 全量单测 | `cd backend && mvn test` | `Tests run: 37, Failures: 0, Errors: 0, Skipped: 0` / `BUILD SUCCESS`（既有 20 无回归 + 新 17） | ✅ 与预期一致 |
| 前端本模块单测 | `npx vitest run src/__tests__/client.test.ts src/__tests__/AuthContext.test.tsx src/__tests__/LoginPage.test.tsx` | `Test Files 3 passed (3)` / `Tests 17 passed (17)` | ✅ 与预期一致 |
| 前端构建 | `cd frontend && npm run build` | `tsc && vite build` → `✓ built in 15.73s`（tsc 无类型错误） | ✅ |
| Python 本模块单测 | `cd ai_service && python -m pytest tests/test_identity.py tests/test_memory.py -q` | `49 passed in 43.65s`（test_identity 20 + test_memory 29） | ✅ |
| 密钥配置 | `.env` 检查 | `PW_JWT_SECRET` 已设 64 字节（≥32）；`.env` gitignored 未提交 | ✅ |
| 契约 JSON | `AuthDtoJsonTest` | `register→{user_id}`；`login→{token, username, user_id}`；token null 省略 | ✅ |

> 注：python 全量回归（215 passed）由 Developer 自测记录，本 Reviewer 仅复现 identity/memory 专项 49 例；`tests/test_identity.py` 在文件头显式 `settings.jwt_secret = _TEST_SECRET`，与 .env 解耦、用例确定性良好。vites 输出中 LoginPage 测试的 `node.exe : NativeCommandError` 为 PowerShell 包装 stderr 的显示产物（退出码 0、17 全过），非测试失败。

---

## 七、架构与规范核对摘要

- 分层：Controller（`AuthController` 仅校验+格式转换）/ Service（`AuthService` 业务）/ Repository（`UserRepository` 纯 CRUD）/ AI 集成层（Python）职责清晰。
- DTO 约束：Entity `UserEntity` 未暴露到 Controller；响应 DTO `RegisterResult`/`LoginResult` 用 `@JsonProperty` 锁定 `user_id` 契约 key。
- 依赖方向：无跨层/反向/循环依赖；新增依赖均有 plan §5.1 依据，无 ADR 需求（JWT 认证决策已在 plan §3 记录）。
- 变更范围：与 plan §3.1 文件清单一致，无超出范围改动；对既有功能无破坏性变更（匿名降级保持 IP 行为）。

---

## 审查人签名

- 审查人：Reviewer
- 日期：2026-08-05
- 结论：⚠️ 有条件通过（无阻塞；建议项见 §四，文档同步留收尾阶段）

> 下一步：Tester 依据 acceptance-criteria.md 执行验收（真实 E2E：注册→登录→带 token 调 /ai→记忆按 user_id 隔离→跨用户隔离）。
