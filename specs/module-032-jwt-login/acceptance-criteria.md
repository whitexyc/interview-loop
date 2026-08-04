# 验收标准 — Module-032: JWT 登录体系

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-032 |
| 模块名称 | JWT 登录体系 |
| 关联 plan.md | `specs/module-032-jwt-login/plan.md` |
| 验收日期 | 2026-08-05 |
| 验收人 | Tester |
| 验收版本 | 0.32.0-module-032 |

---

## 1. 功能验收

### 1.1 Java 后端认证

- [ ] 📋 注册接口可用 — 验证方式：POST /api/auth/register 创建用户，密码 BCrypt 存储（DB 非明文）
- [ ] 📋 重复用户名报错 — 验证方式：同用户名二次注册返回 code=1 + "用户名已存在"
- [ ] 📋 登录签发 JWT — 验证方式：POST /api/auth/login 返回 {token, username, user_id}；payload 含 sub/username/exp(7天)
- [ ] 📋 密码错误 401 — 验证方式：错误密码登录返回 code=1
- [ ] 📋 JWT 校验 — 验证方式：AuthInterceptor 对受保护接口验证 token（非法/过期 401）

### 1.2 React 前端

- [ ] 📋 登录/注册页 — 验证方式：LoginPage 表单可提交并跳转
- [ ] 📋 登录态持久化 — 验证方式：token 存 localStorage，刷新后仍登录
- [ ] 📋 Authorization 附加 — 验证方式：登录后 /api 与 /ai 请求带 `Authorization: Bearer <token>`（api/client.ts 统一封装）
- [ ] 📋 退出登录 — 验证方式：清除 token + 用户态
- [ ] 📋 未登录可用 — 验证方式：不登录仍能访问聊天（不强制登录，零回归）

### 1.3 Python AI 服务

- [ ] 📋 JWT 解析中间件 — 验证方式：带合法 token 的 /ai 请求 → request.state.user_id = JWT.sub
- [ ] 📋 无 token 降级 — 验证方式：无/非法 token → user_id 空，降级 client_ip（行为与现状一致）
- [ ] 📋 记忆 source 隔离 — 验证方式：登录用户保存记忆 → source=`memory:<user_id>:`；recall 按 user_id 过滤
- [ ] 📋 匿名零回归 — 验证方式：无 token 时记忆按 client_ip 隔离（与 module-023 行为一致）

### 1.4 记忆隔离 E2E

- [ ] 📋 跨用户隔离 — 验证方式：注册 A/B 两用户，A 保存记忆，B 的 recall 查不到 A 的记忆

---

## 2. 接口验收

### 2.1 契约对齐

- [ ] 📦 JWT 算法 HS256，payload {sub=user_id, username, exp=7天}（三栈一致）
- [ ] 📦 共享密钥 JWT_SECRET（Java application.yml + AI .env 同值，不进仓库）
- [ ] 📦 登录/注册响应格式 `{code, data:{token, username, user_id}}`
- [ ] 📦 前端 /ai 请求带 Bearer 头；AI 无 token 降级 client_ip

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [ ] 💻 所有 public 方法有 Docstring/Javadoc

### 3.2 命名规范

- [ ] 💻 Java camelCase / Python snake_case / React 组件 PascalCase

### 3.3 代码长度

- [ ] 💻 单方法 ≤ 50 行
- [ ] 💻 单类 ≤ 500 行
- [ ] 💻 模块生产代码 ≤ 600 行（plan 声明调整）

### 3.4 编译检查

- [ ] 💻 Java `mvn compile`、前端 `npm run build`、Python py_compile 均通过
- [ ] 💻 无未使用 import / 未计划依赖

### 3.5 安全

- [ ] 💻 密码 BCrypt 哈希（不存明文）
- [ ] 💻 JWT_SECRET 不进代码/仓库（env 配置）

---

## 4. 测试验收

### 4.1 单元测试

- [ ] 🧪 Java AuthService/JwtUtil 单测（注册/登录/BCrypt/JWT 签发校验）
- [ ] 🧪 Python 单测（JWT 解析成功/无 token 降级/非法 token 降级/记忆 source 前缀）
- [ ] 🧪 前端 vitest（登录态/请求封装附加 header）

### 4.2 回归测试

- [ ] 🧪 `python -m pytest tests/ -q`：195 passed / 0 failed（基线无新增失败）
- [ ] 🧪 `mvn test` 通过
- [ ] 🧪 `npx vitest run` 通过（既有失败与本模块无关）

### 4.3 真实 E2E

- [ ] 🧪 注册→登录→拿 token→带 token 调 /ai→记忆 source=memory:<user_id>:
- [ ] 🧪 跨用户记忆隔离（A 的记忆 B 查不到）
- [ ] 🧪 无 token 匿名调用零回归

---

## 5. 文档验收

### 5.1 变更记录

- [ ] 📝 changelog.md 已更新（含三栈分区）
- [ ] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [ ] 📝 JWT 认证决策记录在 plan.md（§3）+ ADR

### 5.3 共享记忆

- [ ] 📝 memory/project-context.md 更新（module-032 行 + 技术决策）
- [ ] 📝 memory/agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST）
- [ ] 📝 memory/file-index.md 更新

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 14 | 0 | 0 | 0 |
| 接口验收 | 4 | 0 | 0 | 0 |
| 代码质量验收 | 8 | 0 | 0 | 0 |
| 测试验收 | 8 | 0 | 0 | 0 |
| 文档验收 | 6 | 0 | 0 | 0 |
| **合计** | **40** | **0** | **0** | **0** |

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-05
- 结论:
  - [ ] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 待执行

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
