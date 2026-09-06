# 开发计划 — Module-084: 外部 MCP 客户端接入（MCP client 发现外部工具并注册进 ToolRegistry，受 module-083 工具治理约束）

> Planner: 2026-09-01 | 依据：`AGENT-GROWTH-ROADMAP.md` module-084 行（阶段 A：工具治理与外部接入——"外部 MCP 客户端接入：作为 MCP client 连接 1 个真实外部 MCP server，发现工具并注册进 ToolRegistry，复用既有工具白名单"）+ module-083 复盘确认（综合评审与任务简报均明确：`approval="required"` 与 `allowed_tools` 第三权限层是**专门为外部工具预留**的治理挂点）
> 范围：外部 MCP **客户端（出向）** 接入——stdio 本地子进程传输（v1）+ 服务启动时连接/发现/注册 + 全部外部工具 `approval="required"` + 配置显式授权白名单；Streamable HTTP client **明确不做**（留后续）
> 预算：WP-A 2h + WP-B 1 天 + WP-C 1h + WP-D 0.5 天 + WP-E 1h + WP-F 2h + WP-G 0.5 天 ≈ 2.5 天
> Agent 配置：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1（无前端/Java 子任务）

## 0. Planner 已探明事实（勿重复调查）

- **mcp==1.26.0 已在 requirements.txt:44**（module-067/ADR-0018 server 端 FastMCP 用同一官方 SDK）。官方 SDK 同时提供 client 端：`from mcp.client.stdio import stdio_client` / `from mcp import ClientSession`——**本环境 venv 实测 import 通过，版本 1.26.0，`stdio_client(server: StdioServerParameters, errlog=...)` 签名可用**。→ 零新依赖成立。
- **注册入口**：`ToolRegistry.register(name, description, args_schema, func, group, timeout, approval)`（tool_registry.py:304）→ `AgentTool`（L146，`func` 契约 `async def func(ctx, args) -> str`）。MCP 工具 `inputSchema` 就是 JSON Schema 格式，可直接作 `args_schema`（083 WP-A jsonschema 校验天然复用，无需改写）。
- **治理五闸落点（module-083，已闭环 @ a6c67ff）**：
  - 审批闸在 `AgentTool.run._precheck` 第一步：`approval=="required"` 且无 approved → 插 pending 行 `approval_requests` + 返回 `"(工具 X 需人工审批，调用申请已提交)"`（DB 异常 fail-closed 拒绝）；端点复用 `GET/POST /ai/tools/approvals`（main.py:1218/1240，**外部工具审批工作流零新增**）。
  - 白名单闸在 `execute_tool_with_log` 执行层：`allowed_tools is not None and name not in allowed_tools` → 拒绝 + `result_ok=false`（react.py:359-361）。
  - 幂等仅作用于 `_IDEMPOTENT_TOOLS` 硬编码 7 只读工具（tool_registry.py:84）——**外部工具天然不在清单 → 不触发同参拦截**（治理 = 审批 + 白名单，无需再拦，零改动）。
  - 超时 = `asyncio.wait_for(func, timeout=self.timeout)`（默认 `settings.tool_default_timeout=15.0`），外部工具自动继承围栏。
- **阶段分组语义（关键定案依据）**：`schemas_for_phase` → `to_llm_schemas(group)` 过滤规则 `not t.group or group in t.group`（tool_registry.py:335-349）。若外部工具注册 `group=["external"]`，在 `tool_phase_split=true` 下 retrieval/generation 两阶段 schema 均不可见 + `_phase_allows` 执行层拒绝 → **外部工具完全不可用**。→ **定案：外部工具注册 `group=None`（未分组）**：schema 全阶段可见（与内置工具同口径，"schema 是门禁、执行层是守门"），可见性交给审批 + 白名单两闸。
- **073 自动重试冲突**：`AgentTool._execute` 对异常自动重试 1 次（排除清单 `_NO_RETRY_TOOLS` 是固定名集合）。外部工具可能副作用（如写文件）→ 失败自动重放会**重复副作用**。→ 需 per-tool `no_retry` 属性（默认 False，内置 10 工具 073 语义逐字不变），不可塞 `_NO_RETRY_TOOLS`（动态名集合放不进固定集合）。
- **生产调用面（两条 ReAct 循环都要显式接白名单）**：
  - `/ai/rag/chat/agent` → `react_loop(ctx, _build_messages(ctx), budget, max_answer_len=...)`（main.py:738，当前不传 allowed_tools）；
  - `/ai/rag/chat/agent-lg` → `langgraph_react_loop(...)`（main.py:812）→ 内部 `execute_tools` 调 `execute_tool_with_log(name, args, tool, ctx)`（langgraph_react.py:169，不传 allowed_tools → None → 全量放行）。**若只接手写端点，agent-lg 将成为白名单层的绕过口**（审批闸仍在 run 内通用，但"显式授权白名单"失效）→ langgraph 端点必须同接。
