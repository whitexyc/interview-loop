# 审查报告 — Module-092: 记录维度增强（parity_events）

> 审查对象：`ai_service/eval/parity_events.py`（新增，42→实测 43 AST）+ 接入点
> `ai_service/eval/parity_telemetry.py:228-240` + 单测 `tests/eval/test_parity_events.py`（21 项）
> 审查人：reviewer-events-2 ｜ 日期：2026-09-11 ｜ 模式：轻量实现后的独立审查（首派因 429 限流失败，本次重派）

---

## 1. 审查结论

**结论：PASS（0 阻塞 / 0 高 / 3 低）** —— 代码质量达标，可作为「记录维度增强」落库依据；
但发现 **1 处文档性红线余量误报**（parity_telemetry 实测 198/200，余量仅 2 行，非文档所写 5 行），
须在后续任何对 parity_telemetry.py 的改动前先腾空间，故记为附条件通过。

独立验证全绿：单测 67/67、全量回归 **1849/0/0/3**（junitxml 权威计数）、红线 `agent/`+`main.py` 零 diff、
口径一致性独立复现 **225 例 0 不一致**、JSONL 批次 3/4 新字段齐全。

---

## 2. 问题列表

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|---------|---------|
| 1 | specs/.../changelog.md §二/§已知偏差/§修复轮总结；memory/file-index.md:286；memory/agent-activity-log.md（092 多行） | — | parity_telemetry.py 实际 AST=**198**，但 changelog（§二 193、§已知偏差「当前 195」、§修复轮总结「195」）与 memory 多处记 193/195，**红线余量被误报为 5 行，真实仅 2 行** | 低（文档，但影响余量风险评估） | 更正全部 193/195→198；在「已知偏差」明确「余量 2 行，后续任何 +3 AST 改动都会顶破 ≤200，须先拆分 main/print_report（已知偏差已声明暂缓）」 |
| 2 | eval/parity_events.py | — | 实际 AST=**43**，声明为 42（1 行出入） | 低（文档） | 更正声明为 43；不影响红线（43≪200） |
| 3 | eval/parity_events.py:121-141（summarize_events） | 134 | `total` 计入挂在共享 logger `agent.tool_registry` 上的**全部** WARNING（含非执行类告警：schema 校验失败 `tool_registry.py:89`、审批查询失败 `tool_registry.py:112`），这些不含关键词不入桶，但会**膨胀 total** | 低（正确性观察） | 要么在 `_EventSink.emit` 捕获时按 `_EVENT_PATTERNS` 关键词预筛，要么文档注明「total 含非执行告警」。单测 `test_unknown_message_falls_to_no_bucket` 已覆盖该行为 |
| 4 | eval/parity_events.py:99-118（capture_tool_events） | 113 | 旁路捕获依赖全局 logger `agent.tool_registry` 有效级别 ≤ WARNING；若任一导入将其级别调高，`logger.warning` 不生成记录、`emit` 不被调用，捕获**静默失效且无报错** | 低（side-channel 固有局限） | 受「零生产改动」约束可接受；建议在 parity_telemetry 调用处日志注明此依赖，或给 sink handler 设 `setLevel` 同时确认 logger 不过滤 |

> 阻塞/高：无。以上均为低级别（文档准确性 / 观察性），不阻断本审查结论。

---

## 3. 验收标准核对（对应任务 6 项重点核查）

