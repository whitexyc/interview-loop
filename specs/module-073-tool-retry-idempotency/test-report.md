# Module-073 测试报告 — 工具防重复 + 失败自动重试 + 日志隐私修正

> Tester：2026-08-19 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：✅ Pass（Reviewer 全量 1249/0 独立复跑 + 24 项定向 + 133 项存量 + 红线 git diff 实证，见 review-report.md）
> **验收结论：✅ 通过（Tester 独立复验：全量 1249/0 + 24 项定向全绿 + 133 项受影响存量全绿 + 真实 chat 冒烟日志截断实证）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1249 passed / 0 failed（202.47s，148 warnings）** = 1225 基线 + 24 新增 |
| 新增单测 | `tests/agent/test_tool_retry_dedup.py` 19 项 + `tests/core/test_log_privacy.py` 5 项 = **24 项全绿**（独立运行 48.81s） |
| 受影响存量套件 | test_agent_tools / test_tool_call_logs / test_mcp_server / test_tool_phase_split / test_agent_phase_fix = **133 passed**（83.35s） |
| 存量测试改动 | **零改动**（`git diff tests/` 仅 conftest.py +14 行 autouse fixture 钉住 `tool_auto_retry=False`，对齐 056/058/066 模式，验收许可） |
| 全量收集口径 | git 已跟踪测试 1187 项 + 并行未跟踪测试 38 项（tests/retrieval/ 26 + test_tool_history_wiring.py 12，非本模块产物，参与收集全绿）+ 本模块 24 项 = 1249（口径与 Developer "1225 基线" 一致：1225 = 1187 + 38 并行项） |
| 收集 ERROR | 1 项预存：`scripts/test_models.py::test_model`（module-050 遗留，未触碰；项目惯例跑 `pytest tests/` 不受影响） |

## 二、新增单测抽查（任务 1 验证点逐项核对，24/24 全过）

### test_tool_retry_dedup.py（19 项）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| AC-1 add_note 完全一致去重（strip 后逐字，含首尾空白差异判重复）返回 bool | ✅ | `test_add_note_exact_duplicate_returns_false`：`"重要发现"` → `"  重要发现  "` 返回 False 不追加；不同 note 返回 True 正常追加 |
| AC-2 note_to_self 重复提示"笔记已存在（未重复记录）"且 scratchpad 长度不变 | ✅ | `test_note_to_self_duplicate_returns_hint`：二次调用返回提示，len==1；首次返回"已记录笔记" |
| AC-16 空/纯空白 note 仍返回"未提供笔记内容" | ✅ | `test_note_to_self_empty_returns_hint` |
| AC-16 >500 字 note 截断后判重（两次相同超长 note 判重复） | ✅ | `test_note_to_self_long_note_truncated_dedup`：600 字两次调用 len==1 |
| AC-4 re_search 同改写 query 二次拦截 + retrieve 仅首调 | ✅ | `test_same_rewritten_blocks_second`：retrieve.await_count==1、sufficiency 仍调 2 次（守卫在 check_sufficiency 之后，如实标注） |
| AC-4 不同改写 query 正常执行 | ✅ | `test_different_rewritten_ok`：两次改写各检索一次 |
| AC-5 sufficient 分支不更新守卫字段 | ✅ | `test_sufficient_does_not_update_guard`：last_research_query 仍 "" |
| AC-5 空改写（rewritten_query 缺失）同输入二次拦截 | ✅ | `test_same_raw_query_blocks`：retrieve.await_count==1 |
| AC-19 守卫首调边界（last_research_query 初始 ""） | ✅ | `test_first_call_records_guard` |
| AC-6/AC-21 检索工具异常重试 1 次成功（func 计数==2，返回正常结果） | ✅ | `test_retry_recovers_after_first_failure`：瞬时 429 → 重试 → "检索结果 ok"，calls==2 |
| AC-7/AC-20 重试仍失败返回 ""（LLM 判断继续/放弃） | ✅ | `test_retry_still_fails_returns_empty`：await_count==2、返回 "" |
| AC-8/AC-17 超时不重试（wait_for 仅调 1 次，精确文案不变） | ✅ | `test_timeout_no_retry`：monkeypatch asyncio.wait_for 抛 TimeoutError → wait_for.call_count==1、返回 `"(工具 slow_tool 执行超时)"` |
| AC-9 generate_answer / verify_answer 不重试（func 仅 1 次） | ✅ | `test_generate_verify_not_retried`：两工具 await_count==1 |
| AC-10 开关 false（conftest autouse 钉住）全工具不重试 | ✅ | `test_switch_off_no_retry`：await_count==1（存量行为零回归） |
| AC-7 两次失败各有 warning 日志 | ✅ | `test_retry_warning_logs`（caplog）：「首次失败，自动重试」+「重试仍失败，返回空」 |
| AC-17 重试内超时单独处理返回超时提示（非空串） | ✅ | `test_retry_timeout_inside_retry`：首败→重试超时 → `"(工具 search_knowledge 执行超时)"` |
| **AC-11 预算锁定**（react_loop 集成：工具首败后重试成功） | ✅ | `test_retry_budget_locked_in_react_loop`：calls==2 / tool_call 事件==1 / done.tool_count==1 / 消息历史 tool 结果==1 条 / record_tool_call.await_count==1 |

