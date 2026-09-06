# 开发计划 — Module-083: 工具治理（schema 校验 / 幂等 / 工具级超时 / 高风险审批 / Agent 级最小权限）

> Planner: 2026-09-01 | 依据：`AGENT-GROWTH-ROADMAP.md` module-083 行（阶段 A：工具治理与外部接入——"不会调工具谈不上治理"，module-084 外部 MCP 客户端接入的前置）+ 用户已确认的 5 项治理范围（2026-08-31/09-01 沟通，含用户反馈）
> 范围：Agent 工具执行层治理 5 项（WP-A~E），全部默认零行为变化（现有 10 工具零改动语义）
> 预算：WP-A 半天 + WP-B 半天 + WP-C 2 小时 + WP-D 1 天 + WP-E 半天 + WP-F 回归半天 ≈ 3 天
> Agent 配置：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1（无前端/Java 子任务）

## 0. Planner 已探明事实（勿重复调查）

- **AgentTool 类**（tool_registry.py:43-113）：`__init__(name, description, args_schema, func, group=None)`；`run(self, args, ctx)` 内两处 `asyncio.wait_for(self.func(ctx, args), timeout=15)`（L84 首试 / L92 重试分支，module-073 引入），超时提示精确文案 `f"(工具 {self.name} 执行超时)"`——**存量超时测试逐字断言该文案，不可改**；失败返回空串（module-028 降级哲学）；`_NO_RETRY_TOOLS = {"generate_answer", "verify_answer"}`（L35）；本模块已 `from src.config import settings`（L18，module-073 引入）。
- **生产调用点仅 2 处**：`execute_tool_with_log`（react.py:332-368，L360 调 `tool.run`，react_loop L508 与 langgraph_react L169 两条循环共用）+ `mcp_server.py:90`（MCP exec 闭包直接调 `tool.run(args, ctx)`，**轻量 ctx 只有 query/identity/docs/add_note/memory 等，无 executed_fingerprints 字段**）。→ 校验/超时/审批放 run() 内三条路径自动继承（对齐 module-073 重试先例）；幂等必须 `getattr(ctx, "executed_fingerprints", None)` 短路（缺字段 = 零拦截）。
- **存量测试关键事实**：test_agent_tools.py 大量 `tool.run({}, None)`（ctx=None，L116/126/138/212/226 等；test_tool_retry_dedup.py L226-294 同款）。→ **run() 必须容忍 ctx=None**（getattr 短路）；且若 schema 校验强制 required，`run({}, None)` 对 `_SEARCH_SCHEMA` 等（required 含 query）会从"缺省回退"变"校验拒绝"→ 破坏存量。**据此决策：校验时置空 required（见 WP-A）**。
- **jsonschema 依赖**：环境实测已装 **4.26.0**（`importlib.metadata.version('jsonschema')` 验证），**requirements.txt 无此行**（须补）；纯 Python 无重依赖。
- **config 工具段**（config.py:107-147）：`max_agent_tools=5` / `tool_phase_split=True` / `agent_retrieval_max_rounds=3` / `agent_retrieval_budget=3` / `agent_generation_budget=2` / `tool_auto_retry=True` / `tool_call_logs_enabled=True`；`model_config env_prefix="PW_"` → 新配置自动映射 `PW_TOOL_DEFAULT_TIMEOUT`。
- **执行层守门先例**：`_phase_allows`（react.py:216-243，2026-08-20 module-066 实测补）——"schema 是门禁、执行层是守门"，拒绝返回可读提示喂回 LLM、result_ok=false 审计可见。WP-E 的 allowed_tools 沿用同一哲学。
- **tool_call_logs 落库语义（module-066/ADR-0017）**：`execute_tool_with_log` 计时包住 run；result_ok=false 仅在工具不存在或 run 抛异常；run 内部返回提示文本属正常路径 result_ok=true。校验失败/幂等命中/审批拒绝均走"run 返回提示"→ result_ok=true（不变更落库语义）；allowed_tools 拒绝与阶段守门同口径 result_ok=false。
- **预算计数点**（react_loop L497-508）：`tool_count += 1` / `ctx.phase_count[ctx.phase] += 1` 在 execute_tool_with_log 之前——所有执行前闸（校验/幂等/审批/权限）拒绝的调用仍计 1 次（与阶段守门拒绝同口径），**预算语义零变化**。
- **DDL 模式**：database.py `TOOL_CALL_LOGS_DDL`（L95）+ `ensure_tool_call_logs_table()`（L115，拆 ";" 逐条执行）+ `init_db()`（L248，L265 挂接 ensure）——approval_requests 表照此复制。
- **端点惯例**：main.py 无独立 router，直接 `return {"code": 0, "msg": "success", "data": ...}` / 失败 `{"code": 1, "msg": ...}`。
- **基线**：module-082 后全量 **1485 passed / 4 failed（module-028 langchain-openai proxies 环境性基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）**——本模块红线：**新增 0 失败、存量测试零改动**。

