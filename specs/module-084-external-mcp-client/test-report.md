# 测试报告 — Module-084 外部 MCP 客户端接入（stdio 发现注册 + 治理约束 + 白名单透传）

> Tester: 2026-09-06 | 测试对象：`specs/module-084-external-mcp-client/`（plan.md / acceptance-criteria.md / changelog.md / review-report.md）+ 3 个新增文件 + 5 个修改文件 + tests/agent/test_mcp_client.py（34 项）
> 测试方法：命令表全项独立复跑（不采信 changelog/review-report）+ 全量差异逐根因重跑归类 + 红线 git diff 逐文件归属甄别 + 独立真实 stdio 子进程握手冒烟（非测试进程）+ AC-30/AC-35 运行时补充探针 + AST 行数/方法长度独立复算 + 4 项 LOW 逐项独立验证

## 1. 验证命令执行结果（独立复跑）

| 验收项 | 验证命令（ai_service 目录） | 预期 | 实际 | 状态 |
|--------|---------------------------|------|------|------|
| 定向单测 | `pytest tests/agent/test_mcp_client.py -q` | 34 passed | **34 passed, 2 warnings（42.49s）** | ✅ |
| 全量回归 | `pytest tests/ -q` | 基线新增 0 失败 | **1564 passed / 2 failed / 3 skipped / 158 warnings（422.90s = 7:02）**，差异逐项归因见 §2（新增 0 失败成立） | ✅ |
| 受影响存量 | `pytest tests/agent/test_agent_tools.py tests/agent/test_tool_retry_dedup.py tests/agent/test_tool_governance.py tests/agent/test_tool_phase_split.py tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py tests/core/test_rerank_langgraph.py -q` | 204 passed | **204 passed, 2 warnings（84.58s）**（存量零改动实证） | ✅ |
| py_compile | `py_compile agent/mcp_client.py agent/tool_registry.py agent/langgraph_react.py main.py src/config.py scripts/mcp_sample_server.py` | COMPILE OK | **PY_COMPILE OK** | ✅ |
| config 冒烟 | `settings.mcp_external_*` | `False [] [] 10.0` | **False [] [] 10.0**（默认全关） | ✅ |
| AC-15 env 映射 | 进程环境注入 `PW_MCP_EXTERNAL_ENABLED/COMMAND/TOOLS`（不动 .env） | 映射生效 | **True ['python', 'scripts/mcp_sample_server.py'] ['ext_append_log'] 10.0**（JSON 数组解析正确） | ✅ |
| 红线 status | `git status --short rag/engine.py rag/router.py mcp_server.py` | 无输出 | **无输出（零 diff）** | ✅ |
| 红线 diff 甄别 | `git diff` react.py / database.py / requirements.txt | 084 归属零 | **逐块甄别全部为 083 遗留**（executed_fingerprints + allowed_tools 二维守门 / APPROVAL_REQUESTS_DDL / jsonschema==4.26.0）+ 环境遗留（openai==1.109.1 proxies 修正、onnxruntime HHEM ONNX、hhem_loader.py 双路径加载）——零 084 归属 | ✅ |
| 内置工具契约 | `registry.list_tools()` 运行探针 | `10 True True` | **10 True True**（10 工具 no_retry 全 False / approval 全 auto，AC-39 实证） | ✅ |
| 依赖冒烟 | `mcp.client.stdio` import + 版本 | 1.26.0 | **1.26.0**（client 端可导入，零新依赖实证） | ✅ |
| 真实握手冒烟（AC-22/23，非测试进程） | `stdio_client(StdioServerParameters(sys.executable, scripts/mcp_sample_server.py))` 独立脚本 | list_tools 2 实名 + 真实调用 | **LIST_TOOLS: ['ext_current_time', 'ext_append_log']；CALL_TIME: 2026-09-06T01:45:55+00:00 isError=False；CALL_LOG 文件真实追加（grep 实证后清理恢复原状）** | ✅ |

