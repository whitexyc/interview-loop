# 功能规格说明书 — Module-032: JWT 登录体系（后端 auth + 前端登录页 + AI 服务解析）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-032 |
| 模块名称 | JWT 登录体系 |
| 版本号 | 0.32.0-module-032 |
| 优先级 | P1（记忆身份基础设施；后续 module-033/034 依赖此 user_id） |
| 预估代码量 | **声明调整：≤ 600 行**（跨三栈，工作流 §3.1 允许 plan 声明调整；默认 200 行不适用） |
| 创建日期 | 2026-08-05 |
| 最后更新 | 2026-08-05 |
| 负责人 | Planner: 规划执行, Developer: 3 栈并行（Backend/React/Python） |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：用户直接需求（记忆架构讨论，2026-08-05）
- 原始描述：三层记忆架构（长期/短期/会话）需要**登录用户身份**作为记忆隔离键。系统当前**无任何认证**（纯 IP），需引入完整 JWT 登录。用户选定：**完整 JWT 登录**（非轻量/访客标识）。

### 2.2 用户故事

```
作为 网站用户
我想要 登录后获得稳定用户身份（user_id）
以便 我的长期/短期记忆按用户隔离（跨设备、跨会话），匿名访客仍可用（降级 IP）
```

### 2.3 验收场景（BDD 格式）

```
场景 1：注册
  假设 提交用户名+密码
  当 调 POST /api/auth/register
  那么 创建用户（密码 BCrypt 哈希存储），重复用户名明确报错

场景 2：登录
  假设 已注册用户提交正确凭证
  当 调 POST /api/auth/login
  那么 返回 JWT（payload 含 sub=user_id, username, exp=7天）

场景 3：AI 服务识别用户
  假设 前端带 Authorization: Bearer <token> 调 /ai
  当 AI 服务处理请求
  那么 解析出 user_id 注入 request.state；记忆按 memory:<user_id>: 隔离

场景 4：匿名降级
  假设 无 token 或非法 token 调 /ai
  当 AI 服务处理请求
  那么 降级用 client_ip（匿名零回归，行为与现在一致）

场景 5：记忆隔离
  假设 用户 A 登录保存了记忆
  当 用户 B 用自己身份检索
  那么 检索不到 A 的记忆（source 前缀隔离）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容 | 匿名访问（无登录）行为零回归（降级 IP） |
| 安全 | 密码 BCrypt 存储；JWT 密钥走环境变量/配置，不进仓库 |
| 回归 | 三栈全量测试通过（pytest 195 / mvn / vitest） |
| 契约 | 三栈按 §3.5 契约对齐（Reviewer 专项核对） |

---

## 3. 技术方案

### 3.1 涉及文件（三栈）

| 文件路径 | 栈 | 操作类型 | 说明 |
|----------|-----|----------|------|
| `backend/src/main/java/com/personalwebsite/controller/AuthController.java` | Java | 新增 | 注册/登录接口 |
| `backend/src/main/java/com/personalwebsite/service/AuthService.java` | Java | 新增 | 注册/登录业务 + BCrypt |
| `backend/src/main/java/com/personalwebsite/service/JwtUtil.java` | Java | 新增 | HS256 签发/解析 |
| `backend/src/main/java/com/personalwebsite/model/UserEntity.java` | Java | 新增 | 用户实体 |
| `backend/src/main/java/com/personalwebsite/repository/UserRepository.java` | Java | 新增 | 用户数据访问 |
| `backend/src/main/java/com/personalwebsite/interceptor/AuthInterceptor.java` | Java | 新增 | 受保护接口鉴权（按需） |
| `backend/src/main/resources/db/migration/V032__create_users.sql` | Java | 新增 | users 表 DDL |
| `backend/src/main/resources/application.yml` | Java | 修改 | jwt-secret 配置（env 覆盖） |
| `backend/pom.xml` | Java | 修改 | 新增 jjwt / spring-security-crypto 依赖 |
| `frontend/src/pages/LoginPage.tsx` | React | 新增 | 登录/注册页 |
| `frontend/src/auth/AuthContext.tsx` | React | 新增 | 登录态 + token 存取（localStorage） |
| `frontend/src/api/client.ts` | React | 新增/修改 | 请求封装：自动附 Authorization |
| `frontend/src/components/AppLayout.tsx` | React | 修改 | 顶部登录/用户入口 |
| `frontend/vite.config.ts` | React | 修改（无需，/api 已代理） | — |
| `ai_service/main.py` | Python | 修改 | JWT 解析中间件 → request.state.user_id |
| `ai_service/rag/memory.py` | Python | 修改 | source 前缀 `memory:<user_id>:` |
| `ai_service/rag/engine.py` | Python | 修改 | `_recall_memory` / `save` 用 user_id |
| `ai_service/.env` | Python | 修改 | JWT_SECRET（本地） |

### 3.2 业务逻辑说明

#### Java 后端（功能 1：注册/登录 + JWT）

```
1. users 表: id BIGSERIAL PK, username VARCHAR UNIQUE, password_hash VARCHAR, created_at
2. POST /api/auth/register {username, password}:
   - 用户名唯一校验（重复 → 业务错误 code）
   - BCrypt 哈希存储
