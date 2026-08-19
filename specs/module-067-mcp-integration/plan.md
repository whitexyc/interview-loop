# 开发计划 — Module-067: MCP 集成（ToolRegistry → 标准 MCP Server）

> Planner: 2026-08-17 | 依据：`specs/module-067-mcp-integration/task-brief.md` + ADR-0018（已立项）
> 范围：把 ToolRegistry 10 工具暴露为标准 MCP Server（stdio + Streamable HTTP 双传输，只读 6 工具 + token 认证）
> 预算：WP-A 1 天 + WP-B 半天 + WP-C 半天 + WP-D 半天 ≈ 2.5 天

## 0. Planner 已探明事实（勿重复调查）

1. **ToolRegistry**（`ai_service/agent/tool_registry.py`）：`AgentTool` = name / description / args_schema（JSON Schema，OpenAI parameters 格式）/ func（`async def (ctx, args) -> str`）/ group（`set[str]`，取值 "retrieval"/"generation"）；`list_tools()` / `list_tool_names()` / `to_llm_schemas(group=None)` 现成；10 工具已注册（模块级 `register_builtin_tools()` 直接注册到全局单例 `registry`，import 即就绪）。**工具执行统一走 `AgentTool.run(args, ctx)`**：内置 15s 超时 + 异常捕获返回提示文案（"（工具 X 执行超时）" / 空串）——MCP 适配层复用该语义即可，不要绕过 run 直接调 func。
2. **⚠️ 6 只读工具 ≠ group="retrieval" 过滤（对 task-brief 措辞的事实修正）**：检索组共 7 个（含 re_search 双组），按 group 过滤会**多暴露 re_search**（改写重检 + 累积 ctx.docs 的状态类工具）。task-brief 的"默认只暴露 6 个只读检索工具"必须用**显式 6 名白名单常量**（`READ_ONLY_TOOLS`），`build_server(registry, groups=None)` 语义定为：`groups=None` → 白名单过滤；`groups=["retrieval"]` 等显式传值 → 按 group 过滤（仅测试/扩展用）。
3. **main.py**：`app = FastAPI(...)`（L175，lifespan=L101）+ CORSMiddleware（L182）+ http 中间件 `rate_limit_middleware`（L192-232：限流/trace_id/JWT，除 /ai/health 全路径）。**现无任何 `app.mount`**——/ai/mcp 将是首个挂载点。文件尾部 `uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)`。
4. **config.py**（`ai_service/src/config.py`）：pydantic-settings `BaseSettings`，`model_config = {"env_prefix": "PW_", "env_file": ".env"}`，字段 snake_case → `PW_` 大写环境变量。新增 `mcp_token: str = ""`（→ `PW_MCP_TOKEN`）对齐既有模式；开关型字段带中文注释说明语义。
5. **依赖管理：`ai_service/requirements.txt` 为准**（`==` 锁定），**无 pyproject.toml / uv.lock**；uv 0.11.32 可用（工作流 `uv run` 用，uv 支持 requirements.txt-only 项目自动 sync 进 .venv）。**requirements.txt 无 mcp**——但当前环境（hermes venv，fastapi 0.133.1 所在）**已装 mcp 1.26.0**（环境与 requirements 漂移，同 module-028 langchain-openai 观察）。本模块需在 requirements.txt 补 **`mcp==1.26.0`**（锁对齐已装版本；`uv run mcp dev` 依赖它解析）。
6. **FastMCP API（mcp 1.26.0 实测签名，关键适配点）**：`from mcp.server.fastmcp import FastMCP` 可用；**`stateless_http` / `json_response` 是 FastMCP 构造函数参数**（`FastMCP(name, ..., stateless_http=True, json_response=True)`，另有 `streamable_http_path="/mcp"` 默认）；**`mcp.streamable_http_app()` 无参**返回 Starlette app——ADR/task-brief 的 `mcp.streamable_http_app(stateless_http=True, json_response=True)` 写法在本 SDK 版本需**适配为构造参数**（task-brief WP-B 已提示"按装的包适配"）。FastMCP 自带 `token_verifier`/`auth` 基建，但本项目选**自定义 ASGI 认证中间件**（~15 行，零 SDK 深度耦合、fail-closed 语义直白可单测）。
7. **mcp CLI**：控制台脚本 `mcp.exe` 可用（mcp.cli:app），子命令 `dev`（Inspector）/ `run` / `install` / `version`；**`python -m mcp` 不可用**（无 `__main__`）。Inspector 命令 `uv run mcp dev ai_service/mcp_server.py`。
8. **存量测试基线：1075/0**（module-066 验收口径 = 1037 基线 + 38 新增，Tester/Reviewer 双独立复跑一致）；本机实测 pytest 收集 **1076**（066 同款"验收口径 vs 收集数"轻微差异）。⚠️ task-brief 事实 5 写"897/0（47 文件）"系 module-063 前旧快照——**回归基线以当前全量实测为准（1075 基线 + 新增）**，不与 897 对齐。
9. **测试环境**（`ai_service/tests/conftest.py`）：autouse fixture 钉住多个生产开关（限流放行 / intent_classifier=false / reranker_quantize=false / tool_phase_split=false 等），存量测试全部 `import main`——**fail-closed 检查绝不能放模块导入期**（否则全量存量测试启动即炸）。fail-closed 放 **lifespan 启动检查**（存量测试多用 httpx ASGITransport 不触发 lifespan，零影响），auth 中间件运行时恒校验（token 为空也一律 401，双保险）。
10. **测试文件位**：端点级测试在 `ai_service/tests/api/`（test_main / test_feedback / test_verify_tasks / test_observability）→ 新文件 **`ai_service/tests/api/test_mcp_server.py`**。
11. **工具 ctx 依赖（MCP 适配层必须合成轻量 ctx）**：search 系（search_knowledge/fts/vector/graph）用 `ctx.query`（args 缺省）与 `ctx.add_docs(docs)`（累积，MCP 单次调用无后续消费者，可为 no-op）；`recall_memory` 用 `ctx.identity` 并写 `ctx.memory`；`extract_entities` 只用 args。MCP 层每调用构造一次性轻量 ctx（如 `types.SimpleNamespace(query=..., identity="mcp", docs=[], add_docs=lambda d: None, memory="")`），**不要**构造完整 ReactContext。
12. **环境坑**：Windows；deepseek 429 限流风暴时段降级链慢为外部抖动（如实记录不伪造）；`mcp dev` 需浏览器开 Inspector，本机沙箱可能打不开 GUI → 兜底 `mcp run`（stdio 直跑）+ 小型 python MCP client 脚本验证连通（记录输出）。

