# 审查报告 — Module-083 工具治理

> Reviewer: 2026-09-01 | 审查对象：`specs/module-083-tool-governance/`（plan.md / acceptance-criteria.md / changelog.md）+ 6 个生产文件 + 1 个测试文件
> 审查方法：全文件通读（tool_registry.py 438 行 / react.py 547 行 / config.py 438 行 / database.py 534 行 / main.py 1273 行 / test_tool_governance.py 789 行）+ 独立测试复跑 + git diff 逐文件核验 + AST 行数/方法长度/空 catch 机械化审计

## 1. 审查结论

- **结论：✅ 通过（0 阻塞 / 0 重大 / 5 项 P3 非阻塞建议）**

守门总序、兼容性红线、幂等时机、安全语义四大审查要点全部实测通过；红线文件零 diff 独立验证成立；行数双口径（Developer AST 185 / Reviewer 逐行 197）均 ≤ 200；新增 43 项测试独立复跑全绿；存量套件零改动零回归（4 项失败均为 module-028 proxies 环境性基线，与 changelog 声明逐字一致）。

## 2. 问题列表（如有）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | agent/tool_registry.py | 131-137（`_request_approval`） | 先查后插（check-then-insert）存在 TOCTOU 竞态：并发同工具调用可双插 pending（表无 (tool_name) 唯一约束）。当前 10 工具全 auto 不触达，机制预留路径，无害。 | P3 | 留 module-084 落 required 工具时加部分唯一索引（`UNIQUE (tool_name) WHERE status='pending'`）或改 `INSERT ... WHERE NOT EXISTS` 原子化 |
| 2 | main.py | 1219-1236（`list_tool_approvals`） | GET 端点无 try/except：DB 不可用时 FastAPI 默认 500 而非 `{code:1}`。与既有兄弟端点（list_crawl_sources）同待遇，管理面端点，可接受。 | P3 | 如需统一失败响应，后续模块按现有端点惯例补 code=1（非本模块阻塞项） |
| 3 | agent/tool_registry.py | 60（`_fingerprint`） | 实现用 `json.dumps(args, sort_keys=True, ensure_ascii=False)`，plan §WP-B 草图为 `json.dumps(args, sort_keys=True)`——同进程内确定性一致，键序无关语义不受影响，功能零差异。 | P3 | 无（仅记录口径差异；changelog 已如实写明 ensure_ascii=False） |
| 4 | tests/agent/test_tool_governance.py | 全文件 | AC-41（args 非 JSON 序列化 → `_fingerprint` 返回 None 跳过幂等）**无直接单测**——行为已实现（tool_registry.py:62-64 try/except TypeError → None），但防御分支未机械断言。changelog 将 AC-41 标 ✅ 属"实现核验"而非"测试覆盖"。 | P3 | 后续补 1 行用例（传含不可序列化对象 args，断言 func 执行且不拦）；LLM tool_calls 参数必为 JSON，理论不可达，非阻塞 |
| 5 | agent/tool_registry.py | 276（`_record_fingerprint`） | 超时判定依赖与返回文案 `f"(工具 {self.name} 执行超时)"` 精确字符串比对——若未来某工具真实输出恰为该串会误判"未成功执行"跳过指纹。代码内已注释说明（与 react.py `_EMPTY_RESULT_MARKERS` 红线文本耦合先例对齐），超时文案本身是存量测试红线不可改。 | P3 | 保持现状（文档化取舍）；如未来解耦，可改由 _execute 返回结构携带"是否超时"标记 |

**备注（非问题）**：WP-E 提示文案用全角括号「（工具 …」与存量阶段守门文案一致（plan 草图为半角，系示意非契约）；AC-30 仅要求含"权限白名单"，实测满足。

## 3. 验收标准核对

