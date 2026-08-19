# Module-073 审查报告 — 工具防重复 + 失败自动重试 + 日志隐私修正

> Reviewer：2026-08-19 | 对照 `acceptance-criteria.md` + `plan.md` 逐项核查
> 结论：**✅ Pass（进 Tester）**

## 一、独立验证（不采信 changelog 数字，逐项实测）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest -q`（ai_service 根） | **1249 passed / 0 failed（207.65s）** 与 changelog 一致；1 项预存 collection ERROR `scripts/test_models.py::test_model`（fixture 'label' not found）——git log 实证最后一次改动 36d3606 module-050、本模块 diff 零触碰，module-066/067 同款口径 |
| 定向单测 | 独立复跑 `python -m pytest tests/agent/test_tool_retry_dedup.py tests/core/test_log_privacy.py -q` | **24 passed**（19 + 5），与报告一致 |
| 受影响存量套件 | 独立复跑 `python -m pytest tests/agent/test_agent_tools.py tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py tests/agent/test_tool_phase_split.py tests/agent/test_agent_phase_fix.py -q` | **133 passed**（含 test_agent_tools 62 项）与报告一致 |
| 日志隐私 grep | `Select-String rag/engine.py 'query\[:50\]'` | **8 处**（L248/309 新增 + 存量 L347/426/766/776/783/862）✓ |
| 异常日志完整 grep | `Select-String rag/engine.py 'RAG chat 失败'` | **仅 L516**，含完整 `request.query` + `error=%s` + `exc_info=True` ✓ |
| 开关冒烟 | `python -c "from src.config import settings; print(settings.tool_auto_retry)"` | **True**（生产默认，PW_TOOL_AUTO_RETRY 回退）✓ |
| 红线核验 | `git diff --stat` | 代码改动限 react.py / tool_registry.py / config.py / engine.py + conftest.py + 2 新增测试文件；langgraph_react.py / mcp_server.py / database.py / router.py 零改动 ✓ |
| 存量测试零改动 | `git diff --stat -- ai_service/tests/` | 仅 conftest.py 新增 autouse fixture（14 行），存量断言零改动 ✓ |
| CONTEXT.md 只增不删 | diff 核查 + %TEMP%\CONTEXT.md.module073.bak 存在（81525 B，0:55:29） | 追加 module-073 段 8 行，零删行 ✓ |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-073 行（含 v0.73.0 版本号 + 状态"👀 Developer 完成待 Reviewer"）+ file-index 行 + [PLAN]/[CODE] 行全在 ✓ |

**环境备注**：工作树含 2 个未跟踪测试文件（`ai_service/tests/agent/test_tool_history_wiring.py` + `ai_service/tests/retrieval/test_query_rewrite_history.py`，38 项）——系 module-072 并行会话在途产出（mtime 0:30 早于本模块），非本模块改动，其测试已计入 1225 基线（pytest 收集不受 git 跟踪影响），Reviewer 未触碰。

## 二、WP 逐项核对

### WP-A：防重复（add_note 去重 + re_search 守卫）— ✅ 通过

- **add_note 返回 bool + 完全一致去重**（react.py:100-117）：`note.strip()` 后逐字比较 `in self.scratchpad` → 重复返回 False 不追加；不同追加返回 True。**不做近似去重**（判定器确定性红线）✓；docstring 完整声明语义
- **存量兼容**：test_agent_tools.py:952 直接调 `ctx.add_note("工作笔记内容")` 只读 scratchpad 不检查返回值（实测通过）✓
- **_note_to_self 重复提示**（tool_registry.py:315-323）：`note.strip()[:500]` 截断后 `if not ctx.add_note(note)` → 返回"笔记已存在（未重复记录）"；比较点取截断后值（两次相同超长 note 截断一致仍判重复，单测 test_note_to_self_long_note_truncated_dedup 锁定）✓；空/纯空白 note 仍返回"（未提供笔记内容）"✓
- **MCP ctx 兼容**：mcp_server.py:79 `add_note=lambda note: None` 返回 None（falsy）→ `_note_to_self` 若经 MCP 会误报"已存在"——但 note_to_self **不在 MCP 只读白名单**（READ_ONLY_TOOLS 显式 6 名，mcp_server.py:39-46），路径不可达，changelog 已如实声明 ✓
- **last_research_query 字段**（react.py:98）：`__init__` 初始化 ""，初始 "" 断言由 test_first_call_records_guard 覆盖 ✓
- **re_search 守卫位置**（tool_registry.py:296-307）：check_sufficiency（L296）**之后**、`hybrid_retriever.retrieve`（L308）**之前**——拦截"重检索 + 文档格式化"大头；`rewritten == ctx.last_research_query` → 返回"已按该改写重检过，无新结果"，**不调 retrieve / add_docs / _format_docs** ✓（单测断言 retrieve.await_count==1 且 sufficiency.await_count==2，如实锁定"守卫在 check_sufficiency 之后"边界）
- **sufficient 分支不更新守卫字段**（L297-298 提前 return）✓；**空改写同输入二次拦截**（`result.get("rewritten_query", query)` 兜底 → rewritten=query，单测 test_same_raw_query_blocks）✓
- **输入级预拦截不采纳**：如实标注（文档变化后同 query 合法重评会被误拦），changelog + 代码注释一致 ✓
- **add_docs `_seen_ids` 逐字不动**（react.py:119-125 diff 无此区域改动）✓

