# 变更记录 — Module-083: 工具治理（schema 校验 / 幂等 / 工具级超时 / 高风险审批 / Agent 级最小权限）

> Developer: 2026-09-01 | 依据：`plan.md` v1（WP-A~F）+ `acceptance-criteria.md`（AC-1~AC-58）
> 基线：module-082 后全量 **1485 passed / 4 failed（module-028 langchain-openai proxies 环境性基线）/ 3 skipped / 1 error（scripts/test_models.py 陈旧脚本）**——本模块红线：**新增 0 失败、存量测试零改动、mcp_server.py / langgraph_react.py / engine.py / router.py 零 diff**

---

## 一、实现总览（执行层守门总序，硬约束 1 落地）

```
execute_tool_with_log 二维守门（_phase_allows + allowed_tools，react 循环层）
  → AgentTool.run._precheck（审批 → schema 校验 → 幂等指纹拦截）
  → AgentTool._execute（wait_for(self.timeout) + module-073 重试语义）
  → 成功（非空且非超时提示）后才记幂等指纹
MCP 路径（mcp_server.py:90 直接调 tool.run）只经过 run 内三闸，不经过 execute_tool_with_log。
```

## 二、WP 实现说明

### WP-A args schema 校验（AC-1~6 / AC-40）
- `tool_registry.py` 模块级 `_schema_error(name, args, schema)`：非 dict args → `"(工具 X 参数错误: 参数应为 object)"`；**校验 schema 置空 required**（`{**schema, "required": []}` 浅拷贝不 mutate 原对象）——保留工具内 "query 缺省回退 ctx.query" 契约（存量 `run({}, None)` 与 MCP 外部调用依赖）；`jsonschema` 非 ValidationError 异常 → `logger.warning` + fail-open 放行（依赖层异常不拖垮工具链路）。
- requirements.txt 补 `jsonschema==4.26.0`（环境实测已装 4.26.0，锁版本对齐已装环境防漂移，同 mcp==1.26.0 先例）。
- 校验失败返回提示文本喂回 LLM、不进重试分支（`_precheck` 在 try 外）、不记指纹、`result_ok=true`（run 正常返回）→ tool_call_logs 落库语义零变化。

### WP-B 幂等（AC-7~15 / AC-36 / AC-39 / AC-41）
- `ReactContext.__init__` 加 `executed_fingerprints: set[str] = set()`（每请求独立，跨请求不共享）。
- `_IDEMPOTENT_TOOLS` 白名单 7 只读检索工具（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/re_search）；generate_answer/verify_answer/note_to_self 天然排除（不在白名单）。
- `_fingerprint(name, args)`：`sha256(name + "|" + json.dumps(args, sort_keys=True, ensure_ascii=False))`——键序无关；args 非 JSON 序列化 → 返回 None 跳过幂等（防御注释）。
- **记录时机 = 成功执行之后**：`_record_fingerprint` 仅在「非空结果 **且** 非超时提示」时记指纹——超时返回文本非空但不是执行结果（AC-12 超时不可记），以精确超时文案判定"未执行成功"（与 react.py `_EMPTY_RESULT_MARKERS` 红线文本耦合先例对齐）。失败（空串）/超时 → 同参可重放，与 module-073 自动重试自洽；073 重试成功只记 1 次。
- MCP 轻量 ctx（SimpleNamespace 无 executed_fingerprints）/ ctx=None → `getattr` 短路零拦截（mcp_server.py 零改动自动兼容）。
- 幂等命中消息非空 → 可能触发 `_retrieval_hit` 推进阶段，但首执已推进过（advance_phase 单向前进）→ 无死锁（集成测试 `test_idempotent_hit_loop_continues` 实证循环正常结束）。
- 每请求独立 → 两个 ReactContext 不共享拦截（AC-36 测试实证）。
- 指纹只存当前活跃已执行集合（内存 set，随请求释放），不落库——结果已在消息历史中可回溯，无需持久化（与"成功结果不重放"用户口径一致）。

### WP-C 工具级超时（AC-16~19）
- `AgentTool.__init__` 加 `timeout: Optional[float] = None` → `self.timeout = timeout if timeout is not None else settings.tool_default_timeout`（config 是新工具默认值来源）；`register()` 透传（现有 10 工具不传 → 全 15.0 零行为变化）。
- `_execute` 两处 `asyncio.wait_for(..., timeout=15)` → `timeout=self.timeout`；超时 warning 日志改用 self.timeout 格式化（**返回文案 `"(工具 X 执行超时)"` 一字不改**，存量测试逐字断言；巡检确认无测试断言日志里的 "(15s)"）。config 0/负数值语义未定义（AC-38，未做隐式规整）。
- MCP 路径（mcp_server.py:90 复用 run）自动继承 self.timeout。
- 测量调优不在本模块（tool_call_logs 已记 duration_ms，module-085 看板拉 P95 后按数据调整各工具值，入遗留清单）。

