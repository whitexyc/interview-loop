# Module-059 任务简报：工具治理 P1 —— 按执行阶段切分工具集

> 自包含执行简报（ADR-0012 方案 A 落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
>
> **2026-08-13 同步 worktree-m8-knowledge-panel（b42da5d）后修订**：工具口径 10 个（verify_answer / re_search / note_to_self 均已注册为工具），分组按本版执行。
>
> **⚠️ 执行状态（2026-08-13）：本模块已并入 module-058 一起执行**（058 新增 WP-E 引用本简报；两模块共用回归环境）。执行完成后：本简报 WP 的产出并入 058 交付物，058 验收时统一收口。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`ai_service`，FastAPI + asyncpg + pgvector + Apache AGE；执行路径参考 module-058：`.claude/worktrees/m8-knowledge-panel/ai_service`）。

**为什么做（动机）**：ADR-0012 记录——工具数量毒害 LLM 选工具准确率（~50 个 84-95% → 200 个 41-83% → 740 个接近 0%），且存在 Lost in the Middle 效应（列表中间的工具最容易被漏选）。当前 10 个工具虽在安全阈值内，但**全量暴露无阶段概念**：检索阶段 LLM 可能误调 `generate_answer`/`verify_answer`（现靠工具内部字符串防御"尚未检索到文档…"），生成阶段可能误调检索工具。本模块做**结构性阶段隔离**：省 schema token + 防误调 + 面试"未雨绸缪"叙事。

**现状（代码实测，勿改口径）**：

- **工具注册 10 个**（`agent/tool_registry.py:327-387`）：search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory / generate_answer / **verify_answer / re_search / note_to_self**（每个含 name + description + args_schema + func）
- **全量暴露**：`agent/react.py:213` `client.chat_with_tools(messages, tools.to_llm_schemas())`——每轮全量 10 个 schema，**无阶段状态机**；`agent/langgraph_react.py:89` 同款全量暴露
- **防误调现状**：`tool_registry.py:202-203` `_generate_answer` 内部检查 `ctx.docs` 空则返回"（尚未检索到文档，请先调用 search_knowledge 等检索工具）"；`_verify_answer`（:216-217）同款防御——字符串级防御，非结构性
- **三条新工具实现（归组依据）**：`_verify_answer`（:211-229）需 docs + answer 调 `reflector.verify_answer`（module-039 逐句 HHEM 验证）；`_re_search`（:232-257）需已有 docs（无 docs 返回"尚未检索"）→ `check_sufficiency` → 改写重检 → 累积 ctx.docs（module-040）；`_note_to_self`（:260-267）写 `ctx.scratchpad`（module-041，无前置依赖）
- **两条 ReAct 循环**：`agent/react.py::react_loop`（main.py:575 流式路径，含 max_answer_len 截断）与 `agent/langgraph_react.py::langgraph_react_loop`（main.py:643，module-030）——**都要覆盖**
- **预算路径**：预算=0 时无工具直接回答（react.py:205-210）；预算耗尽用 `ctx.docs` 兜底 `reflector.generate_answer`（react.py:260-271）——语义不变
- **测试**：740 passed（module-057 基线，同步后未重跑）

## 二、已知事实（勿重新调查）

| # | 事实 |
| - | ----------------------------------------------------------------------------------------------------------------- |
| 1 | 检索组 = search_knowledge / search_fts / search_vector / search_graph / extract_entities / recall_memory / **re_search**（7 个，均"取数/辅助取数"类；re_search 在初次检索不足时触发） |
| 2 | 生成组 = generate_answer / verify_answer / note_to_self / **re_search（双组）**（4 个；verify 需 docs+answer 必须在生成后；re_search 实现依赖已有 docs，本质是"反思-重检"工具 → 初次检索不足 + 生成后验证不充分两个时机都要用，**双组可见**） |
| 3 | 阶段判定标准（Q1 结论）：**以"是否已调用过 generate_answer 或 verify_answer"为界**，而非"ctx.docs 是否非空"——后者会切断"生成后发现不足→再补检"能力 |
| 4 | 补检口（Q2 结论，代码实证）：**re_search 双组**即解决补检——生成阶段验证（verify_answer）判不充分后，LLM 调 re_search 改写重检，新结果累积 ctx.docs 后再 generate_answer 迭代；无需在生成组额外塞 search_* |
| 5 | 切换方向：retrieval → generation **单向前进**（调 generate_answer 或 verify_answer 后置 generation）；generation 内调 re_search **不回退**（补检语义，防死循环） |
| 6 | LLM 单轮可返回多个 tool_calls（react.py:231 预算截断前全执行）——阶段按"本轮调用前"确定；generate_answer/verify_answer 不在检索阶段 schema 内，**检索阶段同轮无法混合"先检后生"**，LLM 需先检索（可能多轮）再调生成工具（下一轮切 generation）。这是本设计的预期行为（强制"先检后生"），不是缺陷 |
| 7 | 配置开关：`PW_TOOL_PHASE_SPLIT`（默认 **true**，保留 false 回退全量暴露零回归）——对齐 `PW_RETRIEVAL_FUSION_MODE` 既有模式 |
| 8 | 系统提示词 `_SYSTEM_PROMPT`（react.py:42-65）已列 10 个工具并含规则 5"检索结果不相关时调 re_search 重检"——**阶段切分不要求改 prompt 工具清单**，但建议在 prompt 中补充阶段语义一句话（可选） |