| 验收项 | 对应代码 / 测试 | 状态 |
|--------|----------------|------|
| AC-1 校验前置（非法类型不执行 / wait_for 0 次） | tool_registry.py `_schema_error` L70-105（required 置空 L87）+ `test_invalid_type_blocked_no_execute` | ✅ |
| AC-2 合法 args 正常执行 | `test_valid_args_executes` | ✅ |
| AC-3 缺省回退契约（run({}, ctx) 非拒绝） | L87 `{**schema, "required": []}` 浅拷贝 + `test_empty_args_fallback_contract` | ✅ |
| AC-4 run 容忍 ctx=None | L212-215 getattr 短路 + `test_ctx_none_no_crash` | ✅ |
| AC-5 非 dict args → "参数应为 object" | L82-83 + `test_non_dict_args_rejected` | ✅ |
| AC-6 requirements 含 jsonschema==4.26.0 + 冒烟 | requirements.txt +3 行；实测 `importlib.metadata.version('jsonschema')` = 4.26.0 | ✅ |
| AC-7 ReactContext.executed_fingerprints 每请求独立 | react.py:100 + `test_per_request_isolated` | ✅ |
| AC-8 只读 7 工具同参二次拦截、func 1 次 | `_IDEMPOTENT_TOOLS` L47-51（7 项核对）= `test_same_args_second_blocked` | ✅ |
| AC-9 参数键序无关 | `_fingerprint` L56-68 sort_keys=True + `test_fingerprint_ignores_key_order`/`test_key_order_insensitive_blocked` | ✅ |
| AC-10 异参放行 | `test_different_args_executes` | ✅ |
| AC-11 失败（空串）不记指纹可重放 | `_record_fingerprint` L270（`not result` 短路）+ `test_failure_not_recorded_replayable` | ✅ |
| AC-12 超时不记指纹 | L271 精确文案判定 + `test_timeout_not_recorded_replayable` | ✅ |
| AC-13 排除清单（generate/verify/note 照常执行） | L47-51 白名单设计排除 + `test_excluded_tools_not_intercepted` | ✅ |
| AC-14 MCP 轻量 ctx / None 零拦截 | L213 getattr 短路 + `test_lightweight_ctx_and_none_no_interception` | ✅ |
| AC-15 073 重试成功只记 1 次指纹 | `test_retry_success_records_once`（func 计数 2、指纹 1、三次拦截） | ✅ |
| AC-16 工具级 timeout 透传 wait_for + 精确文案 | `__init__` L169-170 + `_execute` L236/242 + `test_timeout_param_forwarded`（wait_for 收到 0.01） | ✅ |
| AC-17 默认 15.0 来源 config + 10 工具全 15.0 | L170 + `test_default_timeout_from_settings_and_builtin_attr` | ✅ |
| AC-18 config tool_default_timeout: float = 15.0 | config.py:153（PW_TOOL_DEFAULT_TIMEOUT 映射，env_prefix="PW_" 实测） | ✅ |
| AC-19 存量超时文案测试全绿 + 不含秒数 | `test_timeout_marker_exact_string`（断言 "15" not in result）+ 受影响存量 120/0 | ✅ |
| AC-20 approval 字段默认 "auto" + 10 工具全 auto | `__init__` L172-175 / `register` L309-311 + 同 AC-17 用例断言 | ✅ |
| AC-21 auto 工具 `_approval_allowed` 0 次调用 | L221-223 短路 + `test_auto_tool_zero_approval_db_access` | ✅ |
| AC-22 required + 无 approved → 提示 + 不执行 + 插申请 | L224-230 + `test_required_no_approval_blocks_and_submits`（requester 断言） | ✅ |
| AC-23 pending 去重不重复插 | L133-135 + `test_request_approval_dedup_pending` / `..._inserts_when_no_pending` | ✅ |
| AC-24 approved 放行（工具级） | L221 + `test_required_approved_allows` | ✅ |
| AC-25 DB 异常 fail-closed 拒绝 | L109-113 + `test_approval_db_error_fail_closed` / `test_required_db_down_blocks_execution` | ✅ |
| AC-26 GET 列表字段 + status 过滤（缺省 pending） | main.py:1219-1236 参数化 + `test_get_lists_pending_fields` / `test_get_status_filter` | ✅ |
| AC-27 POST approve/reject / 非法 action / 不存在 / 已处理 | main.py:1241-1264 + `TestApprovalEndpoints` 6 用例 | ✅ |
| AC-28 DDL 幂等 + init_db 挂接 | database.py:126-151（拆 ";" 执行）+ init_db L292-293 + `test_ensure_ddl_idempotent` / `test_init_db_hooks_approval_table` | ✅ |
| AC-29 三处 allowed_tools 参数 | react.py:333/379/425 签名 | ✅ |
| AC-30 白名单外拒绝 + result_ok=false + 提示含"权限白名单" | react.py:359-363 两维守门 + `test_outside_whitelist_denied` | ✅ |
| AC-31 白名单内正常 | `test_inside_whitelist_allows` | ✅ |
| AC-32 None = 全量（存量零回归） | react.py:360 `allowed_tools is not None` 条件 + `test_none_allows_all` | ✅ |
| AC-33 langgraph 零改动 | `git diff -- ai_service/agent/langgraph_react.py` 空（独立复跑） | ✅ |
| AC-34 react_agent→react_loop→execute_tool_with_log 透传 | react.py:410-411 / 523-524 + `test_transparent_chain_through_react_agent` | ✅ |
| AC-35 float 整数字面已知边界（1.0 被拒） | 未做规整（plan §8 明确本模块不加）+ changelog 遗留清单 #1 如实标注 | ✅（如实标注） |
| AC-36 指纹每请求独立 + 幂等命中无死锁 | `test_per_request_isolated` + `test_idempotent_hit_loop_continues`（循环正常结束） | ✅ |
| AC-37 审批闸先于阶段守门 / 校验 | `_precheck` L221 审批在前 + `test_approval_gate_precedes_schema_validation` | ✅ |
| AC-38 config 0/负值不规整 | `__init__` L169 直接赋值无隐式规整 | ✅ |
| AC-39 空 args 三层全兼容 | `test_empty_args_fallback_contract` + 指纹 sha256(name\|{}) + auto 短路 | ✅ |
| AC-40 jsonschema 内部异常 fail-open + warning | L88-89 + `test_jsonschema_internal_error_fail_open` | ✅ |
| AC-41 args 非 JSON 序列化 → 跳过幂等 | L62-64（try/except TypeError → None）；**无直接单测（见问题 #4）** | ✅（实现） |
| AC-42 POST 已处理 id → code 1 不崩 | `test_post_already_decided` | ✅ |
| AC-43 MCP 路径四态兼容 | run() 内三闸（mcp_server.py:90 复用，零 diff）+ 轻量 ctx 短路测试 + 存量 mcp 套件 120/0 | ✅ |
| AC-44 LLM 循环自愈（提示喂回不中断 SSE） | 拦截文本作为 tool 结果消息 + `test_idempotent_hit_loop_continues` | ✅ |
| AC-45 全量零新增失败 | Reviewer 范围内：tests/agent + tests/crawl = **442 passed / 4 failed**（4 个均为 TestChatWithTools proxies 环境基线，与 changelog §4.2 逐字一致）；全量 1526/6 口径留 Tester | ✅（范围内） |
| AC-46 存量测试零改动 | git status 仅 6 修改 + 1 新增；受影响存量 **120 passed / 5 deselected**（deselect 即 proxies 基线） | ✅ |
| AC-47 行为红线逐字（超时/空串/result_ok/预算/表结构） | 超时文案 L240 一字未改；失败空串 L258；result_ok 语义 execute_tool_with_log 未变；react_loop 计数点未动；TOOL_CALL_LOGS_DDL 零 diff | ✅ |
| AC-48 10 工具默认路径零变化 | 全部 timeout=15.0 / approval=auto / allowed_tools=None / 幂等仅 7 只读工具 | ✅ |
| AC-49 正常路径零开销 | auto 0 DB（测试断言 0 次）；校验纯函数 O(args)；`{**schema,"required":[]}` 浅拷贝；幂等内存 set + 1 次 sha256 | ✅ |
| AC-50 审批路径 1 SELECT + ≤1 INSERT | `_approval_allowed` L99-103（1 SELECT）+ `_request_approval` L130-138（1 SELECT + ≤1 INSERT） | ✅ |
| AC-51 审批 SQL 全参数化 | `:n` / `:s` / `:i` / `:r` 全部 text() 参数绑定，无拼接（逐行核验） | ✅ |
| AC-52 fail-closed / fail-open 语义不混淆 | `_approval_allowed` fail-closed（L109-113 注释"宁拒勿放"）vs `_request_approval`/`record_tool_call` fail-open（注释可辨） | ✅ |
| AC-53 校验错误不泄露内部细节 | L85 `e.message` 仅参数路径；日志不含堆栈/密钥 | ✅ |
| AC-54 生产代码 ≤200 行（AST 口径） | Developer 185 ✓；Reviewer 逐行口径 197（差异 = 多行 DDL 字符串内部 12 行 SQL 文本，双口径均 ≤200） | ✅ |
| AC-55 方法 ≤50 + docstring | 新增/改动方法全部 ≤50（run 6 / _precheck 12 / _execute 20 / _record_fingerprint 12 / 两端点 18-24）；public 方法全 docstring | ✅ |
| AC-56 无空 catch | AST 审计：5 文件 0 空 ExceptHandler；全部 except 带 logger + 注释（fail-open/fail-closed 性质标注） | ✅ |
| AC-57 变更文件范围 | git status 精确 6 修改 + 1 新增；mcp_server/langgraph_react/engine/router 四文件 git diff 空 | ✅ |
| AC-58 无新 ADR | docs/adr（specs/adr）清单止于 0019，决策记录入 changelog | ✅ |

