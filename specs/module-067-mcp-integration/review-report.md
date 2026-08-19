# Module-067 审查报告 — MCP 集成（ToolRegistry → 标准 MCP Server，ADR-0018）

> Reviewer：2026-08-17 | 对照 `acceptance-criteria.md` + `plan.md` + ADR-0018 逐项核查
> 结论：**✅ Pass（3 项 LOW + 4 项 INFO 非阻塞记录）**

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest -q`（ai_service） | **1102 passed / 0 failed（161.29s，43 warnings）+ 1 ERROR**（`scripts/test_models.py::test_model` fixture 'label' 收集错误——文件 git diff 零改动，module-050 遗留，module-066 review-report §一 亦记录同一现象） |
| 新增单测 | 独立复跑 `python -m pytest tests/api/test_mcp_server.py -q` | **27 passed（47.39s）** |
| 增量核对 | 1102 − 27 = 1075 | 与 module-066 验收基线 1075 完全一致，存量零回归 |
| HTTP 无 token | 真实 uvicorn（127.0.0.1:8017，PW_MCP_TOKEN=review-smoke-067）`curl /ai/mcp/` | **401** |
| HTTP 错 token | 同上 `Authorization: Bearer wrong` | **401** |
| HTTP 对 token | 同上 POST initialize（2025-03-26 协议） | **200**，`serverInfo.name=personal-knowledge-kb`（version 1.26.0，无 version kwarg 适配点验证） |
| 规范 URL | `curl /ai/mcp`（无尾斜杠） | **307 → /ai/mcp/** |
| fail-closed | 环境无 PW_MCP_TOKEN 进入 lifespan | **RuntimeError "PW_MCP_TOKEN 未设置：MCP HTTP 模式 fail-closed 拒绝启动"**（放 lifespan 不放 import 期，实测确认） |
| 真实工具调用 | `build_server(registry).call_tool("search_knowledge", {query, top_k:2})` | 真实检索返回 2 篇（"6-Java线程池ThreadPoolExecutor核心参数与工作原理" score=1.0 等），LEN=456 |
| schema 实查 | 真实 registry 构建后 list_tools() | 恰 6 工具；query 必填 string；top_k 可选 `anyOf [integer, null]`；description 与 ToolRegistry 逐字一致 |
| exec 边界 | 零 properties schema 构建 | `_mcp_tool()` 零参闭包生成 + 调用正常（"no-args-ok"） |
| 代码长度 | mcp_server.py 统计 | 163 行总计 / **135 行功能代码**（≤200 达标）；`_mcp_auth_middleware` 单函数 22 行（≤50 达标） |
| 零 print | grep mcp_server.py | 0 处（日志走 logging→stderr） |
| 存量零改动 | git diff ai_service/ | tool_registry.py / react.py / engine.py / conftest.py 全部无 diff；main.py 仅 import hmac/mcp_server + lifespan 检查 + 中间件 + mount；config.py 仅 mcp_token；requirements.txt 仅 mcp==1.26.0 |
| CONTEXT.md 只增不删 | git diff CONTEXT.md | **+2 行**（ADR-0018 行 + module-067 索引行），零删行 |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-067 行（待审查状态）+ v0.67.0 + adr-018 索引 + file-index 3 行 + [PLAN]/[CODE] 行全在 |

## 二、WP 逐项核对

### WP-A：mcp_server.py + 动态注册 — ✅ 通过

- **READ_ONLY_TOOLS 显式 6 名白名单**（mcp_server.py:39-46）：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory——**不按 group 过滤**（plan §0.2 事实修正落地，规避检索组 7 含 re_search 双组状态类工具的多暴露风险）✓
- **build_server(registry, groups=None)**（L128-160）：遍历 `registry.list_tools()` 动态注册；`groups=None` → 白名单；显式 groups → `tool.group & group_set` 过滤（单测验证 generation 组恰 4 工具）；ToolRegistry 零改动，单一事实源 ✓
- **exec 动态参数模型**（L96-125）：properties 键 → 参数名；type 映射 string→str/integer→int/number→float/boolean→bool/未知→str；required 必填无默认、properties 带 default 给默认、其余 `Optional[X]=None`；**必填排前可选排后**（_VERIFY_SCHEMA 乱序 SyntaxError 实测修复的工程处理正确）；None 值参数剔除（`args.get("top_k",5)` 缺省语义不被 `int(None)` 破坏，单测 test_optional_param_none_dropped 验证）；零 properties 边界实测正常 ✓
- **执行统一走 AgentTool.run**（L83-93）：复用 15s 超时 + 异常降级；run 返回空串 → 包装"（工具执行失败）"；工具内部防御文案（"（无检索结果）"等）透传保留 ✓
- **轻量 ctx 合成**（L65-80）：SimpleNamespace(query/identity="mcp"/docs/memory + add_docs/add_note no-op)——不构造完整 ReactContext，search 系拿 query、recall_memory 拿 identity 且 memory 可写（单测验证）✓
- **截断**（L58-62）：≤2000 原样 / >2000 截断 + "…（结果已截断，完整内容需更多上下文）"（3 项单测）✓
- **stdio 入口 + 模块级实例**（L165, L192-195）：`if __name__ == "__main__": mcp.run()`；`mcp = build_server(registry)` 供 main.py 挂载复用 ✓
- **版本适配诚实**：stateless_http/json_response 构造参数、streamable_http_path="/"、无 version kwarg——均注释说明（L20-22, L140-151），与 mcp 1.26.0 实测签名一致 ✓

### WP-B：Streamable HTTP 挂载 + token 认证 — ✅ 通过

- **挂载**（main.py:281）：`app.mount("/ai/mcp", _mcp_auth_middleware(mcp_server.streamable_http_app()))`——项目首个 mount；真实 uvicorn 下 401/401/200/307 四态独立复测全过 ✓
- **认证中间件**（main.py:256-278）：`hmac.compare_digest` 常量时间比较（auth/expected 同 bytes 类型，无类型异常）；**每请求实时读 settings.mcp_token**（改 token 立即生效，单测 test_token_change_takes_effect_immediately 验证）；token 为空恒 401（fail-closed 双保险）；401 返回 JSONResponse 不含任何 token 信息，零日志输出 ✓
- **fail-closed 放 lifespan**（main.py:114-121）：`if not settings.mcp_token: raise RuntimeError(...)` 在 import 期之外、`init_db()` 之前——存量测试全 ASGITransport 不触发 lifespan 零影响（grep 全量 12 文件 36 处 ASGITransport 引用、无 TestClient，与 Developer 声明一致）；独立实测 lifespan 空 token 启动即抛 ✓
- **MCP session 任务组手动进入**（main.py:182-191）：Mount 不转发 lifespan scope 的适配——`mcp_http_lifespan()` 复刻 `StreamableHTTPSessionManager.run()` 核心语义（对照 SDK 源码逐行比对：create_task_group + _task_group 注入 + cancel + 置 None，去掉单次调用 guard）；HTTP initialize 200 实测证明任务组就绪 ✓
- **DNS rebinding 保护关闭**（mcp_server.py:150）：默认仅放行 localhost Host（实测 test Host 421）——0.0.0.0 远程部署必须关闭；安全边界为 token 认证（fail-closed + 中间件恒 401），代码注释声明充分 ✓
- **config.py**：`mcp_token: str = ""`（PW_MCP_TOKEN）带 fail-closed + stdio 零认证边界注释 ✓；**requirements.txt**：仅 `mcp==1.26.0` 一行 + 注释 ✓

### WP-C：安全与边界 — ✅ 通过

- **只读原则**：单测断言 generate_answer / verify_answer / re_search / note_to_self 不在默认注册列表（含 re_search——检索组但被显式白名单排除，正是白名单意义）；真实 registry 构建独立核对恰 6 工具 ✓
- **工具内部防御保留**：search 无结果提示 / extract_entities 无实体提示等透传（适配层不剥除）✓
- **执行语义**：走 AgentTool.run（15s 超时 + 降级）；单测 mock 抛异常 → "（工具执行失败）"可读文案；缺必填 / 类型错误 → MCP 参数校验 ToolError 可读错误（非 500/裸异常）✓
- **明确不做**：不实现 MCP client（冒烟脚本为临时验证未入库）、不做工具治理迁移、不做完整问答暴露（走 /ai/rag/chat）、不写 SSE（仅 Streamable HTTP，代码审查确认）✓
- **token 不落日志**：中间件零日志输出 ✓

### WP-D：回归 + 文档收口 — ✅ 通过

- 全量 1102/0 独立复跑（+1 项预存收集 ERROR 未触碰，module-066 同口径）✓
- 新增 27 项单测全覆盖 changelog 声明点（注册遍历/只读过滤 2/显式 groups/description 透传/schema 6/截断 3/执行 8/HTTP 认证 6/fail-closed 1）✓
- changelog 如实记录（Inspector GUI 沙箱不可开、真实 client 以官方 SDK stdio 冒烟 + HTTP JSON-RPC 握手为证、规范 URL 尾斜杠、.env 需补 PW_MCP_TOKEN 运营约束）✓
- ADR-0018 状态 ✅ 已实施（5 条验收标准逐条核对 + 适配点标注）✓
- README（PW_MCP_TOKEN + MCP 能力段）/ CONTEXT.md（只增 2 行，已备份）/ 07-项目经历-精简版.md（核心工作第 6 条）/ 三记忆文件全 ✓

## 三、发现（非阻塞，已附证据）

| # | 文件 | 位置 | 级别 | 问题描述 | 建议 |
|---|------|------|------|----------|------|
| 1 | ai_service/mcp_server.py | mcp_http_lifespan（L168-189） | LOW | 复刻 SDK `run()` 时遗漏了 finally 中的 `_server_instances.clear()`（对照 mcp 1.26.0 源码逐行比对）——lifespan 重启后 session_manager 残留陈旧 server instance。生产单次进入无影响、测试多轮进入无功能破坏（27 项 + HTTP 冒烟全过），但语义未完全对齐 | 在 `sm._task_group = None` 旁补 `sm._server_instances.clear()` 对齐 SDK 原语义 |
| 2 | ai_service/mcp_server.py | L182, L184 | LOW | 访问 FastMCP 私有属性（`mcp._session_manager` / `sm._task_group`）——对 mcp 1.26.0 内部实现强耦合；requirements `==` 锁定已缓解，但升级 SDK 时该函数可能静默失效 | 保持现状（适配必要性已实测确认）；在注释中补"升级 mcp 需复核本函数"提示，或后续观察官方是否提供公开 lifespan 接入点 |
| 3 | ai_service/mcp_server.py | L150（transport_security） | LOW | DNS rebinding 保护全局关闭——token 认证成为唯一安全边界；若未来有人移除 token 校验（或中间件被跳过），无 Host 校验兜底 | 保持现状（远程部署必需，代码注释已声明）；建议在 README 安全段补一句"远程暴露依赖 PW_MCP_TOKEN 为唯一边界" |
| 4 | ai_service/mcp_server.py | _make_ctx（L65-80） | INFO | 合成 ctx 含 history/scratchpad/add_note 三个字段——6 个暴露工具均不使用（generate_answer/note_to_self 未暴露，re_search 未暴露）；防御性形状 | 可保留（工具演进友好），也可按简单至上精简；不阻塞 |
| 5 | ai_service/mcp_server.py | _make_ctx identity（L74） | INFO | 所有 MCP 调用统一 identity="mcp"——不同 MCP client 共享同一记忆命名空间（与 web 用户 user_id/client_ip 隔离，不串扰）；单用户项目可接受，plan §0.11 既定设计 | 保持；如需多 client 隔离可后续引入按 token 派生 identity |
| 6 | ai_service/main.py | lifespan（L114-121） | INFO | fail-closed 是**全服务级**（/ai/rag/chat 等端点同样拒绝启动，非仅 MCP 端点）——plan 明确设计（对齐 module-053 fail-fast 先例）；运营影响：本地 .env 必须补 PW_MCP_TOKEN（changelog/README/project-context 均已说明，实测当前 .env 确实无该键） | 保持；协调者提交后需提醒用户补 .env |
| 7 | 文档 | plan WP-D"00-信息包" | INFO | plan 引用"00-信息包"文件在 docs/简历/ 中不存在（实际文件为 07-项目经历-精简版.md）——Developer 落地到 07 核心工作第 6 条（内容以 ADR-0018 面试话术为纲） | 合理替代，无需处理 |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| tool_registry.py / react.py / engine.py 一律不碰 | git diff ai_service/ 全量核对 | ✅ 零 diff |
| main.py 仅挂载 + 认证中间件 + import + lifespan 检查 | diff 逐段核对 | ✅ |
| config.py 仅加 mcp_token 字段 | diff 核对 | ✅ |
| requirements.txt 仅加 mcp 一行 | diff 核对（4 行含注释） | ✅ |
| 依赖仅 mcp 官方 SDK | requirements 全文件核对 | ✅ 无第三方 MCP 库 |
| 存量测试零改动 | git diff tests/ | ✅ conftest.py 亦零改动 |
| 不写 SSE 传输 | 代码审查 | ✅ 仅 Streamable HTTP |
| stdio 禁 print | grep mcp_server.py | ✅ 0 处 |

## 五、架构与代码质量评估

- **复用而非重造**：执行语义复用 AgentTool.run（15s 超时 + 降级哲学）、ctx 合成对齐 plan §0.11 既定方案、fail-closed 对齐 module-053 fail-fast 先例、lifespan 检查对齐 module-032 JWT 模式、版本适配点全部实测落注释——**无重造现成模式** ✓
- **单一事实源**：ToolRegistry 零改动，description/args_schema 动态透传（改 registry 描述 build_server 自动同步，单测验证）——无双份维护 ✓
- **分层**：MCP 纯适配层（mcp_server.py）+ 宿主挂载（main.py），无跨层/反向依赖；import 无环 ✓
- **安全**：token 常量时间比较 + 实时读配置 + 空 token 恒 401 双保险 + token 零日志；SQL/数据库面零新增（MCP 不落库，ADR-0018 决策 4③）✓
- **代码长度**：mcp_server.py 135 行功能代码（≤200 达标）；_mcp_auth_middleware 22 行（≤50 达标）✓
- **诚实边界**：Inspector GUI 不可开如实记录、真实 client 以官方 SDK 冒烟为证（不假装 Cursor 验证）、scripts/test_models.py 遗留 ERROR 如实标注不触碰——诚实标注贯穿 ✓

## 六、结论

**✅ Pass（进 Tester）**。WP-A~D 全部通过标准达成；全量 1102/0 独立复跑确认（+1 项 module-050 遗留收集 ERROR，与 module-066 同口径）；真实 uvicorn 401/401/200/307 四态 + fail-closed 启动拒绝 + 真实检索工具调用全部独立复测通过；schema 转换/截断/白名单/ctx 合成单测全覆盖；红线全守（tool_registry/react/engine/conftest 零 diff，依赖仅 mcp==1.26.0）。§三 7 项发现均为 LOW/INFO 非阻塞（SDK 私有属性耦合与 lifespan 复刻细节、DNS rebinding 关闭的边界声明、ctx 冗余字段、identity 命名空间、全服务级 fail-closed 运营约束、plan 文件引用偏差），不阻塞 Tester 验收。