- **同名覆盖风险（防 028~083 存量破坏）**：`register()` 同名覆盖（tool_registry.py:312 注释"同名覆盖，便于测试替换"）——外部工具名若与内置 10 工具重名会**覆盖内置工具**。→ 注册前冲突检测：重名跳过 + warning。
- **lifespan**（main.py:140-177）：`mcp_http_ctx` 进入前有 scheduler / feedback_scanner；外部 MCP 连接挂 lifespan（startup 连接发现注册 / shutdown close），fail-open 不阻塞启动。main.py import 惯例：`from agent.tool_registry import registry` 可直接引入。
- **config 先例**：pydantic-settings `model_config env_prefix="PW_"`；已有 Literal 枚举先例（memory_type_mode 等）；**list[str] 配置无先例需新增**（PW_ 下 env 传 JSON 数组字符串，如 `'["python","scripts/mcp_sample_server.py"]'`）。
- **conftest**（tests/conftest.py）：多个 autouse fixture 钉配置钉测试环境（tool_phase_split=false / max_agent_tools=4 / tool_auto_retry=false / tool_call_logs_enabled=false）→ 新增 `mcp_external_enabled=False` autouse 钉住（新开关必须先钉 false 再在用例内显式开启，hermetic 惯例）。
- **基线**：本模块前全量 **1485 passed / 4 failed（module-028 langchain-openai proxies 环境性基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）**——红线：**新增 0 失败、存量测试零改动**。
- **零新建**：无新表（复用 `approval_requests`）、无新端点（复用审批两端点）、requirements.txt 零改动（mcp 已在）。

## 1. 技术选型（Planner 已裁定，Developer 不复议）

### 1.1 传输：stdio 本地子进程（v1）；Streamable HTTP client 明确不做（留后续）
- 理由：stdio 零网络面、零新鉴权/DNS-rebinding 决策、本地可复现可 hermetic 测试；`mcp.client.stdio` 实测可用；验收"1 个真实外部 MCP server（本机可跑）"= 子进程启动一个自写最小 server 即真实达标（真实 stdio 握手 + 真实 list_tools + 真实 call_tool）。
- HTTP client（连远程 server）需 URL/认证/超时/网络故障面等一组新决策，与 067 server 端 HTTP 对称补齐时再立项，不在本模块。

### 1.2 外部工具来源：自写最小 MCP server（`scripts/mcp_sample_server.py`，验收样例/fixture）
- FastMCP（复用 mcp==1.26.0）注册 2 个真实工具：
  - `ext_current_time`（只读：返回当前 UTC 时间字符串，演示读取类工具）；
  - `ext_append_log`（副作用：向本地文件 `mcp_sample_out.log` 追加一行参数内容，演示审批治理价值）。
- 经 `stdio_client(StdioServerParameters(command=["python", "scripts/mcp_sample_server.py"], ...))` 子进程运行；**生产使用方把 `PW_MCP_EXTERNAL_COMMAND` 指向任意真实 server（如官方 filesystem server）即可，client 与 server 内容无关**。
- 拒绝备选：连 `@modelcontextprotocol/server-filesystem`（需 npm install，违反"零新依赖"且本机验收不可复现）；连自家中台 mcp_server.py（module-067 入向 server，与自己 client 对接是闭环演示不算"外部"）。均否决。

