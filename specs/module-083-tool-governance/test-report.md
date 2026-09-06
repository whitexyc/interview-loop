# 测试报告 — Module-083 工具治理（schema 校验 / 幂等 / 工具级超时 / 高风险审批 / Agent 级最小权限）

> Tester: 2026-09-01 | 测试对象：`specs/module-083-tool-governance/`（plan.md / acceptance-criteria.md / changelog.md）+ 6 个生产文件 + 1 个测试文件（tests/agent/test_tool_governance.py）
> 测试方法：指定命令独立复跑（定向 / 全量 / 受影响存量 / py_compile）+ 红线 git diff 核验 + 运行时属性实证 + 失败 6 项逐一根因重跑 + AST 行数独立复核

## 1. 验证命令执行结果（独立复跑）

| 验收项 | 验证命令 | 预期 | 实际 | 状态 |
|--------|----------|------|------|------|
| 定向单测 | `pytest tests/agent/test_tool_governance.py -v` | 全 passed | **43 passed** | ✅ |
| 全量回归 | `pytest tests/ -q` | 1526/6（4 proxies + 2 Redis）/3 skipped | **1526 passed / 6 failed / 3 skipped / 158 warnings**（6:36） | ✅ |
| 6 项失败根因重跑 | 逐类复跑 | proxies 基线 / Redis 环境 | 4×TestChatWithTools：`Client.__init__() got an unexpected keyword argument 'proxies'`（module-028 langchain-openai 基线）｜2×real_redis：`Timeout connecting to server`（Redis 6379 未启动，环境性） | ✅ 与 changelog §4.2 逐字一致 |
| 受影响存量 | `test_agent_tools + test_tool_retry_dedup + test_tool_call_logs + test_mcp_server -k "not ChatWithTools"` | 全 passed | **120 passed / 5 deselected**（5 deselected = 5 项 ChatWithTools） | ✅ |
| py_compile | `tool_registry.py / react.py / config.py / database.py / main.py` | COMPILE OK | **PY_COMPILE OK** | ✅ |
| 红线核验 | `git diff -- mcp_server.py langgraph_react.py engine.py router.py` | 空 | **空输出（零 diff）** | ✅ |
| 变更文件范围 | `git status --short` | 6 修改 + 1 新增 | 6 生产文件（tool_registry/react.py/main.py/config.py/database.py/requirements.txt）+ 1 新增测试；四红线文件零 diff | ✅ |
| 依赖冒烟 | `jsonschema` 版本 + import | 4.26.0 | **4.26.0，validate 可用** | ✅ |
| config 冒烟 | `settings.tool_default_timeout` 等 | 15.0 | **15.0 / tool_idempotency_enabled=True / tool_approval_enabled=True** | ✅ |
| 10 工具运行实证 | `register_builtin_tools().list_tools()` | 10 工具全 auto / 15.0 | **10 全 timeout=15.0 / approval=auto** | ✅ |
| 幂等清单实证 | `_IDEMPOTENT_TOOLS` / `_NO_RETRY_TOOLS` | 7 只读 / 2 排除 | **7 项**（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/re_search）；_NO_RETRY_TOOLS=generate_answer/verify_answer（073 基线）；note_to_self 不在幂等清单（AC-13 达成）；generate/verify/note 均不拦 | ✅ |

## 2. Reviewer 建议重点复核项