## 2. 全量回归差异逐根因归类（简报预期 1560/6/3+1 error vs 实测 1564/2/3，逐项重跑不轻信）

| # | 差异 | 根因（独立复跑证据） | 归类 |
|---|------|---------------------|------|
| 1 | **+4 passed**（4×module-028 proxies 基线失败不再失败） | `tests/agent/test_agent_tools.py::TestChatWithTools` 复跑 **5 passed**；根因是工作树 requirements.txt 已含 `openai==1.109.1` 修复（注释原文"2026-09-01 实测 proxies 基线 4 失败清零"）——review-report §6 已甄别为**环境遗留（本模块前已存在）** | 环境性（非 084 引入，084 前已修复） |
| 2 | **-4 failed**（6 → 2） | 同上：4 项 proxies 失败转为通过 | 环境性 |
| 3 | **2 failed**（test_llm_chain real_redis + test_cache real_redis） | 逐项复跑：`Redis 缓存不可用 (连接失败): Timeout connecting to server`（cache.py:89）+ 端口探测 127.0.0.1:6379 **NOT reachable** | 环境性（Redis 未启动，与 083 基线逐字同因） |
| 4 | **1 error 未出现**（scripts/test_models.py 陈旧脚本） | `pytest tests/ -q` 不收集 scripts/（范围外）；直接运行 `pytest scripts/test_models.py` 仍 **1 error**——陈旧问题原样存在，零 084 关系。module-083 实测行（1526/6/3）同样无该 error（其亦为 tests/ 范围运行） | 收集范围差异（陈旧问题未变化） |
| — | **算术自洽校验** | 083 基线收集量 1526+6+3=1535，+34 新增 = **1569**；实测 1564+2+3 = **1569** ✓ 逐项对账无缺漏 | — |

**结论：新增 0 失败成立。** 2 项失败全部为 Redis 未启动环境性（module-083 基线内）；4 项 proxies 差异系环境遗留修复（先于本模块存在）所致的基线数字自然改善，非本模块行为变化。

## 3. Reviewer 4 项 LOW + 2 备忘独立验证（逐项）

| # | Reviewer 发现 | 独立验证 | 结论 |
|---|--------------|---------|------|
| LOW-1 | 测试桥 `_register_tools_public` import 时挂载生产类（test_mcp_client.py:804-809） | 读文件实证 L809 `ExternalMCPClient._register_tools_public = _register_tools_public` 模块级执行；仅测试进程、不改生产行为 | **属实，非阻塞**（建议后续改用例内直接调私有方法或 monkeypatch） |
| LOW-2 | 超时围栏逐段而非整体（最坏 ≈4×timeout） | mcp_client.py L123-124 / L126-127 / L128 三段各得完整 timeout + L138 list_tools 再一段 = 4 段独立 wait_for | **属实，非阻塞**（有界 fail-open 不死阻塞；v1 可接受） |
| LOW-3 | 握手中途失败不清理已进入 CM，子进程存活至 shutdown close | init_ext except 分支 L103-106 不调 close()；`_stdio_cm` 保持在实例（L122 已赋值），close()（L203-208）可达并终结；init_ext 每进程一次无累积 | **属实，非阻塞**（有界；可在 except 分支补 close） |
| LOW-4 | changelog 测试分组口径误差（声明 lifespan 3/样例 3，实为 2/4） | 逐类清点：TestNoRetry 3 + TestInitExt 6 + TestExtCall 7 + TestAllowedToolsMatrix 4 + TestConfig 2 + **TestLifespan 2** + TestEndpointWhitelist 3 + TestLanggraphAllowedTools 3 + **TestSampleServer 4** = 34 ✓ | **属实，非阻塞**（总数 34 正确，文档勘误即可） |
| 备忘 B1 | conftest 未重置 session/_stdio_cm/_session_cm | conftest.py:285-291 仅重置三配置 + registered/_registry；通读 34 用例确认**无任何用例向单例写这三个字段**（真实子进程用例用局部实例 + finally 清理） | **属实，当前无污染路径**（未来如有单例真实 init_ext 用例需扩充） |
| 备忘 B2 | enabled+空 command → agent_allowed_tools 返回 None | mcp_client.py L96-98 早退于 L99 `self._registry = reg` 之前 → L221 返回 None；该路径外部零注册，None 无未授权放行对象 | **属实，安全方向，非缺陷** |

