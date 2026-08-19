# 开发计划 — Module-073: 工具防重复 + 失败自动重试 + 日志隐私修正

> Planner: 2026-08-19 | 依据：`specs/module-073-tool-retry-idempotency/task-brief.md`（2026-08-19 用户决策）
> 范围：Agent 工具执行层治理（note_to_self/re_search 防重复 + 失败重试 1 次 + engine 日志"正常截断异常完整"）
> 预算：WP-A 半天 + WP-B 半天 + WP-C 2 小时 + WP-D 半天 ≈ 1.5 天
> Agent 配置：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1（无前端/Java 子任务）

## 0. Planner 已探明事实（勿重复调查）

- **AgentTool.run 现状**（tool_registry.py:57-74）：签名 `async def run(self, args: dict, ctx) -> str`——try `asyncio.wait_for(self.func(ctx, args), timeout=15)` / except TimeoutError → 返回 `"(工具 {name} 执行超时)"` / except Exception → 返回 `""`（module-028 降级哲学：结果喂回 LLM 判断继续/放弃）。**生产调用点仅 2 处**：react.py:315（`execute_tool_with_log` 内，计时包住 run，落 tool_call_logs）与 mcp_server.py:90（MCP exec 闭包）——重试改在 run 内部，两条 ReAct 循环（react_loop/langgraph，均经 execute_tool_with_log）+ MCP 自动继承，**langgraph_react.py / mcp_server.py 零改动**。
- **tool_count 计数点**（react.py react_loop L457）：`tool_count += 1` 位于 `for tc in allowed` 循环内、`execute_tool_with_log` 调用**之前**，每个 LLM 提议并实际执行的 tool_call 计一次；`ctx.phase_count[ctx.phase] += 1` L458 同位置。**重试发生在 AgentTool.run 内部 → 对循环完全不可见：不增加 tool_count / phase_count，不影响预算截断（L430-438 min(总剩余,阶段剩余)）与消息历史（tool 结果消息每 call 一条）**。tool_call_logs 的 duration_ms 会含重试耗时（execute_tool_with_log 计时包住整个 run）——task-brief 明确接受（表结构一字不改红线，ADR-0017）。
- **result_ok 语义不变**：execute_tool_with_log 中 result_ok=false 仅在工具不存在或 run 抛出异常；run 内部捕获所有异常（重试后仍失败也返回 ""）不向外抛 → module-066 落库语义零影响。
- **test_agent_tools.py 实测 62 个 test 函数**（`def test_` 计数）；直接断言 AgentTool.run 行为仅 3 处，全部兼容重试设计：
  - `test_tool_run_failure_returns_empty`（L111-117）：func 恒抛 RuntimeError → 重试 1 次仍失败 → 返回 ""（**无调用次数断言**，兼容）
  - `test_tool_run_timeout_returns_prompt`（L119-129）+ `test_tool_timeout`（L131-141）：sleep(999) → 超时**不重试** → 精确文案 `"(工具 X 执行超时)"` 不变（**兼容前提：TimeoutError 分支先于重试分支判断**）
  - 其余 ~15 处 run() 调用 func 正常返回 → 不触发重试路径
  - note 测试全部不同 note（"发现了一个重要线索"/笔记1-4/1000 字长 note），**无重复写同 note 的测试**；re_search 测试全部单次调用 + 每次新建 ReactContext（守卫字段初始 ""）→ WP-A 去重对存量零影响
  - `test_mcp_server.py:150` 断言 run 失败返回空串 → MCP 包装"（工具执行失败）"，恒抛工具重试仍返回空串 → 兼容
- **日志三处实测**（engine.py）：L246 `logger.info("RAG search: query=%s, top_k=%d", request.query, ...)` / L307 `logger.info("RAG chat: query=%s, history=%d", request.query, ...)` / L513 `logger.error("RAG chat 失败: %s", e, exc_info=True)`（异常路径反而缺 query）。现有截断实测：engine.py 内 `query[:50]` 6 处（L345/424/763/773/780/859）+ router.py 7 处 + query_rewrite.py 5 处（task-brief 口径"其余 8 处"与实测有出入，以实测为准，本模块只动指定 3 行）。**无存量测试断言这三行日志文案**（grep 实证）；caplog 断言先例：tests/core/test_degradation_fix.py。
- **配置开关模式**（config.py）：`model_config = {"env_prefix": "PW_"}`（L327）→ 新字段自动映射 `PW_TOOL_AUTO_RETRY`；开关先例 `tool_phase_split: bool = True`（L114，注释记录决策 + PW_ 回退）。conftest autouse 钉住模式：`monkeypatch.setattr(settings, "xxx", False)`（default_tool_phase_split_disabled / tool_call_logs_disabled 等），新测试体内显式 set True。**注意：tool_auto_retry 是少数默认 true 的开关**（task-brief 指定），conftest 钉住 false 保 hermetic。
- **基线**：全量 1225/0（module-072 后 + HyDE prompt 优化）；存量测试零改动红线。