| 重点项 | 独立验证 | 结论 |
|--------|----------|------|
| **AC-45 全量 1526/6** | 全量复跑 1526 passed / 6 failed / 3 skipped；6 项失败逐一根因复跑确认 = 4×proxies 基线 + 2×真实 Redis 环境（PG 5432 / Redis 6379 / Docker 均不可达）；**新增 0 失败** | ✅ |
| **AC-8/11/15 幂等 × 073 交互** | `test_same_args_second_blocked`（只读 7 工具二次拦截、func 1 次）／`test_failure_not_recorded_replayable`（空串不记指纹可重放）／`test_timeout_not_recorded_replayable`／`test_retry_success_records_once`（重试成功 func 2 次、指纹 1 次、三次拦截）／`test_idempotent_hit_loop_continues`（无死锁）全 passed | ✅ |
| **AC-21/22 审批闸** | `test_auto_tool_zero_approval_db_access`（_approval_allowed 0 次调用）／`test_required_no_approval_blocks_and_submits`（提示+不执行+插 pending+requester）／`test_approval_gate_precedes_schema_validation`（审批先于校验）全 passed | ✅ |
| **AC-30/33 权限守门 + langgraph 零改动** | `test_outside_whitelist_denied`（拒绝+result_ok=false+提示含"权限白名单"）／`test_inside_whitelist_allows`／`test_none_allows_all`／`test_transparent_chain_through_react_agent`（react_agent→react_loop→execute_tool_with_log 透传）全 passed；**langgraph_react.py git diff 独立复跑为空** | ✅ |
| **真实端点冒烟 GET/POST /ai/tools/approvals** | ⚠️ **环境受限不可执行**：生产 DB 为 PostgreSQL（TCP 5432 不可达）、Redis 6379 不可达、Docker daemon 未运行；服务 lifespan `init_db()` 依赖 PG 无法启动。AC 表将该项标注"（可选，Tester）"。替代覆盖：6 项 `TestApprovalEndpoints` 单测（真实端点处理器 `list_tool_approvals`/`decide_tool_approval` 代码路径 + 字段/过滤/非法 action/不存在/已处理断言）全部 passed；端点 SQL 手工逐行核验全参数化（`:s`/`:i`） | ⚠️ 环境性受限（非代码缺陷），AC-26/27 由单测覆盖 ✅ |
| **AC-54 行数（Reviewer 口径 197）** | 独立复核：`git diff --numstat` 6 文件合计 **+337**（与 Reviewer 记录逐字一致）；AST 口径 Developer 185 / Reviewer 197，**双口径均 ≤200**；Tester 追加解释：337 原始行含空行/注释/DDL 字符串/整类改写 scoping，声明内代码行（排除 docstring/注释）229 属高估口径，不改变双口径结论 | ✅ |

## 3. 验收标准核对（AC-1 ~ AC-58 逐项）

