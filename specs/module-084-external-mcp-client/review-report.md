# 审查报告 — Module-084 外部 MCP 客户端接入

> Reviewer: 2026-09-06 | 审查对象：`specs/module-084-external-mcp-client/`（plan.md / acceptance-criteria.md / changelog.md）+ 3 个新增文件 + 5 个修改文件
> 审查方法：全文件通读（mcp_client.py 229 行 / mcp_sample_server.py 51 行 / test_mcp_client.py 809 行 / tool_registry.py 654 行 / config.py 447 行 / main.py 1288 行 / langgraph_react.py 418 行 / conftest.py 292 行）+ 独立测试复跑 + git diff 逐文件归属核验 + AST 行数/方法长度机械化审计 + 语义矩阵运行时探针 + 真实 stdio 子进程握手独立冒烟
> 083/084 归属区分口径：工作树含 module-083 未提交变更（最后提交停在 module-082），084 归属按"变更内容是否与外部 MCP client 相关"判定，已逐文件甄别（见 §6 红线核验）

## 1. 审查结论

- **结论：✅ 通过（PASS）（0 阻塞 / 0 重大 / 4 项 LOW 非阻塞 + 2 项备忘）**

协调者指定的 10 项重点核查全部实测通过；语义矩阵红线（启用分支绝不返回 None）经代码路径 + 独立运行时探针双重确认；两端点白名单透传闭环无绕过口；红线文件（react.py / database.py / mcp_server.py / rag/engine.py / rag/router.py / requirements.txt）对 084 零改动经 git diff 逐文件甄别成立；行数双口径（AST 语句）独立复算与 Developer 声明逐字一致（mcp_client 113 / 样例 server 19），核心 ~164 / 严格含样例 ~183 ≤ 200；34 项定向测试 + 204 项受影响存量独立复跑全绿；真实 stdio 子进程握手（AC-23/24）独立冒烟复现成功。