### WP-B：失败自动重试 — ✅ 通过

- **AgentTool.run 重试嵌套**（tool_registry.py:83-100）：catch Exception 后 `if settings.tool_auto_retry and self.name not in _NO_RETRY_TOOLS` → 重试 1 次同一 func 同参数同 ctx；重试成功返回正常结果 / 重试仍失败返回 ""（module-028 降级哲学不变）✓
- **TimeoutError 分支先于重试分支判断**（L85-87 在前，L88-100 在后）——存量两处超时测试精确文案 `"(工具 X 执行超时)"` 兼容前提写死，实测 test_tool_run_timeout_returns_prompt / test_tool_timeout 通过 ✓
- **超时不重试**：代码注释完整声明理由（超时=慢非抖动、重试翻倍墙钟 15→30s、15s 是 module-042 预算围栏语义）；单测 monkeypatch `agent.tool_registry.asyncio.wait_for` 抛 TimeoutError → func await_count==0、wait_for call_count==1（瞬时完成不 sleep）✓
- **重试内超时单独处理**（L93-95）：重试内 TimeoutError → 返回超时提示（非空串），单测 test_retry_timeout_inside_retry 覆盖 ✓
- **_NO_RETRY_TOOLS 排除清单**（L37）：`{"generate_answer", "verify_answer"}` 与 plan 逐字一致；单测 test_generate_verify_not_retried 断言 func await_count==1 ✓
- **开关**（config.py:127-136）：`tool_auto_retry: bool = True` 默认 true（task-brief 指定），注释记录决策 + PW_TOOL_AUTO_RETRY 回退；conftest autouse `default_tool_auto_retry_disabled`（conftest.py:102-113）钉 false，新测试体内显式 set True——hermetic 双保险 ✓
- **import 无环**：`from src.config import settings`（tool_registry.py:25）——config.py 仅依赖 typing + pydantic_settings（实测 import 清单），src.config 零业务依赖无循环导入风险 ✓
- **重试不增预算（单测锁定）**：test_retry_budget_locked_in_react_loop——react_loop 集成（首败重试成功）：func 调用 2 次 / tool_call 事件 1 个 / `done["tool_count"]==1` / 消息历史 1 条 tool 结果 / record_tool_call await 1 次（react.py:473-479 计数点在 run 之前，重试对循环不可见）✓
- **MCP / langgraph 自动继承**：mcp_server.py:90 `_invoke_tool` 复用同一 run（6 只读工具全在重试集，超时围栏 15s 不变）；langgraph_react.py:169 复用 execute_tool_with_log → 继承零改动 ✓；test_mcp_server.py:150 恒抛工具 → 重试仍失败返回空串 → 包装"（工具执行失败）"——存量兼容实测通过 ✓
- **tool_call_logs 表结构零改动**（ADR-0017 红线）：database.py 零 diff；execute_tool_with_log（react.py:310-338）计时包住整个 run（duration_ms 含重试耗时）、result_ok 语义不变（run 内部全捕获不向外抛）✓
- **可观测**：重试两声 warning（"首次失败，自动重试"/"重试仍失败，返回空"），单测 caplog 断言 ✓

### WP-C：日志隐私（正常截断 / 异常完整）— ✅ 通过

