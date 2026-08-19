# Module-067 测试报告 — MCP 集成（ToolRegistry → 标准 MCP Server，ADR-0018）

> Tester：2026-08-17 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：✅ Pass（3 LOW + 4 INFO 非阻塞，见 review-report.md）
> **验收结论：✅ 通过（全量 1102/0 独立复跑 + 27 新增全绿 + 真实 HTTP/stdio 双传输 E2E 独立复验）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（`tests/`，Tester 独立复跑） | **1102 passed / 0 failed（149.87s，43 warnings）** = 1075 基线 + 27 新增 |
| 新增单测 | `tests/api/test_mcp_server.py` **27 项全绿**（独立运行 51.10s） |
| 存量测试改动 | **零改动**（`git diff ai_service/tests/` 空；conftest.py 亦零 diff；唯一新增为未跟踪新文件 test_mcp_server.py） |
| 单测 mock 性 | 全 mock 零 LLM/DB（TestExecution/TestHttpAuth 全 mock 工具函数与 settings；真实 DB 只在 §三冒烟） |
| warnings | 与基线同源（Redis setex 弃用 / SAWarning 连接清理，非本模块引入） |
| 收集 ERROR | 根目录 `python -m pytest -q` 时 1 项预存 ERROR：`scripts/test_models.py::test_model`（fixture 'label' not found，文件 git diff 零改动，module-050 遗留，module-066 review-report §一 同口径）；项目惯例跑 `pytest tests/` 不受影响，Tester 复跑 tests/ 全绿无 ERROR |
| fail-closed 与存量测试 | conftest.py 无 mcp_token/TestClient 处理（grep 零命中），1102 全过证明存量测试无触发 lifespan 者（全 ASGITransport，与 changelog 声明一致） |

## 二、新增单测抽查（与 changelog 声明逐项核对，27 项全过）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| build_server 注册遍历（恰 6 只读、集合与 READ_ONLY_TOOLS 相等） | ✅ | test_default_registers_exactly_read_only_tools |
| 只读过滤（generate/verify/re_search/note_to_self 零暴露） | ✅ | test_non_read_only_tools_excluded |
| 显式 groups 过滤（generation 组恰 4 工具含 re_search 双组） | ✅ | test_explicit_groups_filters_by_group |
| description 透传（改 registry 描述 build_server 自动同步） | ✅ | test_description_passthrough |
| schema 转换三变体（_SEARCH：query 必填 string + top_k 可选 anyOf[integer,null]；_ENTITY：仅 query；_MEMORY：query + top_k 可选） | ✅ | test_schema_search/entity/memory_variant |
| 未知 type → str 兜底 | ✅ | test_schema_unknown_type_falls_back_to_str |
| properties default 生效（非必填） | ✅ | test_schema_schema_default_applied |
| 截断 ≤2000 原样 / 空串原样 / >2000 截断 + 后缀（长度精确 2000+suffix） | ✅ | TestTruncate 3 项 |
| 执行结果透传 + ctx 合成（query 透传、identity="mcp"、ctx.memory 可写） | ✅ | test_call_returns_tool_result / test_ctx_query_and_identity / test_ctx_memory_writable |
| 失败包装（run 返回空串 → "（工具执行失败）"不抛裸异常） | ✅ | test_failure_returns_readable_message |
| None 值参数剔除（int(args.get('top_k',5)) 缺省语义不被 int(None) 破坏） | ✅ | test_optional_param_none_dropped |
| 缺必填参数 → MCP 参数校验 ToolError（可读错误非 500） | ✅ | test_missing_required_param_rejected |
| top_k 类型错误 → ToolError 不崩溃 | ✅ | test_wrong_type_rejected |
| _make_ctx 形状（query/identity/docs/add_docs/memory 字段） | ✅ | test_make_ctx_shape |
| HTTP 认证：无 token 401 / 错 token 401（含 401 JSON message）/ 对 token initialize 200（serverInfo=personal-knowledge-kb，验证 session 任务组就绪）/ /ai/mcp 无尾斜杠 307 / 空 token 恒 401 / 改 token 立即生效 | ✅ | TestHttpAuth 6 项 |
| fail-closed：lifespan 空 token 启动即抛 RuntimeError（match "PW_MCP_TOKEN"） | ✅ | TestFailClosed::test_lifespan_raises_without_token |

## 三、冒烟复跑（Tester 独立执行，未采信 changelog 数字）

### 3.1 fail-closed（真实 uvicorn，无 PW_MCP_TOKEN）