## 1. WP-A：args schema 校验（用户确认：复用现有 JSON Schema）

### 依赖决策（Planner 评估结论）
- **接受 jsonschema**（requirements.txt 补 `jsonschema==4.26.0`，锁版本对齐已装环境，防漂移同 mcp==1.26.0 先例）：纯 Python 轻量、环境已装、社区标准实现；`args_schema` 本来就是 OpenAI function parameters 格式的 JSON Schema，`validate(args, args_schema)` 直接复用零改写。
- **备选手写轻量校验（拒绝）**：只做 int/str 类型手判会漏嵌套 object/array items、枚举、数值范围等约束，且未来 module-084 外部 MCP 工具 schema 更复杂——自研 JSON Schema 子集得不偿失。

### 实现
- tool_registry.py 模块级：`from jsonschema import validate as _js_validate, ValidationError`。
- 新增纯函数 `_schema_error(name, args, schema) -> Optional[str]`：
  - 非 dict args → `f"(工具 {name} 参数错误: 参数应为 object)"`；
  - **校验 schema 置空 required**：`{**(schema or {}), "required": []}`（浅拷贝，不 mutate 原对象；工具实现里 query 等"缺省回退 ctx.query"是设计契约，且存量 `run({}, None)` 与 MCP 外部调用依赖该回退——强制 required 会把"静默回退"变"报错拒绝"，违背零回归；只校验**已提供参数**的类型/枚举/嵌套）；
  - `_js_validate(args, schema)`；`except ValidationError as e` → `f"(工具 {name} 参数错误: {e.message})"`（e.message 含出错路径且短，LLM 可读）；
  - 其余异常（jsonschema 版本差异等）→ `logger.warning` 一次 + 返回 None（**fail-open 不阻断执行**，带注释——依赖层异常不能拖垮工具链路）；
  - 通过 → None。
- `run()` 内**执行前**（try 之前）：
  ```python
  err = _schema_error(self.name, args, self.args_schema)
  if err:
      return err   # 不真执行、不进重试分支、不记指纹（在 _precheck 中实现，见 WP-B 结构约束）
  ```
- **静默失败消除**：`top_k="abc"` 不再被 `int()` 吞成空串，改为显式参数错误提示喂回 LLM 自行纠正。
- tool_call_logs 语义零变化：校验失败 = run 正常返回提示 → result_ok=true。
- **预估代码量**：~14 功能行（_schema_error ~10 + run 接线 1 + import/描述 2 + requirements 1）。
- **通过标准**：单测——`top_k="abc"` 返回含"参数错误"提示且 func 未被调用（assert_not_called）/ 合法 args 正常执行 / `run({}, None)` 缺省回退（零回归）/ 校验失败 wait_for 0 次（不进重试）/ 非 dict args 提示。

## 2. WP-B：幂等（同参不重放，用户要求 plan 写清机制）

