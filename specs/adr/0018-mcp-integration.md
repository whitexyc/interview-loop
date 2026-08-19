# ADR-0018：MCP 集成（ToolRegistry 暴露为标准 MCP Server）

## 元信息

- 状态：✅ **已实施 module-067**（2026-08-17；执行简报 `specs/module-067-mcp-integration/task-brief.md` + changelog.md）
- 日期：2026-08-17
- 关联：module-028（ToolRegistry）、agent/tool_registry.py（工具注册）、ai_service/main.py（FastAPI 入口）、ADR-0012（工具治理）、module-058（阶段切分）

## 背景：现状（代码实测）

1. **ToolRegistry 已是 MCP 雏形**：`AgentTool` 含 name / description / args_schema（JSON Schema）/ func / group；`to_llm_schemas(group=None)` 生成 LLM 可见函数定义；10 个工具（7 检索 + 3 生成/验证/笔记）
2. **服务入口**：FastAPI app（main.py:175），已有 /ai/health、/ai/rag/search、/ai/rag/chat 等端点
3. **缺的只是"标准协议包装层"**：工具定义与执行逻辑全在，暴露成 MCP server = 遍历 registry 动态注册 + 传输层适配

**为什么做**：2026 年 AI Agent 生态标配（Cursor / Claude Code / Copilot 全支持 MCP），AI 编程助手公司的核心工作就是"把工具接进 Agent"——岗位直击。MCP 解决 N×M 集成复杂度为 N+M。

## 业界方案（2026 调研）

| 要点 | 结论 |
|---|---|
| **SDK** | 官方 `pip install mcp`（MCP Python SDK），**FastMCP 高层 API**（装饰器注册、type hints 自动生成 schema、生命周期管理，省 ~60% 样板代码）；FastMCP v3 稳定，基于 MCP 协议 1.25 |
| **传输** | **stdio**（默认，本地 Claude Desktop/Cursor 启动子进程）；**Streamable HTTP**（远程，单端点 /mcp，替代已废弃的 SSE）；可挂载进现有 FastAPI（`mcp.streamable_http_app()` + Starlette Mount） |
| **认证** | HTTP 模式必须配认证（JWTAuthProvider / token），stdio 天然安全（本地进程） |
| **错误** | `ToolError` 显式抛出（不要裸 Exception，MCP client 能显示可读错误） |
| **坑** | ① 不要再写 SSE 传输（2025-03 规范已弃用）；② 工具必须 type hints + docstring（schema 由它们生成）；③ 日志走 stderr（stdio 模式 stdout 是协议通道） |

## 决策 1：用官方 FastMCP，动态遍历 ToolRegistry 注册

**不动 ToolRegistry 现有结构**，新增 `mcp_server.py`：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("personal-knowledge-kb", version="0.1.0")

def build_server(registry) -> FastMCP:
    for tool in registry.list_tools():           # 遍历 10 个工具
        # 用 tool.args_schema 动态构造参数（从 JSON Schema 生成 Pydantic model）
        # 用 tool.description 作为 docstring（MCP 用它生成工具描述给 LLM 看）
        mcp.tool(name=tool.name, description=tool.description)(make_fn(tool))
    return mcp