## 2. 重点核查表（协调者指定 10 项）

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **agent_allowed_tools 语义矩阵红线** | ✅ | mcp_client.py:221-224——`if not settings.mcp_external_enabled or self._registry is None: return None` 之后启用分支唯一出口 L223-224 `return builtin \| (self.registered & set(settings.mcp_external_tools))`，恒为 set 绝不返回 None；白名单空 = 交集空 = 只放内置；白名单含未注册名交集自然剔除（AC-26）。运行时探针独立验证：enabled + spawn 失败（`_registry` 已设 L99）→ 非 None 且恰为 10 内置名；enabled + command 空（init_ext L96-98 早退，`_registry` 未设）→ None，此时外部工具零注册、None 无放行对象（安全方向，见备忘 B2） |
| 2 | **两端点白名单透传无绕过口** | ✅ | main.py:745 计算 + main.py:748-750 `/ai/rag/chat/agent` 透传 react_loop；main.py:822 计算 + main.py:825-827 `/ai/rag/chat/agent-lg` 透传 langgraph_react_loop；langgraph_react.py:317（loop 参数）/ 367（initial_state 注入）/ 174-175（execute_tools 节点 `state.get("allowed_tools")` → execute_tool_with_log）；执行层闸门 react.py:359-361（083 代码，未触碰）两路共用——手写与 langgraph 汇合同一守门点，无第三调用面 |
| 3 | **同名冲突检测** | ✅ | mcp_client.py:142-144——`if tool.name in reg.list_tool_names(): logger.warning("外部工具 %s 与存量工具重名，跳过注册（防覆盖）") + continue`，先于 register（L145）；`test_conflict_name_skipped`（test_mcp_client.py:257-272）断言注册后内置 description 一字不变 + registered 为空 |
| 4 | **fail-open 链五路** | ✅ | ① disabled：mcp_client.py:94-95 直接 return 0（不 spawn，`test_disabled_zero_spawn` 断言 stdio_client 0 次调用）；② command 空：L96-98 warning + return 0；③ spawn 失败 / ④ 握手超时（L123-128 三段 `asyncio.wait_for`）/ ⑤ list_tools 失败（L138 wait_for）：③④⑤ 全部汇入 L100-106 单一 `except Exception → logger.warning + return len(registered)` 不 re-raise；lifespan 调用点 main.py:172-173 无额外包装即天然不阻塞启动（`test_spawn_failure_fail_open` + `test_lifespan_spawn_failure_service_survives` 双证）。enabled=false 零开销：init_ext L94-95 首行短路，无任何 spawn/DB/子进程动作（模块级 import 属 main.py import 链既有成本，mcp SDK 经 mcp_server L26 已加载） |
| 5 | **no_retry 语义** | ✅ | tool_registry.py:165（`no_retry: bool = False` 参数）/ 182（赋值）/ 253-254（重试条件追加 `and not self.no_retry`，注释标注 module-084）；`_NO_RETRY_TOOLS` L42 一字未改；超时永不重试结构保留——`except asyncio.TimeoutError` L249 先于 `except Exception` L252 判定，no_retry 不影响超时分支；内置 10 工具 `register_builtin_tools` L598-647 均不传 no_retry/approval → 默认 False/auto（`test_builtin_tools_all_no_retry_false` L152-157 逐一断言 10 工具 no_retry is False + approval == "auto"）；`test_no_retry_true_executes_once` 断言 func 执行 1 次、`test_no_retry_default_keeps_073_semantics` 断言默认 False 仍重试成功（执行 2 次） |
| 6 | **审批闸复用** | ✅ | mcp_client.py:151 `approval="required"` 硬编码字面量（无配置引用，不可豁免）；执行期走 AgentTool.run → `_precheck` 第一闸 tool_registry.py:224-228 → `_approval_allowed`（L93-113）/ `_request_approval`（L116-144）→ 复用 083 端点 main.py:1232（GET）/ main.py:1254（POST），两端点本模块零改动；零新表（database.py diff 仅 083 的 APPROVAL_REQUESTS_DDL，见 §6）；`test_register_and_approval_flow`（test_mcp_client.py:731-787）实证未审批 → pending INSERT 落库 + 拦截提示，approve 后真实执行文件追加 |
| 7 | **截断与异常提示** | ✅ | `_truncate` mcp_client.py:49-53（`_TRUNCATE_LIMIT=2000` L45），应用于 structuredContent 分支 L185 与文本分支 L189；异常路径 L177-179 返回 `（外部工具 X 调用失败: {e}）` 仅 str(e) 无堆栈无密钥（docstring L172-173 如实声明异常消息可能含路径、仅文本层面）；isError 日志 L182 `detail[:200]` 截断防日志膨胀；grep 实证：两新文件 0 处 `print(`、4 处 except 全部 `except Exception as e` + logger（无裸 except）、logger 行无 args/token 明文（仅工具名/计数） |
| 8 | **conftest fixture** | ✅ | tests/conftest.py:273-291 `default_mcp_external_disabled`（autouse）——钉 `mcp_external_enabled=False` / `mcp_external_command=[]` / `mcp_external_tools=[]`（L285-287 三件套）+ 重置 external 单例 `registered=set()` / `_registry=None`（L289-291），对齐 056/058/081 既有模式；monkeypatch 自动还原配置，单例重置防测试间污染 |
| 9 | **行数（铁律 2）** | ✅ | Reviewer 独立 AST 语句口径：mcp_client.py = **113** / mcp_sample_server.py = **19**（与 changelog §三声明逐字一致）；084 归属修改文件按 diff 内容甄别：tool_registry ~8（L158-159/165/179-182/253-254/315/325-326/330）、config 11（L432-442）、main ~16（L27-28/172-173/180-181/742-745+750/821-822+827）、langgraph 11（numstat +11/-1）→ **核心 ~159 ≤ 200**；严格含样例 ~178 ≤ 200（口径注：Developer 记 ~164/~183，差异系 main.py 084 行按含注释 23 vs 不含注释 ~16 的计数差异，双口径均过线）。最长方法 init_ext：物理 28 行（L81-108）/ AST 14 语句，双口径 ≤ 50 |
| 10 | **AC 覆盖抽查** | ✅ | 见 §3 |

## 3. AC 覆盖抽查（协调者指定 5 项 + 边界补充）

