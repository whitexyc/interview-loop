# 测试报告 — Module-058: 检索链优化（prompt 顺序 + 可观测性）+ 工具治理 P1（阶段切分）

> Tester | 2026-08-13
> 验收口径：WP-A（拼标题）用户决策推迟，本模块不含；工具治理 P1（原 module-059）以 WP-E 并入
> 必读文件已读：plan.md / acceptance-criteria.md / task-brief.md / 059 brief / ADR-0012 / project-context.md

---

## 1. 结论

**✅ 验收通过（AC 全过，0 阻塞）**

| 维度 | 结论 |
|------|------|
| 全量 pytest | **780 passed / 0 failed（153.66s，43 warnings 与基线同源）**，与 changelog §5 逐字一致 |
| 新测试计数 | test_prompt_order 6 + test_tool_phase_split 18 + test_observability 16 = 40（740+40=780） |
| 实现抽查 | 阶段状态机/归组/开关回退/计时埋点/token 采集/prompt 顺序 六项全部与 changelog 一致 |
| 真实 E2E | 两循环复验通过（tool_trace 全检索组、0 生成工具、0 防御串、0 error） |
| DB 实查 | request_logs 种子 3 行逐位一致；Tester 复验新增 4 行（usage 按供应商——MAJOR-2 生产侧证明） |
| 记忆硬核查 | 三件套全部 ✅（本报告补 Tester 行） |
| 非阻塞 minor | 1 项：ADR-0012 第 5/61 行数字未同步（774/0、测试 14 项，实为 780/0、18 项）——Reviewer 第 2 轮已发现，状态行实质正确，建议主会话收口时改 |

---

## 2. 全量测试

### 2.1 独立复跑

`python -m pytest tests/ -q` → **780 passed / 0 failed（153.66s，43 warnings）**

- 与 changelog §5「780/0 = 740 基线 + 40 新增」逐字一致；与 Reviewer 独立复跑（780/0，148.11s）一致。
- 43 warnings 与基线同源（test_nli_improve sklearn 单标签 kappa 警告 + SAWarning 连接池 GC + Redis setex 弃用等，非本模块引入）。
- 存量测试零改动（git diff 确认仅 test_memory.py 1 项顺序预期按验收 §1 许可更新，见 §6.3）。

### 2.2 新测试逐文件计数与实质核对

| 文件 | 计数 | 实质核对 |
|------|------|---------|
| test_prompt_order.py | 6 | 模板区块顺序（sections < docs < query < 回答）/ query 与 docs 标签格式一字不改 / 格式化后 docs 在 query 前 / 空 sections 无占位符残留 / 历史段仍最前——均为真断言（读代码确认） |
| test_tool_phase_split.py | 18 | TestToolGroups 5（检索组恰 7 无生成工具/生成组恰 4 含 re_search/无参全量 10/10 工具元数据非空/未分组工具双阶段可见）+ TestPhaseStateMachine 9（初始 retrieval/advance_phase 单元含 re_search 不触发与不回退/开关 true 过滤/调 generate_answer 后下一轮切 generation 4/verify_answer 同样切/re_search 生成内不回退/开关 false 全量 10/预算=0 零 schema/预算耗尽兜底全程检索组）+ TestLangGraphPhaseSplit 3 + TestSystemPromptUnchanged 1 |
| test_observability.py | 16 | TestTraceAndStats 3（timing 后写覆盖/usage 按供应商求和/trace_id 互异/开关关零埋点）+ TestTraceIdInLogs 3（record.trace_id 注入/无请求空串/install 幂等）+ TestCacheCounting 1 + TestEngineChatTimings 1（六阶段全在）+ TestRequestLogs 2（字段完整/fail-open）+ TestEndpointWiring 3（record 构建/零落库/端点中间件 trace_id 32 hex）+ TestChatWithToolsUsageLabel 3（deepseek/qwen/claude 三路径供应商桶无 'llm'） |

- 测试均全 mock、asyncio.run 执行（不依赖 pytest-asyncio），conftest autouse 钉住 `tool_phase_split=False` + `request_logs_enabled=False`（对齐 module-056 模式），新测试体内显式开启验证——「存量全绿」隔离机制成立。