## 1. WP-A：mcp_server.py + 动态注册（1 天，核心）

- **目标**：新建 `ai_service/mcp_server.py`，用官方 FastMCP 把 ToolRegistry 6 个只读工具动态注册为标准 MCP server（stdio 默认传输）。
- **涉及文件**：
  - `ai_service/mcp_server.py`（新建，功能代码 ~120 行：build_server + schema 转换 + ctx 合成 + 截断 + stdio 入口）
- **实现要点**：
  - `READ_ONLY_TOOLS: set[str]` 常量 = {search_knowledge, search_fts, search_vector, search_graph, extract_entities, recall_memory}（6 个，见 §0.2——不按 group 过滤，显式白名单）
  - `build_server(registry, groups: Optional[list[str]] = None) -> FastMCP`：遍历 `registry.list_tools()`；`groups is None` → 只注册 `READ_ONLY_TOOLS` 内的工具；显式 groups → 按 `t.group & set(groups)` 过滤（测试/扩展用）
  - 每个工具注册：
    - name 直用 `tool.name`；`tool.description` 作 MCP 工具描述（改 ToolRegistry 描述 MCP 自动同步，单一事实源）
    - 参数模型：从 `tool.args_schema` 动态生成（`pydantic.create_model` 或 exec 动态构造带 type hints 的闭包函数）：`properties` 键 → 参数名；`type: "string"→str / "integer"→int / "number"→float / "boolean"→bool`，未知/缺失 → str 兜底；`required` 含的字段无默认值（必填），properties 带 `default` 的给默认值，其余可选——**生成的函数签名参数名必须与 args_schema properties 键一致**
    - 函数体：`return await tool.run(args, ctx)`（复用 AgentTool.run 的 15s 超时 + 异常降级语义，不直接调 func）；ctx 用 §0.11 轻量合成
  - 截断辅助 `_truncate_result(text, limit=2000) -> str`：超过 limit 截断 + 追加提示"…（结果已截断，完整内容需更多上下文）"；未超限原样返回
  - 模块级 `mcp = build_server(registry)`（import 即构建，供 main.py 挂载复用同一实例）
  - stdio 入口：`if __name__ == "__main__": mcp.run()`（FastMCP 默认 stdio 传输）
  - **日志走 logging（stderr），模块内禁 print**（stdio 模式 stdout 是协议通道）
  - 工具函数签名按 ADR-0018 坑 ② 尽量补 type hints（FastMCP 用它生成 schema；本项目 args_schema 已有，schema 转换兜底，签名以转换结果为准）
