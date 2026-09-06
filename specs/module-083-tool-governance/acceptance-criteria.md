# 验收标准 — Module-083: 工具治理（schema 校验 / 幂等 / 工具级超时 / 高风险审批 / Agent 级最小权限）

> 依据：`plan.md` v1（2026-09-01）| 验收口径：全量 **1485 passed / 4 failed（module-028 proxies 环境性基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）** 新增 0 失败、**存量测试零改动** 红线

## 1. 功能验收

### 1.1 核心路径验收（WP-A args schema 校验）
- [ ] AC-1 校验前置：注册 schema 工具（如 `_SEARCH_SCHEMA`）调 `run({"top_k": "abc"}, ctx)` → 返回含 `"(工具 <名> 参数错误"` 的提示、底层 func **未被调用**（assert_not_called）、不进入重试分支（asyncio.wait_for 0 次调用）
- [ ] AC-2 合法 args 正常执行：func 被调用、结果原样返回（校验通过零开销语义）
- [ ] AC-3 **缺省回退契约保留**：`run({}, ctx)`（schema required 含 query）→ 不报参数错误，走工具内 `args.get("query") or ctx.query` 回退（零回归；校验 schema 的 required 已置空的直接证据）
- [ ] AC-4 **run 容忍 ctx=None**：`run({}, None)`（存量测试形态）→ 不抛 AttributeError，校验照常、幂等短路
- [ ] AC-5 非 dict args（如 list）→ 返回"参数应为 object"提示，不执行
- [ ] AC-6 requirements.txt 含 `jsonschema` 行（==4.26.0）；`python -c "from jsonschema import validate; print('ok')"` 通过

### 1.2 核心路径验收（WP-B 幂等：同参不重放）
- [ ] AC-7 `ReactContext.__init__` 新增 `executed_fingerprints: set[str] = set()` 字段（每请求独立，跨请求不共享）
- [ ] AC-8 只读检索 7 工具（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/re_search）同参二次调用 → 第二次返回 `"(该调用已执行过，结果见上文)"`，func 仅执行 1 次
- [ ] AC-9 参数键序无关：`{"query":"q","top_k":5}` 与 `{"top_k":5,"query":"q"}` 指纹一致 → 二次调用拦截（sort_keys=True 证据）
- [ ] AC-10 不同参数（query 或 top_k 变化）→ 不拦截，正常执行
- [ ] AC-11 **失败不记指纹可重放**：首次 func 抛异常（返回空串）→ 不记指纹 → 同参再次调用真实执行（与 module-073 重试语义自洽）
- [ ] AC-12 **超时不记指纹**：同参超时后再次调用真实执行
- [ ] AC-13 **排除清单**：generate_answer / verify_answer / note_to_self 同参二次 → 仍执行（不受幂等拦截）
- [ ] AC-14 **MCP 轻量 ctx / ctx=None 零拦截**：getattr 短路，无 executed_fingerprints 字段的 ctx 不幂等
- [ ] AC-15 073 重试交互：工具首次异常自动重试成功后 → 指纹只记 1 次（func 计数 2、同参三次调用被拦）

### 1.3 核心路径验收（WP-C 工具级超时）
- [ ] AC-16 `AgentTool(timeout=0.01)`：func sleep 超时 → 返回精确文案 `"(工具 <名> 执行超时)"`（**一字不改**），asyncio.wait_for 收到 timeout=0.01（monkeypatch wait_for 断言）
- [ ] AC-17 默认值：`AgentTool().timeout == settings.tool_default_timeout == 15.0`（config 是新工具默认值来源）；现有 10 工具注册后 timeout 全 15.0（零行为变化）
- [ ] AC-18 config.py 新增 `tool_default_timeout: float = 15.0`（`PW_TOOL_DEFAULT_TIMEOUT` 回退）
- [ ] AC-19 存量超时测试（test_agent_tools.py 精确文案断言）全绿——超时提示不含秒数