### test_log_privacy.py（5 项）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| AC-12 engine.search 正常 INFO 截断 [:50]、完整 query 不出现 | ✅ | caplog levelno==INFO 过滤：60 字符 query → 含 [:50] 前缀、不含完整 |
| AC-18 query 恰好 50 字符不截断 | ✅ | `_EXACT_50` 在日志中完整出现 |
| AC-13 engine.chat 正常 INFO 截断 [:50]（levelno 过滤防假阴性） | ✅ | mock resolve_tool_history + router 走 realtime 快捷路径，完整 query 缺席 |
| AC-14 异常路径 ERROR 含完整 query + 错误信息 + 堆栈 | ✅ | mock resolve_tool_history 抛 RuntimeError → ERROR 记录含完整 query、「模拟失败」、rec.exc_info is not None |
| AC-18 异常路径空 query 不崩 | ✅ | query="" → ERROR 记录含 "query=" + 错误信息 |

## 三、红线核验（Tester 独立 git diff）

| 核验项 | 结果 | 依据 |
|--------|------|------|
| langgraph_react.py / mcp_server.py / database.py / router.py 零改动 | ✅ | `git diff --stat` 对四文件无输出 |
| tool_call_logs 表结构零改动（ADR-0017） | ✅ | diff 无 database.py / 表 DDL 文件 |
| 生产改动文件 | ✅ | 仅 react.py / tool_registry.py / engine.py / config.py 4 个 + conftest.py（+14 autouse） |
| 存量测试零改动 | ✅ | `git diff tests/` 仅 conftest.py +14 行 |
| 日志截断 grep | ✅ | engine.py 内 `query[:50]` 共 8 处（存量 6 + 新增 246/309 两处） |
| 异常日志完整 grep | ✅ | 「RAG chat 失败」仅 1 处（L516）且为完整 `request.query` 裸引用 + exc_info=True |
| 开关冒烟 | ✅ | `settings.tool_auto_retry == True`（生产默认，PW_TOOL_AUTO_RETRY 可关） |

## 四、冒烟（真实环境，Tester 独立执行）

**真实 chat 全链路冒烟**（deepseek-v4-flash + 本地 Postgres + reranker + HHEM，query 构造为 60 个"测"前缀 + 真实问题共 >50 字符）：

- chat 正常路径 INFO 日志 `RAG chat: query=测测测…（50 字符截断）, history=0` → **truncated_ok=True**（含 query[:50] 前缀、完整 query 不出现）
- 全链路 INFO 日志扫描：**完整 query 未在任何 INFO 记录中出现**（full_query_in_info=False）
- 全链路正常完成（result=ok，retrieval→sufficient 反思→generate→HHEM 验证 supported=5/unsupported=3）
- 异常路径完整日志由 caplog 单测覆盖（mock 抛错触发 L516），真实链路异常不人为制造