## 4. 铁律合规检查

| 铁律 | 检查结果 | 证据 |
|------|----------|------|
| #2 新增生产代码 ≤200 行 | ✅ | git diff numstat 合计 +337（全行）；AST 口径 Developer 185 / Reviewer 197，均 ≤200；测试代码 789 行不计入 |
| #3 方法 ≤50、类 ≤500 | ✅ | 新增/改动方法全 ≤50；>50 项（register_builtin_tools 69 / react_loop 123 / lifespan 62 / chat_agent 69 / chat_agent_langgraph 71 / AgentTool 类 145 / ToolRegistry 54 / ReactContext 57 / Settings 424）经 `git show HEAD` 逐一核验为**基线既有**，非本模块新增；类均 ≤500 |
| #4 public 方法 docstring / 魔法数字命名 | ✅ | 全部新方法带 docstring；硬编码 15 → settings.tool_default_timeout；`_IDEMPOTENT_TOOLS`/`_NO_RETRY_TOOLS` 常量命名 |
| #5 禁空 catch | ✅ | AST 机械化审计 0 空 handler；每处 except 带 logger + 语义注释（fail-open/fail-closed 可辨） |
| #8 日志禁敏感信息 | ✅ | 逐条 grep 3 个生产文件全部 logger 行：审批决定日志仅 id/action/status；守门拒绝日志仅 name/allowed_tools/phase；审批辅助 warning 仅异常信息；args/token 零日志明文 |
| #9 禁 SQL 拼接 | ✅ | approval SELECT/INSERT/UPDATE 全参数化（`:n`/`:s`/`:i`/`:r`/`:args`）；DDL 为静态常量字符串 |
| #11 记忆收口 | ⚠️ 记录 | project-context.md module-083 行仍为"🔵 规划中"（Planner 产物），协调者按 changelog 遗留 #6 决定何时更新为 Developer 完成态；本审查不阻塞 |

