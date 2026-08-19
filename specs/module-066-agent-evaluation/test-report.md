# Module-066 测试报告 — Agent 级评估体系（ADR-0017）

> Tester：2026-08-17 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：✅ Pass（第 1 轮复审 4 minor + 1 建议，见 review-report.md）
> **验收结论：✅ 通过（机制全链路独立复验 / 首次跑指标未达标如实记录，AC 口径满足）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1075 passed / 0 failed（174.73s，43 warnings）** = 1037 基线 + 38 新增 |
| 新增单测 | `tests/agent/test_tool_call_logs.py` 12 项 + `tests/eval/test_agent_tasks.py` 26 项 = **38 项全绿**（独立运行 52.33s） |
| 存量测试改动 | **零改动**（git diff tests/ 仅 `conftest.py` +14 行 autouse fixture 钉住新开关，对齐 056/058/060 既有模式，验收许可） |
| 单测 mock 性 | 全 mock 不依赖真实 LLM/DB（fixture 模式本身零依赖，通过运行验证） |
| warnings | 与基线同源（Redis setex 弃用 / SAWarning 连接清理，非本模块引入） |
| 收集 ERROR | 根目录 1 项预存 ERROR：`scripts/test_models.py::test_model`（module-050 遗留，未触碰；项目惯例跑 `pytest tests/` 不受影响） |

## 二、新增单测抽查（与 changelog 声明逐项核对）

### tool_call_logs 落库（12 项，全过）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| DDL 幂等建表 | ✅ | ensure 拆分逐条执行断言（CREATE + 7 条 COMMENT = 8 条 SQL） |
| 成功落库全字段 | ✅ | INSERT SQL + 绑定参数断言（CAST(:args AS jsonb)、trace_id 来自 contextvar） |
| result_preview 截断 200 | ✅ | 500 字符 → 断言 200 |
| args 非 JSON 序列化兜底 {} | ✅ | set 入参不崩、落库 `{}` |
| 开关 false 零开销 | ✅ | 工厂未被调用（session.executed 空） |
| fail-open | ✅ | commit 抛异常不向上抛 |
| result_ok 三态 | ✅ | 成功 true / 工具不存在 false / run 抛异常 false |
| react 预算截断只记实际执行 | ✅ | budget=1：事件流不变（tool_call→tool_result→token→done）+ 只落 1 行 |
| langgraph 同构接线 | ✅ | 事件流 + 落 1 行断言 |
| trace_id 从 observability 读 | ✅ | init_request 后断言落库 trace_id |

### agent_tasks 判定器与评测脚本（26 项，全过）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| 任务集 schema（30-50 条/id 唯一/工具名合法/points 1-3） | ✅ | 实测 36 条、六类路径 17/7/3/3/3/3、id 唯一（Tester 独立加载统计一致） |
| 六类路径覆盖 | ✅ | 六类各 ≥1 断言 |
| 多轮任务存在 | ✅ | 7 条 task 为数组 |
| expected_tools 阶段顺序 | ✅ | 生成组后不得出现检索-only（re_search 豁免） |
| 判定器四规则 | ✅ | 覆盖顺序放宽 / 无多调 re_search 豁免 / 参数类型缺必填不判值 / outcome 不过度宽松 |
| 失败分类五类 | ✅ | 参数错→工具选错→工具漏调→路径绕→答案缺要点 全断言 |
| 指标聚合 | ✅ | pass^1/正确率/平均步数/P50-P95 线性插值/chat 无轨迹 None 占位 |
| fixture 全量确定性 | ✅ | 36 条 pass^1=1.0 六类全过（真实运行复核，见 §三） |
| pass_k 口径 | ✅ | k 次全成功才算过断言 |
| grounding 从 tool_call_logs 读回 | ✅ | mock 行 2/3 → 0.6667；空行 → None |
| 评测记忆清理 | ✅ | DELETE ... LIKE memory:eval-066-anon:% 断言 |
| agent_eval_runs DDL + INSERT | ✅ | 幂等 + git_commit/JSONB scores/per_question 参数断言 |
| CLI --no-save / 默认落库 | ✅ | save 调用次数断言 |

## 三、冒烟复跑（Tester 独立执行，未采信 changelog 数字）

### 3.1 fixture 模式（零 LLM/DB，36 条全量）