### WP-D 高风险审批（AC-20~28 / AC-37 / AC-42 / AC-50~53）
- `AgentTool.__init__` 加 `approval: str = "auto"`；`register()` 透传默认 "auto"；现有 10 工具全 auto → 门全短路（`_approval_allowed` 0 次调用，AC-21 测试实证）零 DB 开销、零行为变化。
- database.py：`APPROVAL_REQUESTS_DDL`（approval_requests 表：id/tool_name/args JSONB/status/requester/requested_at/decided_at，CREATE TABLE IF NOT EXISTS + COMMENT）+ `ensure_approval_requests_table()`（拆 ";" 逐条执行，对齐 ensure_tool_call_logs_table）+ `init_db()` 挂接（module-083 日志行）。
- `_approval_allowed(name)`：SELECT 最近一条 approved（`ORDER BY decided_at DESC LIMIT 1`）；**DB 异常 → logger.warning + fail-closed 拒绝**（审批类工具属可能副作用类，宁拒勿放；与 tool_call_logs 观测路径 fail-open 严格区分，注释可辨）。SQL 全参数化（:n）。
- `_request_approval(name, args, requester)`：同 tool_name 已有 pending 不重复插入（先查后插）；落库失败仅日志告警（fail-open，观测/工作流路径）；args 非序列化兜底 `{}`。
- `_precheck` 审批闸**先于** schema 校验（AC-37 顺序测试实证：required + 非法参数 → 返回审批提示而非参数错误）。
- main.py 两端点（沿用 {code, msg, data} 惯例）：`GET /ai/tools/approvals?status=`（缺省 pending，暂不分页留 module-084）+ `POST /ai/tools/approvals`（body `{id, action}`，approve/reject；非法 action / id 不存在 / 已处理 → code 1 不崩）。鉴权与现有 /ai 端点同等待遇（requester 经 ctx.identity 记录；强鉴权留 084）。
- **开发决定（任务简报 vs plan 冲突消解）**：任务简报写 `POST /ai/tools/approvals/{id}/decide`，plan §WP-D 与 AC-27 均为 `POST /ai/tools/approvals`（body {id, action}）——以 **plan/AC 为准**（plan 是 Planner 权威规格，AC 由其派生；实现按 plan）。

### WP-E Agent 级最小权限（AC-29~34）
- `react_agent` / `react_loop` / `execute_tool_with_log` 加 `allowed_tools: Optional[set[str]] = None`（None = 全量放行向后兼容）；react_agent → react_loop（关键字传递）→ execute_tool_with_log 透传。
- execute_tool_with_log 执行层二维守门：`tool is not None and (not _phase_allows(name, ctx) or (allowed_tools is not None and name not in allowed_tools))`——两维独立判因：白名单外 → `"（工具 X 不在当前 Agent 权限白名单，请按可用工具选择）"`；阶段外 → 存量 `"（工具 X 当前阶段不可用…）"` 文案逐字保留；均 result_ok=false（审计可见）+ warning 日志 + 喂回 LLM。
- langgraph_react.py:169 调用点不传新参 → 全量放行（该文件零 diff 已核验）；mcp 路径不经 execute_tool_with_log。
- schema 暴露层暂不联动（LLM 仍见全量 schema，执行层拒绝返回提示闭环；按白名单过滤留后续优化）。

### 配置与开关（config.py）
- `tool_default_timeout: float = 15.0`（PW_TOOL_DEFAULT_TIMEOUT 回退，plan §WP-C 明确要求）。
- `tool_idempotency_enabled: bool = True` / `tool_approval_enabled: bool = True`——**任务简报额外要求、plan 未列**：按简报补充并经 `_precheck`/`_record_fingerprint`/审批闸轻量接线（默认 true 零行为变化，false 为逃生口，与代码库"每个特性带回退开关"惯例一致）。

## 三、行数统计（铁律 2，对齐 module-075/080 AST 口径先例）

| 文件 | 全行（numstat 口径） | AST 可执行行（module-075/080 先例） |
|------|---------------------|--------------------------------------|
| agent/tool_registry.py | 195 | 111 |
| agent/react.py | 29 | 17 |
| main.py | 67 | 45 |
| src/config.py | 16 | 3 |
| src/database.py | 27 | 8 |
| requirements.txt | 3 | 1 |
| **生产代码合计** | **337** | **185** |