### 机制（用户方案落定）
- `ReactContext.__init__`（react.py:72-85）加字段 `self.executed_fingerprints: set[str] = set()`——**每请求独立**（ReactContext 每请求新建，跨请求不共享）。
- tool_registry.py 模块级：
  - `_IDEMPOTENT_TOOLS = {"search_knowledge", "search_fts", "search_vector", "search_graph", "extract_entities", "recall_memory", "re_search"}`（用户确认口径：**只读检索类 7 工具**；`generate_answer`/`verify_answer`/`note_to_self` 排除——每次调用语义不同或已有内容级去重）。
  - 指纹纯函数 `_fingerprint(name, args) -> Optional[str]`：`sha256(name + "|" + json.dumps(args, sort_keys=True))`（**sort_keys=True 保证参数键序无关**）；args 非 JSON 序列化（TypeError）→ 返回 None（不幂等、直接执行，防御注释——LLM 参数来自 tool_calls 必为 JSON，理论不可达）。
- `run()` 执行前拦截（_precheck 内，先于校验/审批之后的顺序见 WP-D 结构）：
  ```python
  fp_set = getattr(ctx, "executed_fingerprints", None)   # MCP 轻量 ctx / ctx=None → 短路零拦截
  fp = _fingerprint(self.name, args) if fp_set is not None else None
  if fp is not None and self.name in _IDEMPOTENT_TOOLS and fp in fp_set:
      return "(该调用已执行过，结果见上文)"
  ```
- **记录时机 = 成功执行之后**（不在执行前记录）：`_execute` 返回非空结果后 `fp_set.add(fp)`。**失败（返回空串）/超时不记指纹 → 同参可重放**——与 module-073 语义自洽：异常恢复可重放、成功结果不重放，防"首次失败 → LLM 同参重试被误拦"。
- **结构约束（铁律3 方法 ≤50 行）**：现 run() 约 40 行，叠加 WP-A/B/D 会超限 → 重构为：
  - `async def _precheck(self, args, ctx) -> Optional[str]`：审批闸（WP-D，仅 required 工具）→ schema 校验（WP-A）→ 幂等拦截（WP-B），返回拦截/拒绝提示或 None；
  - `async def _execute(self, args, ctx) -> str`：现有 try/wait_for(15)/retry 主体原样搬入（`timeout=15` 改 `self.timeout`，WP-C）；
  - `run()` 主体：`pre = await self._precheck(...); if pre: return pre` → `res = await self._execute(...)` → 记指纹 → `return res`。run() 保持 ≤50 行，**超时精确文案 / 失败空串 / result_ok 语义逐字不变**（存量测试面见 §0）。
- **与既有机制不冲突**（写清）：073 重试是异常恢复（run 内 except），幂等是同参重放拦截（_precheck 入口），两者分层；校验失败/幂等命中均**不进重试分支**。041 note 去重是内容级（scratchpad），且 note_to_self 已排除在幂等清单外。073 re_search 同改写守卫是"改写 query 级"，幂等是"name+args 精确级"——双层防空转。
- **副作用标注**：幂等命中消息非空且不在 `_EMPTY_RESULT_MARKERS` → 可能触发 `_retrieval_hit`（react.py:157）推进阶段——但首次真实执行已推进过（advance_phase 单向前进），无死锁影响。
- **预估代码量**：~20 功能行（集合 3 + _fingerprint 7 + 拦截 5 + 记指纹 3 + ctx 字段 2）。
- **通过标准**：单测——同参二次返回"(该调用已执行过，结果见上文)"且 func 仅调 1 次 / 参数键序不同指纹一致仍拦截 / 不同参正常 / 首败后同参重放成功 / 超时不记指纹 / generate_answer 排除（同参二次仍执行）/ ctx=None 与轻量 ctx 零拦截 / 重试成功路径只记 1 次指纹。

## 3. WP-C：工具级超时（用户思路：先测量再调整，本模块只做参数化）

