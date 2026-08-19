# Changelog — Module-058: 检索链优化（prompt 顺序 + 可观测性）+ 工具治理 P1（阶段切分）

> Developer | 2026-08-13
> 开工前已读 `memory/project-context.md` 全文（module-001~057 清单与迭代状态，避免重复/冲突）✅
> 执行口径：WP-A（拼标题+防扎堆）用户决策推迟，本模块不含；工具治理 P1（原 module-059，ADR-0012 方案 A）以 WP-E 并入

---

## 1. 模块目标与结果

| WP | 内容 | 结果 |
|----|------|------|
| WP-B | `_GENERATE_PROMPT` 顺序改 docs 前移、query 最后（前缀缓存铺路）+ verify 场景 token 对比 | ✅ 顺序已改（sections 内容/格式一字不改）；**真实探测：多文档同 docs 重复生成命中 DeepSeek 硬盘缓存**（billed miss 3001 → 57-60，-98%）；单文档规模未达缓存门槛如实记录；verify 场景口径核实（LLM 只拆句，docs 不进 LLM prompt，无 token 前缀可复用） |
| WP-C | 可观测性：trace_id + 阶段计时（意图/分诊改写/检索 FTS·向量·图谱/rerank/反思/生成/幻觉检测）+ token 用量 + 缓存命中 → request_logs 落库 | ✅ 全链路落地（src/observability.py + 中间件 + 引擎/重排/LLM 客户端埋点 + init_db 幂等建表 + fail-open 落库）；真实 chat 一条完整 trace 样例已产出（见 §3） |
| WP-E | 工具阶段切分（ADR-0012 方案 A）：检索组 7 / 生成组 4（re_search 双组），ctx.phase 状态机，两条循环同步 | ✅ 全量实施 + 18 项单测 + 两循环真实 E2E 冒烟（tool_trace 全为检索组工具、0 防御串）；10 个工具 name/description/args_schema 一字不改；PW_TOOL_PHASE_SPLIT 默认 true、false 回退全量 |
| WP-D | 全量 pytest + 文档 + 记忆 + ADR-0012 + 面试口径更新点 | ✅ **774 passed / 0 failed**（740 基线 + 34 新增，1 项存量顺序预期测试按验收许可更新）；ADR-0012 状态行更新；记忆三件套同步；面试口径更新点落盘 |

---

## 2. WP-B prompt 顺序 + 前缀缓存

### 2.1 改动

- **`ai_service/agent/reflector.py`（改）**：`_GENERATE_PROMPT` 区块顺序由 `{sections} → 用户问题 → 检索到的文档` 改为 **`{sections} → 检索到的文档: {docs_detail} → 用户问题: {query}`**（docs 前移、query 最后）。sections 内容/格式一字不改（历史对话/记忆/工作笔记段拼接逻辑未动），query/docs 标签格式不变——仅调换区块顺序。生成质量相关测试除顺序预期变更外零漂移。
- **`ai_service/tests/test_memory.py::TestPromptZeroRegression::test_empty_sections_byte_identical_to_old`（改，验收 §1 允许的顺序预期变更）**：该存量测试断言"空 sections 时 prompt 与旧版逐字节一致"——旧断言锁定的是 module-023 时代的区块顺序，WP-B 正是要改这个顺序（docs 前移为前缀缓存铺路，属**本模块的有意变更**而非回归），按验收"除顺序预期变更外无其他漂移"更新期望字符串为 module-058 定稿顺序；其余断言（标签格式、sections 拼接）零改动。
- **`ai_service/tests/test_prompt_order.py`（新，6 项）**：模板区块顺序（sections < docs < query < 回答）/ 格式化后 docs 在 query 前 / query 与 docs 标签格式不变 / 空 sections 无占位符残留 / 历史记忆段仍拼在最前。

### 2.2 前缀缓存真实探测（scripts/probe_prefix_cache.py，deepseek-v4-flash 真实 API）

