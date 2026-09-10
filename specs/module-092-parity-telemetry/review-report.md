# 审查报告 — Module-092: 对比评测深化（多轮采样 + 分阶段遥测 + 冷启动）

> 审查人：reviewer-092 ｜ 审查时间：2026-09-10 ｜ 依据：plan.md + acceptance-criteria.md（AC-1~28 + T1~T9）+ changelog.md + 全文件通读 + 独立复算/复跑/DB 抽查
> 审查方式：静态全文件通读（非仅 diff）＋ `ast` 独立复算 AST ＋ 单测独立复跑 ＋ 全量回归 junitxml 权威计数 ＋ PostgreSQL 只读抽查 agent_eval_runs ＋ 磁盘 JSONL 留痕字段与 stage_tokens 复算

---

## 1. 审查结论

**结论：通过（附条件通过）** —— 0 阻塞 / 0 高 / 2 中 / 5 低。

- 最高优先项（AC-23 usage 差分归属）**经独立核实裁定为正确且健壮**，任务提示担心的「供应商未返回 usage 致差分错位」场景**不会发生**（设计用「每调用各自基准 `u0`」而非位置对齐，见 §5 专项裁定）。
- 红线 `agent/ src/ main.py` 零 diff **成立**（实测 `git diff --stat` 全空）；`src/config.py` 的偏离为**已申报的可接受偏离**（见 §5 红线裁定）。
- 全量回归 **1825 passed / 0 failed / 3 skipped**（junitxml 权威计数；任务所称「1800」为旧基线近似值，实际随 module-093 等增至 1825，关键结论「0 失败 / 3 跳过 / 零新增失败」成立）。
- 阻塞项：无。中危 2 项（方法超 50 行、IO trace 的 `round` 字段恒为 1）均为非阻断，归 Developer 下一轮跟进；Tester 需注意 T8 复算前提受 `round` 字段缺陷影响（见问题 #3/#4）。

---

