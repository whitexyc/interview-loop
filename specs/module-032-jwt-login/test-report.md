# 测试报告 — module-032: JWT 登录体系

> 📋 本文件由 Tester 维护，记录该模块的测试执行结果和验收结论。
> 测试通过后，在验收标准文件签署验收结论。

---

## 模块信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-032 |
| 模块名称 | JWT 登录体系 |
| 开发计划 | `specs/module-032-jwt-login/plan.md` |
| 验收标准 | `specs/module-032-jwt-login/acceptance-criteria.md` |
| 变更日志 | `specs/module-032-jwt-login/changelog.md` |
| 审查报告 | `specs/module-032-jwt-login/review-report.md` |
| 测试员 | Tester |
| 测试日期 | 2026-08-05 |

---

## 1. 测试环境

| 字段 | 内容 |
|------|------|
| 后端框架 | Java Spring Boot 3.2 + MyBatis-Plus |
| 数据库 | PostgreSQL 16.14（本机 localhost:5432/personal_website） |
| 测试框架 | JUnit 5 + Mockito / pytest / vitest |
| 平台 / OS | Windows 11 |
| 已知环境坑 | PowerShell `Get-Content` 会向字符串注入 ETS 附加属性（PSPath/PSDrive 等），`ConvertTo-Json` 会把这些属性序列化成 JSON 对象，导致 Java `@RequestBody` 反序列化失败（测试脚本需用 `[System.IO.File]::ReadAllText()` 读取，非模块缺陷） |
| 依赖前置 | pyjwt（hermes venv，非 uv 全局 python）；AI 服务需用 `<home>\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe` 启动 |
| 与 CI / 其他环境差异 | — |
| 运行环境 | 本地开发环境 |
| 测试命令 | `mvn test` / `npx vitest run` / `python -m pytest tests/ -q` |

---

## 2. 单元测试

### 2.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试文件数 | 三栈合计（Java 17 新增 + Python 20 新增 + 前端 17 新增） |
| 测试用例总数 | Java 全量 37 / Python 全量 215 / 前端全量 34 |
| 通过 | Java 37 / Python 215 / 前端 31 |
| 失败 | Java 0 / Python 0 / 前端 3（既有 ChatPage 环境性失败，与本模块无关） |
| 跳过 | 0 |
| 行覆盖率 | — |
| 分支覆盖率 | — |
| 方法覆盖率 | — |
| 覆盖率要求 | ≥ 80%（默认，按 plan.md 约定执行） |

### 2.2 测试用例明细

| 测试类 | 测试方法 | 场景描述 | 结果 |
|--------|----------|----------|------|
| `JwtUtilTest`（Java） | shouldParseGeneratedToken | 签发→解析 sub/username | ✅ |
| `JwtUtilTest`（Java） | shouldHaveSevenDayExpiration | exp-iat ≈ 7 天 | ✅ |
| `JwtUtilTest`（Java） | shouldRejectExpiredToken | 过期 token 抛异常 | ✅ |
| `JwtUtilTest`（Java） | shouldRejectTamperedToken | 篡改 token 抛异常 | ✅ |
| `JwtUtilTest`（Java） | shouldRejectShortSecret | secret <32 字节 fail-fast | ✅ |
| `AuthServiceTest`（Java） | shouldRegisterNewUser | BCrypt 落库 + user_id | ✅ |
| `AuthServiceTest`（Java） | shouldRejectDuplicateUsername | 重复用户名 code=1 | ✅ |
| `AuthServiceTest`（Java） | shouldRejectBlankUsername | 空用户名不落库 | ✅ |
| `AuthServiceTest`（Java） | shouldLoginWithValidCredentials | 登录签发 JWT | ✅ |
| `AuthServiceTest`（Java） | shouldRejectWrongPassword | 错误密码 code=1 | ✅ |
| `AuthServiceTest`（Java） | shouldRejectUnknownUser | 未知用户 code=1 | ✅ |
| `AuthControllerTest`（Java） | 3 例 | 接口返回格式 | ✅ |
| `AuthDtoJsonTest`（Java） | 3 例 | 契约 JSON | ✅ |
| `test_identity.py`（Python） | 20 例 | JWT 解析/无 token 降级/非法 token 降级 | ✅ |
| `test_memory.py`（Python） | 29 例 | 记忆 source 前缀/隔离/LIKE 注入防护 | ✅ |
| `client.test.ts`（前端） | — | 请求封装附 Authorization | ✅ |
| `AuthContext.test.tsx`（前端） | — | 登录态持久化/恢复/登出 | ✅ |
| `LoginPage.test.tsx`（前端） | — | 登录注册表单 | ✅ |

