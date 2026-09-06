# 变更记录 — Module-084: 外部 MCP 客户端接入（stdio 发现注册 + 治理约束 + 白名单透传）

> Developer: 2026-09-03 | 依据：`plan.md` v1（2026-09-01/02，WP-A~G）+ `acceptance-criteria.md`（AC-1~AC-49）
> 基线：module-083 后全量 **1526 passed / 6 failed（4×module-028 proxies 环境性 + 2×real_redis 环境性）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）**——本模块红线：**新增 0 失败、存量测试零改动、react.py / database.py / mcp_server.py / engine.py / router.py / requirements.txt 零 diff**
> 实施说明：WP-A（tool_registry no_retry）与 WP-C（config 4 配置项）已由前次会话（2026-09-02）先行落地；本次会话完成 WP-B/D/E/F/G 并清理 WP-A 遗留的两处编辑瑕疵（`__init__` 重复赋值块 + docstring 乱码 `EfY`，纯删除零行为变化）。

---

## 一、实现总览（外部工具执行链路）

```
服务启动（lifespan）
  → mcp_client.external.init_ext(registry)：门控（enabled+command）→ stdio 子进程
    + ClientSession 握手（mcp_external_timeout 围栏）→ list_tools 发现
    → 逐工具：冲突检测（重名跳过防覆盖）→ registry.register(
        name, desc, inputSchema, _ext_func, group=None,
        approval="required", no_retry=True)
Agent 调用（两个端点同口径）
  → allowed_tools = mcp_client.external.agent_allowed_tools()（语义矩阵三态）
  → execute_tool_with_log 二维守门（阶段 + 白名单，module-083）
  → AgentTool.run._precheck（审批闸 required → schema 校验（inputSchema 复用）
    → 幂等（外部不在清单，跳过））
  → _execute（wait_for 15s 围栏 + no_retry=True 不自动重放）
  → _ext_func 闭包 → session.call_tool → 结果归一化（isError/structuredContent/
    文本拼接/空占位）→ 截断 2000
服务关闭（lifespan finally）→ mcp_client.external.close()（幂等）
```

## 二、WP 实现说明

### WP-A no_retry（AC-1~AC-3，前次会话落地 + 本次清理）
- `AgentTool.__init__` / `register()` 加 `no_retry: bool = False`；`_execute` 重试条件追加 `and not self.no_retry`——内置 10 工具默认 False，073 自动重试语义逐字不变；外部副作用工具传 True 关闭自动重放。
- 本次清理：`__init__` 内前次编辑意外产生的重复赋值块（description/args_schema/func/group/timeout/approval 二次赋值）删除；docstring 中乱码 `EfY` 删除。纯删除零行为变化。

### WP-B agent/mcp_client.py（AC-4~AC-13，核心新文件）
- **`ExternalMCPClient` 模块级单例 `external`**：状态 = `_stdio_cm` / `_session_cm` 两个异步上下文句柄 + `session` + `registered` 名集合 + `_registry` 引用。stdio 上下文句柄存实例字段是会话跨 init_ext 生命周期存活至 close() 的关键。
- `init_ext(reg)`：`mcp_external_enabled=False` → 返回 0 零开销（不 spawn）；command 空 → warning + 返回 0（AC-27 fail-open 分支）；`_spawn_session()`（StdioServerParameters(command, args, cwd=ai_service 根) + `asyncio.wait_for(mcp_external_timeout)` 全路径围栏）→ `_register_tools(reg)`（list_tools → 冲突检测 → register）→ 任何异常 warning + 返回已注册数（fail-open 不 re-raise，AC-31）。
- **注册契约**：`approval="required"`（硬编码不走配置——外部工具可能有副作用，宁可多审）；`no_retry=True`（073 重试排除的动态工具名实现）；`group=None`（未分组全阶段 schema 可见，plan §0 定案——外部工具与执行阶段无关，可见性交审批+白名单两闸）；`args_schema` 直接用 MCP `inputSchema`（JSON Schema 天然兼容 083 jsonschema 校验）。
- **同名冲突检测**：`tool.name in reg.list_tool_names()` → 跳过 + warning（register 是同名覆盖语义，防外部工具顶掉内置 10 工具，AC-6）。
- `_ext_call(name, args)`：`session.call_tool(name, arguments=args or {})` → 归一化四分支：`isError` → 可读失败提示；`structuredContent` 非空 → JSON 序列化优先（防文本块重复表达）；`content` 文本块拼接；空 → `（外部工具 X 无返回结果）`占位（AC-34）。统一 `_truncate(2000)`（对齐 067 截断）。**任何异常 → `（外部工具 X 调用失败: {e}）`不抛裸异常**（AC-11，SSE 流不中断；异常消息无堆栈无密钥，铁律 8）。
- `close()`：session → stdio 依次 `__aexit__`，各自 try/except 告警不抛（shutdown 路径清理失败不失败）；未初始化直接返回（AC-13 幂等）。
- `agent_allowed_tools()` **语义矩阵（AC-12 红线）**：未启用（或 `_registry is None`，init_ext 从未成功调用）→ `None`（存量全量放行零变化）；启用（无论白名单空否）→ **非 None** = `set(内置名) ∪ (registered ∩ mcp_external_tools)`——启用分支绝不返回 None（None=全量放行会放行未授权外部工具）；白名单空 = 只放内置外部全拒；白名单含未注册名 → 交集自然为空不报错（AC-26）。内置名动态取 `registry.list_tool_names() - registered`（不硬编码 10 名，对内置工具集变化鲁棒）。
- mcp 1.26.0 client API 实测（开发期 `python -c` 探针）：`StdioServerParameters` 含 `cwd` 字段；`ListToolsResult.tools`（Tool.name/description/inputSchema）；`CallToolResult(content/structuredContent/isError)`；`call_tool(name, arguments=...)`。