## 2. 问题列表

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|----------|----------|
| 1 | `ai_service/eval/parity_telemetry.py` | 465–528 | `main` 物理 67 行（含 docstring 66 行），超 AC-15「方法 ≤50 行」；changelog §一称「方法最长 main ≤50」与实际不符 | 中 | 将落库循环（L501–514）、汇总与报告（L516–527）拆为独立函数，使 `main` ≤50 行 |
| 2 | `ai_service/eval/parity_telemetry.py` | 402–462 | `print_report` 物理 61 行，超 AC-15 | 中 | 拆为「聚合表 / 工具明细 / 冷启动 / 失败清单」子打印函数（均 ≤50 行） |
| 3 | `ai_service/eval/parity_telemetry.py` | 238 | `run_round_real` 调用 `run_telemetry_side(loop, item, 1)` 硬编码 `k=1`，repeat 序号 `i` 未透传；导致 IO trace 的 `round` 字段恒为 1（实测 564 条全为 round=1），批次间无法按轮分离 | 中 | `run_round_real` 将 `i` 作为 round meta 传入：`run_telemetry_side(loop, item, i)`，并把 `i` 透传至 `wrap_llm_io(..., round=i, ...)`；同时 `lp.run_side` 的 trace_id 后缀亦用 `i`（当前用 `k`）；确保 `round` 与真实 repeat 对齐 |
| 4 | `ai_service/eval_io_traces/io-20260910-162434.jsonl`（id=12~17） | — | 首次跑批 trace 缺 `tool` 与 `usage` 字段（旧版 parity_io 生成，仅含 seq/loop/task_id/round/in_tool/input/duration_ms/output）；不满足 AC-21 要求的 `tool` 字段，且 §十.2 的分阶段 token 无法从该 trace 复算 | 中 | 该 trace 为历史产物（跑批早于字段上线）。建议：① 在 changelog 注明此 trace 由旧版生成、字段不全；② Tester 以第二批 trace `io-20260910-182411.jsonl`（含 tool+usage）为主核对 T7/T8；③ 修复 #3 后若需完整可复算，可重跑补齐（成本较高，非必须） |
| 5 | `specs/module-092-parity-telemetry/changelog.md` | §二 / §九.1 / §9.4 | 数字与实测不一致：§二 parity_telemetry「198」（实际 193，§九迁移后值）；§九.1 parity_io「90 AST」（实际 118）；§9.4 parity_io「19 项」（实际 25，§十追加 6 项） | 低 | 同步为实测值 193 / 118 / 25 |
| 6 | `specs/module-092-parity-telemetry/changelog.md` §7.2 / `plan.md` §7.2 / `acceptance-criteria.md` §AC-28 | — | config.py 偏离归因表述不准：`git diff b9faa29..HEAD -- ai_service/src/config.py` 显示 config.py 由独立提交引入（ce6646b「module-093 OpenCode Zen provider 接入」+ opencode 三字段；8ac4c4a「[config] 降级链调整」+ fallback_chain 默认），module-092 自身 `git diff -- agent/src/main.py` 为空 | 低 | 注明「opencode 三字段来自 module-093、fallback_chain 默认值来自 [config] 提交；module-092 跑批依赖之，故列为本模块偏离可接受」；运行期 .env 已含同款链，零运行时差异，无需 ADR |
| 7 | `ai_service/eval/parity_telemetry.py` | 126–140 | `_usage_interceptor` 为模块级公开函数却仅有行内注释、缺 `"""` docstring（其余 public 函数均有） | 低 | 补 docstring（Args/Returns，说明原函数先执行再本地捕获、sparse usage 不中断） |
| 8 | `ai_service/eval/parity_telemetry.py` | 373 | `subprocess.run(..., timeout=600)` 魔法数字 | 低 | 提为模块常量 `_SUBPROCESS_TIMEOUT_S = 600` |
| 9 | `ai_service/eval/parity_telemetry.py` | 207–210 | `_agent_lg.execute_tool_with_log` 用 `_tool_guard(_agent_react.execute_tool_with_log)` 包（即 langgraph 侧工具执行实际走 react 原函），代码异味 | 低 | 改为两环路各自包各自原函：`_tool_guard(_agent_lg.execute_tool_with_log)`；功能等价（两函数同源），仅可读性 |

> 注：问题 #3/#4 同源——`round` 字段缺陷使 §十.2「每轮 × 环路」的分阶段 token 表**无法从持久化 JSONL 逐值复算**（T8 前提受损）；但 `stage_tokens`/`_usage_delta` 函数本身正确（单测 25/25 全绿），§十.2 数值系内存内按轮聚合得出、比例合理（环路级 76–80% / 工具内 20–24%，与复算比值一致）。建议 Tester 用内存路径或修复 #3 后复算。

---

## 3. 验收标准核对