## 4. 补充独立探针（Tester 追加，非既有测试）

| 探针 | 方法 | 结果 |
|------|------|------|
| **AC-30 参数校验继承** | 真实 `_register_tools` 注册（inputSchema required=[content]）→ run({"content":123}) 类型违规 | **"(工具 ext_append_log 参数错误: 123 is not of type 'string')"，call_tool 零执行** ✅。注：AC-30 示例"缺必填"按 083 置空 required 契约放行（tool_registry.py:70-92 docstring 明示"MCP 外部调用依赖"该缺省回退契约；mcp_client.py docstring 同引）——AC 措辞与 083 契约相抵属**文档瑕疵非代码缺陷**；真实 server 侧 FastMCP pydantic 校验兜底返回 isError 可读提示，无未校验执行面 |
| **AC-35 并行不串话** | 真实样例 server 单 session 上 asyncio.gather 3 并发 call_tool（1×ext_current_time + 2×ext_append_log 不同 marker） | 三结果各自精确对应（A 无 B marker、B 无 A marker）、时间戳正确、mcp_sample_out.log 双 marker 落盘（探针行已清理）✅ |
| **AST 行数复算（AC-45）** | ast.walk 语句口径（排除 docstring） | mcp_client.py **101** / mcp_sample_server.py **16**（与 Developer 113/19 口径略异，差异系 def/class 头与 handler 计数口径，**双口径均 ≤200**）；最长方法 init_ext 物理 28 行 / AST 13 语句 ≤50 ✅ |
| **安全 grep（AC-44）** | 两新文件 grep `print(` / 裸 `except:` / logger 行逐条读 | **0 print、0 裸 except**；9 条 logger 仅工具名/计数/异常消息，args/token/密钥零明文 ✅ |
| **零新端点（AC-48）** | main.py diff 路由装饰器甄别 | 仅 083 的 GET/POST `/ai/tools/approvals`，**084 零新端点** ✅ |

## 5. 环境受限项（如实标注）

1. **fail-open 启动冒烟（AC-16/31 uvicorn 级）未执行**：环境探测 Docker daemon 未运行、PG 5432 / Redis 6379 均不可达（与 module-083 Tester 同情形）——服务 lifespan `init_db()` 依赖 PG 无法启动。**替代覆盖充分**：`test_lifespan_spawn_failure_service_survives`（lifespan 层走**真实 init_ext** 内部捕获 + 坏 command，服务照常 yield）+ `test_spawn_failure_fail_open` + `test_handshake_timeout_fail_open` + `test_disabled_zero_spawn` 全绿。属环境受限非代码缺陷。
2. **真实 E2E 审批链路（AC-24 E2E"尽力"项）未执行**：同上 PG 依赖。**替代覆盖**：`test_register_and_approval_flow` 半真实链路（真实子进程 + 真实全局 registry + 真实审批闸 pending 落库打桩断言 + approve 后真实执行文件追加）全绿。

## 6. 验收标准核对（AC-1 ~ AC-49 逐项）

