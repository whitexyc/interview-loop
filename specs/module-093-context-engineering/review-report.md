# 审查报告 — Module-093: 上下文工程（预算观测 + 历史压缩 + 对拍裁定）

> Reviewer: reviewer-093 | 2026-09-11 | 审查范围：commit 4fcfd54..6020049
> 审查方式：全文件通读 + 独立复算/复跑（AST / D3 / D1 / DB 对账 / junitxml 全量回归）
> 说明：本审查为平台 429 中断后的自动重派轮，全部验证由本轮独立完成。

## 1. 审查结论

**通过（PASS，附条件）** — 2026-09-11 | 审查人：reviewer-093

- **0 阻塞 / 0 高 / 2 中 / 3 低**。两项"中"均为文档口径问题（AST 申报口径失实、
  AC-2 高估结论过强），代码本体与对拍数据经独立复算全部成立，不阻塞进入 Tester；
  但 **changelog / ADR / ctx-report 勘误归 Developer 下一轮完成**（本报告 §2）。
- 核心裁定速览：
  - **AST 申报失实属实**：Developer 申报 23/6/34 系**顶层语句口径**（`len(tree.body)`），
    项目既定口径为 ast.walk 全语句计数（092 先例 198 即该口径）→ 实测 **150/24/173**。
    两种口径下红线均满足（150≤200、197≤350），定性为申报口径错误而非虚报，要求勘误。
  - **D3 原子折叠独立验证通过**：自写脚本构造 3/6/10 轮 × keep_recent∈{0,2,6,12,30}
    共 15 组多轮 tool_calls 消息 + compress_view 全链路触发，折叠后**零孤儿 tool 消息**、
    system 全保留、首条 user 原文保留、摘要恒单条。
  - **D1 视图语义验证通过**：未启用/未超限返回原 list 引用（`is` 断言）；启用超限返回
    新列表且 deepcopy 快照比对原列表零 mutate；clear/compact 均不 mutate 入参。
  - **对拍数据真实且可复算**：agent_eval_runs id=39/40/41 独立复算 pass_1
    **0.5614/0.5439/0.4737** 与报告逐值一致（32/57、31/57、27/57），fixture=False、
    git_commit=4fcfd54d、ctx_mode 三值齐全、module=093；三判据复算结论一致
    （clearing ② FAIL → 不引入；compaction 三过 → 引入）。
  - **归因严谨性裁定：成立**。+31.6% 反升拆解为每调用视图膨胀 +36%（独立复算
    5197→7061，**+35.9%**）数据可复算；"re-invoke 假说不可证"属实——ctx-* trace
    命名空间确与首跑/fixture 行共用（trace 时间窗 03:13~05:29 vs 落库 05:29:54，
    无 run_id 不可逐行归属），且方向证据（clearing 60 < off 169）确实相反；
    "失锚→长答案复利"机理已如实标注 hypothesis，未越界坐实。
  - 全量回归 junitxml 权威：**tests=1870 / failures=0 / errors=0 / skipped=3**
    （=基线 1849 + 21 新增，零新增失败）；定向单测 21 passed。

## 2. 问题列表

### 阻塞/高

（无）

