# Module-066 变更日志 — Agent 级评估体系（ADR-0017）

> 实施：Developer（2026-08-17）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：Agent 行为评估闭环——工具调用明细落库（tool_call_logs）+ 任务级评测集
> （agent_tasks.json 36 条）+ 三层指标（Outcome/Trajectory/System）+ 版本化落库
> （agent_eval_runs）。全量 pytest 基线 1037/0（module-065 验收数；实测收集 1038，
> plan §0 已更正 task-brief 897 旧快照）。

## 一、WP-A：tool_call_logs 表 + 落库（ADR-0017 决策 2）

**缺口**：request_logs 只记阶段耗时与 token 用量，无工具调用明细（调了哪个工具、
参数、结果、成败、耗时全都没落库）——本模块核心缺口。

**实施**：
- `ai_service/src/database.py`：`TOOL_CALL_LOGS_DDL`（ADR-0017 决策 2 结构**一字不改**：
  id/trace_id/tool_name/args JSONB/result_ok/result_preview VARCHAR(200)/duration_ms/
  created_at）+ `ensure_tool_call_logs_table()`（与 feedback/request_logs 同款 ';'
  拆分逐条执行幂等模式）+ `init_db()` 挂接。**幂等实测**：真实 PG 二次运行 OK。
- `ai_service/src/config.py`：`tool_call_logs_enabled: bool = True`（PW_TOOL_CALL_LOGS
  回退，与 request_logs 同生命周期）。
- `ai_service/agent/react.py`：新增共用辅助 `execute_tool_with_log(name, args, tool,
  ctx)` + `record_tool_call(...)`（两条 ReAct 循环共用，只改一处 = 回归，对齐
  module-058 schemas_for_phase 防漂移模式）：
  - **计时包住 run**（time.perf_counter → duration_ms 落库）
  - **result_ok 语义**：工具不存在（tools.get 返回 None）/run 抛出异常才 false；
    AgentTool.run 内部捕获失败返回空串属正常路径（result_ok=true）
  - **result_preview 截断 200**（大文档不撑爆列）；args 非 JSON 序列化（个别供应商
    防御路径）兜底 {}；trace_id 从 observability contextvar 读取（**不改 ReactContext
    字段/循环签名——红线**，无请求上下文时为空串）
  - **落库失败 fail-open**（try/except 吞掉不阻断循环，对齐 save_request_log 哲学）
  - **开关 false 零开销**（不构造记录直接返回）
- `react.py` `react_loop` L291 执行处接线：`result = "" if tool is None else
  await tool.run(args, ctx)` → `result = await execute_tool_with_log(name, args,
  tool, ctx)`（循环逻辑/事件格式/预算截断逻辑**零改动**）。
- `ai_service/agent/langgraph_react.py` `execute_tools` 节点同构接线（复用同一辅助）。
- `ai_service/tests/conftest.py`：autouse fixture 钉住测试环境 `tool_call_logs_enabled
  =False`（对齐 056/058/060 模式——存量 react 循环测试全量覆盖执行路径，不钉住会
  触发真实 DB 落库；**存量测试零改动**）。

**真实 E2E 验证（Docker PG + 真实 LLM）**：agent 模式评测冒烟后
`SELECT * FROM tool_call_logs` 查到 4 行（trace_id=eval-at-002-1 关联、tool_name
search_knowledge/search_fts/search_vector、result_ok=true、duration_ms 1-1270ms、
长文档 result_preview 截断 200）——落库链路全字段验证通过。

**通过标准达成**：单测 12 项全绿（成功/失败落库、开关 false 跳过、preview 截断、
args 非法 JSON 防御、fail-open、截断不落库、react/langgraph 接线、trace_id
contextvar）；真实 E2E 查表通过。**未达成**：无。

## 二、WP-B：任务级评测集（ADR-0017 决策 3）

**产出**：`ai_service/eval/agent_tasks.json` **36 条**（30-50 区间内），条目结构
按 task-brief 给定一字不改：`{"id", "task"（字符串或数组=多轮追问）, "expected_tools",
"answer_points"（1-3 个）}`。

**来源与六类路径覆盖（36 条 = 全路径计数）**：

