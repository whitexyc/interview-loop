# Module-073 变更日志 — 工具防重复 + 失败自动重试 + 日志隐私修正

> 实施：Developer（2026-08-19）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：Agent 工具执行层治理——note_to_self/re_search 防重复（WP-A）+ 失败自动
> 重试 1 次（WP-B）+ engine 日志"正常截断异常完整"（WP-C）。全量 pytest 基线
> 1225/0（module-072 后），存量测试零改动红线。

## 一、变更概述

工具层三项治理落地：① note_to_self 完全一致去重（add_note 返回 bool）+ re_search
同改写 query 守卫（防 LLM 空转重检）；② AgentTool.run 异常自动重试 1 次（超时
不重试、generate/verify 排除、重试不增预算）；③ engine.py 三处日志"正常截断
[:50] / 异常完整"（隐私修正）。langgraph_react.py / mcp_server.py / database.py
零改动——重试在 AgentTool.run 内部，两条 ReAct 循环 + MCP 自动继承。

## 二、文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/agent/react.py | 修改 | `add_note` 完全一致去重 + 返回 bool；`__init__` 加 `last_research_query` 字段 |
| ai_service/agent/tool_registry.py | 修改 | `AgentTool.run` 异常重试嵌套（TimeoutError 先判）+ `_NO_RETRY_TOOLS` 排除清单 + `from src.config import settings`；`_note_to_self` 重复提示分支；`_re_search` 同改写 query 守卫 |
| ai_service/src/config.py | 修改 | `tool_auto_retry: bool = True`（PW_TOOL_AUTO_RETRY 回退，task-brief 指定默认 true） |
| ai_service/tests/conftest.py | 修改 | autouse fixture `default_tool_auto_retry_disabled`（测试环境钉住 false，hermetic） |
| ai_service/rag/engine.py | 修改 | L246/L307 正常路径 `query[:50]` 截断 + L513 异常路径完整 `query=%s, error=%s, exc_info=True` + 原则注释 |
| ai_service/tests/agent/test_tool_retry_dedup.py | 新增 | WP-A 防重复 11 项 + WP-B 重试 8 项（含预算锁定 react_loop 集成）共 19 项 |
| ai_service/tests/core/test_log_privacy.py | 新增 | WP-C 日志隐私 caplog 单测 5 项 |
| specs/module-073-tool-retry-idempotency/changelog.md | 新增 | 本文档 |
| CONTEXT.md | 修改 | 追加 module-073 段（只增不删，备份 %TEMP%\CONTEXT.md.module073.bak） |

**零改动红线核验**：tool_call_logs 表结构（ADR-0017 一字不改）/ langgraph_react.py /
mcp_server.py / database.py / router.py 均未触碰；无新依赖、无新表、无新端点。

## 三、WP-A：防重复（去重是重试的前置条件）

### 设计决策 A1: add_note 完全一致去重（判定器确定性优先）
- **决策**：`ReactContext.add_note` 返回 bool——`note.strip()` 已存在于 scratchpad
  → 返回 False 不追加；否则 append 返回 True。`_note_to_self` 重复时返回
  "笔记已存在（未重复记录）"，比较点取截断 500 后的值（两次相同超长 note 截断
  结果一致 → 仍判重复）。
- **原因**：scratchpad 重复来自 LLM 同参数机械重复调用；措辞变体是正常产出。
  完全一致（strip 逐字）而非近似去重——判定器确定性红线（近似需嵌入模型/阈值，
  会误拦正常产出且引入不确定性）。mcp_server.py 的 SimpleNamespace ctx
  `add_note=lambda note: None` 返回 None（falsy）但 note_to_self 不在 MCP 只读
  白名单（module-067 显式 4 非只读工具零暴露）→ 不受影响。
- **存量兼容**：test_agent_tools.py L952 直接调 add_note 只读 scratchpad 不检查
  返回值 ✓；note 测试全部不同 note ✓。

### 设计决策 A2: re_search 同改写 query 守卫（拦"重检索 + 格式化"大头）
- **决策**：`_re_search` 在 check_sufficiency 之后、`hybrid_retriever.retrieve`
  之前插入守卫：`rewritten == ctx.last_research_query` → 返回
  "已按该改写重检过，无新结果"；否则记录 `ctx.last_research_query = rewritten`。
  空改写（rewritten_query 缺失/等于原 query → rewritten=query）同输入二次调用
  同样拦截。sufficient 分支提前返回**不更新**守卫字段。
