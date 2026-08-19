# Module-067 变更日志 — MCP 集成（ToolRegistry → 标准 MCP Server，ADR-0018）

> 实施：Developer（2026-08-17）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：ToolRegistry 10 工具 → 标准 MCP Server（stdio + Streamable HTTP 双传输，
> 只读 6 工具 + token 认证 fail-closed）。全量 pytest 基线 1075/0（module-066 验收数；
> 实测收集 1076，scripts/test_models.py 1 项系 module-050 遗留 ERROR 未触碰）。

## 一、WP-A：mcp_server.py + 动态注册

**产出**：`ai_service/mcp_server.py`（约 190 行含 docstring，功能代码 < 200 行达标）。

- **READ_ONLY_TOOLS 显式白名单常量**（6 名）：search_knowledge / search_fts /
  search_vector / search_graph / extract_entities / recall_memory——**不按 group 过滤**
  （检索组 7 个含 re_search 双组状态类工具，按 group 会多暴露，plan §0.2 事实修正落地）。
- **build_server(registry, groups=None)**：遍历 `registry.list_tools()` 动态注册；
  `groups=None` → 白名单过滤；显式 groups（如 ["retrieval"]）→ 按 group 过滤
  （仅测试/扩展用）。**ToolRegistry 零改动**（tool_registry.py 不在 git diff），
  描述/args_schema 单一事实源——改 registry 描述 build_server 自动同步（单测验证）。
- **参数模型动态生成**（`_make_tool_fn`）：exec 构造带 type hints 的闭包函数——
  properties 键 → 参数名；type 映射 string→str / integer→int / number→float /
  boolean→bool，未知 → str 兜底；required 字段必填、带 default 给默认值、其余可选
  （`Optional[X] = None`）；**必填参数排前、可选排后**（Python 函数签名约束——
  `_VERIFY_SCHEMA` 只 required answer、query 可选，乱序会 SyntaxError，实测修复）。
  FastMCP 从 type hints 自生成 MCP schema（可选参数呈 anyOf [type, null]）。
  **None 值参数在 args 构造时剔除**——`int(args.get("top_k", 5))` 缺省语义不被
  `int(None)` 破坏（单测 test_optional_param_none_dropped）。
- **执行统一走 `AgentTool.run(args, ctx)`**（复用 15s 超时 + 异常降级，不直接调
  func）；run 返回空串（执行失败）→ 包装"（工具执行失败）"可读提示，不抛裸
  Exception；工具内部防御文案（"（无检索结果）"等）透传保留。
- **轻量 ctx 合成**（`_make_ctx`）：SimpleNamespace(query / identity="mcp" /
  docs=[] / memory="" / add_docs no-op / add_note no-op)——不构造完整 ReactContext；
  search 系拿得到 query、recall_memory 拿得到 identity 且可写 ctx.memory（单测验证）。
- **截断** `_truncate_result(text, limit=2000)`：超限截断 + 后缀
  "…（结果已截断，完整内容需更多上下文）"，未超限原样。
- **stdio 入口**：`if __name__ == "__main__": mcp.run()`（默认 stdio 传输）；
  模块级 `mcp = build_server(registry)` 供 main.py 挂载复用同一实例。
- **日志走 logging（stderr），模块内零 print**（stdio 模式 stdout 是协议通道）。

**通过标准达成**：单测覆盖 build_server 恰 6 工具（名称与白名单一致）/ description
透传 / schema 三变体（_SEARCH/_ENTITY/_MEMORY）转换 / 截断 ≤2000 原样 + >2000 截断
提示 / ctx 合成（identity + query + memory 可写）/ 缺必填参数与类型错误被 MCP 参数
校验拒绝（ToolError 可读错误非 500）。**冒烟**：stdio python client（官方 mcp SDK
ClientSession）6 工具全列出 + search_knowledge 真实检索返回截断版结果（真实 PG +
真实图谱提取，输出记录见 §五）。**未达成**：`mcp dev` Inspector GUI 本机沙箱不可开
（进程可正常启动，已记录），以 python client 冒烟为连通性证明（plan §0.12 兜底方案）。

## 二、WP-B：Streamable HTTP 挂载 FastAPI + token 认证

**产出**：main.py 挂载 + 认证中间件 + lifespan fail-closed + config 字段 +
requirements 一行。