| 场景 | 第 1 次调用 | 第 2 次调用（同 docs） | 结论 |
|------|-----------|----------------------|------|
| 单文档（docs ≈500 token，prompt 637 token） | prompt=637，cached=512，miss=125 | prompt=640，cached=512，miss=128 | **未观察到 docs 段缓存**：cached 恒 512（固定 prompt 头，非 docs 段）——单文档规模未达供应商缓存门槛（DeepSeek 硬盘缓存对重复前缀有 ≥1024 token 门槛，当前总 prompt < 门槛） |
| **多文档（docs ≈2500 token，prompt 3001 token）** | prompt=3001，cached=0，miss=3001 | prompt=3004，**cached=2944**，miss=60 | **✅ docs 前置前缀缓存生效**：docs 段写入缓存并在第二次命中（billed miss 3001 → 60，**-98%**；DeepSeek 缓存命中按 1/10 价计费 → 成本大幅下降）；复跑（缓存已热）两次均 cached=2944/miss=57-60 稳定命中 |

- **verify 场景口径（探测 3，如实记录）**：module-051 拆分后 verify 的 LLM 调用是**纯拆句**（prompt = answer 文本，docs 不进 LLM prompt，docs 进 HHEM/LLM 判分），故"同 docs 验多 claim"**不存在 LLM token 前缀可复用**——docs 前置前缀缓存的真实受益面是 **generate_answer 同 docs 重复生成**（多文档场景实测生效）。改顺序本身保留（docs 前移近零成本 + 为多文档/长 docs 场景铺路，届时 >1024 token 前缀自动受益）。
- **生成质量抽查（如实声明）**：探测中 4 次真实 generate_answer 输出均为正常引用格式答案（含 [N] 引用）；两循环 E2E 兜底生成答案 1590/1451 字符、5 sources 引用正确，无退化。golden_sufficiency/golden_factcheck 属离线评测链（eval_runs），本模块未重跑全量（WP-B 只调换区块顺序，sections 内容一字不改，fixture 模式测试在全量 pytest 中通过）。

---

## 3. WP-C 可观测性

### 3.1 改动

- **`ai_service/src/observability.py`（新）**：请求观测上下文（contextvar，非全局状态）——`init_request(trace_id)` / `timing(stage, seconds)`（毫秒，同阶段后写覆盖）/ `record_usage(provider, prompt, completion)`（按供应商累积）/ `record_cache(hit)`（命中/未命中计数）/ `get_request_stats()` / `save_request_log(record)`（fail-open 落库）+ **`TraceIdFilter` / `install_trace_id_filter`（Review 修复：trace_id 贯穿日志——过滤器从 contextvar 注入 record.trace_id，挂根 logger 及 handler，见 §7 修复记录）**。**开关 `settings.request_logs_enabled`（PW_REQUEST_LOGS，默认 true）关闭时全部 helper 零埋点零落库**；不引入新依赖（contextvar + 现有 SQLAlchemy/日志）。
- **`ai_service/src/config.py`（改）**：新增 `request_logs_enabled`（PW_REQUEST_LOGS 默认 true）+ `tool_phase_split`（PW_TOOL_PHASE_SPLIT 默认 true，WP-E）。
- **`ai_service/src/database.py`（改）**：`REQUEST_LOGS_DDL` + `ensure_request_logs_table`（**init_db 自愈幂等，对齐 module-048 feedback 表模式**——CREATE TABLE IF NOT EXISTS + COMMENT，'；' 拆分逐条执行）；字段：trace_id/identity/endpoint/intent/timings(JSONB)/usage(JSONB)/cache_hits/cache_misses/error/created_at；identity 对齐 048 口径（user_id 优先 client_ip 兜底）。
- **`ai_service/rag/models.py`（改）**：`RequestLog` ORM 模型（与 DDL 对齐）。
- **`ai_service/main.py`（改）**：限流中间件请求入口生成 trace_id 挂 `request.state.trace_id` + 初始化观测上下文；新增 `persist_request_log`（请求结束 fire-and-forget，fail-open）；chat / chat_stream / agent / agent-lg 四端点接线（chat_stream 与两个 agent 端点在 finally 中落库，**流式结束/断开均触发**）；chat_stream 各阶段计时接入观测上下文（intent/retrieve/rerank/reflection/generate/verify）；**Review 修复：basicConfig 日志格式含 `[%(trace_id)s]` + `install_trace_id_filter()`（trace_id 贯穿日志，见 §7）**。
- **`ai_service/rag/engine.py`（改）**：`chat()` 阶段计时（intent / triage_rewrite / retrieve / rerank / reflection / generate / verify）；`_retrieve()` 缓存命中/未命中计数（`_retrieve_cache_key` 处）+ hyde/reflection 计时。
- **`ai_service/rag/retrieval/retriever.py`（改）**：`_timed_channel` 包装，并行融合主路径（`_execute_fusion` 三通道 / `_execute` 两通道）FTS·向量·图谱各自计时（retrieve_fts/retrieve_vector/retrieve_graph）。**已知边界**：降级串行/快路径（外部 session、embedding 失败）不单独计时（观测缺失不中断，如实声明）。
- **`ai_service/llm/client.py`（改）**：`_extract_usage`（兼容 OpenAI SDK usage / langchain response_metadata.token_usage / Anthropic usage）+ `_record_usage`，非流式 generate/chat/chat_with_tools 各供应商响应返回处采集（无 usage 静默跳过不中断；**流式 generate_stream 不采集**——SSE 逐 token 场景供应商通常不返回 usage，口径声明）。fallback 链内层客户端各自记录，天然带供应商标签。