---

## 3. 实现抽查（与 changelog 一致性）

| 检查项 | 实现位置 | 结论 |
|--------|---------|------|
| prompt 顺序 | `agent/reflector.py:148-161` `_GENERATE_PROMPT` = `{sections} → 检索到的文档: {docs_detail} → 用户问题: {query} → 回答：` | ✅ docs 前移、query 最后；标签格式一字未改；sections 内容零漂移 |
| 阶段状态机 | `agent/react.py:141-162` `schemas_for_phase`（开关 true 按 `ctx.phase` 过滤 / false 全量）+ `advance_phase`（仅 `retrieval→generation` 单向前进，`_GENERATION_GATE_TOOLS={generate_answer, verify_answer}`）；`ReactContext.phase` 初始 "retrieval"（:93） | ✅ 判定以「已调用过生成工具」为界（非 docs 非空）；generation 内 re_search 不回退 |
| 两条循环同步 | `agent/langgraph_react.py:94` llm_call + `:158` execute_tools 复用同一公共辅助 | ✅ 只改一处 = 回归 |
| 归组 | `agent/tool_registry.py:369-414` 检索组 7 / 生成组 4（re_search 双组）；`to_llm_schemas(group=None)` 全量 10 | ✅ 与 ADR-0012 逐字一致；10 工具 name/description/args_schema 零改动（只加 group） |
| 开关回退 | `src/config.py:93` `tool_phase_split=True`（PW_TOOL_PHASE_SPLIT）、`:99` `request_logs_enabled=True`（PW_REQUEST_LOGS） | ✅ 默认 true；false 回退全量 10 / 零埋点（单测覆盖） |
| 计时埋点 | `rag/engine.py:238-370` 七阶段（intent/triage_rewrite/rerank/reflection/retrieve/generate/verify）+ `_retrieve` 内 hyde/reflection + `retriever.py:41` `_timed_channel` 并行融合主路径三通道各自计时 | ✅ 与 changelog §3.1 一致；降级串行/快路径不计时已声明 |
| 缓存计数 | `rag/engine.py:707/710` `record_cache(hit=...)`（`_retrieve_cache_key` 处） | ✅ 命中/未命中分计 |
| token 采集 | `llm/client.py:47` `_extract_usage`（OpenAI SDK usage / langchain response_metadata.token_usage / Anthropic usage 三形态）+ `:175` `_provider_label`（deepseek / ModelScope 系 self._label / claude） | ✅ 无 usage 跳过不中断；流式不采集已声明；chat_with_tools 两处改传 `_provider_label()`（MAJOR-2 修复） |
| request_logs | `src/database.py:57-71` REQUEST_LOGS_DDL（CREATE TABLE IF NOT EXISTS + COMMENT + ';' 拆分逐条执行，init_db 自愈）+ `rag/models.py` RequestLog ORM + `src/observability.py`（contextvar 上下文 + save_request_log fail-open + TraceIdFilter/install_trace_id_filter） | ✅ 对齐 048 feedback 表模式；不引入新依赖 |
| trace_id 接线 | `main.py:184-192` 中间件生成挂 request.state + 观测上下文；`:232` persist_request_log；`:420/612/684/757` chat / chat_stream / agent / agent-lg 四端点（流式 finally 落库） | ✅ 与 changelog §3.1 一致；日志格式 `[%(trace_id)s]` + install_trace_id_filter（MAJOR-1 修复） |
| 测试隔离 | `tests/conftest.py:46-70` 两个 autouse fixture 钉住 | ✅ 对齐 module-056 成熟模式 |

---

## 4. 冒烟复跑（与 Developer changelog 数字一致性抽查）

### 4.1 request_logs 表 DB 实查（真实 PG）

验证前：**3 行种子**，与 changelog §3.2 trace 样例逐位一致——

| id | endpoint | 核对结果 |
|----|----------|---------|
| 1 | probe-engine.chat | timings 9 键（intent 3885.5 / rerank 20935.0 / verify 15015.2 / generate 10197.2 / retrieve 24447.3 / reflection 1763.9 / fts 6.5 / graph 1708.8 / vector 123.7）+ usage deepseek 4561/1562——与 changelog §3.2 逐位一致 ✅ |
| 3 | agent | 含修复前 'llm' 桶（MAJOR-2 实据，保留合理，changelog 已声明）✅ |
| 4 | agent-lg | 同上 ✅ |