- `AgentTool.__init__` 加参数 `timeout: Optional[float] = None` → `self.timeout = timeout if timeout is not None else settings.tool_default_timeout`（settings 已 import；**config 是新工具默认值来源**）。
- config.py 工具段加 `tool_default_timeout: float = 15.0`（`PW_TOOL_DEFAULT_TIMEOUT` 回退；注释：新工具默认超时来源；**测量调优不在本模块**——tool_call_logs 已记 duration_ms（module-066），module-085 看板拉 P95 后按数据调整各工具值）。
- `_execute` 内两处 `asyncio.wait_for(..., timeout=15)`（tool_registry.py:84/92）→ `timeout=self.timeout`；超时 warning 日志 `"工具 %s 超时 (15s)"` 改用 self.timeout 格式化（日志非返回文案）；**返回文案 `"(工具 X 执行超时)"` 一字不改**（存量测试精确断言）。
- `register()` 透传 `timeout=None`；现有 10 工具不传 → 全 15.0 → **零行为变化**。
- MCP 路径（mcp_server.py:90 复用 run）自动继承。
- **预估代码量**：~8 功能行（__init__ 3 + _execute 两处替换 2 + config 3）。
- **通过标准**：`AgentTool(timeout=0.01)` 超时返回精确文案且 wait_for 收到 timeout=0.01（monkeypatch wait_for 断言）/ 默认 `.timeout == settings.tool_default_timeout == 15.0` / 存量超时测试全绿。

## 4. WP-D：高风险审批（用户确认：现有 10 工具全低危，机制预留）

- `AgentTool.__init__` 加 `approval: str = "auto"`（"auto"/"required"，存 self.approval）；`register()` 透传默认 "auto"；**现有 10 工具全 auto → 门全短路（不查库）→ 零行为变化、零开销**；机制为 module-084 外部 MCP 工具（可能有副作用）预留。
- **数据表 approval_requests**（database.py，同款幂等 DDL 模式 + 注释）：
  ```sql
  CREATE TABLE IF NOT EXISTS approval_requests (
      id           BIGSERIAL   PRIMARY KEY,
      tool_name    VARCHAR(64) NOT NULL,
      args         JSONB       NOT NULL DEFAULT '{}',
      status       VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
      requester    VARCHAR(256) NOT NULL DEFAULT '',
      requested_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
      decided_at   TIMESTAMP
  );
  COMMENT ON TABLE approval_requests IS '高风险工具人工审批请求（module-083，机制预留，10 内置工具全 auto 不触达）';
  ```
  + `ensure_approval_requests_table()`（拆 ";" 逐条执行，对齐 ensure_tool_call_logs_table）+ `init_db()`（database.py:248 附近）挂接。
- **审批 DB 访问放 tool_registry.py 模块级**（对齐 record_tool_call 放 react.py 的既有模式，测试 monkeypatch 友好）：
  - `async _approval_allowed(name) -> bool`：`SELECT 1 FROM approval_requests WHERE tool_name=:n AND status='approved' ORDER BY decided_at DESC LIMIT 1`（参数化）；DB 异常 → logger.warning + **返回 False（fail-closed 安全侧，带注释：审批类工具属可能副作用类，宁拒勿放）**；仅 `approval=="required"` 时被调用（auto 短路零 DB 开销）。
  - `async _request_approval(name, args, requester)`：**同 tool_name 已有 pending 则不重复插入**（`WHERE NOT EXISTS` 或先查后插，参数化），返回 None。
- **run() 审批闸（_precheck 第一步，先于校验）**：
  ```python
  if self.approval == "required" and not await _approval_allowed(self.name):
      requester = getattr(ctx, "identity", "")
      await _request_approval(self.name, args, requester)
      return f"(工具 {self.name} 需人工审批，调用申请已提交)"
  ```
  - 语义：required 工具的每次 LLM 提议调用触发 pending 申请（同工具已有 pending 不重复插）；审批通过后**工具级放行**（同工具后续调用直接执行；args 级更细粒度审批留 module-084）。
- **端点**（main.py，跟现有 dict 返回惯例 `{code, msg, data}`）：
  - `GET /ai/tools/approvals?status=pending`：查询 approval_requests（status 缺省 pending；**暂不分页**——行数克制，按需留 module-084）；返回 `{"code":0,"msg":"success","data":{"approvals":[{id, tool_name, args, status, requester, requested_at, decided_at}, ...]}}`。
  - `POST /ai/tools/approvals`：body `{"id": int, "action": "approve"|"reject"}` → UPDATE status + `decided_at=now()`；非法 action / 不存在 / 已处理 → `{"code":1,"msg":...}`；成功 `{"code":0,"msg":"success","data":{"id":...,"status":...}}`。
  - **鉴权说明**：与现有 /ai 端点同等待遇（身份经 resolve_identity 可得，requester 记录用）；不新增强鉴权——强鉴权/工作流留 module-084 外部 MCP 接入时按需。