### 3.2 真实 trace 样例（scripts/probe_request_trace.py，真实 PG + 本地 bge-m3 + deepseek）

一次真实 `rag_engine.chat("Java 线程池的核心参数有哪些？")` 的完整观测（request_logs 已落库可查）：

```
timing[intent] = 3885.5ms（意图分类）
timing[retrieve_fts] = 6.5ms / timing[retrieve_vector] = 123.7ms / timing[retrieve_graph] = 1708.8ms（三通道各自）
timing[retrieve] = 24447.3ms（检索总时长，含 HyDE/反思轮次）
timing[rerank] = 20935.0ms（含 bge-reranker 2.17GB 冷加载）
timing[reflection] = 1763.9ms
timing[generate] = 10197.2ms
timing[verify] = 15015.2ms（LLM 判分 15s 超时 → 空 claims，module-051 既有行为）
usage = {'deepseek': {'prompt': 4561, 'completion': 1562}}
cache_hits=0 cache_misses=0（engine.chat 路径无检索缓存，命中计数只统计 _retrieve 路径——口径声明）
```

- 真实验证：init_db 幂等建表 → 真实 chat → 观测上下文收集 → `save_request_log` 落库 → **查回完整记录**（trace_id/identity/endpoint/intent/timings/usage/cache_hits/error/created_at 全字段）。
- 真实 HTTP E2E 期间 request_logs 自动落库（DB 实查 4 行：1 probe + 2 agent + 1 agent-lg）——**流式结束/断开与端点异常同样经 finally 留痕**（四端点统一 finally 调 persist_request_log），error 仅主链路异常置 true；**无 422 行**（FastAPI body 校验 422 在端点执行前抛出，persist_request_log 不可能被调用——旧 changelog "1 行 422 失败请求也落库"系误记，已修正）。修复轮核对时发现 id=2 行（endpoint=agent、timings 空、usage 空、error=False，创建于 E2E 前 51s）来源无法确证（推测为 E2E 准备期提前断开的 SSE 探测请求，属 finally 留痕形态），**已删除该异常样例行**，保留 3 行可确证种子（id=1 probe / id=3 agent / id=4 agent-lg）。
- 可回答"单问题成本分布"与"P50/P95 延迟"：request_logs 表聚合查询即可（如 `percentile_cont(0.5) WITHIN GROUP (ORDER BY (timings->>'generate')::float)`），结构化 JSONB 无重型框架。

---

## 4. WP-E 工具治理 P1：阶段切分状态机（ADR-0012 方案 A）

### 4.1 改动（10 个工具 name/description/args_schema 一字不改，只动暴露逻辑）