## 三、任务步骤（按序，每步有通过标准）

### WP-A 阶段状态机 + 分组暴露（🔴 核心，半天）

- **ToolRegistry 加 group 属性**：每个工具注册时带 `group`（"retrieval" / "generation"，双组工具用 `["retrieval","generation"]`），新增 `to_llm_schemas(group=None)`（None=全量，传组=过滤）；`register_builtin_tools` 为 10 个工具标注组（见事实 1/2）
- **ReactContext 加 `phase` 字段**（默认 "retrieval"）
- **react_loop 改造**：每轮 `schemas = tools.to_llm_schemas(group=ctx.phase)`（retrieval → 7 个；generation → 4 个）；执行完本轮 tool_calls 后，若含 `generate_answer` 或 `verify_answer` → `ctx.phase = "generation"`
- **langgraph_react_loop 同步改造**（langgraph_react.py:89 同一调用点；同一 ctx / registry 逻辑，抽公共辅助函数避免两处漂移）
- **开关**：`settings.tool_phase_split`（读 PW_TOOL_PHASE_SPLIT，默认 true）；false 时 `to_llm_schemas(group=None)` 全量，零回归
- **通过标准**：单测覆盖——① retrieval 阶段 schema 恰好 7 个且不含 generate_answer/verify_answer；② 调 generate_answer 后下一轮 schema = 生成组 4 个（含 re_search）；③ generation 内调 re_search 后仍 generation；④ 调 verify_answer 同样切 generation；⑤ 开关 false 时全量 10 个；⑥ 预算=0 / 预算耗尽兜底路径行为与改动前逐字一致；⑦ **conftest autouse fixture 钉住测试环境 `PW_TOOL_PHASE_SPLIT=false`（对齐 module-056 分类器开关模式），新测试显式开 true 验证切分——默认 true 会漂移走 react 层的存量 agent 测试，钉住是"存量全绿"的真正保证**

### WP-B 回归 + 真实 E2E 冒烟（🟡 半天）

- **全量 pytest 740 全绿**（存量测试不改；如 test_agent_tools.py 有断言依赖全量 schema 需核对——预期无，纯新增过滤逻辑）
- **真实 E2E（uvicorn 8001）**：chat 一条知识题（观察 tool_trace：先 search_knowledge → generate_answer →（可选 verify_answer）→ 阶段切换正确、无"尚未检索"防御串）；stream 一条（事件流正常，done 带 sources）
- **通过标准**：740/0；E2E 两条真实链路 tool_count/阶段切换符合预期

### WP-C 文档收口（🟢 1 小时内）

- ADR-0012 状态行更新为"✅ P1 已实施（module-059）"（工具 10 个口径已在 08-13 同步复核）
- 面试口径：简历 08 文档 2.x + CONTEXT.md 更新点——"10 个工具按阶段切分：检索阶段 7 个（含 re_search 重检）、生成阶段 4 个（generate_answer/verify_answer/note_to_self + re_search 补检口），ctx.phase 状态机结构性防误调 + 每轮省 schema token；未来工具扩量走 ADR-0012 三档路线（阶段切分 → 意图路由分组 → 动态工具检索）"
- **通过标准**：ADR-0012 / 记忆三件套（project-context / agent-activity-log / file-index）同步；简历弹药可背诵

## 四、纪律项（违反 = 返工）

1. **不破坏现状**：默认 rrf 三通道不动；预算=0 / 预算耗尽兜底语义不变；**存量测试零改动**（740 基线）
2. **两条循环同改**：react_loop + langgraph_react_loop 只改一处 = 回归；抽公共辅助函数
3. **阶段切换单向前进**：generation 不因调 re_search 回退（防死循环）；不引入"docs 非空即生成"口径
4. **不新增/不删除/不改写工具**：只动暴露逻辑，10 个工具的 name/description/args_schema 一字不改
5. **开关必须留**：PW_TOOL_PHASE_SPLIT=false 回退全量，零回归可一键逃生

## 五、交付物

1. 代码：tool_registry（group + 过滤）、react.py / langgraph_react.py（阶段状态机）、config（开关）
2. 单测：阶段暴露/切换/补检/开关/预算路径（新增，不碰存量）
3. 真实 E2E 冒烟记录（chat + stream 各一条，含 tool_trace 与阶段切换）
4. ADR-0012 更新 + 记忆三件套 + 面试口径更新点（08 文档 + CONTEXT.md）