### 1.4 核心路径验收（WP-D 高风险审批：机制预留）
- [ ] AC-20 `AgentTool.__init__` / `register()` 新增 `approval` 字段，**默认 "auto"**；现有 10 工具全部 auto（`reg.list_tools()` 逐一核验）
- [ ] AC-21 **auto 工具零开销**：`run()` 路径 `_approval_allowed` 断言 0 次调用（monkeypatch 计数，不查库）
- [ ] AC-22 **required + 无 approved**：返回 `"(工具 <名> 需人工审批，调用申请已提交)"`、func 未执行、插入 pending 行（tool_name/args/status=pending/requester）
- [ ] AC-23 **pending 去重**：同 tool_name 已有 pending → 不重复插入
- [ ] AC-24 **approved 放行**：已有 approved 记录 → 正常执行（工具级放行，不校验 args 差异）
- [ ] AC-25 **DB 异常 fail-closed**：`_approval_allowed` 抛异常 → logger.warning + 拒绝执行（安全侧）
- [ ] AC-26 `GET /ai/tools/approvals`（?status 缺省 pending）：返回 `{code, msg, data:{approvals:[...]}}`，每条含 id/tool_name/args/status/requester/requested_at/decided_at；status=approved/rejected 过滤生效
- [ ] AC-27 `POST /ai/tools/approvals`：`{id, action:"approve"}` → status=approved + decided_at 非空；`"reject"` 同理；**非法 action / id 不存在 / 已处理** → code 1 提示不崩
- [ ] AC-28 DDL 幂等：`ensure_approval_requests_table()` 二次执行不报错（拆 DDL 逐条断言，对齐 test_tool_call_logs 手法）+ `init_db()` 挂接点存在

### 1.5 核心路径验收（WP-E Agent 级最小权限）
- [ ] AC-29 `react_agent` / `react_loop` / `execute_tool_with_log` 新增 `allowed_tools: Optional[set[str]] = None` 参数
- [ ] AC-30 白名单外工具（如 `allowed_tools={"search_knowledge"}` 时调 `search_fts`）→ 拒绝执行、func 未执行、`result_ok=false`、提示含"权限白名单"、喂回 LLM
- [ ] AC-31 白名单内工具正常执行
- [ ] AC-32 **None = 全量**：存量 `react_agent(...)` 调用（不传新参）零回归全放行
- [ ] AC-33 **langgraph 零改动**：langgraph_react.py 调用点不传新参（git diff 核验该文件零 diff）；其路径继续全量放行
- [ ] AC-34 透传链路：`react_agent(allowed_tools=...)` → `react_loop` → `execute_tool_with_log` 生效（集成断言一次）

## 2. 边界条件验收
- [ ] AC-35 **校验边界**：`top_k: 1.0`（float 整数字面）被 jsonschema 严格 integer 判定拒绝——如实标注为已知边界；如 module-085/评估发现 LLM 周期传浮点整数字面，届时加"整数字面规整"兜底（本模块不加，纳入 changelog 备注）
- [ ] AC-36 **幂等边界**：指纹集合每请求独立（两个 ReactContext 不共享拦截）；过滤后消息 `"(该调用已执行过，结果见上文)"` 非空且不在 `_EMPTY_RESULT_MARKERS` → 可能触发 `_retrieval_hit`，但首次真实执行已推进阶段（advance_phase 单向前进）→ 无死锁（集成：幂等命中后循环仍可正常结束）
- [ ] AC-37 **审批边界**：required 工具在 generation 阶段同样过审批闸（_precheck 先于阶段守门——审批在 run 内、阶段在 execute_tool_with_log，两闸顺序不冲突）；auto 工具不受任何影响
- [ ] AC-38 **超时边界**：config 值 0/负数语义未定义（默认 15.0 不触发；Developer 不得为此加隐式规整，如加了须 changelog 说明）
- [ ] AC-39 **空 args 边界**：`run({}, ctx)` → 校验通过（缺省回退）、幂等指纹 `sha256(name|{})` 正常、审批 auto 短路——三层全兼容

## 3. 异常场景验收
- [ ] AC-40 **jsonschema 内部异常**（非 ValidationError，如版本差异）→ fail-open 放行执行 + logger.warning（不阻断工具链路）
- [ ] AC-41 **args 非 JSON 序列化**（罕见）→ `_fingerprint` 返回 None 跳过幂等，执行不受阻
- [ ] AC-42 **审批端点并发/脏数据**：POST 已处理 id → code 1 提示不崩；status 枚举外值不影响（只认 approved）
- [ ] AC-43 **MCP 路径回归**：mcp_server.py:90 复用 run()——校验（合法参数零变化）/超时（15s 围栏不变）/审批（auto 短路）/幂等（轻量 ctx 短路）全兼容，`test_mcp_server.py` 存量全绿
- [ ] AC-44 **LLM 循环自愈**：校验失败/审批拒绝/幂等命中的提示文本作为 tool 结果消息喂回 LLM，循环继续（不抛异常、不中断 SSE 事件流）

## 4. 非功能验收