| AC | 要求 | 对应测试 | 断言质量 |
|----|------|----------|----------|
| AC-12 | 语义矩阵三态锁死 | `TestAllowedToolsMatrix` 4 项（test_mcp_client.py:367-404）+ `test_discovery_registers_with_governance` 内矩阵断言（L249-255） | 到位：未启用 None（L374）/ 启用+空白名单非 None 且 len==10（L384-386）/ 授权∩已注册精确并集（L252-255）/ 启用但未初始化 None（L400-404） |
| AC-18/19 | 双端点白名单拒绝 | `test_agent_endpoint_denies_external`（L545-571）/ `test_agent_lg_endpoint_denies_external`（L573-599）| 到位：httpx ASGI 真实走 SSE 端点断言 tool_result 含"权限白名单"且 func 未执行；`test_unauthorized_no_approval_submission`（L789-798）补断言白名单拒绝不触发 `_request_approval`（await_count==0，执行层先于审批闸） |
| AC-23 | 真实 stdio 握手（非 mock） | `test_real_subprocess_handshake`（L710-729） | 到位：`sys.executable` 真子进程 → initialize → list_tools 精确断言 `['ext_current_time','ext_append_log']` → call_tool 返回真实 ISO 时间；**Reviewer 独立冒烟复现**（见 §6） |
| AC-24 | 注册链路半真实 + 审批 | `test_register_and_approval_flow`（L731-787） | 到位：真实子进程 init_ext 注册进真实全局 registry → 未审批拦截提示 + INSERT 断言 → approve（`_approval_allowed` SELECT 打桩返回 1，符合 AC"或"分支）→ 真实执行且 `mcp_sample_out.log` 确实追加 + finally 清理全局 registry/清单例状态 |
| AC-31 | spawn 失败 fail-open | `test_spawn_failure_fail_open`（L274-287）+ `test_lifespan_spawn_failure_service_survives`（L501-520） | 到位：init_ext 层 warning + 返回 0；lifespan 层 enabled+坏 command 走真实 init_ext 内部捕获，服务照常 yield |
| AC-4/5/6/13/27/34 | 补充抽查 | `test_disabled_zero_spawn`/`test_discovery_registers_with_governance`（approval/group/no_retry/args_schema 四契约逐一断言）/`test_conflict_name_skipped`/`test_close_idempotent_uninitialized`/`test_empty_command_fail_open`/`test_empty_result_placeholder` | 全部到位，注册契约四字段（approval="required"/group==set()/no_retry=True/args_schema==inputSchema）断言精确 |