`python -m uvicorn main:app`（无 token）→ 启动即抛 **RuntimeError "PW_MCP_TOKEN 未设置：MCP HTTP 模式 fail-closed 拒绝启动（请在 .env 配置）"**，`ERROR: Application startup failed. Exiting.`（exit 3）——服务拒绝启动，与 changelog 逐字一致。

### 3.2 HTTP 四态（真实 uvicorn 127.0.0.1:8017，PW_MCP_TOKEN=smoke-token-067）

| 验证项 | 结果 |
|--------|------|
| GET /ai/mcp/ 无 token | **401** |
| POST initialize 错 token（Bearer wrong） | **401** |
| POST initialize 正确 token | **200**，`serverInfo: {name: "personal-knowledge-kb", version: "1.26.0"}`（JSON-RPC 握手完整返回，无 version kwarg 适配点实证） |
| GET /ai/mcp（无尾斜杠） | **307 → http://127.0.0.1:8017/ai/mcp/**（-MaximumRedirection 0 直测） |

### 3.3 真实 MCP client 全会话（官方 SDK，HTTP 端点，Tester 独立编写脚本）

官方 `mcp.client.streamable_http.streamablehttp_client` + `ClientSession` 连真实 `http://127.0.0.1:8017/ai/mcp/`（Bearer smoke-token-067）：

```
HTTP TOOLS: ['extract_entities','recall_memory','search_fts','search_graph','search_knowledge','search_vector']
HTTP 只读核对: 恰 6 工具，4 个非只读零暴露
HTTP RETURN_LEN: 456
HEAD: [1] overview > 已发布日报 (score=1.0) | 6 | 2026-07-16 | Java 线程池 ThreadPoolExecutor 核心参数与工作原理 | ...
HTTP session smoke PASS
```

- **tools/list 恰 6 只读** + generate/verify/re_search/note_to_self 零暴露（真实 HTTP 会话核对）；
- **call_tool search_knowledge 真实检索**返回 2 篇命中文档（"6-Java线程池ThreadPoolExecutor核心参数与工作原理" score=1.0 等，真实 PG）；
- 该结果同时证明 **Mount 不转发 lifespan 的手动任务组修复成立**（完整会话 initialize → list_tools → call_tool 三阶段全通，非仅握手）；
- 此冒烟比 changelog 记录（HTTP 仅握手 + stdio 全调用）更强：官方 SDK 客户端走完整 HTTP 会话协议。

### 3.4 stdio 路径真实工具调用（build_server(registry).call_tool，与 stdio 工具执行同代码路径）

| 尝试 | 结果 |
|------|------|
| 第 1 跑 search_knowledge("Java 线程池核心参数", top_k=2) | deepseek 限流/慢响应（>15s）→ 工具返回 **"（工具 search_knowledge 执行超时）"**（真实降级路径实证：15s 超时 + 可读文案，非裸异常） |
| 第 2 跑同参数 | **LEN=456 真实结果**（与 changelog 记录数字一致），截断未触发（<2000 原样返回——真实 passthrough 行为实证） |
| top_k=5 / top_k=10 | LEN=1388 / 1794，均 <2000 原样返回；本数据集文档摘要紧凑，**真实截断未被自然触发**（边界由单测 3 项精确覆盖，非缺陷） |

## 四、实现抽查（与 changelog 一致，Tester 独立核对）