## 1. WP-A：防重复（去重是重试的前置条件）

### 子任务 A1: add_note 去重 + note_to_self 提示
- **描述**：
  - `ReactContext.add_note`（react.py:99-101）改为**返回 bool**（True=新增，False=重复已存在）：`note = note.strip()`；`if note in self.scratchpad: return False`；`self.scratchpad.append(note); return True`。去重语义：**完全一致**（strip 后逐字比较），**不做近似去重**——scratchpad 重复来自 LLM 同参数机械重复调用，措辞变体是正常产出不应拦截（确定性优先，判定器确定性红线）。
  - `_note_to_self`（tool_registry.py:281-288）：`note = note.strip()[:500]` 后改为 `if not ctx.add_note(note): return "笔记已存在（未重复记录）"`；新增时走现有返回（含 len(ctx.scratchpad)）。比较点是截断 500 后的值（截断在 add_note 前，两次相同超长 note 截断结果一致 → 仍判重复）。
  - 存量兼容：直接调用 add_note 的存量测试（test_agent_tools.py L952）只读 scratchpad 值、不检查返回值 ✓。
- **预估代码量**：~6 功能行（react.py 3 + tool_registry.py 2 + 空行/注释）
- **涉及文件**：
  - `ai_service/agent/react.py`（add_note 去重 + bool 返回）
  - `ai_service/agent/tool_registry.py`（_note_to_self 重复提示分支）
- **依赖**：无
- **通过标准**：单测——同 note（含首尾空白差异）不追加且返回 False / 不同 note 追加返回 True / note_to_self 重复时返回"笔记已存在（未重复记录）"且 scratchpad 长度不变 / 首次正常返回"已记录笔记"

### 子任务 A2: re_search 同改写 query 守卫
- **描述**：
  - `ReactContext.__init__`（react.py:86-97）加字段 `self.last_research_query: str = ""`。
  - `_re_search`（tool_registry.py:253-278）：check_sufficiency 之后、`hybrid_retriever.retrieve` **之前**插入守卫：
    ```python
    rewritten = result.get("rewritten_query", query)
    if rewritten == ctx.last_research_query:
        return "已按该改写重检过，无新结果"
    ctx.last_research_query = rewritten
    ```
    拦截后不再调 retrieve / add_docs / _format_docs。首次（last=""）与不同改写 query 正常执行。
  - **边界如实标注**：守卫在 check_sufficiency **之后**——第二次调用仍会执行一次 check_sufficiency（rewritten 只能由它产出 + 它重新评估充分性，ctx.docs 可能已增长），拦截的是"重检索 + 文档格式化"大头；**不做输入 query 级预拦截（完全免 LLM）**，原因是文档变化后（如 LLM 已调其他检索工具）同 query 合法重评会被误拦。
  - 空改写（rewritten_query 缺失/等于原 query → rewritten=query）：首调存 last=query，同输入二次调用 → 拦截（防 LLM 拿同一原 query 反复调 re_search 空转）。
  - check_sufficiency 返回 sufficient → 提前 return，**不更新** last_research_query。
  - 文档累积幂等（add_docs `_seen_ids`）逐字不动。
- **预估代码量**：~7 功能行（react.py __init__ 1 + tool_registry.py 守卫 6）
- **涉及文件**：
  - `ai_service/agent/react.py`（__init__ 字段）
  - `ai_service/agent/tool_registry.py`（_re_search 守卫）
- **依赖**：无（与 A1 独立，可并行）
- **通过标准**：单测——连续两次同改写 query → 第二次返回"已按该改写重检过，无新结果"且 retrieve 仅首次被调（assert_called_once）/ 不同改写 query 正常检索 / sufficient 分支不更新守卫字段 / 空改写同 query 二次拦截

## 2. WP-B：失败自动重试（执行层一次自我修复，LLM 决策层不动）