| 路径 | 条数 | 说明 |
|------|------|------|
| knowledge 单轮 | 17 | golden 112 题改写（G1/CMS/线程池/synchronized/MoE/RAG/Kafka/Redis/Humongous/Spring 循环依赖/覆盖索引/redo log/缓存穿透/雪花/Agentic RAG/TIME_WAIT/RRF） |
| knowledge 多轮 | 7 | task 为数组（省略句继承语义，module-063 能力）：RSet/“为什么需要”/CAP 权衡/零拷贝异同/AT vs TCC/双亲委派打破/PagedAttention KV Cache/微服务 vs 单体 |
| casual | 3 | expected_tools=[]（你好呀/介绍自己/你会做什么） |
| realtime | 3 | expected_tools=[]（几点/天气/几号，answer_points 取"实时"——chat 模式固定回复"实时数据查询功能正在开发中"必含） |
| 重检 | 3 | expected_tools 含 `re_search`（module-040 能力）：口语化提问（大白话 G1/AOF 是干嘛的/靠 log 恢复） |
| 记忆 | 3 | expected_tools 含 `recall_memory`（仅 agent 模式标注）：固定匿名身份 eval-066-anon |

**约束核验（数据 + 单测双保险）**：
- expected_tools 全部 ∈ ToolRegistry 10 工具；阶段顺序（检索组在前、生成组在后、
  re_search 双组豁免）单测断言。
- **answer_points 知识库真实覆盖冒烟**（计划要求手工任务先检索验证）：RRF 题
  "倒数排名"（KB 10 篇）/"分数量纲"（2 篇）实测命中（module-053 changelog 术语），
  G1/Redis AOF/MySQL redo log/Agentic RAG 检索冒烟全部命中对应文档——36 条全部
  在达标口径内，无"知识库无覆盖"移出项。

**通过标准达成**：36 条可用（30+）；schema 校验单测通过（id 唯一/字段齐全/工具名
合法）；六类路径计数记录如上。**未达成**：无。

## 三、WP-C：评测脚本 + agent_eval_runs 落库（ADR-0017 决策 1/4）

**产出**：`ai_service/eval/agent_tasks.py`（约 500 行含 DDL/落库/报告——plan §3
已声明豁免单文件 ≤200 行上限，评测工具非生产路径，对齐 golden_retrieval.py ~530
行先例）。

**判定器（确定性，不用 LLM-as-judge，ADR-0017 决策 4 一字不改）**：
1. **覆盖** `check_coverage`：期望每个工具都出现于实际调用序列（顺序放宽，
   最后一轮前调用即算）；tools=[] 任务恒过
2. **无多调** `check_no_extra`：实际调用都在期望集合内（豁免：re_search 双组
   设计允许生成阶段补检）
3. **参数类型** `check_args_type`：args 的 key 与 args_schema 必填字段一致
   （不判值语义——诚实边界 3）
4. **Grounding**：result_ok 比例（从 tool_call_logs 落库读回，ADR 决策 1 数据
   来源即该表；不可读/无行 → None 如实标注；降级链兜底不算错）
- outcome pass = 工具覆盖 + answer_points 关键词全部包含（简单子串匹配，不判
  语义）；**chat 模式无工具层** → Trajectory 置 None、outcome 只按 answer_points
  （Trajectory 报告如实输出"无轨迹（--mode chat 无工具调用明细，如实标注）"）

**三层指标**：
- **Outcome**：pass^1（全量逐条）+ pass^k（`--pass_k K`：每任务 K 次独立尝试、
  全成功才算过，τ-bench 可靠性口径）；agent 多轮路径 per_path 子集单独统计
- **Trajectory**：工具调用正确率（1-3 规则同过占比）+ 无多调率/参数正确率细分
  （agent 模式；chat 模式占位）
- **System**：平均步数（tool_count）/ 平均 token（observability usage 上下文
  采集）/ 端到端耗时 P50-P95（线性插值百分位）

**CLI**：`--mode chat|agent`（默认 agent）/ `--sample N`（固定种子 42 抽样可复现）/
`--pass_k K`（默认 1）/ `--limit N`（冒烟）/ `--no-save`（dry-run 不落库）/
`--fixture`（零 LLM/DB 假 LLM 回放：按期望工具序列回放 tool_calls（参数取
args_schema 必填字段占位）+ 假工具固定文本 + 最后一轮答案含全部 answer_points，
仅演示管线不落库）。评测用固定匿名身份 `eval-066-anon`，真实 agent 模式结束
best-effort 清理该身份记忆残留（react_loop 直连不写记忆，防御性清理）。

**落库 `agent_eval_runs` 表**：幂等 DDL（对齐 eval_runs：git_commit +
config_snapshot + scores + per_question JSONB 逐任务明细：task_id/判定结果/
实际工具序列/tool_count/耗时/token）+ `eval_type='agent_eval'`；`--no-save`/
`--fixture` 不落库（对齐 golden_multi_turn 先例）。