| 验收项 | 验证证据（独立复跑 / 代码实证） | 状态 |
|--------|--------------------------------|------|
| AC-1 校验前置 | `test_invalid_type_blocked_no_execute`（提示含"参数错误"、func not called、wait_for 0 次） | ✅ |
| AC-2 合法 args 正常执行 | `test_valid_args_executes` | ✅ |
| AC-3 缺省回退契约 | `test_empty_args_fallback_contract`；代码 L85 `{**schema,"required":[]}` 浅拷贝 | ✅ |
| AC-4 run 容忍 ctx=None | `test_ctx_none_no_crash` | ✅ |
| AC-5 非 dict args | `test_non_dict_args_rejected`；L81"参数应为 object" | ✅ |
| AC-6 jsonschema 依赖 | requirements.txt +3 行；实测 4.26.0 / import ok | ✅ |
| AC-7 executed_fingerprints 每请求独立 | react.py L100；`test_per_request_isolated` | ✅ |
| AC-8 只读 7 工具同参二次拦截 | 运行实证 7 项清单精确；`test_same_args_second_blocked` | ✅ |
| AC-9 参数键序无关 | sort_keys=True；`test_fingerprint_ignores_key_order` / `test_key_order_insensitive_blocked` | ✅ |
| AC-10 异参放行 | `test_different_args_executes` | ✅ |
| AC-11 失败不记指纹可重放 | L256/258 `return ""`；`test_failure_not_recorded_replayable` | ✅ |
| AC-12 超时不记指纹 | L273 精确文案判定；`test_timeout_not_recorded_replayable` | ✅ |
| AC-13 排除清单 | 运行实证 generate/verify/note_to_self 均不在幂等清单；`test_excluded_tools_not_intercepted` | ✅ |
| AC-14 MCP 轻量 ctx / None 零拦截 | getattr 短路；`test_lightweight_ctx_and_none_no_interception` | ✅ |
| AC-15 073 重试只记 1 次指纹 | `test_retry_success_records_once`（func 2 / 指纹 1 / 三次拦截） | ✅ |
| AC-16 超时透传 wait_for + 精确文案 | `test_timeout_param_forwarded`（wait_for 收到 0.01）+ `test_timeout_marker_exact_string`（不含秒数） | ✅ |
| AC-17 默认 15.0 来源 config + 10 工具全 15.0 | 运行实证 10 全 15.0；`test_default_timeout_from_settings_and_builtin_attr` | ✅ |
| AC-18 config tool_default_timeout | config.py L153 实测 15.0 | ✅ |
| AC-19 存量超时文案测试全绿 | `test_timeout_marker_exact_string`；受影响存量 120/0 | ✅ |
| AC-20 approval 默认 "auto" + 10 工具全 auto | 运行实证 10 全 auto | ✅ |
| AC-21 auto 工具零 DB 访问 | `test_auto_tool_zero_approval_db_access`（0 次调用） | ✅ |
| AC-22 required 无 approved → 阻断+提交 | `test_required_no_approval_blocks_and_submits`（requester 断言） | ✅ |
| AC-23 pending 去重 | `test_request_approval_dedup_pending` / `test_request_approval_inserts_when_no_pending` | ✅ |
| AC-24 approved 放行 | `test_required_approved_allows` | ✅ |
| AC-25 DB 异常 fail-closed | `test_approval_db_error_fail_closed` / `test_required_db_down_blocks_execution` | ✅ |
| AC-26 GET 列表字段 + status 过滤 | `test_get_lists_pending_fields` / `test_get_status_filter`（真实处理器路径） | ✅ |
| AC-27 POST approve/reject/非法/不存在/已处理 | `TestApprovalEndpoints` 6 用例 | ✅ |
| AC-28 DDL 幂等 + init_db 挂接 | `test_ensure_ddl_idempotent` / `test_init_db_hooks_approval_table`；database.py L140-146 拆 ";" 执行 | ✅ |
| AC-29 三处 allowed_tools 参数 | react.py:333/379/425 签名 | ✅ |
| AC-30 白名单外拒绝 + result_ok=false + "权限白名单" | `test_outside_whitelist_denied`（record_tool_call 收到 False） | ✅ |
| AC-31 白名单内正常 | `test_inside_whitelist_allows` | ✅ |
| AC-32 None = 全量 | `test_none_allows_all`；代码 `allowed_tools is not None` 条件 | ✅ |
| AC-33 langgraph 零改动 | git diff 空（独立复跑） | ✅ |
| AC-34 透传链路 | `test_transparent_chain_through_react_agent` | ✅ |
| AC-35 float 整数字面已知边界 | changelog 遗留清单 #1 如实标注，本模块不加规整 | ✅（如实标注） |
| AC-36 指纹每请求独立 + 无死锁 | `test_per_request_isolated` / `test_idempotent_hit_loop_continues`（循环正常结束） | ✅ |
| AC-37 审批闸先于阶段守门 | `test_approval_gate_precedes_schema_validation`（审批在 run 内、阶段在 execute_tool_with_log，两闸顺序不冲突） | ✅ |
| AC-38 config 0/负值不规整 | L169 直接赋值无隐式规整（代码实证） | ✅ |
| AC-39 空 args 三层全兼容 | `test_empty_args_fallback_contract`（校验过 / 指纹 sha256(name\|{}) / auto 短路） | ✅ |
| AC-40 jsonschema 内部异常 fail-open | `test_jsonschema_internal_error_fail_open`（warning + 放行） | ✅ |
| AC-41 args 非 JSON 序列化跳过幂等 | L63-67 `except TypeError → None`（实现实证；无直接单测 = Reviewer P3 #4，非阻塞） | ✅（实现） |
| AC-42 POST 已处理 id → code 1 不崩 | `test_post_already_decided` | ✅ |
| AC-43 MCP 路径四态兼容 | mcp_server.py:90 复用 run()（零 diff）+ 轻量 ctx 短路测试 + 存量 mcp 套件 120/0 | ✅ |
| AC-44 LLM 循环自愈 | 拦截文本作为 tool 结果消息；`test_idempotent_hit_loop_continues` | ✅ |
| AC-45 全量 1526/6 新增 0 失败 | **独立复跑 1526 passed / 6 failed / 3 skipped**；6 失败逐一根因确认基线 | ✅ |
| AC-46 存量测试零改动 | 受影响存量 120 passed / 5 deselected（deselect = ChatWithTools 基线）；git status 仅 6+1 | ✅ |
| AC-47 行为红线逐字 | 超时文案 L245/253 一字未改；失败空串 L256/258；result_ok 语义 L356/371 未变；tool_count/phase_count L518/521 位置未动；TOOL_CALL_LOGS_DDL 零 diff（grep 实证） | ✅ |
| AC-48 10 工具默认路径零变化 | 运行实证 timeout=15.0 / approval=auto / allowed_tools=None / 幂等仅 7 只读 | ✅ |
| AC-49 正常路径零开销 | auto 0 DB（测试断言 0 次）；校验纯函数；浅拷贝；内存 set + 1 次 sha256 | ✅ |
| AC-50 审批路径 1 SELECT + ≤1 INSERT | L99-103（1 SELECT）+ L130-142（1 SELECT + ≤1 INSERT） | ✅ |
| AC-51 审批 SQL 全参数化 | `:n`/`:s`/`:i`/`:args` 全 text() 绑定，无拼接（逐行核验含端点 SQL） | ✅ |
| AC-52 fail-closed/fail-open 不混淆 | L111-113 注释"fail-closed 宁拒勿放" vs 申请/落库 fail-open 注释可辨 | ✅ |
| AC-53 校验不泄露内部细节 | L87 仅 e.message；日志无堆栈/密钥 | ✅ |
| AC-54 生产代码 ≤200 行 | numstat 合计 +337（与 Reviewer 一致）；AST 口径 Developer 185 / Reviewer 197，双口径 ≤200 | ✅ |
| AC-55 方法 ≤50 + docstring | 新增/改动方法全 ≤50（run 31/_precheck 23/_execute 25/_record_fingerprint 19/两端点 19/27）；public 方法带 docstring（代码实证） | ✅ |
| AC-56 无空 catch | 全部 except 带 logger + 注释（fail-open/fail-closed 标注，AST 审计复核） | ✅ |
| AC-57 变更文件范围 | git status 精确 6 修改 + 1 新增；四红线文件 git diff 空（独立复跑） | ✅ |
| AC-58 无新 ADR | docs/adr 清单止于 0019；决策入 changelog | ✅ |