### 6.1 功能验收
| AC | 验证证据（独立复跑/代码实证） | 结论 |
|----|------------------------------|------|
| AC-1 no_retry 字段默认 False + 内置 10 全 False | 内置契约探针 `10 True True` + `test_builtin_tools_all_no_retry_false`（tool_registry.py:165/182/315/330） | ✅ |
| AC-2 no_retry=True 不重试 | `test_no_retry_true_executes_once`（func 1 次 + 返回 ""） | ✅ |
| AC-3 默认 False 073 语义不变 | `test_no_retry_default_keeps_073_semantics`（执行 2 次）+ test_tool_retry_dedup.py 24 项全绿（204 内） | ✅ |
| AC-4 禁用零开销不 spawn | `test_disabled_zero_spawn`（stdio_client 0 次）+ 代码 L94-95 首行短路 | ✅ |
| AC-5 发现注册四契约 | `test_discovery_registers_with_governance`（approval=required/group=set()/no_retry=True/args_schema=inputSchema + 返回 2） | ✅ |
| AC-6 冲突名跳过 | `test_conflict_name_skipped`（内置 description 一字不变 + warning；代码 L142-144 先于 register） | ✅ |
| AC-7 call_tool 正常路径 | `test_text_content_concat`（多文本块拼接） | ✅ |
| AC-8 structuredContent 优先 | `test_structured_content_priority`（JSON 反序列化等值断言；代码 L184-185） | ✅ |
| AC-9 超长截断 | `test_truncation_over_2000`（3000 字符 → <2100 + "截断"标记） | ✅ |
| AC-10 isError 语义 | `test_is_error_readable_message`（可读提示含 detail） | ✅ |
| AC-11 异常兜底不抛 | `test_exception_returns_readable`（ConnectionError → 可读提示） | ✅ |
| AC-12 语义矩阵三态 | TestAllowedToolsMatrix 4 项（未启用 None / 启用空白名单非 None 恰 10 / 交集精确 / 未初始化 None）+ 代码 L221-224 启用分支唯一出口恒为 set | ✅ |
| AC-13 close 幂等 | `test_close_idempotent_uninitialized` + 代码 L196-208 逐层判空 | ✅ |
| AC-14 4 配置默认 | `test_defaults_all_off`（Settings(_env_file=None)）+ config 冒烟 `False [] [] 10.0` | ✅ |
| AC-15 env 映射 | `test_env_mapping` + Tester 进程环境注入探针（True/[...] / [...] / 10.0） | ✅ |
| AC-16 lifespan 挂 init_ext + fail-open | `test_lifespan_calls_init_and_close`（await_count=1 + 参数 is registry）+ `test_lifespan_spawn_failure_service_survives`；uvicorn 级冒烟环境受限（§5-1） | ✅（单测覆盖，E2E 标注） |
| AC-17 shutdown 调 close | `test_lifespan_calls_init_and_close`（close await_count=1；main.py:181 finally） | ✅ |
| AC-18 手写端点白名单拒绝 | `test_agent_endpoint_denies_external`（httpx ASGI 真实 SSE + "权限白名单" + func 未执行）+ `test_unauthorized_no_approval_submission`（不提交审批 await_count==0） | ✅ |
| AC-19 langgraph 端点同拒 | `test_agent_lg_endpoint_denies_external`（同口径断言） | ✅ |
| AC-20 state 键 + 缺省 None 零变化 | `test_state_has_allowed_tools_key` + `test_langgraph_loop_none_allows_all`（langgraph_react.py:60/73/317/367） | ✅ |
| AC-21 传入白名单越权拒绝 | `test_langgraph_loop_denies_outside_whitelist`（execute_tools 节点透传生效 L172-175） | ✅ |
| AC-22 样例 server 可独立运行 | Tester 独立 stdio 冒烟（非测试进程）：list_tools 2 实名 + 双工具真实执行 + 文件真实追加 | ✅ |
| AC-23 真实握手非 mock | `test_real_subprocess_handshake`（sys.executable 真子进程 → 精确 2 名单 → 真实 ISO 时间）+ Tester 独立冒烟复现 | ✅ |
| AC-24 注册链路半真实 + 审批 | `test_register_and_approval_flow`（未审批 → "需人工审批" + INSERT 断言；approve → 真实执行文件追加）；E2E 环境受限（§5-2） | ✅（单测覆盖，E2E 标注） |
| AC-25 未启用 schema 无外部工具 | 内置契约探针（registry 恰 10 内置）+ `test_not_initialized_returns_none_even_if_enabled` | ✅ |
| AC-26 白名单含未注册名 | `test_whitelist_unregistered_name_no_error`（不报错、该名不出现） | ✅ |
| AC-27 空 command + enabled | `test_empty_command_fail_open`（warning + 返回 0 + 不 spawn；代码 L96-98） | ✅ |
| AC-28 超时边界 | `test_handshake_timeout_fail_open`（0.01s + 慢 init → 0）；执行期 15s 围栏由 AgentTool.wait_for 继承（_execute L249 超时分支未动） | ✅ |
| AC-29 ext_ 前缀 | 冒烟 LIST_TOOLS 实证 ['ext_current_time', 'ext_append_log'] | ✅ |
| AC-30 参数校验继承 | Tester 补充探针：类型违规 → "参数错误" + call_tool 零执行；"缺必填"示例与 083 置空 required 契约相抵（§4 注，文档瑕疵非缺陷） | ✅ |
| AC-31 spawn 失败 fail-open | `test_spawn_failure_fail_open`（warning + 0）+ `test_lifespan_spawn_failure_service_survives`；uvicorn 级环境受限（§5-1） | ✅（单测覆盖） |
| AC-32 会话中断后调用 | `test_exception_returns_readable`（会话失效 → 可读提示不崩） | ✅ |
| AC-33 审批 DB 异常 fail-closed | test_tool_governance.py 存量语义复用（204 内全绿）；084 零改动 | ✅ |
| AC-34 空结果占位 | `test_empty_result_placeholder`（"（外部工具 ext_x 无返回结果）"）；外部不在 _RETRIEVAL_HIT_TOOLS（react.py 该清单 083/068 遗留零 diff） | ✅ |
| AC-35 并行不串话 | Tester 补充探针（真实 server 3 并发各自对应） | ✅ |

