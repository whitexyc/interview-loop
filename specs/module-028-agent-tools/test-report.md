# 测试报告 — Module-028: Agent 工具化（ToolRegistry + ReAct 循环）

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 新增单测（tests/test_agent_tools.py） | 21 |
| 新增单测通过数 | 21 |
| 新增单测失败数 | 0 |
| 新增单测跳过数 | 0 |
| 新增单测通过率 | 100% |
| 新增单测执行耗时 | 47.5 s |
| 全量回归用例总数 | 143 |
| 全量回归通过数 | 141 |
| 全量回归失败数 | 2（既有 async 技术债务，非本模块回归） |
| 回归新增失败 | 0 |
| 全量回归执行耗时 | 53.5 s |
| 真实 LLM E2E（ReAct 循环） | ✅ 通过（deepseek-v4-flash，工具 4 次 ≤ budget 4，26.1s） |
| 真实 SSE E2E（/ai/rag/chat/agent） | ✅ 通过（工具 4 次，事件 tool_call/tool_result/token/done 齐全，0 error） |
| 真实 E2E（/ai/rag/chat 无回归，重排 mock） | ✅ 通过（真实 LLM + 真实检索，21.5s） |
| 语法检查 py_compile（6 文件） | ✅ OK |

## 2. 覆盖率报告

| 覆盖维度 | 覆盖率 | 要求 | 状态 |
|----------|--------|------|------|
| 单元测试（本模块新增） | 21/21 用例，覆盖 ToolRegistry / chat_with_tools / ReAct / SSE 端点全部验收项 | 验收 §4.1 | ✅ |
| 集成测试（真实 LLM / 真实 SSE / 真实 /ai/rag/chat） | ReAct 真实执行 + SSE 真实事件流 + 既有端点真实链路 | 验收 §4.2 / §4.3 | ✅ |
| 回归测试 | 141/143 通过，2 失败为既有 async 债务 | 100% 无新增失败 | ✅ |

> 说明：本模块为 Python 服务且以集成/链路验证为主，plan.md 与 acceptance-criteria.md 未对覆盖率百分比设硬性指标，按「每个验收项 ≥1 个测试用例」执行（见 §3 逐项核对）。

## 3. 验收标准核对

### 3.1 功能验收（acceptance-criteria.md §1）

| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| 1.1 ToolRegistry 注册工具 | `python -c` 注册验证 + test_builtin_tools_registered | ✅ 通过 | 实测 7 工具，顺序与验收一致 |
| 1.1 LLM 工具调用 | 真实 deepseek ReAct + test_openai_path_returns_content_and_tool_calls | ✅ 通过 | 真实输出 tool_call 并执行 |
| 1.1 ReAct 循环 | 真实 ReAct + test_tool_call_then_direct_answer | ✅ 通过 | 一次不够自动调下一工具（search_knowledge→search_fts 多轮） |
| 1.1 工具预算 | 真实 ReAct（4 ≤ 4）+ test_budget_exhausted_fallback_generation | ✅ 通过 | 预算=总次数上限 |
| 1.1 SSE 工具轨迹 | 真实 SSE E2E + test_sse_tool_trace_events | ✅ 通过 | tool_call/tool_result/token/done |
| 1.1 并存端点 | /ai/rag/chat 真实 E2E + 全量回归 | ✅ 通过 | 既有端点零改动 |
| 1.2 预算=0：直接生成 | test_budget_zero_direct_answer_without_tools | ✅ 通过 | 不调工具直接 chat |
| 1.2 预算耗尽：兜底生成 | test_budget_exhausted_fallback_generation + 真实日志「工具预算耗尽...兜底生成」 | ✅ 通过 | 用已收集 docs 生成 |
| 1.2 工具执行失败：返回空 | test_tool_failure_returns_empty_and_continues + test_tool_run_failure_returns_empty | ✅ 通过 | LLM 判断继续 |
| 1.2 LLM 直接回答（无 tool_call） | test_endpoint_uses_settings_budget | ✅ 通过 | token+done 正常结束 |
| 1.3 LLM 调用失败：降级链切下一供应商 | 独立 mock 测试（qwen 失败→zhipu 成功；全失败→LLMException） | ✅ 通过 | FallbackClient.chat_with_tools 链遍历正确 |
| 1.3 工具崩溃：不整链路崩 | test_tool_run_failure_returns_empty | ✅ 通过 | AgentTool.run 统一捕获 |
| 1.3 死循环：预算防住 | while tool_count < budget + test_budget_exhausted | ✅ 通过 | 天然防死循环 |

