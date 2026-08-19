# 验收标准 — Module-067: MCP 集成（ToolRegistry → 标准 MCP Server）

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Reviewer / Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。来源：task-brief 通过标准 + ADR-0018 验收标准 + plan.md。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-067 |
| 模块名称 | MCP 集成（ToolRegistry → 标准 MCP Server） |
| 关联 plan.md | `specs/module-067-mcp-integration/plan.md` |
| 验收日期 | 2026-08-17 |
| 验收人 | <Reviewer / Tester 签名> |
| 验收版本 | 0.67.0-module-067 |

---

## 1. 功能验收

### 1.1 核心功能验收（WP-A：mcp_server.py + 动态注册）

- [ ] 📋 **build_server 注册遍历**：`build_server(registry)` 遍历 `registry.list_tools()`，注册的工具名与 ToolRegistry 注册名完全一致（单一事实源）— 验证方式：单测断言注册工具名集合
- [ ] 📋 **默认只暴露 6 个只读工具**：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory 全部在列，且恰好 6 个 — 验证方式：单测断言 len==6 与集合相等
- [ ] 📋 **只读过滤（WP-C 核心）**：generate_answer / verify_answer / re_search / note_to_self **不在**默认注册列表（含 re_search——虽属检索组，但为显式白名单排除的对象）— 验证方式：单测断言 4 个名字不在列
- [ ] 📋 **description 透传**：MCP 工具描述来自 ToolRegistry 的 tool.description（改 description 后 MCP 自动同步）— 验证方式：单测修改 registry 中某工具 description → build_server 后描述跟随变化
- [ ] 📋 **args_schema → 参数模型转换**：JSON Schema 的 required / default / type 映射正确（string→str / integer→int / 未知类型→str 兜底；required 字段必填、default 生效；参数名与 properties 键一致）— 验证方式：单测覆盖 _SEARCH_SCHEMA / _ENTITY_SCHEMA / _MEMORY_SCHEMA 三变体
- [ ] 📋 **stdio 入口**：`mcp_server.py` 可独立启动（`mcp run ai_service/mcp_server.py` 或 `uv run mcp dev`），MCP 握手成功列出 6 工具 — 验证方式：真实 CLI 运行记录（Inspector 或 `mcp run` 输出）

### 1.2 核心功能验收（WP-B：Streamable HTTP 挂载 + token 认证）

- [ ] 📋 **/ai/mcp 挂载**：`app.mount("/ai/mcp", ...)` 挂载成功，服务启动后 MCP 端点可达（GET/POST 由 SDK 提供）— 验证方式：真实服务 curl /ai/mcp 返回非 404
- [ ] 📋 **无 token → 401**：请求无 `Authorization` 头返回 401 — 验证方式：单测（ASGITransport）+ 真实 curl
- [ ] 📋 **错 token → 401**：`Authorization: Bearer <错误值>` 返回 401 — 验证方式：单测 + 真实 curl
- [ ] 📋 **正确 token → 200**：`Authorization: Bearer <PW_MCP_TOKEN>` 请求通过，工具调用返回结果 — 验证方式：单测 + 真实 MCP client 连通记录
- [ ] 📋 **fail-closed（PW_MCP_TOKEN 未设置）**：token 为空时 lifespan 启动即抛错拒绝启动（服务起不来）— 验证方式：单测断言启动检查 raise；auth 中间件在 token 为空时恒 401（双保险单测）
- [ ] 📋 **真实 MCP client 连通**：官方 mcp CLI 或 Cursor 连接 stdio / HTTP 模式，能列出 6 工具并调用 search_knowledge 返回真实检索结果 — 验证方式：真实冒烟记录（截图/日志入 changelog）

### 1.3 边界条件验收

- [ ] 🔲 **工具返回截断**：检索结果超过 2000 字符截断 + 追加截断提示；≤2000 字符原样返回 — 验证方式：单测构造超长/短结果断言
- [ ] 🔲 **工具内部防御保留**：无检索结果时返回提示文案（如"（无检索结果）"），extract_entities 无实体返回提示 — 验证方式：单测 mock 底层返回空断言文案
- [ ] 🔲 **空参数 / 缺必填参数**：MCP 参数校验拒绝并返回可读错误（不 500、不裸异常）— 验证方式：单测调用缺 required 参数的工具
- [ ] 🔲 **top_k 类型错误**：传非整数 top_k 被参数校验拒绝（或按 schema 校验错误返回），不崩溃 — 验证方式：单测
- [ ] 🔲 **工具执行超时/失败降级**：工具执行失败返回可读提示文案而非裸 Exception（走 AgentTool.run 15s 超时 + 捕获语义）— 验证方式：单测 mock 工具抛异常/超时断言返回提示

### 1.4 异常场景验收

- [ ] ⚡ 底层检索/图谱服务失败：工具返回提示文案，MCP client 收到可读结果而非连接错误 — 验证方式：单测 mock 底层异常
- [ ] ⚡ token 配置变更（运行时）：auth 中间件每次请求读 settings.mcp_token（不缓存），改 token 后旧 token 立即 401 — 验证方式：单测改 settings 值断言

---

## 2. 安全验收（WP-C）

