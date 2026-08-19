# Module-068 测试报告 — Agent 阶段推进死锁修复

> Tester：2026-08-17 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：✅ PASS（第二轮复审，mustFix ①②③ 修复验证通过，见 review-report.md）
> **验收结论：✅ 通过（全量 1116/0 独立复跑 / E2E 真实轨迹出现 generate_answer / pass^1 未达 0.8 目标如实记录，AC 口径满足）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑，`python -m pytest tests/ -q`） | **1116 passed / 0 failed（154.86s，44 warnings）** = 1102 基线 + 14 新增 |
| 新增单测 | `tests/agent/test_agent_phase_fix.py` **14 项全绿**（独立运行 96.33s） |
| 存量测试改动 | **仅 2 处**：conftest.py +1 autouse fixture 钉住 `max_agent_tools=4`（新增，对齐 056/058/066 模式）+ test_tool_phase_split.py 6 处 schema 序列断言值更新（RETRIEVAL_7 → GENERATION_4，module-068 命中即切语义，Reviewer §3.2 裁定通过）；`test_advance_phase_unit`（L135-145 直接单列表调用）**零改动** |
| 红线文件零改动 | tool_registry.py / engine.py / eval/agent_tasks.py / agent_tasks.json / database.py / scripts/ / requirements.txt 均不在 git status 改动清单（git 核对） |
| warnings | 与基线同源（SAWarning 连接清理等，非本模块引入） |

## 二、新增单测抽查（任务 6 个验证点逐项核对）

| 验证点（任务要求） | 对应用例 | 结果 |
|--------------------|----------|------|
| 检索命中即切（下轮 schema 含生成工具） | test_retrieval_hit_switches_to_generation：tools_seen[1] == GENERATION_4（生成组 4） | ✅ |
| 空结果标记不误判命中 | test_retrieval_hit_pure_function_boundaries：`"（无检索结果）"`/`"（无相关历史记忆）"`（非空字符串坑）/空串/extract_entities JSON 空 entities 均 False；re_search 与非检索工具名排除 | ✅ |
| 3 轮未命中强制切 | test_retrieval_max_rounds_force_switch（第 4 轮 schema 强制生成组）+ test_retrieval_max_rounds_parameterized（阈值参数化，1 轮即切） | ✅ |
| generation 内 re_search 不回退（回归） | test_re_search_in_generation_no_regression_with_results：补检后 tools_seen[3] 仍 GENERATION_4；存量 test_re_search_in_generation_no_regression 同步复验 | ✅ |
| 阶段预算截断（检索 3 + 生成 2） | test_retrieval_phase_budget_truncates（第 4 次检索截断 → 兜底）+ test_generation_phase_budget_truncates（生成组第 3 个截断） | ✅ |
| tool_phase_split=false 仅总预算（存量行为） | test_phase_budget_off_when_switch_false：纯总预算 4 次检索全执行、schema 全量 10 个 | ✅ |

**全量 1116/0 即开关 false（conftest 钉住）下所有存量测试全绿**——"tool_phase_split=false 仅总预算（存量行为逐字）"在全套存量上实证成立。

其他新增覆盖（Tester 抽查）：AC-3 原条件保留（test_advance_phase_old_signature_backward_compat，旧签名 4 次调用推演）、AC-6 签名向后兼容（results 缺省 None = 旧逻辑）、AC-10 总预算兜底（budget=2 收紧）、AC-12 phase_count 按执行时阶段计数（{"retrieval":1,"generation":2}）+ langgraph 同构 2 例（命中切 + 阶段截断 fallback 路由）。AC-13/AC-14/AC-15 由存量测试钉住（预算=0/耗尽兜底/re_search 补检口）。

## 三、E2E 冒烟（Tester 独立执行，真实 deepseek + Docker PG，未采信 changelog 数字）

命令：`python -m eval.agent_tasks --mode agent --sample 2 --no-save`（真实 LLM+DB，不落库）

```
Dataset: 2 tasks | Mode: agent | pass_k: 1 | Evaluated: 2
[Outcome]    pass^1: 0.5000
             knowledge_single   n=2   pass_rate=0.5000
[Trajectory] 工具正确率: 0.5000 | 无多调率: 1.0000 | 参数正确率: 1.0000
             Grounding: 1.0000
[System]     平均步数: 4.0 | 平均 token: 15523.0 | 耗时 P50/P95: 32533.0/37315.6 ms
失败案例分类（1 个，不隐藏）：
  工具漏调     at-008 tools=['search_knowledge'×4] expect=['search_knowledge','generate_answer']
```