3. POST /api/auth/login {username, password}:
   - 校验 BCrypt，失败 → 401
   - 签发 JWT（HS256, sub=user_id, username, exp=7天）
   - 返回 {code:0, data:{token, username, user_id}}
4. 可选 AuthInterceptor 保护 /api/auth/me（本项目登录不 gate 公开内容，
   拦截器仅用于验证 token 有效性，公开接口不强制）
```

#### React 前端（功能 2：登录页 + 登录态）

```
1. LoginPage: 登录/注册表单（antd），调 /api/auth/login|register
2. AuthContext: token + user 状态；token 存 localStorage；启动时恢复
3. api/client.ts: 统一请求封装，存在 token 时自动附 Authorization: Bearer <token>
   （/api 与 /ai 均附加，供 Java 与 AI 服务识别用户）
4. AppLayout: 顶部"登录/用户名·退出"入口；未登录仍可正常使用（不强制登录）
```

#### Python AI 服务（功能 3：JWT 解析 → user_id）

```
1. 中间件: 读取 Authorization: Bearer <token> → pyjwt 解析（HS256, 共享 JWT_SECRET）
   - 成功 → request.state.user_id = payload.sub
   - 无 token / 非法 / 过期 → request.state.user_id = "" （降级）
2. 身份解析辅助: resolve_identity(request) → user_id if user_id else client_ip
   （保持匿名访问用 client_ip 的行为，零回归）
3. rag/memory.py: MEMORY_SOURCE_PREFIX 从 'memory:<ip>:' 改为 'memory:<identity>:'
   save/recall 的 identity 参数 = user_id 优先，否则 client_ip
4. engine.py: _recall_memory(query, identity) 等签名同步
```

### 3.3 关键设计决策

| 决策 | 说明 |
|------|------|
| 完整 JWT 登录（用户选定） | 记忆身份基础设施，后续 module-033/034 依赖 |
| 登录不 gate 公开内容 | 个人站公开可看；登录仅为记忆隔离。前端不强制登录 |
| 匿名降级 IP | 无 token/非法 → 用 client_ip，现有行为零回归 |
| 共享 JWT_SECRET 走 env | Java application.yml + AI .env 同值；不进代码/仓库 |
| BCrypt 密码 | 不存明文/可逆加密 |
| 分三栈模块 | module-032 只做身份基础设施；记忆自动写入/短期/会话在 033/034 |

### 3.4 异常处理

| 异常场景 | 处理方式 |
|----------|----------|
| 重复用户名注册 | 业务错误，返回明确 message |
| 密码错误登录 | 401 |
| 非法/过期 JWT | AI 服务降级 client_ip；Java 受保护接口 401 |
| JWT_SECRET 缺失 | 服务启动报错（明确配置缺失，不静默） |
| AI 服务无 token | 正常处理，降级 IP（零回归） |

### 3.5 跨栈契约（三栈 Developer 必须严格对齐，Reviewer 专项核对）

```
JWT:
  - 算法 HS256；payload {sub: user_id, username, exp: 7天}
  - 共享密钥 JWT_SECRET（Java application.yml 配置 + AI .env，值一致）