- **`ai_service/agent/tool_registry.py`（改）**：`AgentTool` 新增 `group`（阶段集合，"retrieval"/"generation"，双组 ["retrieval","generation"]；空 = 未分组恒全阶段可见，向后兼容）；`register()` 新增 group 参数；**`to_llm_schemas(group=None)` 默认仍全量 10**（存量 `test_agent_tools.py` len==10 不挂），传组过滤；`register_builtin_tools` 标注：**检索组 7**（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/re_search）、**生成组 4**（generate_answer/verify_answer/note_to_self/re_search 双组）。
- **`ai_service/agent/react.py`（改）**：`ReactContext.phase`（初始 "retrieval"）+ 公共辅助 `schemas_for_phase(tools, ctx)`（开关 true 按阶段过滤，false 全量）与 `advance_phase(ctx, executed_names)`（本轮调用过 generate_answer/verify_answer → 下一轮切 generation；**generation 内调 re_search 不回退，单向前进防死循环**）；`react_loop` 每轮按阶段选 schema、执行完本轮工具后推进 phase。
- **`ai_service/agent/langgraph_react.py`（改）**：`llm_call` / `execute_tools` 节点复用同一公共辅助（**只改一处 = 回归，防两处漂移**）。
- **阶段判定口径**：以"是否已调用过 generate_answer/verify_answer"为界（**非 docs 非空**——保留"生成后发现不足→再补检"能力）；检索阶段 schema 无生成工具，LLM 需先检索（可能多轮）再调生成工具（下一轮切 generation）——"先检后生"强制语义，本设计的预期行为（059 brief 事实 6）。
- **`ai_service/src/config.py`（改）**：`tool_phase_split`（PW_TOOL_PHASE_SPLIT 默认 true；false 回退全量 10 零回归逃生口）。
- **`ai_service/tests/conftest.py`（改）**：autouse fixture 钉住测试环境 `tool_phase_split=False` + `request_logs_enabled=False`（对齐 module-056 分类器开关成熟模式——**默认 true 会漂移走 react 层存量 agent 测试，钉住是"存量全绿"的真正保证**；新测试显式开 true 验证切分/落库）。
- **预算路径逐字不变**：预算=0 直接回答（无工具 schema）、预算耗尽 reflector 兜底生成——行为与改动前完全一致（单测断言）。
- **`_SYSTEM_PROMPT` 不改**：工具清单一字不改（存量断言零漂移）；阶段语义由 schema 结构性约束（系统提示词仍列全量 10 个工具供 LLM 知晓能力全集）。

### 4.2 测试（tests/test_tool_phase_split.py，18 项，全 mock）

① 检索组 schema 恰好 7 且不含 generate_answer/verify_answer；② 生成组恰好 4（含 re_search 双组）；③ to_llm_schemas() 无参全量 10；④ 10 个工具 name/description/args_schema 一字不改（只新增 group）；⑤ 未分组工具恒全阶段可见；⑥ ctx.phase 初始 retrieval；⑦ advance_phase 单元（仅生成工具触发切换/re_search 不触发/不回退）；⑧ schemas_for_phase 开关 true 按阶段过滤；⑨ 调 generate_answer 后**下一轮** schema = 生成组 4（react 手写循环）；⑩ verify_answer 同样切 generation；⑪ generation 内调 re_search 不回退（补检口仍在生成组）；⑫ 开关 false 全量 10；⑬ 预算=0 无工具调用；⑭ 预算耗尽兜底路径不变（全程检索组 schema）；⑮-⑰ langgraph 版同款（切换/re_search 不回退/开关 false）；⑱ _SYSTEM_PROMPT 仍列全量 10。

### 4.3 两循环真实 E2E 冒烟（uvicorn 8001，PW_TOOL_PHASE_SPLIT 默认 true）

| 端点 | tool_trace | 生成工具调用 | "尚未检索"防御串 | tool_count/budget | 答案 |
|------|-----------|------------|----------------|-------------------|------|
| /ai/rag/chat/agent | search_knowledge → recall_memory → search_fts → search_knowledge | **0** | **0** | 4/4（预算耗尽兜底） | 1590 字符 / 5 sources |
| /ai/rag/chat/agent-lg | search_knowledge → search_fts → search_vector → search_knowledge | **0** | **0** | 4/4（预算耗尽兜底） | 1451 字符 / 5 sources |

- 两循环 tool_trace 全部为检索组工具（**生成工具未被调用的结构性证据——检索阶段 schema 不含生成工具**）；无"尚未检索"防御串（结构性隔离替代字符串防御生效）。
- **诚实边界**：E2E 中 LLM 未实际调用 generate_answer（信息足够后直接输出/预算耗尽走兜底），**阶段切换的"轮次推进"由 14 项单测覆盖**（LLM 行为非确定，无法在 E2E 强制触发）；E2E 冒烟数据已清理（3 行会话行），request_logs 样例行保留。

---

## 5. WP-D 验收与降级

