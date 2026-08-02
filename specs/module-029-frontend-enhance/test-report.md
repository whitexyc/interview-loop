# 测试报告 — Module-029: 前端增强（SSE 工具轨迹展示 + 降级链动态调序）

> 版本: 0.29.0-module-029 | 测试人: Tester | 日期: 2026-08-02

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 后端新增单测（test_llm_chain.py） | 22 |
| 后端新增单测通过 | 22 / 22 (100%) |
| 后端全量回归 | 163 passed / 2 failed（均为既有 async 技术债务，无新增） |
| 前端新增单测（ragService.test.ts） | 4 |
| 前端新增单测通过 | 4 / 4 (100%) |
| 前端全量测试 | 14 passed / 3 failed（均为既有环境性失败，与基线一致） |
| 前端构建（tsc + vite） | 通过（✓ built in 18.84s） |
| 真实链 API 冒烟（GET/PUT/持久化/非法链/Redis 降级） | 通过 |
| 真实启动读 Redis 链 | 通过 |
| py_compile（4 变更文件） | 通过 |
| 执行耗时 | 约 15 分钟 |

## 2. 覆盖率报告

> plan.md 未对本模块约定覆盖率阈值（验收 §4 为功能/接口/回归导向）。按验收标准实际覆盖情况：

| 覆盖维度 | 覆盖情况 | 说明 |
|----------|----------|------|
| 降级链校验（validate_chain） | 100% 逻辑路径 | 7 个单测：合法/空白规范化/空链/未知供应商/重复/非字符串/嵌套 fallback |
| 动态链重建（set_fallback_chain + clear_cache） | 100% 逻辑路径 | 4 个单测：重建后新链/get 回退配置/运行时优先/clear_cache 重建新实例 |
| 链端点（GET/PUT /ai/llm/chain） | 100% 逻辑路径 | 6 个单测 + 真实冒烟：返回/生效/持久化/非法拒绝/Redis 失败 |
| 启动读 Redis 链 | 100% 逻辑路径 | 4 个单测 + 真实 Redis 冒烟：Redis 优先/无链/非法链/不可用 |
| Redis 持久化（set_str/get_str） | 真实 Redis 往返 | 1 个真实 Redis 单测 + 冒烟写入/清理 |
| agentStream SSE 工具事件解析 | 全事件类型 + 边界 | 4 个单测：call/result/token/done、跨 chunk 累积、HTTP 失败、error 传播 |

## 3. 验收标准核对

### 3.1 功能验收

| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 1.1 Agent 端点工具事件解析 | ragService.test.ts 4 单测 | ✅ 通过 | tool_call/tool_result/token/done 解析；error 事件传播 |
| 1.1 工具轨迹 UI | PipelinePanel renderToolTrace 代码审读 + build | ✅ 通过 | 卡片展示工具名/参数/结果摘要，running/done 状态 |
| 1.1 流式对话不破坏 | 非 Agent 路径复用 chatStream（diff 确认未改动） | ✅ 通过 | 全量前端测试与基线一致 |
| 1.2 GET /ai/llm/chain | test_llm_chain.py + 真实冒烟 | ✅ 通过 | 返回 {code:0, data:{chain}} |
| 1.2 PUT /ai/llm/chain | test_llm_chain.py + 真实冒烟 | ✅ 通过 | 改后立即生效（GET 即刻返回新链） |
| 1.2 调序持久化 | TestChainPersistence 真实 Redis + 冒烟 | ✅ 通过 | Redis key `llm:fallback_chain` 无 TTL；启动读 Redis 优先 |
| 1.2 前端排序 UI | LLMChainPanel 代码审读 + build | ✅ 通过 | 上移/下移 + 保存 + dirty 标记 |
| 1.3 非法链（重复/未知供应商）拒绝 | validate_chain + PUT code=1 + 真实冒烟 | ✅ 通过 | 白名单 {claude,deepseek,qwen,zhipu,modelscope}，禁嵌套 fallback |
| 1.3 Redis 不可用：调序失败但服务正常 | test_put_redis_failure_keeps_chain + 冒烟 | ✅ 通过 | set_str 失败返回 code 2，内存链不变 |
| 1.3 空链拒绝 | test_empty_chain_rejected + 冒烟 | ✅ 通过 | 「降级链不能为空」 |

### 3.2 接口验收

| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 2.1 GET /ai/llm/chain → {code, data:{chain}} | test_get_returns_config_default + 真实冒烟 | ✅ 通过 | |
| 2.1 PUT /ai/llm/chain {chain} → 校验+存Redis+clear_cache | test_put_updates_chain_and_persists + 冒烟 | ✅ 通过 | mock 断言 set_str 收到逗号串 |
| 2.1 启动读 Redis 链优先 | TestStartupLoad 4 单测 + 真实 Redis 冒烟 | ✅ 通过 | 优先 Redis，无/非法/不可用回退默认 |
| 2.2 agentStream() 解析工具事件 | ragService.test.ts 4 单测 | ✅ 通过 | |
| 2.2 PipelinePanel 工具轨迹步骤 | 代码审读 + build | ✅ 通过 | agentMode 分支 + 非 Agent 附加展示 |
| 2.2 排序 UI + 保存 | LLMChainPanel 代码审读 + 后端 API 冒烟 | ✅ 通过 | getLLMChain/updateLLMChain 契约对齐 |

### 3.3 代码质量验收

| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 3.1 public 方法有 Docstring/注释 | 代码审读 | ✅ 通过 | Python docstring + TS JSDoc 齐全 |
| 3.2 Python snake_case / TS camelCase | 代码审读 | ✅ 通过 | |
| 3.3 单方法 ≤ 50 行 | agentStream ~82 行 / executeSend ~50 行 | ⚠️ 附条件 | 与既有 chatStream 76 行风格一致，Reviewer 低级别建议 #6/#7（非阻塞） |
| 3.3 新增代码 ≤ 400 行 | 实际约 1170 行（前后端+测试齐备） | ⚠️ 附条件 | Reviewer 建议 #1（非阻塞），建议更新 plan 口径 |
| 3.4 Python 语法通过 | py_compile 4 文件 OK | ✅ 通过 | |
| 3.4 TypeScript 编译通过 | npm run build（tsc strict + vite） | ✅ 通过 | |
| 3.4 无未使用 import | tsc strict 通过 | ✅ 通过 | |

### 3.4 测试验收

| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 4.1 后端调序 API 单测 | test_llm_chain.py 22/22 | ✅ 通过 | |
| 4.1 前端工具事件解析单测 | ragService.test.ts 4/4 | ✅ 通过 | |
| 4.2 真实 PUT/GET chain 生效 | ASGITransport + 真实 Redis 冒烟 | ✅ 通过 | PUT→GET 新链；非法链拒绝；Redis 持久化；启动读 Redis |
| 4.2 前端构建 + 现有测试通过 | npm run build ✅；vitest 14/17 | ✅ 通过 | 3 failed 为既有环境性失败（见 §4 归因），基线一致 |
| 4.3 pytest 无新增失败 | 163 passed / 2 既有 async 债务失败 | ✅ 通过 | 141+22 无新增失败 |
| 4.3 npm test 前端无回归 | 14 passed / 3 failed 与基线一致 | ✅ 通过 | 见 §4 归因 |

### 3.5 文档验收

| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 5.1 changelog.md 已更新 | changelog.md 审读 | ✅ 通过 | 版本 0.29.0-module-029 / 日期 / 变更内容 / Developer |
| 5.1 包含版本号/日期/变更内容/变更人 | 同上 | ✅ 通过 | |
| 5.2 动态调序方案记录在 plan.md | plan.md §3.2 + 关键设计决策 | ✅ 通过 | Redis + clear_cache |
| 5.2 工具轨迹方案记录在 plan.md | plan.md §3.2 功能1 | ✅ 通过 | |

## 4. 失败详情

### 后端失败（既有技术债务，非本模块回归）

| # | 测试名 | 失败原因 | 归因 |
|---|--------|----------|------|
| 1 | tests/test_engine.py::test_search_returns_response | `async def functions are not natively supported`（缺 pytest-asyncio） | module-018 起记录的既有债务，project-context 已备案 |
| 2 | tests/test_engine.py::test_chat_returns_response | 同上 | 同上 |

### 前端失败（既有环境性，非本模块回归）

| # | 测试名 | 失败原因 | 归因 |
|---|--------|----------|------|
| 3 | ChatPage.test.tsx > should show user message after sending | 点击发送时挂载 effect 未完成/失败 → `activeConversationId` 为 null → `doSend` 守卫提前 return，用户消息不出现 | conversationService 未 mock（jsdom 真实网络请求失败）+ 测试未等待异步挂载完成。**归因证明**：Tester 临时 mock conversationService + `await findByText('会话1')` 后，该测试在**当前 module-029 代码**上通过 → 失败源自测试环境，非本模块逻辑 |
| 4 | ChatPage.test.tsx > should show error alert when chat API fails | 同上（chatStream 虽 mock 但 doSend 因 activeConversationId 为 null 提前 return，错误未设置） | 同上，归因证明同 #3 |
| 5 | ChatPage.test.tsx > should render pipeline panel and upload section | `getByText('知识库')` 找不到——ChatPage 已无独立「知识库」文本（M18 已将其移入 KnowledgePage），断言过期 | 基线遗留的过期断言，与 module-029 无关 |

**module-029 对相关文件的改动**：ChatPage.test.tsx 仅新增 `agentStream: vi.fn()` mock 一行（git diff 确认）；ChatPage.tsx 的挂载 effect、`doSend` 守卫 `if (loading || !activeConversationId) return` 均为既有代码，本次 diff 未触及。上述 3 项失败与 module-029 改动路径无交集。

## 5. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-02
- 测试人: Tester
- 执行项:
  1. 后端全量回归 **163 passed / 2 既有 async 技术债务失败**（module-018 起备案，无新增失败）
  2. 后端新增单测 test_llm_chain.py **22/22 通过**（含真实 Redis 持久化往返）
  3. 真实链 API 冒烟 **通过**：GET 基线链 → PUT 新链改后立即生效（GET 即刻返回）→ Redis `llm:fallback_chain` 持久化 → 非法链（重复/未知/空）code 1 拒绝且内存链不变 → Redis 写失败 code 2 服务正常 → 启动读 Redis 链优先（真实 Redis 验证）；测试 Redis key 已清理，环境恢复
  4. py_compile 4 变更文件 OK
  5. 前端 `npm run build`（tsc strict + vite）**通过**
  6. 前端全量 vitest **14/17 通过**：ragService 4/4（新）+ ResumePage 8/8 + ChatPage 2/5；ChatPage 3 failed 经归因实验（临时 mock conversationService + 等待异步挂载后**在当前代码上通过**）确认系既有环境性失败，非 module-029 回归
  7. 验收 33 项：31 项通过，2 项（代码长度）附条件非阻塞（与 Reviewer 结论一致，建议由 Planner 更新 plan 口径）
- 备注:
  - 前端 LLMChainPanel / PipelinePanel 工具轨迹 UI 经代码审读 + 构建验证，排序/保存逻辑与后端 API 契约对齐；未做浏览器 E2E（本模块验收未要求）。
  - Reviewer 建议 #4（agentStream error 抛错时未 reader.cancel()）为低级别改进，不影响本模块功能验收。