### 中（须 Developer 勘误，不阻塞 Tester）

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|---------|---------|
| MID-1 | specs/module-093-context-engineering/changelog.md + specs/adr/0022-context-compression.md | changelog:11-17 表格与 §验收摘要、ADR §6 | **AST 申报口径失实**：申报 23/6/34 为顶层语句数（`len(tree.body)` 复算恰为 23/6/34 实证），项目红线口径为 ast.walk 全语句（plan §5、092 先例）。实测 ast.walk：ctx_manager=**150**、ctx_tasks=**24**、ctx_parity=**173**（合计 197）。红线两种口径均满足，但数值失实 6.5 倍须勘误 | 中 | changelog 三处 AST 数值改为 150/24/173（注明 ast.walk 口径），并保留一句" Developer 初报 23/6/34 系顶层语句口径误用"的勘误记录；ADR §6 同步 |
| MID-2 | specs/module-093-context-engineering/ctx-report.md + ai_service/agent/ctx_manager.py | ctx-report §3、ctx_manager.py:39-45 | **AC-2 "误差方向安全侧"结论过强**：报告 5/5 样本（中文/技术中文）成立，但审查员独立抽样的 ASCII 密集混合文本 `RAG系统使用bge-m3嵌入模型与RRF融合排序，Hit@5达到0.9905` 实测 est=26 < tiktoken=32（ratio **0.81**，低估）——ASCII 4 chars/token 对代码标识符/数字密集文本偏低。AC-2 字面标准（自选 5 条标注样本）满足，但"宁可高估"非普适 | 中 | ctx-report §3 补一段诚实边界："高估方向对中文/技术中文成立；ASCII 密集（代码标识符/数字）文本可能低估至 ~0.8"；三臂同比结论不受影响（同系数），触发线在英文密集场景可能偏晚 |

### 低（记录，可随下轮顺带）

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|---------|---------|
| LOW-1 | ai_service/agent/ctx_manager.py | 61 | `_is_cjk` docstring 残留旧系数："True=CJK（按 **1.5** chars/token 估算）"，与实际 0.8（:44 `_CJK_CHARS_PER_TOKEN`）矛盾 | 低 | 改为"按 0.8 chars/token 估算" |
| LOW-2 | ai_service/eval/ctx_parity.py | 304 | `_git_commit` 的 `except Exception: return ""` 静默吞异常（eval 层可接受，但违反"静默失败"最小化精神） | 低 | 加 `logger.debug("git commit 获取失败", exc_info=True)` |
| LOW-3 | ai_service/agent/ctx_manager.py | 254-256 | `_summarize_rounds` 截断长度 80/120 为魔法数字 | 低 | 提为模块常量 `_SUMMARY_USER_CHARS=80` / `_SUMMARY_ASSISTANT_CHARS=120` |

### 备忘（非问题，核实记录）

- ctx-report §7.2/§8 已如实标注 ctx-* trace 行不含 run_id、与首跑/fixture 共用命名空间
  ——审查员 DB 实证（tool_call_logs ctx-* 时间窗 2026-09-11 03:13~05:29，三行 id=39/40/41
  落库于 05:29:54；前缀计数 off=169/clearing=60/compaction=77 与报告逐值一致）。
  该诚实标注是本轮 §8 归因"严谨"判定的关键依据。
- Developer 记忆纪律合规：file-index 登记（:287）、activity-log `[DEV]` 行、
  project-context 热区均已更新（diff stat 实证）。

## 3. 验收标准核对