后端接口（Java 8080，前端经 /api 代理）:
  - POST /api/auth/register {username, password}
      → 成功 {code:0, data:{user_id}} | 失败 {code:1, msg:"用户名已存在"}（HTTP 400）
  - POST /api/auth/login {username, password}
      → 成功 {code:0, data:{token, username, user_id}} | 失败 {code:1, msg:"用户名或密码错误"}（HTTP 400）
  注：失败字段为 CommonResult 既有 `msg`（非 message），HTTP 400；前端 AuthContext 兼容 message/msg 两形态。

前端→AI 服务: 所有 /ai 请求带 Authorization: Bearer <token>（有 token 时）

AI 服务身份解析:
  - request.state.user_id（JWT.sub）；无/非法 token → "" 降级 client_ip
  - 记忆 source: memory:<identity>:long: / memory:<identity>:short:
```

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
# Java
cd backend && mvn test

# 前端
cd frontend && npm run build && npx vitest run

# AI
cd ai_service && python -m pytest tests/ -q

# E2E（真实服务）
# 1. 起三服务 2. 注册 → 登录拿 token 3. 带 token 调 /ai 4. 验证记忆按 user_id 隔离
```

### 4.2 预期输出

```
注册/登录: {code:0, data:{token, username, user_id}}
AI 带 token: 记忆 source = memory:<user_id>:
AI 无 token: 行为与现在一致（client_ip）
回归: pytest 195 passed / mvn 通过 / vitest 通过
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| AI 解析不到 user_id | JWT_SECRET 不一致 | 核对 Java/AI 两端 secret |
| 登录 401 | BCrypt 或用户名不匹配 | 检查 register 是否成功 |
| 前端没带 token | api/client 未附加 | 检查请求封装 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖 | 说明 | 状态 |
|------|------|------|
| Java Spring Boot 3.2 | 后端基础 | ✅ 已有 |
| 前端 React + antd | 页面基础 | ✅ 已有 |
| AI FastAPI + pyjwt（新增） | JWT 解析 | 需安装 pyjwt |
| Java jjwt + spring-security-crypto（新增） | JWT + BCrypt | 需加依赖 |

### 5.2 下游依赖

- module-033（长期记忆自动写入）、module-034（短期/会话记忆）依赖本模块的 `user_id` 身份。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 三栈契约漂移 | 登录后 AI 识别不了用户 | 中 | 契约写死 §3.5；Reviewer 专项核对 |
| JWT_SECRET 泄露/不一致 | 伪造 token / 解析失败 | 中 | env 配置不进仓库；两端一致 |
| 依赖安装失败（pyjwt/jjwt） | 构建失败 | 低 | venv/pom 标准安装 |
| 匿名回归风险 | 未登录用户记忆行为变化 | 低 | 降级 client_ip，现有测试覆盖 |

### 6.2 技术注意事项

- [x] vite 已代理 /api→8080、/ai→8000（无需改代理）
- [ ] 前端请求封装统一（api/client.ts），避免散落的 fetch 漏带 token
- [ ] JWT_SECRET 用环境变量，.env 不入库（gitignore 已有 .env?）

### 6.3 开发建议

- 后端先行（契约源头），前端/AI 并行；契约以 plan §3.5 为准
- 三栈 Developer 并行，各自自测后统一交给 Reviewer

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-05 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
