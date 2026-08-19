# 验收标准 — Module-058: 检索链优化 + 可观测性 + 工具治理 P1

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 执行口径：WP-A（拼标题+防扎堆）已推迟，本模块不含；工具治理 P1（原 059）以 WP-E 并入

## 1. 功能验收（WP-B prompt 顺序 + 前缀缓存）

- [ ] 📋 `_GENERATE_PROMPT` 顺序改为 `{sections} → 检索到的文档: {docs_detail} → 用户问题: {query}`（docs 前移、query 最后）
- [ ] 📋 存量 prompt 相关测试零回归（除顺序预期变更外无其他漂移；sections 内容/格式一字不改）
- [ ] 📋 verify 场景 token 对比（前后 API usage）：同 docs 前缀复用 token 下降；**若实测为单次 LLM 调用无法对比 → 如实记录边界，改顺序保留**
- [ ] 📋 生成质量抽查无回归（golden_sufficiency / golden_factcheck 抽样）

## 2. 功能验收（WP-C 可观测性）

- [ ] 📋 trace_id：每次请求生成 UUID，贯穿日志（chat / stream 均含），挂 request.state + 日志 extra
- [ ] 📋 阶段耗时：意图路由 / 分诊改写 / 检索（FTS、向量、图谱各自）/ rerank / 反思 / 生成 / 幻觉检测 计时落日志
- [ ] 📋 token 用量：每次 LLM 调用记录 prompt/completion token（fallback 链各供应商；无 usage 记 None 不中断）
- [ ] 📋 缓存命中：`_retrieve_cache_key` 处计数命中/未命中
- [ ] 📋 request_logs 表：**init_db 自愈幂等 DDL**（对齐 module-048 feedback 表模式，不另起迁移脚本），字段含 trace_id/identity/intent/各阶段耗时/token/缓存命中/错误标记
- [ ] 📋 identity 对齐 048 口径（user_id 优先、client_ip 兜底）
- [ ] 📋 一条真实请求可查到完整 trace（各阶段耗时 + token + 缓存命中）；可回答"单问题成本分布"与"P50/P95 延迟"（结构化日志 + 聚合查询即可）
- [ ] 📋 不引入新依赖（无重型 tracing 框架）

## 3. 功能验收（WP-E 工具阶段切分）

- [ ] 📋 ToolRegistry：AgentTool.group（"retrieval"/"generation"/双组）+ `to_llm_schemas(group=None)` 默认全量 10（`test_agent_tools.py:94 assert len==10` 不挂）
- [ ] 📋 分组口径：检索组 7（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/**re_search**）；生成组 4（generate_answer/verify_answer/note_to_self/**re_search 双组**）
- [ ] 📋 ctx.phase 状态机：初始 retrieval；本轮 tool_calls 含 generate_answer 或 verify_answer → 下一轮切 generation
- [ ] 📋 判定标准：以"是否已调用过 generate_answer/verify_answer"为界（**不是** docs 非空——保留补检能力）
- [ ] 📋 generation 内调 re_search **不回退**（单向前进，防死循环）
- [ ] 📋 react_loop + langgraph_react_loop 同步改造（抽公共辅助函数，只改一处 = 回归）
- [ ] 📋 预算=0 / 预算耗尽兜底路径行为与改动前逐字一致
- [ ] 📋 开关 `PW_TOOL_PHASE_SPLIT` 默认 true；false 回退全量 10 零回归（逃生口）
- [ ] 📋 **10 个工具 name/description/args_schema 一字不改**（只动暴露逻辑）

## 4. 验收（WP-D 收口）

- [ ] 📋 token 对比记录（WP-B）+ 观测样例（WP-C 一条真实 trace：阶段耗时 + token + 缓存命中）
- [ ] 📋 工具治理验收：WP-E 单测 + 两循环 E2E 冒烟记录（chat + stream，tool_trace 阶段切换正确、无"尚未检索"防御串）
- [ ] 📋 ADR-0012 状态行更新（✅ P1 已实施，注明并入 module-058 执行）
- [ ] 📋 面试口径更新点落盘（08 文档 2.5/2.7：prompt"docs 前置前缀缓存"、观测"有 trace 可量化"、工具"10 个按阶段切分（检索 7 / 生成 4，re_search 双组）"、检索"拼标题三通道 RRF（WP-A 待后续）"）

## 5. 降级验收

- [ ] 📦 前缀缓存收益不可量化（API 无 usage / 缓存不生效）→ 如实标注，改顺序保留（近零成本 + 铺路）
- [ ] 📦 request_logs 落库失败 → fail-open 不阻塞主链路（try/except + 日志告警）
- [ ] 📦 工具切分 E2E 异常 → `PW_TOOL_PHASE_SPLIT=false` 一键回退全量（逃生口留证）
- [ ] 📦 全量 pytest 740+N 全绿保持

## 6. 接口兼容

- [ ] 🔌 默认 rrf 三通道不动；hybrid / 独立 title 回退开关保留（WP-A 推迟不涉及）
- [ ] 🔌 `to_llm_schemas()` 无参调用行为不变（全量 10）；工具内部语义不变
- [ ] 🔌 request_logs 建表幂等（服务重复启动不报错）；request_logs 开关 false 时零埋点零落库

## 7. 测试验收

- [ ] 🧪 tests/test_tool_phase_split.py（新）：① 检索阶段 schema 恰好 7 个且不含 generate_answer/verify_answer；② 调 generate_answer 后下一轮 schema = 生成组 4（含 re_search）；③ generation 内调 re_search 后仍 generation；④ 调 verify_answer 同样切 generation；⑤ 开关 false 全量 10；⑥ 预算路径不变
- [ ] 🧪 tests/test_observability.py（新）：trace_id 贯穿 / 阶段计时 / 缓存命中计数 / request_logs 幂等落库 / 落库失败 fail-open
- [ ] 🧪 prompt 顺序测试（新）：顺序断言 + 存量零回归
- [ ] 🧪 conftest autouse fixture 钉住测试环境 `PW_TOOL_PHASE_SPLIT=false`（对齐 module-056 分类器开关模式）；request_logs 测试隔离（测试不污染落库）
- [ ] 🧪 `python -m pytest tests/ -q` — 全量 740+N 全绿（**不改存量测试掩盖**）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含 token 对比 + trace 样例 + 阶段切分结论 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-058 行** + 头部"最后更新"日期改为当天
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0012 状态行更新（P1 已实施）
- [ ] 📝 **CONTEXT.md 只增不删**（术语新增走追加；同步/合并永远取更全一侧）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
