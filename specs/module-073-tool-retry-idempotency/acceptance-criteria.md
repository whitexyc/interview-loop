# 验收标准 — Module-073: 工具防重复 + 失败自动重试 + 日志隐私修正

> 依据：`plan.md` v1（2026-08-19）| 验收口径：全量 1225 基线 + 新增全绿、存量测试零改动红线

## 1. 功能验收

### 1.1 核心路径验收（WP-A 防重复）
- [ ] AC-1 `ReactContext.add_note`：同内容 note（strip 后完全一致，含首尾空白差异）二次追加返回 False 且 scratchpad 不重复；不同 note 追加返回 True（react.py:99-101）
- [ ] AC-2 `note_to_self` 工具：重复 note 返回"笔记已存在（未重复记录）"且 scratchpad 长度不变；首次/新 note 返回"已记录笔记"（tool_registry.py:281-288）
- [ ] AC-3 `ReactContext` 新增 `last_research_query: str = ""` 字段（react.py __init__）
- [ ] AC-4 `re_search`：连续两次相同改写 query → 第二次返回"已按该改写重检过，无新结果"，且不再调 hybrid_retriever.retrieve / add_docs / _format_docs；不同改写 query 正常执行（tool_registry.py:253-278）
- [ ] AC-5 re_search 守卫边界：check_sufficiency 返回 sufficient → 提前返回且不更新守卫字段；空改写（rewritten_query 缺失/等于原 query）同输入二次调用 → 拦截；文档累积幂等（_seen_ids）逐字不动

### 1.2 核心路径验收（WP-B 失败自动重试）
- [ ] AC-6 `AgentTool.run`：只读检索类（search_*/extract_entities/recall_memory/re_search）+ note_to_self 异常 → 自动重试 1 次同一 func 同参数同 ctx；重试成功返回正常结果（tool_registry.py:57-74）
- [ ] AC-7 重试仍失败 → 返回 ""（与现状一致，LLM 判断继续/放弃，module-028 降级哲学不变）；两次失败各有 warning 日志（"首次失败，自动重试"/"重试仍失败，返回空"）
- [ ] AC-8 超时（15s）不重试 → 返回 `"(工具 X 执行超时)"` 精确文案不变；重试内超时同样返回超时提示；**TimeoutError 分支先于重试分支判断**
- [ ] AC-9 generate_answer / verify_answer 异常不重试（func 仅执行 1 次）
- [ ] AC-10 开关 `tool_auto_retry=false`（PW_TOOL_AUTO_RETRY）→ 全工具不重试（func 仅执行 1 次，存量行为零回归）
- [ ] AC-11 **预算锁定**：重试不增加 tool_count / phase_count（react_loop 集成测试：工具首败后成功 → tool_count==1、tool_trace 1 条、消息历史 1 条 tool 结果）；record_tool_call 只记 1 次（最终结果），duration_ms 含重试耗时；**tool_call_logs 表结构零改动**（ADR-0017 红线）

### 1.3 核心路径验收（WP-C 日志隐私：正常截断 / 异常完整）
- [ ] AC-12 `engine.search` 正常路径日志 query 截断 [:50]（engine.py:246），完整 query 不出现
- [ ] AC-13 `engine.chat` 正常路径日志 query 截断 [:50]（engine.py:307），完整 query 不出现
- [ ] AC-14 `engine.chat` 异常路径日志含**完整** query + 错误信息 + 堆栈（engine.py:513）——异常完整原则
- [ ] AC-15 原则注释声明（L246 附近）：正常路径一律 [:50] 截断 / 异常路径完整记录（排查需要）/ tool_call_logs args 完整保留（审计用途）

### 1.4 边界条件验收
- [ ] AC-16 note 判重边界：带首尾空白 note 与 strip 后等价文本判重复（" 笔记 " == "笔记"）；空/纯空白 note 仍返回"未提供笔记内容"；>500 字 note 截断后判重（两次相同超长 note 判重复）
- [ ] AC-17 重试边界：开关关时重试分支不可达；超时异常不进入重试（仅进入超时分支）；重试内 TimeoutError 与 Exception 分别处理返回不同提示/空串
- [ ] AC-18 日志边界：query 恰好 50 字符不截断；>50 字符截断；异常路径 query 为空字符串也能完整记录（不崩）
- [ ] AC-19 守卫首调边界：last_research_query 初始 ""，首次 re_search 无论改写与否正常执行并记录