| 项 | 抽查结果 |
|----|----------|
| READ_ONLY_TOOLS 显式 6 名白名单（frozenset，mcp_server.py:39-46） | ✅ 与 AC §1.1 名单逐一相等；不按 group 过滤（检索组 7 含 re_search 双组，plan §0.2 事实修正落地） |
| build_server 动态注册（groups=None 白名单 / 显式 groups 按组） | ✅ 单测 + 真实 registry 独立核对 |
| exec 参数模型（必填排前可选排后 / None 剔除 / 未知 type→str） | ✅ 源码核对 + 单测 5 项 + Reviewer 边界实测（零 properties schema） |
| 执行走 AgentTool.run（15s 超时 + 降级） | ✅ 源码核对 + 单测 + §3.4 真实超时实证 |
| ctx 轻量合成（SimpleNamespace，不构造 ReactContext） | ✅ 源码核对 + 单测 3 项 |
| 截断 `_truncate_result` 2000 + 固定后缀 | ✅ 单测 3 项精确边界 |
| main.py 挂载 + 认证中间件（hmac.compare_digest 常量时间 / 每请求实时读 / 空 token 恒 401） | ✅ diff 核对（-6/+26 行级）：import hmac + mount + 中间件 + lifespan 检查 + 任务组 yield 前后进入退出；auth/expected 同 bytes 类型无类型异常 |
| fail-closed 放 lifespan 不放 import 期 | ✅ diff 核对 + §3.1 真实启动拒绝 + 1102 存量全过（lifespan 不触发） |
| mcp_http_lifespan 任务组手动进入（Mount 不转发 lifespan 的修复） | ✅ §3.3 完整 HTTP 会话三阶段实证 |
| 零 print / 无 SSE 传输 | ✅ grep mcp_server.py 0 处 print；SSE 12 处命中全在 main.py 既有 chat 流式端点（/ai/rag/chat 相关），mcp_server.py 零命中 |
| 代码长度 | ✅ mcp_server.py 163 行总计（功能代码 ≤200 达标，Reviewer 实测 135）；_mcp_auth_middleware ~22 行（≤50） |
| 红线 | ✅ git diff：tool_registry.py / react.py / engine.py / conftest.py 零 diff；config.py 仅 +mcp_token；requirements.txt 仅 +mcp==1.26.0；依赖仅官方 SDK |
| 文档 | ✅ CONTEXT.md 严格 +2 行零删（ADR-0018 行 + module-067 行，diff 独立核对）；README 环境变量表 + MCP 能力段；ADR-0018 状态 ✅ 已实施 + 验收标准逐条标注 |

## 五、观察与诚实声明（非阻塞）

1. **changelog 单测分类计数 29 vs 实际 27 个测试函数**：changelog §四分类计数加总为 29（"只读过滤 2"/"schema 转换 6"），实际测试函数为 27（只读过滤 1 / schema 5，其余分类按断言级口径计数）——总数量 27 一致，系分类口径粒度差异，非功能问题，建议后续 changelog 以函数数为准。
2. **真实截断未被自然触发**：本数据集检索摘要紧凑（top_k=10 实测最大 1794 < 2000），截断路径由单测 3 项精确覆盖（≤2000 原样 / 空串 / >2000 截断 + 后缀长度精确断言）+ §3.4 真实 passthrough 实证，属数据特性非缺陷。
3. **deepseek 限流抖动如实记录**：§3.4 第 1 跑 15s 超时系外部 API 延迟（已知 deepseek 429 风暴，plan §6 预警），第 2 跑即恢复；超时降级路径反而被真实演示（可读文案，非裸异常）。
4. **真实截断/长文档场景**：如需真实超 2000 字工具返回的端到端证据，可后续构造长文档后补跑（非本模块阻塞）。
5. **curl 与 307**：PowerShell Invoke-WebRequest 默认跟随重定向（首跳 307 显示为 401），用 -MaximumRedirection 0 直测确认 307 → Location 正确。

