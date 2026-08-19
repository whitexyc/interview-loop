# 开发计划 — Module-066: Agent 级评估体系

> Planner: 2026-08-17 | 依据：`specs/module-066-agent-evaluation/task-brief.md` + ADR-0017（已立项）
> 范围：Agent 行为评估闭环（工具调用明细落库 + 任务级评测集 + 三层指标 + 版本化落库）
> 预算：WP-A 半天 + WP-B 半天 + WP-C 1 天 + WP-D 半天 ≈ 2.5 天

## 0. Planner 已探明事实（勿重复调查）

- **落库插入点**：`agent/react.py` `react_loop` L277-296——`allowed = tool_calls[:max(0, budget - tool_count)]` 截断后，循环内 `tool.run(args, ctx)`（L291）逐个执行，`tool_result` 事件 yield 前/后即插入点；`langgraph_react.py` 有同构执行路径（`execute_tools` 节点）。
- **trace_id 来源**：main.py 中间件 L206-208 生成并挂 `request.state.trace_id` + `observability.init_request(trace_id)`（contextvar）；**ReactContext 无 trace_id 字段**——落库时从 `request.state` / observability 上下文读取（react.py 内需经参数/上下文传入，勿新增 ctx 字段改循环签名）。
- **DDL 模式**：`src/database.py` request_logs 表 L53-75 + `ensure_request_logs_table()` L80 + `init_db()` L214-221 幂等建表——tool_call_logs 照抄该模式（独立 DDL 常量 + ensure 函数 + init_db 挂接）。
- **eval_runs 模式**：`eval/golden/golden_retrieval.py` L61-70 幂等 DDL + `record_eval_run()` L218-249（git_commit + config_snapshot + scores + per_question）——agent_eval_runs 照抄。
- **配置开关**：`src/config.py` L98 `max_agent_tools = 4`；PW_ 开关模式见 `request_logs_enabled` 等既有字段（conftest autouse 钉住测试环境，对齐 056/058/060 模式）。
- **工具清单**：ToolRegistry 10 工具 + 阶段切分（module-058 ADR-0012：检索组 7 / 生成组 4，re_search 双组）——任务集 expected_tools 必须满足阶段顺序（检索工具在前、生成工具在后）。
- **存量测试基线**：**1037 passed / 0 failed**（module-065 验收数，2026-08-15；实测收集 1038）。⚠️ task-brief 事实 5 写"897/0（47 文件）"系 module-063 前旧快照——**回归基线以当前全量实测为准（1037 基线 + 新增）**，不与 897 对齐。
- **chat 路径无工具轨迹**：engine.chat 不走 ReAct 循环、无 tool_call_logs——`--mode chat` 只输出 Outcome + System（无 Trajectory 层，如实标注"无轨迹"）；`--mode agent` 三层全出。
- **环境坑（历史已知）**：deepseek 429 限流风暴时段降级链慢为外部抖动（如实记录不伪造）；Windows/CPU 本机跑全量 agent 评测耗时成本高（--sample 限制）。

## 1. WP-A：tool_call_logs 表 + 落库（半天）

- **目标**：Agent 每次实际工具调用落一行明细（trace_id / 工具名 / 参数 / 成败 / 预览 / 耗时），补 request_logs 缺工具调用明细的核心缺口。
- **涉及文件**：
  - `ai_service/src/database.py`（DDL + ensure_tool_call_logs_table + init_db 挂接）
  - `ai_service/src/config.py`（`tool_call_logs_enabled: bool = True`，PW_TOOL_CALL_LOGS 回退）
  - `ai_service/agent/react.py`（L291 `tool.run` 处落库：计时包住 run，result_ok = 执行无异常，result_preview 截断 200，args JSON 序列化）
  - `ai_service/agent/langgraph_react.py`（同构落库，实验端点顺手带）
  - `ai_service/tests/test_tool_call_logs.py`（新增单测）
- **DDL**（ADR-0017 决策 2，一字不改）：
  ```sql
  CREATE TABLE IF NOT EXISTS tool_call_logs (
      id BIGSERIAL PRIMARY KEY, trace_id VARCHAR(64) NOT NULL,
      tool_name VARCHAR(64) NOT NULL, args JSONB NOT NULL DEFAULT '{}',
      result_ok BOOLEAN NOT NULL DEFAULT TRUE,
      result_preview VARCHAR(200) NOT NULL DEFAULT '',
      duration_ms INTEGER NOT NULL DEFAULT 0,
      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP );
  ```
