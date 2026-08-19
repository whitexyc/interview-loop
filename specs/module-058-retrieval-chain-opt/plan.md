# 功能规格说明书 — Module-058: 检索链优化 + 可观测性 + 工具治理 P1

> Planner | 2026-08-13
> 执行口径：WP-A（拼标题+防扎堆）用户决策推迟；工具治理 P1（原 module-059，ADR-0012 方案 A）并入本模块执行

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-058 |
| 模块名称 | 检索链优化（prompt 顺序 + 前缀缓存 + 可观测性）+ 工具治理 P1（阶段切分） |
| 版本号 | 0.58.0-module-058 |
| 优先级 | P0（WP-B 近零成本前缀缓存 / WP-C 线上可观测性 / WP-E 工具阶段隔离，用户拍板一并执行） |
| 预估代码量 | ≤ 500 行（WP-B 改 prompt 一行 + 验证；WP-C 计时埋点 + request_logs 表 + 日志；WP-E 状态机 + 分组 + 单测） |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-B prompt 顺序 + 前缀缓存 | `_GENERATE_PROMPT` 顺序改 `{sections} → 检索到的文档: {docs_detail} → 用户问题: {query}`（docs 前移、query 最后）；verify 场景（同 docs 验多 claim）前后 token 对比验证前缀缓存 | 058 brief WP-B（🟢 1 小时内） |
| WP-C 可观测性 | trace_id 贯穿 + 阶段耗时（意图路由/分诊改写/检索 FTS·向量·图谱各自/rerank/反思/生成/幻觉检测）+ token 用量（各供应商）+ 缓存命中率 → request_logs 落库（init_db 幂等 DDL 对齐 048 feedback 表） | 058 brief WP-C（🔴 1-2 天） |
| WP-E 工具治理 P1 | ADR-0012 方案 A：10 工具按执行阶段切分（检索组 7 / 生成组 4，re_search 双组），ctx.phase 状态机单向前进，react_loop + langgraph_react_loop 同步改造，PW_TOOL_PHASE_SPLIT 开关（默认 true） | 用户"工具治理放到 58 中" + 059 brief（🟢 半天） |
| WP-D 验收收口 | 全量 pytest 740+N 全绿（默认 rrf 不动、存量测试不改）+ token 对比 + trace 样例 + WP-E E2E 冒烟 + ADR-0012 状态更新 + 面试口径更新点（08 文档 2.5/2.7 + CONTEXT.md 只增不删） | 058 brief WP-D |

### 验收场景