重试开关行为真实链路：工具瞬时异常属低概率外部事件，真实冒烟中未触发重试路径——重试行为由单测锁定（func 计数断言），如实标注未做真实抖动复现。

## 五、观察与诚实声明

1. **全量 1249 收集口径**：git 已跟踪基线 1187 + 并行未跟踪测试 38 项（tests/retrieval/test_query_rewrite_history.py 26 项 + tests/agent/test_tool_history_wiring.py 12 项——创建于本模块交付前、非本模块 filesChanged 内，可能系并行会话产物）+ 本模块 24 项 = 1249。与 Developer「1225 基线 + 24 新增」逐字一致（1225 = 1187 + 38 并行项已含其基线统计），总数无矛盾；38 项并行测试全绿且与本模块零关联。
2. **真实重试路径未复现**：真实 chat 冒烟中检索工具无异常（无 429/闪断），重试分支行为由 mock 单测锁定（func 计数、wait_for 计数），如实标注。
3. **check_sufficiency 空转未完全消除**（plan 已知边界）：守卫在 check_sufficiency 之后，第二次调用仍执行一次充分性评估——单测断言 sufficiency.await_count==2 如实锁定该行为。
4. **重试内超时/重试仍失败均为单测覆盖**：真实链路低概率事件不人为制造，与项目既有冒烟口径一致。

## 六、AC 逐条对照（30 项，AC-1~AC-30 全过）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| AC-1~AC-5（WP-A 防重复 5 项） | ✅ | 单测逐项（§二） |
| AC-6~AC-11（WP-B 重试 6 项） | ✅ | 单测逐项，AC-11 预算锁定由 react_loop 集成测试断言 |
| AC-12~AC-15（WP-C 日志 4 项） | ✅ | caplog 单测 + 真实冒烟 + grep 核验 + L246 原则注释 |
| AC-16~AC-19（边界 4 项） | ✅ | 单测（空白/截断/超时优先/50 字符边界/守卫首调） |
| AC-20~AC-22（异常 3 项） | ✅ | 恒抛重试仍失败返回 "" / 瞬时抖动重试恢复（react_loop 集成透明）/ MCP 继承（复用同一 run，mcp_server.py 零改动，test_mcp_server.py:150 存量兼容 133 项全绿） |
| AC-23~AC-24（性能 2 项） | ✅ | 首次成功零重试分支（单测 func 计数==1）；超时不重试防墙钟翻倍 |
| AC-25~AC-26（安全 2 项） | ✅ | grep 实证 8 处截断 + L516 完整；tool_call_logs args JSONB 语义不变（表结构零改动） |
| AC-27~AC-30（质量 4 项） | ✅ | 全量 1249/0 存量零改动 / 新增 24 项覆盖 / 无新依赖无新表无新端点 / 生产功能行数 ~40 行 ≤200、ponytail 最简 |

## 七、结论

**验收通过。** 关键验证点：
1. 全量 1249/0 独立复跑全绿（202.47s），存量测试零改动（仅 conftest autouse +14 许可）；
2. 新增 24 项单测覆盖任务 1 全部验证点：note_to_self 去重 / re_search 同改写守卫 / 重试 1 次成功 / 重试仍失败返回空 / 超时不重试 / 开关 false 不重试 / 预算 tool_count 不增（react_loop 集成断言）/ 日志截断与完整；
3. 红线核验实证：langgraph/mcp/database/router 零改动、tool_call_logs 表结构零改动、`query[:50]` 8 处、异常日志 1 处完整；
4. 真实 chat 冒烟（deepseek + 本地 PG 全链路）：INFO 日志截断 [:50] 生效、完整 query 未泄露；
5. 开关冒烟 tool_auto_retry=True（生产默认）。

**模块状态：✅ 验收通过（待 Developer 提交推送后 team-lead 收口）**
