# module-093 上下文工程：预算观测 + 历史压缩 + 对拍裁定

> Planner: 2026-09-11 | 上一模块：module-092 对比评测深化（v0.92.0 已封板）
> 类型：**产品功能模块**（与 091/092 的 eval-only 模块不同——本模块改 agent 行为，红线相应重定义）
> 背景缺陷：既有 4 项能力短板中「上下文工程」只做了三层记忆（Write 块），Compress 与预算治理空白（09-11 盘点）

## 0. 已探明事实（勿重复调查）

1. **模块号**：module-093 空闲（specs/ 最后占用为 092；原 093 号已被"供应商台账"方案释放）。
2. **react_loop 单点**：`agent/react.py:452` `react_loop(ctx, messages, budget, ...)`，messages 传入并**原地累积**（`:549` assistant / `:575` tool 消息追加）；`agent/langgraph_react.py` 有对应环路结构。两环路都必须接入同一套上下文管理函数，否则对拍不公平。
3. **无 token 估算函数**：项目代码无 tiktoken/估算器（tiktoken 仅作为 venv 传递依赖存在，项目未直接依赖）。需新建轻量启发式估算器（中英混合按 chars 系数折算，宁可高估）。
4. **既有熔断不冲突**：module-089 任务级 token 熔断（`tasks.budget_exceeded()`，chat_with_tools 之前，断工具循环不断答案）是**任务累计**维度；本模块的预算是**单次调用上下文构成**维度，两者正交。
5. **可恢复存储天然存在**：`execute_tool_with_log` 已把全部工具结果（含 args/result）落库 `tool_call_logs`——clearing 清掉的原始结果天然可回溯（Manus"可恢复压缩"原则的外置存储已就位）。
6. **观测先例**：`tracing.record_span("name", "decision", decision=...)` 机制已有（budget_break / budget_truncate / advance_phase）——预算观测走同一机制，零新表。
7. **配置模式**：`src/config.py` pydantic-settings，`PW_` 前缀环境变量（`tool_default_timeout` 先例）；tests/conftest.py autouse 钉开关为 false 的先例（083）——**本模块行为开关默认 false，保证存量回归零破坏**。
8. **eval 资产**：092 的 `parity_io`/`parity_telemetry`（usage 拦截/分桶/落库）在 eval 层，产品路径观测不復用它；但 WP-C 对拍**复用** parity 基建（落库、config_snapshot、score 计算）。

## 1. 设计决策（事前定死）

| # | 决策 | 理由 |
|---|------|------|
| D1 | **压缩用"视图"不原地改**：传给 `chat_with_tools` 的 messages 是压缩后的副本，`react_loop` 本地 messages 保持完整 | 原始上下文零丢失（可恢复）；对拍公平（三臂同源）；tool_call_id 引用链不被破坏 |
| D2 | **clearing 在前，compaction 在后** | Anthropic 定性 clearing 为"最安全的压缩"（零推理成本、机械替换、可重取）；compaction 有损，只做兜底 |
| D3 | **compaction 折叠必须整块**：assistant(含 tool_calls) + 其配对的全部 tool 消息作为一个原子单元折叠，摘要作为单条 user 角色消息置于历史开头 | OpenAI 格式要求 tool 消息紧跟配对 assistant——破坏配对 = 请求 400 |
| D4 | **两环路共用 `agent/ctx_manager.py` 同一函数集**（手写环路与 langgraph 环路各自在调 LLM 前调用） | 对拍公平性：三臂差异只来自 ctx_mode，不来自实现分叉 |
| D5 | **行为开关默认 false**（`ctx_compress_enabled: bool = False`），观测 span 默认开 | 观测无行为变化可默认开；行为改动默认关 → 存量测试逐字不变 → 全量回归零破坏 |
| D6 | **摘要 v1 规则式**（保留 system + 首条 user 原文 + 最近 K 条完整 + 中间轮压缩为要点行），不引入 LLM 摘要 | LLM 摘要引入额外推理成本与不确定性，且不可单测锁定；规则式的保真局限如实写入报告 |

## 2. 工作包

### WP-A 上下文预算观测（默认开，零行为变化）

新建 `ai_service/agent/ctx_manager.py`：

1. `estimate_tokens(text: str) -> int`——启发式估算（ASCII 4 chars/token、CJK ~1.5 chars/token，按字符类别分段累计；向上取整）。不做精确分词，写明误差边界。
2. `classify_context(messages: list, tool_schemas: list) -> dict`——五桶：`system / tools / user / assistant / tool_results`，各桶返回 `{count, est_tokens}`。分桶规则：role 字段判 user/assistant/system/tool；tools 桶 = tool_schemas 的 JSON 序列化估算。
3. `observe_context(messages, tool_schemas, where) -> dict`——汇总 + `tracing.record_span("ctx_budget", "observe", decision=...)` 一条（摘要 json）。在 `react_loop` 每轮 `chat_with_tools` 之前调用。

### WP-B 历史压缩（默认关）

`ctx_manager.py` 继续：

