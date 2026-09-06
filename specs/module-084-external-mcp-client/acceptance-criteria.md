# 验收标准 — Module-084: 外部 MCP 客户端接入（MCP client 发现 + 注册外部工具进 ToolRegistry，受 module-083 工具治理约束）

> 依据：`plan.md` v1（2026-09-01）| 验收口径：默认配置下 **存量行为零变化**（外部默认全关）；全量 **1485 passed / 4 failed（module-028 proxies 环境性基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）** 新增 0 失败、**存量测试零改动** 红线

## 1. 功能验收

### 1.1 WP-A：工具注册面扩展（no_retry）
- [ ] AC-1 `AgentTool.__init__` / `register()` 新增 `no_retry: bool = False` 字段；内置 10 工具注册后 `no_retry` 全 False（`reg.list_tools()` 逐一核验）——073 自动重试语义逐字不变
- [ ] AC-2 `AgentTool(no_retry=True)` 首试异常 → **不自动重试**（func 执行 1 次、wait_for 1 次调用断言），返回 `""`
- [ ] AC-3 `AgentTool(no_retry=False)`（默认）首试异常 → 仍自动重试 1 次（073 存量行为，存量 `test_tool_retry_dedup.py` 全绿实证）

### 1.2 WP-B：MCP client 接入核心（`agent/mcp_client.py`）
- [ ] AC-4 **默认禁用零开销**：`mcp_external_enabled=False` 时 `init_ext(registry)` 返回 0、`stdio_client`/spawn 断言 0 次调用（不启动子进程）、registry 无外部工具
- [ ] AC-5 **发现注册**：mock `list_tools` 返回 2 个工具（`ext_current_time` / `ext_append_log`）→ `init_ext` 后 registry 多出 2 工具，且逐一断言：`approval=="required"`、`group==set()`（未分组）、`no_retry==True`、`args_schema==inputSchema`、返回注册数 2
- [ ] AC-6 **冲突名跳过**：外部工具名与内置 10 工具重名（如 `search_knowledge`）→ 跳过不覆盖内置工具 + `logger.warning`（注册后内置工具行为/description 一字不变）
- [ ] AC-7 **call_tool 正常路径**：外部工具 `run(args, ctx)` → session.call_tool 收到 (name, arguments=args)，文本块结果拼接待返回
- [ ] AC-8 **structuredContent 优先**：CallToolResult 同时含 content 与 structuredContent → 返回 structuredContent JSON 序列化
- [ ] AC-9 **超长截断**：结果 >2000 字符 → 截断 + 截断标记（`…`），不撑爆 LLM 上下文
- [ ] AC-10 **isError 语义**：`CallToolResult.isError=True` → 返回可读失败提示文本（非裸异常）
- [ ] AC-11 **异常兜底**：call_tool 抛任意异常 / 会话中断 → 返回可读提示（"（外部工具 X 调用失败…）"），不抛裸异常、SSE 事件流不中断
- [ ] AC-12 **agent_allowed_tools 三态**：外部未启用 → `None`；启用且白名单含授权名 → `set(内置 10 名 ∪ 已注册∩白名单)`；启用但白名单为空 → **非 None**（=只放内置，外部全拒）——语义矩阵锁死
- [ ] AC-13 `close()` 幂等：未初始化调用直接返回；初始化后关闭 session + stdio 无异常

### 1.3 WP-C：配置（`src/config.py`）
- [ ] AC-14 新增 4 项配置：`mcp_external_enabled=False` / `mcp_external_command=[]` / `mcp_external_tools=[]` / `mcp_external_timeout=10.0`（默认全关 = 存量零变化）
- [ ] AC-15 环境变量映射：`PW_MCP_EXTERNAL_ENABLED=true` + `PW_MCP_EXTERNAL_COMMAND='["python","scripts/mcp_sample_server.py"]'` + `PW_MCP_EXTERNAL_TOOLS='["ext_append_log"]'` 生效（`python -c "from src.config import settings; print(...)"`）

### 1.4 WP-D：lifespan + 两端点接线（`main.py`）
- [ ] AC-16 lifespan startup 调用 `init_ext(registry)`（monkeypatch 计数 ≥1）且 **fail-open**：spawn 抛异常 → 服务启动不崩、/health 200、内置 10 工具 agent 问答正常
- [ ] AC-17 lifespan shutdown 调用 `close()`（monkeypatch 计数）
- [ ] AC-18 `/ai/rag/chat/agent`（手写 ReAct）带 `allowed_tools`：外部工具未授权 → 执行层拒绝、func 未执行、提示含"权限白名单"、不提交审批申请（approval_requests 无新 pending 行）
- [ ] AC-19 `/ai/rag/chat/agent-lg`（LangGraph）同样受白名单约束（拒绝口径同 AC-18，集成断言一次）