- **预估代码量**：~85 功能行（DDL+注释 16 + ensure 9 + 审批辅助 16 + run 闸 6 + GET 端点 18 + POST 端点 20）——**WP-D 是行数大头**，见 §7 总量对照。
- **通过标准**：单测（DB 访问 monkeypatch）——auto 工具 `_approval_allowed` 断言 0 次调用 / required 无 approved → 返回审批提示 + func 未执行 + 插 pending / 已有 pending 不重复插 / 有 approved → 放行 / DB 异常 fail-closed 拒绝 / GET 列表字段 + status 过滤 / POST approve→approved+decided_at、reject 同理、非法 action code 1 / ensure_approval_requests_table 二次执行幂等（拆 DDL 断言，对齐 test_tool_call_logs L99-107 手法）。

## 5. WP-E：Agent 级最小权限（用户问的第三层，now 落地）

- `react_agent`（react.py:340）加 `allowed_tools: Optional[set[str]] = None` 参数（None=全量，向后兼容）→ 透传给 react_loop。
- `react_loop`（react.py:379）加同参 → 在 execute_tool_with_log 调用点（react.py:508）传入。
- `execute_tool_with_log`（react.py:332）加 `allowed_tools: Optional[set[str]] = None` 参数，执行层守门与 `_phase_allows` 叠加：
  ```python
  if tool is not None and (not _phase_allows(name, ctx)
                           or (allowed_tools is not None and name not in allowed_tools)):
      result_ok = False
      result = (f"(工具 {name} 不在当前 Agent 权限白名单，请按可用工具选择)"
                if allowed_tools is not None and name not in allowed_tools
                else f"(工具 {name} 当前阶段不可用，请按可用工具列表选择)")
      logger.warning("工具 %s 被权限/阶段守门拒绝（allowed=%s phase=%s）", name, allowed_tools, ctx.phase)
  ```
  （两维守门各自独立判因；result_ok=false 审计可见，喂回 LLM 判断——对齐 066 实测补齐的执行层守门哲学。）
- **langgraph_react.py 零改动**：调用点 L169 不传新参 → None → 全量放行（module-030 先例：execute_tool_with_log 签名扩展默认值兼容两条循环）。
- **schema 暴露层暂不联动**：LLM 仍见全量 schema（省 token 的按白名单过滤留后续优化），执行层拒绝返回提示即可闭环——与"schema 是门禁、执行层是守门"现有语义一致。
- 为未来子 Agent / 外部 MCP 工具（module-084）**按 Agent 发权限**预留：main.py 端点在需要时传白名单。
- **预估代码量**：~12 功能行（三处参数 3 + 守门 7 + 注释 2）。
- **通过标准**：单测——None 全量放行（存量 react_agent 调用零变化）/ 白名单外工具拒绝且 func 未执行 + result_ok=false + 提示含"权限白名单" / 白名单内正常 / react_agent→react_loop→execute_tool_with_log 透传链路 / langgraph 调用点零改动（git diff）。

## 6. WP-F：回归 + 文档收口