- **FastMCP 1.26.0 版本适配（实测，勿照抄 ADR 旧写法）**：
  - `stateless_http` / `json_response` 是 **FastMCP 构造参数**（`streamable_http_app()`
    零参调用）——构造即传，stdio 共用同一实例不受影响；
  - **1.26.0 构造无 `version` 参数**（serverInfo version 由 SDK 管理，实测显示
    "1.26.0"），省略并注释说明；
  - **`streamable_http_path="/"`**：默认 `/mcp` 挂载到 `/ai/mcp` 后实际端点为
    `/ai/mcp/mcp`（与 plan 声明不一致），设 "/" 使端点落在挂载根；
  - **Starlette Mount 不转发 lifespan scope**：FastMCP session_manager 任务组只在
    自身 Starlette lifespan 初始化（独立 uvicorn 运行才触发）——挂载场景不处理则
    每个请求抛 "Task group is not initialized"（实测复现）。修复：新增
    `mcp_server.mcp_http_lifespan()` 复刻 `session_manager.run()` 核心语义
    （create_task_group + _task_group 注入 + cancel 关闭，去掉其"单次调用 guard"），
    main.py lifespan 的 yield 前后进入/退出（try/finally 兜底）；
  - **FastMCP 默认 DNS rebinding 保护关闭**：默认仅放行 localhost Host（实测
    "test" Host 被 421 拒绝）——0.0.0.0 部署下任何远程 Host 都会被拒，本项目安全
    边界是 token 认证（fail-closed），显式 `TransportSecuritySettings(
    enable_dns_rebinding_protection=False)`。
- **挂载**：`app.mount("/ai/mcp", _mcp_auth_middleware(mcp.streamable_http_app()))`
  （项目首个 mount）。规范 URL 为 **`/ai/mcp/`**（尾斜杠）；`/ai/mcp` 由 Starlette
  307 重定向（标准行为，实测确认）。
- **认证中间件** `_mcp_auth_middleware`（ASGI 包装 ~25 行）：`Authorization:
  Bearer <PW_MCP_TOKEN>`，比较用 **hmac.compare_digest**（常量时间防时序侧信道）；
  每次请求**实时读 settings.mcp_token**（不缓存，改 token 立即生效，单测验证）；
  token 为空 → 恒 401（fail-closed 双保险）。
- **fail-closed 放 lifespan 不放 import 期**（存量测试全量 import main，import 期
  raise 全炸；测试全用 ASGITransport 不触发 lifespan，零影响——grep 实测零
  TestClient）：lifespan 启动处 `if not settings.mcp_token: raise RuntimeError(...)`，
  对齐 module-053 fail-fast 先例。
- **config.py**：`mcp_token: str = ""`（PW_MCP_TOKEN，注释写明 fail-closed 语义 +
  stdio 零认证边界）。
- **requirements.txt**：`mcp==1.26.0`（锁对齐已装环境；uv run mcp dev 依赖解析）。

**通过标准达成**：单测 token 三态（无/错 401、对 200）+ 空 token 恒 401 + 运行时
改 token 立即生效 + lifespan 空 token 启动即抛（RuntimeError 含 PW_MCP_TOKEN）；
真实 uvicorn 冒烟同口径全过（见 §五）。**未达成**：无（Inspector GUI 例外同 WP-A）。

## 三、WP-C：安全与边界

- **只读原则**：单测断言 generate_answer / verify_answer / re_search / note_to_self
  不在默认注册列表（含 re_search——检索组但被显式白名单排除，正是白名单的意义）；
  真实 stdio client tools/list 恰好 6 个同口径核对。
- **工具内部防御保留**：search 无结果提示、extract_entities 无实体提示等外部调用
  同样受益（适配层不剥除）。
- **执行语义**：走 `tool.run(args, ctx)`（15s 超时 + 失败返回提示文案）——不抛裸
  Exception 给 MCP client；run 空串包装"（工具执行失败）"（单测 mock 抛异常断言）。
- **明确不做（ADR-0018 决策 4）**：不实现 MCP client（冒烟脚本为临时验证，未入库）；
  不做工具治理迁移（阶段切分是 ReAct 循环内机制）；不做完整问答暴露（走
  /ai/rag/chat）；不写 SSE 传输（2025-03 规范已弃用，Streamable HTTP 替代）。
- **日志/凭证**：mcp_server.py 零 print；token 不落日志（中间件不打印认证信息）。

**通过标准达成**：单测覆盖只读过滤（4 个非只读不在列）/ token 三态 / 截断 /
fail-closed / ctx 合成 / schema 三变体 + 未知类型 str 兜底 + default 生效。**未达成**：无。

## 四、WP-D：回归 + 文档收口

- **全量回归**：`python -m pytest -q` = **1102 passed**（1075 基线 + 27 新增，
  存量零改动；scripts/test_models.py 1 项 ERROR 系 module-050 遗留，未触碰），
  0 failed。
- **新增单测 27 项**（`ai_service/tests/api/test_mcp_server.py`）：
  build_server 注册遍历 1 / 只读过滤 2 / 显式 groups 1 / description 透传 1 /
  schema 转换 6（三变体 + 未知 type + default + optional anyOf 口径）/ 截断 3 /
  执行 8（结果透传 / ctx query+identity / ctx.memory 可写 / 失败包装 / None 剔除 /
  缺必填 ToolError / 类型错误 ToolError / _make_ctx 形状）/ HTTP 认证 6（无/错/
  对 / 307 / 空 token / 改 token 即时生效）/ fail-closed 1（lifespan raise）。
