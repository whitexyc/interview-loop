# 运维记录 — 2026-09-11（非模块：工程小项打包）

> 按约定"小工程项不立 module"（供应商接入同款精神）：本页记录三项工程小改的
> 设计说明与自证，全部轻量模式（规划/实现/验证由编排者完成，改动小且机械）。

## 1. ctx_parity 接入 092 记录维度增强（093 验收 minor 遗留）

- **背景**：module-093 验收发现 `eval/ctx_parity.py` 只复用 066 判定口径
  （`outcome_pass`），未继承 092 的记录维度增强（逐要点命中 / 异常事件）。
- **改动**：`run_one_script` 接入 `eval/parity_events`——每轮
  `capture_tool_events`（旁路捕获工具超时/重试/失败）→ per_round 新增
  `answer_points_hit` / `failed_points` / `telemetry.events` 三字段，口径与
  092 完全一致（`answer_point_hits` 与 `outcome_pass` 同为子串包含）。
- **效果**：此后 ctx 对拍可回答"这轮为什么没过"（失分点直出）与"这天稳不稳"
  （事件计数）。零生产 diff（仅 eval 层）。

## 2. 工具超时分档（092 遥测数据落地）

- **依据**：092 工具级实测——`generate_answer`/`verify_answer`（内部含完整
  LLM 生成）在统一 15s 档**恒贴上限**（qwen 下 p50=15012ms，每轮白等 15s 后
  走兜底路径）；`re_search` 频繁撞线；只读检索类 p50 8.7~10s 未撞线。
  module-083 当时就写了"测量调优不在本模块"——本项补上这个测量调优。
- **改动**：`agent/tool_registry.py` 增 `_TOOL_TIMEOUT_TIERS =
  {generate_answer: 40, verify_answer: 40, re_search: 30}`，`register()` 在
  `settings.tool_timeout_tiering=True` 且未显式传 timeout 时应用分档；
  `src/config.py` 纯增量 `tool_timeout_tiering: bool = False`。
- **开关默认 False 零行为变化**；显式传 timeout 的调用方优先级最高。
  开启后用户可感知收益：生成类工具不再每轮白等 15s 超时、答案走正常路径
  而非兜底。是否默认开启留给用户决策（涉及生产延迟预算）。

## 3. README 数字与实验说明更新

- 测试数 1225 → **1870**；ADR 数 18 → **23**；模块数 70+ → **90+**。
- 工程实践段新增「三次数据化架构裁定」条目（091/092/093 概括 + 实验端点
  保留可复现说明 + ADR-0020~0023 指引）——回应 091 遗留的
  "README 补实验端点说明"。

## 自证

- 新增单测 `tests/agent/test_tool_timeout_tiering.py` 5 项（默认关/开启分档/
  未命中默认/显式优先/取值表），定向全绿。
- 全量回归 junitxml 权威口径（EXIT code 不可信）。
- 红线：`rag/`、`main.py`、092 封板四文件零 diff。