```

**关键**：ToolRegistry 保持单一事实源，MCP 层只是适配——改工具定义（description/args_schema）MCP 自动同步，不会双份维护。**复用 group 属性**：`build_server(registry, groups=["retrieval"])` 可只暴露检索组（默认全量 10 个）。

## 决策 2：双传输（stdio + Streamable HTTP 挂载 FastAPI）

| 模式 | 用途 | 实现 |
|---|---|---|
| **stdio**（默认） | 本地 Cursor / Claude Code / Claude Desktop 即插即用 | `python -m ai_service.mcp_server`（`mcp.run()`） |
| **Streamable HTTP** | 远程部署，挂载进现有 FastAPI | `app.mount("/ai/mcp", mcp.streamable_http_app(stateless_http=True, json_response=True))` |

**为什么挂载进现有 FastAPI 而不是独立服务**：复用同一端口/进程/配置（PW_ 环境变量、日志、数据库连接池），零新增部署；别人配置 URL 即可连。

## 决策 3：认证与安全（远程模式必须）

- 新增环境变量 **`PW_MCP_TOKEN`**：HTTP 模式启动时若未设置 → 拒绝启动（fail-closed，宁可不用不能裸奔）
- 请求校验：Authorization: Bearer <token>，无/错 token 返回 401
- **只暴露只读工具**（v0）：search_knowledge / search_fts / search_vector / search_graph / recall_memory / extract_entities——**不暴露 generate_answer / verify_answer / note_to_self / re_search**（generate 需要完整 ctx 上下文，不适合外部调用；写类/状态类工具对陌生 client 风险高）
- 工具返回**截断**（如检索结果前 2000 字符 + 提示"完整内容需更多上下文"），防大文档撑爆 client 上下文

## 决策 4：MCP 的边界（不做什么）

1. **不做客户端**：只做 server（做 client 是另一个项目，且 MCP client 生态已被 IDE 覆盖）
2. **不做工具治理迁移**：阶段切分（ADR-0012）是"本项目 ReAct 循环内"的机制，MCP client 自己管理工具暴露——但工具内部防御（"尚未检索"提示等）保留，外部调用同样受益
3. **不做评测集成**：MCP 调用不走 request_logs 的 RAG 链路（只暴露检索工具，不暴露完整 chat）——MCP 是"检索能力外挂"，不是"完整问答服务"（完整问答走现有 /ai/rag/chat）

## 诚实边界（面试防御）

1. MCP 是管道不是判断——它定义"怎么调"，不管"该不该调、结果对不对"；我的项目在管道之外补了工具治理 + HHEM 验证 + 审计，这是"懂 MCP 且超越 MCP"
2. v0 只暴露 6 个只读检索工具，generate/verify 不暴露——外部场景的完整问答不是 MCP 的职责
3. 本地 stdio 模式零认证（进程内），远程模式必须 token——安全边界写清楚，不假装安全

## 面试话术

> "我的 ToolRegistry（10 个工具，name + description + JSON Schema）本身就是 MCP 的雏形，集成就是加一层标准协议包装。用官方 FastMCP：遍历 registry 动态注册工具，description 变工具描述、args_schema 变参数 schema——ToolRegistry 保持单一事实源，改工具定义 MCP 自动同步。双传输：stdio 给本地 Cursor/Claude Code 即插即用，Streamable HTTP 挂载进现有 FastAPI（/ai/mcp，复用端口和配置）。安全上只暴露 6 个只读检索工具，远程必须 PW_MCP_TOKEN（fail-closed）。我理解 MCP 的边界：它是管道不是判断——所以工具阶段切分、HHEM 验证、审计这些 MCP 没管的三层我项目里都有，这是'懂 MCP 且超越 MCP'。"

## 验收标准

1. `pip install mcp` 后 `mcp_server.py` 启动，`uv run mcp dev`（Inspector）能看到 6 个工具并调用成功（本地 stdio）— ✅ 已实施：stdio python client 冒烟 6 工具 + search_knowledge 真实检索（DB 真实结果）；`mcp dev mcp_server.py` 可启动（Inspector GUI 沙箱不可开，已记录）
2. Streamable HTTP 挂载 /ai/mcp，无 token 401、有 token 200，工具调用返回截断结果 — ✅ 已实施：真实 uvicorn 冒烟无/错 token 401、正确 token initialize 200；截断 2000 单测 + stdio 冒烟生效（规范 URL 为 `/ai/mcp/`，无尾斜杠 307）
3. 工具描述/参数来自 ToolRegistry（改 description 后 MCP 自动同步，单测验证）— ✅ 单测 test_description_passthrough / schema 三变体
4. 存量 897 测试全绿 + 新增单测（注册遍历、schema 生成、token 校验、只读工具过滤）— ✅ 全量 pytest 1075 基线 + 27 新增全绿（scripts/test_models.py 1 项系 module-050 遗留 ERROR 未触碰；897 为 module-063 前旧快照，以 1075 实测为准）
5. 真实客户端连通性验证记录（Cursor 或 mcp 官方 inspector 截图/日志）— ✅ stdio client 冒烟输出记录于 changelog；HTTP 真实 curl 三态 + initialize 握手记录

**实施适配点（mcp 1.26.0 实测，勿照抄本 ADR 旧写法）**：stateless_http/json_response 是 FastMCP 构造参数（streamable_http_app() 零参）；1.26.0 构造无 version 参数；挂载场景 Starlette Mount 不转发 lifespan scope → 需手动进入 session 任务组（mcp_server.mcp_http_lifespan）；streamable_http_path 需设 "/"（默认 /mcp 挂载后为 /ai/mcp/mcp）；FastMCP 默认 DNS rebinding 保护仅放行 localhost Host（远程部署 421）→ 关闭（token 认证是安全边界）。详见 specs/module-067-mcp-integration/changelog.md