```
[Outcome]    pass^1: 1.0000（六类路径全 1.0）
[Trajectory] 工具正确率: 1.0000 | 无多调率: 1.0000 | 参数正确率: 1.0000
[System]     平均步数: 2.22 | 耗时 P50/P95: 1.0/3.0 ms
```

与 changelog 逐字一致（含 P50/P95 1.0/3.0ms），确定性演示管线验证通过。

### 3.2 真实 agent 模式 E2E（Tester 独立跑 `--sample 2 --no-save`，真实 deepseek + Docker PG）

```
Dataset: 2 tasks | Mode: agent | pass_k: 1 | Evaluated: 2
[Outcome]    pass^1: 0.5000
             knowledge_single   n=2   pass_rate=0.5000
[Trajectory] 工具正确率: 0.5000 | 无多调率: 0.5000 | 参数正确率: 1.0000
             Grounding: 1.0000
[System]     平均步数: 4.0 | 平均 token: 12816.0 | 耗时 P50/P95: 35719.5/51194.6 ms
失败案例分类（1 个，不隐藏）：
  工具选错     at-008 tools=['search_knowledge','extract_entities','search_knowledge','search_fts']
              expect=['search_knowledge','generate_answer']
```

- **tool_call_logs 真实落库独立查表验证**：跑后 +8 行（id 156-163，表总量 155→163），trace_id=eval-at-002-1 / eval-at-008-1 关联正确，tool_name/result_ok=true/duration_ms 2-15016ms/result_preview 全字段核验。**全表 max(length(result_preview)) = 200（截断在 DB 层成立）**。
- 三层指标全部输出、失败分类如实（at-008 调了期望外工具归"工具选错"）；Grounding=1.0 系从 tool_call_logs 读回——评测与生产观测同数据面闭环验证通过。
- **本跑 at-002 通过（pass）**：实际工具序列 search_knowledge×3 + generate_answer（15s 超时兜底）→ 覆盖规则满足 + 兜底答案含要点。与 changelog 快照（pass^1=0.0）不同属 LLM 行为方差，机制忠实记录（详见 §五观察 1）。

### 3.3 agent-lg 端点真实 HTTP E2E（uvicorn 8001 + 真实 LLM）

- POST `/ai/rag/chat/agent-lg` "什么是G1垃圾收集器？" → SSE 200，token + done 事件完整，真实答案 + 引用。**本次运行 tool_count=0（LLM 直接作答未调工具）→ 按"只记实际执行"语义 0 落库，行为正确**。
- langgraph 落库链路验证：Developer 此前 agent-lg 真实运行 trace `c7ff1c5e…`（真实 UUID）在表内 4 行（全 search_knowledge、result_ok=true、duration 1374-3301ms，与 changelog 数字吻合）；单测 test_langgraph_loop_logs_tools 覆盖同构接线。

### 3.4 数据面直查（Tester 独立 SELECT，未采信 changelog）

| 验证项 | 证据 | 结果 |
|--------|------|------|
| tool_call_logs 表存在 + init_db 幂等 | 服务启动日志 "tool_call_logs 表已就绪（module-066）"（服务 init_db 二次运行 OK） | ✓ |
| agent_eval_runs 落库 | id=1：eval_type='agent_eval'、git_commit=7241f723、per_question=10 条 JSONB、scores.pass_1=0.1 | ✓ 与 changelog pass^3 报告逐字一致 |
| 截断 200 | 全表 max(result_preview)=200 | ✓ |
| 开关默认 true | 运行环境 settings.tool_call_logs_enabled=True（无显式覆盖） | ✓ |
| 评测身份清理 | `memory:eval-066-anon:%` 残留 = 0 | ✓ |
| 首跑通过标准 | pass^1=0.5（本跑）/0.1（pass^3 落库）< 0.8 目标，**未达标**——AC 要求"不达标 → 输出失败案例分类报告不隐藏不改标准"，已满足 | ⚠️ 如实记录 |

## 四、实现抽查（与 changelog 一致）