### WP-C config（AC-14~AC-15，前次会话落地）
- `mcp_external_enabled: bool = False` / `mcp_external_command: list[str] = []`（PW_ env JSON 数组）/ `mcp_external_tools: list[str] = []`（显式授权白名单）/ `mcp_external_timeout: float = 10.0`。默认全关 = 存量零变化；env 映射实测 `Settings(_env_file=None)` JSON 数组解析通过。

### WP-D lifespan + 两端点（AC-16~AC-19）
- main.py 顶部 `from agent import mcp_client` + `from agent.tool_registry import registry`（agent.tool_registry 经 mcp_server import 链已在 import 期加载，零新增启动开销）。
- lifespan：`setup_feedback_scheduler(True)` 之后、`mcp_http_lifespan()` 进入之前 `await mcp_client.external.init_ext(registry)`（fail-open 语义由 init_ext 内部捕获保证）；finally 中 `mcp_http_ctx.__aexit__` 之后 `await mcp_client.external.close()`（先退 MCP 任务组再关外部会话，幂等）。
- `/ai/rag/chat/agent`（react_loop）与 `/ai/rag/chat/agent-lg`（langgraph_react_loop）event_stream 内循环调用前各加一次 `allowed_tools = mcp_client.external.agent_allowed_tools()` 并透传——**两路同接消除 agent-lg 绕过口**（AC-18/19/43）；外部未启用时返回 None，存量行为逐字不变（AC-38）。

### WP-E langgraph_react.py（AC-20~AC-21）
- `ReActGraphState` 加 `allowed_tools: Optional[set[str]]` 键；`langgraph_react_loop` 尾部加 `allowed_tools=None` 参数（追加在 max_answer_len 之后，存量位置调用方零影响）→ `initial_state["allowed_tools"]`；`execute_tools` 节点 `state.get("allowed_tools")` 透传给 `execute_tool_with_log`（TypedDict 键缺省安全，.get 防 KeyError）。
- None = 全量放行 → 未配置外部工具时存量行为零变化（083 AC-33 口径保持）。

### WP-F scripts/mcp_sample_server.py（AC-22~AC-24 验收 fixture）
- FastMCP("mcp-sample-server") + 2 工具：`ext_current_time`（只读，UTC ISO 时间）/ `ext_append_log`（副作用，向脚本同目录 `mcp_sample_out.log` 追加一行——审批治理演示价值）。`mcp.run()` stdio。logging 走 stderr（stdout 是协议通道，对齐 mcp_server.py 先例）。生产使用方把 `PW_MCP_EXTERNAL_COMMAND` 指向任意真实 server 即可，client 与 server 内容无关。