## 六、AC 逐条对照（40 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| 1.1-1 build_server 注册遍历 | ✅ | 单测 + 真实 registry 集合一致 |
| 1.1-2 默认恰好 6 只读 | ✅ | 单测 len==6 + §3.3 HTTP tools/list 恰 6 |
| 1.1-3 只读过滤（4 非只读零暴露） | ✅ | 单测 + §3.3/§3.4 真实核对 |
| 1.1-4 description 透传 | ✅ | 单测（改 registry 描述自动同步） |
| 1.1-5 args_schema → 参数模型 | ✅ | 单测三变体 + 未知 type + default + anyOf 口径 |
| 1.1-6 stdio 入口 | ✅ | §3.4 build_server 调用（stdio 同路径）+ 真实超时/成功双实证；Inspector GUI 沙箱不可开（changelog 如实记录） |
| 1.2-1 /ai/mcp 挂载 | ✅ | §3.2/3.3 真实服务非 404（401/200 均达端点） |
| 1.2-2 无 token → 401 | ✅ | 单测 + §3.2 真实 curl 同口径 |
| 1.2-3 错 token → 401 | ✅ | 单测 + §3.2 真实 |
| 1.2-4 正确 token → 200 | ✅ | 单测 + §3.2 真实 initialize 200 + §3.3 全会话 |
| 1.2-5 fail-closed（lifespan raise + 中间件恒 401） | ✅ | 单测 2 项 + §3.1 真实启动拒绝 |
| 1.2-6 真实 MCP client 连通 | ✅ | §3.3 官方 SDK HTTP 全会话（比 changelog 握手口径更强） |
| 1.3-1 工具返回截断 | ✅ | 单测 3 项精确边界 + §3.4 真实 passthrough（真实数据集未自然超限，见 §五.2） |
| 1.3-2 工具内部防御保留 | ✅ | 源码（run 透传）+ 单测失败包装 |
| 1.3-3 空参数/缺必填 | ✅ | 单测 ToolError 可读错误 |
| 1.3-4 top_k 类型错误 | ✅ | 单测 ToolError 不崩溃 |
| 1.3-5 超时/失败降级 | ✅ | 单测 + §3.4 真实 15s 超时实证 |
| 1.4-1 底层失败提示文案 | ✅ | 单测（run 返回空串包装） |
| 1.4-2 token 运行时变更 | ✅ | 单测 test_token_change_takes_effect_immediately |
| §2-1 只读原则 | ✅ | 单测 + §3.3 真实核对 |
| §2-2 fail-closed | ✅ | §3.1 真实拒绝启动 |
| §2-3 token 不落日志 | ✅ | 中间件零日志输出（源码核对） |
| §2-4 stdio 零认证边界声明 | ✅ | README + config 注释 + changelog 如实声明 |
| §2-5 日志走 stderr | ✅ | grep 0 print（logging） |
| §2-6 不写 SSE | ✅ | grep mcp_server.py 零命中；仅 Streamable HTTP |
| §3-1 单一事实源 | ✅ | tool_registry.py 零 diff |
| §3-2 红线遵守 | ✅ | git diff 核对（main/config/requirements 仅声明范围） |
| §3-3 新增依赖仅 mcp | ✅ | requirements diff 仅 mcp==1.26.0 |
| §3-4 代码长度 | ✅ | 163 行总计 / 功能 135 ≤200；中间件 22 ≤50 |
| §3-5 命名规范 | ✅ | snake_case / 常量全大写 / 无未使用 import（Reviewer + Tester 目检） |
| §3-6 参数化防御 | ✅ | hmac.compare_digest 常量时间 |
| §4-1 新增单测 ≥15 项 | ✅ | 27 项全绿（≥15 达标） |
| §4-2 存量测试零改动 + 全量 | ✅ | tests/ 1102/0 独立复跑；git diff tests/ 空 |
| §4-3 真实冒烟 | ✅ | stdio 真实检索 + HTTP 401/401/200/307 + fail-closed + §3.3 官方 SDK 全会话 |
| §5-1 changelog | ✅ | 如实记录（适配点/冒烟/诚实边界/未达成项） |
| §5-2 README | ✅ | PW_MCP_TOKEN 表 + MCP 能力段 |
| §5-3 CONTEXT.md 只增不删 | ✅ | Tester diff 核验 +2 行零删（已备份） |
| §5-4 ADR-0018 状态 ✅ | ✅ | 已实施 + 逐条核对标注 |
| §5-5 00-信息包（07 替代） | ✅ | 07-项目经历-精简版.md 核心工作第 6 条（plan 文件引用偏差 Reviewer INFO-7 已记录） |
| §5-6 memory 三文件 | ✅ | project-context / file-index / agent-activity-log（Reviewer 核验） |
| §6 验证命令表 | ✅ | 全部按命令复跑通过（§一/§三） |

**合计：40 项全通过（无未达标项；§五 3 项观察均为非阻塞诚实记录）。**

## 七、结论

**验收通过。** 关键验证点：
1. 全量 1102/0 全绿（149.87s），存量测试零改动（git diff tests/ 空，conftest 亦零 diff）；
2. 新增 27 项单测全绿，覆盖 changelog 声明全部点（注册遍历/只读过滤/schema 三变体/截断/执行 8/HTTP 认证 6/fail-closed）；
3. fail-closed 真实启动拒绝（RuntimeError，exit 3）；
4. HTTP 真实四态独立复测（无/错 token 401、正确 200、无尾斜杠 307）；
5. **官方 SDK MCP 客户端完整 HTTP 会话 E2E 独立通过**（initialize → tools/list 恰 6 只读 → call_tool 真实检索 456 字符）——比 Developer/Reviewer 的握手口径更强；
6. 真实工具调用超时降级被真实演示（deepseek 延迟 >15s → "（工具 search_knowledge 执行超时）"可读文案），第二跑恢复真实检索；
7. CONTEXT.md 只增不删（+2 零删）、README/ADR-0018/07 简历/记忆三文件闭环。

非阻塞观察：changelog 分类计数粒度差异（29 vs 27 函数）；真实数据集未自然触发截断（边界由单测覆盖）；deepseek 外部抖动影响首跑耗时。

**模块状态：✅ 验收通过（待 Developer 提交推送后 team-lead 收口）**
