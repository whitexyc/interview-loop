# Review 报告 — Module-058: 检索链优化（prompt 顺序 + 可观测性）+ 工具治理 P1（阶段切分）

> Reviewer | 2026-08-13
> 审查范围：plan.md / acceptance-criteria.md / task-brief.md / 059 brief / ADR-0012 / changelog.md + 全部变更文件
> 独立验证：全量 pytest 复跑 + request_logs 表 DB 实查 + 新测试逐文件收集计数

---

## 1. 结论

**✅ Conditional（有条件通过，2 项 major 修复后重审）**

| 维度 | 结论 |
|------|------|
| 方法学 | ✅ 与 plan/ADR-0012 一致，口径声明完整 |
| 正确性 | ✅ 核心逻辑正确（WP-B 顺序 / WP-C 埋点 / WP-E 状态机） |
| 降级链 | ✅ fail-open / 开关回退 / 预算路径零回归 |
| 诚实性 | ⚠️ 422 落库声明与事实不符（minor #1），其余如实 |
| 测试 | ✅ 全量 774/0 独立复现；新增 34 项（分文件计数 18/10/6） |
| 结果解读 | ✅ 数字与 DB 实查一致（probe 行 / E2E 行） |
| 风格与最小改动 | ✅ 中文注释、最小改动、无投机性 |
| 记忆核查 | ✅ 三件套 + ADR-0012 状态行 + CONTEXT.md 只增 + 08 文档 2.8 |

---

## 2. 独立验证记录

### 2.1 全量 pytest 独立复跑

`python -m pytest tests/ -q` → **774 passed / 0 failed（154.01s，42 warnings 与基线同源）**，与 changelog §5 完全一致。

### 2.2 新测试逐文件收集计数

| 文件 | changelog 声称 | 实际收集 | 结论 |
|------|--------------|---------|------|
| test_tool_phase_split.py | 14 | **18** | 口径错误（minor #2） |
| test_observability.py | 14 | **10** | 口径错误（minor #2） |
| test_prompt_order.py | 6 | 6 | ✅ |
| 合计 | 34 | 34 | ✅ 总数正确，774 成立 |

### 2.3 request_logs 表 DB 实查（真实 PG）

| id | endpoint | intent | error | timings | usage | 结论 |
|----|----------|--------|-------|---------|-------|------|
| 1 | probe-engine.chat | knowledge | F | 9 阶段全 | deepseek 4561/1562 | ✅ 与 changelog §3.2 trace 样例逐位一致 |
| 2 | agent | agent | F | 空 | 空 | 来源未说明（非 422，见 minor #1） |
| 3 | agent | agent | F | retrieve_fts/graph/vector | **{'llm': ..., 'deepseek': ...}** | 佐证 major #2（"llm" 标签） |
| 4 | agent-lg | agent | F | retrieve_fts/graph/vector | **{'llm': ..., 'deepseek': ...}** | 佐证 major #2 |

### 2.4 关键实现逐点核对（通过项摘录）