Tester 真实 E2E 复验新增 **4 行（id=5-8）**：

| id | endpoint | timings | usage | 结论 |
|----|----------|---------|-------|------|
| 5-7 | agent（×3） | retrieve_fts/vector/graph 全在 | **仅 deepseek 键**（8438/1367、10173/2541、10051/2977） | ✅ MAJOR-2 修复的生产侧证明（无 'llm' 桶） |
| 8 | agent-lg | 三通道全在（graph 9.1s） | **仅 deepseek 键**（11963/3175） | ✅ 同上 |

id=5-8 按「request_logs 样例/E2E 行保留为观测种子」既有策略保留。

### 4.2 两循环真实 E2E 冒烟（uvicorn 8001，PW_TOOL_PHASE_SPLIT 默认 true）

| 端点 | 请求 | tool_trace | 生成工具 | "尚未检索"防御串 | error | tool_count/budget | 答案 |
|------|------|-----------|---------|----------------|-------|-------------------|------|
| /ai/rag/chat/agent | 线程池核心参数 | search_knowledge → recall_memory → search_knowledge → search_knowledge | 0 | 0 | 0 | 4/4（预算耗尽兜底） | 1098 字，线程池参数 [6][7][8] 引用正确，sources 5 |
| /ai/rag/chat/agent-lg | G1 GC 停顿预测 | search_knowledge → search_fts → search_vector → search_graph | 0 | 0 | 0 | 4/4（预算耗尽兜底） | 1432 字，G1 停顿预测模型正确，sources 5 |

- 两循环 tool_trace 全部为检索组工具（**检索阶段 schema 不含生成工具的结构性证据**）；无"尚未检索"防御串（结构性隔离替代字符串防御生效）；done 事件 tool_count/budget/answer/sources 字段齐全。
- 与 Developer changelog §4.3 记录一致（其 agent 为 search_knowledge→recall_memory→search_fts→search_knowledge、agent-lg 为 search_knowledge→search_fts→search_vector→search_knowledge；本报告 agent-lg 第 4 个为 search_graph，LLM 选择非确定性，均为检索组工具）。
- 与 Developer 相同诚实边界：LLM 未实际调 generate_answer（信息足够后预算耗尽走兜底），阶段轮次推进由 18 项单测覆盖。
- **环境注记（如实）**：Tester 首条 agent 请求经 PowerShell Invoke-WebRequest 发送时 query 中文乱码（"Java ?????"），LLM 如实回复"无法确定问题"并列出相关主题——属请求端编码问题非服务缺陷；以 curl UTF-8 重跑后答案正常。E2E 期间产生的 7 行 `memory:127.0.0.1:session:` 会话行已清理；8001 已停服。

### 4.3 WP-B 前缀缓存抽查

- 未重跑 probe_prefix_cache.py（真实 API 调用有 token 成本且缓存已热，复跑数字必然变化），改为**逻辑自洽核查**：脚本判定条件 `c2 > c1 and c2 - c1 > 500`（cached 0 → 2944 命中）与 changelog「billed miss 3001 → 57-60（-98%）」数字自洽；单文档 637 token 未达 DeepSeek ≥1024 缓存门槛的边界声明与脚本输出结构一致；verify 口径（module-051 拆分后 LLM 只拆句、docs 不进 prompt）已由代码核实（`_VERIFY_PROMPT` 纯拆句）。
- 生成质量抽查：Tester 两循环真实 E2E 答案均为正常引用格式（[6][7][8] / [N] 引用），无退化；golden_sufficiency/golden_factcheck 属离线评测链（eval_runs），本模块未重跑全量（WP-B 只调换区块顺序，fixture 模式测试在全量 pytest 中通过，与 changelog §2.2 声明一致）。

---

## 5. 验收标准（AC）逐条对照

### §1 功能验收（WP-B prompt 顺序 + 前缀缓存）