| 验收项 | 对应代码 文件:行号 | 状态 | 备注 |
|--------|-------------------|------|------|
| AC-1 多轮采样 | `parity_telemetry.py:271` round_order + `:497` 主循环 | ✅ PASS | DB 实测 id=12~23 repeat=0/1/2 × loop 两值 |
| AC-2 聚合统计 | `parity_telemetry.py:286` aggregate_rounds | ✅ PASS | mean±std/min/max + 逐轮值 |
| AC-3 落库可对账 | `parity_telemetry.py:380` build_snapshot | ✅ PASS | DB 抽查 12 行均含 module=092/repeat/loop（commit 4673de65 / abb0727） |
| AC-4 LLM 遥测 | `parity_telemetry.py:94` Proxy + `:126` interceptor | ✅ PASS | 单测 21/21 |
| AC-5 工具遥测 | `parity_telemetry.py:310` aggregate_tool_rows + `parity_io.py:243` read_tool_rows | ✅ PASS | |
| AC-6 编排开销 | `parity_telemetry.py:143` segment_summary | ✅ PASS | 残差定义 |
| AC-7 三段闭合 | `parity_telemetry.py:169` closure_ok | ✅ PASS | ΣLLM+Σ工具溢出判失败 |
| AC-8 编译冷启动 | `parity_telemetry.py:355` measure_import_coldstart | ✅ PASS | 单测实测正数 + 差值口径 |
| AC-9 cold/warm | `parity_telemetry.py:332` collect_cold_warm | ✅ PASS | |
| AC-10 公平性声明 | changelog §8 / report | ✅ PASS | 声明写入报告（Tester 核对报告文本） |
| AC-11 判定确定性 | 全流程计时/库表/拦截器，无 LLM 评判 | ✅ PASS | |
| AC-12 失败不掩盖 | `parity_telemetry.py:457` print_report 失败清单 | ✅ PASS | 如实列出 fail_reason |
| AC-13 生产代码零改动 | `git diff -- agent src main.py` 空 | ✅ PASS | 实测全空（config.py 偏离见 §5/问题#6） |
| AC-14 代码量 ≤200 | parity_telemetry 193 / parity_io 118 | ✅ PASS | `ast` 独立复算 193 / 118（但 method>50 见 #1/#2） |
| AC-15 方法 ≤50 行 | `parity_telemetry.py:465` / `:402` | ⚠️ 中 | `main` 67 行、`print_report` 61 行超长（问题 #1/#2） |
| AC-16 单测 telemetry | `test_parity_telemetry.py` 21 项 | ✅ PASS | 独立复跑 21/21 全绿 |
| AC-17 全量回归 | `pytest tests/ -q` | ✅ PASS | junitxml：1825 passed / 0 failed / 3 skipped（「1800」为旧基线） |
| AC-18 报告可复现 | changelog §8 含命令/commit/参数 | ✅ PASS | Tester 核对报告文本 |
| AC-19 结论复核 | changelog §8.2/§8.3 | ✅ PASS | 提请 ADR-0020 复核，不擅自改判 |
| AC-20 StateGraph 归因 | changelog §8.1 编排开销差 +305.8ms | ✅ PASS | |
| AC-21 LLM IO 留痕 | `parity_io.py:102` LlmIoTracer + 第二批 trace | ⚠️ 中 | 第二批 trace 字段齐全；**首批 trace（id=12~17）缺 `tool`**（问题 #4） |
| AC-22 工具 IO | `tool_call_logs.args` + `result_preview` | ✅ PASS | 既有能力复用，不重复记录 |
| AC-23 分阶段 token | `parity_io.py:80` _usage_delta + `:175` stage_tokens | ✅ PASS（函数） | 函数单测 25/25 全绿；T8 复算受 `round` 恒=1 影响（问题 #3） |
| AC-24 留痕 fail-open | `parity_io.py:222` write_io_trace + `:243` read_tool_rows | ✅ PASS | 异常均 `logger.warning` 后返回 0/[]，不中断跑批 |
| AC-25 parity_io AST≤200 | `parity_io.py` 118 | ✅ PASS | `ast` 独立复算 118 |
| AC-26 parity_io 单测 | `test_parity_io.py` 25 项 | ✅ PASS | 独立复跑 25/25 全绿 |
| AC-27 批次波动 | changelog §11 + DB 实测 | ✅ PASS | DB 实测 P95 比值 0.6290 vs 0.9179（差 46%）逐值吻合 |
| AC-28 红线偏离申报 | plan §7.2 / AC-28 / changelog §7.2 | ✅ PASS | 三处显式申报；裁定见 §5/问题#6 |

T1–T9（Tester 对账项）静态可核部分已顺带核实：T1/T3/T9（DB 12 行 + P95 比值）✅；T7（JSONL 字段）⚠️ 首批缺 tool；T8（stage_tokens 复算）⚠️ 受 round 缺陷限制，第二批可复算但比值对、绝对值因轮合并不可分。

---

## 4. 架构评估