- **WP-B**：`_GENERATE_PROMPT` 顺序 = sections → 检索到的文档 → 用户问题，标签格式一字未改；test_memory.py 仅 1 项顺序预期更新（AC §1 许可范围）；probe 脚本多文档 miss 3001→57-60（-98%）与脚本判定逻辑自洽，verify 口径（LLM 只拆句）如实。
- **WP-C**：contextvar 每请求上下文（非全局）；中间件 trace_id 挂 request.state；engine.chat 七阶段计时 + retriever `_timed_channel` 三通道并行主路径（降级串行不计时，已声明）；缓存命中计数在 `_retrieve_cache_key` 处；`_extract_usage` 兼容 OpenAI/langchain/Anthropic 三形态；REQUEST_LOGS_DDL 幂等（CREATE TABLE IF NOT EXISTS + 分号拆分，对齐 048）；RequestLog ORM 与 DDL 字段对齐；identity 048 口径；save fail-open；四端点接线、流式 finally（断开也触发）——E2E 行证实流式 contextvar 传播正常。
- **WP-E**：group 归组 7/4 与 ADR-0012 完全一致（re_search 双组）；`to_llm_schemas(group=None)` 仍全量 10；`schemas_for_phase`/`advance_phase` 公共辅助两条循环共用（langgraph llm_call + execute_tools 均已接线）；单向前进、以"已调用过生成工具"为界（非 docs 非空）；预算=0/预算耗尽路径逐字未动；conftest autouse 钉住 tool_phase_split=false + request_logs_enabled=false；10 工具 name/description/args_schema 零改动（`test_builtin_tool_group_metadata` 断言 + diff 核对）。
- **记忆/文档**：project-context 模块行 + 头部日期 ✅；activity Developer 行 ✅（本行 Reviewer 追加）；file-index 6 行 ✅；ADR-0012 状态行 ✅（并入 module-058 表述一致）；CONTEXT.md 只增不删 ✅；08 文档 2.8 节只追加不覆盖 ✅（gitignore 文件，实读确认）。

---

## 3. Major Findings（必须修复，修复后重审）

### MAJOR-1: trace_id 未贯穿日志（AC §2 "日志 extra" 未实现）

- **文件**：`ai_service/src/observability.py:63-65`（get_trace_id 定义但零调用）+ `ai_service/main.py`（无 logging filter）
- **问题**：AC §2「trace_id：…挂 request.state + 日志 extra」与 plan §3.2「挂 request.state + 日志 extra，引擎/LLM 客户端从上下文取」——**日志 extra 部分未实现**：`get_trace_id()` 定义后没有任何调用方，全部 logger 调用均不带 trace_id，无法用 trace_id 关联服务日志行；`database.py:72` COMMENT「trace_id 贯穿日志与落库」与实现不符（只贯穿落库）。
- **建议**：最小实现——在 main.py（或 observability.py）加一个 `logging.Filter`，从 contextvar 取 `get_trace_id()` 注入 `record.trace_id` extra，`logging.getLogger().addFilter(...)`（或给关键 logger 附加）；顺带消除 get_trace_id 死代码。加 1 条单测断言日志 record 带 trace_id。

### MAJOR-2: chat_with_tools 的 token 用量标签恒为 "llm"，无法按供应商归属

- **文件**：`ai_service/llm/client.py:197` / `:233`（`_record_usage("llm", raw)`）
- **问题**：AC §2「token 用量：每次 LLM 调用记录 prompt/completion token（fallback 链各供应商）」——`_chat_with_tools_openai` / `_chat_with_tools_bind` 的用量一律记在 `"llm"` 键下，agent/agent-lg 端点的工具调用轮次**无法按供应商归属**（fallback 链切换时混在一个桶里）；DB 实查 id=3/4 行 `usage={'llm': {...}, 'deepseek': {...}}` 佐证。changelog §3.1「fallback 链内层客户端各自记录，天然带供应商标签」对 agent 路径不成立，"单问题成本分布按供应商"的观测口径在 agent 端点失真。
- **建议**：`_record_usage` 的标签改用调用方 provider 标识——OpenAI 路径用 `self.__class__` 映射（DeepSeekClient→"deepseek"、_ModelScopeBaseClient→self._label），bind 路径 Claude→"claude"；或在 `_chat_with_tools_*` 增加 provider 参数透传。新增 1 条单测断言标签为供应商名。

---

## 4. Minor Findings