| AC | 结果 | 依据 |
|----|------|------|
| _GENERATE_PROMPT 顺序 = sections → docs → query | ✅ 通过 | 代码实读 + test_prompt_order 6 项 |
| 存量 prompt 测试零回归（除顺序预期变更） | ✅ 通过 | 全量 780/0；git diff 确认仅 test_memory.py 1 项顺序预期按验收许可更新（§6.3） |
| verify 场景 token 对比 | ✅ 通过（如实标注边界） | changelog §2.2 记录：多文档 3001 token 同 docs 二次生成 cached 0→2944（-98%）；**verify 口径核实：LLM 只拆句 docs 不进 prompt，无前缀可复用**——收益面在 generate_answer 同 docs 重复生成（探测 3 声明）；单文档未达缓存门槛如实记录；改顺序保留（近零成本铺路） |
| 生成质量抽查无回归 | ✅ 通过 | Tester 两循环 E2E 答案引用格式正常；fixture 模式测试全量绿 |

### §2 功能验收（WP-C 可观测性）

| AC | 结果 | 依据 |
|----|------|------|
| trace_id：UUID 生成贯穿日志（chat/stream 均含），挂 request.state + 日志 extra | ✅ 通过 | 中间件（main.py:184-192）+ TraceIdFilter 注入 record.trace_id（日志格式 `[%(trace_id)s]`）+ TestTraceIdInLogs 3 项 + 端点用例断言 32 hex |
| 阶段耗时：意图/分诊改写/检索（FTS/向量/图谱各自）/rerank/反思/生成/幻觉检测 落日志 | ✅ 通过 | engine.py 七阶段 + retriever._timed_channel 三通道 + test_observability 断言六阶段齐全（engine.chat 无 triage 时的口径：triage_rewrite 仅在改写路径计时）；DB 实查 id=1 行 9 键全在 |
| token 用量：各供应商 prompt/completion（无 usage 记跳过不中断） | ✅ 通过 | _extract_usage 三形态 + _provider_label 供应商桶（MAJOR-2 修复）+ TestChatWithToolsUsageLabel 3 项 + DB 实查 id=5-8 仅 deepseek 键 |
| 缓存命中：_retrieve_cache_key 处计数 | ✅ 通过 | engine.py:707/710 + TestCacheCounting（命中/未命中各 1） |
| request_logs 表：init_db 幂等 DDL，字段含 trace_id/identity/intent/各阶段耗时/token/缓存命中/错误标记 | ✅ 通过 | REQUEST_LOGS_DDL 幂等（对齐 048）+ RequestLog ORM + DB 实查 8 行字段完整 |
| identity 对齐 048 口径（user_id 优先 client_ip 兜底） | ✅ 通过 | observability.py 构建 record 用 048 解析（端点用例断言 127.0.0.1 兜底） |
| 一条真实请求可查完整 trace；可回答成本分布与 P50/P95 | ✅ 通过 | probe_request_trace.py 样例（id=1 行全字段）+ DB 实查 + changelog §3.2 聚合查询说明 |
| 不引入新依赖 | ✅ 通过 | contextvar + 现有 logging/SQLAlchemy；requirements 无新增 |

### §3 功能验收（WP-E 工具阶段切分）

| AC | 结果 | 依据 |
|----|------|------|
| AgentTool.group + to_llm_schemas(group=None) 默认全量 10 | ✅ 通过 | tool_registry.py + TestToolGroups（test_agent_tools len==10 存量不挂，全量绿） |
| 分组口径：检索 7 / 生成 4（re_search 双组） | ✅ 通过 | 代码实读 + TestToolGroups ①②（集合级断言） |
| ctx.phase 状态机：初始 retrieval；调 generate_answer/verify_answer → 下一轮 generation | ✅ 通过 | react.py:93/152-162 + TestPhaseStateMachine 2 项（下一轮 schema = 生成组 4 断言） |
| 判定标准 = 已调用过生成工具（非 docs 非空） | ✅ 通过 | advance_phase 用 `_GENERATION_GATE_TOOLS`，与 docs 无关 |
| generation 内调 re_search 不回退 | ✅ 通过 | advance_phase 单向前进（仅 retrieval→generation）+ 手写/langgraph 各 1 项用例 |
| react_loop + langgraph_react_loop 同步改造（抽公共辅助） | ✅ 通过 | schemas_for_phase/advance_phase 双循环复用（langgraph llm_call:94 + execute_tools:158） |
| 预算=0 / 预算耗尽兜底路径逐字一致 | ✅ 通过 | 预算=0 分支（react.py:239-244）零 schema；预算耗尽 reflector 兜底；单测 2 项 + 真实 E2E 4/4 兜底 |
| 开关 PW_TOOL_PHASE_SPLIT 默认 true；false 回退全量 10 | ✅ 通过 | config.py:93 + 手写/langgraph 各 1 项用例 |
| 10 个工具 name/description/args_schema 一字不改 | ✅ 通过 | 只动暴露逻辑；TestToolGroups④ 元数据非空 + _SYSTEM_PROMPT 全 10 断言 |