| 验收项 | 对应代码 文件:行号 | 状态 | 备注 |
|--------|-------------------|------|------|
| AC-1 估算器边界 | ctx_manager.py:85-89 | ✅ | 单测 + 独立脚本复验（空串 0、正/单调） |
| AC-2 宁可高估 | ctx_manager.py:44-45 + ctx-report §3 | ✅* | 字面标准满足（自选 5 条）；独立抽样发现 ASCII 密集低估边界 → MID-2 |
| AC-3 纯函数可单测 | ctx_manager.py:73-89 | ✅ | 无网络/模型依赖，21 项单测全绿 |
| AC-4 五桶分类 | ctx_manager.py:115-144 | ✅ | count 逐桶断言正确 |
| AC-5 tools 桶来源 | ctx_manager.py:140-143 | ✅ | tool_schemas JSON 序列化估算 |
| AC-6 观测零行为 | ctx_manager.py:147-168 | ✅ | 深比较零 mutate 独立复验 |
| AC-7 clearing 占位符 | ctx_manager.py:193-215 | ✅ | role/tool_call_id/顺序逐字不变 |
| AC-8 保留窗口 | ctx_manager.py:207 | ✅ | keep_recent 窗口 + 计数准确 |
| AC-9 可恢复 | tool_call_logs（落库先例 :13） | ✅ | 机制就位（T4 逐条对账归 Tester） |
| AC-10 块完整性 | ctx_manager.py:264-298 | ✅ | **15 组独立构造 + 全链路触发均零孤儿**（本轮 D3 脚本） |
| AC-11 保留项 | ctx_manager.py:278-297 | ✅ | system 全保留 + 首条 user + 摘要单条（独立复验） |
| AC-12 视图编排 | ctx_manager.py:323-343 | ✅ | `is` 断言 + 新列表 + 深比较（独立复验） |
| AC-13 默认关零行为 | config.py:210 + ctx_manager.py:331 | ✅ | 默认 False 返回原引用；全量 1870/0/3 |
| AC-14 两环路共用 | react.py:510-518 / langgraph_react.py:101-109 | ✅ | 同一 `agent.ctx_manager.compress_view`（grep 无分叉）；接入 diff 各 11 行 ≤20 |
| AC-15 观测 span | react.py:514 / langgraph_react.py:105 | ✅ | 每轮 ctx_budget span，trace_spans_enabled 可静音 |
| AC-16 压缩 span | react.py:515-517 / langgraph_react.py:106-108 | ✅ | triggered 时记 ctx_compress（wiring 测试断言） |
| AC-17 配置回退 | config.py:199-210 | ✅ | 纯增量三字段（diff 实证 +14/-0），PW_ 前缀 |
| AC-18 AST 红线 | 三文件 ast.walk 复算 | ✅* | 150≤200、197≤350 红线满足；**申报数值失实** → MID-1 勘误 |
| AC-19 代码规范 | 全部新增文件 | ✅* | 方法 ≤50 行（最长 compress_view 43 行）；public docstring 齐；无空 except；LOW-1/3 两处小疵 |
| AC-20 单测 | tests/agent/test_ctx_manager.py + wiring | ✅ | 21 passed；断言行为非 mock 计数 |
| AC-21 判据事前定死 | plan.md §2.9 + ADR §4；git_commit=4fcfd54d | ✅ | 跑批 commit 恰为 plan 提交，判据先于跑批入库（证据链闭合） |
| AC-22 诚实记录 | ctx-report §7/§8 | ✅ | 不利结论（clearing ② FAIL、compaction 裕度 0.0123/0.91%）逐值照实 |

## 4. 架构评估

- **分层合规**：全部能力落在 `agent/ctx_manager.py` 纯函数集；eval 插桩（`_InstrumentedClient`、
  `mock.patch.object(react_mod/lg_mod, "compress_view", ...)`）全在 eval 层且原行为透传，
  生产路径零 diff（红线实证：rag/、092 四封板文件、main.py 在 4fcfd54..6020049 均**零 diff**）。
- **D4 无分叉实证**：react.py:42 与 langgraph_react.py:40 均 `from agent.ctx_manager import
  compress_view, observe_context`，两环路调用点同构（各 11 行 diff，≤20 ✅）。
- **视图模式（D1）正确**：压缩只作用于传给 `chat_with_tools` 的副本，本地 messages 完整
  （wiring 测试 + 审查员独立深比较双证）；tool_call_id 引用链由 D3 原子折叠保护。
- **config 纯增量**：src/config.py +14/-0，仅三字段 + 注释，无存量行改动。
- **依赖方向**：ctx_manager 仅依赖 src.config/src.tracing，无反向依赖；eval 层单向引用 agent 层。
- **新增依赖**：无（估算器自研启发式，tiktoken 仅测试对比用且 venv 既有）→ 无需新 ADR。

## 5. 安全评估

| 检查项 | 结论 | 依据 |
|--------|------|------|
| SQL 注入 | ✅ 通过 | 零新 SQL；落库复用 066 `save_agent_eval_run` 参数化绑定 |
| XSS | ✅ 通过 | 无前端改动；摘要文本经 JSON 序列化进 span，非 HTML 输出 |
| 密码/API Key | ✅ 通过 | 无密钥引入；供应商鉴权走既有 settings |
| 敏感日志 | ✅ 通过 | 对拍用匿名 `eval-093-anon` 身份 + `_cleanup_eval_memory()` 测后清理；per_question 仅存 answer[:300] |
| 危险兜底/静默失败 | ✅ 通过（1 低） | 新增代码仅 ctx_parity.py:304 一处静默 except（LOW-2）；react/langgraph 接入无 try 吞异常 |
| 行为开关安全侧 | ✅ 通过 | 压缩默认关（D5），观测只读默认开；回滚 = 开关置 False 零行为变化 |