| 项 | 抽查结果 |
|----|----------|
| DDL 结构 | `TOOL_CALL_LOGS_DDL` 8 列（id/trace_id/tool_name/args JSONB/result_ok/result_preview VARCHAR(200)/duration_ms/created_at）与 ADR-0017 决策 2 一致，init_db 挂接幂等 | ✓ |
| 共用辅助 | `execute_tool_with_log`/`record_tool_call` 单点实现，react_loop L291 与 langgraph_react execute_tools 同构接线；循环逻辑/事件格式零改动（diff 核对仅执行行替换） | ✓ |
| trace_id 来源 | `observability.get_trace_id()`（contextvar），ReactContext/循环签名零改动 | ✓ |
| conftest 钉住 | autouse fixture `tool_call_logs_enabled=False`（hermetic，存量 react 循环测试全量覆盖执行路径不触发真实 DB） | ✓ |
| 任务集 | 36 条六类路径计数与 changelog 一致；expected_tools ⊆ 注册表 10 工具 | ✓ |
| 判定器 | 四规则确定性（覆盖/无多调 re_search 豁免/参数类型不判值/Grounding 读回），chat 模式 Trajectory 置 None 输出"无轨迹" | ✓ |
| 行数预算 | 生产代码新增约 100 行（react.py +88 / database.py +39 / config.py +9 / langgraph +4）；eval 脚本 ~500 行（plan §3 已声明豁免 ≤200 上限，对齐 golden_retrieval.py 先例） | ✓ |
| py_compile | 全部改动文件通过 | ✓ |

## 五、观察与诚实声明（非阻塞）

1. **"generate_answer 结构性不可达"表述过强（本跑独立证据）**：默认配置（tool_phase_split=True）下本跑 at-002 实际**执行**了 generate_answer（id=159，15016ms，"(工具 generate_answer 执行超时)"）——循环对 LLM 调用的工具名不做 schema 暴露校验，LLM 可调用注册表内但非当前阶段 schema 的工具 → 实际是"schema 不引导调用"（可达性低）而非"结构性不可达"。与 Reviewer minor-① 同向且更强：DB 中 generate_answer 执行行（含 id=19）未必来自 PW_TOOL_PHASE_SPLIT=false 运行。判定器/数据集不受影响（忠实记录实际行为）；建议 backlog 修正归因表述。
2. **agent-lg E2E 行数**：changelog 记"3 行"，DB 实为 4 行（c7ff1c5e trace，id 36/37/38/41，其中 39/40 系并发 pass^3 评测行交错）——Reviewer minor-② 已记录，非阻塞。
3. **确定性 trace_id 复用**：eval-<task>-<k> 跨运行复用，grounding 读回可能混入历史行（当前全 ok 无失真）——Reviewer minor-④ 已记录，建议后续改随机后缀。
4. **本跑 pass^1=0.5 vs changelog 快照 0.0**：LLM 行为方差（at-002 本跑调到了 generate_answer）；机制（判定/分类/落库/读回）忠实，非缺陷。
5. **真实全量评测**：`--sample 10 --pass_k 3`（30 次 LLM 运行）已落库 id=1（pass^3=0.1）；全量 36 条 × 3 次受成本限制留后续模块——与 ADR-0017 诚实边界一致。