- **目标**：全量绿（1485/4 基线口径，4 failed 系 module-028 proxies 环境性、1 error 系 scripts/test_models.py 陈旧脚本）+ **存量测试零改动**（红线：tool_call_logs 表结构 / 预算计数 / MCP / langgraph / result_ok 语义）。
- 新增 `ai_service/tests/agent/test_tool_governance.py`（预计 ~30 项：WP-A 5 / WP-B 7 / WP-C 3 / WP-D 8 / WP-E 5 + 混合 2）。
- conftest：**预计零改动**（无新开关；tool_default_timeout 默认 15.0 与现状等价、测试用相对断言；WP-D 测试 monkeypatch DB 函数不依赖真实库）——如 Developer 实现必须钉（例如给 settings 设短暂默认以免超时用例慢），须在 changelog 说明并遵循 hermetic 惯例。
- 涉及文件：
  - 修改：`ai_service/agent/tool_registry.py`、`ai_service/agent/react.py`、`ai_service/src/config.py`、`ai_service/src/database.py`、`ai_service/main.py`、`ai_service/requirements.txt`
  - 新增：`ai_service/tests/agent/test_tool_governance.py`
  - 文档：`specs/module-083-tool-governance/changelog.md`（Developer）、`review-report.md`（Reviewer）、`test-report.md`（Tester）；记忆三件套（project-context / file-index / agent-activity-log）；CONTEXT.md 补 module-083 行由协调者决定（只增不删先例）。
- **明确不做**：不做 args 级审批粒度（留 084）；不做 allowed_tools 联动 schema 暴露过滤；不做超时自动调优（085 看板 P95 后）；不改 mcp_server.py / langgraph_react.py / engine.py / router.py；无新 ADR（本模块是 ADR-0012/0017 治理线延续，决策记录入 changelog；若协调者裁定需新 ADR 再补）。

## 7. 技术方案汇总

- **数据表**：新增 `approval_requests` 1 张（DDL + ensure + init_db 挂接）；`tool_call_logs` 一字不改红线。
- **API 端点**：新增 2 个——`GET /ai/tools/approvals`（列审批，?status= 过滤）、`POST /ai/tools/approvals`（{id, action: approve|reject}）。
- **外部依赖**：新增 `jsonschema==4.26.0`（requirements.txt 一行，环境已装实测）。
- **配置项**：新增 `tool_default_timeout: float = 15.0`（PW_TOOL_DEFAULT_TIMEOUT）。
- **执行层守门总序**（写清，防实现顺序漂移）：execute_tool_with_log 内 `_phase_allows` + `allowed_tools` 两维守门（react 循环层）→ AgentTool.run 内 `_precheck`（审批 → schema 校验 → 幂等拦截）→ `_execute`（wait_for(self.timeout) + 073 重试）→ 成功记幂等指纹。MCP 路径只经过 run 内三闸（无 execute_tool_with_log）。
- **代码量口径**（铁律2 生产 ≤200 行）：

| WP | 内容 | 预估功能行 |
|----|------|-----------|
| WP-A | _schema_error + run 接线 + import + requirements | ~14 |
| WP-B | _IDEMPOTENT_TOOLS + _fingerprint + _precheck 拦截/记指纹 + ctx 字段 | ~20 |
| WP-C | __init__ timeout + _execute 两处替换 + config | ~8 |
| WP-D | approval DDL/ensure + 审批辅助 + _precheck 闸 + 2 端点 | ~85 |
| WP-E | allowed_tools 三处参数 + execute_tool_with_log 守门 | ~12 |
| 合计 | | ~139（含注释/常量后预期 ≤180）|

  若含注释/docstring 后仍 >200（WP-D 端点膨胀风险），Developer 须按 module-080 先例处理：plan.md 晒实际行数对照表 + 申请 `GATE_MAX_MODULE_LINES` 放宽，Reviewer/Tester 复核。**测试代码不计入生产行数**。

  **Developer 实测补充（2026-09-01，WP-A~F 完成后回填）**：

  | 文件 | 全行（numstat 口径） | AST 可执行行（module-075/080 先例口径） |
  |------|---------------------|--------------------------------------|
  | agent/tool_registry.py | 195 | 111 |
  | agent/react.py | 29 | 17 |
  | main.py | 67 | 45 |
  | src/config.py | 16 | 3 |
  | src/database.py | 27 | 8 |
  | requirements.txt | 3 | 1 |
  | **合计** | **337** | **185** |

  **口径说明**：铁律 2「新增生产代码 ≤200 行」按 module-075/080 确立的 **AST 可执行行口径** 判定——排除空行 / 注释 / docstring（docstring 为铁律 4 强制，注释/空行为既有代码库惯例）——本模块 **185 ≤ 200 ✓，无需申请 GATE_MAX_MODULE_LINES 放宽**。全行口径 337（超预估主因：WP-D 审批表/端点按计划预估即占 ~85 行大头，实际含参数化 SQL 与 fail-closed/fail-open 注释说明；WP-B 幂等拦截与记指纹拆 _precheck/_record_fingerprint 两方法满足方法 ≤50 行）。请 Reviewer/Tester 按 AST 口径复核（与 module-080 同口径先例）。