- **通过标准**：
  - 单测：`build_server` 注册恰好 6 工具（名称与 READ_ONLY_TOOLS 一致）、description 透传、schema 转换正确（required/default/type 映射）、截断逻辑、ctx 合成（recall_memory 拿得到 identity）
  - 冒烟：`uv run mcp dev ai_service/mcp_server.py`（Inspector）能看到 6 个工具，search_knowledge 调用返回真实检索结果（截断版）；Inspector GUI 不可用则 `mcp run` + python client 验证（§0.12 兜底）

## 2. WP-B：Streamable HTTP 挂载 FastAPI + token 认证（半天）

- **目标**：/ai/mcp 挂载进现有 FastAPI（复用端口/进程/配置），PW_MCP_TOKEN 认证，fail-closed。
- **涉及文件**：
  - `ai_service/main.py`（挂载 + 认证中间件 + lifespan fail-closed 检查，~30 行）
  - `ai_service/src/config.py`（+`mcp_token: str = ""`，PW_MCP_TOKEN）
  - `ai_service/requirements.txt`（+`mcp==1.26.0`）
  - `ai_service/tests/api/test_mcp_server.py`（token 校验/挂载测试）
- **实现要点**：
  - config.py：`mcp_token: str = ""`（注释写明 fail-closed 语义：HTTP 模式必须配置，缺省拒绝启动；stdio 模式零认证是设计——本地进程）
  - main.py 挂载（`from mcp_server import mcp` 复用 §1 实例）：
    ```python
    app.mount("/ai/mcp", _mcp_auth_middleware(mcp.streamable_http_app()))
    ```
    - **构造参数适配（§0.6 实测）**：stateless_http/json_response 在 FastMCP 构造时传——mcp_server.py 模块级实例构建即传 `FastMCP("personal-knowledge-kb", version="0.1.0", stateless_http=True, json_response=True)`（与 stdio 入口共用同一实例，参数不影响 stdio 模式）；`streamable_http_app()` 零参调用
    - `_mcp_auth_middleware`（ASGI 包装 ~15 行）：`Authorization` 头 != `f"Bearer {settings.mcp_token}"` → 401（JSON 响应）；`settings.mcp_token` 为空 → **恒 401**（双保险）
  - **fail-closed 放 lifespan**（§0.9：绝不能放 import 期）：lifespan 启动处 `if not settings.mcp_token: raise RuntimeError("PW_MCP_TOKEN 未设置：MCP HTTP 模式 fail-closed 拒绝启动（宁可不用不能裸奔）")`——对齐 module-053 fail-fast 先例（Literal 非法值启动即抛）。**存量测试用 ASGITransport 不触发 lifespan，零影响**；如有用 TestClient 的存量测试触发 lifespan，该测试体内显式设 settings.mcp_token（实测确认后处理）
  - 工具返回截断在 mcp_server 层统一生效（§1），HTTP 模式同样受益
  - requirements.txt 加 `mcp==1.26.0`（§0.5：uv run 解析依赖需要）
- **通过标准**：无 token 请求 401、错 token 401、正确 token 200（HTTP 状态码单测 + 真实 curl 冒烟）；真实 MCP client（`mcp` 官方 CLI 或 Cursor）连通性验证记录（截图/日志）；PW_MCP_TOKEN 未设置时 lifespan 启动即抛（单测断言）

## 3. WP-C：安全与边界（半天）

- **目标**：只读暴露 + 防御保留 + 边界声明，单测全覆盖。
- **涉及文件**：`ai_service/tests/api/test_mcp_server.py`（只读过滤 / token 校验 / 截断 / fail-closed 断言）
- **实现要点**：
  - 只暴露 6 个只读工具（WP-A 白名单已实现）：generate_answer / verify_answer / re_search / note_to_self **不注册**——单测断言 `list_tool_names` 过滤后不含这 4 个（含 re_search 虽属检索组——§0.2 正是显式白名单的意义）
  - 工具内部防御保留（如 search 无结果提示、extract_entities 无实体提示）——外部调用同样受益，适配层不剥除
  - 执行语义：走 `tool.run(args, ctx)`（15s 超时 + 失败返回提示文案，§0.1）——**不抛裸 Exception 给 MCP client**，异常在 run 内消化为可读文案（对齐项目降级哲学；不额外引 ToolError，除非 run 返回空串需要包装提示）
  - **明确不做**（ADR-0018 决策 4）：不实现 MCP client；不做工具治理迁移（阶段切分是本项目 ReAct 循环内机制，MCP client 自己管）；不做完整问答暴露（完整问答走 /ai/rag/chat）；不写 SSE 传输（2025-03 规范已弃用）