### 2.3 失败用例详情

| 测试方法 | 预期结果 | 实际结果 | 失败原因 | 归类 | 严重度 |
|----------|----------|----------|----------|------|--------|
| ChatPage.test.tsx 3 例 | 渲染/发送/错误提示 | 3 例失败 | 既有基线失败（`conversationService` 未 mock 导致 `activeConversationId=null`、`doSend` 守卫提前 return、`getByText('知识库')` 断言过期），文件最后修改为 module-029（`git log` 确认 `ChatPage.test.tsx` 未被 module-032 触碰） | 环境性失败 | 低 |

> 归类取值：环境性失败 / 真实回归 / 待排查（详见第 5 章「环境性失败归因」）。
> 前端 3 例失败与基线一致（git stash 基线可复现），非本模块引入。

---

## 3. 集成测试

### 3.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试场景数 | 7（真实服务 E2E） |
| 通过 | 4（Java 注册/登录/me + 匿名降级） |
| 失败 | 3（JWT 身份解析、记忆 user_id 隔离、跨用户隔离） |
| 覆盖率要求 | ≥ 60%（默认，按 plan.md 约定执行） |

### 3.2 测试场景明细

| 场景 | 描述 | 前置条件 | 预期结果 | 实际结果 | 状态 |
|------|------|----------|----------|----------|------|
| 注册用户 A | POST /api/auth/register | 真实 Java 服务 + PostgreSQL | code=0, user_id 返回 | code=0, user_id=1 | ✅ |
| 登录用户 A | POST /api/auth/login | A 已注册 | code=0, {token, username, user_id} | code=0, user_id=1, token 210 字符 | ✅ |
| 重复用户名注册 | 同用户名二次 register | A 已注册 | HTTP 400 code=1 "用户名已存在" | HTTP 400 `{code:1, msg:"用户名已存在"}` | ✅ |
| /api/auth/me 带 token | GET + Bearer | A 已登录 | code=0, user_id/username | code=0, user_id=1 | ✅ |
| /api/auth/me 无 token | GET 无头 | — | 401 | 401 | ✅ |
| 带 token 保存记忆 | POST /ai/memory/save + Bearer | A 已登录 + AI 服务 | source=`memory:1:` | source=`memory:127.0.0.1:` | ❌（见失败详情） |
| 带 token 召回 + 跨用户隔离 | POST /ai/memory/recall | A 保存记忆，B 登录 | B 查不到 A 记忆 | B 召回了 A 的记忆（count=2） | ❌（见失败详情） |
| 无 token 保存记忆 | POST /ai/memory/save 无头 | — | source=`memory:<client_ip>:` | source=`memory:127.0.0.1:`（匿名零回归） | ✅ |

---

## 4. 回归测试

### 4.1 回归范围

| 已有模块 | 是否受影响 | 回归测试数 | 结果 |
|----------|-----------|-----------|------|
| Java 后端全部 | 否 | 37 | ✅ 37 run / 0 fail |
| Python AI 服务全部 | 否 | 215 | ✅ 215 passed / 0 failed |
| 前端全部 | 否 | 34 | ⚠️ 31 pass / 3 既有 ChatPage 失败（基线一致） |

### 4.2 回归结果

| 统计项 | 值 |
|--------|-----|
| 回归测试总数 | 三栈合计 286 |
| 通过 | Java 37 + Python 215 + 前端 31 = 283 |
| 失败 | 3（前端既有基线，非本模块） |
| 通过率要求 | 100%（前端既有失败除外，与基线一致） |

### 4.3 三栈回归命令输出（Tester 实跑）

| 验证项 | 命令 | 实际结果 | 结论 |
|--------|------|----------|------|
| Java 全量单测 | `cd backend && mvn test` | `Tests run: 37, Failures: 0, Errors: 0, Skipped: 0` / `BUILD SUCCESS` | ✅ 与预期一致 |
| 前端全量 | `cd frontend && npx vitest run` | `Test Files 1 failed \| 5 passed (6)` / `Tests 3 failed \| 31 passed (34)`，3 失败全在 ChatPage.test.tsx | ⚠️ 与预期一致（31 pass + 3 既有失败） |
| Python 全量 | `cd ai_service && python -m pytest tests/ -q` | `215 passed, 3 warnings in 72.13s` | ✅ 与预期一致 |
| 前端构建 | `cd frontend && npm run build` | Reviewer 已复现 tsc+vite ✓ | ✅ |