### 3.2 接口验收（acceptance-criteria.md §2）

| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| 2.1 注册工具带 name/description/args_schema | test_to_llm_schemas_format | ✅ 通过 | |
| 2.1 list_tools() 返回已注册工具 | test_builtin_tools_registered / test_register_builtin_tools_into_custom_registry | ✅ 通过 | |
| 2.1 内置工具齐全（7 个） | `registry.list_tool_names()` | ✅ 通过 | search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/generate_answer |
| 2.2 chat_with_tools 返回 {content, tool_calls} | test_openai_path_returns_content_and_tool_calls / test_no_tool_calls_returns_empty_list | ✅ 通过 | 含 message 供回传 |
| 2.2 tool_calls 格式（name + args） | 同上 + 真实 SSE tool_call 事件 | ✅ 通过 | |
| 2.2 各供应商兼容（deepseek/qwen/zhipu） | test_openai_path_*（OpenAI 系）+ test_bind_path_for_non_openai（Claude）| ✅ 通过 | 真实 deepseek 已验；qwen/zhipu 走同一 OpenAI 系路径 |
| 2.3 react_agent 返回 {answer, tool_count, tool_trace} | 真实 ReAct + test_tool_call_then_direct_answer | ✅ 通过 | |
| 2.3 预算为总次数上限 | 真实 ReAct（4≤4）+ test_default_budget_from_settings | ✅ 通过 | settings.max_agent_tools=4 |
| 2.4 POST /ai/rag/chat/agent（SSE） | 真实 SSE E2E + test_sse_tool_trace_events | ✅ 通过 | HTTP 200 |
| 2.4 事件: tool_call / tool_result / token / done | 真实 SSE E2E | ✅ 通过 | 实测事件序列：tool_call→tool_result→(token)→done；4 tool_call / 4 tool_result / 2 token / 1 done / 0 error |
| 2.4 现有 /ai/rag/chat 不变 | git diff（仅新增端点）+ 全量回归 + 真实 E2E | ✅ 通过 | main.py 变更纯新增；/ai/rag/chat、/ai/rag/chat/stream 零改动 |

### 3.3 代码质量验收（acceptance-criteria.md §3）

| 验收项 | 验证方式 | 状态 | 备注 |
|--------|----------|------|------|
| 3.1 public 方法有 Docstring | 阅读 tool_registry.py / react.py / client.py | ✅ 通过 | |
| 3.1 ReAct 循环逻辑有行内注释 | 阅读 react.py | ✅ 通过 | 预算/降级/回传均有注释 |
| 3.2 snake_case / 无无意义命名 | 阅读全部新文件 | ✅ 通过 | |
| 3.3 单个方法 ≤ 50 行 | react_loop 约 90 行 | ⚠️ 附注 | Reviewer 建议 #1（plan 已预估 ReAct 约 120 行，记录为已知豁免，不阻塞） |
| 3.3 本模块新增代码 ≤ 400 行（plan 已申请调整） | 约 690 行 | ⚠️ 附注 | plan.md 预申请调整上限，Reviewer 建议 #6，不阻塞 |
| 3.4 Python 语法通过 | `python -m py_compile` 6 文件 | ✅ 通过 | |
| 3.4 无未使用 import | 逐一核对（Reviewer 已核 + Tester 抽查） | ✅ 通过 | |

### 3.4 测试验收（acceptance-criteria.md §4）