**口径说明**：铁律 2「新增生产代码 ≤200 行」按 module-075 确立、module-080 §5.4 沿用的 **AST 可执行行口径** 判定（排除空行 / 注释 / docstring；docstring 为铁律 4 强制、注释为代码库惯例）：**AST 185 ≤ 200 ✓，无需申请 GATE_MAX_MODULE_LINES 放宽**。全行 337 超 plan 预估 ~139-180：主因 WP-D（审批表/辅助/闸/2 端点按 plan 预估即 ~85 行大头，实际含参数化 SQL 与 fail-closed/fail-open 注释说明）+ WP-B 分置 _precheck/_record_fingerprint 两方法（方法 ≤50 行约束）。对照表已回填 plan.md §7，Reviewer/Tester 可按 module-080 同口径复核。
**测试代码不计入生产行数**（test_tool_governance.py ~470 行，43 项）。

铁律 3（方法 ≤50 行）：本模块**新增/改动的所有方法 ≤50 行**（run 34 / _precheck 20 / _execute 25 / _record_fingerprint 20 / 两端点 18-25 / execute_tool_with_log 30 等）；存量 >50 方法（register_builtin_tools 69、react_loop 123、lifespan 62、chat_agent 69、chat_agent_langgraph 71）为 HEAD 基线既有超限（git show HEAD 逐一核验），非本模块新增，沿用历史豁免。

## 四、验证输出

### 4.1 定向测试（WP-F 新增 43 项，全绿）
```
cd ai_service && .venv\Scripts\python -m pytest tests/agent/test_tool_governance.py -q
43 passed, 2 warnings（starlette multipart / pydantic lifespan 既有告警，与本模块无关）
```

### 4.2 任务指定定向命令
```
pytest tests/agent/ -q -k "governance or tool"
172 passed, 4 failed（4 个均 module-028 langchain-openai proxies 环境性基线：TestChatWithTools 四例）
```

### 4.3 受影响存量套件（零改动实证）
```
pytest tests/agent/test_agent_tools.py tests/agent/test_tool_retry_dedup.py tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py -q
121 passed, 4 failed（同上 4 个 proxies 基线，非本模块回归）
```

### 4.4 全量回归
```
pytest tests/ -q
1526 passed, 6 failed, 3 skipped, 404.71s
```
失败构成：
- **4 × module-028 proxies 基线**（TestChatWithTools，环境性，规划声明预期存在）；
- **2 × 真实 Redis 集成测试**（test_prefix_invalidation_real_redis / test_set_get_roundtrip_real_redis）——`Timeout connecting to server`，Docker Redis 未启动（本机 Docker Desktop daemon 未运行，docker ps 连接失败）；module-060 changelog 已记录同类环境依赖（Docker Redis 7 就绪即绿）。两测试路径不触及本模块任何代码（LLM 链持久化 / cache 前缀失效）。
→ **module-083 新增 0 失败**；存量收集数 1493 + 43 新增 = 1536，实测收集 1535（1 项差为陈旧脚本/收集环境差异，与基线"1 error scripts/test_models.py"同源口径）。

### 4.5 线红线核验
```
git diff --name-only -- ai_service/mcp_server.py ai_service/agent/langgraph_react.py ai_service/rag/engine.py ai_service/agent/router.py
（空输出 = 零 diff ✓）
变更文件共 7：修改 tool_registry.py / react.py / config.py / database.py / main.py / requirements.txt + 新增 tests/agent/test_tool_governance.py
```

### 4.6 冒烟与编译
```
py_compile（5 生产文件）  COMPILE OK
from src.config import settings → tool_default_timeout=15.0 / tool_idempotency_enabled=True / tool_approval_enabled=True
from jsonschema import validate, ValidationError → jsonschema ok（4.26.0）
```

## 五、验收标准对照（AC 摘要）