### 1.5 WP-E：langgraph_react.py allowed_tools 透传
- [ ] AC-20 `ReActGraphState` 含 `allowed_tools` 键；`langgraph_react_loop(allowed_tools=None)` 缺省 → 存量全量放行语义零变化
- [ ] AC-21 传入白名单 → `execute_tools` 节点把 allowed_tools 传给 `execute_tool_with_log` 生效（越权调用拒绝，`result_ok=false`）

### 1.6 WP-F：样例外部 MCP server + 真实子进程握手（核心验收——"接 1 个真实外部 MCP server"）
- [ ] AC-22 `scripts/mcp_sample_server.py` 可独立启动：`cd ai_service && python scripts/mcp_sample_server.py`（stdio 模式）不报错；`ext_current_time` 只读返回 UTC 时间、`ext_append_log` 向 `mcp_sample_out.log` 追加一行（副作用演示）
- [ ] AC-23 **真实握手**（非 mock）：测试内 `stdio_client(StdioServerParameters(command=["python","scripts/mcp_sample_server.py"]))` 真实子进程 → `list_tools` 返回 2 个实名工具（`ext_current_time`/`ext_append_log`）→ `call_tool("ext_current_time")` 返回真实时间字符串
- [ ] AC-24 **注册链路半真实**：真实样例 server 子进程 + 真实 registry → `init_ext` 注册 2 工具 → `ext_append_log` 未审批调用返回 `"(工具 ext_append_log 需人工审批，调用申请已提交)"` + pending 行落库（args 含调用参数）→ mock approve（`_approval_allowed` 返回 True 或真实表 UPDATE）→ 再调用真实执行（文件确实追加）

## 2. 边界条件验收
- [ ] AC-25 **外部未启用时 LLM schema 无外部工具**：registry 只含内置 10 工具（`to_llm_schemas()` 长度 10）、`agent_allowed_tools() is None`——存量端点零变化
- [ ] AC-26 **白名单含未注册名**（server 未提供）：agent_allowed_tools 不报错、不含该名；`allowed_tools` 集合无副作用
- [ ] AC-27 **空 command + enabled=true**：不 spawn、warning、返回 0（fail-open 分支）
- [ ] AC-28 **超时边界**：握手超时（`mcp_external_timeout=0.01` + server 慢启动）→ 返回 0 不阻塞启动；执行期超时由 `AgentTool.timeout`（默认 15.0）兜住（外部工具 failure 返回文案"（工具 X 执行超时）"兼容）
- [ ] AC-29 **工具名可辨识前缀**：样例 server 工具名带 `ext_` 前缀（样例约定；外部任意 server 不强制，冲突检测兜底）
- [ ] AC-30 **参数校验继承**：外部工具传 schema 违规参数（如 ext_append_log 缺必填）→ 083 WP-A 校验提示（"参数错误"），func 未执行

## 3. 异常场景验收
- [ ] AC-31 **spawn 失败**（command 指向不存在命令）→ init_ext 返回 0 + warning；服务启动 200；内置工具正常（fail-open 铁律）
- [ ] AC-32 **会话中断后调用**：外部工具执行期 session 失效 → 可读提示返回、不崩溃、LLM 循环继续（SSE 事件流完整）
- [ ] AC-33 **审批 DB 异常** → fail-closed 拒绝执行（083 语义复用，不因外部引入而变）
- [ ] AC-34 **外部结果为空** → 可读占位提示（"（外部工具 X 无返回结果）"或等价），不进 `_retrieval_hit` 误判路径（外部工具不在 `_RETRIEVAL_HIT_TOOLS`）
- [ ] AC-35 **多个外部工具并行调用**（一次 SSE 多 tool_call）→ 各自独立 call_tool、结果正确对应（无串话）

## 4. 非功能验收

### 4.1 向后兼容零回归
- [ ] AC-36 全量 pytest = **1485 passed / 4 failed（module-028 proxies 基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）——新增 0 失败**
- [ ] AC-37 存量测试零改动：test_agent_tools.py（62 项）、test_tool_retry_dedup.py（24 项）、test_mcp_server.py、test_rerank_langgraph.py 全过
- [ ] AC-38 **红线 git diff**：react.py / database.py / mcp_server.py / engine.py / router.py / requirements.txt **零 diff**；生产修改仅 tool_registry.py / config.py / main.py / langgraph_react.py
- [ ] AC-39 **默认配置生产行为零变化**：外部全关时 10 工具 approval 全 auto、no_retry 全 False、allowed_tools 全 None、幂等清单不变