---

## 5. 环境性失败归因

| 现象 | 判断标准 | 归类 | 处理方式 |
|------|----------|------|----------|
| 前端 ChatPage.test.tsx 3 例失败 | `git log -- frontend/src/__tests__/ChatPage.test.tsx` 最后提交为 module-029 `e8b4c73`；module-032 提交 `fffbc5d` 未触碰该文件 | 环境性失败（既有基线） | 不阻塞；记录与基线一致 |
| PowerShell `Get-Content` 注入 ETS 属性致登录 500 | `ConvertTo-Json` 把 PSPath/PSDrive 序列化为 JSON 对象，Java 无法反序列化为 String；改用 `[System.IO.File]::ReadAllText()` 后登录成功 | 环境性失败（测试脚本） | 测试脚本修正后重跑即通过，非模块缺陷 |

---

## 6. 真实环境冒烟（真实 E2E）

> 真实服务：Java Spring Boot（:8080，`APP_JWT_SECRET` = ai_service/.env 的 `PW_JWT_SECRET` 值）+ AI 服务（:8000，hermes venv uvicorn）+ 真实 PostgreSQL。AI 服务首次启动需预热 bge-m3 嵌入模型。

### 冒烟命令

```bash
# 启动 AI 服务（hermes venv，含 pyjwt）
cd ai_service
<home>\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000

# 启动 Java 后端（需设置 APP_JWT_SECRET 与 PW_JWT_SECRET 同值）
cd backend
$env:APP_JWT_SECRET = '<PW_JWT_SECRET 值>'
mvn spring-boot:run
```

### 冒烟结果

| 冒烟项 | 命令 | 结果 | 是否通过 |
|--------|------|------|----------|
| 注册 A | `POST :8080/api/auth/register {username,password}` | `{code:0, data:{user_id:1}}` | ✅ |
| 登录 A | `POST :8080/api/auth/login` | `{code:0, data:{token, username, user_id:1}}` | ✅ |
| 带 token 保存记忆 | `POST :8000/ai/memory/save` + Bearer | `{code:0, data:{id, status:"saved"}}`，但 DB source=`memory:127.0.0.1:`（应为 `memory:1:`） | ❌ |
| 带 token 召回 A | `POST :8000/ai/memory/recall` + Bearer | code=0 返回记忆（但按 client_ip 召回，非 user_id） | ⚠️ |
| 跨用户隔离 | B 登录 + recall | B 召回了 A 的记忆（count=2） | ❌ |
| 无 token 匿名保存 | `POST :8000/ai/memory/save` 无头 | `{code:0}`，DB source=`memory:127.0.0.1:` | ✅（匿名零回归） |

### 根因定位（真实 E2E 暴露的跨栈契约缺陷）

1. Java 签发的 JWT header 解码为 `{"alg":"HS512"}`（A、B 两用户均如此）。
2. 共享密钥 `PW_JWT_SECRET`=64 字节（64 个 hex 字符）。jjwt 0.12.6 `JwtUtil.generateToken` 用 `.signWith(key)`（未显式指定算法），`Keys.hmacShaKeyFor(64字节)` 自动选择 **HS512**。
3. Python `src/identity.py` `parse_jwt` 只接受 `algorithms=["HS256"]`，pyjwt 对 HS512 token 抛 `InvalidAlgorithmError: The specified alg value is not allowed` → `parse_jwt` 返回 `""` → `resolve_identity` 降级 `client_ip`。
4. 结果：登录用户身份永不被解析 → 记忆永远按 client_ip 隔离 → A 与 B 在同一 IP（127.0.0.1）下**共享同一记忆命名空间** → 跨用户隔离失败。
5. 单元测试未暴露：Java `JwtUtilTest` 测试密钥 `"test-secret-key-at-least-32-bytes-long!!"` 为 40 字节 → jjwt 选 HS256，与 Python 的 HS256 校验恰好一致；生产 64 字节密钥才触发 HS512。Reviewer 复现（mvn/vitest/pytest）也仅跑单测，未做真实双服务 JWT 握手。