## 4. 问题列表（全部非阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | tests/agent/test_mcp_client.py | 804-809 | 测试桥 `_register_tools_public` 在测试模块 import 时向**生产类** `ExternalMCPClient` 永久挂载方法（进程内不回收）。功能无害（仅测试进程、不改生产行为），但污染生产类命名空间，偏离"mock 注入不改生产对象"的整洁口径。 | LOW | 改为用例内直接 `await ExternalMCPClient._register_tools(client, reg)`（Python 私有方法可直接调用）或经 monkeypatch 挂载自动还原 |
| 2 | agent/mcp_client.py | 110-128, 138 | 超时围栏是**逐段**而非整体：stdio 进入 / ClientSession 进入 / initialize 三段各得完整 `mcp_external_timeout`，list_tools 再得一段——最坏累积启动延迟 ≈ 4×10s=40s（每段都挂起时）。仍是有界 fail-open 不死阻塞，但"握手超时 10s"的直觉口径被放大 4 倍。 | LOW | 后续如需精确预算可改 `asyncio.timeout` 整体包裹 `_spawn_session+_register_tools`；v1 现状可接受（spawn 失败路径瞬时失败，真实挂起场景罕见） |
| 3 | agent/mcp_client.py | 122-128, 191-208 | 握手中途失败（stdio CM 已进入但 ClientSession/initialize 失败）时，fail-open 返回不清理已进入的上下文——子进程存活至服务 shutdown 才由 close() 终结（`_stdio_cm` 保持在实例上，close 可达）。init_ext 每进程仅调用一次，无累积泄漏，影响有界。 | LOW | 可在 init_ext except 分支先 `await self.close()` 再返回，失败即回收子进程；v1 如实声明即可 |
| 4 | specs/module-084-external-mcp-client/changelog.md | §二 WP-G | 测试分组声明 "lifespan 3 / 样例 server 3" 与实际类分布不符：`TestLifespan` 2 项 / `TestSampleServer` 4 项（`test_unauthorized_no_approval_submission` 归属样例类但实为 AC-18 补充）。总数 34 正确，仅分组口径小误差。 | LOW | 文档勘误即可，不影响任何验收结论 |
| B1 | tests/conftest.py | 273-291 | （备忘）fixture 重置 `registered/_registry` 两字段，未重置 `session/_stdio_cm/_session_cm`——逐测试路径排查确认当前无任何用例向**单例**写入这三个字段（lifespan 用例 mock init_ext；真实子进程用例用局部实例），无实际污染风险。 | 备忘 | 未来如有用例对单例跑真实 init_ext，需在此扩充重置字段 |
| B2 | agent/mcp_client.py | 94-99, 221 | （备忘）enabled=true + command 空 + init_ext 已调用 → `agent_allowed_tools()` 返回 None（init_ext 在 `_registry` 赋值前早退）。运行时探针确认安全：该路径外部工具零注册，None 无未授权放行对象；且与 AC-12"外部未启用 → None"的 fail-open 语义一致。非缺陷，记录语义边界供 Tester 知悉。 | 备忘 | 无需动作；如未来把"启用但 command 空"视为独立状态，可在此分支也置 `_registry` 使返回非 None |

## 5. 铁律合规检查

| 铁律 | 检查结果 | 证据 |
|------|----------|------|
| #2 新增生产代码 ≤200 行 | ✅ | AST 语句口径独立复算：mcp_client 113 + 样例 19 + 084 归属修改 ~27 → 核心 ~159 / 严格 ~178，双口径 ≤200（§2 #9）；测试代码 809 行不计入 |
| #3 方法 ≤50 | ✅ | mcp_client 最长 init_ext 物理 28 行 / AST 14 语句；`_ext_call` 15 语句 / `close` 12 / `_register_tools` 11，全部 ≤50 |
| #4 public 方法 docstring / 魔法数字命名 | ✅ | ExternalMCPClient 全部 public 方法（init_ext/_ext_call/close/agent_allowed_tools）带 Args/Returns docstring；2000 截断 → `_TRUNCATE_LIMIT` 常量；`_AI_SERVICE_DIR` 命名 |
| #5 禁空 catch | ✅ | grep + 逐处核验：4 处 `except Exception as e` 全部带 logger.warning + fail-open/fail-closed 性质注释（L104"fail-open"显式标注） |
| #8 日志禁敏感信息 | ✅ | 8 条 logger 行逐条核验：仅工具名/计数/异常消息；args/token/密钥零明文；isError detail 截断 200 字符 |
| #9 禁 SQL 拼接 | ✅ | 本模块零新增 SQL（复用 083 参数化审批查询，逐条 `:n`/`:args`/`:s`/`:i` 绑定核验） |
| #11 记忆收口 | ✅ | 本次审查按 PASS 更新三件套（file-index module-084 行 + activity-log [REVIEW]/[HANDOFF] + project-context 状态行） |

## 6. 红线核验（AC-38：084 归属零改动甄别）

| 文件 | 工作树 diff | 甄别结论 |
|------|-------------|----------|
| agent/react.py | +29/-12 | **083 遗留**：全部为 executed_fingerprints（幂等）与 allowed_tools 签名/二维守门（react.py:335/359-361/385/430/525），无任何 MCP client 相关内容 → 084 零改动 ✅ |
| src/database.py | +27 | **083 遗留**：APPROVAL_REQUESTS_DDL + ensure_approval_requests_table + init_db 挂接 → 084 零改动 ✅ |
| requirements.txt | +7/-1 | **083 + 环境遗留**：jsonschema==4.26.0（083）、openai 1.109.1（module-028 proxies 基线修正）、onnxruntime（2026-09-01 HHEM ONNX）；无新增 client 依赖（mcp==1.26.0 原有）→ 084 零改动 ✅ |
| mcp_server.py / rag/engine.py / rag/router.py | 空（`git diff --stat` 无输出） | 零 diff ✅（独立复跑） |
| agent/tool_registry.py / src/config.py / main.py | 混合 diff | 已逐块甄别：084 归属仅 no_retry 三处（tool_registry）/ mcp_external_* 4 项（config L432-442）/ import 2 行 + lifespan 2 处 + 两端点 allowed_tools（main）；其余为 083 审批端点/治理代码 |
| agent/langgraph_react.py / tests/conftest.py | +11/-1、+21 | 全部为 084 归属（透传链 + autouse fixture），与声明一致 |

