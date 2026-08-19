# Module-066 审查报告 — Agent 级评估体系（ADR-0017）

> Reviewer：2026-08-17 | 对照 `acceptance-criteria.md` + `plan.md` + ADR-0017 逐项核查
> 结论：**✅ Pass（4 项 minor 非阻塞记录 + 1 项建议改进）**

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest tests/ -q` | **1075 passed / 0 failed（145.36s，43 warnings）** 与 changelog 一致 |
| 根目录收集 | 独立复跑 `python -m pytest -q`（ai_service 根） | **1075 passed + 1 ERROR**（`scripts/test_models.py::test_model` fixture 'label' 收集错误，module-050 遗留未触碰）与 changelog 声明一致 |
| fixture 冒烟 | 独立复跑 `python -m eval.agent_tasks --fixture` | pass^1=1.0000、六类路径 n=17/7/3/3/3/3 全过、工具正确率 1.0、平均步数 2.22、P50/P95 1.0/2.2ms——与 changelog 一致（P95 3.0 vs 2.2ms 为 perf_counter 计时抖动，非问题） |
| tool_call_logs 落库 | 直查 DB（155 行） | 字段/截断 200/result_ok=true/duration_ms 1-15017ms 全验证通过；eval-* 与真实 UUID trace（c7ff1c5e…）并存 |
| agent_eval_runs | 直查 DB id=1 | per_question 10 条与 changelog pass^3 报告**逐字一致**：pass^3=0.1000、knowledge_single n=6 0.0 / knowledge_multi n=3 0.0 / realtime n=1 1.0、工具正确率 0.1、Grounding 1.0、9 条 fail 均"工具选错"类 |
| 种子 42 抽样 | 独立复算 `random.Random(42).sample(36,10)` | [at-002, 004, 005, 008, 015, 016, 101, 105, 107, 303] 与 DB 落库任务集逐项一致 |
| answer_points KB 覆盖 | 直查 documents LIKE | 倒数排名 10 篇 / 分数量纲 2 篇（与 changelog 逐字吻合）/ 锁升级 7 / 偏向锁 6 / Humongous 57 / 三级缓存 49 / 回表 40 / Agentic RAG 57 / PagedAttention 91 / 雪花算法 34——36 条全覆盖声明成立 |
| 评测身份清理 | 直查 documents WHERE source LIKE 'memory:eval-066-anon:%' | **0 行**（测后清理生效） |
| DDL 幂等 | 读 ensure_tool_call_logs_table + 单测 | ';' 拆分 8 条（CREATE + 7 COMMENT），对齐 feedback/request_logs 模式；init_db 挂接 ✓ |
| 存量测试零改动 | git diff tests/ | 仅 conftest.py 新增 autouse fixture（对齐 056/058/060 模式），存量断言零改动 |
| CONTEXT.md 只增不删 | diff 核查 | 补 ADR-0017 行 + module-066 索引行共 2 行，零删行 ✓ |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-066 行 + v0.66.0 + ADR-017 索引 + §5 backlog 补 generate_answer 盲区 + file-index 8 行 + [PLAN]/[CODE] 行全在（本条为 Reviewer 行） |

## 二、WP 逐项核对

### WP-A：tool_call_logs 表 + 落库 — ✅ 通过

- **DDL 一字不改**：`ai_service/src/database.py:94-112` 与 ADR-0017 决策 2 逐列比对（id/trace_id/tool_name/args JSONB/result_ok/result_preview VARCHAR(200)/duration_ms/created_at）完全一致 ✓
- **开关**：`ai_service/src/config.py:118` `tool_call_logs_enabled: bool = True`（PW_TOOL_CALL_LOGS，env_prefix PW_ 确认），默认 true 与 request_logs 同生命周期 ✓
- **只记实际执行**：`react.py:367-382` 落库位于 `allowed` 截断之后循环内；单测 `test_react_loop_logs_only_executed`（budget=1 截断 generate_answer 不落库）✓
- **result_ok 语义**：`react.py:239-250` 工具不存在/run 抛异常才 false；AgentTool.run 内部捕获（tool_registry.py:57-74 统一 catch 返回空串）→ 空结果属正常路径 result_ok=true ✓
- **preview 截断 200 / args 兜底 / fail-open / 开关零开销**：`react.py:190-220` 全实现 + 单测 4 项 ✓
- **trace_id 从 observability contextvar 读**（`react.py:210` get_trace_id()），未加 ReactContext 字段/未改循环签名 ✓
- **langgraph 同构**：`langgraph_react.py:153` 复用 execute_tool_with_log（单点实现防漂移）✓
- **真实 E2E**：DB 直查 eval trace 4 行（trace_id=eval-at-002-1 关联、截断 200、duration 1-1270ms）+ 真实 UUID trace c7ff1c5e… 4 行（agent-lg 端点）✓
- **循环逻辑红线**：git diff 确认 react.py 仅 `result = "" if tool is None else await tool.run(...)` → `execute_tool_with_log(...)` 单行替换 + 新增辅助函数；事件格式/预算截断/阶段机零改动 ✓

### WP-B：任务级评测集 — ✅ 通过

- 36 条（17+7+3+3+3+3，30-50 区间）✓；id 唯一、字段齐全、工具名 ∈ ToolRegistry 10 工具（单测断言）✓
- **≥6 类路径**：knowledge 单轮/多轮/casual/realtime/重检/记忆各 ≥1（单测 + classify_path 计数）✓
- **阶段顺序**：检索组在前生成组在后（单测 test_expected_tools_phase_order；re_search 双组豁免）——at-401/402/403 与 at-501/502/503 序列人工复核通过 ✓
- **多轮任务**：7 条 task 数组、追问为省略/指代句（"它为什么需要 RSet？"）✓
- **answer_points 真实 KB 覆盖**：DB 直查命中（见上表）✓

### WP-C：评测脚本 + agent_eval_runs 落库 — ✅ 通过（4 项 minor 见 §三）

- **判定器确定性**：四规则（覆盖顺序放宽/无多调 re_search 豁免/参数类型必填字段/outcome=覆盖+answer_points 子串）全纯函数，**零 LLM judge** ✓；单测逐规则断言 ✓
- **三层指标**：Outcome pass^k（全成功口径，单测 test_pass_k_all_runs_required）/ Trajectory 工具正确率 + 无多调率 + 参数正确率 + Grounding（tool_call_logs 读回，不可读标 None 不伪造）/ System 步数·token·P50-P95（线性插值）✓
- **chat 模式**：Trajectory 置 None 如实输出"无轨迹"；outcome 只按 answer_points（修复轮发现，避免非空 expected_tools 任务恒 fail 误报）✓
- **CLI**：--mode/--sample（种子 42）/--pass_k/--limit/--no-save/--fixture 全实现 + 单测；--fixture 独立复跑零 LLM/DB 全量通过 ✓
- **agent_eval_runs 落库**：幂等 DDL + INSERT（git_commit/config_snapshot/scores/per_question JSONB）+ eval_type='agent_eval'；DB 直查 id=1 真实落库 ✓
- **不达标如实输出**：真实冒烟 pass^1=0.0 与 pass^3=0.1 均如实记录 + 失败分类报告（工具选错 ×9），判定器/数据集未改凑数 ✓——首次跑通过标准未达（pass^1≥0.8/工具正确率≥0.9）属**系统行为盲区发现**而非实现缺陷，处理符合 ADR-0017 诚实边界 4
- **评测身份**：eval-066-anon + 测后清理（DB 直查 0 残留）✓

### WP-D：回归 + 文档收口 — ✅ 通过

- 全量 1075/0（独立复跑）+ 1 项预存收集 ERROR（module-050 遗留，未触碰）✓
- 新增 38 项单测（12+26）全 mock ✓
- changelog / CONTEXT.md（只增不删备份先行）/ ADR-0017 状态 ✅ 已实施 / 三记忆文件全 ✓

## 三、发现（非阻塞 minor，已附证据）

| # | 文件 | 位置 | 问题描述 | 建议 |
|---|------|------|----------|------|
| 1 | specs/module-066-agent-evaluation/changelog.md | §三 pass^3 结论（L158-165） | **pass^3 根因归因不精确**：changelog 称 9/9 失败同一根因"generate_answer 实际不可达"，但 DB 证据显示**落库 run（id=1，commit 7241f723）中 at-002 第 2 次尝试实际调用了 generate_answer**（tool_call_logs id=19：duration 15017ms=AgentTool 15s 超时、preview "(工具 generate_answer 执行超时)" 25 字符）——在默认阶段切分下（to_llm_schemas("retrieval") 不含 generation 组，tool_registry.py:133）该调用不可能发生，说明该 run 实际以 PW_TOOL_PHASE_SPLIT=false 执行（changelog 未记录该 run 的环境配置，A/B 表称 phase-off 实验为 --limit 2）。真实失败构成 = LLM 行为性不调 generate（9/10 首试）+ 1 次调用超时 + 检索阶段多调 recall_memory/extract_entities。"结构性不可达"结论对**默认配置**成立（--limit 2 实测），backlog 条目也正确限定"默认阶段切分下"，但 pass^3 段的"同一根因"概括越界 | 建议后续顺手修正 changelog pass^3 段：注明该 run 实际配置 + 按 DB 证据拆分失败原因（行为性不调/超时/多调） |
| 2 | 同上 | §三 agent-lg E2E（L196-198） | changelog 称 c7ff1c5e… trace "3 行"；DB 实为 **4 行**（id 36-38 + 41） | 补记为 4 次 search_knowledge（或注明查询时点差异） |
| 3 | 同上 | §三 首跑失败分类（L127） | at-001 首跑 trace `[search_knowledge, extract_entities, search_knowledge, search_knowledge]` 在 DB 中**无对应行**（eval-at-001-1 仅有 17:10:16 的 [sk, fts, sk, sk] 4 行；extract_entities 全表仅 at-004-2 一次）；at-002 trace 则与 DB 逐字吻合——疑似粘贴自落库接线前的探路 run | 修订为 DB 可核对的 trace，或注明来源 run |
| 4 | ai_service/eval/agent_tasks.py | L316 trace_id=f"eval-{id}-{k}" | **确定性 trace_id 跨运行复用**：重复跑同一任务集会生成相同 trace_id，`_load_grounding`（L290-307）按 trace_id SELECT 会混入历史运行行（实测 eval-at-002-1 的 grounding 混合了 3 次运行的 12 行——当前全 result_ok=true 无失真，但若历史运行出现 result_ok=false，后续运行 grounding 将被污染） | 建议 trace_id 加运行唯一后缀（如时间戳/递增 run 号），grounding 严格限定本次运行 |

**建议改进（不阻塞）**：`--fixture --mode chat` 组合不是零 LLM（main() 仅 agent 分支短路 fixture，chat 分支会真调 engine.chat）——docstring 宣称"零 LLM/DB"建议限定 agent 模式；另 test_cli_default_saves 在 PG 存活时会真实执行 ensure_tool_call_logs_table（幂等无害，但非完全 hermetic）。

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| 不新增不删工具 | tool_registry.py 无 diff | ✅ |
| 不改 react 循环逻辑/事件格式 | react.py 仅单行替换 + 新增辅助；langgraph 同构 | ✅ |
| 不用 LLM judge | 判定器四规则全确定性纯函数 | ✅ |
| request_logs 不动 | database.py 仅新增 TOOL_CALL_LOGS 块 | ✅ |
| 存量测试零改动 | git diff tests/ 仅 conftest 加 autouse fixture（对齐 056/058/060 先例） | ✅ |
| chat/agent 双路径落库覆盖 | react_loop + langgraph execute_tools 共用 execute_tool_with_log | ✅ |

## 五、架构与代码质量评估

- **复用而非重造**：DDL/ensure 幂等模式、fail-open 落库哲学、conftest autouse 钉开关、eval_runs 版本化落库、--fixture 假 LLM（复用 test_tool_phase_split 的 _FakeLLM 思路）——全部对齐既有先例，无新框架/新依赖（依赖审计：零新增）✓
- **单点防漂移**：execute_tool_with_log/record_tool_call 放 react.py 供两条循环共用（对齐 schemas_for_phase 模式）——工程上优于两处各写一份 ✓
- **分层**：纯 Python 侧，无跨层/反向依赖；生产路径零新增 import 环 ✓
- **行数**：agent_tasks.py 702 行 > plan §3 "~270 功能代码"估算——plan 已声明豁免单文件 ≤200 上限（对齐 golden_retrieval.py ~530 先例），评测工具非生产路径，不阻塞；剩余超量主要为 fixture 假 LLM/报告打印/防御性清理，可接受
- **安全**：SQL 全部参数化绑定（含 CAST AS jsonb）；无密钥/无敏感信息落库（result_preview 截断）；评测身份匿名 + 清理 ✓

## 六、结论

**✅ Pass（进 Tester）**。WP-A~D 全部通过标准达成（真实 pass^1 未达门槛属系统行为盲区发现，处理符合 ADR-0017 诚实边界，判定器/数据集未改凑数）；全量 1075/0 独立复跑确认；tool_call_logs / agent_eval_runs 双表 DB 直查与 changelog 数字逐字一致；红线全守。§三 4 项 minor 均为 changelog 叙述精度 / 评测 trace_id 复用设计弱点，不阻塞 Tester 验收；建议 Developer 在后续模块顺手修正 changelog pass^3 段配置与根因描述（含 generate_answer 15s 超时这一未记录的系统行为——即使 LLM 调用 generate_answer 也可能被 AgentTool 15s 超时截断，值得并入 backlog 盲区分析）。