## 5. 审查总结

### 5.1 守门总序（硬约束 1）—— 实测成立
还原完整顺序并逐层验证：
1. **react 循环层二维守门**：react.py:359 `tool is not None and (not _phase_allows(...) or (allowed_tools is not None and name not in allowed_tools))` —— 阶段粒度（module-058）与 Agent 粒度（083 WP-E）独立判因，白名单外 → "权限白名单"提示、阶段外 → 存量文案逐字保留，均 result_ok=false + warning 审计可见。
2. **run._precheck 三闸**：tool_registry.py:210-227 —— 审批（L221，仅 required，auto 短路 0 DB）→ schema 校验（L225，required 置空浅拷贝）→ 幂等拦截（L227，同参二次提示）。任一拦截不进 `_execute`（不进 073 重试分支）。
3. **_execute**：L234-258 原 073 主体原样搬入，仅 `timeout=15` → `self.timeout`；超时永不重试、排除清单、失败空串逐字保留。
4. **成功后才记指纹**：`_record_fingerprint` L260-281 —— 空串/超时文案不记 → 同参可重放，与 073 自洽；`test_failure_not_recorded_replayable` / `test_timeout_not_recorded_replayable` / `test_retry_success_records_once` 三点实证。
5. MCP 路径（mcp_server.py:90，文件零 diff）仅经 run 内三闸，无 execute_tool_with_log —— 与 plan §7 一致。