- **描述**：`AgentTool.run`（tool_registry.py:57-74）catch 异常后**重试 1 次同一 func（同参数同 ctx）**：
  - 模块级常量 `_NO_RETRY_TOOLS = {"generate_answer", "verify_answer"}`（**排除清单**——与 task-brief 工具类型策略逐字一致：只读检索类 search_*/extract_entities/recall_memory/re_search + note_to_self 重试；generate/verify 不重试，15s 超时是常态重试无意义。排除清单比白名单简单，未来新工具默认继承重试）
  - 结构（TimeoutError 分支**先于**重试分支判断——存量超时测试精确文案兼容前提）：
    ```python
    try:
        return await asyncio.wait_for(self.func(ctx, args), timeout=15)
    except asyncio.TimeoutError:
        logger.warning("工具 %s 超时 (15s)", self.name)
        return f"(工具 {self.name} 执行超时)"
    except Exception as e:
        if settings.tool_auto_retry and self.name not in _NO_RETRY_TOOLS:
            logger.warning("工具 %s 首次失败，自动重试: %s", self.name, e)
            try:
                return await asyncio.wait_for(self.func(ctx, args), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("工具 %s 重试超时 (15s)", self.name)
                return f"(工具 {self.name} 执行超时)"
            except Exception as e2:
                logger.warning("工具 %s 重试仍失败，返回空: %s", self.name, e2)
                return ""
        logger.warning("工具 %s 执行失败，返回空: %s", self.name, e)
        return ""
    ```
  - **超时不重试的合理性**（写入代码注释）：超时=慢不是抖动（LLM 生成/rerank 慢），重试不修复根因只把单工具墙钟翻倍到 30s，且 module-042 的 15s 是预算围栏语义，重试超时突破围栏；异常（429/网络闪断）是瞬时抖动，重试大概率成功。两次尝试各自独立 wait_for(15s)。
  - **可观测**：重试发生时 logger.warning（"首次失败，自动重试"），重试仍失败第二声 warning；tool_call_logs 只记最终结果（result_ok/duration_ms 含重试耗时，**表结构一字不改**），重试细节不落表。
  - **预算**：重试不增加 tool_count / phase_count（run 内部，计数点在 react_loop L457 于 run 之前，见 §0）——单测锁定。
  - 开关：config.py 加 `tool_auto_retry: bool = True`（注释记录决策 + `PW_TOOL_AUTO_RETRY` 回退，**默认 true 为 task-brief 指定**）；conftest 加 autouse fixture `default_tool_auto_retry_disabled`（monkeypatch.setattr False，hermetic，对齐 056/058/066 模式）；新测试体内显式 set True。
  - tool_registry.py 需新增 `from src.config import settings`（src.config 零业务依赖，无循环导入风险）。
  - **MCP 路径自动继承**：mcp_server.py:90 复用同一 run，6 只读工具全在重试集 → 零改动；超时围栏 15s 对 MCP 客户端不变。
- **预估代码量**：~22 功能行（_NO_RETRY_TOOLS 2 + run 重试分支 ~15 + config 4 + conftest 6，后两者各文件独立计数）
- **涉及文件**：
  - `ai_service/agent/tool_registry.py`（AgentTool.run 重试嵌套 + _NO_RETRY_TOOLS + import settings）
  - `ai_service/src/config.py`（`tool_auto_retry: bool = True`）
  - `ai_service/tests/conftest.py`（autouse 钉住 false）
- **依赖**：A1（note_to_self 重试安全性依赖去重拦双写——task-brief 明示"去重是重试的前置条件"；A1/A2 先落地，B 后接）
- **通过标准**：单测——检索工具异常重试 1 次成功（func 调用计数器 == 2，返回正常结果）/ 重试仍失败返回 ""（计数器 == 2）/ **超时不重试**（monkeypatch `agent.tool_registry.asyncio.wait_for` 抛 TimeoutError → func 计数 == 1、返回超时提示，测试瞬时完成不 sleep 15s）/ generate_answer 异常不重试（func 计数 == 1）/ 开关 false 不重试（func 计数 == 1）/ **预算锁定**（react_loop 集成：LLM 提议 1 个工具调用、工具首败后成功 → tool_count == 1、tool_trace 1 条、消息历史 1 条 tool 结果、record_tool_call 调用 1 次）

## 3. WP-C：日志隐私修正（正常截断 / 异常完整）