- **原因**：拦截在 check_sufficiency 之后是**如实标注的边界**——rewritten 只能
  由它产出，且它重新评估充分性（ctx.docs 可能已增长）；拦掉的是重检索 + 文档
  格式化大头。**不做输入 query 级预拦截（完全免 LLM）**：文档变化后（如 LLM 已
  调其他检索工具）同 query 合法重评会被误拦。add_docs `_seen_ids` 累积幂等
  逐字不动——同改写重检本不会新增文档，拦截无害；LLM 换 query 可继续重检。

## 四、WP-B：失败自动重试（执行层一次自我修复，LLM 决策层不动）

### 设计决策 B1: 重试在 AgentTool.run 内部，全路径自动继承
- **决策**：`AgentTool.run` catch 异常后（非超时）对同一 func 同参数同 ctx 重试
  1 次。模块级 `_NO_RETRY_TOOLS = {"generate_answer", "verify_answer"}` 排除
  清单（15s 超时是常态，重试无意义；排除清单比白名单简单——未来新工具默认继承
  重试）。生产调用点仅 2 处（react.py execute_tool_with_log + mcp_server.py:90）
  → 手写 ReAct 循环 + langgraph + MCP 全部自动继承，langgraph_react.py /
  mcp_server.py 零改动。
- **原因**：只读检索类异常多为瞬时抖动（LLM 429/网络闪断），重试大概率成功；
  note_to_self 重试安全依赖 WP-A 去重拦双写（task-brief 明示"去重是重试的前置
  条件"——A 先落地 B 后接）。

### 设计决策 B2: 超时不重试 + TimeoutError 分支先判
- **决策**：`except asyncio.TimeoutError` 分支在 `except Exception`（重试分支）
  **之前**判断；超时直接返回 `"(工具 X 执行超时)"` 精确文案，不进入重试。
  重试内超时同样返回超时提示（`"(工具 X 执行超时)"`）。两次尝试各自独立
  wait_for(15s)。
- **原因**：① 超时=慢不是抖动（LLM 生成/rerank 慢），重试不修复根因只把单工具
  墙钟翻倍到 30s；15s 是 module-042 预算围栏语义，重试超时突破围栏。② 存量
  test_agent_tools.py 两处超时测试（sleep(999)）断言精确文案 `"(工具 X 执行
  超时)"`——TimeoutError 分支先判是兼容前提（实现顺序写死）。

### 设计决策 B3: 重试不增加预算（tool_count 语义不变，单测锁定）
- **决策**：重试发生在 run 内部，对 react_loop 完全不可见——不增加 tool_count /
  phase_count（计数点在 react_loop L457 `tool_count += 1`，位于 execute_tool_with_log
  调用之前）/ 消息历史（tool 结果消息每 call 一条）。tool_call_logs 只记最终
  结果（result_ok=true，duration_ms 含重试耗时——execute_tool_with_log 计时包住
  整个 run）；重试细节不落表（logger.warning 承载）。
- **原因**：task-brief 关键设计点；tool_call_logs 表结构一字不改红线（ADR-0017）。
  预算锁定由 react_loop 集成测试锁定（工具首败后成功 → tool_count==1 / 1 个
  tool_call 事件 / 消息历史 1 条 tool 结果 / record_tool_call 只调 1 次）。

### 设计决策 B4: 开关默认 true + conftest 钉住 false
- **决策**：config `tool_auto_retry: bool = True`（env_prefix="PW_" → 自动映射
  PW_TOOL_AUTO_RETRY=false 可关）。conftest autouse fixture
  `default_tool_auto_retry_disabled` 测试环境钉住 false。
- **原因**：默认 true 为 task-brief 指定（少数默认开的新开关）；钉住 false 保证
  存量 test_agent_tools.py（"失败一次返回空"基准断言，含无调用次数断言的
  test_tool_run_failure_returns_empty）hermetic 零漂移——对齐 056/058/066 模式。

## 五、WP-C：日志隐私修正（正常截断 / 异常完整）

- **决策**：engine.py:246 `"RAG search: query=%s, top_k=%d"` 参数改
  `request.query[:50]`；:307 `"RAG chat: query=%s, history=%d"` 参数改
  `request.query[:50]`；:513 异常路径改 `"RAG chat 失败: query=%s, error=%s"`
  传完整 `request.query` + `e` + `exc_info=True`（原实现反而缺 query）。
  L246 附近补原则注释：正常路径 query 一律 [:50] 截断；异常路径完整记录
  （排查需要完整信息）；tool_call_logs args 完整保留（审计用途）。
