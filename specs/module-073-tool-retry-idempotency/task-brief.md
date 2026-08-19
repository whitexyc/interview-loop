# Module-073 Task Brief：工具防重复 + 失败自动重试 + 日志隐私修正

> 自包含执行简报（2026-08-19 用户决策：note_to_self/re_search 防重复 + 失败重试机制 + 日志"正常截断异常完整"）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。

## 事实（代码实测，2026-08-19）

1. **note_to_self 无防重复**（tool_registry.py:281-288）：`ctx.add_note(note)` 直接 append 到 scratchpad（react.py:99-101）——重复执行同内容 note = scratchpad 两条重复笔记（唯一有重复副作用的写工具）。
2. **re_search 半防重复**（tool_registry.py:253-278）：`ctx.add_docs` 已按 doc id 去重（react.py:103-109 `_seen_ids`）——文档累积幂等；但**重复执行本身浪费**（check_sufficiency LLM 调用 + 重检索），连续两次相同改写 query 重检 = LLM 空转。
3. **失败无自动重试**（AgentTool.run，tool_registry.py:57-74）：15s 超时围栏返回"执行超时"、异常返回空串——结果喂回 LLM 判断继续/放弃（module-028 降级哲学）。偶发抖动（LLM 429/网络闪断）一次失败就失败。
4. **预算语义**（react.py:397+）：tool_count 计数的是"LLM 提议的工具调用次数"——**自动重试发生在 AgentTool.run 内部（同一 func 重跑），不增加 tool_count**（预算不受影响，关键设计点）。
5. **日志隐私缺口**（engine.py）：
   - :246 `"RAG search: query=%s"` 完整打印（正常路径不该完整）
   - :307 `"RAG chat: query=%s"` 完整打印（同上）
   - :513 `logger.error("RAG chat 失败: %s", e, exc_info=True)` **只记错误不记 query**（异常路径反而缺 query）
   - 其余 8 处日志已 `query[:50]` 截断 ✅
   - 用户决策：**正常截断（[:50]）、异常完整**（异常需要完整信息排查）
6. **tool_call_logs**（module-066 / ADR-0017）：args JSONB 完整记录工具参数（含 query）——审计用途，**表结构一字不改红线**；重试细节不落表（在 logger.warning），如实标注。
7. **基线**：全量 1225/0（module-072 后 + HyDE prompt 优化）。

## WP-A：防重复（去重是重试的前置条件）

- `ReactContext.add_note`（react.py:99-101）加去重：`note.strip()` 已存在于 scratchpad → 不追加；`_note_to_self`（tool_registry.py:281-288）返回"笔记已存在（未重复记录）"
- `ReactContext` 加 `last_research_query: str = ""` 字段；`_re_search` 连续两次**相同改写 query** → 返回"已按该改写重检过，无新结果"（防 LLM 空转）；首次/不同 query 正常执行
- 文档累积幂等（_seen_ids）不动
- 通过标准：单测（同 note 不追加/不同 note 追加/同改写 query 连续调用提示/不同 query 正常）

## WP-B：失败自动重试（执行层一次自我修复，LLM 决策层不动）

- `AgentTool.run`（tool_registry.py:57-74）catch 异常后**重试 1 次同一 func（同参数）**；**超时（15s）不重试**（超时=慢不是抖动，重试翻倍延迟）
- 工具类型策略：
  - 只读检索类（search_*/extract_entities/recall_memory/re_search）：异常重试 1 次（只读重试天然安全）
  - note_to_self：异常重试 1 次（WP-A 去重后双写被拦，安全）
  - generate_answer / verify_answer：**不重试**（15s 超时是常态，重试无意义）
- 开关：config `tool_auto_retry: bool = True`（PW_TOOL_AUTO_RETRY 可关）
- 可观测：重试发生时 `logger.warning("工具 %s 首次失败，自动重试: %s", name, e)`；tool_call_logs 只记最终结果（result_ok/duration 含重试耗时，表结构不改）
- 预算：重试不增加 tool_count（AgentTool.run 内部，关键设计点——单测断言 tool_count 不变）
- 通过标准：单测（检索工具异常重试 1 次成功/重试仍失败返回提示/超时不重试/开关 false 不重试/预算不增）

## WP-C：日志隐私修正（正常截断 / 异常完整）

- engine.py:246 `query[:50]`（正常截断）
- engine.py:307 `query[:50]`（正常截断）
- engine.py:513 改为 `logger.error("RAG chat 失败: query=%s, error=%s", request.query, e, exc_info=True)`（异常完整：query 原文 + 错误 + 堆栈）
- 原则落定（代码注释声明）：正常路径一律 [:50] 截断；异常路径完整记录（排查需要完整信息）；tool_call_logs args 完整保留（审计用途）
- 通过标准：单测（正常路径日志含截断 query/异常路径日志含完整 query）或 grep 断言

## WP-D：回归 + 文档收口

- 全量 1225 基线 + 新增单测全绿（存量测试零改动红线）
- changelog + CONTEXT.md（只增不删先备份）+ 三记忆文件
- METRICS.md 无相关段（不加）

## 纪律项

1. 只动 `tool_registry.py`（_note_to_self/_re_search/AgentTool.run）+ `react.py`（add_note/ctx 字段）+ `config.py`（开关）+ `engine.py`（3 处日志）+ 相关单测
2. **tool_call_logs 表结构零改动**（ADR-0017 一字不改红线）；重试细节在日志
3. 重试不增加预算（tool_count 语义不变）——单测锁定
4. 判定器确定性优先；编码调 ponytail skill（最简可行：去重 if + 重试 try 嵌套 + 3 处截断，不重写执行层）
5. 存量测试零改动（改了=FAIL）
