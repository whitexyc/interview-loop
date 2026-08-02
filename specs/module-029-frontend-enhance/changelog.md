# 变更日志 — Module-029: 前端增强（SSE 工具轨迹展示 + 降级链动态调序）

> 版本: 0.29.0-module-029 | 变更人: Developer | 日期: 2026-08-02

## 变更概述

本模块包含两部分增强：
1. **SSE 工具轨迹前端展示**：module-028 后端 `/ai/rag/chat/agent` 已推送 tool_call/tool_result/token/done SSE 事件，前端此前未展示。本模块新增 `agentStream()` 解析函数 + ChatPage「Agent 模式」开关 + PipelinePanel 工具轨迹卡片，让用户可视化 Agent 正在调用什么工具。
2. **降级链动态调序**：降级链顺序原为 `.env` 静态配置（`PW_FALLBACK_CHAIN`），调整需重启。本模块新增 `GET/PUT /ai/llm/chain` API，链存 Redis（跨重启持久），PUT 后 `clear_cache()` 重建 FallbackClient 即时生效，并新增前端排序 UI。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/src/cache.py | 修改 | 新增 `get_str`/`set_str` 字符串读写（链存 Redis，ttl=None 持久） |
| ai_service/llm/client.py | 修改 | 动态链：`validate_chain`/`set_fallback_chain`/`get_fallback_chain` + `get_client("fallback")` 读运行时链 |
| ai_service/main.py | 修改 | 新增 `GET/PUT /ai/llm/chain` + `load_fallback_chain_from_redis()`（lifespan 启动时调用） |
| ai_service/tests/test_llm_chain.py | 新增 | 22 个单测：validate_chain/动态链重建/端点/启动加载/真实 Redis 往返 |
| frontend/src/types/rag.ts | 修改 | 新增 `ToolCallEvent`/`ToolResultEvent`/`ToolTrace` 类型 |
| frontend/src/services/ragService.ts | 修改 | 新增 `agentStream()`（解析工具事件）+ `getLLMChain()`/`updateLLMChain()` |
| frontend/src/components/PipelinePanel.tsx | 修改 | 新增 `agentMode` + `toolTrace` props，工具轨迹卡片渲染 |
| frontend/src/pages/ChatPage.tsx | 修改 | Agent 模式开关 + `executeSend` 分支（agentStream/chatStream）+ 工具轨迹状态 |
| frontend/src/components/LLMChainPanel.tsx | 新增 | LLM 供应商顺序排序 UI（上下移 + 保存） |
| frontend/src/pages/KnowledgePage.tsx | 修改 | 挂载 LLMChainPanel |
| frontend/src/__tests__/ragService.test.ts | 新增 | 4 个单测：工具事件解析/跨 chunk 累积/HTTP 失败/error 事件 |
| frontend/src/__tests__/ChatPage.test.tsx | 修改 | mock 补充 `agentStream` |

## 关键设计说明

### 设计决策 1: 链存 Redis 但 `get_client` 保持同步
- 决策: Redis 是异步、`LLMFactory.get_client` 是同步类方法（被全链路同步调用）。用 `LLMFactory._fallback_chain` 内存变量承载运行时链；PUT 端点异步写 Redis 后更新内存变量 + `clear_cache()`；启动时 lifespan 异步读 Redis 赋给内存变量。`get_client` 只读内存变量。
- 原因: 若把 `get_client` 改异步将波及所有调用方（chat_stream/reflector/react_loop 等），破坏面大；内存变量方案零侵入、保持调用方不变。

### 设计决策 2: PUT 严格失败（Redis 不可用 → 调序不生效）
- 决策: `cache.set_str` 返回 False 时，PUT 返回 `{code: 2, message}`，不调用 `set_fallback_chain`/`clear_cache`，内存链保持原样。
- 原因: 验收要求「Redis 不可用：调序失败但服务正常」。写不进去就不能假装生效（重启即丢），且与内存状态保持一致。

### 设计决策 3: agentStream 错误事件不被吞掉
- 决策: SSE 解析的 `catch` 仅吞 `SyntaxError`（JSON 解析失败 = 非 JSON 数据行），`error` 事件抛出的 `Error` 继续传播。
- 原因: 后端 `error` 事件（如「服务暂时不可用」）应展示给用户；若与 JSON 解析失败共用 catch 吞掉，用户看不到错误。修正了 chatStream 中同类潜在的吞错模式（本模块仅改新函数，不动既有代码）。

### 设计决策 4: 工具轨迹用 `tool_count` 匹配 call/result
- 决策: ChatPage 收到 tool_call 追加 `{...tool, status: 'running'}`；收到 tool_result 用 `tool_count` 精确匹配更新为 `done`。
- 原因: `tool_count` 每次调用唯一，比「最后一条 + 工具名匹配」更稳，避免 React 状态更新竞态。

### 设计决策 5: 白名单校验（禁嵌套 fallback）
- 决策: `validate_chain` 白名单 = {claude, deepseek, qwen, zhipu, modelscope}；拒绝空链、未知供应商、重复、非字符串。
- 原因: 降级链上的元素必须是可实例化的单供应商，不允许嵌套 fallback（否则无限递归）。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 后端链单测 | `python -m pytest tests/test_llm_chain.py` | 22 passed |
| 后端全量回归 | `python -m pytest tests/ -q` | 163 passed / 2 既有 async 技术债务失败（无新增） |
| py_compile | `python -m py_compile main.py llm/client.py src/cache.py tests/test_llm_chain.py` | OK |
| 实时 API | `curl GET/PUT /ai/llm/chain` | GET 返回当前链；PUT 生效；非法链拒绝；重启后读 Redis |
| 前端构建 | `npm run build` | tsc + vite build 通过 |
| 前端测试 | `npm test` | 17 tests：ragService 4/4 + ResumePage 8/8 + ChatPage 2/5（3 个为既有环境性失败，基线相同） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始实现 | Developer |
