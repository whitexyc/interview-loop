# Module-058 任务简报：检索链优化 + 可观测性 + 工具治理 P1

> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。
>
> **⚠️ 2026-08-13 执行口径更新**：本模块已**并入工具治理 P1（原 module-059，ADR-0012 阶段切分）**一起执行——WP-E 新增工具阶段切分；**WP-A（分块拼标题+防扎堆）用户决策推迟**（三通道 RRF Hit@5 已达 0.9905，基线饱和，后续模块再做；届时对比指标须含 Recall@5 + MRR，防扎堆聚合式必配）。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`，FastAPI + asyncpg + pgvector + Apache AGE）。

**现状（代码实测，勿改口径）**：

- **分块**（`rag/retrieval/chunker.py`）：三级——MarkdownHeader 按 ##/### 切父块（≤4000，超限递归切 overlap=0）→ RecursiveCharacterTextSplitter 切子块（**目标 300 软上限**、重叠 50、separators=`["\n\n","\n","。","."," ",""]`）；**子块只对 content 向量化，title 是独立字段未进向量**
- **检索**（`rag/retrieval/retriever.py`）：**默认已切 rrf 三通道**（`src/config.py:79` `retrieval_fusion_mode="rrf"`）；FTS/向量各 `fetch_k=top_k*2` 候选 + 图谱 `search_related(top_k)` → `_execute_fusion` 三路 RRF（k=60）融合 → 取 top_k=5；hybrid 两通道保留为回退（`_execute`）；融合仅 round 0，round 1/2 单路混合
- **评估基线**：golden 112 题 Hit@5 **0.9905**（RRF 三通道，eval_runs id=18，module-053 已放行）；同集同脚本同表对比
- **prompt 拼接**（`agent/reflector.py` `_GENERATE_PROMPT`）：`{sections} → 用户问题: {query} → 检索到的文档: {docs_detail}`——**query 挡在 docs 前，前缀缓存被堵死**
- **可观测性**：**无线上运行时追踪**——有离线评测（eval_runs）但线上无 trace_id/阶段耗时/token 用量/缓存命中率
- **测试**：740 passed

## 二、已知事实（勿重新调查）

| # | 事实                                                                                                                |
| - | ----------------------------------------------------------------------------------------------------------------- |
| 1 | 拼标题 = `embed_text(f"{title}\n{content}")`，改向量化一行 + `reindex_knowledge_base.py` 重灌（124 篇，本地 bge-m3 分钟级）            |
| 2 | 拼标题的**扎堆风险**：同父块子块都带相同标题 → query 命中标题时同父块多子块同时高分 → 映射去重后父块变少、挤占其他文档。**必须配防扎堆**                                    |
| 3 | 防扎堆两选一：① 每父块限命中（top-k 子块里同 parent 最多 2 个；当前整块返回下限 1 也够）② **聚合式**（按 parent_id 分组，父块分=组内最高子块分，返回带组内全部命中子块——保深度）     |
| 4 | 前缀缓存：LLM API 对 prompt 开头重复前缀自动打折（DeepSeek 硬盘缓存/Qwen 支持）；**前提 = 前缀逐字一致**；docs 前移后，verify 场景（同 docs 验 N 个 claim）最受益 |
| 5 | 业界召回提升：Anthropic contextual retrieval 实测 +35-50%（拼标题是零 LLM 成本的本地版）                                                |
| 6 | 可观测性业界标配：P50/P95 延迟、TTFT/TBT、token 成本/问题、缓存命中率、错误率、单问题成本分布                                                        |

## 三、任务步骤（按序，每步有通过标准）

### WP-A 分块拼标题 + 防扎堆（⏸️ 已推迟，2026-08-13 用户决策）

> **状态：推迟到后续模块。** 理由：三通道 RRF Hit@5 已 0.9905（id=18），基线饱和，拼标题收益空间小。**执行时注意**：① 对比指标用 Hit@5 + Recall@5 + MRR 三口径（057 改写实验 MRR -0.0353 提示精排面仍有空间）；② 防扎堆（聚合式）必配；③ 标题作为强语义锚点，价值在冷门/未见过 query 泛化，属索引质量投资而非当前分数投资。

- **拼标题**：向量化改为 `embed_text(f"{title}\n{content}")`（定位 `rag/retrieval/embeddings.py` 或分块入库处子块向量化调用）
- **防扎堆（选聚合式）**：子块检索结果按 `parent_id` 分组 → 父块分 = 组内最高子块分 → 取 top-N 父块 → 每个父块附带组内全部命中子块（保深度不丢内容）——若实现复杂度高，退化为"每父块限 2 个命中"（简单，覆盖略降）
- **重灌**：`reindex_knowledge_base.py` 全量重建（含图谱，注意先 `--dry-run`）
- **评估**：golden 对比，**基线 = 0.9905（eval_runs id=18）**，同集同脚本
- **通过标准**：Hit@5 ≥ 0.9905（拼标题目标是有提升或持平）；有提升才留，无提升回滚（保留 title 独立字段回退开关）

### WP-B prompt 顺序 + 前缀缓存（🟢 近零成本，1 小时内）

- 把 `_GENERATE_PROMPT` 顺序改为 `{sections} → 检索到的文档: {docs_detail} → 用户问题: {query}`（docs 前移、query 最后）
- 验证前缀缓存：verify_answer 场景（同 docs 验多 claim）前后 token 对比（可用 API 返回的 usage 字段）
- **通过标准**：verify 场景 N 个 claim 验证的 token 明显下降（同 docs 前缀复用）；生成质量无回归（golden/factcheck 抽查）

### WP-C 可观测性（🔴 核心，1-2 天）

- **trace_id**：每次请求生成 UUID，贯穿日志（可挂到请求上下文/日志 extra）
- **阶段耗时**：在 main.py/engine.py 关键节点计时落日志：意图路由 / 分诊改写 / 检索（FTS、向量、图谱各自）/ rerank / 反思 / 生成 / 幻觉检测
- **token 用量**：记录每次 LLM 调用的 prompt/completion token（fallback 链各供应商）
- **缓存命中**：RedisCache 命中率（`_retrieve_cache_key` 处计数）
- **落库**：复用 eval_runs 模式建 `request_logs` 表（或结构化日志 + 简单聚合查询），字段：trace_id/identity/intent/各阶段耗时/token/缓存命中/错误标记；**建表走 init_db 自愈幂等 DDL（对齐 module-048 feedback 表模式，不另起迁移脚本）**
- **通过标准**：一次真实请求能查到完整 trace（各阶段耗时 + token + 缓存命中）；可回答"单问题成本分布"和"P50/P95 延迟"

### WP-E 工具治理 P1：阶段切分状态机（🟢 半天，原 module-059 并入）

> 完整方案见 `specs/module-059-tool-phase-split/task-brief.md`（10 工具口径 08-13 同步复核版），此处仅列要点。

- **分组**：检索组 7（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/**re_search**）；生成组 4（generate_answer/verify_answer/note_to_self/**re_search 双组**）
- **状态机**：`ctx.phase` 初始 retrieval；每轮 `tools.to_llm_schemas(group=ctx.phase)`；本轮 tool_calls 含 generate_answer 或 verify_answer → 下一轮切 generation；generation 内调 re_search **不回退**（单向前进防死循环）
- **判定标准**：以"是否已调用过 generate_answer/verify_answer"为界，**不是** docs 非空（会切断补检）
- **改造点**：`tool_registry.py`（AgentTool.group + `to_llm_schemas(group=None)` **默认仍全量 10 个**——存量测试 `test_agent_tools.py:94 assert len==10` 不挂）；`react.py:213`；`langgraph_react.py:89`（llm_call node）+ execute_tools 切 phase；`src/config.py` 加 `tool_phase_split`（读 `PW_TOOL_PHASE_SPLIT`，默认 true）
- **通过标准**：单测（检索阶段 7 个无生成工具/调 generate_answer 或 verify_answer 切 generation/re_search 不回退/开关 false 全量 10/预算路径不变）+ 740 全绿 + E2E 两循环冒烟；**conftest autouse fixture 钉住测试环境 `PW_TOOL_PHASE_SPLIT=false`（对齐 module-056 分类器开关成熟模式，否则默认 true 会漂移走 react 层的存量 agent 测试），新测试显式开 true 验证切分——"存量测试全绿"的真正保证**

### WP-D 验收（🔴 收尾）

- 全部 740 测试全绿（不破坏现状：默认 rrf 不动、存量测试不改）
- ~~golden 对比表（拼标题后 vs 0.9905）~~ → **WP-A 已推迟，本项验收不适用，无此交付**；token 对比（WP-B）+ 观测样例（WP-C trace 示例）
- 工具治理验收：WP-E 单测 + 两循环 E2E 冒烟记录
- 面试口径更新：检索"拼标题三通道 RRF（WP-A 待后续）"、prompt"docs 前置前缀缓存"、观测"有 trace 可量化"、工具"10 个按阶段切分（检索 7 / 生成 4，re_search 双组）"

## 四、纪律项（违反 = 返工）

1. **不破坏现状**：默认 rrf 三通道不动；hybrid/独立 title 保留回退开关；存量测试全绿
2. **评估同口径**：新旧数字同一 golden、同一脚本、同一 eval_runs 表；拼标题对比基线 0.9905（id=18）
3. **防扎堆必配**：拼标题必须同时上防扎堆（聚合式或限命中），否则召回被少数父块占满
4. **重灌要谨慎**：先 `--dry-run` 看规模再全量；单篇失败不阻断（reindex 既有语义）
5. **可观测性不引入新依赖**：优先复用现有日志 + eval_runs 表模式，不装重型 tracing 框架（项目无该基建）

## 五、交付物

1. ~~WP-A golden 对比表（拼标题+防扎堆 vs 0.9905）~~ → **已推迟**（后续模块，届时三口径对比）
2. WP-B token 对比（verify 前缀缓存前后）+ prompt 顺序 diff
3. WP-C 观测样例（一条真实 trace：各阶段耗时 + token + 缓存命中）+ request_logs 结构
4. WP-E 工具治理：阶段切分单测 + 两循环 E2E 冒烟记录（详见 module-059 brief）
5. 面试口径更新点（08 文档 2.5/2.7 + CONTEXT.md）