```
场景 1：前缀缓存（WP-B）
  假设 改 _GENERATE_PROMPT 顺序（docs 前移、query 最后）+ verify 场景实测（API usage 字段）
  那么 同 docs 前缀复用 token 下降（前后对比）；生成质量抽查无回归（golden/factcheck 抽样）

场景 2：可观测性（WP-C）
  假设 发一条真实请求（chat / stream）
  那么 日志含 trace_id + 各阶段耗时 + token 用量 + 缓存命中；request_logs 表可查完整记录；
      可回答"单问题成本分布"和"P50/P95 延迟"（结构化日志 + 聚合查询即可，不装重型框架）

场景 3：工具阶段切分（WP-E）
  假设 默认 tool_phase_split=true 走 agent 端点（react 或 langgraph 任一路）
  那么 检索阶段 schema 恰好 7 个且不含 generate_answer/verify_answer；调 generate_answer 或
      verify_answer 后下一轮切 generation（4 个含 re_search）；generation 内调 re_search 不回退；
      开关 false 时回退全量 10 个零回归

场景 4：验收（WP-D）
  假设 全量 pytest + 两循环 E2E 冒烟（chat + stream）
  那么 740+N 全绿；E2E tool_trace 阶段切换正确、无"尚未检索"防御串；ADR-0012 状态行更新；
      记忆三件套同步；面试口径更新点落盘
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-B | `ai_service/agent/reflector.py`（`_GENERATE_PROMPT` 顺序：sections → docs_detail → query） | 修改 |
| WP-C | `ai_service/main.py`（trace_id 中间件 + 请求结束落库 request_logs，含流式）+ `ai_service/rag/engine.py`（阶段计时）+ `ai_service/src/cache.py` 或调用处（缓存命中计数）+ `ai_service/llm/client.py`（token 采集） | 修改 |
| WP-C | `ai_service/src/config.py`（request_logs 开关）+ request_logs 建表 DDL（init_db 自愈幂等，对齐 048 feedback 表模式） | 修改 |
| WP-E | `ai_service/agent/tool_registry.py`（AgentTool.group + `to_llm_schemas(group=None)`）+ `ai_service/agent/react.py`（:213 附近，ctx.phase 状态机）+ `ai_service/agent/langgraph_react.py`（:89 附近同步改造，抽公共辅助函数防两处漂移）+ `ai_service/src/config.py`（tool_phase_split 读 PW_TOOL_PHASE_SPLIT 默认 true） | 修改 |
| WP-B/C/E | `ai_service/tests/test_prompt_order.py`、`test_observability.py`、`test_tool_phase_split.py`（新建）+ `ai_service/conftest.py`（autouse fixture 钉住测试环境开关，对齐 056 模式） | 新建 |
| WP-D | changelog / review-report / test-report + memory/ 三文件 + ADR-0012 状态行 + CONTEXT.md（只追加）+ 面试口径更新点（docs/简历/08 文档 2.5/2.7） | 修改 |

### 3.2 关键实现约束

- **WP-B**：`_GENERATE_PROMPT` 只调换区块顺序（sections 内容/格式一字不改，query 标签格式不变）；存量 prompt 相关测试除顺序预期变更外零漂移；token 对比用 API 返回 usage 字段（LLM 判分降级路径/拆句调用实测——**若 verify 场景实际为单次 LLM 调用无法同 docs 多轮复用，则如实记录边界**，改顺序本身保留：docs 前移成本为零且为前缀缓存铺路）；生成质量抽查 golden_sufficiency/golden_factcheck 抽样无回归
- **WP-C**：trace_id 用 UUID，FastAPI 中间件生成挂 request.state + 日志 extra，引擎/LLM 客户端从上下文取（不新增全局状态）；阶段计时 `time.perf_counter` 落结构化日志；token 从各供应商响应 usage 字段采集（无 usage 记 None 不中断）；缓存命中在 `_retrieve_cache_key` 处计数命中/未命中；**request_logs 落库在请求结束（含流式结束/断开）后台写入，失败 fail-open 不阻塞主链路**；建表走 init_db 自愈幂等 DDL（对齐 module-048 feedback 表 FEEDBACK_DDL 模式，不另起迁移脚本）；字段：trace_id/identity/intent/各阶段耗时/token/缓存命中/错误标记；identity 对齐 048 口径（user_id 优先 client_ip 兜底）；**不引入新依赖**（复用现有日志 + SQLAlchemy，不装重型 tracing 框架）
- **WP-E**（对齐 059 brief + ADR-0012）：分组口径——检索组 7（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/**re_search**）、生成组 4（generate_answer/verify_answer/note_to_self/**re_search 双组**）；`ctx.phase` 初始 retrieval，每轮 `to_llm_schemas(group=ctx.phase)`，本轮 tool_calls 含 generate_answer 或 verify_answer → 下一轮切 generation；**判定以"是否已调用过生成工具"为界（非 docs 非空——会切断补检）**；generation 内调 re_search **不回退**（单向前进防死循环）；`to_llm_schemas(group=None)` 默认仍全量 10（`test_agent_tools.py:94 assert len==10` 不挂）；两条循环（react_loop + langgraph_react_loop）抽公共辅助函数同改；预算=0 / 预算耗尽兜底路径行为与改动前逐字一致；**10 个工具 name/description/args_schema 一字不改（只动暴露逻辑）**；开关 `PW_TOOL_PHASE_SPLIT` 默认 true、false 回退全量零回归（逃生口）
- **测试隔离**：conftest autouse fixture 钉住测试环境 `PW_TOOL_PHASE_SPLIT=false`（对齐 module-056 分类器开关成熟模式，默认 true 会漂移走 react 层的存量 agent 测试）；request_logs 同样钉住（测试不落库污染），新测试显式开 true/开落库验证
- **诚实边界**：前缀缓存收益依赖供应商 API 缓存策略（DeepSeek 硬盘缓存/Qwen），以实测为准不可量化则如实标注；可观测性 = 结构化日志 + request_logs 落库，P50/P95 靠聚合查询（无重型框架）；工具治理只改暴露逻辑，工具本身行为不变

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 前缀缓存收益不可量化（API 无 usage / 缓存不生效） | 如实标注"无法量化"；改顺序保留（docs 前移近零成本 + 为后续缓存策略铺路） |
| request_logs 落库失败 | fail-open：try/except + 日志告警，不阻塞回答主链路 |
| 流式请求中断 | 落库在 SSE 结束/断开时后台写，失败不阻塞 |
| 工具阶段切分 E2E 异常 | `PW_TOOL_PHASE_SPLIT=false` 一键回退全量（逃生口），如实记录 |
| 全量 pytest | 740+N 全绿保持（存量测试零改动） |

---

## 4. 依赖

- module-028/036（ToolRegistry 10 工具 + react_loop）、module-030（langgraph_react_loop）、module-039（verify_answer 需 docs+answer → 生成组）、module-040（re_search 需已有 docs → 双组）、module-041（note_to_self → 生成组）
- module-048（feedback 表 init_db 幂等 DDL 模式 + identity 解析口径）、module-056（conftest 钉住开关模式）
- ADR-0011（prompt 评估方法论）、ADR-0012（工具治理方案 A 定稿：阶段判定/归组依据/单向前进）
- 环境：DB 可用（request_logs 建表）、deepseek 可用（token usage 验证）、740 测试基线（module-057 后）

## 5. 已知边界

- **WP-A 拼标题 + 防扎堆推迟**（用户决策，2026-08-13）：三通道 RRF Hit@5 已 0.9905（eval_runs id=18）基线饱和；后续模块执行时对比指标须含 **Hit@5 + Recall@5 + MRR** 三口径（057 改写实验 MRR -0.0353 提示精排面仍有空间），防扎堆（聚合式）必配
- 前缀缓存收益依赖供应商缓存策略，本模块只验证不优化供应商侧
- 可观测性落地 = 结构化日志 + request_logs 表（无重型 tracing 框架，符合项目基建现状）
- 工具治理只动暴露逻辑；10 个工具定义与内部实现一字不改
- CONTEXT.md 只增不删（记忆硬约束：合并/同步永远取更全一侧）；面试口径更新点只追加不覆盖
- 本模块不改默认 rrf 三通道、不改 hybrid/独立 title 回退开关、不改存量测试（红线）