1. **changelog 422 落库声明与事实不符**（`specs/module-058-retrieval-chain-opt/changelog.md` §3.1「真实 HTTP E2E 期间…1 行 422 失败请求也落库且 error=False、timings 空——失败请求同样留痕」）：DB 实查 4 行**无 422 行**；代码上 FastAPI body 校验 422 在端点执行前抛出，`persist_request_log` 不可能被调用（失败留痕仅覆盖端点内异常与流式 finally 断开）。行 id=2（endpoint=agent、timings 空、usage 空、error=False）来源未说明，疑为未触发检索/LLM 的请求而非 422。建议：changelog 改为「流式结束/断开与端点异常同样经 finally 留痕（error 仅主链路异常置 true）」，并如实说明 id=2 行来源（或删除该行）。
2. **新测试分文件数量口径错误**：changelog §5 / project-context 模块行 / file-index 均写「test_tool_phase_split 14 + test_observability 14」，实际 **18 + 10**（总数 34 与 774 均正确）。建议三处文档改为 18/10。
3. **观察（非本模块）**：工作树携带先前会话遗留未提交改动——`ai_service/agent/router.py`（docstring）、`ai_service/tests/test_golden_intent.py`（TestRunCompareClassifier，module-056 Review 修复）、`specs/module-033-long-term-memory/changelog.md`（附属发现追加）、CONTEXT.md 早期会话追加段。主会话提交时请与 module-058 提交分离，避免混入。

---

## 5. 放行提示（Tester）

- 复跑全量 pytest（774/0）已由 Reviewer 独立完成一次；Tester 可选择性复跑新三文件（约 50s 收集 + 执行）。
- 建议在条件修复后复验：① 日志行含 trace_id（MAJOR-1）；② request_logs.usage 键为供应商名（MAJOR-2）。
- request_logs 4 行种子数据保留为观测样例（勿删，后续模块聚合查询可复用）。

---

# 第二轮审查（Reviewer | 2026-08-13）— conditional 意见修复核查

## 1. 结论

**✅ Pass（通过）** — 上轮 2 项 major + 2 项 minor 全部修复；无新引入阻塞项；本轮新发现 1 项 minor（文档数字同步遗漏）不阻塞放行。独立复跑全量 pytest **780 passed / 0 failed（148.11s）** 与 changelog 逐字一致。

## 2. 独立验证记录（第二轮）

| 项 | 结果 |
|----|------|
| 全量 pytest 独立复跑 | **780 passed / 0 failed（148.11s，42 warnings）**，与 changelog §5 一致 |
| 新测试逐文件计数 | test_prompt_order 6 / test_tool_phase_split 18 / test_observability 16 = 40，与三处文档口径一致 |
| request_logs 表 DB 实查 | 3 行（id=1 probe / id=3 agent / id=4 agent-lg），**id=2 已删除**，与 §3.1 声明一致；id=3/4 usage 含 'llm' 键系修复前历史种子行（该 bug 实据），保留合理且 changelog 已声明 |

## 3. MAJOR-1 修复核查（trace_id 贯穿日志）— ✅ 已修复

- `observability.py`：`TraceIdFilter`（从 contextvar 取 `get_trace_id()` 注入 `record.trace_id`，恒返回 True 不丢记录）+ `install_trace_id_filter()`（isinstance 幂等；根 logger + 根 handler 双挂，覆盖 logging.info 直发与模块级 logger 传播两类路径）；`get_trace_id()` 只读不惰性初始化（死代码消除，由过滤器消费）。
- `main.py`：basicConfig 格式加 `[%(trace_id)s]`，basicConfig 之后调用 `install_trace_id_filter()`（此时根 handler 已创建，顺序正确）；basicConfig 之前的 import 期日志走 lastResort 默认格式，不存在缺 trace_id 字段崩溃路径（全量 780/0 佐证）。
- `database.py` 旧 COMMENT「trace_id 贯穿日志与落库」已移除（现 DDL 注释仅陈述表结构语义）。
- 测试：`TestTraceIdInLogs` 3 项（请求上下文存在 → 注入 / 无请求 → 空串 / install 幂等），全绿。
- **结论**：AC §2「挂 request.state + 日志 extra」两部分均落实，服务日志行可用 trace_id 跨模块关联。