| 验收项 | 对应代码 文件:行号 | 状态 | 备注 |
|--------|-------------------|------|------|
| ① 事件分类完备正确，覆盖 `_execute` 全部日志文案 | tool_registry.py:250/255/259/262/264 ↔ parity_events.py:31-35 | ✅ | 五条文案逐一比对，映射与多类重叠均与代码注释一致 |
| ① 不用裸「失败」泛匹配，避免首次失败误算最终失败 | parity_events.py:34（"执行失败"/"重试仍失败"） | ✅ | 实测「首次失败，自动重试」→ retry=1/fail=0（见 §四验证 2） |
| ① 单测锁定该坑 | test_parity_events.py:155-164 | ✅ | `test_initial_failure_not_counted_as_final_fail` 断言 retry=1/fail=0 |
| ① 一条日志计入多类合理 | parity_events.py:23-30, 124-125 | ✅ | "重试超时"→retry+timeout 设计合理（触发重试路径 vs 最终超时诊断含义不同），单测 `test_retry_timeout_counts_both` 锁定 |
| ② 答案要点判定与 outcome_pass 逐字一致 | parity_events.py:51-52 ↔ agent_tasks.py:197 | ✅ | 独立复现 225 例 0 不一致（含正则特殊字符/Unicode/points=[]/answer=None） |
| ③ capture 正常+异常两条路径均摘 handler | parity_events.py:99-118（try/finally） | ✅ | 单测 `test_handler_removed_after_exit` + `test_handler_removed_on_exception` 双路径锁定；72 次跑批无泄漏 |
| ③ `_EventSink.emit` 满足铁律 5 | parity_events.py:89-96 | ✅ | 初版 `pass`（静默）已改为 `logger.warning` 留痕，对齐 parity_io.py:244 先例；单测 `test_emit_failure_is_logged_not_silent` 锁定 |
| ③ asyncio 串行重入无问题 | parity_telemetry.py:228（每 run 进/出一次） | ✅ | 串行 await，单次仅一个 handler 在全局 logger 上，无并发/重入冲突（详见 §5） |
| ④ AST 复算三文件 | parity_events.py / parity_io.py / parity_telemetry.py | ⚠️ | 实测 43/118/198；前两者与声明一致，**parity_telemetry 198≠文档 195**（见问题 #1） |
| ④ 红线 agent/+main.py 零 diff | git diff --stat -- ai_service/agent ai_service/main.py | ✅ | 输出为空，确认零生产改动 |
| ⑤ 单测真实断言/独立 logger/无网络DB | test_parity_events.py | ✅ | 21 项均断言行为；日志用例用 `monkeypatch` 隔离 logger 名（:77-83）；无真实 LLM/DB |
| ⑥ JSONL 新字段真实写入且合理 | parity_io.py:133-147 + eval_io_traces/ | ✅ | 批次 3/4：repeat∈{0,1,2}、in_tool=True 时 tool 全非空（216/203 条）、usage 全记录且非空（见 §四验证 4） |

---

## 4. 独立验证（命令与输出）

### 验证 1 — AST 复算（与任务声明 198/118/42 比对）
```
$ for f in eval/parity_telemetry.py eval/parity_io.py eval/parity_events.py; do \
    .venv/Scripts/python.exe -c "import ast;t=ast.parse(open('$f',encoding='utf-8').read());print(sum(1 for n in ast.walk(t) if isinstance(n,ast.stmt)))"; done
eval/parity_telemetry.py: 198
eval/parity_io.py:        118
eval/parity_events.py:     43      # 任务声明 42 → 实测 43（见问题 #2）
```
> 方法：changelog §二 定义口径 `ast.walk` 全文 `ast.stmt` 计数。parity_telemetry 198 与任务一致、但与 changelog/memory 多处所写 195 冲突（问题 #1）。

### 验证 2 — 事件分类覆盖面 + 裸失败不误判（直接读 `_execute` 五条文案逐条跑）
```
'工具 X 超时 (15.0s)'               -> ['timeout']
'工具 X 首次失败，自动重试: e'       -> ['retry']
'工具 X 重试超时 (15.0s)'           -> ['timeout', 'retry']
'工具 X 重试仍失败，返回空: e'       -> ['retry', 'fail']
'工具 X 执行失败，返回空: e'         -> ['fail']
'首次失败' retry/fail = 1 0  (期望 1/0，未误判为最终失败)
```
→ 五条生产日志文案 **100% 被 `_EVENT_PATTERNS` 覆盖**，且「首次失败」未被算入 fail 桶。

### 验证 3 — 口径一致性独立复现（自写脚本，不复用编排者）
```
任务集条数: 36
总用例: 225   不一致数: 0
结论: PASS — 口径完全一致
```
覆盖：每任务 answer_points × 6 种答案形态（全命中/部分/全漏/None/空串/Unicode 乱序）
+ 边界（要点含 `(G1)` `.*` `[` `$1` `^x` / 答案含 emoji😀 中文 / points=[] / answer=None）。
判定内核 `all(p in (answer or ""))`（agent_tasks.py:197）与 `answer_point_hits` 的 `str(p) in text` 等价
（answer_points 经 load 校验均为 str，`str(p)==p`）。

### 验证 4 — JSONL 新字段抽查（批次 3/4）
```
FILE eval_io_traces/io-20260910-230610.jsonl: lines=532
  repeat values: [0, 1, 2]
  in_tool=True with non-empty tool: 216 / empty tool: 0
  records with usage field: 532  usage non-empty: 532
FILE eval_io_traces/io-20260910-233453.jsonl: lines=507
  repeat values: [0, 1, 2]
  in_tool=True with non-empty tool: 203 / empty tool: 0
  records with usage field: 507  usage non-empty: 507
```
→ `attempt`/`repeat`/`tool`/`usage` 全部真实写入；`repeat` 覆盖 1/2/3（0-based）；`in_tool=True` 时 `tool` 非空；`usage` 全量非空。修复轮 round→attempt+repeat 生效。