### 1.3 注册时机：服务启动（lifespan）一次性连接 + 发现 + 注册；会话保持至关闭
- startup：`await mcp_client.init_ext(registry)`——门控（enabled + command 非空）→ spawn 子进程 + ClientSession → `list_tools()` → 逐工具冲突检测 → `register(name, description, inputSchema 清洗后, func 闭包, group=None, approval="required", no_retry=True)` → 返回注册数。
- 会话句柄存模块级单例（对外暴露 `mcp_client.external`），工具 func 闭包经其 `call_tool` 执行；shutdown：`await mcp_client.close()`（关 session + stdio）。
- **fail-open**：enabled=false / command 空 / spawn 失败 / 握手超时（`mcp_external_timeout=10.0s`）→ `logger.warning` + 跳过注册，服务照常启动，内置 10 工具零影响。

### 1.4 安全默认（083 机制落地为"外部工具必须显式授权才能用"）
- **审批**：全部外部工具 `approval="required"`（硬编码，不走配置——外部工具 = 可能有副作用，宁可多审不少审）。审批工作流复用 083：首个 LLM 提议调用 → pending 行 → `GET /ai/tools/approvals` 查看 → `POST approve` → 工具级放行。
- **显式授权白名单**：config `mcp_external_tools: list[str]`（`PW_MCP_EXTERNAL_TOOLS`）——仅列入名的外部工具进入 `allowed_tools` 组装。语义矩阵：
  - 外部未启用 → `allowed_tools=None`（存量零变化）；
  - 外部启用（白名单空与否）→ `allowed_tools = set(内置 10 名) ∪ (已注册外部 ∩ 白名单)`——**白名单空 = 只放内置，外部全拒**（此分支绝不可返回 None，否则 None=全量放行会放行外部工具）。
  - 未授权外部工具：schema 可见 → LLM 提议 → 执行层拒绝（"不在当前 Agent 权限白名单"）+ 不提交审批申请；已授权未审批：run 审批闸提交 pending。
- **同名冲突**：注册前 `name in registry.list_tool_names()`（内置名集合）→ 跳过 + warning，防覆盖内置工具。
- **幂等**：外部工具不在 `_IDEMPOTENT_TOOLS` → 不拦截（治理 = 审批 + 白名单）。
- **重试**：外部工具 `no_retry=True`（副作用不可自动重放）。
- **deep-dive 无害性**：外部工具结果喂回 LLM 的消息历史（tool 结果消息）+ tool_call_logs 落库（066 自动继承）+ 预算计数（每次提议调用计 1 次，083 语义不变）。

## 2. WP-A：工具注册面扩展（tool_registry.py，~7 功能行）

- `AgentTool.__init__` 加 `no_retry: bool = False` → `self.no_retry`（docstring 注明：module-084 外部副作用工具的 073 排除，默认 False 内置零变化）。
- `_execute` 重试条件 `if settings.tool_auto_retry and self.name not in _NO_RETRY_TOOLS` → 追加 `and not self.no_retry`。
- `register()` 透传 `no_retry=False` 缺省。
- **通过标准**：单测——`AgentTool(no_retry=False)` 异常仍自动重试（073 存量语义）/ `no_retry=True` 异常只执行 1 次不重试 / 存量 test_tool_retry_dedup.py 全绿（默认 False）。

## 3. WP-B：MCP client 接入核心（新增 `agent/mcp_client.py`，~95 功能行）

模块结构（模块级单例 + 纯辅助，测试 monkeypatch 友好；不 import main，仅依赖 registry/config）：