- **通过标准**：单测验证只读过滤（4 个非只读工具不在注册列表）、token 校验三态（无/错/对）、截断逻辑（≤2000 原样 / >2000 截断+提示）、fail-closed（token 空 → lifespan raise + 中间件恒 401）、ctx 合成字段、schema 转换三变体（_SEARCH_SCHEMA / _ENTITY_SCHEMA / _MEMORY_SCHEMA）

## 4. WP-D：回归 + 文档收口（半天）

- **目标**：全量绿 + 文档闭环（changelog / 三记忆 / README / CONTEXT.md / ADR-0018 状态 / 面试信息包）。
- **涉及文件**：
  - `ai_service/tests/api/test_mcp_server.py`（新增单测 ~15-20 项）
  - `specs/module-067-mcp-integration/changelog.md`（新增，Developer 产出）
  - `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`（三记忆更新）
  - `README.md`（环境变量表补 `PW_MCP_TOKEN` + 功能段补 MCP 能力：6 只读工具 / stdio + Streamable HTTP 双传输 / token 认证 / fail-closed）
  - `CONTEXT.md`（补 ADR-0018 行 + module-067 索引行——**只增不删，取更全侧，先备份**，项目红线）
  - `specs/adr/0018-mcp-integration.md`（状态 → ✅ 已实施，验收标准逐条核对标注）
  - 00-信息包（"核心模块"可加一条：MCP server 集成——6 只读工具 + 双传输 + token 认证；内容以 ADR-0018 面试话术为纲）
- **验证点**：
  - 全量 pytest = **1075 基线 + 新增全绿**（存量零改动；红线：tool_registry.py / react.py / engine.py 一律不碰，main.py 只加挂载+中间件+import，config.py 只加字段，requirements.txt 只加一行）
  - 真实冒烟：stdio `mcp dev`/`mcp run` 6 工具 + search_knowledge 真实检索（截断版）；HTTP 无 token 401 / 有 token 200 + 真实 MCP client 连通记录
  - 记忆硬核查：project-context 头部日期 + module-067 行 + activity [PLAN] 行 + file-index 行 + CONTEXT 只增
- **明确不做**：不写 SSE 传输；不引第三方 MCP 库；不做 MCP client；不做工具治理迁移。

## 5. 技术方案汇总

- **数据表**：无新增（MCP 纯适配层，不落库；request_logs/tool_call_logs 不接入——ADR-0018 决策 4③）
- **API 端点**：`/ai/mcp`（Streamable HTTP，MCP 协议端点 GET/POST 由 SDK 提供，`streamable_http_path="/mcp"` 默认与挂载路径一致）；无 REST 语义端点新增
- **外部依赖**：`mcp==1.26.0`（官方 MCP Python SDK，唯一新增；不引第三方替代库）
- **Agent 配置**：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1（无前端/Java 子任务）

## 6. 风险评估

- **FastMCP 版本 API 差异**（task-brief WP-B 已预警）：stateless_http/json_response 在 1.26.0 是构造参数——§0.6 已实测签名，按适配写法执行；换环境装到不同版本时以 `inspect.signature` 复核为准
- **fail-closed 误伤存量测试**：检查放 lifespan 不放 import 期（§0.9）；如存量有 TestClient 测试触发 lifespan，测试内显式设 settings.mcp_token（实测确认，预期 0 处）
- **JSON Schema → 参数模型转换边界**（required/default/未知 type）：未知 type 一律 str 兜底（现有 3 个 schema 只有 string/integer，实测无风险）；单测断言三变体
- **ctx 合成遗漏**（recall_memory 需要 identity、search 系需要 query）：§0.11 已列全 4 字段需求，单测覆盖
- **`mcp dev` Inspector GUI 本机不可开**（Windows 沙箱）：兜底 `mcp run`（stdio 直跑）+ python client 脚本验证连通，输出记录进 changelog；`python -m mcp` 不可用，统一用 `mcp`/`uv run mcp` 命令
- **deepseek 429 限流风暴**（历史观察）：真实检索冒烟慢为外部抖动，如实记录，可重跑
- **环境依赖漂移**（requirements 与已装不一致，module-028 观察同款）：装 mcp 以 `pip install mcp==1.26.0` 显式对齐；requirements.txt 同步

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始版本（WP-A~D 拆解 + 文件路径 + 通过标准 + 事实核实） | Planner |