- **engine.py:248** `logger.info("RAG search: query=%s, top_k=%d", request.query[:50], ...)` 正常截断 ✓
- **engine.py:309** `logger.info("RAG chat: query=%s, history=%d", request.query[:50], len(request.history))` 正常截断 ✓
- **engine.py:516** `logger.error("RAG chat 失败: query=%s, error=%s", request.query, e, exc_info=True)` 异常完整（原实现反而缺 query）✓
- **原则注释**（L246-247）：正常路径一律 [:50] 截断 / 异常路径完整记录（排查需要）/ tool_call_logs args 完整保留（审计用途）——AC-15 三要素齐全 ✓
- **只动指定 3 行**：diff 确认 engine.py 仅 3 处日志行 + 2 处注释；存量截断实测 6 处（brief"其余 8 处"口径出入以实测为准，changelog 如实声明）✓
- **测试手法对齐 plan §6 脆弱性提示**：≥60 字符 query + caplog levelno==INFO 过滤（错误路径日志也含完整 query，不按级别过滤会假阴性）+ 50 字符边界不截断（[:50] 恒等）+ 空 query 异常不崩 + 堆栈断言 `record.exc_info is not None` ✓
- **mock 路径真实**：`rag.engine.resolve_tool_history`（模块级 L119）/ `router_agent.classify`（L41 import）为真实可 patch 符号，实测通过 ✓

### WP-D：回归 + 文档收口 — ✅ 通过

- 全量 1249/0 独立复跑确认（见 §一）；存量测试零改动（git diff tests/ 仅 conftest 新增）✓
- 新增单测 24 项（19 + 5）全 mock / caplog，无真实 DB/LLM 依赖 ✓
- changelog.md 结构完整（变更概述/文件列表/WP 决策/验证结果/已知边界/变更记录）✓
- CONTEXT.md 只增不删（备份 %TEMP%\CONTEXT.md.module073.bak 实测存在）✓
- 三记忆文件全部更新（见 §一）✓
- 无新依赖、无新表、无新端点；无新 ADR（决策入 changelog，plan 声明）✓

## 三、发现（非阻塞）

| # | 文件 | 位置 | 问题描述 | 严重级别 | 建议 |
|---|------|------|----------|----------|------|
| 1 | ai_service/rag/engine.py | L516 | 异常路径完整 query 含用户输入原文——属**用户决策**（异常完整原则，排查需要），但 ERROR 级别日志若无日志脱敏管线，长 query 可能泄露到日志聚合平台。当前无聚合平台、与既有 error 日志口径一致，不阻塞 | 低 | 如未来接入日志平台，可评估对 ERROR 日志 query 做局部掩码（保留首尾）或按身份脱敏；当前保持用户决策 |
| 2 | ai_service/agent/tool_registry.py | L37 | `_NO_RETRY_TOOLS` 排除清单对**未来新增工具**默认继承重试——生成类新工具若不主动加入清单会"意外获得重试"（15s 超时常态下重试无意义）。plan 已权衡（排除清单比白名单简单），注释已声明 | 低 | 未来新增生成类工具时在代码评审中提示加入 `_NO_RETRY_TOOLS`；可在 register_builtin_tools 生成组注册处补一行提醒注释 |
| 3 | ai_service/tests/agent/test_tool_retry_dedup.py | L244-253 | 超时测试 monkeypatch `asyncio.wait_for` 用 `awaitable.close()` 防 RuntimeWarning——若 func 非协程（sync 包装场景）close 不存在会 AttributeError；当前全部工具 func 均 async，不构成实际风险 | 低 | 维持现状（对齐存量测试模式），无需改动 |
| 4 | 工作树 | tests/agent/test_tool_history_wiring.py + tests/retrieval/test_query_rewrite_history.py | 未跟踪文件（module-072 并行会话在途产出），非本模块改动，但其存在使"全量 1249"口径依赖它们保持可收集状态 | 低 | 协调者统一提交时注意：module-072 文件与本模块文件一并提交（勿遗漏/勿互覆盖） |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| tool_call_logs 表结构零改动（ADR-0017） | database.py 零 diff | ✅ |
| langgraph_react.py / mcp_server.py / database.py / router.py 零改动 | git diff --stat 实证 | ✅ |
| 存量测试零改动 | git diff tests/ 仅 conftest 新增 autouse fixture | ✅ |
| 重试不增加预算 | react_loop 集成单测锁定（tool_count==1） | ✅ |
| 判定器确定性优先（不做近似去重） | add_note 完全一致 strip 逐字 | ✅ |
| 无新依赖 / 无新表 / 无新端点 | git diff + requirements 未动 | ✅ |

## 五、架构与代码质量评估

