# 验收标准 — Module-092: 对比评测深化（多轮采样 + 分阶段遥测 + 冷启动）

> Planner: 2026-09-07 | 配套 plan.md | 红线：`agent/` `src/` `main.py` 零 diff；基线 1769/0/3 零新增失败
>
> **2026-09-10 追加**（用户追加需求：「各个阶段的输入输出也需要」「每个阶段的 token 消耗有没有」）：
> AC-21 ~ AC-26 + T7 ~ T9 为本次追加项。**红线偏离如实申报**——`src/config.py` 为接入
> OpenCode Go provider 新增 3 字段（`opencode_api_key/model/base_url`）并把 `fallback_chain`
> 默认值追加 `opencode`（纯增量；运行期由 `.env` 显式覆盖，见 §7 偏离记录）；
> `agent/`、`main.py` 仍零 diff。

## 1. 功能验收

| # | 验收项 | 判据（可机械断言） |
|---|--------|--------------------|
| AC-1 | 多轮采样 | `--repeat 3` 产出 3 轮 × 2 环路完整运行，轮间抽样集合相同（同一任务 id 集）、任务顺序重洗 |
| AC-2 | 聚合统计 | 每指标（pass^1/工具正确率/tokens/P50/P95）输出 mean±std/min/max + 逐轮明细 |
| AC-3 | 落库可对账 | 6 条 run 入 agent_eval_runs，config_snapshot 含 repeat/repeat_of；`git_commit` 逐条记录 |
| AC-4 | LLM 阶段遥测 | 每环路：调用次数、总/mean/P50 耗时、tokens 合计（prompt/completion 拆分）——来自 client proxy + `_record_usage` 拦截 |
| AC-5 | 工具阶段遥测 | 每环路按 tool_name 分组：次数、总/mean/P50 duration_ms、失败数（tool_call_logs 直查） |
| AC-6 | 编排开销归因 | 编排开销 = 总时长 − ΣLLM − Σ工具，两环路各自成值且差值有明确数字（StateGraph 归因） |
| AC-7 | 三段闭合 | 每次运行三段之和 vs 总 duration_ms 误差 <2%；超限逐条列出并解释 |
| AC-8 | 编译冷启动 | 独立子进程计时 `import agent.react` vs `import agent.langgraph_react`（后者含 build_react_graph），差值毫秒级成表 |
| AC-9 | cold/warm 对比 | 每轮首条任务记 cold、其余 warm；cold 与 warm 中位比值 × 2 环路成表 |
| AC-10 | 公平性声明 | 报告写明：本地模型加载为两环路共同成本不计入差异；LLM 首次握手同为一次 |
| AC-11 | 判定确定性 | 全流程无 LLM 评判；数据全部来自计时/库表/拦截器 |
| AC-12 | 失败不掩盖 | 任一次运行异常记 fail_reason 列出；不重跑挑数据；多轮 std 如实报 |
| AC-21 | LLM 阶段输入输出留痕 | 每次 LLM 调用落一条 JSONL 记录，含 `messages`（完整对话历史）/ `tools`（工具 schema）/ `content` / `tool_calls` / `duration_ms` / `in_tool` / `tool`；异常路径记 `output.error` 后仍留痕 |
| AC-22 | 工具阶段输入输出 | 由既有 `tool_call_logs` 提供（`args` jsonb 输入 + `result_preview` 输出），不重复记录（口径说明入报告） |
| AC-23 | 分阶段 token | 每次调用 token 按「调用前后 usage 列表长度差分」精确归属（`_usage_delta`）；`stage_tokens()` 可输出 环路级 / 工具内 + 按工具名 的 prompt / completion / calls 三项 |

## 2. 非功能验收

| # | 验收项 | 判据 |
|---|--------|------|
| AC-13 | 生产代码零改动 | `git diff --stat` 对 agent/src/main.py 全空 |
| AC-14 | 代码量 | 本模块新增 AST ≤ 200（实测复算）；顺带修 091 遗留 3 函数 docstring（Args/Returns） |
| AC-15 | 方法/类规模 | 方法 ≤50 行 |
| AC-16 | 单测 | `tests/eval/test_parity_telemetry.py`：拦截器捕获、三段闭合计算、聚合统计、cold/warm 判定，全绿 |
| AC-17 | 全量回归 | 1769/0/3 零新增失败 |
| AC-18 | 报告可复现 | 报告含运行命令、commit、repeat/sample 参数、总成本（tokens 与墙钟） |
| AC-24 | 留痕 fail-open | 写盘失败不中断跑批（仅 warning）；`read_tool_rows` DB 异常返回 `[]`——两条路径均有单测 |
| AC-25 | 新增文件代码量 | `eval/parity_io.py` AST ≤200；`parity_telemetry.py` 迁出 `_tool_rows` 后仍 ≤200（实测 193） |
| AC-26 | 新增单测 | `tests/eval/test_parity_io.py` 覆盖：超长截断 / 三方法入参序列化 / 出参 str 与 dict 两形态 / 行为透传 / seq 递增 / 工具名与 `in_tool` 归因 / 异常路径记录后抛出 / usage 差分归属 / `stage_tokens` 分阶段聚合 / 写盘失败 fail-open / 读回 fail-open，全绿 |

## 3. 结论验收