### 1.5 异常场景验收
- [ ] AC-20 工具恒抛异常（重试仍失败）→ 返回 ""，循环继续（存量 test_tool_run_failure_returns_empty 兼容）
- [ ] AC-21 检索工具瞬时抖动（首次异常、二次成功）→ 自动重试恢复，对 react_loop / LLM 完全透明（无第二个 tool_call 事件、无重复 tool 结果消息）
- [ ] AC-22 MCP 路径（mcp_server.py:90）自动继承重试：只读工具异常 → 重试后正常返回；超时围栏 15s 对客户端不变（零改动验证，test_mcp_server.py 存量兼容）

## 2. 非功能验收

### 2.1 性能验收
- [ ] AC-23 正常路径零开销：工具首次成功不触发重试分支任何额外日志/调用（无 perf 回归）
- [ ] AC-24 重试延迟受控：超时不重试（单工具墙钟上限 30s 仅异常重试场景可达，实际 429/闪断异常为秒级失败）

### 2.2 安全验收（隐私）
- [ ] AC-25 日志隐私：正常路径 INFO 日志无完整 query（grep 核验 engine.py:246/307 参数为 `request.query[:50]`）；异常路径完整 query 仅 error 级别（排查用途）
- [ ] AC-26 tool_call_logs args JSONB 完整保留语义不变（审计用途，表结构零改动红线）

### 2.3 代码质量验收
- [ ] AC-27 全量 pytest = 1225 基线 + 新增全绿（0 failed）；**存量测试零改动**（test_agent_tools 62 项含 3 处 AgentTool.run 直接断言全部通过）
- [ ] AC-28 新增单测覆盖：test_tool_retry_dedup.py（WP-A ~8 项 + WP-B ~8 项，含预算锁定）+ test_log_privacy.py（WP-C ~4 项 caplog）
- [ ] AC-29 无新依赖、无新表、无新端点；langgraph_react.py / mcp_server.py / database.py 零改动（git diff 核验）；代码改动仅限 tool_registry.py / react.py / config.py / engine.py / conftest.py + 2 个新增测试文件
- [ ] AC-30 生产功能代码 ≤ 200 行（预估 ~40 行）；ponytail 最简实现（去重 if + 重试 try 嵌套 + 3 处截断，不重写执行层）；无 linter 错误、命名符合项目规范

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量回归 | `cd ai_service && python -m pytest -q` | 1225 基线 + 新增全绿，0 failed |
| 定向单测 | `python -m pytest tests/agent/test_tool_retry_dedup.py tests/core/test_log_privacy.py -q` | 全部 passed |
| 日志隐私 grep | `Select-String -Path rag/engine.py -Pattern 'query\[:50\]'` | ≥8 处（存量 6 + 本模块 246/307 新增） |
| 异常日志完整 grep | `Select-String -Path rag/engine.py -Pattern 'RAG chat 失败'` | 含完整 `request.query` 裸引用（仅 513 行） |
| 红线核验 | `git diff --stat` | 代码改动限 4 生产文件 + conftest + 2 新增测试文件；tool_call_logs 表/循环逻辑/MCP/langgraph 零改动 |
| 开关冒烟 | `python -c "from src.config import settings; print(settings.tool_auto_retry)"` | True（生产默认） |

## 4. 验收结论
- 审查人: Reviewer（2026-08-19 审查通过 ✅ PASS——全量 1249/0 独立复跑 + 24 项定向 + 133 项受影响存量 + 日志 grep + 红线 git diff 实证，4 项 LOW 非阻塞；详见 review-report.md）
- 测试人: <Tester 签名>
- 验收时间: 2026-08-19
- 结论: [x] 通过（Reviewer 侧）/ [ ] 不通过
- 备注: AC-1~AC-30 全部核对通过（见 review-report.md §六 对照表）；建议 Tester 重点关注 AC-11 预算锁定集成测试、AC-22 MCP 路径继承、AC-12~14 日志 levelno 过滤断言手法