- **ponytail 最简实现**：去重 if + 重试 try 嵌套 + 3 处截断，不重写执行层；生产功能代码 ~40 行 ≤ 200 上限 ✓
- **单点继承而非多处接线**：重试放 AgentTool.run 内部 → react_loop / langgraph / MCP 三路径零改动自动继承（对齐 execute_tool_with_log 单点防漂移模式）✓
- **分层**：纯 Python 侧，config → tool_registry 单向依赖，无环 ✓
- **配置模式对齐**：env_prefix PW_ 自动映射 + conftest autouse 钉住（对齐 056/058/066 先例）✓
- **安全**：日志隐私修正减少敏感信息暴露面；无新增凭据/注入面；SQL 零改动 ✓

## 六、验收标准核对

| 验收项 | 对应实现 | 状态 |
|--------|----------|------|
| AC-1 add_note 去重返回 bool | react.py:100-117 + test_add_note_exact_duplicate_returns_false | ✅ |
| AC-2 note_to_self 重复提示 | tool_registry.py:321-322 + test_note_to_self_duplicate_returns_hint | ✅ |
| AC-3 last_research_query 字段 | react.py:98 | ✅ |
| AC-4 re_search 同改写守卫 | tool_registry.py:305-307 + test_same_rewritten_blocks_second | ✅ |
| AC-5 守卫边界（sufficient/空改写/_seen_ids） | 三测试覆盖 | ✅ |
| AC-6 异常重试 1 次成功 | tool_registry.py:89-92 + test_retry_recovers_after_first_failure | ✅ |
| AC-7 重试仍失败返回 "" + 两声 warning | L96-98 + test_retry_still_fails_returns_empty / test_retry_warning_logs | ✅ |
| AC-8 超时不重试精确文案 / 重试内超时 | L85-87/L93-95 + 双测试 | ✅ |
| AC-9 generate/verify 不重试 | L37 + test_generate_verify_not_retried | ✅ |
| AC-10 开关 false 不重试 | config.py:127 + conftest 钉 false + test_switch_off_no_retry | ✅ |
| AC-11 预算锁定 + tool_call_logs 只记 1 次 | test_retry_budget_locked_in_react_loop | ✅ |
| AC-12/13/14 日志截断/异常完整 | engine.py:248/309/516 + 3 测试 | ✅ |
| AC-15 原则注释 | engine.py:246-247 | ✅ |
| AC-16 note 判重边界（空白/空/超长） | 3 测试 | ✅ |
| AC-17 重试边界（开关关/超时/重试内） | 3 测试 | ✅ |
| AC-18 日志边界（50 字符/超长/空 query 异常） | 3 测试 | ✅ |
| AC-19 守卫首调边界 | test_first_call_records_guard | ✅ |
| AC-20 恒抛异常返回 "" | test_retry_still_fails_returns_empty + 存量 test_tool_run_failure_returns_empty | ✅ |
| AC-21 瞬时抖动恢复透明 | test_retry_recovers_after_first_failure + 预算锁定集成 | ✅ |
| AC-22 MCP 继承重试 | mcp_server.py:90 复用 + test_mcp_server.py:150 存量兼容 | ✅ |
| AC-23 正常路径零开销 | 重试分支仅异常进入（代码审阅） | ✅ |
| AC-24 超时不重试延迟受控 | 单测锁定 wait_for 1 次 | ✅ |
| AC-25 日志隐私 grep | 8 处截断 + L516 完整（实测） | ✅ |
| AC-26 tool_call_logs args 语义不变 | database.py 零改动 | ✅ |
| AC-27 全量 1249/0 + 存量零改动 | 独立复跑 | ✅ |
| AC-28 新增单测覆盖 | 19 + 5 = 24 项 | ✅ |
| AC-29 无新依赖/表/端点 + 红线 | git diff 实证 | ✅ |
| AC-30 代码量 ≤200 + ponytail | ~40 行 + 最简实现 | ✅ |

## 七、结论

**✅ Pass（进 Tester）**。WP-A~D 全部通过标准达成：防重复语义（完全一致 strip 逐字 + 截断后判重 + add_note bool 返回）与 re_search 守卫位置（check_sufficiency 后 retrieve 前）逐行核对与 plan 一致；重试分支（TimeoutError 先判 / _NO_RETRY_TOOLS 排除 / 超时不重试 / 预算不增）全部单测锁定且存量 3 处 run 直接断言兼容；日志三处改动 grep 实证；全量 1249/0 独立复跑与报告一致；红线全守（tool_call_logs 表结构 / langgraph / MCP / database / 存量测试零改动）。§三 4 项 LOW 均为设计权衡记录与并行会话观察，不阻塞验收。建议 Tester 重点关注：预算锁定集成测试（AC-11）、MCP 路径继承（AC-22）、日志 levelno 过滤断言手法（AC-12~14）。