## 6. 五轴评分

| 轴 | 分 | 依据 |
|----|----|------|
| 正确性 | 4 | D3 15 组构造零孤儿、D1 引用/mutate 语义全过、DB 逐值复算一致、三判据复现；扣分：AST 申报口径失实（MID-1）、estimator 高估非普适（MID-2，机制影响有限） |
| 完整性 | 5 | AC-1~22 逐项有对应实现与验证；三臂对拍 + fixture 管线 + 失败归因 + 首跑事故诚实记录齐备 |
| 清晰性 | 4 | 模块 docstring/设计决策索引完整，public 函数 Args/Returns 齐；扣分：LOW-1 陈旧系数注释、LOW-3 魔法数字 |
| 可维护性 | 4 | 纯函数 + 视图模式 + 常数命名系数可调、单测锁定格式合法性；扣分：compress_view 五桶求和三处重复表达式（可提 `_total_tokens` 小函数） |
| 安全性 | 5 | 零新 SQL/零密钥/匿名身份/测后清理/默认关安全侧；唯一静默 except 属 eval 层低危 |

## 7. ADR

- **已产生：specs/adr/0022-context-compression.md**（状态：已采纳——clearing 不引入 /
  clearing+compaction 引入-灰度默认关）。审查核对：§4 三判据与 plan §2.9 逐字一致且先于
  跑批入库（跑批 git_commit=4fcfd54d 即 plan 提交，证据链闭合）；§5 裁定与 DB 复算一致；
  §5.1 "建议引入-灰度默认关"与 config 默认 False 自洽。**须勘误**：§6 的 AST 数字随 MID-1
  改为 ast.walk 口径（150 / 197 合计）。
- 无新 ADR 需求：无新外部依赖、无偏离 plan 的架构决策（CJK 系数 1.5→0.8 属实现参数
  修正且已申报，规则式摘要 D6 维持）。

## 附：本轮独立验证命令与输出摘要

```
# AST 复算（ast.walk stmt）
./.venv/Scripts/python.exe -c "import ast; ...": ctx_manager=150, ctx_tasks=24, ctx_parity=173
  （顶层语句口径复算恰为 23/6/34 —— Developer 申报口径实证）
# 定向单测
./.venv/Scripts/python.exe -m pytest tests/agent/test_ctx_manager.py tests/agent/test_ctx_compress_wiring.py -q
  → 21 passed, 2 warnings in 37.70s
# 全量回归（junitxml 权威，EXIT code 不可信以 XML 为准）
./.venv/Scripts/python.exe -m pytest tests/ -q --junitxml=_r.xml
  → XML: tests=1870 failures=0 errors=0 skipped=3 (285.7s)
# DB 对账（asyncpg @ postgresql://...personal_website，只读）
  id=39 off        module=093 fixture=False commit=4fcfd54d pass_1 复算 0.5614 (32/57) ✅
  id=40 clearing                                       pass_1 复算 0.5439 (31/57) ✅
  id=41 clearing_compaction                            pass_1 复算 0.4737 (27/57) ✅
  三判据复算：clearing ②FAIL→不引入；compaction ①②③OK→引入（与报告一致）
  每调用视图 token：off≈5197 / clearing≈7061（+35.9%）/ compaction≈3255
# D3/D1 独立脚本：15 组 rounds×keep_recent 组合 + compress_view 全链路 → 零孤儿、
  is 断言、深比较零 mutate，全部通过
# 红线：git diff 4fcfd54..6020049 -- ai_service/rag eval/langgraph_parity.py
  parity_telemetry.py parity_io.py parity_events.py main.py → 全空
```