**修复方向（供 Developer）**：`JwtUtil.generateToken` 显式指定 HS256（如 `signWith(key, Jwts.SIG.HS256)`），或在 Java 端把 secret 截断/调整为 ≤48 字节以匹配 HS256 选择，保证与 plan §3.5 契约「HS256」及 Python `algorithms=["HS256"]` 一致。修改后需重跑本 E2E（带 token 保存记忆 → source=`memory:<user_id>:`、跨用户隔离、无 token 降级）。

---

## 7. 异常兜底测试

| 测试场景 | 输入 | 预期行为 | 实际行为 | 结果 |
|----------|------|----------|----------|------|
| 无 token 记忆保存 | POST 无 Authorization | 降级 client_ip（匿名零回归） | source=`memory:127.0.0.1:` | ✅ |
| 非法 token 记忆保存 | Bearer 伪造 token | 降级 client_ip（不 500） | 未单独跑（单测 test_identity 覆盖三态） | ✅（单测覆盖） |
| 重复用户名注册 | 同用户名二次 register | HTTP 400 code=1 | `{code:1, msg:"用户名已存在"}` | ✅ |
| 错误密码登录 | 错误密码 | HTTP 400 code=1 | 探测返回 400（BusinessException 统一 400） | ✅ |
| /api/auth/me 无 token | GET 无头 | 401 | 401 | ✅ |
| LIKE 注入防护 | identity 含 %/_/\ | 拒绝降级 'unknown' + 转义 | 单测 `TestNormalizeIdentity` 覆盖 | ✅（单测覆盖） |

---

## 8. 验收标准核对

> 逐项核对 `acceptance-criteria.md` 中的验收项；详见 acceptance-criteria.md 勾选结果。

### 关键结论

- **Java 后端认证（1.1）**：全部通过（注册/重复用户名/登录/密码错误/JWT 校验 /me）。
- **React 前端（1.2）**：单测 + build 通过（登录态/持久化/Authorization 附加/登出/未登录可用）。
- **Python AI 服务（1.3）**：❌ **JWT 解析中间件未生效**——Java 签发 HS512、Python 仅校验 HS256，真实 token 全被拒绝 → 记忆 source 不能按 user_id 隔离；匿名降级（client_ip）✅ 零回归。
- **记忆隔离 E2E（1.4）**：❌ **跨用户隔离失败**——A/B 同 IP 共享记忆命名空间。
- **契约对齐（2.1）**：❌ **JWT 算法 HS256 三栈一致**未达成（Java 实际 HS512）。
- **代码质量（3）**：通过（注释/命名/长度/编译/BCrypt/JWT_SECRET 不进仓库）。
- **测试验收（4）**：单测 ✅、回归 ✅、真实 E2E ❌（核心链路失败）。

---

## 9. 测试结论

### 总结

| 统计项 | 值 |
|--------|-----|
| 单元测试通过率 | Java 37/37 (100%)、Python 215/215 (100%)、前端 31/34 (91%，3 既有基线) |
| 集成测试通过率 | 4/7（真实 E2E 场景） |
| 回归测试通过率 | Java 100%、Python 100%、前端 31/34（既有基线失败除外） |
| 异常测试通过率 | 单测覆盖 + 冒烟验证 |
| 真实环境冒烟通过率 | 4/7 |
| **总体验收结论** | **不通过** |

### 验收结论

- [ ] ✅ **通过** — 所有测试通过，验收标准全部满足，建议合并
- [x] ❌ **不通过** — 存在核心 E2E 失败，需 Developer 修复后重新测试
- [ ] ⚠️ **有条件通过** — 核心路径通过，非核心问题可后续修复

### 签署

| 字段 | 内容 |
|------|------|
| 测试人 | Tester |
| 签署时间 | 2026-08-05 |
| 结论 | 不通过（存在跨栈 JWT 算法契约缺陷，核心记忆隔离功能 E2E 失败） |
| 记忆库同步确认 | project-context 状态待 Developer 修复后更新 / file-index 待更新 / agent-activity-log 已追加 ✅ |

### 失败详情（阻塞）

