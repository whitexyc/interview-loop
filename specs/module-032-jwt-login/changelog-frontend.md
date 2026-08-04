# 变更日志 — Module-032: JWT 登录体系（React 前端 / 功能 2）

> 本文件记录 React 前端变更；Java 后端与 Python AI 服务各栈 Developer 各自维护其分区
> （见同目录 `changelog-backend.md`）。

## 变更概述

实现前端登录体系：新增登录/注册页（`LoginPage`）与登录态管理（`AuthContext`，token 存
localStorage、启动恢复、login/register/logout）；新增统一请求封装 `api/client.ts`，
登录后 /api 与 /ai 请求自动附加 `Authorization: Bearer <token>`（axios 走请求拦截器，
SSE fetch 走 `authHeader()`），供 Java 与 AI 服务识别用户身份。顶部导航（`AppLayout`）
新增登录入口 / 用户名·退出，未登录不强制（匿名访问零回归）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `frontend/src/api/client.ts` | 新增 | 统一请求封装：getToken/setToken/clearToken（localStorage）、authHeader、createHttp（拦截器自动附 Bearer 头）、apiHttp（/api, 10s）、aiHttp（/ai, 60s） |
| `frontend/src/auth/AuthContext.tsx` | 新增 | AuthProvider + useAuth：token/user 状态、启动恢复、login/register/logout；注册成功自动登录 |
| `frontend/src/pages/LoginPage.tsx` | 新增 | 登录/注册表单（antd Form + Segmented 切换），错误内联 Alert，成功跳转首页 |
| `frontend/src/components/AppLayout.tsx` | 修改 | 顶部右侧登录入口：未登录显示"登录"按钮，已登录显示用户名 + "退出" |
| `frontend/src/App.tsx` | 修改 | 挂载 AuthProvider；新增 `/login` 路由（独立页面） |
| `frontend/src/services/resumeService.ts` | 修改 | 改为复用 `apiHttp`（统一实例，自动带 token） |
| `frontend/src/services/conversationService.ts` | 修改 | 改为复用 `apiHttp` |
| `frontend/src/services/ragService.ts` | 修改 | axios 调用复用 `aiHttp`；SSE 流式（chatStream/agentStream）fetch 头加 `...authHeader()` |

**新增测试**：
- `frontend/src/__tests__/client.test.ts` — token 存取 / authHeader / createHttp 拦截器附加
- `frontend/src/__tests__/AuthContext.test.tsx` — 初始态 / 登录成功写 localStorage / 登录失败（HTTP 4xx 与 code=1 两形态）/ 注册自动登录 / 退出清空 / 启动恢复
- `frontend/src/__tests__/LoginPage.test.tsx` — 登录成功跳转、登录失败显示错误、注册成功跳转

## 关键设计说明

### 设计决策 1: 统一请求封装 + 双通道带 token
- 决策：`api/client.ts` 提供 `createHttp(baseURL, timeout)`，请求拦截器在每次请求前读
  `localStorage.getItem('auth_token')`，存在则写 `Authorization: Bearer <token>`。预置
  `apiHttp`（/api→8080, 10s）与 `aiHttp`（/ai→8000, 60s），三个 service 全部改为复用。
  对不走 axios 的 SSE fetch（`chatStream`/`agentStream`）用 `authHeader()` 手动并入 header。
- 原因：plan §6.2 要求"避免散落的 fetch 漏带 token"。fetch 无法挂 axios 拦截器，故提供
  `authHeader()` 作为补充通道；两处 SSE 各加一行，满足跨栈契约"所有 /ai 请求带 Bearer 头"。

### 设计决策 2: token 与 user 双持久化，惰性初始化恢复
- 决策：token 存 `localStorage['auth_token']`，user（{username, user_id}）存
  `localStorage['auth_user']`（JSON）。AuthContext 用 `useState(() => getToken())` 与
  `useState(() => readStoredUser())` 惰性初始化，挂载即恢复，无需额外 effect。
- 原因：验收 1.2"刷新后仍登录"要求能显示用户名，故 user 也需持久化；惰性初始化比
  `useEffect` 更少一次渲染抖动，且登录/登出路径都是自闭环（setToken 与 localStorage 同步）。

### 设计决策 3: 注册即登录（注册接口不返回 token）
- 决策：`register()` 先调 `/auth/register`（成功只返回 user_id），成功后自动调
  `login()` 拿 token，形成"注册即登录"。
- 原因：跨栈契约中 register 不返回 token（`{code:0, data:{user_id}}`），若注册后要求用户
  再手动登录体验割裂；自动登录与验收 1.2"表单提交并跳转"一致。

### 设计决策 4: 失败处理兼容两种形态（重要契约对齐）
- 决策：`postAuth` 把认证接口失败统一转成带 message 的 Error，兼容：
  1) HTTP 200 但 `body.code=1`（plan §3.5 原始契约 `{code:1, message}`）；
  2) HTTP 4xx AxiosError（后端 `BusinessException` 统一 400，body=`{code:1, msg}`，
     见 `changelog-backend.md` 契约解释）。
  错误字段优先 `message`、回退 `msg`，与后端实际序列化的 `CommonResult.msg` 对齐。
- 原因：axios 对 4xx 默认 reject，若不 catch `err.response.data`，登录失败会显示 axios
  默认错误而非后端"用户名或密码错误"。此设计保证 HTTP 200 / 4xx 两种后端行为下前端都能
  展示正确错误信息。

### 设计决策 5: 登录不 gate 公开内容
- 决策：AppLayout 未登录时仅显示"登录"入口，路由不设守卫，聊天/简历/知识库匿名可用。
- 原因：plan §3.3"登录仅为记忆隔离，前端不强制登录"，匿名访问零回归。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 构建（tsc + vite） | `cd frontend && npm run build` | `✓ built`（tsc 无类型错误） |
| 本模块单测 | `npx vitest run src/__tests__/client.test.ts src/__tests__/AuthContext.test.tsx src/__tests__/LoginPage.test.tsx` | 3 files / 17 passed |
| 全量回归 | `npx vitest run` | 31 passed / 3 failed（均为既有 ChatPage 失败，已用 `git stash` 基线验证与本模块无关：ChatPage.test 挂载时未 mock conversationService，axios 在 jsdom 请求失败导致 `activeConversationId=null`，`doSend` 提前 return） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始实现（client.ts + AuthContext + LoginPage + AppLayout 登录入口 + service 统一实例 + 测试） | Developer (frontend) |