### 4.1 向后兼容零回归
- [ ] AC-45 全量 pytest = **1485 passed / 4 failed（module-028 proxies 基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）——新增 0 失败**
- [ ] AC-46 存量测试零改动：test_agent_tools.py（62 项含 3 处 AgentTool.run 直接断言）、test_tool_retry_dedup.py（24 项）、test_tool_call_logs.py、test_mcp_server.py 全过
- [ ] AC-47 **行为红线逐字不变**（git diff / 局部单测实证）：超时精确文案、失败返回空串、result_ok 语义（066）、tool_count/phase_count 预算计数、tool_call_logs 表结构一字不改
- [ ] AC-48 现有 10 工具：approval 全 auto、timeout 全 15.0、allowed_tools 全 None、幂等仅拦"同参二次只读检索"——生产默认路径行为零变化

### 4.2 性能验收
- [ ] AC-49 正常路径零开销：auto 工具 0 次 DB 查询；校验 = 纯函数 O(args)；`{**schema, "required": []}` 每次浅拷贝（KB 级）可忽略；幂等 = 内存 set + 一次 sha256
- [ ] AC-50 审批路径（仅 required 工具，当前不触达）每次调用 1 次 SELECT + 至多 1 次 INSERT——机制预留不构成现网开销

### 4.3 安全验收
- [ ] AC-51 审批 SQL 全参数化（:tool_name / :status / :id），无拼接（semgrep 扫描通过）
- [ ] AC-52 审批 DB 异常 fail-closed（拒绝执行）+ fail-open 原则只用于观测/落库路径（tool_call_logs），两类语义不混淆（带注释可辨）
- [ ] AC-53 jsonschema 校验不泄露内部细节：错误提示只含参数路径（e.message），不含堆栈/密钥

### 4.4 代码质量验收（铁律）
- [ ] AC-54 生产功能代码 ≤200 行（预估 ~139；超限须按 plan §7 先例晒对照表 + 申请 GATE_MAX_MODULE_LINES 放宽）；**测试代码不计入**
- [ ] AC-55 方法 ≤50 行：run() 拆 _precheck/_execute 后达标；execute_tool_with_log 守门叠加后 ≤50（超限提取辅助）；public/导出方法有 docstring
- [ ] AC-56 无空 catch/吞异常：所有 except 带 logger + 注释（fail-open/fail-closed 性质）；业务提示统一返回文本，不抛业务异常
- [ ] AC-57 变更文件范围：修改 tool_registry.py / react.py / config.py / database.py / main.py / requirements.txt + 新增 tests/agent/test_tool_governance.py；**mcp_server.py / langgraph_react.py / engine.py / router.py 零 diff**（git diff 核验）
- [ ] AC-58 无新 ADR（默认，决策记录入 changelog；协调者裁定需 ADR 则后补）

## 5. 可运行验证命令表

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量回归 | `cd ai_service && python -m pytest -q` | 1485 passed / 4 failed（proxies 基线）/ 3 skipped / 1 error（陈旧脚本），**新增 0 失败** |
| 定向单测 | `cd ai_service && python -m pytest tests/agent/test_tool_governance.py -q` | 全部 passed（预计 ~30 项） |
| 受影响存量 | `cd ai_service && python -m pytest tests/agent/test_agent_tools.py tests/agent/test_tool_retry_dedup.py tests/agent/test_tool_call_logs.py tests/test_mcp_server.py -q` | 全部 passed（存量零改动实证） |
| 依赖冒烟 | `python -c "from jsonschema import validate, ValidationError; print('jsonschema ok')"` | `jsonschema ok`（4.26.0） |
| config 冒烟 | `python -c "from src.config import settings; print(settings.tool_default_timeout)"` | `15.0` |
| DDL 幂等 | `python -m pytest tests/agent/test_tool_governance.py -k "approval or ddl" -q` | 二次执行 ensure 不报错用例 passed |
| 红线核验 | `git diff --stat` | 6 生产文件修改 + 1 测试新增；mcp/langgraph/engine/router 零改动 |
| 端点冒烟（可选，Tester） | 启动服务后 `curl http://127.0.0.1:8001/ai/tools/approvals` | `{"code":0,"msg":"success","data":{"approvals":[]}}`（空表 200） |

## 6. 验收结论
- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-09-01
- 结论: [ ] 通过 / [ ] 不通过
- 备注: Tester 重点关注 AC-8/11/15（幂等机制 + 073 交互）、AC-21/22（审批短路/闸）、AC-30/33（权限守门 + langgraph 零改动）、AC-45 全量零新增失败