## 4. 已知边界 / 备注

1. **真实端点冒烟未执行（环境性）**：PG 5432 / Redis 6379 均不可达、Docker daemon 未运行 → 服务无法启动（lifespan 依赖 PG `init_db`）。AC 表标注该冒烟为"（可选，Tester）"；端点行为已由 6 项 TestApprovalEndpoints 单测（真实处理器代码路径）覆盖。**不属于代码缺陷，与全量 2 项 real_redis 失败同根因。**
2. **AC-41 无直接单测**（Reviewer P3 #4）：行为已实现（`_fingerprint` except TypeError → None），理论不可达，非阻塞。
3. **TOCTOU 竞态**（Reviewer P3 #1）：审批 check-then-insert 无唯一约束，当前 10 工具全 auto 不触达，预留机制，留 module-084。
4. **全量套件中 158 warnings** 为存量 Pydantic/废弃警告，非本模块引入（定向集与受影响存量的警告均为存量源）。

## 5. 验收结论

- 审查人: Reviewer（2026-09-01，0 阻塞 / 0 重大 / 5 项 P3 非阻塞，已通过）
- 测试人: Tester（2026-09-01）
- 验收时间: 2026-09-01
- 结论: **[x] 通过**
- 统计: **验收通过 58/58**
- 备注: 全量回归 1526/6（6 = 4×module-028 proxies 基线 + 2×真实 Redis 环境性 Docker 未启动），**新增 0 失败**；受影响存量 120/0；定向 43/43；py_compile 全过；四红线文件（mcp_server/langgraph_react/engine/router）零 diff 独立复核成立；幂等 × 073 交互、审批闸、权限守门全部测试实证通过；Reviewer 5 项 P3 建议均非阻塞，留后续模块按需处理。