## 4. MAJOR-2 修复核查（chat_with_tools 用量按供应商）— ✅ 已修复

- `client.py`：`LLMClient._provider_label()`——DeepSeekClient → "deepseek"、_ModelScopeBaseClient 系 → self._label（qwen/zhipu/modelscope）、ClaudeClient → "claude"、兜底 "llm"；`_chat_with_tools_openai` / `_chat_with_tools_bind` 两处改传 `self._provider_label()`。FallbackClient.chat_with_tools 遍历链内客户端，各供应商天然分桶（不会落到 "llm" 兜底）。
- 测试：`TestChatWithToolsUsageLabel` 3 项（deepseek OpenAI 路径 / qwen ModelScope 系 / claude bind 路径），断言落对应供应商桶且无 "llm" 桶；存量 test_agent_tools 零改动全绿。
- **结论**：agent/agent-lg 端点工具调用轮次的 token 用量可按供应商归属，"单问题成本分布按供应商"口径成立。

## 5. MINOR-1 / MINOR-2 修复核查 — ✅ 已修复

- **MINOR-1**：changelog §3.1/§6.4 改为「流式结束/断开与端点异常同样经 finally 留痕（error 仅主链路异常置 true）；**422 不落库**（FastAPI body 校验在端点执行前抛出，persist_request_log 不可达）」；来源无法确证的 id=2 异常样例行**已删除**（DB 实查确认现 3 行）。
- **MINOR-2**：changelog §1/§4.2/§5、project-context 模块行、file-index 三处均更正为「test_prompt_order 6 + test_tool_phase_split 18 + test_observability 16 = 40 新增，全量 780/0」；逐文件计数独立复核一致（§4.2 测试清单已补 4 项漏列）。

## 6. 新发现（本轮，均不阻塞）

1. **minor — ADR-0012 状态行数字未随修复轮更新**（`specs/adr/0012-tool-governance.md` 第 5 行「全量 pytest 774/0」、第 61 行「测试 14 项 + … 全量 pytest 774/0」）：修复轮已把 changelog / project-context / file-index 统一到 780/0 与 18 项，ADR 两处未同步（「测试 14 项」首轮即偏误，实为 18 项，当时漏查）。建议改为「测试 18 项 + 两循环真实 E2E 冒烟 + 全量 pytest 780/0」。
2. **观察（非阻塞）**：observability.py `TraceIdFilter` docstring 称「祖先 logger 的 filter 不作用于子 logger 传播上来的 record（callHandlers 只经 handler.filter）」——CPython 中 Logger.filter 会沿祖先链检查（handle 阶段），根 logger 挂载已足以覆盖传播记录；实现双挂行为正确（幂等且恒放行），注释技术表述略偏，无需改代码。

## 7. 其余维度复核（修复轮零改动范围）

- WP-B / WP-E / 降级链 / 接口兼容：修复轮仅动 observability.py / main.py / client.py / 测试 / 文档（changelog §7 明示），首轮核查结论沿用。
- 记忆：project-context 模块行（含修复记录、40 新增、780/0 口径）+ 头部日期、file-index 6 文件行 + specs 行、agent-activity-log Developer 修复轮行均已追加 ✅；本轮 Reviewer 行追加见 memory/agent-activity-log.md。
- minor #3 观察复核：router.py / test_golden_intent.py / module-033 changelog / CONTEXT.md 的 diff 仍为先前会话遗留内容（module-056 L4 口径 docstring / 附属发现段 / 早期会话追加段），修复轮未触碰，主会话提交时与 module-058 分离。

## 8. 放行提示（Tester）

- 上轮 2 项 major 已验证修复，Tester 可选复验：① 起服务发请求，日志行含 `[trace_id]`（肉眼关联）；② 真实 agent 请求后 request_logs.usage 键为供应商名（不再是 "llm" 桶）。
- request_logs 3 行种子保留（id=1/3/4，勿删）。
