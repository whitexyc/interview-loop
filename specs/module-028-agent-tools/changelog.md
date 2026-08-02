# 变更日志 — Module-028: Agent 工具化（ToolRegistry + ReAct 循环）

## 变更概述

把固定 RAG 流水线升级为 Agentic ReAct 循环：LLM 自主决定调用哪些工具、以什么顺序，直到可回答或达到工具总调用次数预算。新增 ToolRegistry（7 个内置工具包装现有检索/图/记忆/生成方法）、LLMClient 工具调用接口、ReAct 循环核心（react_agent 非流式 + react_loop 异步生成器共用）、`/ai/rag/chat/agent` SSE 端点、`max_agent_tools` 预算配置。现有 `/ai/rag/chat`、`/ai/rag/chat/stream` 不变（并存，可 A/B 对比）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/agent/tool_registry.py | 新增 | ToolRegistry + 7 个内置工具（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory/generate_answer），包装 hybrid_retriever / graph_store / graph_extractor / engine._recall_memory / reflector |
| ai_service/agent/react.py | 新增 | ReAct 循环：ReactContext（会话上下文）+ react_agent（非流式入口）+ react_loop（异步生成器，SSE 复用） |
| ai_service/llm/client.py | 修改 | 基类 LLMClient 新增 chat_with_tools（ChatOpenAI 系走底层客户端保留 reasoning_content，Claude 走 bind_tools）；FallbackClient 覆写遍历降级链 |
| ai_service/main.py | 修改 | 新增 POST /ai/rag/chat/agent（SSE，事件 tool_call/tool_result/token/done/error） |
| ai_service/src/config.py | 修改 | 新增 max_agent_tools 配置项（默认 4，开发可调大） |
| ai_service/tests/test_agent_tools.py | 新增 | 单测 21 个：ToolRegistry / chat_with_tools / ReAct 循环（预算/降级/直接回答/reasoning_content 回传）/ SSE 端点 |

## 关键设计说明

### 设计决策 1: 工具执行绑定会话上下文，注册表全局无状态复用
- 决策: 工具 func 签名 `async def (ctx, args)`，ctx（ReactContext：query/client_ip/history/累积 docs/记忆）由 ReAct 循环每次调用注入；全局 `registry` 单例只存工具定义，无共享可变状态。
- 原因: 检索工具需累积 docs 到会话（供 generate_answer/兜底），记忆工具需 client_ip（按 IP 隔离）。ctx 显式传参使注册表可跨多请求并发复用，避免按会话重建注册表。

### 设计决策 2: ReAct 核心为异步生成器 react_loop，react_agent 与 SSE 端点共用
- 决策: `react_loop(ctx, messages, budget)` 逐事件产出（tool_call/tool_result/token/done）；`react_agent`（非流式，返回 {answer, tool_count, tool_trace}）与 main.py 的 SSE 端点都消费同一生成器。
- 原因: 避免非流式与流式两条路径逻辑重复；事件化输出天然适配 SSE 工具轨迹（验收场景 4）。

### 设计决策 3: DeepSeek thinking 模式 reasoning_content 回传（关键修复）
- 决策: chat_with_tools 对 ChatOpenAI 系（deepseek/qwen/zhipu）改走底层 OpenAI 兼容客户端 `async_client.create`，返回原始 assistant 消息 dict（含 reasoning_content + 原始 tool_calls），ReAct 循环原样追加到消息历史并在下一轮回传。
- 原因: 实测 deepseek-v4-flash（thinking 模式）要求把上一轮 assistant 消息的 `reasoning_content` 原样回传，否则 400 `reasoning_content must be passed back`；LangChain `bind_tools` 会丢弃该字段（langchain-openai 1.4.1 实测）。bind_tools 仅保留给 Claude（ChatAnthropic，无此问题）。本决策是对 plan.md「用 bind_tools」实现细节的必要修正（已验证三家 function calling 仍兼容）。

### 设计决策 4: 工具总次数预算 + 预算耗尽兜底 + 预算=0 直接回答
- 决策: while `tool_count < budget`；预算耗尽用 `reflector.generate_answer(ctx.docs)` 兜底生成；预算=0 时 LLM 不带工具直接 chat 回答；工具失败由 AgentTool.run 统一捕获返回空串，LLM 判断继续/放弃。
- 原因: 预算为循环总上限防空转烧钱（验收场景 3）；工具失败返回空沿用降级哲学；budget=0 满足边界验收。

### 设计决策 5: assistant 工具调用消息只含实际执行的 tool_calls
- 决策: 追加 assistant 消息时按本轮实际执行的 tool_call id 过滤原始 tool_calls（保留原样 arguments 字符串），再逐条追加 tool 结果消息。
- 原因: OpenAI/DeepSeek 要求 assistant 消息中声明的 tool_calls 必须有对应 tool 结果；预算截断（一次返回多个 tool_call 但预算不足）时避免产生无对应结果的孤立声明导致下轮 400。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法检查 | `python -m py_compile src/config.py llm/client.py agent/tool_registry.py agent/react.py main.py tests/test_agent_tools.py` | 通过 |
| 新增单测 | `python -m pytest tests/test_agent_tools.py -q` | 21 passed |
| ToolRegistry 注册 | `python -c "from agent.tool_registry import registry; print([t.name for t in registry.list_tools()])"` | 7 个内置工具 |
| ReAct 真实 LLM | `python -c "import asyncio; from agent.react import react_agent; asyncio.run(react_agent('Java线程池核心参数', budget=4))"` | 工具次数 ≤ 4，答案生成 |
| SSE 端点 E2E | `POST /ai/rag/chat/agent`（httpx ASGITransport） | 200，事件含 tool_call/tool_result/token/done |
| 全量回归 | `python -m pytest tests/ -q` | 138 passed / 2 既有 async 技术债务失败（非本次回归） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始实现：ToolRegistry + ReAct + chat_with_tools + SSE 端点 + 预算配置 | Developer |
