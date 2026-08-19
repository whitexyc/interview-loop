# Module-067 Task Brief：MCP 集成（ToolRegistry → 标准 MCP Server）

> 自包含执行简报（ADR-0018 落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。

## 事实（代码实测，2026-08-17）

1. `ToolRegistry`（tool_registry.py）：`AgentTool` 含 name / description / args_schema(JSON Schema) / func / group；`list_tools()` / `to_llm_schemas(group=None)` 现成；10 个工具已注册（7 检索组 + 3 生成/验证/笔记组）
2. FastAPI app（main.py:175），已有 /ai/health、/ai/rag/search、/ai/rag/chat 等端点；配置统一读 `src/config.py`（PW_ 环境变量模式）
3. 10 个工具名：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory（检索组）+ generate_answer / verify_answer / re_search / note_to_self（生成/双组）
4. 依赖未装 `mcp`——需要新增（官方 SDK，`pip install mcp`，FastMCP v3 基于 MCP 协议 1.25）
5. 存量测试 897/0（47 个测试文件），全量回归基线

## WP-A：mcp_server.py + 动态注册（1 天，核心）

- 新建 `ai_service/mcp_server.py`，用官方 FastMCP：
  - `build_server(registry, groups=None) -> FastMCP`：遍历 `registry.list_tools()`，按 group 过滤（默认**只暴露 6 个只读检索工具**：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory）
  - 每个工具：name 直用、description 作工具描述、args_schema 动态生成参数模型（JSON Schema → Pydantic，注意处理 required/default/type 映射，type hints 缺失时用 schema 兜底）
  - **不动 ToolRegistry 现有结构**——MCP 层只是适配，单一事实源不变
  - 日志走 stderr（stdio 模式 stdout 是协议通道，禁 print）
- stdio 入口：`if __name__ == "__main__": mcp.run()`（本地 Cursor/Claude Code/Claude Desktop 配置 `"command": "python", "args": ["-m", "ai_service.mcp_server"]`）
- **通过标准**：`uv run mcp dev ai_service/mcp_server.py`（Inspector）能看到 6 个工具，search_knowledge 调用返回真实检索结果（截断版）

## WP-B：Streamable HTTP 挂载 FastAPI + token 认证（半天）

- main.py 挂载：`app.mount("/ai/mcp", mcp.streamable_http_app(stateless_http=True, json_response=True))`（注意 FastMCP 版本传输参数名——in-SDK 版 `transport="streamable-http"`，独立包版 `transport="http"`，按装的包适配）
- 认证：新增 `PW_MCP_TOKEN`（config.py + 环境变量表）；**未设置 → HTTP 模式拒绝启动（fail-closed）**；请求校验 `Authorization: Bearer <token>`，无/错 401
- 工具返回**截断**：检索结果 result_preview 前 2000 字符 + 提示（防大文档撑爆 client 上下文）
- **通过标准**：无 token 请求 401、有 token 200；真实 MCP client（`mcp` 官方 CLI 或 Cursor）连通性验证记录

## WP-C：安全与边界

- 只暴露 6 个只读工具（WP-A 已实现）——generate_answer / verify_answer / re_search / note_to_self **不暴露**（写/状态类工具对陌生 client 风险高；generate 需完整 ctx 上下文不适合外部调用）
- 工具内部防御保留（如"尚未检索到文档"提示）——外部调用同样受益
- **不实现 MCP client**、**不做工具治理迁移**（阶段切分是本项目 ReAct 循环内机制，MCP client 自己管）、**不做完整问答暴露**（MCP 是检索能力外挂，完整问答走 /ai/rag/chat）
- **通过标准**：单测验证只读过滤（generate 等工具不在注册列表）、token 校验、截断逻辑

## WP-D：回归 + 文档收口

- 存量 897 全绿 + 新增单测（build_server 注册遍历 / schema 生成 / 只读过滤 / token 校验 / 截断）
- 更新 README（环境变量表补 `PW_MCP_TOKEN` + 功能段补 MCP 能力）+ CONTEXT.md（ADR-0018 + module-066 索引行）+ ADR-0018 状态标已实施
- 面试口径补充（00-信息包"核心模块"可加一条：MCP server 集成，6 只读工具 + 双传输 + token 认证）

## 纪律项

1. 只动新增文件（mcp_server.py）+ main.py 挂载 + config.py 加开关——**tool_registry.py / react.py / engine.py 一律不碰**
2. 依赖新增仅 `mcp`（官方 SDK），不引其他 MCP 框架（不用第三方的 mcp 替代库）
3. 不要写 SSE 传输（2025-03 规范已弃用），用 Streamable HTTP
4. 工具 type hints 与 docstring 尽量补全（FastMCP 用它们生成 schema/描述；现有工具 description 已有，参数 schema 走动态转换）
5. 远程安全性 fail-closed：PW_MCP_TOKEN 缺失即拒绝启动 HTTP 模式，宁可不用不能裸奔