### §4 验收（WP-D 收口）

| AC | 结果 | 依据 |
|----|------|------|
| token 对比记录（WP-B）+ 观测样例（WP-C 一条真实 trace） | ✅ 通过 | changelog §2.2/§3.2 + DB 实查 id=1 行逐位一致 |
| 工具治理验收：单测 + 两循环 E2E 冒烟（阶段切换正确、无防御串） | ✅ 通过 | 18 项单测 + Tester 两循环真实 E2E（§4.2）+ Developer changelog §4.3 |
| ADR-0012 状态行更新（✅ P1 已实施，注明并入 module-058） | ✅ 通过（附注 minor） | ADR-0012:5 状态行实质正确；**但行内数字仍 774/0、测试 14 项（实为 780/0、18 项）——Reviewer 第 2 轮新 minor，非阻塞，建议主会话收口时同步** |
| 面试口径更新点落盘（08 文档 2.5/2.7 + CONTEXT.md 只增不删） | ✅ 通过 | changelog §5（08 文档 2.8 节只追加）+ CONTEXT.md 追加节实读确认（git diff 全为 + 行） |

### §5 降级验收

| AC | 结果 | 依据 |
|----|------|------|
| 前缀缓存收益不可量化 → 如实标注，改顺序保留 | ✅ 通过 | 单文档未达门槛如实记录（changelog §2.2）；多文档实测 -98% |
| request_logs 落库失败 fail-open | ✅ 通过 | save_request_log try/except + TestRequestLogs②（commit 抛异常不抛） |
| 工具切分 E2E 异常 → PW_TOOL_PHASE_SPLIT=false 一键回退 | ✅ 通过 | 开关保留 + 单测 2 项（手写/langgraph） |
| 全量 pytest 740+N 全绿 | ✅ 通过 | 780/0 |

### §6 接口兼容

| AC | 结果 | 依据 |
|----|------|------|
| 默认 rrf 三通道不动；hybrid/独立 title 回退开关保留 | ✅ 通过 | git diff 无 retriever 融合逻辑改动；config 无相关开关变更 |
| to_llm_schemas() 无参行为不变（全量 10）；工具内部语义不变 | ✅ 通过 | test_agent_tools 存量全绿；10 工具零改动 |
| request_logs 建表幂等；开关 false 零埋点零落库 | ✅ 通过 | CREATE TABLE IF NOT EXISTS 幂等（DB 实查）+ 单测 2 项 |

### §7 测试验收

| AC | 结果 | 依据 |
|----|------|------|
| test_tool_phase_split.py ①-⑥ 六类覆盖 | ✅ 通过 | 18 项，覆盖①-⑥且更全（§2.2） |
| test_observability.py（trace 贯穿/计时/缓存计数/幂等落库/fail-open） | ✅ 通过 | 16 项 |
| prompt 顺序测试 + 存量零回归 | ✅ 通过 | test_prompt_order 6 项 + 全量绿 |
| conftest autouse 钉住测试环境开关；request_logs 隔离 | ✅ 通过 | conftest.py:46-70 |
| 全量 pytest 740+N 全绿（不改存量测试掩盖） | ✅ 通过 | 780/0；存量仅 test_memory.py 1 项按验收许可更新 |

### §8 文档验收（含记忆硬性约束）