## 7. 独立复跑输出（Reviewer，2026-09-06）

```
定向：     pytest tests/agent/test_mcp_client.py -q                → 34 passed, 2 warnings in 27.61s
受影响存量：pytest tests/agent/test_agent_tools.py tests/agent/test_tool_retry_dedup.py
           tests/agent/test_tool_governance.py tests/agent/test_tool_phase_split.py
           tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py
           tests/core/test_rerank_langgraph.py -q                  → 204 passed, 2 warnings in 62.46s
           （与 Developer 自测声明逐字一致；存量测试零改动）
py_compile：agent/mcp_client.py scripts/mcp_sample_server.py agent/tool_registry.py
           src/config.py main.py agent/langgraph_react.py          → PY_COMPILE OK
config 冒烟：settings.mcp_external_*                                 → False [] [] 10.0（默认全关）
真实握手冒烟（AC-23 独立复现，非测试进程）：
           LIST_TOOLS: ['ext_current_time', 'ext_append_log']
           CALL_TIME: 2026-09-06T01:26:05.647959+00:00 isError: False
           CALL_LOG: 已追加到 mcp_sample_out.log: reviewer-smoke-084（文件真实追加）
行数审计：  AST 语句口径自动脚本 → mcp_client 113 / sample_server 19 / 最长方法 init_ext 14 语句
语义矩阵探针（enabled 边界三场景）：
           S1 enabled+空command → allowed is None（外部零注册，安全）
           S2 enabled+spawn失败 → 非 None、len==10（只放内置）
           S3 白名单含未注册名 → 该名不出现
红线核验：  git diff --stat -- mcp_server.py rag/engine.py rag/router.py → 空输出（零 diff）
```

## 8. 审查总结

### 8.1 治理闭环（本模块核心价值）—— 实测成立
外部工具从注册到执行的完整守门链逐环节还原并验证：
1. **注册期**（mcp_client.py:130-156）：list_tools → 重名跳过（L142-144，防覆盖内置 10 工具）→ register 硬编码 `approval="required"` + `no_retry=True` + `group=None`（L145-153），inputSchema 直作 args_schema 复用 083 jsonschema 校验。
2. **请求期二维守门**（react.py:359-361）：阶段粒度 + allowed_tools 白名单独立判因，两 agent 端点（main.py:745/822）与 langgraph execute_tools 节点（langgraph_react.py:174-175）三路汇入同一闸，**无绕过口**。
3. **run._precheck**（tool_registry.py:224-238）：审批闸 required → pending 落库 → 拦截提示喂回 LLM；白名单拒绝发生在执行层（run 之前），不提交审批申请（test_unauthorized_no_approval_submission 断言 await_count==0）。
4. **执行期**：wait_for 15s 围栏 + no_retry=True 不自动重放副作用；结果归一化四分支（isError/structuredContent 优先/文本拼接/空占位）+ 截断 2000。
5. **关闭期**（main.py:180-181 + mcp_client.py:191-208）：close 幂等、逐层 try/except 不因清理失败失败。