- `async def init_ext(reg: ToolRegistry) -> int`：门控（`settings.mcp_external_enabled` 且 command 非空，否则 return 0 零开销）→ `stdio_client(StdioServerParameters(command=settings.mcp_external_command, cwd=ai_service 目录))` + `ClientSession` + `initialize()`（包 `asyncio.wait_for(mcp_external_timeout)`）→ `list_tools()` → 逐工具：冲突检测（跳过内置重名）→ 构造 func 闭包 → `reg.register(name, desc, inputSchema, func, group=None, approval="required", no_retry=True)` → 记录 `registered` 集合 → 返回注册数。**任何异常 → warning + return 0（fail-open，不 re-raise）**。
- `async def _ext_call(name, args) -> str`：`session.call_tool(name, arguments=args)`；结果处理——`CallToolResult.isError` → 可读失败文本；`structuredContent` 非空优先 JSON 序列化；否则 `content` 文本块（TextContent.text）逐块拼接；统一 `_TRUNCATE(2000)` 截断（对齐 067 思路，防大 payload 撑爆 LLM 上下文）。**任何异常/会话中断 → 返回可读提示文本（"（外部工具 X 调用失败…）"），不抛裸异常**（run 内失败返回空串、LLM 判断语义兼容）。
- `async def close() -> None`：关闭 session + stdio（幂等，未初始化直接返回）。
- `def agent_allowed_tools() -> Optional[set[str]]`：按 §1.4 语义矩阵组装（external 未启用 → None；启用 → 内置名 ∪ 授权∩已注册）。
- **注意（1.26.0 实测确认）**：`list_tools()` 返回 `ListToolsResult.tools`（`Tool.name/description/inputSchema`）；`call_tool` 返回 `CallToolResult`（content/structuredContent/isError）——字段名以落地时实测为准，勿照抄旧文档。
- **单测通过标准**：见 WP-G（含真实子进程握手用例）。

## 4. WP-C：配置（src/config.py，~10 功能行）

- `mcp_external_enabled: bool = False`（`PW_MCP_EXTERNAL_ENABLED`；默认 false = 零影响，fail-open 总开关）。
- `mcp_external_command: list[str] = []`（`PW_MCP_EXTERNAL_COMMAND`；stdio 子进程命令 JSON 数组，如 `["python","scripts/mcp_sample_server.py"]`）。
- `mcp_external_tools: list[str] = []`（`PW_MCP_EXTERNAL_TOOLS`；显式授权白名单，空 = 即使注册也不放行）。
- `mcp_external_timeout: float = 10.0`（`PW_MCP_EXTERNAL_TIMEOUT`；连接/握手/发现超时，执行期超时仍由 `AgentTool.timeout`=15.0 围栏）。
- 注释写清默认全关 = 存量零变化。

## 5. WP-D：lifespan + 两端点接线（main.py，~22 功能行）

- lifespan：`mcp_http_ctx.__aenter__()` 之前加 `await mcp_client.init_ext(registry)`（`from agent import mcp_client` + `from agent.tool_registry import registry`）；finally 里加 `await mcp_client.close()`（在 `mcp_http_ctx.__aexit__` 前/后均可，先 exit 后 close 防止工具在用）。fail-open 语义天然成立（init_ext 内部捕获）。
- 两个 agent 端点（/ai/rag/chat/agent L738、/ai/rag/chat/agent-lg L812）：循环调用处传 `allowed_tools=mcp_client.agent_allowed_tools()`（在 event_stream 内计算一次）。
- **通过标准**：单测——init_ext 被 lifespan 调用（monkeypatch 计数）/ spawn 失败服务启动不崩；react 端点带白名单执行层拒绝外部工具；langgraph 端点同拒。

## 6. WP-E：langgraph_react.py allowed_tools 透传（~6 功能行，消除绕过口）

- `ReActGraphState` TypedDict 加 `"allowed_tools": Optional[set[str]]`；
- `langgraph_react_loop` 加 `allowed_tools: Optional[set[str]] = None` 参数 → `initial_state["allowed_tools"]=allowed_tools`；
- `execute_tools` 节点读 `state["allowed_tools"]` 传给 `execute_tool_with_log(name, args, tool, ctx, allowed_tools=...)`。
- None = 全量 → 未配置外部工具时存量行为逐字不变（083 AC-33 语义保持：该文件被改但与 083 无关，属 084 显式授权闭环必需）。

## 7. WP-F：样例外部 MCP server（新增 `scripts/mcp_sample_server.py`，验收 fixture，~55 行）