### 6.2 非功能验收（重点核）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-36 全量新增 0 失败 | **独立复跑 1564 passed / 2 failed / 3 skipped**；2 失败逐项重跑 = Redis Timeout（6379 不可达，环境性基线）；4 项 proxies 差异系工作树 openai 修复（084 前环境遗留）；scripts error 范围外未变化；算术对账 1569=1569 | ✅ |
| AC-37 存量测试零改动 | 受影响存量 204/204 全绿；git status tests/ 仅 conftest.py 修改（autouse fixture，plan §9 许可）+ 新增 test_mcp_client.py；无存量测试文件改动 | ✅ |
| AC-38 红线 git diff | engine.py/router.py/mcp_server.py **零 diff**（status 无输出）；react.py/database.py/requirements.txt 逐块甄别零 084 归属（§1 表）；生产修改恰为 tool_registry/config/main/langgraph_react + 新增 mcp_client/mcp_sample_server/test_mcp_client | ✅ |
| AC-39 默认配置零变化 | 内置契约探针 `10 True True` + config 冒烟全关 + `test_agent_endpoint_default_allows_builtin`（allowed_tools=None 内置全放行）+ 幂等清单 `_IDEMPOTENT_TOOLS` 零改动（tool_registry diff 甄别） | ✅ |
| AC-40 禁用路径零开销 | 代码 L94-95 首行短路 + `test_disabled_zero_spawn`（0 spawn/0 DB） | ✅ |
| AC-41 启用路径开销可控 | 注册仅启动一次（lifespan 单调用）；每调用 1 次 call_tool（L176）；截断 2000（L49-53 + 测试） | ✅ |
| AC-42 审批全 required 硬编码 | mcp_client.py L151 字面量（无配置引用）；内置 10 全 auto（契约探针） | ✅ |
| AC-43 无绕过口 | main.py:745/748-750 + 822/825-827 两端点 + langgraph L172-175 三路汇入 react.py 执行层同闸（diff 甄别 react.py 该闸为 083 代码零 084 改动）+ 审批闸 run 内通用 | ✅ |
| AC-44 无敏感泄露/无 SQL 拼接 | §4 安全 grep（0 print/0 裸 except/logger 无密钥）+ 本模块零新增 SQL（审批复用 083 参数化） | ✅ |
| AC-45 行数 ≤200 | Tester 独立 AST 复算 mcp_client 101 / sample 16；核心（+084 归属修改 ~27）≈128 / 严格 ≈144，**双口径 ≤200**（Developer 113/19 口径同过线） | ✅ |
| AC-46 方法 ≤50 + docstring | 最长 init_ext 28 物理 / 13 AST；public 方法全带 Args/Returns docstring（代码逐个核验） | ✅ |
| AC-47 无空 catch | 4 处 except 全带 logger + fail-open/fail-closed 性质注释（L104 显式标注） | ✅ |
| AC-48 零新依赖/零新表/零新端点 | mcp==1.26.0 原有（requirements 084 零归属）；database.py diff 仅 083 DDL；main.py 无新路由（§4 甄别） | ✅ |
| AC-49 无新 ADR | specs/adr 止于 0019；选型决策记录入 changelog | ✅ |

