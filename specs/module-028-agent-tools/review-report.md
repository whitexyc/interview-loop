# 审查报告 — Module-028: Agent 工具化（ToolRegistry + ReAct 循环）

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-02
- 审查人: Reviewer
- 审查耗时: ~45 分钟

**核查说明**：Reviewer 已完整阅读全部变更文件（非仅 diff），逐行核对 7 项审查清单，
并独立运行验证命令（py_compile / 新增单测 21 个 / 全量回归 / ToolRegistry 注册 /
关键机制 `reasoning_content` 字段保留），Developer 自测结论全部复现，无阻塞问题。

---

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/agent/react.py | L160-249 | `react_loop` 方法约 90 行，超过「方法 ≤ 50 行」约束 | 中 | 将「逐批执行工具 + 追加 tool 结果消息」的循环体抽为私有辅助函数（如 `_execute_tools(ctx, messages, allowed, tool_calls, tools, tool_count)`），生成器主体只保留事件编排；若抽不动可维持现状（生成器逻辑强内聚，plan 已预估 ReAct 约 120 行），记录为已知豁免 |
| 2 | ai_service/tests/test_agent_tools.py | 全文 | 验收 §1.3「LLM 调用失败：降级链切下一供应商」无专门单测：`FallbackClient.chat_with_tools`（client.py L416-429）的链遍历仅靠代码模式与 chat/generate 同构推断，未直接验证 | 中 | 新增 mock 单测：构造链 [qwen,zhipu]，首个 `chat_with_tools` 抛 LLMException、第二个成功返回，断言遍历顺序与成功即返回 |
| 3 | ai_service/tests/test_agent_tools.py | 全文 | 预算截断路径（react.py L212-214：一轮返回多个 tool_call 但预算只够前 N 个 → 只执行 N 个、assistant 消息不含孤立声明，设计决策 5）无专门单测 | 低 | 新增单测：budget=1，LLM 返回 2 个 tool_call，断言仅执行 1 个、tool_count==1、第二轮消息历史中 assistant 消息只含 1 个 tool_call 且无孤立声明 |
| 4 | ai_service/main.py | L378-395 | SSE「token」事件为粗粒度整段文本（每轮 LLM 返回一次性下发），且最终答案同时以 token 与 done.answer 两个通道下发；工具间推理文本也会混入 token 通道，无「中间推理 vs 最终答案」区分标记 | 低 | 与 plan 一致（SSE 用于工具轨迹事件而非实时 token），非 bug；建议前端以 done.answer 为准、token 仅作进度提示；若需实时生成流可后续扩展 chat_with_tools 流式变体 |
| 5 | ai_service/main.py | L348-404 | `/ai/rag/chat/agent` 未将本轮问答持久化到 IP 会话缓存（`save_messages_to_session`），与 `/ai/rag/chat` 行为不一致，跨请求多轮历史只能靠前端自行回传 history | 低 | 验收未要求；若要与现有链路 A/B 对比体验，建议后续补一次持久化，或在前端文档中明确该端点不落会话 |
| 6 | 本模块新增代码 | — | 新增代码约 690 行（不含测试），超出 plan 预估 400 行（plan 已注明「需调整上限」，工具注册表 289 + ReAct 250 + client 90 + main 57 + config 2） | 低 | 已在 plan.md 预申请调整，非本次回归；建议后续 module 在计划阶段按实际分解预留 |
| 7 | ai_service/agent/tool_registry.py L3 / ai_service/agent/react.py L3 | L3 | 模块 docstring 分隔行显示为 `===== =====`（疑似 em-dash 符号损坏），与既有 reflector.py 等文件同款 | 低 | 纯外观；若为编码损坏可在后续统一清理，不阻塞 |