- **文档**：本 changelog + README（环境变量表补 PW_MCP_TOKEN + 功能段补 MCP 能力）+
  CONTEXT.md（ADR-0018 行 + module-067 索引行，只增不删，已备份）+
  ADR-0018 状态 → ✅ 已实施（验收标准逐条核对标注）+ 07-项目经历-精简版.md
  （核心工作补第 6 条 MCP 集成）+ memory 三文件。
- **验证点**：红线遵守——tool_registry.py / react.py / engine.py 零改动；
  main.py 仅加 import + 挂载 + 中间件 + lifespan 检查；config.py 仅加 mcp_token；
  requirements.txt 仅加一行。git diff 可核对。

## 五、真实冒烟记录（2026-08-17）

| 验证项 | 方式 | 结果 |
|--------|------|------|
| stdio 连通 + 6 工具 + 只读核对 | python 官方 MCP client（ClientSession）spawn `python mcp_server.py` | TOOLS(6) 全列出（名称与 READ_ONLY_TOOLS 一致），generate_answer/re_search 不在列，初始化握手 OK |
| search_knowledge 真实检索 | 同 client `call_tool("search_knowledge", {query: "Java 线程池核心参数", top_k: 2})` | 真实返回 2 篇命中文档（"6-Java线程池ThreadPoolExecutor核心参数与工作原理" score=1.0 等，真实 PG + 真实图谱实体提取 entities=3），结果截断生效 |
| HTTP 无 token | 真实 uvicorn（PW_MCP_TOKEN=smoke-token-067）+ GET /ai/mcp/ | **401** |
| HTTP 错 token | 同上 POST initialize Bearer wrong | **401** |
| HTTP 正确 token | 同上 POST initialize Bearer smoke-token-067 | **200**，JSON-RPC 握手返回 serverInfo name=personal-knowledge-kb |
| 规范 URL | GET /ai/mcp（无尾斜杠） | 307 → /ai/mcp/（跟随后 401，链式验证） |
| fail-closed | 不设 PW_MCP_TOKEN 启动 uvicorn | **启动即抛 RuntimeError**"PW_MCP_TOKEN 未设置：MCP HTTP 模式 fail-closed 拒绝启动"，拒绝启动 |
| mcp dev | `mcp dev mcp_server.py`（沙箱无 GUI） | 进程正常启动运行 25s 无退出（Inspector GUI 沙箱不可开，如实记录） |

注意：本地 `ai_service/.env` 需补 `PW_MCP_TOKEN=<值>` 才能正常启动服务（fail-closed
新约束，README 环境变量表已说明）。

## 六、诚实边界与已知事项

1. **FastMCP 1.26.0 挂载适配是本次最大实测修正**：Mount 不转发 lifespan（任务组
   手动进入）、streamable_http_path 需 "/"、无 version 参数、DNS rebinding 保护
   421 拦截——均以实测行为为准并注释在代码中，与 ADR/task-brief 旧写法不同处已
   在 ADR-0018 验收标准节标注。
2. **规范 URL 带尾斜杠**（/ai/mcp/）：MCP client 配置 URL 时用尾斜杠版本（或依赖
   307 跟随）；接受 curl -i /ai/mcp 首跳 307。
3. **`python -m mcp` 不可用**（无 __main__），统一用 `mcp` / `uv run mcp` 命令。
4. **real MCP client（Cursor 等外部工具）连接未在沙箱实测**（无 GUI/无外置 IDE），
   以官方 SDK client stdio 冒烟 + HTTP JSON-RPC 握手为连通性证明。
5. 工具返回截断 2000 字符为全局阈值（非配置化），如需调整改 `_TRUNCATE_LIMIT`。

## 七、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | WP-A~D 全部实施：mcp_server.py + 挂载/认证/fail-closed + 27 单测 + 冒烟 + 文档收口 | Developer |

## 附：文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/mcp_server.py | 新增 | MCP 适配层（READ_ONLY_TOOLS / build_server / _make_tool_fn exec 参数模型 / _make_ctx / 截断 / mcp_http_lifespan / stdio 入口） |
| ai_service/main.py | 修改 | +import hmac/mcp_server + _mcp_auth_middleware + app.mount("/ai/mcp") + lifespan fail-closed + yield 前后 MCP session 任务组 |
| ai_service/src/config.py | 修改 | +mcp_token（PW_MCP_TOKEN） |
| ai_service/requirements.txt | 修改 | +mcp==1.26.0（含注释） |
| ai_service/tests/api/test_mcp_server.py | 新增 | 27 项单测 |
| specs/module-067-mcp-integration/changelog.md | 新增 | 本文档 |
| specs/adr/0018-mcp-integration.md | 修改 | 状态 → ✅ 已实施 + 验收标准逐条核对 + 适配点标注 |
| README.md | 修改 | 环境变量表 + 功能段 MCP 能力 |
| CONTEXT.md | 修改 | +ADR-0018 行 + module-067 索引行（只增不删，已备份） |
| docs/简历/07-项目经历-精简版.md | 修改 | 核心工作补 MCP 集成条目 |
| memory/project-context.md / file-index.md / agent-activity-log.md | 修改 | module-067 行 + 索引 + 活动记录 |