- 复用 mcp_server.py 写法：`FastMCP("mcp-sample-server")` + `@mcp.tool()` 两个工具（`ext_current_time` 只读 / `ext_append_log` 写 `mcp_sample_out.log`，参数 JSON Schema 从 type hints 生成）+ `mcp.run()`（stdio）。
- 说明：属验收样例/可执行 fixture（非 Agent 核心生产链路），独立列示不混入核心行数口径；若协调者按铁律 2 从严全计入，则总口径见 §8 对照表仍 ≤200。

## 8. WP-G：测试 + conftest + 回归（新增 `ai_service/tests/agent/test_mcp_client.py`，预计 ~26 项）

- conftest autouse 新增 `mcp_external_disabled` fixture（钉 `mcp_external_enabled=False` + command/tools 清空），用例内显式 setattr 开启。
- 用例矩阵：WP-A 3（no_retry 默认/生效/存量 073 语义）/ WP-B 10（禁用不 spawn / 发现注册 2 工具含 approval/group/no_retry 断言 / 冲突名跳过 / ext_call 文本提取 / structuredContent 优先 / 截断 / CallToolResult.isError 提示 / 异常提示不抛 / agent_allowed_tools 三态）/ WP-C 3（4 配置默认值 + PW_ 映射）/ WP-D 3（lifespan 挂接 + 两端点白名单拒绝）/ WP-E 2（langgraph 透传生效）/ WP-F 2（样例 server 可 import + **真实子进程握手**：`stdio_client` 起 `scripts/mcp_sample_server.py` → list_tools 返回 2 实名工具 → call_tool ext_current_time 返回真实结果）/ 审批集成 3（已授权未审批 → pending 提交 + 拦截提示；approve 后放行真执行；未授权 → 白名单拒绝且不提交）。
- **红线**：全量 1485/4 基线新增 0 失败；存量测试零改动（mcp_server.py / react.py / database.py / router.py / engine.py 零 diff）；TOCTOU 无（无新表无新端点无新依赖）。

### 行数对照（铁律 2 生产 ≤200，module-075/080 确立的 AST 可执行行口径）

| WP | 文件 | 预估功能行 |
|----|------|-----------|
| WP-A | agent/tool_registry.py（改） | ~7 |
| WP-B | agent/mcp_client.py（新） | ~95 |
| WP-C | src/config.py（改） | ~10 |
| WP-D | main.py（改） | ~22 |
| WP-E | agent/langgraph_react.py（改） | ~6 |
| 合计（核心生产） | | ~140 |
| WP-F | scripts/mcp_sample_server.py（新，验收样例） | ~55 raw / ~40 AST |
| 严格口径合计（含样例） | | ~180 ≤ 200 ✓ |

含注释/docstring 后全行口径预计 ~300 上下；若 AST 口径超 200，Developer 按 module-080 先例晒实际行数对照表 + 申请 `GATE_MAX_MODULE_LINES` 放宽，Reviewer/Tester 复核。**测试代码不计入生产行数**。

## 9. 技术方案汇总

- **数据表**：0 新增（复用 `approval_requests`）。
- **API 端点**：0 新增（复用 `GET/POST /ai/tools/approvals`；不新增工具列表端点——registry 形态单测 + SSE tool_call 事件足够验收）。
- **外部依赖**：0 新增（复用 mcp==1.26.0 的 client 端）。
- **配置项**：新增 4 个，默认全关（`mcp_external_enabled=false` / `mcp_external_command=[]` / `mcp_external_tools=[]` / `mcp_external_timeout=10.0`）。
- **执行层守门总序（外部工具）**：`execute_tool_with_log` 二维守门（阶段 + allowed_tools 显式授权，两端点均接）→ `run._precheck`（审批闸：required 无 approved → 提交 pending 拦截）→ schema 校验（inputSchema 即 args_schema）→ 幂等（外部不在清单，跳过）→ `_execute`（wait_for 15s + **no_retry=True 不重试**）。
- **新增文件**：`agent/mcp_client.py`、`scripts/mcp_sample_server.py`、`tests/agent/test_mcp_client.py`；修改 `agent/tool_registry.py` / `src/config.py` / `main.py` / `agent/langgraph_react.py` / `tests/conftest.py`；**react.py / database.py / mcp_server.py / engine.py / router.py / requirements.txt 零 diff**。