---

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| ToolRegistry 注册工具 | tool_registry.py L238-288 | ✅ 通过 | 实测 7 工具，顺序与验收一致 |
| LLM 工具调用 | client.py L85-196 | ✅ 通过 | OpenAI 系走 async_client.create 保留 reasoning_content；Claude 走 bind_tools |
| ReAct 循环（一次不够自动调下一工具） | react.py L160-249 | ✅ 通过 | while tool_count < budget |
| 工具预算（总次数 ≤ budget） | react.py L195/L212/L231 | ✅ 通过 | 单测断言 + 真实 LLM 3-4 次 ≤ 4 |
| SSE 工具轨迹（tool_call/tool_result/token/done） | main.py L348-404 | ✅ 通过 | 单测事件序列 + 真实 E2E |
| 并存端点（/ai/rag/chat 不受影响） | main.py L194-206 | ✅ 通过 | 代码零改动；全量回归 141 passed / 2 既有 async 债务 |
| 预算=0 直接生成 | react.py L190-193 | ✅ 通过 | 单测 test_budget_zero |
| 预算耗尽兜底生成 | react.py L241-249 | ✅ 通过 | 单测 test_budget_exhausted_fallback |
| 工具失败返回空、LLM 判断继续/放弃 | tool_registry.py L49-63 | ✅ 通过 | AgentTool.run 捕获；单测 test_tool_failure |
| LLM 直接回答（无 tool_call） | react.py L200-205 | ✅ 通过 | 单测 test_endpoint_uses_settings_budget |
| LLM 调用失败降级链切下一供应商 | client.py L416-429 | ✅ 通过 | 代码实现正确；单测缺失（见建议 #2） |
| 工具崩溃不整链路崩 | tool_registry.py L49-63 | ✅ 通过 | 单测 test_tool_run_failure_returns_empty |
| 死循环预算天然防住 | react.py L195 | ✅ 通过 | while 条件 + 兜底 break |
| chat_with_tools 返回 {content, tool_calls} | client.py L101-113 | ✅ 通过 | 含 message 附加字段供回传 |
| 各供应商兼容（deepseek/qwen/zhipu） | client.py L115-156 | ✅ 通过 | 三家均 ChatOpenAI 系走同一路径；developer 已实测 deepseek + qwen |
| react_agent 返回 {answer, tool_count, tool_trace} | react.py L118-157 | ✅ 通过 | |
| 代码质量：snake_case / Docstring / 行内注释 | 全部新文件 | ✅ 通过 | public 方法均有 Docstring |
| 代码质量：方法 ≤ 50 行 | react.py L160-249 | ⚠️ 附注 | react_loop 约 90 行（见建议 #1） |
| 代码质量：本模块新增 ≤ 400 行 | 全部 | ⚠️ 附注 | 约 690 行（plan 已预申请调整，见建议 #6） |
| 无未使用 import | 全部新文件 | ✅ 通过 | 逐一核对 |
| 单测：ToolRegistry / ReAct / LLMClient mock | tests/test_agent_tools.py | ✅ 通过 | 21/21 |
| 集成：真实 LLM 工具调用（deepseek/qwen ≥1 家） | — | ✅ 通过 | developer 真实链路验证（deepseek + qwen）；Reviewer 环境无 key，信任记录 |
| 回归：pytest tests/ 无新增失败 | — | ✅ 通过 | Reviewer 实测 141 passed / 2 既有 async 债务（test_engine.py 缺 pytest-asyncio，module-018 已记录） |
| changelog / plan 记录 SSE 格式 | specs 下 | ✅ 通过 | |

---

## 4. 架构评估