- **分层 / 依赖方向**：`eval/` 为评测脚本层，全部拦截在 eval 层以 `mock.patch` 包装生产客户端（`agent.react.LLMFactory.get_client` / `llm.client._record_usage` / 两环路 `execute_tool_with_log`），且 `_record_usage` 原行为先执行（`observability` 口径不变）。生产代码 `agent/` `src/` `main.py` **零 diff**，符合「只读生产代码」红线。零新增外部依赖。
- **DTO / 数据契约**：IO 留痕 JSONL 与 `tool_call_logs` 均为既有表/文件格式复用，无新表无 ALTER；`config_snapshot` 注入 `module/repeat/repeat_of/loop` 走既有 JSONB 列。
- **复用性**：`parity_telemetry.py` 复用 091 `langgraph_parity.py` 的 `run_side/score_run/_LLM_PATCH/_LOOP_FN/compute_scores`（零复制）；`_tool_rows` 迁入 `parity_io` 腾出 AST 空间，结构合理。
- **新增依赖**：无（仅评测层新增 2 文件）。
- **风险点**：`_TOOL_STACK` 为模块级全局列表，依赖串行 await 无并发（ReAct 循环串行）；当前正确，但若未来引入并发 LLM 调用需重新审视（已在 changelog 注明「串行 await 无并发」前提）。

---

## 5. 安全评估

逐项（通过 / 不通过）：

- **SQL 注入**：`parity_telemetry.py:200` 与 `parity_io.py:257` 的 `DELETE/SELECT ... WHERE trace_id = :t` 均用参数化绑定（`:t`），无字符串拼接 → **通过**。
- **XSS**：评测脚本不向 Web 输出用户可控 HTML；报告打印到 stdout，无 XSS 面 → **通过**。
- **密码 / API Key 泄露**：`config.py` opencode 字段为配置项，未在日志/留痕打印；JSONL 留痕仅含 messages/tools/content/tool_calls，不含 key → **通过**。
- **敏感日志**：IO 留痕含 LLM 输入输出（messages/tool_calls），属评测数据非密钥；`_trunc` 限单字段 20000 字符防过大；不落 API Key → **通过**。
- **fail-open 链路**：`write_io_trace` / `read_tool_rows` / 预清理 三处异常均 `logger.warning` 后 fail-open（返回 0/[]），**无吞异常不打日志** → **通过**（AC-24）。

**红线裁定（AC-28 / 最高关注）**：`src/config.py` 偏离性质裁定为**可接受**：
1. 偏离内容 = 纯增量 `opencode_api_key/model/base_url` 三字段 + `fallback_chain` 默认值由 `qwen,zhipu,deepseek` 改为 `qwen,zhipu,opencode,deepseek`。
2. `fallback_chain` 默认变更**确实改变「未配置 .env」的裸默认行为**（opencode 前插、deepseek 移至链尾），但项目 `.env` 当前即 `qwen,zhipu,opencode,deepseek`（project-context 2026-09-10），**运行期零差异**；opencode 三字段为可选配置、默认空、仅 `llm_provider=opencode` 或链含 opencode 时生效 → 纯增量。
3. 该偏离已在 plan §7.2 / AC-28 / changelog §7.2 **三处显式申报**，申报充分，**无需额外 ADR**（建议补一条备注说明归属，见问题 #6）。
4. `git diff --stat -- ai_service/agent ai_service/src ai_service/main.py` 实测**全空** → module-092 红线成立。