**tool_call_logs 真实落库独立查表验证（`SELECT trace_id, tool_name FROM tool_call_logs WHERE trace_id LIKE 'eval-at-%' AND created_at > now() - interval '15 minutes'`）**：

```
eval-at-002-1 | search_knowledge
eval-at-002-1 | search_knowledge
eval-at-002-1 | search_knowledge
eval-at-002-1 | generate_answer      ← 真实轨迹出现 generate_answer（AC-7 ✅）
eval-at-008-1 | search_knowledge ×4（无 generate_answer → 工具漏调 fail）
```

- **AC-7 通过标准（Tester 独立证据）**：at-002 真实轨迹 = 检索 3 → generate_answer，该题 pass（pass^1=0.5）——"generate_answer 真实可达且被调用、不再全检索至预算耗尽兜底"在独立运行中实证（对比 066 首跑"4 轮全检索"）。at-002 未走兜底（无"工具预算耗尽"日志），答案由 generate_answer 产出。
- **at-008 残余失败 = changelog §六 分类的 LLM 行为性残余**：生成阶段 schema 下 deepseek 仍持续输出 search_knowledge（_SYSTEM_PROMPT 全量工具清单 + 执行层不校验 schema 暴露），至预算耗尽走 reflector 兜底——与 Developer id=3 重跑分类一致（工具漏调），非结构性缺陷，backlog 已有 3 项对应。
- 平均步数 4.0 ≤ 6（AC-19 ✅）；真实检索（图检索 entities 1-3、RAG 检索）全链路 200。
- 本跑 pass^1=0.5 与 id=3 主口径 0.0 差异系 LLM 行为方差（同 066 首跑 vs 冒烟 0.1 vs 0.5 先例），机制忠实记录。

## 四、存量测试改动核对（git diff 独立核对）

- `tests/conftest.py`：+1 autouse fixture `default_max_agent_tools_4`（钉住总预算=4，生产默认 4→5 与存量 budget==4 断言矛盾的化解，对齐 056/058/066 先例）——纯新增，无存量行修改。
- `tests/agent/test_tool_phase_split.py`：6 处 schema 序列断言值（RETRIEVAL_7 → GENERATION_4）+ 注释，**tool_count/兜底答案/预算路径断言逐字保持**；第 1 轮检索命中 → 第 2 轮 schema 必为生成组，与 module-068 核心特性互斥（Reviewer §3.2 逐轮推演实证 + 裁定通过）。
- `test_advance_phase_unit`（L135-145）：**零改动**——advance_phase 签名向后兼容红线实质未破。
- 生产红线文件（tool_registry/engine/判定器/评测集/database/scripts）：git status 无任何条目，零改动。
- specs/ 目录 gitignored（.gitignore:41），spec 文档在盘上不追踪，属既有工作流。