### 验证 5 — 单测复跑
```
tests/eval/test_parity_events.py    -> 21 passed (29.8s)
tests/eval/test_parity_io.py        -> 25 passed
tests/eval/test_parity_telemetry.py -> 21 passed (56.1s)
合计 67 passed（预期 21+25+21=67）✅
```

### 验证 6 — 全量回归（junitxml 权威计数；本环境 EXIT=1 但 junitxml 全绿，以 XML 为准）
```
$ pytest tests/ -q --junitxml=_r.xml   (tmp_path_retention_policy=all 规避 safe-delete 钩子拦截)
root=<testsuites> -> <testsuite tests=1849 failures=0 errors=0 skipped=3>
```
→ **tests=1849 / failures=0 / errors=0 / skipped=3**（与任务预期完全一致）✅。

### 验证 7 — 红线
```
$ git diff --stat -- ai_service/agent ai_service/main.py   (输出为空) ✅
```

---

## 5. 架构评估

- **分层/依赖方向**：纯评测层（`eval/`）新增，零生产 diff。接入点仅在 `parity_telemetry.py:228-240`
  以 `contextmanager` + 纯函数调用方式并入，不修改 `agent/`、`main.py`、LangGraph 环路源码。
- **旁路捕获设计**：`_EventSink` 挂全局 logger `agent.tool_registry`（与 `tool_registry.py:37` 同名 logger 一致），
  handler 级别 WARNING 精确贴合 `_execute` 的 `logger.warning` 调用。try/finally 保证进/出对称摘挂。
- **asyncio 串行重入**：跑批为串行 `await`，`capture_tool_events` 在每个 `run_telemetry_side` 内成对进入/退出，
  任意时刻全局 logger 上至多一个本模块 handler；无并发写 sink、无栈帧依赖（区别于 parity_telemetry 的 `_TOOL_STACK` 栈判定），
  重入安全。唯一局限见问题 #4（依赖 logger 有效级别）。
- **JSONL 字段**：由 `parity_io.LlmIoTracer` 写入，`tool` 来自 `_TOOL_STACK[-1]`、`usage` 来自 `_usage_delta` 差分，
  与三段遥测口径同源，字段一致可对账（验证 4 已证）。

---

## 6. 安全评估

| 项 | 结果 |
|----|------|
| SQL 注入 / XSS | 通过 — 本模块不拼接 SQL；只读 `tool_call_logs`（`parity_io.py:262` 参数化） |
| 密码 / API Key / 敏感日志 | 通过 — 仅旁路读工具执行日志文案，不触及密钥；JSONL 留痕为 LLM 输入输出（既有能力，非本模块新增敏感面） |
| fail-open 铁律 5 | **通过** — `_EventSink.emit` 异常走 `logger.warning` 留痕（parity_events.py:96），对齐 parity_io.py:244 的 fail-open 先例；非静默吞异常 |
| 捕获泄漏 | 通过 — handler 双路径必移除（问题 #3 验证） |
| 注入依赖 | 通过 — 无新外部依赖，纯标准库 + logging |

---

## 7. 五轴评分

| 轴 | 分 | 依据 |
|----|----|------|
| 正确性 | 5 | 事件分类 5/5 文案全覆盖、裸失败不误判、口径一致独立复现 225 例 0 不一致、JSONL 字段齐全、单测+全量全绿 |
| 完整性 | 5 | 覆盖 timeout/retry/fail 三类及其重叠；要点命中/失分点/质量细节组合入口齐备；边界（None/空/Unicode/特殊字符）均验证 |
| 清晰性 | 4 | docstring（Args/Returns）充分；唯一减分项为 parity_telemetry 198/200 余量紧张（属可维护性而非清晰性） |
| 可维护性 | 4 | parity_events 小而内聚、易读；扣分点：parity_telemetry 仅剩 2 行红线余量（问题 #1），后续改动风险高，需先重构 |
| 安全性 | 5 | fail-open 留痕合规、零生产改动、无注入/敏感泄露面 |

---

## 8. ADR

**本次未产生 ADR**。纯评测层增强，零生产 diff、无新外部依赖、无与 plan 分歧的架构决策；
红线偏离（`src/config.py` opencode 三字段 + fallback_chain 默认）为独立提交 `ce6646b`/`8ac4c4a` 引入，
module-092 运行期 `.env` 同款链零差异，依 changelog §三/AC-28 已申报、无需 ADR（与既往 092 Reviewer 裁定一致）。