| 域 | 状态 | 说明 |
|----|------|------|
| WP-A schema 校验（AC-1~6/35/40/53） | ✅ | 校验失败不执行+wait_for 0 次 / 合法执行 / 缺省回退契约 / run({},None) 容忍 / 非 dict 提示 / fail-open / e.message 无内部细节；**AC-35 已知边界如实标注**：float 整数字面（top_k: 1.0）被 jsonschema 严格 integer 拒绝——概率低（LLM JSON 整数通常无小数点），留 module-085/评估观察，届时加"整数字面规整"兜底（本模块不加） |
| WP-B 幂等（AC-7~15/36/39/41） | ✅ | 同参拦截 / 键序无关 / 异参放行 / 失败·超时·校验失败不记可重放 / 排除清单 / 轻量 ctx 与 None 零拦截 / 073 重试记 1 次 / 每请求独立 / 循环无死锁 |
| WP-C 超时（AC-16~19/38/43） | ✅ | timeout 透传 wait_for / 默认 15.0 来源 config / 精确文案一字不改（不含秒数）/ 0 负值语义未定义未规整 / MCP 15s 围栏不变（存量 test_mcp_server 全绿） |
| WP-D 审批（AC-20~28/37/42/49~53） | ✅ | auto 零 DB / required 拦截+插申请 / pending 去重 / approved 放行 / DB 异常 fail-closed / GET+POST 端点含非法输入 / DDL 幂等 / init_db 挂接 / 审批先于校验 / SQL 全参数化 |
| WP-E 权限（AC-29~34） | ✅ | None 全量 / 白名单外拒绝 result_ok=false+提示含"权限白名单" / 白名单内放行 / react_agent 透传链路 / langgraph 零 diff 全量放行 / 两维独立判因 |
| 兼容性红线（AC-43~48/57） | ✅ | 超时文案 / 失败空串 / result_ok 语义 / tool_call_logs 表结构（DDL 零改动）/ 预算计数（各闸拒绝仍计 1 次，代码未动计数点）/ 4 红线文件零 diff |
| 代码质量（AC-54~58） | ✅ | AST 口径 185 ≤ 200 / 方法 ≤50（新增部分）/ 无空 catch（全带 logger+注释）/ 无新 ADR（决策入本 changelog，治理线延续 ADR-0012/0017） |
| 性能（AC-49~50） | ✅ | auto 工具 0 DB 查询（测试断言）/ 校验纯函数 O(args) / 幂等内存 set + 一次 sha256 / 审批路径仅 required 工具触达 |

## 六、遗留清单（backlog / 非阻塞）

1. **AC-35 已知边界**：jsonschema 严格 integer 会把 `top_k: 1.0`（float 字面）判拒；若 module-085/评估发现 LLM 周期传浮点整数字面，届时在 `_schema_error` 前置"整数字面 float 规整"兜底（本模块不加，plan §8 已声明）。
2. **超时自动调优**：tool_call_logs 已记 duration_ms（module-066），module-085 看板拉 P95 后按数据调整各工具 timeout 值（本模块只做参数化，config 是新默认来源）。
3. **args 级审批粒度 / 审批端点分页 / 强鉴权**：留 module-084 外部 MCP 客户端接入时按需（plan §WP-D/AC-26 声明"暂不分页"）。
4. **allowed_tools 联动 schema 暴露过滤**（省 token）：明确不做，执行层拒绝返回提示即可闭环（plan §WP-E）。
5. **全量回归环境依赖**：2 项真实 Redis 测试需 Docker Redis 7 就绪（module-060 先例）；当前本机 daemon 未启动属环境条件，非模块回归。
6. **记忆三件套 / CONTEXT.md 收口**：plan WP-F 列出的 project-context / file-index / agent-activity-log 更新与 CONTEXT.md module-083 行由协调者决定（本 changelog 为 Developer 交接物）。

## 七、变更文件清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `agent/tool_registry.py` | 修改 | jsonschema 校验 / 幂等 / 审批辅助 + AgentTool(timeout/approval) + run 拆 _precheck/_execute/_record_fingerprint |
| `agent/react.py` | 修改 | ReactContext.executed_fingerprints + execute_tool_with_log/react_agent/react_loop 加 allowed_tools |
| `src/config.py` | 修改 | tool_default_timeout / tool_idempotency_enabled / tool_approval_enabled |
| `src/database.py` | 修改 | APPROVAL_REQUESTS_DDL + ensure_approval_requests_table + init_db 挂接 |
| `main.py` | 修改 | ApprovalDecisionRequest + GET/POST /ai/tools/approvals |
| `requirements.txt` | 修改 | jsonschema==4.26.0 |
| `tests/agent/test_tool_governance.py` | 新增 | 43 项（WP-A 7 / WP-B 11 / WP-C 3 / WP-D 17 / WP-E 5） |
| `specs/module-083-tool-governance/plan.md` | 修改 | §7 回填 Developer 实测行数对照表 + 口径说明 |
| `specs/module-083-tool-governance/changelog.md` | 新增 | 本文档 |

## 八、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-01 | WP-A~F 全部实现：校验/幂等/超时/审批/权限 + 43 项测试 + 全量回归（新增 0 失败）+ 行数对照回填 | Developer |