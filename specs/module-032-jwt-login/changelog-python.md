# 变更日志 — Module-032: JWT 登录体系（Python AI 服务 / 功能 3）

> 本文件记录 Python AI 服务的变更；Java 后端见 `changelog-backend.md`，React 前端由该栈 Developer 维护。

## 变更概述

AI 服务从纯 IP 身份升级为「JWT user_id 优先，否则 client_ip」的双层身份解析（匿名零回归）：

1. 新增 `src/identity.py`：`parse_jwt`（HS256 + 共享 JWT_SECRET，`Authorization: Bearer <token>` → user_id，无/非法/过期返回 ""）与 `resolve_identity`（user_id 非空优先，否则 client_ip）。
2. 扩展现有 `rate_limit_middleware`：除注入 `request.state.client_ip` 外，再解析 JWT 注入 `request.state.user_id`。
3. `rag/memory.py` 记忆 source 前缀 `memory:<ip>:` → `memory:<identity>:`（identity = user_id 优先，否则 client_ip），`save/recall/_next_title` 参数由 `ip` 改为 `identity`。
4. `rag/engine.py`：`chat` / `_recall_memory` 参数 `client_ip` → `identity`；chat / stream / agent 端点经 `resolve_identity` 传入解析后的身份。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/src/identity.py` | 新增 | `parse_jwt`（HS256 JWT 解析）+ `resolve_identity`（user_id 优先，否则 client_ip） |
| `ai_service/src/config.py` | 修改 | 新增 `jwt_secret` 配置（环境变量 `PW_JWT_SECRET`，.env 本地值，不进仓库） |
| `ai_service/main.py` | 修改 | `rate_limit_middleware` 解析 JWT 注入 `request.state.user_id`；chat/chat_stream/chat_agent/chat_agent_langgraph 端点用 `resolve_identity` 传身份；memory_save/memory_recall 端点改用 `resolve_identity`；lifespan 增加 JWT_SECRET 缺失 fail-fast |
| `ai_service/rag/memory.py` | 修改 | source 前缀 `memory:<identity>:`；`_normalize_ip`→`_normalize_identity`（允许 user_id，拒绝 LIKE 元字符）；`save/recall/_next_title` 参数 `ip`→`identity` |
| `ai_service/rag/engine.py` | 修改 | `chat`/`_recall_memory` 参数 `client_ip`→`identity`，按身份召回记忆 |
| `ai_service/requirements.txt` | 修改 | 新增 `pyjwt>=2.8.0` |
| `ai_service/.env` | 修改 | 新增 `PW_JWT_SECRET`（本地随机值，.env 已 gitignore，不进仓库） |
| `ai_service/.env.example` | 修改 | 新增 `PW_JWT_SECRET=your_shared_jwt_secret` 占位（文档化所需环境变量，无真实密钥） |
| `ai_service/tests/test_identity.py` | 新增 | JWT 解析成功 / 无 token / 非法 / 过期降级、resolve_identity 优先级、中间件链路 identity 注入、memory source 前缀（identity 优先 user_id）、engine identity 透传 |
| `ai_service/tests/test_memory.py` | 修改 | 2 处 `rag_engine.chat(..., client_ip=...)` 改名为 `identity=...`（随 `chat` 参数重命名同步） |

## 关键设计说明

### 设计决策 1: 身份解析独立模块 `src/identity.py`
- 决策：`parse_jwt` 与 `resolve_identity` 放独立模块，不塞进 `main.py`。
- 原因：单测可轻量导入（不依赖 main 的重型依赖链）；中间件与端点共用一套解析逻辑，避免散落。

### 设计决策 2: 复用现有限流中间件注入 user_id（不新增独立中间件）
- 决策：扩展现有 `rate_limit_middleware`，在注入 `client_ip` 后追加 `request.state.user_id = parse_jwt(...)`。
- 原因：FastAPI 中间件是后进先出，现有中间件已承担「每请求注入 request.state」职责；合并可保证所有端点（含 `/ai/memory/*`）统一拿到 user_id。健康检查早退，不解析 JWT（零开销）。

### 设计决策 3: 记忆隔离键 = user_id 优先，否则 client_ip（匿名零回归）
- 决策：`resolve_identity` 返回 `user_id`（JWT.sub）非空即用之，否则 `client_ip`（中间件注入）。
- 原因：登录用户跨设备/跨会话记忆隔离（acceptance 1.3）；匿名访客降级 client_ip，与 module-023 行为一致（acceptance 1.4 零回归）。`rag/engine.py` 的 `chat`/`_recall_memory` 参数由 `client_ip` 重命名为 `identity`（语义已不再仅是 IP）。

### 设计决策 4: memory.py 安全模型从「IPv4 校验」升级为「LIKE 元字符拒绝 + 转义」
- 决策：`_normalize_ip`（仅放行 IPv4）→ `_normalize_identity`（放行任意非空且不含 `%`/`_`/`\` 的身份串）。
- 原因：user_id 不是 IPv4，旧校验会把它误降级为 `unknown` 导致身份隔离失效。user_id 由 JWT 服务端签发（可信），client_ip 由中间件提取（可信），两者都不会含 LIKE 元字符；仍保留 `_escape_like` 双保险（review #1 防注入逻辑不退化）。`memory:<identity>:` 尾冒号分隔符防前缀重叠泄漏的机制原样保留。

### 设计决策 5: 端点一律走 `resolve_identity`，body `ip` 仅作兜底
- 决策：`memory_save`/`memory_recall` 改用 `resolve_identity(fastapi_req)`（user_id 优先）；仅当身份为 `"unknown"` 且 body 传了 `ip` 时才回退用 body ip。
- 原因：满足「登录用户保存记忆 → source=`memory:<user_id>:`」验收；匿名时以中间件 server 派生的 client_ip 为准（更可信，body ip 客户端可控），并保留 module-023 显式传 ip 的兼容路径。

### 设计决策 6: JWT_SECRET 缺失 fail-fast（lifespan）
- 决策：lifespan 启动时 `jwt_secret` 为空即抛 `RuntimeError` 拒绝启动。
- 原因：plan §3.4 明确「JWT_SECRET 缺失 → 服务启动报错，不静默」。与 Java 端 fail-fast 对齐；单测经 ASGITransport 不触发 lifespan，无副作用。

### 跨栈契约说明（供 Reviewer/Java 对齐）
- JWT：HS256，payload `{sub=user_id, username, exp=7天}`，共享密钥与 Java `application.yml` 同值。Python 端因既有 `PW_` 配置前缀，.env 变量名为 **`PW_JWT_SECRET`**（等价于 Java 的 `APP_JWT_SECRET` 环境变量，均为 .env 本地配置、不进仓库）。
- 匿名降级：无/非法/过期 token → `request.state.user_id=""` → 端点用 `resolve_identity` 取 client_ip，记忆 source 仍为 `memory:<client_ip>:`（零回归）。
- agent 路径：`ReactContext` 的既有 `client_ip` 字段承载解析后的 identity 值（未改 agent 文件，值即身份）；tool_registry 的 `_recall_memory` 经它把身份透传 engine。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 全量回归 + 新增 | `cd ai_service && python -m pytest tests/ -q` | `215 passed`（基线 195 无回归 + 本模块新增 20） |
| 语法检查 | `cd ai_service && python -m py_compile main.py src/config.py src/identity.py rag/memory.py rag/engine.py` | 通过 |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始实现（identity 模块 + 中间件 JWT 解析 + memory/engine 身份化 + 单测） | Developer (python) |