## 六、AC 逐条对照（40 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| 1.1-1 建表 + init_db 幂等 | ✅ | DDL 8 列与 ADR 一字一致；服务启动 init_db 二次运行 OK |
| 1.1-2 真实对话后落库可查 | ✅ | Tester 独立跑 2 任务 +8 行全字段核验（trace_id 关联） |
| 1.1-3 只记实际执行 | ✅ | 单测（budget 截断只落 1 行）+ 本跑 agent-lg 0 工具调用 0 落库 |
| 1.1-4 langgraph 同构落库 | ✅ | 单测 + c7ff1c5e 真实 UUID 4 行查表 |
| 1.1-5 开关 false 零落库 | ✅ | 单测（工厂零调用） |
| 1.1-6 preview 截断 200 | ✅ | 单测 + DB 全表 max=200 |
| 1.1-7 开关默认 true | ✅ | 代码默认 + 运行实测 True |
| 1.2-1 任务集 30-50 条 | ✅ | 36 条 |
| 1.2-2 条目结构合法 | ✅ | 单测 + Tester 独立加载 |
| 1.2-3 工具名合法 | ✅ | 单测 + 实查（4 工具 ∈ 注册表） |
| 1.2-4 六类路径覆盖 | ✅ | 17/7/3/3/3/3 |
| 1.2-5 多轮任务构造合理 | ✅ | 7 条数组 task |
| 1.2-6 手工任务检索冒烟 | ✅ | changelog 记录（RRF 倒数排名 10 篇/分数量纲 2 篇）+ Reviewer 直查 |
| 1.3-1 默认参数跑通三层指标 | ✅ | 真实运行输出全层 |
| 1.3-2 判定器确定性 | ✅ | 单测四规则逐条 |
| 1.3-3 pass^3 口径 | ✅ | 单测 + 落库 id=1（30 次真实运行） |
| 1.3-4 chat 模式无轨迹占位 | ✅ | 单测 + 真实 chat 冒烟输出"无轨迹（如实标注）" |
| 1.3-5 --fixture 零 LLM/DB | ✅ | Tester 复跑全量 |
| 1.3-6 agent_eval_runs 落库字段 | ✅ | id=1 直查（commit/快照/JSONB 明细） |
| 1.3-7 首跑通过标准 | ⚠️ 未达标如实记录 | pass^1 0.5/0.1 < 0.8；AC 要求"输出失败分类报告不改标准"已满足（工具选错分类输出） |
| 1.3-8 不达标分类报告 | ✅ | 真实运行失败分类输出 + changelog 记录 |
| 1.4-1 存量测试零改动 | ✅ | git diff tests/ 仅 conftest autouse（验收许可） |
| 1.4-2 全量 1037+新增全绿 | ✅ | Tester 独立复跑 1075/0 |
| 1.4-3 changelog 产出 | ✅ | 含达成情况 + 诚实边界 + 失败分类 |
| 1.4-4 CONTEXT.md 只增不删 | ✅ | Tester diff 核验 +2 行零删 |
| 1.4-5 ADR-0017 状态 ✅ | ✅ | 已实施 |
| 1.4-6 记忆三文件 | ✅ | project-context（module-066 + adr-017 行）/ file-index（9 行）/ activity-log（3 条） |
| §2 边界 6 项 | ✅ | 单测全过（args 兜底/工具不存在/空 expected_tools/答案缺要点/参数类型/超长特殊字符） |
| §3 异常 5 项 | ✅ | 单测全过（fail-open/降级链兜底不算错/失败按 fail 记录可重跑/--no-save 0 新行/评测身份清理 0 残留） |
| §4 代码质量 5 项 | ✅ | 行数预算/方法 ≤50 行/命名对齐（tool_call_logs↔request_logs、agent_eval_runs↔eval_runs）/py_compile 通过/无跨层 |
| §5.1 单测 38 项 | ✅ | 12 + 26 全绿，全 mock |
| §5.2 回归 | ✅ | 1075/0，存量零改动 |
| §5.3 真实冒烟 | ✅ | 真实 agent 落库查表 + agent-lg HTTP + eval 脚本 --limit/--sample 跑通（本报告 §三） |
| §6 文档 6 项 | ✅ | changelog/记忆三件套/CONTEXT/ADR 全在 |

**合计：40 项中 39 项通过，1 项（1.3-7 首跑通过标准）未达标但如实记录且 AC 要求的降级行为（失败分类报告）已满足 —— 按 AC 语义判通过，指标缺口作为 Agent 行为盲区输入下一轮。**

## 七、结论

**验收通过（机制全链路独立复验）。** 关键验证点：
1. 全量 1075/0 全绿，存量测试零改动（仅 conftest autouse 许可新增）；
2. 新增 38 项单测全部覆盖 changelog 声明点，判定器四规则/截断 200/开关/fail-open/只记实际执行逐项断言通过；
3. tool_call_logs 真实落库 Tester 独立查表验证（+8 行、trace_id 关联、全表 preview max=200）；
4. agent_eval_runs id=1 与 changelog 逐字一致（pass^3=0.1、10 条明细、commit 7241f723）；
5. fixture 模式确定性复现（36/36，P50/P95 1.0/3.0ms 逐字吻合）；
6. 首次跑指标未达标（pass^1<0.8）如实分类记录，未改判定器凑数——符合 AC 诚实要求；
7. Tester 独立发现：generate_answer "结构性不可达"表述过强（默认配置下本跑实际执行了 generate_answer，循环不校验 schema 暴露），与 Reviewer minor-① 同向并强化，建议 backlog 修正归因。

非阻塞观察：agent-lg E2E 行数 3 vs 4（minor-②，已记录）；确定性 trace_id 复用潜在 grounding 混历史行（minor-④，已记录）；本跑数字与 changelog 快照不同系 LLM 行为方差。

**模块状态：✅ 验收通过（待 Developer 提交推送后 team-lead 收口）**