### 8.2 兼容性红线 —— 逐字核验
- 默认全关路径：enabled=false → init_ext L94-95 首行短路（`test_disabled_zero_spawn` 断言 stdio_client 0 次）→ agent_allowed_tools 返回 None → 两端点 allowed_tools=None → react.py L359 守门条件短路 → 存量行为零变化（test_agent_endpoint_default_allows_builtin + 受影响存量 204 全绿实证）。
- 073 重试语义：`_NO_RETRY_TOOLS` 一字未改、TimeoutError 分支先判结构未动、默认 no_retry=False → `test_no_retry_default_keeps_073_semantics` + test_tool_retry_dedup.py 24 项全绿。
- tool_registry `__init__` 前次编辑事故的重复赋值块已清理（现 L162-182 单次赋值链，纯删除零行为变化，与 changelog 声明一致）。

### 8.3 结论
Developer 的 WP-A~G 实现与 plan/AC 一致，changelog 声明（34 项测试、204 受影响存量、AST 113/19、init_ext 28 行、五路 fail-open、语义矩阵）经独立复跑与复算**全部成立**。4 项 LOW（测试桥挂载生产类 / 超时逐段口径 / 握手失败子进程延迟回收 / changelog 分组小误差）+ 2 项备忘均非阻塞，已附建议。

**建议 Tester 重点复核**：AC-36 全量回归（预期 1526/6 基线零新增失败）；AC-16/17 lifespan 挂接（可结合 fail-open 冒烟：`PW_MCP_EXTERNAL_ENABLED=true` + 坏 command 启动 → /health 200）；AC-22 样例 server 独立启动；真实 E2E 审批链路（AC 验证命令表"真实 E2E"行，LLM 行为性尽力项）；AC-39 默认配置 10 工具零变化（import 链冒烟）。

---

## 修复轮回审（2026-09-06）

> 回审范围：**聚焦修复轮，不重开全套审查**（§4 的 LOW-①/④ 及 2 项备忘维持原结论）。审查对象仅两处 diff：`ai_service/agent/mcp_client.py` `_spawn_session`（L110-138，LOW-③ 深层根因修复）+ `ai_service/tests/agent/test_mcp_client.py` `test_handshake_timeout_fail_open`（L289-326，假绿测试重写）。根因机理经安装版 mcp SDK 源码独立佐证：`stdio_client` 为 `@asynccontextmanager`，其内部 anyio task group 在 yield 之前进入（.venv/Lib/site-packages/mcp/client/stdio.py:79 → :85）——进入与退出必须同 task，wait_for 临时 task 方案结构性不可行，根因分析成立。

### 结论

- **✅ PASS（0 阻塞 / 0 重大 / 1 LOW 观察项 + 1 备忘）**