### 5.2 兼容性红线（硬约束 2）—— 逐字核验
- 超时精确文案 `"(工具 X 执行超时)"`：tool_registry.py:240/250 一字未改；`test_timeout_marker_exact_string` 断言不含秒数；`git diff` 复核 _execute 其余逻辑零改动（-9 行全部为重构替换）。
- 失败返回空串：L254-258 逐字。
- result_ok 语义：execute_tool_with_log L351-356 与 HEAD 一致（工具不存在/异常才 false；run 内部返回提示属正常路径 true）。
- tool_call_logs 表结构：database.py diff 仅新增 APPROVAL_REQUESTS_DDL 块，`TOOL_CALL_LOGS_DDL` 零 diff。
- 预算计数：react_loop L513-515 `tool_count += 1` / `phase_count += 1` 位置未动，各闸拒绝仍计 1 次（与阶段守门同口径）。
- 存量 `run({}, None)` 契约：`_schema_error` 不触 ctx、`_precheck`/`_record_fingerprint` 均 getattr 短路 —— `test_ctx_none_no_crash` 实证。

### 5.3 安全语义 —— 实测正确
- 审批 DB 异常 fail-closed（tool_registry.py:109-113，拒绝执行）vs 观测/落库路径 fail-open（`_request_approval`/`record_tool_call`/schema 校验）两语义注释区分清晰，未混淆。
- token/args 不入日志明文：逐条 grep 全生产文件 logger 行证实（详见铁律 #8 证据列）。
- 参数校验错误仅透出 `e.message`（AC-53）。

### 5.4 验证输出（Reviewer 独立复跑）
```
定向：              pytest tests/agent/test_tool_governance.py -v     → 43 passed
存量回归：          pytest tests/agent/ tests/crawl/ -q               → 442 passed / 4 failed
                    （4 failed 全部 TestChatWithTools，根因 'proxies' keyword ——
                      module-028 langchain-openai 环境基线，与 changelog §4.2 逐字一致）
受影响存量：        test_mcp_server + test_agent_tools + test_tool_retry_dedup
                    + test_tool_call_logs -k "not ChatWithTools"      → 120 passed / 5 deselected
py_compile：        agent/tool_registry.py react.py src/config.py src/database.py main.py → COMPILE OK
红线核验：          git diff --stat -- mcp_server.py agent/langgraph_react.py
                    rag/engine.py agent/router.py                      → 空输出（零 diff ✓ 独立验证）
依赖/配置冒烟：     jsonschema 4.26.0；settings.tool_default_timeout=15.0 /
                    tool_idempotency_enabled=True / tool_approval_enabled=True
行数审计：          自动脚本（ast 口径）：tool_registry 111 / react 17 / main 45 /
                    config 3 / database 20（含 DDL 字符串 12 行，Developer 口径 8）/ req 1
                    → Reviewer 逐行 197 ≤ 200，Developer AST 185 ≤ 200，双口径过线
```

### 5.5 结论
Developer 的 5 项 WP 实现与 plan/AC 一致，changelog 声明（43 项测试、120/0 受影响存量、4 × proxies 基线、4 红线文件零 diff、185 行）经独立复跑与复算**全部成立**。唯一行数口径差异（database.py DDL 字符串内部 12 行）不影响 ≤200 判定。5 项 P3 建议非阻塞（预留机制 TOCTOU、GET 端点异常响应、AC-41 缺直接单测、指纹 ensure_ascii 口径、超时文案耦合），已附修建议，留后续模块按需处理。

**建议 Tester 重点复核**：AC-45 全量 1526/6（2 项真实 Redis 环境依赖）、AC-8/11/15 幂等 × 073 交互、AC-21/22 审批闸、AC-30/33 权限守门 + langgraph 零改动、真实端点冒烟 `GET/POST /ai/tools/approvals`（空表 200）。