- **描述**（原则落定，L246 附近补注释声明）：
  - engine.py:246 → `logger.info("RAG search: query=%s, top_k=%d", request.query[:50], request.top_k)`
  - engine.py:307 → `logger.info("RAG chat: query=%s, history=%d", request.query[:50], len(request.history))`
  - engine.py:513 → `logger.error("RAG chat 失败: query=%s, error=%s", request.query, e, exc_info=True)`（异常路径完整：query 原文 + 错误 + 堆栈——排查需要完整信息）
  - 原则注释（L246 附近一行）：`# 日志隐私（module-073）：正常路径 query 一律 [:50] 截断；异常路径完整记录（排查需要完整信息）；tool_call_logs args 完整保留（审计用途）`
- **预估代码量**：3 行改动 + 2 行注释
- **涉及文件**：
  - `ai_service/rag/engine.py`（仅 3 处日志行 + 注释，其余零改动）
- **依赖**：无
- **通过标准**：单测（pytest caplog，对齐 test_degradation_fix.py 先例）——
  - 正常路径截断：`engine.search`（SearchRequest query=60+ 字符，mock hybrid_retriever.retrieve 返回 []）→ INFO 记录含 query[:50]、不含完整 query
  - 正常路径截断：`engine.chat` 同理（**按 levelno==INFO 过滤断言**——WP-C 落地后错误路径日志也含完整 query，不按级别过滤会假阴性）
  - 异常路径完整：mock `rag.engine.resolve_tool_history` 抛 RuntimeError（chat try 块内首个调用点 L324）→ ERROR 记录含完整 query + 错误信息

## 4. WP-D：回归 + 文档收口

- **目标**：全量绿 + 文档闭环。验证点：全量 pytest = 1225 基线 + 新增全绿、**存量测试零改动**（红线：tool_call_logs 表结构 / 循环逻辑 / MCP / langgraph 零改动）。
- **涉及文件**：
  - `ai_service/tests/agent/test_tool_retry_dedup.py`（新增：WP-A + WP-B 单测，预计 ~18 项）
  - `ai_service/tests/core/test_log_privacy.py`（新增：WP-C caplog 单测，预计 ~4 项）
  - `specs/module-073-tool-retry-idempotency/changelog.md`（新增）
  - `CONTEXT.md`（补 module-073 行——**只增不删，取更全侧，先备份 %TEMP%**，项目红线）
  - `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`（三记忆更新）
  - `METRICS.md`：无相关段（不加）
- **明确不做**：tool_call_logs 表结构零改动（ADR-0017 红线）；重试细节不落表（logger.warning 承载）；不做近似去重 / 输入级预拦截；不改 generate/verify 重试策略；langgraph_react.py / mcp_server.py / database.py 零改动；无新 ADR（无架构变更、无新依赖、无表结构变更、无新端点——决策记录入 changelog）。

## 5. 技术方案汇总

- **数据表**：无新增、无改动（tool_call_logs 红线不动）
- **API 端点**：无新增
- **外部依赖**：无新增
- **配置项**：`tool_auto_retry: bool = True`（PW_TOOL_AUTO_RETRY 回退；conftest autouse 钉住 false）
- **代码量口径**：生产功能代码 ~40 行（WP-A 13 + WP-B 22 + WP-C 3 + 注释 2）≤ 200 ✓；新增测试 ~180 行（含注释/docstring，测试不计入生产行数上限）

## 6. 风险评估

- **存量测试兼容**（重试改变 run 执行次数）：已核验 62 项 test_agent_tools 断言面（3 处直接断言均兼容，见 §0）+ conftest autouse 钉住 false 双保险；**TimeoutError 分支必须先于重试分支判断**（两处超时测试精确文案兼容前提，实现顺序写死）
- **重试延迟翻倍**（最坏 15+15s）：只读检索工具异常（429/网络闪断）重试几乎立即成功/失败，实际增量秒级；generate/verify 不重试封顶；超时不重试防墙钟翻倍
- **check_sufficiency 空转未完全消除**：同改写拦截在 check_sufficiency 之后（rewritten 只能由它产出）；输入级预拦截（完全免 LLM）因文档变化误拦合法重评不采纳——如实标注，不预设成功
- **去重误拦**（同改写 query 但 docs 已变）：add_docs 累积幂等使同改写重检不会新增文档，拦截无害；LLM 换 query 可继续重检
- **日志断言脆弱性**：用 ≥60 字符 query + levelno 过滤 + 断言"前缀包含 + 完整 query 缺席"（勿为空 query 断言截断语义）
- **MCP 行为继承**：重试透明无需新测试；6 只读工具均在重试集，超时围栏 15s 对客户端不变；result_ok 语义不变（test_mcp_server.py:150 兼容）

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-19 | 初始版本（WP-A~D 拆解 + 文件路径 + 通过标准） | Planner |