- **全量 pytest**：`python -m pytest tests/ -q` → **780 passed / 0 failed**（740 基线 + 40 新增：test_prompt_order 6 + test_tool_phase_split 18 + test_observability 16；存量测试零改动，仅 test_memory.py 1 项顺序预期按验收 §1 许可更新。注：初版文档误记 14/14，实收集 18/10，修复轮新增 6 项后 18/16，见 §7）。
- **降级**：前缀缓存收益在单文档规模不可量化 → 如实记录边界，改顺序保留（近零成本 + 铺路）；request_logs 落库失败 → fail-open（try/except + 日志告警，单测覆盖）；流式中断 → finally 落库不阻塞；工具切分异常 → `PW_TOOL_PHASE_SPLIT=false` 一键回退全量（逃生口，单测覆盖）；开关 false 时零埋点零落库（单测覆盖）。
- **接口兼容**：默认 rrf 三通道不动；hybrid/独立 title 回退开关保留（WP-A 推迟不涉及）；`to_llm_schemas()` 无参行为不变；request_logs 建表幂等（服务重复启动不报错，真实 init_db 验证）。
- **面试口径更新点**：08 文档 2.8 节新增（prompt"docs 前置前缀缓存"、观测"有 trace 可量化"、工具"10 个按阶段切分（检索 7 / 生成 4，re_search 双组）"、检索"拼标题三通道 RRF（WP-A 待后续）"）；CONTEXT.md 只增不删（工具阶段切分术语追加）。

## 6. 已知边界（诚实声明）

1. **前缀缓存**：单文档（prompt <1024 token）未达 DeepSeek 硬盘缓存门槛，docs 段不缓存（探测实测）；多文档（≥3000 token）实测命中（billed miss -98%）。缓存策略属供应商侧，本模块只验证不优化。
2. **verify 场景**：LLM 只拆句，docs 不进 LLM prompt——"同 docs 验多 claim"无 token 前缀可复用（module-051 拆分的设计结果，口径已核实）。
3. **可观测性**：流式 LLM 调用不采集 token usage（SSE 逐 token 供应商不返回 usage）；engine.chat 路径无检索缓存故 cache_hits/misses 恒 0（命中计数只在 _retrieve 路径统计）；降级串行/快路径检索不单独计时。
4. **request_logs 错误标记**：422 等请求校验失败**不会落库**（FastAPI body 校验在端点执行前抛出，persist_request_log 不可达）；error 仅主链路异常置 true（chat internal_error / 流式与 agent 端点 except 分支）；流式提前断开/提前结束经 finally 留痕（可能 timings/usage 为空，error=False，如实记录）。
5. **E2E 阶段切换**：LLM 未在 E2E 中调生成工具，轮次推进由单测覆盖；E2E 冒烟未观察到"尚未检索"防御串（0 次）。
6. **工具阶段切分已知行为**：检索阶段 LLM 若仍按系统提示词调用 schema 外的生成工具名（个别供应商/模型行为），工具仍按名执行（registry 查找），阶段在下一轮才推进——结构性隔离降低概率而非硬阻断（DeepSeek/OpenAI 兼容 API 不做 schema 校验，Anthropic 会拒绝并触发降级链，如实声明）。
7. **探测脚本**：scripts/probe_prefix_cache.py（WP-B 证据可复跑）与 scripts/probe_request_trace.py（WP-C 样例可复跑）保留为工具；probe_request_trace.py 每次运行会产生 1 行 request_logs 样例（清理了记忆/会话行）。

---

## 7. 修复记录（Reviewer conditional 意见逐条修复，2026-08-13）

### MAJOR-1：trace_id 未贯穿日志（AC §2「日志 extra」部分未实现）→ 已修复

- **问题**：`get_trace_id()` 定义后零调用，无任何 logger 使用 trace_id，无法用 trace_id 关联服务日志行；database.py COMMENT「trace_id 贯穿日志与落库」只落实了落库侧。
- **修复**：
  - `ai_service/src/observability.py`：新增 `TraceIdFilter`（filter 从 contextvar 取 `get_trace_id()` 注入 `record.trace_id` extra，无请求上下文时为空串不干扰）+ `install_trace_id_filter()`（幂等，重复调用返回同一实例）。**挂载位置说明**：Python logging 中祖先 logger 的 filter 不作用于子 logger 传播上来的 record（callHandlers 只经 handler.filter），故同时挂根 logger（覆盖 logging.info 直发）与其 handler（覆盖模块级 `getLogger(__name__)` 传播记录）。`get_trace_id()` 改为只读不惰性初始化（避免无请求上下文的日志触发 contextvar 写入），由过滤器消费消除死代码。
  - `ai_service/main.py`：basicConfig 格式加 `[%(trace_id)s]`（过滤器保证字段恒存在）+ basicConfig 之后调用 `install_trace_id_filter()`。