| 失败项 | 严重度 | 失败原因 | 建议修复方式 | 是否阻塞 |
|--------|--------|----------|-------------|----------|
| 带 token 记忆 source 应为 `memory:<user_id>:`，实为 `memory:<client_ip>:` | 高 | Java `JwtUtil.generateToken` 对 64 字节 secret 用 jjwt 自动选 HS512；Python `parse_jwt` 仅接受 HS256，真实 token 全部被拒 → 身份不解析、记忆按 client_ip 隔离 | Java 端显式指定 HS256（`signWith(key, Jwts.SIG.HS256)`）或调整 secret 长度以触发 HS256；改后重跑 E2E 全链路 | ✅ |
| 跨用户记忆隔离失败（B 召回 A 的记忆） | 高 | 同上：A/B 登录 token 均被拒，退化为同 IP（127.0.0.1）匿名，共享记忆命名空间 | 同修复方向：HS256 对齐后 user_id 生效，隔离按 user_id 生效 | ✅ |

---

## 10. E2E 测试数据说明

本模块真实 E2E 产生的数据**保留在数据库中**（供 Developer 修复后重测复用），未清理：

- 测试用户：`users` 表 2 条（`e2e_user_a_*` user_id=1、`e2e_user_b_*` user_id=2，BCrypt 密码哈希）。
- 测试记忆：`documents` 表 6 行（id 7695-7700，source=`memory:127.0.0.1:`，标题 `记忆-2026-08-05-01`，为 A 保存 2 行 + B/匿名 4 行的父/子块）。

> 如需清理（修复后重新验收时建议重建），可执行：
> `DELETE FROM documents WHERE id BETWEEN 7695 AND 7700;`
> `DELETE FROM users WHERE id IN (1,2);`

---

## 11. 改进建议

| 建议 | 优先级 | 建议处理时间 |
|------|--------|-------------|
| 三栈回归/契约核对应包含**真实双服务 JWT 握手 E2E**（本模块 Reviewer 复现仅跑单测，未覆盖 64 字节生产密钥下的算法选择差异） | 高 | 本模块修复时 |
| `JwtUtil` 的 jjwt 算法选择与 plan §3.5「HS256」契约存在隐式依赖（依赖密钥长度），建议显式 `signWith(key, Jwts.SIG.HS256)` 消除脆弱性 | 高 | 本模块修复时 |
| plan.md §3.5 契约措辞 `message` vs 实际 `msg` 偏差（Reviewer 建议 #1） | 中 | 收尾阶段 |
| `AuthService.register` TOCTOU 竞态（Reviewer 建议 #2） | 低 | 后续 |
| 文档同步滞后（project-context/file-index 状态行） | 低 | 收尾阶段（task #9） |

---

## 12. 修复复验（2026-08-05，Developer 修复 + team-lead 重跑真实 E2E）

### 修复内容

`JwtUtil.generateToken` 由 `.signWith(key)` 改为显式 `.signWith(key, Jwts.SIG.HS256)`（jjwt 0.12.6），消除"密钥长度决定算法"的隐式依赖（64 字节 → HS512 的缺陷根因）。新增回归测试 `JwtUtilTest.shouldSignHS256WithLongSecret`（64 字节密钥下断言 token header alg=HS256）。

### 复验结果（真实服务）

| 验证项 | 结果 |
|--------|------|
| `mvn test`（含新回归） | **38 run / 0 fail** / BUILD SUCCESS |
| 真实 E2E：注册 A → 登录 | code=0 user_id=3 |
| **token header alg** | **HS256** ✅（修复前 HS512） |
| 带 token 保存记忆 → DB source | **memory:3:**（user_id 隔离生效）✅ |
| 带 token 召回 A | 召回 1 条「用户A的偏好：喜欢用Python和asyncio」✅ |
| **跨用户隔离（B 召回）** | **0 条** ✅（修复前 B 召回 A 的记忆） |
| 无 token 保存 → DB source | memory:127.0.0.1:（匿名降级零回归）✅ |

### 更新后结论

- **总体验收结论：通过（40/40）**——核心跨栈 JWT 契约缺陷已修复并经真实 E2E 复验。
- E2E 测试数据（用户 1-4、记忆行 7695-7704）已在复验后清理。
- 遗留非阻塞项：`AuthService.register` TOCTOU 竞态（Reviewer 建议 #2）、`AuthInterceptor` Bearer 大小写（建议 #3）、`ReactContext.client_ip` 字段命名（建议 #4），留后续模块处理。