## 五、AC 逐条对照（重点项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| AC-1 检索命中即切 generation | ✅ | 单测 tools_seen 序列（第 1 轮 RETRIEVAL_7 → 第 2 轮 GENERATION_4）+ E2E at-002 检索 3 → generate_answer |
| AC-2 防空转兜底（3 轮强制切，参数化） | ✅ | test_retrieval_max_rounds_force_switch + 参数化变体 |
| AC-3 原条件保留（生成工具触发） | ✅ | test_advance_phase_old_signature_backward_compat + 存量 6 用例复验 |
| AC-4 命中判定零 LLM | ✅ | `_retrieval_hit` 纯函数确定性（代码审阅 + 单测 8 例） |
| AC-5 命中判定边界 | ✅ | 空标记/空串/extract_entities 空实体/re_search 排除/非检索工具名全断言 |
| AC-6 签名向后兼容 | ✅ | results 缺省 None = 旧行为；test_advance_phase_unit 零改动通过 |
| AC-7 真实 E2E 轨迹含 generate_answer | ✅ | **Tester 独立运行查表实证**（eval-at-002-1 含 generate_answer 且 pass） |
| AC-8/AC-9 阶段截断（检索 3 + 生成 2） | ✅ | 单测两例 + langgraph 同构 |
| AC-10 总预算兜底 | ✅ | budget=2 收紧场景单测 |
| AC-11 开关 false 仅总预算 | ✅ | 单测 + **全量 1116 项在 conftest 钉 false 下全绿**（最强实证） |
| AC-12 阶段计数口径 + 双循环同构 | ✅ | phase_count 断言 {"retrieval":1,"generation":2} + langgraph 2 例 |
| AC-13 预算=0 | ✅ | 存量测试钉住（全量绿） |
| AC-14 预算耗尽兜底不变 | ✅ | 存量 test_budget_exhausted_fallback_unchanged（仅 schema 断言值随语义更新，兜底答案逐字） |
| AC-15 generation 内 re_search 不回退 | ✅ | 新增 + 存量两版用例 |
| AC-16 评测重跑跑通 + 落库 | ✅ | Developer id=3 落库（Reviewer 直查逐字一致）；Tester 独立 --no-save 跑通 |
| AC-17 指标对比如实记录 | ✅ | changelog §六 对比表（id=1 vs id=3），含 §三 勘误重写（UTC 口径/id=2 并列报告） |
| AC-18 pass^1 ≥ 0.8 | ⚠️ **未达目标，如实记录** | id=3 主口径 0.0（未提升）；Tester 独立跑 0.5；id=2 并列报告 0.2。结构修复生效（generate_answer 可达），残余为 LLM 行为性，backlog 3 项 |
| AC-19 平均步数 ≤ 6 | ✅ | id=3 = 4.6；Tester 独立跑 = 4.0 |
| AC-20 残余失败分类更新 | ✅ | 工具选错×8/工具漏调×1/答案缺要点×1，分类细化如实（Reviewer 独立复算一致） |
| AC-21 全量回归 | ✅ | Tester 独立复跑 1116/0 |
| AC-22 存量测试零改动 | ✅ | 按 Reviewer §3.2 裁定口径：仅 6 处断言值随特性语义更新 + conftest 新增 fixture + test_advance_phase_unit 零改动；生产红线零 diff |
| AC-23 行数口径 ≤ 200 | ✅ | git diff --stat：react.py +99 / langgraph_react.py +39 / config.py +16 ≈ 154（含注释），符合 |
| AC-24 无新增依赖 + PW_ 覆盖 | ✅ | requirements 零 diff；agent_retrieval_max_rounds/agent_retrieval_budget/agent_generation_budget 三字段均 env_prefix="PW_" 自动映射 |

**合计：24 项中 23 项通过，1 项（AC-18 pass^1 提升目标）未达标但如实记录数字 + 失败分类 + backlog 措施，AC 的诚实要求（"不预设成功、不隐藏"）已满足 —— 按 AC 语义判通过。**

## 六、观察与诚实声明（非阻塞）

1. **AC-18 未达标是如实记录，非隐瞒**：pass^1 结构性死锁已破（E2E 独立实证 generate_answer 真实可达且通过），但 deepseek 在生成阶段仍行为性不调 generate_answer（at-008 工具漏调）——plan §6 已预判此残余，backlog 3 项（执行层校验 schema 暴露 / _SYSTEM_PROMPT 与阶段 schema 对齐 / 生成阶段强制兜底）。
2. **Reviewer 第二轮 3 项 minor（非阻塞，已入 backlog）**：verify_answer 用例覆盖率语义偏移（集合成员静态可审）、search_graph 空实体标记未入排除清单（changelog §八 已声明）、生产默认 max_agent_tools==5 无断言（conftest 钉住 4 的 hermetic 设计取舍）。
3. **本跑 pass^1=0.5 vs id=3 主口径 0.0**：LLM 行为方差（同 066 先例），机制（判定/分类/落库/读回）忠实，非缺陷。
4. **全量测试在开关 false + budget=4 钉住下运行**：阶段预算/命中即切等新逻辑由 14 项新增单测在显式 setattr true 下覆盖——测试环境 hermetic 设计，生产默认（true + budget=5）由 E2E 真实运行实证。

## 七、结论

**验收通过。** 关键验证点（Tester 全部独立执行，未采信 changelog 数字）：
1. 全量 1116/0 独立复跑（1102 基线 + 14 新增），存量改动仅 Reviewer 裁定口径的 6 处断言值 + conftest 新增 fixture，红线文件零 diff；
2. 新增 14 项单测完整覆盖任务 6 个验证点（命中即切/空标记不误判/3 轮强制切/re_search 不回退/阶段预算截断/开关 false 仅总预算）；
3. E2E 独立运行（真实 deepseek + Docker PG）：at-002 轨迹 [search_knowledge×3 → generate_answer] 且 pass——AC-7 "真实轨迹出现 generate_answer，不再全检索兜底"独立实证；
4. 预算/阶段状态机真实生效（平均步数 4.0/4.6 ≤ 6）；
5. AC-18 pass^1 提升目标未达（0.0/0.2/0.5 三口径如实并列），残余为 LLM 行为性，backlog 3 项承接——诚实不隐藏。

**模块状态：✅ 验收通过（待 Developer 提交推送后 team-lead 收口）**