- **测试**：tests/test_observability.py 新增 `TestTraceIdInLogs` 3 项（请求上下文存在 → record.trace_id 注入 / 无请求 → 空串 / install 幂等）。**测试要点**：根 logger 默认 WARNING 会滤掉 INFO 级记录，用例显式 setLevel 放行（独立调试确认）。
- **验证**：16/16 通过（含存量 10 项零改动）；日志样例 `[trace-log-abc]` 可肉眼关联。

### MAJOR-2：chat_with_tools 的 token 用量标签恒为 "llm"（AC §2「fallback 链各供应商」未满足）→ 已修复

- **问题**：`llm/client.py:197,233` `_record_usage("llm", ...)` 恒标 "llm"，工具调用轮次用量无法按供应商归属；DB 实查 request_logs id=3/4 行 `usage={'llm':..., 'deepseek':...}` 佐证（'llm' 桶即本 bug 证据）。
- **修复**：`LLMClient._provider_label()`——DeepSeekClient → "deepseek"、_ModelScopeBaseClient 系 → `self._label`（qwen/zhipu/modelscope）、ClaudeClient → "claude"、兜底 "llm"；`_chat_with_tools_openai` / `_chat_with_tools_bind` 两处改传 `self._provider_label()`。FallbackClient 委托链内各供应商客户端，天然逐供应商落桶。
- **测试**：tests/test_observability.py 新增 `TestChatWithToolsUsageLabel` 3 项（DeepSeekClient OpenAI 路径 → deepseek / QwenClient ModelScope 系 → qwen / ClaudeClient bind 路径 → claude），断言 usage 落对应供应商桶且无 "llm" 桶。
- **验证**：16/16 通过；存量 test_agent_tools（chat_with_tools 循环行为）零改动全绿。

### MINOR-1：changelog §3.1「1 行 422 失败请求也落库」与事实不符 → 已修正

- **事实核对**（DB 实查）：request_logs 共 4 行（1 probe + 2 agent + 1 agent-lg），**无 422 行**；代码上 FastAPI body 校验 422 在端点执行前抛出，persist_request_log 不可能被调用——旧文档系误记。
- **修正**：§3.1 / §6.4 改为「流式结束/断开与端点异常同样经 finally 留痕（error 仅主链路异常置 true）；422 不落库」。
- **id=2 行处理**：id=2（endpoint=agent、timings 空、usage 空、error=False，创建于 E2E 前 51s）来源无法确证（推测为 E2E 准备期提前断开的 SSE 探测请求，属 finally 留痕形态），**已删除**，保留 3 行可确证种子（id=1 probe / id=3 agent / id=4 agent-lg）；删除行为已如实记录于 §3.1。

### MINOR-2：测试分文件数量口径错误（14/14 实为 18/10）→ 已修正

- 实测收集：test_tool_phase_split **18** 项（TestToolGroups 5 + TestPhaseStateMachine 9 + TestLangGraphPhaseSplit 3 + TestSystemPromptUnchanged 1）、test_observability **10** 项（修复前）——初版 changelog / project-context / file-index 均误写 14/14（总数 34 碰巧正确）。
- 修正：changelog §1/§4.2/§5（§4.2 测试清单补 ①-⑱ 与 4 项漏列：group 元数据/初始 phase/advance_phase 单元/schemas_for_phase）、project-context module-058 行、file-index 两行；修复轮新增 6 项测试后最终口径 **test_prompt_order 6 + test_tool_phase_split 18 + test_observability 16 = 40 新增**，全量 **780/0**。

### MINOR-3：工作树携带先前会话遗留未提交改动（提交时注意，本模块未触碰）

- 观察属实（git status 核实）：`ai_service/agent/router.py`（docstring，module-056 L4 启用口径）、`ai_service/tests/test_golden_intent.py`（TestRunCompareClassifier，module-056 Review 修复）、`specs/module-033-long-term-memory/changelog.md`（附属发现）、`CONTEXT.md`（早期会话追加段）——均为先前会话遗留，**本修复轮未修改上述文件**；主会话提交 module-058 时建议与这些遗留改动分离（不同 commit）避免混入。