- **原因**：用户决策"正常截断、异常完整"（task-brief 事实 5）。存量截断实测
  engine.py 内 6 处（L345/424/763/773/780/859）+ router.py 7 处 + query_rewrite.py
  5 处——task-brief 口径"其余 8 处"与实测有出入，**以实测为准**，本模块只动
  指定 3 行。无存量测试断言这三行日志文案（grep 实证）。
- **测试手法**（plan §6 脆弱性提示落地）：≥60 字符 query + caplog
  **levelno==INFO 过滤**断言"前缀包含 + 完整 query 缺席"（错误路径日志也含完整
  query，不按级别过滤会假阴性）；50 字符边界不截断；异常路径断言 ERROR 记录
  完整 query + 错误信息 + `exc_info is not None`（堆栈在 record.exc_info，不在
  r.message）；空 query 异常不崩。

## 六、验证命令与结果

| 验证项 | 命令 | 预期结果 | 实际 |
|--------|------|----------|------|
| 定向单测 | `python -m pytest tests/agent/test_tool_retry_dedup.py tests/core/test_log_privacy.py -q` | 全部 passed | 24 passed（19 + 5） |
| 受影响存量套件 | `python -m pytest tests/agent/test_agent_tools.py tests/agent/test_tool_call_logs.py tests/api/test_mcp_server.py tests/agent/test_tool_phase_split.py tests/agent/test_agent_phase_fix.py -q` | 全部 passed | 133 passed |
| 全量回归 | `cd ai_service && python -m pytest -q` | 1225 基线 + 24 新增全绿 | 见 §七 |
| 日志隐私 grep | `Select-String -Path rag/engine.py -Pattern 'query\[:50\]'` | ≥8 处（存量 6 + 新增 2） | 8 处 |
| 异常日志完整 grep | `Select-String -Path rag/engine.py -Pattern 'RAG chat 失败'` | 含完整 `request.query` 裸引用（仅 513 行） | 1 处 |
| 开关冒烟 | `python -c "from src.config import settings; print(settings.tool_auto_retry)"` | True（生产默认） | True |
| 红线核验 | `git diff --stat` | 代码改动限 4 生产文件 + conftest + 2 新增测试文件 | 符合 |

## 七、回归结果

- 全量 pytest：**1225 基线 + 24 新增 = 1249 passed / 0 failed**（215.24s；
  test_tool_retry_dedup 19 + test_log_privacy 5）；**存量测试零改动**（test_agent_tools
  62 项含 3 处 AgentTool.run 直接断言——恒抛重试仍失败返回 ""、超时精确文案
  不变——全部通过）。
- **预存 ERROR 1 项未触碰**：`scripts/test_models.py::test_model` 收集期
  `fixture 'label' not found`——module-050 遗留脚本（git log 实证最后一次改动
  36d3606 module-050，本模块 diff 零触碰），module-066/067 同款记录口径
  （"scripts/test_models.py 1 项 module-050 遗留 ERROR 未触碰"），与本次改动无关。
- 预算锁定复证：react_loop 集成测试断言 tool_count==1（工具首败重试成功）。

## 八、已知边界（如实标注）

1. **check_sufficiency 空转未完全消除**：同改写拦截在 check_sufficiency 之后
   （rewritten 只能由它产出）；输入级预拦截（完全免 LLM）因文档变化误拦合法重评
   不采纳。
2. **重试延迟最坏翻倍**：异常重试场景单工具墙钟上限 30s（15+15）；实际 429/闪断
   为秒级失败；generate/verify 不重试封顶；超时不重试防墙钟翻倍。
3. **tool_call_logs duration_ms 含重试耗时**：表结构一字不改红线（ADR-0017），
   重试细节在 logger.warning，不落表（task-brief 明确接受）。
4. **MCP 行为继承无新测试**：mcp_server.py:90 复用同一 run，6 只读工具全在重试集
   → 重试透明继承；超时围栏 15s 对 MCP 客户端不变；result_ok 语义不变
   （test_mcp_server.py:150 存量兼容）。
5. **日志截断口径以实测为准**：task-brief "其余 8 处" vs 实测 engine 内 6 处 +
   router 7 处 + query_rewrite 5 处，本模块只动指定的 3 行。

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-19 | 初始实现（WP-A~D） | Developer |