**最高优先项（AC-23 usage 差分归属）专项裁定**：**正确且健壮**。
- 核实 `llm/client.py`：`chat`/`chat_with_tools`/`generate` 三条路径均在返回前各调用 `_record_usage` 恰好一次（client.py:218/254/324/333/375/384/425/434/509/521），且 `_record_usage` 仅在 `usage` 非 None 时记账（client.py:101–103）。
- 差分机制（`parity_io.py:80` `_usage_delta`）以**每调用各自基准 `u0 = len(records)` 在调用前捕获**，调用后取 `records[u0:]`。因 records 只增不减、每次调用自取基准，**即使某次调用供应商未返回 usage（`_extract_usage` 返回 None、`_record_usage` 静默跳过）也不会把下一次 usage 误记到上一次**——任务提示的反例**不会发生**（稀疏记账由每调用基准吸收）。
- 工具内（`in_tool=True`）与环路级调用通过同一 `u0` 基准 + `stage_tokens` 按 `in_tool` 标志分桶，**不串桶**（嵌套工具 A 内调 B 时 `tool` 取 `_TOOL_STACK[-1]` 即最内层，合理）。
- 反例探查结论：当前单测 `test_usage_delta_sums_new_only` / `test_usage_attributed_to_each_call` 覆盖「无 usage」「每调用各属一份」；**未显式覆盖「前次调用无 usage、后次有 usage」的差分隔离场景**，建议补一条用例固化该保证（非阻塞，归 Developer）。

---

## 6. 五轴评分

| 轴 | 分数 | 依据 |
|----|------|------|
| 正确性 | 4/5 | 核心（usage 差分 / stage_tokens / 三段拆解 / 聚合）正确且单测覆盖；扣 1：`round` 字段恒=1（问题 #3）+ 首批 trace 缺字段（问题 #4）使持久化数据维度失真，但内存计算正确 |
| 完整性 | 4/5 | AC-1~28 全部覆盖、声明充分；扣 1：§十.2 分阶段 token 不可从 trace 逐值复算（受 #3 限）、首批 trace 不满足 AC-21 全字段 |
| 清晰性 | 4/5 | 文档/注释总体到位；扣 1：changelog 数字三处失准（#5）、`_usage_interceptor` 缺 docstring（#7） |
| 可维护性 | 3/5 | `main`(67)/`print_report`(61) 超 50 行（#1/#2）、魔法数字（#8）、langgraph patch 异味（#9） |
| 安全性 | 5/5 | SQL 参数化、无密钥泄露、fail-open 全链路有日志、无空 except |

**综合：3.8/5** —— 通过（附条件），无阻塞项。

---

## 7. ADR

- **本次是否产生 ADR**：否。
- 理由：① 无新外部依赖；② 架构决策（eval 层 mock 拦截、三段不相交分桶、差分归属）均在 plan 授权范围内，无超出 plan 的架构变更；③ `src/config.py` 偏离为纯增量 + 运行期 .env 覆盖，已在 plan §7.2 / AC-28 / changelog §7.2 三处申报，**无需新 ADR**（如团队要求可追溯，建议补一条备忘说明 opencode 字段来自 module-093、fallback_chain 默认值来自 [config] 提交，见问题 #6）。
- ADR-0020 复核：本模块仅呈报数据并提请复核（changelog §8.3），不自判结论，符合 AC-19。

---

> 附：独立复算/复跑证据摘要
> - AST：`parity_telemetry.py`=193（声称 193 ✅）、`parity_io.py`=118（声称 118 ✅）
> - 单测：`test_parity_telemetry.py` 21/21 ✅、`test_parity_io.py` 25/25 ✅（合计 46 passed）
> - 全量回归：junitxml tests=1828 / failures=0 / errors=0 / skipped=3 → **1825 passed, 0 failed, 3 skipped**
> - 红线：`git diff --stat -- ai_service/agent ai_service/src ai_service/main.py` 全空 ✅
> - DB 抽查：`agent_eval_runs` id=12~23 共 12 行，module=092 + repeat(0/1/2) + loop 两值齐全；P95 比值 run1 [0.6070,0.5636,0.7167] 均值 0.6291、run2 [0.7830,0.9420,1.0285] 均值 0.9178，与 changelog §8.4/§11 逐值吻合
> - JSONL：io-20260910-162434.jsonl 552 行（id=12~17，缺 tool/usage）、io-20260910-182411.jsonl 564 行（id=18~23，含 tool+usage，round 恒=1）
