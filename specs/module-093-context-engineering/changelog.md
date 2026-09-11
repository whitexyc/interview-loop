# module-093 上下文工程 — Changelog

> Developer: developer-093 | 2026-09-11 | 关联 plan.md / acceptance-criteria.md / ADR-0022
> 红线守约：rag/ 与 092 封板资产（eval/langgraph_parity.py、parity_telemetry.py、
> parity_io.py、parity_events.py）零 diff；main.py 零 diff。

## 新增文件

| 文件 | 用途 | AST |
|------|------|-----|
| `agent/ctx_manager.py` | WP-A 预算观测（estimate_tokens/classify_context/observe_context）+ WP-B 历史压缩（clear_tool_results/compact_history/compress_view）；视图模式，零侵入 | 23（≤200）|
| `eval/ctx_tasks.py` | WP-C 对拍任务集：3 固定剧本 × 18 轮连续追问，每轮 answer_points，复用 066 判定器口径 | 6 |
| `eval/ctx_parity.py` | WP-C 三臂裁决：off/clearing/clearing_compaction 逐臂跑同一剧本，复用 066 outcome_pass + save_agent_eval_run 落库，三判据逐值裁定 | 34 |
| `tests/agent/test_ctx_manager.py` | WP-A/B 单测：估算边界/五桶/占位符/块完整性/默认关零行为/视图不改原列表（19 项） | — |
| `tests/agent/test_ctx_compress_wiring.py` | 两环路接入集成测试：compress_view 为副本、本地 messages 完整、ctx_compress span 触发（2 项） | — |

> ctx_tasks.py + ctx_parity.py 合计 AST = 40（≤350，plan §5 预申请）。

## 改动文件（均 ≤20 行接入 / 纯增量）

| 文件 | 改动 |
|------|------|
| `agent/react.py` | react_loop 每轮 chat_with_tools 前：`view, ctx_meta = compress_view(messages, schemas)` 发视图 + `observe_context` 观测 + 触发记 `ctx_compress` span（≤20 行）|
| `agent/langgraph_react.py` | langgraph_llm_call 对应位置同款调用（≤20 行，D4 无分叉）|
| `src/config.py` | 纯增量三字段：`ctx_compress_enabled=False` / `ctx_token_threshold=24000` / `ctx_keep_recent=6`（AC-17）|

## 配置（PW_ 前缀，可环境变量覆盖）

```ini
PW_CTX_COMPRESS_ENABLED=false     # 历史压缩总开关（默认关，零行为变化）
PW_CTX_TOKEN_THRESHOLD=24000      # history 桶触发线（est_tokens）
PW_CTX_KEEP_RECENT=6              # clearing/compaction 保留最近条数
```

## 验收摘要

- 全量回归（junitxml 权威）：tests=1870 / failures=0 / errors=0 / skipped=3
  （基线 1849/0/0/3，零新增失败，T5 满足）。
- 单测：test_ctx_manager.py(19) + test_ctx_compress_wiring.py(2) = 21 全绿。
- 红线：git diff rag/ 与 092 四文件均零 diff（待 T5 复核）。
- 三判据：跑批前写入 ADR-0022 §4（AC-21）。真实裁定（id=39/40/41，fixture=False，
  commit 4fcfd54d，42.3 min）：clearing 臂 ② FAIL（tokens +31.6%）→ **不引入**；
  clearing+compaction 三判据全过但质量裕度仅 0.012 → **建议引入-灰度默认关**（非无保留
  默认开）。详见 ctx-report.md §7/§8 与 ADR-0022 §5.1。

## 已知局限（诚实记录，AC-22）

- `estimate_tokens` 启发式（**CJK 0.8** / 其他 4 chars per token，偏离 plan WP-A 的
  1.5 系数 → 1.5 对中文低估触发线偏晚不安全，0.8 让 5/5 抽样高估，满足 AC-2 宁可高估；
  已申报），误差方向安全侧；真实 tiktoken 抽样对比见 ctx-report §3（AC-2）。
- 规则式摘要 v1 对"短轮次密集"对话可能引入摘要开销，仅对"长答案轮次"有效降本
  （D6），质量损失由判据 ① 兜底。
- clearing-only 臂经 `compress_view(compact=False)` 表达，未新增配置项（红线三字段）。