**运行验证**：
- **fixture 冒烟（36 条全量）**：pass^1=1.0000（六类路径全过，确定性演示管线）、
  工具正确率 1.0、平均步数 2.22、耗时 P50/P95 1.0/3.0 ms——不依赖 LLM/DB。
- **真实 agent 冒烟（--limit 2 --no-save，真实 deepseek + DB）**：

  ```
  [Outcome]    pass^1: 0.0000（knowledge_single n=2 pass_rate=0.0000）
  [Trajectory] 工具正确率: 0.0000 | 无多调率: 0.0000 | 参数正确率: 1.0000
               Grounding: 1.0000
  [System]     平均步数: 4.0 | 平均 token: 9492.0 | 耗时 P50/P95: 21810.5/30620.1 ms
  失败案例分类（2 个，不隐藏）：
    工具选错  at-001 tools=[search_knowledge, extract_entities, search_knowledge, search_knowledge]
    工具选错  at-002 tools=[search_knowledge, search_fts, search_knowledge, search_vector]
  ```
- **chat 模式冒烟（--mode chat --limit 3 --no-save，真实 deepseek + DB）**：

  ```
  [Outcome]    pass^1: 0.6667（knowledge_single n=3 pass_rate=0.6667）
  [Trajectory] 无轨迹（--mode chat 无工具调用明细，如实标注）
  [System]     平均步数: 0.0 | 平均 token: 8711.0 | 耗时 P50/P95: 37650.0/47401.5 ms
  失败案例分类（1 个，不隐藏）：答案缺要点 at-003 tools=[]（线程池答案缺
  "ThreadPoolExecutor"/"任务队列"任一关键词）
  ```
  2/3 通过（at-001 G1 / at-002 CMS 答案命中要点）；at-003 答案缺要点属真实信号
  （chat 流水线答案措辞不含评测关键词）。Trajectory 占位输出符合预期。

**通过标准（首次跑）评估——未达标，如实记录**：

| 标准 | 目标 | 实测（真实 agent 冒烟） | 达成 |
|------|------|--------------------------|------|
| pass^1 | ≥ 0.8（多轮 ≥ 0.7） | 0.0 | ❌ |
| 工具正确率 | ≥ 0.9 | 0.0 | ❌ |
| 平均步数 | ≤ 6 | 4.0 | ✅ |
| Grounding | = 1.0 | 1.0（tool_call_logs 读回） | ✅ |

**根因（Agent 行为盲区发现，判定器/数据集不改）——A/B 双配置实测**：

| 配置 | generate_answer 可达性 | 实测（--limit 2） |
|------|------------------------|-------------------|
| 默认 tool_phase_split=true | **结构性不可达**（检索阶段 schema 只含检索组 7，生成工具从未暴露 → 状态机永远停在检索阶段） | 4 轮全检索（search_knowledge×2-3 + extract_entities/search_fts/search_vector）→ 预算耗尽兜底；pass^1=0.0 / 工具正确率 0.0 |
| PW_TOOL_PHASE_SPLIT=false（全量 10 schema） | 可达但 **LLM 行为性不调用** | 4 轮仍全检索（search_knowledge×2-3 + search_fts/search_graph）→ 预算耗尽兜底；pass^1=0.0 / 工具正确率 0.0 |

结论：**generate_answer 在真实 agent 循环里实际不可达**——不是评测集或判定器
问题，而是系统行为（module-058 阶段切分设计 + LLM 路径选择共同导致）：期望序列
含生成工具的任务系统性判 fail（分类"工具选错"= 调了期望外工具）。module-058
自身 E2E 冒烟已记录同款行为（"全检索组 0 生成工具…预算耗尽兜底真实答案"）——
本次评测把它量化成了可复现的 **Agent 行为盲区**（回答实际由预算耗尽兜底生成，
工具轨迹层与"该调的调了"期望不符）。**该发现已写入 project-context §5 backlog
（需产品决策：改阶段判定语义 / prompt 引导调生成工具 / 评测期望序列按实测行为
修正）**。真实全量评测待后续模块补跑（--sample 10 --pass_k 3 命令就绪）。

## 四、WP-D：回归 + 文档收口

**测试**：
- 新增单测 **38 项**：`tests/agent/test_tool_call_logs.py` 12 项（DDL 幂等/成功
  落库字段/截断 200/args 兜底/开关 false 零开销/fail-open/result_ok 三态/
  react 预算截断只记实际执行/langgraph 同构/trace_id contextvar）+ `tests/eval/
  test_agent_tasks.py` 26 项（数据集 schema/六类路径/阶段顺序/判定器四规则/
  outcome 不过度宽松/失败分类/指标聚合/percentile/fixture 全量确定性/chat 无
  轨迹/单任务失败记录不中断/grounding 读回/记忆清理/agent_eval_runs DDL+INSERT/
  CLI no-save 与默认落库）。