### 4.2 性能验收
- [ ] AC-40 **禁用路径零开销**：`mcp_external_enabled=False` 时 init_ext 直接返回（无 import 副作用、无子进程、无 DB 操作）
- [ ] AC-41 **启用路径开销可控**：注册仅启动时一次（list_tools 一次网络往返）；每次外部调用 1 次 call_tool（15s 超时围栏内），结果截断 2000 防 LLM 上下文膨胀

### 4.3 安全验收
- [ ] AC-42 **审批全部 required**：所有外部工具 `approval=="required"`（硬编码，非配置可豁免）；内置 10 工具仍全 auto（无新增 DB 开销）
- [ ] AC-43 **无绕过口**：手写 + langgraph 两端点均接白名单（AC-18/19）；审批闸在 run 内两循环通用（深度防御）
- [ ] AC-44 **同名冲突不覆盖内置**（AC-6）；外部结果/错误提示不含堆栈与密钥（grep 日志无敏感信息，铁律 8）；无 SQL 拼接新增（复用 083 参数化审批查询）

### 4.4 代码质量验收（铁律）
- [ ] AC-45 生产功能代码 ≤200 行（预估核心 ~140；严格口径含样例 server ~180）；**测试代码不计入**；超限按 plan §8 晒对照 + 申请放宽
- [ ] AC-46 方法 ≤50 行（init_ext 若超限拆 `_spawn_session` / `_register_tools` 辅助）；public/导出方法有 docstring
- [ ] AC-47 无空 catch/吞异常：所有 except 带 logger + fail-open/fail-closed 性质注释
- [ ] AC-48 零新依赖（requirements.txt 零 diff）；零新表（复用 approval_requests）；零新端点（复用审批两端点）
- [ ] AC-49 无新 ADR（默认，选型决策记录入 changelog；协调者裁定需 ADR 则后补）

## 5. 可运行验证命令表

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量回归 | `cd ai_service && python -m pytest -q` | 1485 passed / 4 failed（proxies 基线）/ 3 skipped / 1 error（陈旧脚本），**新增 0 失败** |
| 定向单测 | `cd ai_service && python -m pytest tests/agent/test_mcp_client.py -q` | 全部 passed（预计 ~26 项，含真实子进程握手 AC-23/24） |
| 受影响存量 | `cd ai_service && python -m pytest tests/agent/test_tool_retry_dedup.py tests/agent/test_agent_tools.py tests/test_mcp_server.py tests/test_rerank_langgraph.py -q` | 全部 passed（存量零改动实证） |
| 依赖冒烟 | `python -c "from mcp.client.stdio import stdio_client; from mcp import ClientSession; import importlib.metadata as m; print(m.version('mcp'))"` | `1.26.0`（client 端可导入，零新依赖实证） |
| 样例 server 启动 | `cd ai_service && python scripts/mcp_sample_server.py` | 进程常驻（stdio 模式，Ctrl+C 退出），无报错 |
| config 冒烟 | `python -c "from src.config import settings; print(settings.mcp_external_enabled, settings.mcp_external_command, settings.mcp_external_tools, settings.mcp_external_timeout)"` | `False [] [] 10.0` |
| 红线核验 | `git diff --stat` | 修改 tool_registry.py / config.py / main.py / langgraph_react.py / conftest.py + 新增 mcp_client.py / mcp_sample_server.py / test_mcp_client.py；react/database/mcp_server/engine/router/requirements 零 diff |
| fail-open 冒烟（Tester，可选） | `.env` 设 `PW_MCP_EXTERNAL_ENABLED=true` + `PW_MCP_EXTERNAL_COMMAND='["python","no_such_server.py"]'` 启动服务 → `curl http://127.0.0.1:8001/health` + agent 问答 | 启动 200 不崩，日志 warning"MCP 外部接入失败"，内置工具 agent 问答正常 |
| 真实 E2E（Tester，可选/尽力） | `.env` 设 enabled=true + command 指向样例 server + tools 白名单 `["ext_append_log"]` → 启动服务 → 引导 LLM 使用 ext_append_log 的 agent 对话 → `GET /ai/tools/approvals?status=pending` → `POST /ai/tools/approvals {id, action:"approve"}` → 再对话 | SSE 首轮 tool_result 含"需人工审批"；pending 可见；approve 后再调真实执行（mcp_sample_out.log 追加）→ 全链路闭环（LLM 工具选择行为性，如实记录） |

## 6. 验收结论
- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-09-01
- 结论: [ ] 通过 / [ ] 不通过
- 备注: Tester 重点关注 AC-4/5（禁用零开销 + 发现注册契约）、AC-12（allowed_tools 三态语义矩阵，防 None 放行外部）、AC-18/19/21（双端点无绕过口）、AC-23/24（真实子进程握手 = 本模块核心价值）、AC-28（fail-open + 超时）、AC-36 全量零新增失败