### 核查点逐条结论

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **asyncio.timeout 用法（Python 3.11）** | ✅ | venv 实测 Python 3.11.15（`asyncio.timeout` 可用，且定向测试真实走过该路径，<3.11 会 AttributeError）。mcp_client.py:129-133——`async with asyncio.timeout(settings.mcp_external_timeout)` 包住握手全程（stdio `__aenter__` / ClientSession `__aenter__` / initialize 三段共享同一 deadline）；`asyncio.timeout` 到期对**当前 task** `task.cancel()`（CPython Lib/asyncio/timeouts.py，无 ensure_future），上下文进入与 close 退出的 task 归属不变 → anyio scope 跨 task 报错根除。附带收益：原 LOW-② 的"逐段超时 4×10s"收敛为握手段整体 1×（list_tools 仍独立一段 L148-149，最坏 2×），LOW-② 部分吸收 |
| 2 | **except BaseException + close + raise 语义** | ✅ 不吞异常 | mcp_client.py:134-138——捕获 BaseException 是**必须**的：超时在块内表现为 CancelledError，转 TimeoutError 发生在 `asyncio.timeout.__aexit__`（位于本 try 之外），只捕 Exception 会漏掉超时；`raise` 原样重抛不吞（含外部取消的 CancelledError——`__aexit__` 的 uncancel 簿记区分超时取消与外部取消，外部取消不会被误转 TimeoutError）；KeyboardInterrupt/SystemExit 也先回收再重抛（优于捕 Exception）。`await self.close()` 在 except 块内运行时无 pending 二次取消（timeout handler 只 cancel 一次）；close 内部 `except Exception`（L209/L216）不会捕获容错路径中的 CancelledError（3.8+ 它是 BaseException），语义兼容 |
| 3 | **fail-open 链完整性** | ✅ | re-raise 后汇入 init_ext 既有单点捕获：mcp_client.py:103-106 `except Exception` → warning + `return len(self.registered)`（TimeoutError 是 Exception 子类，必达）；disabled/空 command 早退（L94-98）、`_registry` 赋值（L99）、allowed_tools 语义矩阵（L220-234）、close 幂等（L201-218）全部零触碰。独立探针实证：timeout=0.01 + 慢 session → warning"fail-open" + 返回 0，进程存活 |
| 4 | **与 close() 幂等实现配合** | ✅ | close 按段判空（L206/L213）——超时发生在 stdio 进入期时 `_session_cm` 仍为 None 自动跳过，只退已进入的 stdio；字段复位（L211-212/218）位于各段 try/except **之后**，`__aexit__` 抛 Exception 被容错后仍复位为 None。探针实测超时后 `_stdio_cm`/`_session_cm` 双双为 None；与 lifespan finally 的 close（main.py:180-181）双调用幂等不冲突。`_stdio_cm = stdio_client(params)`（L127）置于 timeout 块外正确——asynccontextmanager 调用仅构造 CM 对象（同步无阻塞），构造失败则无上下文被进入、无需清理 |
| 5 | **测试重写真实性（去假绿）** | ✅ | test_mcp_client.py:289-326——`_SlowSession.__aenter__` 真实 `asyncio.sleep(1.0)`（L302）+ timeout=0.01（L295）→ 超时真实发生在 await 点（asyncio.timeout 到期取消），不再是 mock 缺方法走 AttributeError 的假绿；patch 点正确（`agent.mcp_client.stdio_client`/`ClientSession` 均为模块级 from-import 名，L318-320）。判别力核验（非 vacuous）：若回收缺失 → `_session_cm` 为 _SlowSession 实例非 None → 断言失败；若超时不触发 → 走到 `_register_tools` 的 `list_tools()` AttributeError，且两字段非 None → 断言仍失败。边界说明：anyio task 绑定本身属 SDK 交互，hermetic fake 无法复现（fake 非 anyio 实现）——该项由真实 filesystem server 探针实证（changelog §六"复跑 close 警告消失"），测试负责超时/回收/fail-open 链路，分工合理 |

### 发现的问题（全部非阻塞）

| # | 文件 | 行号 | 描述 | 级别 |
|---|------|------|------|------|
| 1 | agent/mcp_client.py | 103-106 | 超时路径 warning 的异常 detail 为空串：`asyncio.timeout.__aexit__` 转换抛 `raise TimeoutError from exc_val`（无消息文本，实测 `str(TimeoutError())==''`），日志呈现为"…fail-open…）: "后无原因。**非回归**（修复前 wait_for 同样抛无消息 TimeoutError，行为一致），仅日志可读性。 | LOW |
| B3 | agent/mcp_client.py | 129-138 | （备忘）极窄竞态：握手在 deadline 最后瞬间抛非取消异常且 close 耗时跨过 deadline 时，close 内部 await 会被 timeout 二次取消注入 CancelledError（close 的 except Exception 不捕），原异常被顶替转为 TimeoutError、个别状态字段可能留待 shutdown close 复位。fail-open 结果不变、单例一次性 init 无累积，v1 可接受，无需动作。 | 备忘 |

### 独立复跑输出（Reviewer，2026-09-06）

```
环境：     .venv Python 3.11.15；py_compile agent/mcp_client.py + tests/agent/test_mcp_client.py → COMPILE OK
定向：     pytest tests/agent/test_mcp_client.py -q  → 34 passed, 2 warnings in 16.79s（预期 34 passed ✓）
SDK 佐证： mcp stdio_client @asynccontextmanager，task group 进入于 yield 前（stdio.py:79/:85）→ 同 task 约束证实
超时探针（独立于 pytest，timeout=0.01 + 慢 session）：
           WARNING:agent.mcp_client:MCP 外部接入失败（fail-open，内置工具不受影响）:   ← detail 为空（LOW-1）
           returned: 0 | stdio_cm: None | session_cm: None（同 task 回收实证）
```