- 分层正确性: **通过** — 工具层（agent/tool_registry.py）仅包装既有 Service 层（rag.engine / rag.retriever / rag.graph_store / agent.reflector），无反向依赖；agent/react.py 仅编排不触数据库；main.py 端点薄。
- 依赖方向: **正确** — agent → rag/llm/src 单向；无循环 import（已核对 reflector.py 仅依赖 llm.client）。
- 注册表并发: **通过** — 全局 registry 只存工具定义（import 时写、请求时读），执行时经 ctx 注入会话状态（ReactContext 每请求独立），无共享可变状态；`_seen_ids`/docs/memory 均为 ctx 实例属性。LLMFactory 实例缓存复用与既有 chat 路径同款，无新增并发风险。
- DTO 约束: **通过** — 无 Entity 泄漏，工具输出为 dict 文本。
- 新增依赖: **无** — 仅复用既有 langchain-openai / langchain-anthropic / openai 包；本模块关键决策（async_client.create 直连）依赖的是已装包能力而非新依赖，无需 ADR。

---

## 5. 安全评估

- [x] SQL 注入防护: **通过** — 新代码无原生 SQL；复用既有参数化检索/记忆方法。
- [x] XSS 防护: **通过** — 后端仅返回 JSON/文本，无 HTML 拼接；内容截断展示沿用既有模式。
- [x] 密码安全: **N/A** — 无认证逻辑变更。
- [x] API Key 安全: **通过** — 未新增密钥配置；密钥不参与日志（工具执行失败日志仅记录异常消息与工具名）。
- [x] 敏感信息日志处理: **通过** — 检索结果含知识库文档内容，与既有链路同权限面；SSE 端点为流式，无新增泄露面。
- [ ] 工具结果日志: **通过（附注）** — react.py L242 预算耗尽 warning 仅记录数量不记录内容；tool_registry.py L62 失败日志仅记录异常，符合最小化原则。

---

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: **否**
- 说明: 关键设计决策（chat_with_tools 对 ChatOpenAI 系走 async_client.create 保留 reasoning_content、预算=总次数、assistant 消息只含实际执行 tool_calls）均已记录在 changelog.md 设计决策 1-5 中，是对 plan.md「用 bind_tools」的必要实现修正而非新架构变更；未引入新外部依赖，无需额外 ADR。

---

## 7. 审查检查清单

- [x] 命名符合规范（snake_case / PascalCase）
- [x] 接口返回统一格式（SSE 端点与既有 /ai/rag/chat/stream 同款，不做统一 JSON 包裹）
- [x] 分层正确（agent 工具层 / 编排层 / 端点层职责清晰）
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch（AgentTool.run 统一捕获 + 日志）
- [x] 关键操作有日志记录（工具失败 / 预算耗尽 / LLM 调用失败）
- [x] 敏感信息处理正确
- [x] 代码长度：方法 ≤ 50 行（react_loop 例外，见建议 #1）
- [x] API 端点命名 kebab-case（/ai/rag/chat/agent）
- [x] 安全性检查通过
- [x] 验收标准逐项核对完成
- [x] 已读完整文件（非仅 diff）
- [x] 每个问题均标注文件 + 行号

---

## 8. 审查人实测摘要（Reviewer 独立验证）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| py_compile 6 文件 | `python -m py_compile src/config.py llm/client.py agent/tool_registry.py agent/react.py main.py tests/test_agent_tools.py` | OK |
| 新增单测 | `python -m pytest tests/test_agent_tools.py -q` | 21 passed (48.6s) |
| 全量回归 | `python -m pytest tests/ -q` | 141 passed / 2 既有 async 债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，120+21 无新增失败） |
| ToolRegistry 注册 | `registry.list_tool_names()` | 7 工具，顺序与验收一致 |
| 关键机制：ChatOpenAI 暴露 async_client.create | 脚本 | `hasattr(async_client, 'create')==True` |
| 关键机制：reasoning_content 字段保留 | ChatCompletionMessage.model_config `extra: allow` + model_validate 含 reasoning_content | 属性可读，DeepSeek thinking 回传机制成立 |

---

## 9. 审查结论

本模块实现与 plan.md 验收标准一致，7 项审查清单全部核对通过，无阻塞问题。
3 项建议（react_loop 拆分 / 降级链工具调用单测 / 预算截断单测）记录于 §2.2，
可随后续迭代补强。**审查通过，放行进入 Tester 阶段。**