| 验收项 | 验证方式 | 状态 | 备注 |
|--------|----------|------|------|
| 4.1 ToolRegistry 注册/解析单测 | test_agent_tools.py TestToolRegistry（7 个） | ✅ 通过 | |
| 4.1 ReAct 循环单测（预算/降级/直接回答） | TestReactAgent（预算/兜底/预算=0/失败继续/docs 累积/reasoning 回传/默认预算） | ✅ 通过 | |
| 4.1 LLMClient 工具接口 mock 单测 | TestChatWithTools（OpenAI 路径/Claude bind 路径/reasoning 保留/失败异常） | ✅ 通过 | |
| 4.2 真实 LLM 工具调用（deepseek ≥1 家） | 真实 deepseek-v4-flash ReAct：search_knowledge + search_fts 共 4 次 | ✅ 通过 | 触发真实 tool_call 并执行 |
| 4.2 ReAct 循环真实执行（预算内完成） | `react_agent('Java线程池核心参数', budget=4)` → tool_count=4 ≤ 4，真实带引用答案 | ✅ 通过 | 26.1s；reasoning_content 回传无 400 |
| 4.3 `pytest ai_service/tests/ -x` 无新增失败 | 全量 141 passed / 2 既有 async 债务 | ✅ 通过 | 2 失败为 test_engine.py 缺 pytest-asyncio（module-018 起记录，非本模块） |
| 4.3 现有 /ai/rag/chat 无回归 | 代码 diff + 全量回归 + 真实 E2E（重排 mock，真实 LLM+检索） | ✅ 通过 | 真实返回 200/message=ok/5 sources |

### 3.5 文档验收（acceptance-criteria.md §5）

| 验收项 | 验证方式 | 状态 |
|--------|----------|------|
| 5.1 changelog.md 已更新（版本/日期/变更内容/变更人） | changelog.md v1 2026-08-02 | ✅ 通过 |
| 5.2 ToolRegistry / ReAct / 预算方案记录在 plan.md | plan.md §3 | ✅ 通过 |
| 5.2 SSE 工具轨迹格式记录在 plan.md | plan.md §3.2 | ✅ 通过 |

## 4. 失败详情

无本模块失败。全量回归的 2 个失败为**既有技术债务**（非 module-028 回归）：

### 失败 #1 / #2（既有，回归基线）
- 测试名: tests/test_engine.py::test_search_returns_response / test_chat_returns_response
- 验收项: 回归测试无新增失败
- 失败原因: `async def functions are not natively supported` — 测试环境缺 `pytest-asyncio`，模块级 `async def` 用例无法被 pytest 收集。该问题自 module-018 起记录于 project-context.md，module-024/025/026/027/028 全量回归均出现，与本模块变更无关（本模块未触碰 test_engine.py / engine.chat / engine.search）。
- 堆栈信息:
```
FAILED tests/test_engine.py::test_search_returns_response - Failed: async def functions are not natively supported.
FAILED tests/test_engine.py::test_chat_returns_response - Failed: async def functions are not natively supported.
```
- 关联文件: ai_service/tests/test_engine.py:L6, L12（既有）
- 修复建议: 安装 pytest-asyncio（既有债务，非本模块范围）

## 5. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-02
- 测试人: Tester
- 通过率: 新增单测 21/21（100%）；全量回归 141/143（2 既有 async 债务，0 新增失败）

### 环境备注
1. **真实 /ai/rag/chat 全链路 E2E（含真实重排）受限**：本机 Qwen3-Reranker-0.6B 为生成式模型（module-018），CPU 逐对评分 batch（20→5）运行 >20 分钟无进展，属既有环境性能问题（非 module-028 变更所致，本模块未触碰 reranker/engine）。已用「真实 LLM + 真实检索 + 重排 mock」验证 /ai/rag/chat 端点链路无回归（200/message=ok/5 sources），并通过全量回归 141 passed 佐证。
2. **真实 deepseek 验证成功**：deepseek-v4-flash（thinking 模式）工具调用真实执行，`reasoning_content` 回传机制（chat_with_tools 走 async_client.create）验证通过，无 400。
3. Reviewer 建议 #2/#3（降级链 chat_with_tools 单测、预算截断单测）中，降级链已由 Tester 独立 mock 验证通过；预算截断路径经代码核对（react.py L211-214 只执行预算内 tool_calls）与既有单测覆盖，可随后续迭代补强。