- 全量 pytest：**1075 passed / 0 failed**（167.22s；= 1037 基线 + 38 新增，存量
  测试零改动——唯一非新增文件为 conftest.py 加 autouse 钉住新开关，对齐
  056/058/060 既有模式）+ **1 项预存收集 ERROR**：`scripts/test_models.py::
  test_model`（`def test_model(label)` 参数被 pytest 当 fixture，module-050 既有
  遗留，module-065 Reviewer minor-③ 已记录"不动"；本模块未触碰该文件）。
- 单测全 mock 不依赖真实 LLM/DB（fixture 例外，本身零依赖）。

**真实环境冒烟**：
- init_db 幂等二次运行 OK（tool_call_logs 建表）。
- tool_call_logs 真实落库 4 行查表验证（§一）。
- `python -m eval.agent_tasks --fixture` 36 条全量确定性通过（§三）。
- `python -m eval.agent_tasks --limit 2 --no-save` 真实 agent 模式跑通输出全部
  三层指标 + 失败分类（§三）。
- `python -m eval.agent_tasks --mode chat --limit 3 --no-save` 真实 chat 模式
  跑通（§三）。
- `PW_TOOL_PHASE_SPLIT=false python -m eval.agent_tasks --limit 2 --no-save`
  阶段切分 A/B 对照（§三）。
- **agent-lg 端点真实 HTTP E2E**（uvicorn 8001 真实服务 + 真实 LLM）：POST
  /ai/rag/chat/agent-lg "什么是G1垃圾收集器？" → SSE 200（tool_call ×3
  search_knowledge + tool_result + done）→ `tool_call_logs` 查到 3 行同
  trace_id（c7ff1c5e…，真实 UUID 非 eval 前缀），duration_ms 1374-3301ms、
  result_ok=true——langgraph 端点同构落库验证通过。
- **真实 pass^3 抽样**（`--sample 10 --pass_k 3`，固定种子 42 抽样 10 条 × 3
  次独立尝试 = 30 次真实 LLM 运行，已落库）：

  ```
  Dataset: 10 tasks | Mode: agent | pass_k: 3 | Evaluated: 10
  [Outcome]    pass^3: 0.1000
               knowledge_multi  n=3   pass_rate=0.0000
               knowledge_single n=6   pass_rate=0.0000
               realtime         n=1   pass_rate=1.0000
  [Trajectory] 工具正确率: 0.1000 | 无多调率: 0.1000 | 参数正确率: 1.0000
               Grounding: 1.0000
  [System]     平均步数: 4.6 | 平均 token: 11851.0 | 耗时 P50/P95: 25608.0/44745.8 ms
  失败案例分类（9 个，不隐藏）：工具选错 ×9
  Saved to agent_eval_runs (id=1, commit=7241f723)
  ```
  仅 realtime 任务（at-303，tools=[] 恒过覆盖 + 答案含"实时"）通过；
  知识类任务 9/9 判 fail——同一根因（generate_answer 实际不可达 + 检索阶段
  调了 recall_memory/extract_entities 等期望外工具）。**pass^3 口径机制验证
  通过（k 次全成功才算过、抽样、落库全链路）**；**agent_eval_runs 真实落库
  验证通过（id=1，per_question 10 条明细 JSONB）**。数字为真实行为快照，
  非达标结果——如实记录，下一轮优化输入。

**文档**：
- `specs/module-066-agent-evaluation/changelog.md`（本文件）。
- `CONTEXT.md`：补 ADR-0017 行 + module-066 索引行（**只增不删**，先备份
  %TEMP%\CONTEXT.md.bak-module066）。
- `specs/adr/0017-agent-evaluation.md`：状态 → **✅ 已实施**。
- 三记忆文件：project-context.md（module-066 行 + 头部日期 + ADR-017 索引行 +
  §5 迭代状态 + backlog 补 generate_answer 盲区）、file-index.md（8 新文件行 +
  module-066 模块产出行）、agent-activity-log.md（Developer [CODE] 行）。

**通过标准达成**：全量 1037 基线 + 新增全绿 ✅、存量测试零改动 ✅（conftest
autouse 为验收许可的明确新增）、changelog/记忆/CONTEXT/ADR 状态 ✅。**未达成**：
真实 agent 模式首次跑 pass^1/工具正确率未达门槛（§三如实记录，属 Agent 行为
盲区发现而非实现缺陷）。