4. `clear_tool_results(messages, keep_recent: int) -> tuple[list, int]`——保留最近 keep_recent 条 tool 消息原文，更早的 content 替换为 `[tool result cleared: {name}; re-invoke the tool to retrieve]`（**只换 content 不动结构**，assistant/tool 配对保持）。返回（新列表，清除条数）。**消息顺序与 tool_call_id 一律不变**。
5. `compact_history(messages, keep_recent: int) -> tuple[list, int]`——若 clearing 后估算仍超阈值：定位最早的完整轮次块（user → assistant(±tool_calls) → 配对 tools），折叠为一条摘要 user 消息（`[context summary: 用户先问了X， assistant 回答了Y要点...]`，要点行从被折叠的 user/assistant 文本抽取），保留 system 全部 + 首条 user 原文 + 最近 keep_recent 条。返回（新列表，折叠块数）。**块完整性由单测锁定（AC-10）**。
6. `compress_view(messages, tool_schemas, cfg) -> tuple[list, dict]`——编排入口：估算 → 超阈值则先 clear 再 compact → 返回（视图, 元信息{cleared, compacted, before_tokens, after_tokens}）。未启用或未超限 → 返回（原 list 引用, 零动作元信息）。

**接入点**（两环路各 ≤ 20 行 diff）：
- `react_loop`：每轮循环 `chat_with_tools` 之前 `messages_view, ctx_meta = compress_view(...)`，发送 `messages_view`；span `ctx_compress`（超限触发时）。
- `langgraph_react_loop`：对应位置同款调用。

**配置**（`src/config.py` 纯增量）：
```python
ctx_compress_enabled: bool = False      # PW_CTX_COMPRESS_ENABLED
ctx_token_threshold: int = 24000        # PW_CTX_TOKEN_THRESHOLD（history 桶触发线）
ctx_keep_recent: int = 6                # PW_CTX_KEEP_RECENT（clearing/compaction 保留条数）
```

### WP-C 对拍实验（三臂裁定）

7. 长对话任务集：`ai_service/eval/ctx_tasks.py`——3 个固定剧本 × 18 轮连续追问（基于 at-1xx 多轮风格扩展：G1 深挖 / 线程池深挖 / RAG 深挖），每轮带 `answer_points`（复用 066 判定器口径）。剧本固定入 git（可复现）。
8. `eval/ctx_parity.py`：三臂 `off / clearing / clearing+compaction`（同一剧本逐臂执行，臂内剧本顺序固定），复用 066/092 基建落库 `agent_eval_runs`，`config_snapshot.module='093'` + `ctx_mode` 字段区分。供应商固定单一家（跑批时 shell 指定，不写死）。
9. **判据事前定死**（写入 ADR，结果不利也照实写）：
   - ①质量：压缩臂 pass^1 ≥ off 臂 − 0.10（允许小幅损失）
   - ②收益：压缩臂 history 桶 est_tokens 总量 < off 臂 × 0.70
   - ③成本：压缩臂 LLM 次数 ≤ off 臂 × 1.15（压缩不得引发更多重试）
   - 任一不满足 → 该臂裁定"不引入"；②满足且①③满足 → 建议默认开启并开 ADR
10. 产出 `specs/module-093-context-engineering/{ctx-report,changelog}.md` + `specs/adr/0022-context-compression.md`（含三条判据逐值 + 若不满足的诚实归因）。

## 3. 实现顺序

1. 单测先行：`tests/agent/test_ctx_manager.py`（估算器边界/五桶/占位符/块完整性/默认关零行为/视图不改原列表）
2. WP-A → 冒烟（观测 span 出现，行为零变化）
3. WP-B → 冒烟（开开关，构造超长对话验证触发与格式合法性）
4. WP-C → 先 1 剧本 × 3 臂冒烟，再全量对拍（3 剧本 × 3 臂，估 tokens ~30 万、40 分钟量级）
5. 定向单测 + 全量回归 + 报告 + ADR

## 4. 风险与对策

| 风险 | 对策 |
|------|------|
| 压缩视图破坏 OpenAI 消息格式（tool 配对断裂） | D3 原子折叠 + 单测锁格式合法性（AC-10/11） |
| 估算器误差导致触发线漂移 | 宁可高估；阈值可配置；报告标注误差方向 |
| langgraph 环路 state 结构不同导致接入分叉 | D4 共享纯函数；两环路接入各自 ≤20 行 |
| 默认关也可能被 conftest/其他配置顶开 | AC-13 显式断言 off 时 messages 逐字不变 |
| 供应商波动污染对拍 | 单供应商三臂同批；沿用 092 教训（批次波动如实报 std） |

## 5. 验收与红线

- **红线（本模块重定义）**：`ai_service/rag/` 零 diff（检索主链路持续零改动约定）；`ai_service/eval/langgraph_parity.py`、`parity_telemetry.py`、`parity_io.py`、`parity_events.py` **零 diff**（092 已封板资产不动）。允许动：`agent/react.py`、`agent/langgraph_react.py`（各 ≤20 行接入）、新建 `agent/ctx_manager.py` + `eval/ctx_tasks.py` + `eval/ctx_parity.py`、`src/config.py`（纯增量三字段，申报）。
- 新增 AST ≤ 200（`ctx_manager.py`）；`ctx_tasks.py`/`ctx_parity.py` 为数据与脚本，计入总量但可放宽至 ≤ 350（两文件合计，plan 预先申请）。
- 方法 ≤ 50 行；public 函数 docstring（Args/Returns）；无空 except。
- 全量回归基线 **1849 / 0 / 0 / 3** 零新增失败（junitxml 口径，EXIT code 不可信——safe-delete 干扰）。