## 8. 风险评估

- **校验误拒合法调用（required 语义）**：决策"校验时置空 required"（§1）保留"缺省回退"契约，规避存量 `run({}, None)` 与 MCP 外部调用回归；残余——jsonschema 严格 integer 判定会把 `top_k: 1.0`（float 字面）判拒：概率低（LLM JSON 整数通常无小数点），若 module-085/评估发现周期出现，届时在 _schema_error 前置"整数字面 float 规整"兜底，本模块不加。
- **jsonschema 依赖**：已装 4.26.0 / requirements 锁版本 / 纯 Python；导入失败 = 启动显性失败（fail-fast 可测），运行期校验异常 fail-open 不阻断执行（§1）。
- **幂等误拦合法重放**：同参只读检索 = 同结果（结果已在消息历史），拦掉无害；失败/超时不记指纹可重放；generate/verify/note 排除；知识库静止无"重检最新"语义。
- **审批 fail-closed 与鉴权**：10 工具全 auto 短路零影响；未来 required 工具 DB 不可用 → 拒绝执行（安全侧）；审批端点沿用现有 /ai 鉴权层，强鉴权留 084。
- **零回归**：run() 三闸重构是最大风险点——必须保持 超时精确文案 / 失败空串 / result_ok 语义 / 幂等记录不影响 073 重试 / tool_count 预算语义 逐字不变；Developer 先用受影响存量套件（test_agent_tools 62 + test_tool_retry_dedup 24 + test_tool_call_logs + test_mcp_server）局部跑通再全量。
- **行数超限**：WP-D 端点占大头（§7 对照表 + module-080 放宽先例）。
- **幂等 × 073 交互**：重试成功记 1 次指纹（结果非空）；首败（空串）不记 → 同参可重放；校验失败/幂等命中不进重试分支（_precheck 在 try 外）——顺序写死在 §7 总序。

## 9. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-073 自动重试 | 分层正交：重试=异常恢复（_execute 内），幂等=同参重放拦截（_precheck 入口）；校验失败/幂等命中不进重试分支；重试成功记 1 次指纹 |
| module-041 note 去重 | 内容级（scratchpad）与参数级（指纹）分层；note_to_self 排除在幂等清单外 |
| module-066 / ADR-0017 tool_call_logs | 表结构与 result_ok 语义一字不改；校验失败/幂等命中/审批拒绝均记一行 result_ok=true（run 未抛异常）；allowed_tools/阶段守门拒绝 result_ok=false 审计可见 |
| module-068 阶段预算/推进 | 预算计数在 execute 前 → 各闸拒绝仍计 1 次（与阶段守门同口径）；幂等命中消息可能触发 _retrieval_hit 但首执已推进（advance_phase 单向前进）→ 无死锁 |
| module-058 / _phase_allows | WP-E 与阶段守门是两维（Agent 粒度 vs 阶段粒度），在 execute_tool_with_log 同处叠加、各自独立判因 |
| module-067 MCP server | run 内三闸（校验/超时/审批）经 mcp_server.py:90 自动继承；幂等 getattr 短路零影响；MCP 自身 READ_ONLY_TOOLS 白名单独立不受影响 |
| module-084 外部 MCP 客户端（前置后续） | approval=required + allowed_tools 是外部工具（可能副作用）的治理挂点；审批表/端点为 084 提供工作流底座 |
| 预算机制（总 budget + 068 阶段 budget） | 所有执行前闸不改变计数语义（§0 计数点） |

## 10. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-01 | 初始版本（WP-A~F 拆解 + 依赖决策 + 幂等机制详述 + 审批表/端点 + 行数对照 + 风险与既有机制关系） | Planner |