| AC | 结果 | 依据 |
|----|------|------|
| changelog / review-report / test-report 三件 | ✅ 通过 | changelog §1-7 完整（含修复记录 §7）；review-report 两轮；本文件 |
| project-context.md 模块行 + 头部日期 | ✅ 通过 | 行 76（780/0、40 新增、修复记录）+ 头部「2026-08-13（module-058 完成）」 |
| agent-activity-log.md Dev/Rev/Tester 行 | ✅ 通过 | Developer 2 行 + Reviewer 2 行 + Tester 1 行（本报告追加） |
| file-index.md 新文件行 | ✅ 通过 | 6 行（observability.py / probe×2 / 新测试×3） |
| ADR-0012 状态行更新 | ✅ 通过（附注 minor） | 见 §5 第 4 项附注 |
| CONTEXT.md 只增不删 | ✅ 通过 | git diff 全为 + 行（141 行新增，含 module-058 追加节「检索链优化 + 可观测性 + 工具治理（2026-08-13 module-058 追加，只增不删）」） |
| 开工前必读 project-context.md（changelog 注明） | ✅ 通过 | changelog 头部注明已读 |

---

## 6. 独立核验记录

### 6.1 变更范围

git status 确认 module-058 变更：langgraph_react.py / react.py / reflector.py / tool_registry.py / client.py / main.py / engine.py / models.py / retriever.py / config.py / database.py / conftest.py / test_memory.py + 新建 observability.py / 新测试×3 / probe 脚本×2 / CONTEXT.md / 记忆三件套。

**先前会话遗留（非本模块，Reviewer MINOR-3 复核属实）**：router.py（docstring）、test_golden_intent.py（TestRunCompareClassifier）、specs/module-033-long-term-memory/changelog.md、untracked faithfulness.json / golden_expanded.json / .claude/config.json / module-033-loop.js / ai_service/.ua/——提交时与 module-058 分离。

### 6.2 test_memory.py 存量改动审查

唯一存量测试改动（`TestPromptZeroRegression::test_empty_sections_byte_identical_to_old`）：仅把期望字符串的区块顺序由「用户问题 → 检索到的文档」调换为「检索到的文档 → 用户问题」（注释同步更新），**无其他断言变更**——属验收 §1「除顺序预期变更外无其他漂移」许可范围。

### 6.3 诚实边界复核（与 changelog §6 一致）

- 前缀缓存收益依赖供应商策略（DeepSeek 硬盘缓存 ≥1024 token 门槛），单文档规模不可量化如实记录；verify 场景无 LLM token 前缀可复用（module-051 拆句设计结果）。
- 流式 LLM 调用不采集 token usage；engine.chat 路径无检索缓存故 cache 计数恒 0（只在 _retrieve 路径统计）；降级串行/快路径检索不单独计时。
- 422 校验失败不落库（FastAPI 在端点前抛出，persist_request_log 不可达——Reviewer 已修正 changelog 误记）。
- E2E 中 LLM 未实际调生成工具，阶段轮次推进由 18 项单测覆盖（LLM 行为非确定，无法 E2E 强制）。
- 检索阶段 LLM 若按系统提示词调 schema 外生成工具名，工具仍按名执行（registry 查找），阶段下一轮才推进——结构性隔离降低概率而非硬阻断（changelog §6.6 声明，与代码行为一致）。

---

## 7. 结论与放行

- **验收通过，0 阻塞**：全量 780/0、AC 逐条通过（1 项附注 minor：ADR-0012 数字未同步）、两循环真实 E2E 复验通过、MAJOR-1/MAJOR-2 修复生产侧实证（日志 trace_id 注入 + request_logs usage 供应商桶）、记忆三件套齐全。
- **非阻塞 minor（建议主会话收口处理）**：`specs/adr/0012-tool-governance.md` 第 5/61 行「全量 pytest 774/0」「测试 14 项」与最终口径（780/0、18 项）不一致——Reviewer 第 2 轮已发现并建议，Developer 修复轮未同步；建议改为「测试 18 项 + 两循环真实 E2E 冒烟 + 全量 pytest 780/0」。
- 观测种子：request_logs 8 行保留（id=1/3/4 Developer 种子 + id=5-8 Tester E2E 行）；E2E 会话行已清理；8001 已停服。

**模块标记 ✅ 完成**