- [ ] 🔒 **只读原则**：MCP 暴露面 = 6 个只读检索工具，无任何写/状态类工具（generate_answer / verify_answer / re_search / note_to_self 零暴露）— 验证方式：单测 + 真实 CLI 工具列表核对
- [ ] 🔒 **fail-closed**：PW_MCP_TOKEN 未设置 → HTTP 模式拒绝启动（宁可不用不能裸奔）— 验证方式：见 1.2
- [ ] 🔒 **token 不落日志**：认证过程/错误日志不打印 token 值 — 验证方式：代码审查 + 日志抽查
- [ ] 🔒 **stdio 零认证边界如实声明**：stdio 为本地进程模式（零认证是设计），文档/README 写清安全边界，不假装安全 — 验证方式：文档核对
- [ ] 🔒 **日志走 stderr**：mcp_server.py 无 print 到 stdout（stdio 模式 stdout 是协议通道）— 验证方式：代码审查 grep print
- [ ] 🔒 **不写 SSE 传输**：只用 Streamable HTTP（2025-03 规范已弃用 SSE）— 验证方式：代码审查确认无 SSE 实现

---

## 3. 代码质量验收

- [ ] 💻 **单一事实源**：ToolRegistry 结构零改动（tool_registry.py 不在 git diff），MCP 层纯适配 — 验证方式：git diff 核对
- [ ] 💻 **红线遵守**：react.py / engine.py 一律不碰；main.py 仅加挂载 + 认证中间件 + import；config.py 仅加 mcp_token 字段；requirements.txt 仅加 mcp 一行 — 验证方式：git diff 核对
- [ ] 💻 **新增依赖仅 mcp**：官方 MCP Python SDK（`mcp==1.26.0`），不引第三方替代库 — 验证方式：requirements.txt diff
- [ ] 💻 **代码长度**：mcp_server.py 功能代码 ≤ 200 行（不含注释/docstring/测试）；认证中间件单函数 ≤ 50 行 — 验证方式：行数统计
- [ ] 💻 **命名规范**：符合项目 snake_case / 常量全大写风格；无未使用 import；无 print 残留 — 验证方式：代码审查
- [ ] 💻 **参数化防御**：token 校验用常量时间比较或等价方式（防时序侧信道，对齐安全惯例）— 验证方式：代码审查（如 `hmac.compare_digest`）

---

## 4. 测试验收

- [ ] 🧪 **新增单测覆盖**（tests/api/test_mcp_server.py，≥15 项）：build_server 注册遍历 / description 同步 / schema 三变体转换 / 只读过滤（4 个非只读工具不在列）/ ctx 合成（recall_memory 拿到 identity、search 系拿到 query）/ 截断 ≤2000 原样 + >2000 截断提示 / token 三态（无/错/对）/ fail-closed（lifespan raise + 中间件恒 401）/ 工具失败降级提示 / 空参数校验
- [ ] 🧪 **存量测试零改动**：全量 pytest = 1075 基线 + 新增全绿（897 是 module-063 前旧快照，不与 897 对齐）— 验证方式：全量 pytest 独立复跑
- [ ] 🧪 **真实冒烟**：stdio（`mcp run`/`mcp dev`）6 工具可见 + search_knowledge 真实检索返回截断结果；HTTP 无 token 401 / 有 token 200 + 真实 MCP client 连通记录 — 验证方式：见验证命令表

---

## 5. 文档验收

- [ ] 📝 changelog.md 已产出，如实记录（含版本 API 适配点、冒烟结果、诚实边界）
- [ ] 📝 README 环境变量表补 `PW_MCP_TOKEN`（含 fail-closed 说明）+ 功能段补 MCP 能力（6 只读工具 / stdio + Streamable HTTP / token 认证）
- [ ] 📝 CONTEXT.md 补 ADR-0018 行 + module-067 索引行（**只增不删，取更全侧，先备份**）
- [ ] 📝 ADR-0018 状态 → ✅ 已实施，验收标准逐条核对标注
- [ ] 📝 00-信息包"核心模块"可加 MCP 集成条目（面试口径，内容以 ADR-0018 面试话术为纲）
- [ ] 📝 memory 三文件更新（project-context module-067 行 + file-index + agent-activity-log）

---

## 6. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量回归 | `cd ai_service && python -m pytest -q` | `1075+N passed`（0 failed） |
| 新增单测 | `cd ai_service && python -m pytest tests/api/test_mcp_server.py -q` | 全部 passed |
| stdio 冒烟 | `cd ai_service && uv run mcp dev mcp_server.py`（或 `mcp run mcp_server.py`） | Inspector/CLI 列出 6 工具，search_knowledge 真实返回 |
| HTTP 无 token | `curl -i http://localhost:8001/ai/mcp`（或初始化 POST） | 401 |
| HTTP 有 token | `curl -i -H "Authorization: Bearer $env:PW_MCP_TOKEN" http://localhost:8001/ai/mcp` | 200 |
| fail-closed | 未设置 PW_MCP_TOKEN 启动服务 | 启动即抛 RuntimeError（拒绝启动） |
| 只读核对 | 真实 client tools/list | 恰好 6 工具，无 generate/verify/re_search/note_to_self |

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收（1.1-1.4） | | | | |
| 安全验收（2） | | | | |
| 代码质量验收（3） | | | | |
| 测试验收（4） | | | | |
| 文档验收（5） | | | | |
| **合计** | | | | |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| 1 | | | | |
| 2 | | | | |

### 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-08-17
- 结论:
  - [ ] ✅ **通过** — 所有检查项通过，模块可以标记为完成
  - [ ] ❌ **不通过** — 存在失败项，需要 Developer 修复后重新验收
  - [ ] ⚠️ **有条件通过** — 存在非阻塞性问题，记录技术债务后放行
- 备注: <说明>