- **落库语义**：
  - 只记录**实际执行**的 tool_calls（预算截断掉的 LLM 提议不记——`allowed` 之外无结果）
  - 工具不存在/run 内部失败 → result_ok=false（AgentTool.run 返回空串属正常路径，result_ok=true；异常/抛出才 false）
  - 落库失败 fail-open（try/except 吞掉，不阻断循环——对齐 save_request_log 哲学）
  - 开关 false 时零开销跳过（不构造记录）
- **通过标准**：单测覆盖（成功/失败落库、开关 false 跳过、result_preview 截断、args 序列化防御、fail-open）；真实 E2E 一次 agent chat 后 `SELECT * FROM tool_call_logs` 能查到记录（含 trace_id 关联）。
- **明确不做**：不改 react_loop 循环逻辑与事件格式（红线）；不碰 request_logs 表；不改工具注册表。

## 2. WP-B：任务级评测集（半天）

- **目标**：自建静态任务集（τ-bench 式 simulated user 不做，演进方向记录于 ADR-0017 诚实边界）。
- **涉及文件**：
  - `ai_service/eval/agent_tasks.json`（新建，数据文件 30-50 条）
  - `ai_service/tests/test_agent_tasks.py`（任务集 schema/覆盖校验单测，可并入 WP-C 单测文件）
- **条目结构**（task-brief 给定，一字不改）：
  ```json
  { "id": "at-001", "task": "什么是 RRF 融合？为什么比加权好？",
    "expected_tools": ["search_knowledge", "generate_answer"],
    "answer_points": ["倒数排名", "不依赖分数量纲"] }
  ```
  - `task` 可为字符串数组（多轮追问，如 `["什么是 RRF 融合？", "为什么比加权好？"]`）
  - casual/realtime 类任务 `expected_tools` 为空数组 `[]`
- **来源与配额（30-50 条）**：
  - golden 112 题中挑多轮/复杂题改写 **20 条**（自带知识库覆盖，如 RRF/Kafka 选型/G1 GC）
  - 手工构造边界 **10-20 条**：casual_chat 直答（tools=[]）、realtime 拒绝（tools=[]）、检索不足重检（expected_tools 含 `re_search`，module-040 能力）、多轮省略句继承（数组 task，module-063 能力）、记忆路径（expected_tools 含 `recall_memory`，仅 agent 模式标注）
- **约束**：
  - 覆盖 ≥6 类路径：knowledge 单轮 / knowledge 多轮 / casual / realtime / 重检 / 记忆
  - expected_tools 序列满足阶段切分语义（检索组在前、生成组在后；re_search 双组豁免）
  - 每任务 answer_points 1-3 个关键词（知识库文本中真实可命中的词，防判定器误判）
  - 手工构造任务须先真实检索冒烟验证有对应知识（否则如实标注"知识库无覆盖"并移出达标口径）
- **通过标准**：30+ 条可用；schema 校验脚本通过（id 唯一、字段齐全、工具名 ∈ ToolRegistry 10 工具）；≥6 类路径覆盖有计数记录。

## 3. WP-C：评测脚本 + agent_eval_runs 落库（1 天）

- **目标**：`python -m eval.agent_tasks --mode chat|agent --sample 10 --pass_k 3` 跑任务集 → 三层指标 → 落库版本化。
- **涉及文件**：
  - `ai_service/eval/agent_tasks.py`（新建：判定器纯函数 + 运行器 + CLI + agent_eval_runs DDL/落库）
  - `ai_service/tests/test_agent_tasks.py`（判定器规则单测 + 脚本冒烟单测）
- **判定器（确定性，不用 LLM-as-judge，ADR-0017 决策 4 一字不改）**：
  1. **覆盖**：expected_tools 每个工具都出现于实际调用序列（顺序放宽，最后一轮前调用即算）
  2. **无多调**：实际调用都在期望集合内（豁免：`re_search` 双组设计允许生成阶段补检）
  3. **参数类型**：args 的 key 与 args_schema 必填字段一致（不判值语义）
  4. **Grounding**：result_ok 比例（降级链兜底不算错）
  - outcome pass = 工具覆盖（tools=[] 任务恒过）+ answer_points 关键词全部包含（简单子串匹配，不判语义）
