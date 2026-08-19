# Module-068 审查报告 — Agent 阶段推进死锁修复

> Reviewer：2026-08-17 | 对照 `acceptance-criteria.md` + `plan.md` + `task-brief.md` 逐项核查
> 结论：**✅ 通过（PASS）——第一轮 1 项 mustFix（changelog §三 勘误）经第二轮复审确认修复完成；存量 6 处测试断言更新裁定通过；3 项 minor 非阻塞（2 项遗留 backlog，1 项建议）**
> 轮次：第一轮审查（本文件 §一~§六，2026-08-17 09:32）+ 第二轮复审（§七，mustFix 修复验证，2026-08-17）

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest -q`（ai_service 根） | **1116 passed + 1 ERROR（162.65s）**——ERROR 为 `scripts/test_models.py::test_model` 收集错误（scripts/ git diff 零改动，module-050 遗留，066/067 review 同口径）；增量 1116−1102=14 与新增单测数吻合 |
| 新增 + 存量阶段测试 | 独立复跑 `python -m pytest tests/agent/test_agent_phase_fix.py tests/agent/test_tool_phase_split.py tests/agent/test_agent_tools.py -q` | **94/0**（14 新增 + 80 存量）|
| advance_phase 边界 | 直接调用探针（非测试） | 长度不齐 results zip 截断；3 轮无结果强制切（rounds=3 → generation）；re_search 带内容仍不触发；旧签名单列表调用 3 次递增 rounds ——全部符合预期 |
| agent_eval_runs | 直查 DB id=1/2/3（created_at/git_commit/scores/per_question） | 3 行落库；id=3 scores 与 changelog §六逐字一致（pass_1=0.0 / tool_correct 0.1 / no_extra 0.2 / args 1.0 / grounding 1.0 / avg 4.6 / tokens 16556.6 / P50 24543.5 / P95 37367.0 / per_path 0-0-0）|
| 失败分类 | 按 `agent_tasks.py::classify_failure`（L200-214）四规则独立复算 id=3 十条 per_question | 工具选错×8（no_extra=False）/ 工具漏调×1（at-016 no_extra=True 但 coverage=False）/ 答案缺要点×1（at-303）——与 changelog §六分类完全一致 |
| id=2 勘误核验 | PG 时区实测 `SELECT current_setting('TimeZone'), now()` | **PG TimeZone=Etc/UTC**（now()=01:25 UTC vs 本地 09:25）；created_at 为 UTC 墙钟时间 → **id=2 = 2026-08-17 07:58:57 本地**，晚于 react.py 最后修改（07:36:07 本地）——§三 勘误"早于本模块代码落地"不成立（详见 §三 finding 1）|
| 多轮预算口径 | 读 `agent_tasks.py::_run_agent_once`（L325-330 每轮新 ctx + `react_loop(settings.max_agent_tools)`） | **多轮任务按轮重置预算**，at-105/at-107 的 8 工具 = 两轮各 4（id=1/id=3 同有 8 工具任务）——§三 勘误"轨迹超默认预算口径"不成立（详见 §三 finding 1）|
| 评测身份清理 | 直查 `documents WHERE source LIKE 'memory:eval-066-anon:%'` | **0 行**（测后清理生效）|
| 红线文件 | git diff 全量核对 | tool_registry.py / engine.py / eval/agent_tasks.py / agent_tasks.json / database.py / scripts/ **零 diff** ✓ |
| 存量测试零改动 | git diff tests/ | 仅 conftest.py 新增 autouse fixture（max_agent_tools=4）+ test_tool_phase_split.py 6 处 schema 序列断言按新语义更新（§三 finding 2 裁定）；test_advance_phase_unit（L135-145）**零改动** ✓ |
| CONTEXT.md 只增不删 | diff 核查 | +8 行（module-068 索引行 + 追加段），零删行 ✓ |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-068 行 + v0.68.0 + §5 状态 + backlog 3 项 + file-index module-068 目录行 + [PLAN]/[CODE] 行全在（本条为 Reviewer 行）|

## 二、WP 逐项核对

### WP-A：死锁修复——检索命中即切 generation — ✅ 通过

- **`_RETRIEVAL_HIT_TOOLS`**（react.py:147-150）：恰 6 个（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory），**不含 re_search**（双组补检排除），与 plan §1 逐字一致 ✓
- **`_EMPTY_RESULT_MARKERS`**（react.py:153）："（无检索结果）"/"（无相关历史记忆）"——与 tool_registry.py:151/:218 文案逐字核对一致（耦合点注释标注 + 单测钉住）✓
- **`_retrieval_hit`**（react.py:156-183）：零 LLM；空串 False；空标记 False（非空字符串坑排除）；extract_entities JSON 解析 entities 非空才 True（解析失败/无 entities 键按非空文本判定）；其余非空文本 True。单测 8 例全覆盖 + 独立探针复验 ✓
- **`advance_phase(ctx, executed_names, executed_results=None)`**（react.py:204-234）：三条件任一即切（原生成工具条件 → 命中分支 → 防空转兜底 rounds≥3 强制切），**单向前进不回退**；`executed_results=None` 时行为=旧逻辑（存量 test_advance_phase_unit 单列表调用零改动通过，94/0 实证）✓
- **防空转兜底**（react.py:232-234）：rounds 递增仅在本轮未因其他条件切换后；阈值判定在切换条件之后防重复切换；参数化 `agent_retrieval_max_rounds`（默认 3）+ 单测（max_rounds=1 变体）✓
- **react_loop**（react.py:445-472）：同序收集 `executed_results`（execute_tool_with_log 返回值）；langgraph execute_tools（langgraph_react.py:150-178）同构 ✓
- **at-002 症状自然消解**：执行层不校验 schema 暴露的现状未动（plan 明确不做），修复后命中切 generation 使 generate_answer 在下一轮 schema 可见 ✓
- **通过标准（真实轨迹出现 generate_answer）**：id=2 的 at-101 轨迹 `[search_knowledge, search_fts, search_knowledge, generate_answer, search_knowledge, search_knowledge]` 含 generate_answer 且 pass——是三次运行中**唯一**一次知识类任务经 generate_answer 达 pass 的直接实证（但该运行被勘误错误排除，见 finding 1）；id=3 未出现（行为性残余）

### WP-B：预算按阶段（检索 ≤3 + 生成 ≤2，总 5）— ✅ 通过

- **config.py:104-118**：`max_agent_tools` 默认 4→5（不删字段，PW_MAX_AGENT_TOOLS 兼容）+ `agent_retrieval_budget=3` / `agent_generation_budget=2` / `agent_retrieval_max_rounds=3`，均带 PW_ 覆盖 ✓
- **截断点**（react.py:430-436 / langgraph_react.py:132-138）：`total_remaining = max(0, budget - tool_count)`；`tool_phase_split=true` 时 `allowed = tool_calls[: min(total_remaining, phase_remaining)]`；**false 回退纯总预算存量行为逐字**（conftest 钉住 false 存量 80 项零漂移实证）✓
- **`_phase_budget`**（react.py:186-190）：generation→agent_generation_budget，其余→retrieval 预算 ✓
- **phase_count 按执行时阶段计数**（react.py:458 / langgraph_react.py:163）：切 generation 前执行全部算检索阶段；AC-12 单测实证 `{"retrieval": 1, "generation": 2}` ✓
- **langgraph `phase_exhausted` 路由**（langgraph_react.py:139-143, 249-264）：allowed 空且 total_remaining>0 → 标记 → 路由 fallback——与手写循环 `if not allowed: break` 语义对齐，防"回 llm_call 后 allowed 恒空死循环"（脚本化假 LLM 下必现）。plan 未细化此点，属**必要补充**（plan §0 预算截断点分析只覆盖手写版；langgraph 无 break 语义，无此路由必死循环），实现正确、已注释、单测覆盖（test_langgraph_retrieval_phase_budget_truncates）✓
- **通过标准（平均步数 ≤6）**：id=3 avg_tool_count=4.6 ✓（id=2 亦 4.6）

### WP-C：066 评测重跑 — ⚠️ id=3 数字如实且与 DB 逐字一致；但 §三 勘误两处论证与硬证据矛盾（mustFix，见 §三 finding 1）

- **id=3 数字如实**：pass^1=0.0 / 工具正确率 0.1 / 无多调率 0.2 / 参数正确率 1.0 / Grounding 1.0 / 平均步数 4.6 / 平均 token 16556.6 / P50 24543.5 / P95 37367.0 / per_path 三路全 0——与 DB scores **逐字一致** ✓
- **与 066 首跑对比口径区分诚实**：task-brief 引用的 0.0/0.0 系 066 冒烟 --limit 2；DB id=1 首跑（--sample 10 --pass_k 3）实为 pass^1=0.1/工具正确率 0.1——changelog §三如实区分，未混用 ✓
- **失败分类更新如实**：工具选错×8 / 工具漏调×1 / 答案缺要点×1（at-303 realtime id=1 pass→id=3 fail 系 LLM 答案方差，非回归）——独立复算与 DB per_question 完全一致 ✓
- **结构性修复实证**：id=3 轨迹呈"检索 2 + 生成阶段 2"阶段截断形态（at-002=[sk, extract_entities, sk, sk] 等 4 工具任务在阶段预算下第 3 轮 allowed=[] 截断），对比 066 首跑"4 轮全检索"——状态机真实生效 ✓（独立核对 id=3 全部 10 条轨迹与 budget=5 + 阶段预算 3/2 口径吻合）
- **行为性残余根因分析**（_SYSTEM_PROMPT 全量 10 工具清单 + 执行层不校验 schema 暴露）与 plan §6 风险预判一致，backlog 3 项合理 ✓
- **不达标不隐藏**：pass^1 未提升如实记录（未预设成功），判定器/评测集未改凑数 ✓

### WP-D：回归 + 文档收口 — ✅ 通过

- 新增 14 项单测覆盖 plan WP-A ①-⑥ + WP-B ①-⑤（含 AC-2 参数化/AC-10 总预算兜底/AC-11 开关 false/AC-12 双循环同构）全绿 ✓
- conftest autouse 钉住 `max_agent_tools=4`：与生产默认 4→5 矛盾的存量断言（test_agent_tools.py L585 `settings.max_agent_tools == 4`、L679/L705 `done["budget"] == 4` 共 3 处 + test_rerank_langgraph.py 1 处）双轨化解——测试环境钉住 + 生产新默认，对齐 056/058/066 先例；新测试显式传 budget 覆盖 ✓
- changelog（WP-A~D + plan 矛盾点 §五 + WP-C 实测 §六 + 勘误）、CONTEXT.md（+8 行只增不删）、三记忆文件全 ✓

## 三、发现

### 3.1 阻塞问题（mustFix）

| # | 文件 | 位置 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | specs/module-068-agent-phase-fix/changelog.md | §三 勘误（L87-91） | **勘误两处论证与硬证据矛盾，id=2 排除不成立**：① 实测 PG TimeZone=Etc/UTC，agent_eval_runs.created_at 为 UTC——id=2（2026-08-16 23:58:57 UTC）= **2026-08-17 07:58:57 本地**，**晚于** react.py 最后修改（07:36:07 本地），"早于本模块代码落地"不成立（Developer 在 §六把 id=3 的 01:16 UTC 正确转成本地 09:16，却在 §三 把 id=2 的 23:58 UTC 当成本地时间，两次换算不一致）；② "轨迹（单任务最高 8 工具）超出默认配置预算口径"不成立——`agent_tasks.py::_run_agent_once`（L325-330）多轮任务**按轮重置预算**（每轮新 ctx + react_loop(settings.max_agent_tools)），at-105/at-107 的 8 = 两轮各 4，id=1/id=3 同有 8 工具任务；③ 正确画像：id=2 系 **module-068 代码落地后的运行**（时间戳 + 轨迹形态与模块语义一致），其 at-101 轨迹含 generate_answer 且 pass（三次运行中唯一一次知识类任务经 generate_answer 达 pass——WP-A 通过标准"真实轨迹出现 generate_answer"的直接实证）；其精确代码状态/环境覆盖（PW_MAX_AGENT_TOOLS / PW_TOOL_PHASE_SPLIT）无法从 config_snapshot 确证，应**如实并列报告**而非以错误理由排除 | 阻塞（高） | 按 §一 已验证事实重写 §三 勘误：注明 created_at 为 UTC（PG 实测）+ 多轮按轮预算口径 + id=2 与 id=3 并列报告（pass^1=0.2 / 0.0），标注环境口径无法确证；WP-A 通过标准证据（id=2 at-101 generate_answer pass）同步补入 §六 |

### 3.2 存量测试 6 处断言更新——裁定：**通过（接受）**

plan §0 兼容分析只覆盖 test_advance_phase_unit（单列表调用），未覆盖同文件 6 个循环级用例的"第 2 轮仍在检索组"时序断言——该断言与模块核心特性（检索命中即切）**互斥**（第 1 轮 search_knowledge 返回非空 docs → 命中 → 第 2 轮 schema 必为生成组，逐轮推演 + 94/0 实证）。处理方式符合先例（module-061/062 验收许可更新）：
- 仅更新 6 处 schema 序列断言值（RETRIEVAL_7 → GENERATION_4）+ 注释，**tool_count/兜底答案/预算路径断言逐字保持**（diff 核对）✓
- test_advance_phase_unit（直接单测 advance_phase 的用例）**零改动**，向后兼容红线实质未破 ✓
- 新断言未变弱：仍验证状态机转换 + 额外验证新命中切规则 ✓
- changelog §五 如实记录矛盾点并提交 Reviewer 裁定——处理方式正确。**裁定结论：按本变更（接受），不阻塞**。接受后 AC-22/验收基线"存量测试零改动"按"仅 6 处断言值随特性语义更新 + 预算路径断言逐字保持"口径解释，建议 Tester 签署时按此口径核对。

### 3.3 建议改进（不阻塞）

| # | 文件 | 位置 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/agent/react.py | L153 `_EMPTY_RESULT_MARKERS` | search_graph 空实体标记 "（图检索：未提取到实体）"（tool_registry.py:198）不在排除清单——图谱无实体时误判命中提前切 generation（轻度次优，生成组仍有 re_search 补检口）。Developer 已在 changelog §八 如实声明 | 低 | 后续顺手加进元组（react.py 内一行，不碰 tool_registry 红线）或保持现状（plan 只列 2 个标记，已如实声明）|
| 2 | ai_service/tests/agent/test_agent_phase_fix.py | 全文件 | 无断言生产新默认 `max_agent_tools == 5`（conftest 钉住 4 + 新测试显式传 budget）——4→5 默认值变更本身无测试覆盖 | 低 | 补一条 `settings.max_agent_tools == 5` 默认值断言（或 conftest 内注释）|
| 3 | 同上 | — | conftest autouse 钉 max_agent_tools=4 使所有存量测试在"旧默认"下运行——与 056/058/066 钉 tool_phase_split=false 同模式，属测试环境 hermetic 设计，接受 | 低 | 无需处理 |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| tool_registry.py / engine.py / 检索链路零改动 | git diff 全量 | ✅ |
| 066 判定器 / 评测集（agent_tasks.json / agent_tasks.py）不改不凑数 | git diff 全量 | ✅ |
| 零 LLM 判断（不引入"LLM 自报检索完成"） | `_retrieval_hit` 纯函数确定性 | ✅ |
| 存量测试零改动 | 仅 6 处断言值随特性语义更新（裁定通过）+ conftest 新增 fixture；test_advance_phase_unit 零改动 | ✅（按 §3.2 口径）|
| CONTEXT.md 只增不删 | +8 行零删行 | ✅ |
| 前端 / Java 零改动 | git diff 全量 | ✅ |
| 无新依赖 / 无新 ADR | requirements 零 diff；行为修复非架构决策（ADR-0012 方案 A 未推翻）| ✅ |

## 五、架构与代码质量评估

- **单点防漂移**：_retrieval_hit / _phase_budget / advance_phase 放 react.py 供两条循环共用（对齐 schemas_for_phase / execute_tool_with_log 既有模式），langgraph 仅接线 ✓
- **最简实现（ponytail）**：不重写循环——仅 advance_phase 条件扩展 + 截断点一行改造 + ctx 两字段；功能代码 ~85 行（react.py +99 / langgraph +39 / config +16），符合 plan ≤200 行口径 ✓
- **langgraph phase_exhausted**：plan 未覆盖的必要补充（否则脚本化假 LLM 下必死循环），实现最小且注释完整——正确性经单测 + 代码推演确认 ✓
- **分层/依赖**：纯 Python 侧，无跨层/反向依赖；无新增 import 环 ✓
- **安全**：无新输入面/无密钥/无落库变更；空结果标记硬编码属工具文案耦合（已注释 + 单测钉住 + backlog）✓
- **文档**：changelog 结构完整、矛盾点与实测如实呈现（除 §三 勘误外）；CONTEXT.md 只增不删 ✓

## 六、结论

**⚠️ 有条件通过（CONDITIONAL）——修复 mustFix #1（changelog §三 勘误重写）后进 Tester。**

- WP-A / WP-B / WP-D 全部通过标准达成，代码与 plan 逐字一致；红线全守（tool_registry/engine/判定器/评测集零 diff）。
- WP-C id=3 数字（pass^1=0.0 未提升 + 失败分类）与 DB 逐字一致、如实不隐藏；**但 §三 勘误的两处排除论证（"早于代码落地"、"轨迹超预算"）与硬证据（PG UTC 时间戳 + 多轮按轮预算）直接矛盾**——id=2 实为 module-068 代码落地后的运行，且其 at-101 经 generate_answer 达 pass 恰是 WP-A 通过标准的唯一真实实证。修正方向（报告而非排除）不改变"pass^1 未达门槛"的结论，反而使记录更完整诚实（id=2 pass^1=0.2 / id=3 0.0，LLM 行为性方差区间）。
- 全量 1116/0 独立复跑确认；94/0 定向测试确认；agent_eval_runs 三行落库与 changelog 逐字核对一致。

**mustFix #1 修复指引（具体可执行）**：
1. §三 勘误改写为：注明 `agent_eval_runs.created_at` 为 PG UTC（`SELECT current_setting('TimeZone')` = Etc/UTC 实测），id=2（23:58:57 UTC）= 2026-08-17 07:58 本地，晚于 react.py 最后修改 07:36；
2. 删除"轨迹超默认预算口径"论证（多轮任务按轮重置预算，8 = 4+4，id=1/id=3 同口径）；
3. 将 id=2 并列报告：module-068 代码落地后的运行，pass^1=0.2（at-101 经 generate_answer 通过，WP-A 真实轨迹实证），环境覆盖（PW_MAX_AGENT_TOOLS/PW_TOOL_PHASE_SPLIT）无法从 config_snapshot 确证如实标注；以 id=3 为口径主数字（更保守）不变。

---

## 七、第二轮复审（2026-08-17，mustFix 修复验证）

**结论：✅ 通过（PASS）**。Developer 修复轮**仅改 changelog.md**（git diff 复核：代码文件与第一轮审查时逐字一致，无新代码变更），mustFix ① ② ③ 逐项独立核验：

| mustFix 项 | 修复内容（changelog v3 §三/§六/§九） | Reviewer 独立验证 | 结果 |
|-----------|----------------------------------|-------------------|------|
| ① 时间口径错 | §三 改为注明 `created_at` 为 PG UTC（PG `TimeZone=Etc/UTC` 实测），id=2 = 2026-08-16 23:58:57 UTC = **2026-08-17 07:58 本地**，"早于本模块代码落地"撤回 | 直查 DB：id=2 created_at=23:58:57.624043 UTC ✓；`SELECT current_setting('TimeZone')` = **Etc/UTC** ✓；文件 mtime 实测：config.py **07:35:49** / react.py **07:36:07** / langgraph_react.py **07:36:25** —— id=2 落库晚于最后修改约 22 分钟 ✓ | ✅ |
| ② "轨迹超默认预算"论证 | 删除该论证——per_question 判定轨迹（attempt 1）id=2 at-002=4 工具；"8 工具"系确定性 trace_id 跨 3 次尝试累积；多轮按轮重置预算（8=4+4 不超任何口径）；id=1/2/3 平均工具数同为 4.6 | DB scores：id=1/2/3 avg_tool_count **均 4.6** ✓；per_question id=2 at-105/at-107=8 工具（多轮两轮各 4）✓；tool_call_logs 按 created_at 窗口切分确认"8 工具"为 id=1/2/3 累积（如 eval-at-105-1 n=24 跨 17:19→01:11）✓ | ✅ |
| ③ id=2 并列报告 | §三+§六 将 id=2 并列报告：module-068 代码落地后真实运行，pass^1=0.2（at-101 经 generate_answer 达 pass，coverage=true、tool_correct=false 系判定器 2 工具严格口径；at-303 零工具 pass），config_snapshot 无 agent 侧配置环境覆盖无法确证如实标注；id=3 主口径 pass^1=0.0 数字不变；两 run 差异归因 LLM 行为方差 | DB per_question id=2：at-101 pass=True / cov=True / tools=6 / actual 含 generate_answer（检索 3 → generate_answer → 补检 2 形态逐字吻合）✓、at-303 pass=True / actual=[]（零工具）✓、pass^1=2/10=0.2 ✓；config_snapshot 仅 10 个 RAG 键（min_chars/chunk_size/... 无 max_agent_tools/tool_phase_split）✓ 诚实标注成立 | ✅ |
| §六 补 WP-A 通过标准证据 | id=2 27 条尝试轨迹 5 条含 generate_answer（at-101×3 + at-002-3 + at-016-2）；id=3 28 条中 2 条（at-016-2、at-101-3）；"从未入轨迹"按判定轨迹（attempt 1，10 条全缺）口径澄清；at-016 工具漏调分类加判定口径注 | tool_call_logs 按 created_at 窗口切分实测：**id=2 窗口 27 条 eval 尝试（28 trace_id − probe-068-1）5 条含 generate_answer（eval-at-101-1/2/3、eval-at-002-3、eval-at-016-2）** ✓；**id=3 窗口 28 条 2 条含（eval-at-016-2 ga×1、eval-at-101-3 ga×2）** ✓；id=3 per_question 10 条判定轨迹（attempt 1）全部不含 generate_answer ✓；id=3 at-016 4×search_knowledge no_extra=True cov=False = 工具漏调 ✓ | ✅ |
| §九 v3 行 + §六 UTC 标注 | 变更记录 v3 行（Review 回修摘要）+ id=3 落库 01:16:12 UTC = 09:16 本地 | changelog 已含 v3 行 ✓；DB id=3 created_at=01:16:12.238649 UTC ✓ | ✅ |

**本轮独立复验（不采信 changelog 数字）**：
- 定向测试 `pytest tests/agent/test_agent_phase_fix.py tests/agent/test_tool_phase_split.py tests/agent/test_agent_tools.py -q`：**94/0**（14 新增 + 80 存量）✓
- 全量 pytest：**1116 passed + 1 ERROR（205.92s）**——ERROR 为 `scripts/test_models.py::test_model` 收集错误（scripts/ git diff 零改动，module-050 遗留，066/067 同口径），0 failed ✓（= 1102 基线 + 14 新增）
- 红线复核：tool_registry.py / engine.py / eval/agent_tasks.py / agent_tasks.json / database.py / scripts/ / requirements.txt **零 diff** ✓；CONTEXT.md +8 行只增不删 ✓；eval-066-anon 评测身份残留 **0 行** ✓
- config 新增三字段均经 `env_prefix="PW_"`（config.py:293）自动映射 PW_AGENT_RETRIEVAL_MAX_ROUNDS / PW_AGENT_RETRIEVAL_BUDGET / PW_AGENT_GENERATION_BUDGET（AC-24）✓

**第二轮新增 minor（非阻塞，入 backlog）**：
| # | 文件 | 位置 | 问题描述 | 严重级别 | 处理 |
|---|------|------|----------|----------|------|
| 1 | ai_service/tests/agent/test_tool_phase_split.py | test_verify_answer_switches_to_generation（L176-194） | 断言更新后该用例不再独立覆盖"verify_answer 触发切 generation"（第 1 轮检索命中已先切，verify_answer 在第 2 轮生成 schema 下执行，断言 tools_seen[1]==GENERATION_4 与 verify_answer 无因果）；verify_answer 与 generate_answer 同属 `_GENERATION_GATE_TOOLS` 集合（react.py:142）逐字未变 + test_advance_phase_unit 直调 generate_answer 覆盖集合成员判定，功能风险为零，仅覆盖率语义偏移 | 低 | 后续补一条"第 1 轮空检索 + 第 2 轮 verify_answer → 第 3 轮切 generation"用例（或保持现状，集合成员静态可审） |
| 2 | ai_service/agent/react.py | L153 | search_graph 空实体标记"（图检索：未提取到实体）"未入排除清单（第一轮 minor #1 遗留，changelog §八 已如实声明） | 低 | 保持现状（已声明）或后续加一行 |
| 3 | ai_service/tests | — | 无生产默认 max_agent_tools==5 断言（第一轮 minor #2 遗留） | 低 | 后续补默认值断言 |

**复审结论**：mustFix #1 已按指引完整修复且新论证与 DB 硬证据逐字一致；WP-A/WP-B/WP-D 第一轮已通过且代码零变更；WP-C id=3 数字如实（pass^1=0.0 未提升 + 失败分类），id=2 并列报告使记录更完整诚实（pass^1 0.2 vs 0.0 归因 LLM 行为方差，与 §六 at-303 转 fail 同类）。**裁定：通过（PASS），进 Tester**。Tester 签署时按 §3.2 口径核对"存量测试零改动 = 仅 6 处断言值随特性语义更新 + conftest 新增钉住 fixture + test_advance_phase_unit 零改动"。