## 10. 风险评估

- **stdio 子进程生命周期**：父进程异常退出 → 子进程孤儿（close 时正常终结；本模块不引入守护逻辑，如实声明残余）；子进程挂起 → 单次调用 15s wait_for 兜住 + 握手 10s 超时 fail-open；连接中断后再次调用 → `_ext_call` 返回可读提示不崩 SSE，服务不自动重连（v1 明确不做重连，重启服务恢复）。
- **fail-open 误伤**：连接失败仅外部工具不可用，内置 10 工具零影响（init_ext 内部捕获 + registry 独立）；已注册外部工具执行期失败返回提示喂回 LLM（073 降级哲学同口径）。
- **外部结果注入**：文本块 + 截断 2000；错误提示不含堆栈/密钥（铁律 8 日志防敏感）；LLM 可能把外部结果当事实——由 083 schema / 审批人肉把关 + 086 注入防护（后续阶段）兜底，本模块不加内容校验（明确不做）。
- **同名覆盖**：冲突检测跳过（§1.4），防破坏内置工具。
- **白名单语义错误（返回 None 放行外部）**：§1.4 语义矩阵写死——外部启用分支绝不返回 None；WP-G 三态单测锁死。
- **langgraph 绕过口**：WP-E 透传闭环；approval 闸在 run 内两循环通用（即使漏接也有审批兜底，深度防御）。
- **零回归风险面**：默认全关 + conftest 钉 false + 存量端点 allowed_tools 传 None 路径不变；no_retry 默认 False。Developer 先用受影响存量套件（test_agent_tools 62 + test_tool_retry_dedup 24 + test_mcp_server + test_rerank_langgraph）局部跑通再全量。
- **行数**：§8 对照表；样例 server 计入与否均 ≤200。

## 11. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-083 治理五件 | 审批：外部工具硬编码 approval="required"，复用 approval_requests 表 + 审批两端点；白名单：allowed_tools 两端点透传（Agent 粒度）与 _phase_allows（阶段粒度）叠加；schema 校验：MCP inputSchema 直接作 args_schema 天然复用；超时：15s 默认围栏；幂等：外部不在清单不适用（治理靠审批+白名单） |
| module-073 自动重试 | 外部工具 no_retry=True 关闭（副作用不可重放）；内置 10 工具默认 False 语义逐字不变 |
| module-066 tool_call_logs | 外部工具调用自动落库（name/args/result/duration）；审批拦截 = run 返回提示 → result_ok=true；白名单拒绝 = result_ok=false 审计可见 |
| module-067 MCP server（入向）| 067 是把自家只读 6 工具经 FastMCP 暴露给外部 client（入向）；084 是作为 client 接外部 server（出向）——方向相反互不影响；mcp_server.py 零 diff |
| module-058 阶段切分 | 外部工具 group=None 全阶段 schema 可见（见 §0 语义推导）；不受 retrieval/generation 阶段限制（合理：外部工具与阶段无关），预算计数/推进语义不变 |
| module-030/068 langgraph | WP-E 透传后 agent-lg 与 agent 同受白名单约束；None 时存量行为零变化（083 AC-33 口径保持） |
| module-072 intent/router | 不受影响（外部工具不进意图分类/路由） |

## 12. 明确不做（超范围）

Streamable HTTP client（远程 server 接入）；args 级审批粒度；外部分组/只读组豁免审批；按白名单过滤 schema 暴露；外部工具超时单独调优（085 看板 P95 后）；连接中断自动重连；多外部 server 并发（v1 单 server）；工具列表展示端点。

## 13. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-01 | 初始版本（技术选型四定案 + WP-A~G 拆解 + 安全默认矩阵 + 行数对照 + 风险与既有机制关系） | Planner |