- **指标输出（三层）**：
  - **Outcome**：pass^1（全量逐条判定）+ pass^3（`--sample 10` 抽样 10 条各跑 3 次、全成功才算对——τ-bench 可靠性口径）；agent 多轮路径子集单独统计
  - **Trajectory**：工具调用正确率 = 满足 1-3 规则的任务占比；平均无多调率/参数正确率可细分（`--mode agent` 有效；chat 模式输出"无轨迹"占位如实标注）
  - **System**：平均步数（tool_count）/ 平均 token（从 request_logs usage 或响应内统计）/ 端到端耗时 P50/P95
- **落库 `agent_eval_runs` 表**：幂等 DDL（对齐 eval_runs：git_commit + config_snapshot + scores + per_question JSONB 逐任务明细：task_id/判定结果/实际工具序列/tool_count/耗时/token）；`eval_type='agent_eval'` 口径
- **CLI**：`--mode chat|agent`（默认 agent）、`--sample N`（默认全量）、`--pass_k K`（默认 1）、`--limit`（冒烟）、`--no-save`（dry-run 不落库）、`--fixture`（零 LLM/DB 启发式冒烟，对齐 golden 系先例）
- **通过标准（首次跑）**：脚本跑通输出全部指标；pass^1 ≥ 0.8（agent 多轮路径 ≥ 0.7）；工具正确率 ≥ 0.9；平均步数 ≤ 6；Grounding = 1.0（降级链兜底不算错）。**不达标 → 如实输出失败案例分类报告**（工具选错/参数错/路径绕/答案缺要点），不隐藏、不改标准掩盖。
- **行数口径**：判定器 ~80 行 + 运行器/CLI ~150 行 + DDL/落库 ~40 行 ≈ 功能代码 270 行内——按项目 eval/ 脚本先例（golden_retrieval.py ~530 行）**豁免单文件 ≤200 行上限**（评测工具非生产路径），plan 已声明。

## 4. WP-D：回归 + 文档收口（半天）

- **目标**：全量绿 + 文档闭环（changelog / 三记忆 / CONTEXT.md / ADR-0017 状态）。
- **涉及文件**：
  - `ai_service/tests/test_tool_call_logs.py` + `ai_service/tests/test_agent_tasks.py`（新增单测）
  - `specs/module-066-agent-evaluation/changelog.md`（新增）
  - `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`（三记忆更新）
  - `CONTEXT.md`（补 ADR-0017 行 + module-066 索引行——**只增不删，取更全侧，先备份**，项目红线）
  - `specs/adr/0017-agent-evaluation.md`（状态 → ✅ 已实施）
- **验证点**：全量 pytest = 1037 基线 + 新增全绿、存量测试零改动（红线：request_logs/工具注册表/循环逻辑零改动）；不达标输出失败案例分类报告；真实 E2E 冒烟记录。
- **明确不做**：τ-bench simulated user、LLM judge、参数值语义判定（演进方向如实记录，不本期实现）。

## 5. 技术方案汇总

- **数据表**：
  - `tool_call_logs`（新建，ADR-0017 决策 2 结构，init_db 幂等）
  - `agent_eval_runs`（新建，对齐 eval_runs 模式，git_commit + config_snapshot + scores + per_question JSONB）
- **API 端点**：无新增（纯落库 + 离线评测脚本；前端/Java 零改动）
- **外部依赖**：无新增（复用 bge-m3/LLM 既有链路）
- **Agent 配置**：Developer ×1（全 Python 侧）+ Reviewer ×1 + Tester ×1（无前端/Java 子任务）

## 6. 风险评估

- **LLM 路径方差致 pass^1 不达标**（预期坑，ADR-0017 决策 4 已声明）：search_knowledge 直接命中不再调 search_fts 属正常——覆盖只要求期望工具出现；不达标如实分类输出，不改判定器凑数
- **deepseek 429 限流风暴**（历史观察）：降级链慢为外部抖动，如实记录，可重跑
- **评测成本**：全量 30-50 条 agent 模式（每条 4 步 × LLM + 检索）耗时/费用高——`--sample`/`--limit`/`--fixture` 控制；pass^3 只抽样 10 条（ADR-0017 诚实边界 2）
- **手工任务无知识库覆盖**：构造前真实检索冒烟验证，失败移出达标口径并如实标注
- **memory 路径污染真实记忆**：评测用固定匿名身份（或 fixture 跳过），测后清理，对齐 flywheel_smoke 先例
- **trace_id 获取**：react.py 内读 observability 上下文（勿加 ctx 字段改循环签名——红线）

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-17 | 初始版本（WP-A~D 拆解 + 文件路径 + 通过标准） | Planner |