## 7. 已知边界 / 备注

1. **全量基线数字口径说明**：简报预期"1560/6/3+1 error"沿用 083 后基线（1526+6+3+1 error）+34。实测 1564/2/3 差异已逐项归因（§2）：4 项 proxies 失败被工作树 openai==1.109.1 环境遗留修复清零（该修改先于本模块存在，review-report §6 已甄别）、2 项 real_redis 环境性保持、scripts 1 error 为收集范围差异（`pytest tests/` 不收集 scripts/，直接运行仍 error）。**红线实质（新增 0 失败、存量零改动）成立，且基线数字实际优于预期。**
2. **AC-30 措辞瑕疵（非阻塞）**："如 ext_append_log 缺必填"示例与 083 已定案的"required 置空缺省回退"契约相抵（083 契约明确"MCP 外部调用依赖"该行为）；校验继承的本质要求（违规参数拒绝 + func 不执行）实测成立。建议后续模块勘误 AC 措辞。
3. **stdio 子进程孤儿**（父进程异常退出）：plan §10 已如实声明 v1 不引入守护逻辑。
4. **环境受限两项**（uvicorn fail-open 冒烟 / 真实 E2E 审批链路）均因 PG/Redis/Docker 不可达未执行，单测替代覆盖充分（§5），与 module-083 Tester 环境受限口径一致。
5. 全量 158 warnings 为存量 Pydantic/废弃警告源（与 083 报告同），非本模块引入。

## 8. 验收结论

- 审查人: Reviewer（2026-09-06，0 阻塞 / 0 重大 / 4 项 LOW + 2 备忘非阻塞，已通过）
- 测试人: Tester（2026-09-06）
- 验收时间: 2026-09-06
- 结论: **[x] 通过**
- 统计: **验收通过 49/49**
- 备注: 定向 34/34 + 受影响存量 204/204 + 全量 1564/2/3（2 失败 = Redis 环境性基线，**新增 0 失败**）+ py_compile 6/6 + 红线甄别（084 零归属）+ 独立真实 stdio 握手冒烟复现 + AC-30/AC-35 补充探针通过。Reviewer 4 项 LOW 逐项独立验证属实且均非阻塞（测试桥挂载 / 超时逐段口径 / 握手失败延迟回收 / changelog 分组勘误），2 备忘确认无现实污染路径。AC-30 的"缺必填"示例属文档瑕疵（与 083 置空 required 契约相抵），校验继承实质成立。