## 五、实现决策与取舍

1. **共用辅助函数放 react.py**（关键决策）：execute_tool_with_log + record_
   tool_call 单点实现，langgraph 复用——两条循环只改一处 = 回归（对齐 module-058
   schemas_for_phase 先例），循环逻辑本身零改动（红线）。
2. **落库同步 await 而非 fire-and-forget**：本地 PG 单行插入 ~1-3ms，评测/生产
   可接受；同步保证单测可确定性断言、事件顺序不变。DB 断连 fail-open（asyncpg
   连接拒绝快速失败，不 hang）。
3. **eval 脚本 trace_id 自设 + grounding 从 tool_call_logs 读回**（决策）：ADR
   决策 1 的 Trajectory 数据来源就是 tool_call_logs 表——评测与生产观测共用
   同一数据面，首跑即真实验证了落库链路（Grounding 1.0 就是读回结果）。
4. **fixture 模式 = 假 LLM 回放期望序列**：不新造框架，复用 test_tool_phase_split
   的 _FakeLLM 模式（工具参数按 args_schema 必填字段生成，判定器规则 3 可过），
   确定性演示管线且零 LLM/DB 依赖。
5. **chat 模式 outcome 不含工具覆盖**（修复轮发现）：chat 无工具层，若套用
   覆盖规则则非空 expected_tools 任务恒 fail（误报）——Trajectory 层置 None +
   outcome 只按 answer_points（计划 §0"chat 只出 Outcome+System"语义对齐）。
6. **eval 真实模式启动幂等 ensure 建表**（修复轮发现）：脚本独立运行（无服务端
   init_db）时首任务落库可能打到未建的表（fail-open 吞掉 → 首任务行丢失）——
   真实模式启动时先 ensure_tool_call_logs_table（幂等）。

## 六、已知边界与诚实声明

- **generate_answer 循环内不可达**（本模块最大发现）：默认阶段切分下 agent 模式
  的期望序列含生成工具的任务系统性判 fail——这是真实行为盲区，不是评测缺陷；
  判定器/数据集不改（计划明确"不达标如实分类输出，不改判定器凑数"）。
- pass^3 真实口径已跑（--sample 10 --pass_k 3 = 30 次 LLM 运行 + 落库 id=1，
  pass^3=0.1——机制全链路验证，数字为盲区快照）；受成本限制每次只抽样 10 条
  （ADR-0017 诚实边界 2），全量 36 条 × 3 次留后续模块。
- 任务集 36 条人工构造，非 τ-bench 式 simulated user（ADR-0017 诚实边界 1）——
  多轮对话动态性覆盖有限，演进方向已记录。
- 工具调用正确率不判参数"值"的语义（诚实边界 3）：search_knowledge(query="RRF")
  与 query="rff" 语义等价但字符串不同，判不了。
- 重检路径任务在真实模式依赖 LLM 判断是否 re_search（口语化提问触发），首检
  充分时 LLM 可能不调 → 覆盖失败属真实信号非 bug。
- 记忆路径仅 agent 模式标注；评测身份固定匿名 + 防御性清理，不污染真实记忆。
- 真实冒烟受 LLM 外部抖动影响（deepseek 429 时段降级链慢），可重跑。

## 七、交付物

- `ai_service/src/database.py`（+TOOL_CALL_LOGS_DDL/ensure/init_db 挂接）
- `ai_service/src/config.py`（+tool_call_logs_enabled）
- `ai_service/agent/react.py`（+execute_tool_with_log/record_tool_call + 接线）
- `ai_service/agent/langgraph_react.py`（execute_tools 同构接线）
- `ai_service/tests/conftest.py`（+autouse 钉住开关）
- `ai_service/eval/agent_tasks.json`（36 条任务集）
- `ai_service/eval/agent_tasks.py`（三层指标评测脚本 + agent_eval_runs 落库）
- `ai_service/tests/agent/test_tool_call_logs.py`（12 项）
- `ai_service/tests/eval/test_agent_tasks.py`（26 项）
- `specs/module-066-agent-evaluation/`：changelog（本文件）/ plan / acceptance-criteria
  （review-report / test-report 由 Reviewer/Tester 产出）
- `CONTEXT.md`（ADR-0017 行 + module-066 行，只增不删）
- `specs/adr/0017-agent-evaluation.md`（状态 ✅ 已实施）
- 三记忆文件（project-context / file-index / agent-activity-log）

## 八、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始实现（WP-A~D） | Developer |