### WP-G 测试（AC 覆盖见 test-report）
- `tests/agent/test_mcp_client.py` **34 项**（WP-A 3 / init_ext 6 / _ext_call 7 / allowed_tools 4 / config 2 / lifespan 3 / 端点白名单 3 / langgraph 3 / 样例 server 3）。
- conftest 新增 autouse `default_mcp_external_disabled`：钉 enabled/command/tools 三件套全关 + **重置 external 单例残留状态**（registered/_registry，测试间独立）。
- 真实子进程用例（AC-23/24）用 `sys.executable` 保证 venv python；**AC-24 全程单 `asyncio.run`**——anyio cancel scope 与 task 绑定，stdio 上下文跨 asyncio.run 进入/退出会 "exit cancel scope in a different task"（开发期实测坑，已在代码注释标注）。

## 三、行数统计（铁律 2，AST 语句口径）

| WP | 文件 | 行数 |
|----|------|------|
| WP-A | agent/tool_registry.py（改，084 归属部分） | ~7 |
| WP-B | agent/mcp_client.py（新） | 113（AST 语句） |
| WP-C | src/config.py（改，084 归属部分） | ~10 |
| WP-D | main.py（改，084 归属部分） | ~23 |
| WP-E | agent/langgraph_react.py（改） | 11（diff numstat） |
| **核心合计** | | **~164 ≤ 200 ✓** |
| WP-F | scripts/mcp_sample_server.py（新，验收样例） | 19（AST 语句） |
| 严格口径合计 | | **~183 ≤ 200 ✓** |

（tool_registry/config/main 的 git diff numstat 含 module-083 未提交变更，084 归属部分按功能行估算；方法长度：最长 `init_ext` 28 行 ≤ 50 ✓）

## 四、测试结果（Developer 自测，2026-09-03）

| 验证 | 命令 | 结果 |
|------|------|------|
| 定向 | `pytest tests/agent/test_mcp_client.py -q` | **34 passed**（26.89s） |
| 受影响存量 | `pytest tests/agent/test_agent_tools.py tests/agent/test_tool_retry_dedup.py tests/agent/test_tool_governance.py tests/agent/test_tool_phase_split.py tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py tests/core/test_rerank_langgraph.py -q` | **204 passed**（86.63s，存量零改动） |
| py_compile | 6 个变更/新增生产文件 | COMPILE OK |
| import 链冒烟 | mcp_client/tool_registry/langgraph_react/main | 10 内置工具 no_retry 全 False / approval 全 auto / disabled → allowed_tools None |
| 真实握手冒烟 | stdio_client + mcp_sample_server.py | list_tools 2 实名工具 + 双工具真实执行 + 日志文件真实追加 |

## 五、遗留与明确不做

- Streamable HTTP client / 自动重连 / 多 server 并发 / args 级审批粒度 / 按白名单过滤 schema 暴露——plan §12 明确不做。
- stdio 子进程孤儿（父进程异常退出时）如实声明，v1 不引入守护逻辑；连接中断重启服务恢复。
- 外部工具结果喂回 LLM 的内容级校验不做（086 注入防护阶段兜底）。

---

## 六、真实 MCP 接入修复轮（2026-09-06，验收后补充）

真实接入官方 `@modelcontextprotocol/server-filesystem`（v2026.8.31，node 直启）实测发现并修复 1 处缺陷：

- **缺陷**：`_spawn_session` 用 `asyncio.wait_for` 包 `stdio_client.__aenter__` / `ClientSession.__aenter__`——wait_for 会把协程 `ensure_future` 进**临时 task**，而 anyio 的 cancel scope 绑定"进入上下文的 task"，`close()` 时从调用方 task 退出 scope 报 `Attempted to exit cancel scope in a different task`，stdio 子进程清理实际未执行（Reviewer LOW-③"握手中途失败子进程延迟回收"的深层根因）。
- **修复**：改用 `asyncio.timeout(...)`（Python 3.11，当前 task 内到期取消，scope 归属不变）包住握手全程；新增握手失败时**同 task 内 `await self.close()` 回收已进入的上下文**（close 幂等逐段容错），彻底消除子进程孤儿窗口。
- **测试修正**：AC-28 超时用例初版 mock 让超时路径走了 AttributeError 分支（假绿）——重写为 fake session 类 `__aenter__` 真实 sleep 1.0s，断言超时后 `_stdio_cm/_session_cm` 已被回收为 None。
- **验证**：定向 34/34 全绿；真实 server 探针复跑 close 警告消失；治理链路全通（14 工具发现注册 / 白名单拒绝越权 / 审批拦截 → 真实 PG approval_requests 落 pending / 批准后真实执行 / structuredContent 优先分支实证）。