| # | 验收项 | 判据 |
|---|--------|------|
| AC-19 | 结论复核 | 明确回答：多轮数据下 ADR-0020"维持自研"是否仍成立（P95 多轮均值 vs 1.20 阈值）；若翻转，**如实提请复核**，不擅自改判也不回避 |
| AC-20 | StateGraph 归因 | 给出编排开销差值的数字与解释（节点调度/状态拷贝/路由），无法归因的部分如实标"未定位" |
| AC-27 | 跑批数据与批次波动 | 跑批须真实落库（config_snapshot 含 module/repeat/loop）且失败如实列出；**同配置多次跑批的差异须如实记录**（本次实测两次：P95 比值 0.6290 vs 0.9179），并据此写明"结论强度所需的采样层级" |
| AC-28 | 红线偏离申报 | `src/config.py` 的 provider 接入改动须在 changelog 与 AC 中显式申报性质（纯增量 + 运行期由 .env 覆盖），不得隐去。**来源提交**：`ce6646b`（module-093 OpenCode Zen provider 接入，opencode 三字段）+ `8ac4c4a`（[config] 降级链调整，`fallback_chain` 默认值）；module-092 跑批依赖之，列为可接受偏离；运行期 `.env` 已含同款链（`qwen,zhipu,opencode,deepseek`），零运行时差异，无需 ADR |

## 4. Tester 对账（T1-T6）

| # | 对账项 | 方法 |
|---|--------|------|
| T1 | 6 条 run 落库 | SQL 查 config_snapshot->>'repeat' 0/1/2 × loop 两值，逐条 commit 一致 |
| T2 | 逐轮数字对账 | 任抽 1 轮：报告逐轮明细 vs 库内 per_question 复算一致 |
| T3 | 三段闭合抽验 | 任抽 3 次运行独立复算三段之和 vs 总时长 |
| T4 | 冷启动复现 | 独立跑子进程 import 计时，数字与报告同量级（±30% 内，进程噪声如实标注） |
| T5 | 红线零 diff + 单测全绿 + 全量 1769/0/3 | 独立复跑 |
| T6 | 清理还原 | 评测 trace 精确清理（**时间窗口径**，091 勘误先例），行数还原如实记录；无临时文件残留 |
| T7 | IO 留痕完整性 | 独立读 `eval_io_traces/*.jsonl`：条数 = Σ每次运行的 LLM 调用次数；字段齐全（input.messages/tools、output.content/tool_calls、in_tool、tool、duration_ms）；`in_tool` 分布与工具调用次数量级相符 |
| T8 | 分阶段 token 复算 | 独立用 `stage_tokens()` 从留痕复算 环路级/工具内 + 按工具名，与 changelog §十 表格逐值比对 |
| T9 | 两次跑批对照 | 查 id=12~17 与 id=18~23 的 `scores->>'pass_1'` 与 P95，核对 changelog §十一 差异数字（0.6290 vs 0.9179）属实 |

## 5. 可运行命令表

```bash
cd interview-personal/ai_service
# 冒烟（快，先跑）
PW_LLM_PROVIDER=opencode .venv/Scripts/python.exe -u -X utf8 \
  -m eval.parity_telemetry --mode real --sample 2 --repeat 1 --no-save
# 正式（3 轮 × 12 任务 × 2 环路）
# 注：原表误写为 eval.langgraph_parity（091 的脚本）；092 入口是 eval.parity_telemetry
PW_LLM_PROVIDER=opencode .venv/Scripts/python.exe -u -X utf8 \
  -m eval.parity_telemetry --mode real --sample 12 --repeat 3
# 单测 + 全量
.venv/Scripts/python.exe -m pytest tests/eval/test_parity_telemetry.py tests/eval/test_parity_io.py -q
.venv/Scripts/python.exe -m pytest tests/ -q
```

**环境说明（2026-09-10 实测，供 Tester 复跑参照）**：跑批期间 `PW_LLM_PROVIDER` 由 shell
环境变量显式指定为 `opencode`（即 OpenCode Go 端点 `https://opencode.ai/zen/go/v1` +
`glm-5.3-flash`），**不改 `.env`**（091 验收先例）。`.env` 当前为 `fallback` 链
`qwen,zhipu,opencode,deepseek`。

## 6. 验收结论签署区

| 角色 | 结论 | 日期 | 备注 |
|------|------|------|------|
| Developer | ✅ | 2026-09-11 | changelog.md（含 §十二~§十四 记录维度增强 + Reviewer 补审） |
| Reviewer（主体） | ✅ | 2026-09-10 | review-report.md（PASS 附条件，0 阻塞/2 中/5 低） |
| Reviewer（记录维度增强） | ✅ | 2026-09-11 | review-report-events.md（PASS 0 阻塞/0 高/3 低） |
| Tester | ✅ 验收通过（附条件） | 2026-09-11 | tester-092-final：T1-T9 全过（30行/12-12一致/3-3闭合/±30%/T7批3·4全字段/T8 stage_tokens一致/T9 4批均值0.6290·0.9179·1.0362·0.9696=0.8882、2-12超阈）、AC 27/28+1附条件、全量 1849/0/0/3、AST 198/118/43、红线全空、记录维度增强 answer_points_hit/failed_points/telemetry.events 真实落库验证（id24/30）、冒烟管道端到端+新trace全字段；2项非阻塞（AC-15 main/print_report超50行、parity_telemetry余量仅2行文档误报） |
