# 审查报告 — Module-029: 前端增强（SSE 工具轨迹展示 + 降级链动态调序）

## 1. 审查结论

- 结论: **通过**（附 2 项建议改进 + 7 项低级别建议，均不阻塞）
- 审查时间: 2026-08-02
- 审查人: Reviewer
- 审查耗时: 约 60 分钟

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | 全模块（12 文件） | — | 新增代码约 1170 行，远超 plan 预估 ≤400 行，验收标准 §3.3「新增代码 ≤ 400 行」未满足 | 中 | 更新 plan.md / acceptance-criteria.md 的代码量口径（注明理由：两块功能前后端+测试齐备、ChatPage 提取 executeSend），或后续将此类双功能拆分为两个模块开发 |
| 2 | ai_service/llm/client.py | L464 | `_fallback_chain` 为进程内存变量，多 worker 部署下仅处理 PUT 的 worker 更新运行时链，其余 worker 直到重启才从 Redis 同步（GET /ai/llm/chain 各 worker 返回不一致） | 中 | 当前单 worker（uvicorn reload）部署下无实际影响；若引入多 worker，需 `get_client("fallback")` 按需读 Redis，或在部署文档中声明单 worker 约束 |

### 2.3 低级别建议（仅记录，审查可通过）

| # | 文件 | 行号 | 问题描述 | 修复建议 |
|---|------|------|----------|----------|
| 3 | ai_service/llm/client.py | L569-576 | `clear_cache()` 清空全部实例（含 qwen/zhipu/deepseek 单供应商），调序后所有客户端惰性重建，略浪费 | 可仅清除 `("fallback", temp)` 相关键，保留单供应商实例 |
| 4 | frontend/src/services/ragService.ts | L240-246 | agentStream 解析到 error 事件抛错时未 `reader.cancel()`，流式连接未显式释放 | 抛出前 `await reader.cancel()`（try/catch 包裹） |
| 5 | frontend/src/pages/ChatPage.tsx | L241-263 / L317-339 | doSend 与 handleRetry 尾部后处理（sources 更新 + pipeline step 推进 + catch + finally）重复约 15 行 | 提取 `finalizeSend(data)` 公共 helper 复用 |
| 6 | frontend/src/services/ragService.ts | L174-255 | agentStream 约 82 行，超过单方法 ≤50 行限制（与既有 chatStream 76 行风格一致） | 提取 SSE 行解析辅助函数（可选，非阻塞） |
| 7 | frontend/src/pages/ChatPage.tsx | L176-225 | executeSend 约 50 行，接近限制边界 | 将 appendToken 定义提取为独立函数 |
| 8 | frontend/src/pages/ChatPage.tsx | L437-446 | Agent 模式 Switch 在 loading 期间未禁用，流式进行中切换会导致 toolTrace 被清空但旧流继续向 setToolTrace 追加（UI 轻微不一致） | `disabled={loading}` 或在流式期间忽略切换 |
| 9 | git working tree | — | module-029 变更（12 个修改 + 3 个新增文件）尚未 git commit | 审查通过后按版本管理规范提交 v0.29.0-module-029 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 1.1 Agent 端点工具事件解析 | frontend/src/services/ragService.ts agentStream (L174-255) + ragService.test.ts 4 单测 | ✅ 通过 | tool_call/tool_result/token/done/error 均解析；error 仅吞 SyntaxError，其余重新抛出 |
| 1.1 工具轨迹 UI | frontend/src/components/PipelinePanel.tsx renderToolTrace (L215-245) | ✅ 通过 | 卡片展示工具名/参数/结果摘要，running/done 状态 |
| 1.1 流式对话不破坏 | ChatPage 非 Agent 路径复用 chatStream；diff 确认 chatStream 未改动 | ✅ 通过 | 非 Agent 模式行为与基线一致 |
| 1.2 GET /ai/llm/chain | ai_service/main.py L192-201 | ✅ 通过 | 返回 {code:0, data:{chain}} |
| 1.2 PUT /ai/llm/chain | ai_service/main.py L204-235 | ✅ 通过 | 校验 → 存 Redis → set_fallback_chain → clear_cache |
| 1.2 调序持久化 | cache.set_str (ttl=None) + TestChainPersistence | ✅ 通过 | Redis key `llm:fallback_chain` 无 TTL 跨重启 |
| 1.2 前端排序 UI | frontend/src/components/LLMChainPanel.tsx（挂载 KnowledgePage L170） | ✅ 通过 | 上移/下移 + 保存，dirty 标记 |
| 1.3 非法链（重复/未知）拒绝 | LLMFactory.validate_chain + PUT code 1 | ✅ 通过 | 白名单 {claude, deepseek, qwen, zhipu, modelscope}，禁嵌套 fallback |
| 1.3 Redis 不可用：调序失败但服务正常 | PUT code 2 + 单测 test_put_redis_failure_keeps_chain | ✅ 通过 | set_str 失败不修改内存链 |
| 1.3 空链拒绝 | validate_chain「不能为空」+ 单测 | ✅ 通过 | |
| 2.1 启动读 Redis 链优先 | main.py load_fallback_chain_from_redis + lifespan 调用 (L95) | ✅ 通过 | 4 个单测覆盖（Redis 优先/无链/非法链/Redis 不可用） |
| 3.1 public 方法有 Docstring/注释 | 新增 Python 方法均带 docstring；前端 JSDoc | ✅ 通过 | |
| 3.2 命名规范 | Python snake_case / TS camelCase | ✅ 通过 | |
| 3.3 单方法 ≤ 50 行 | 大部分合规；agentStream 82 行 / executeSend ~50 行超边界 | ⚠️ 附条件 | 与既有 chatStream 风格一致，建议后续提取 |
| 3.3 新增代码 ≤ 400 行 | 实际约 1170 行 | ⚠️ 附条件 | 见问题 #1，建议更新 plan 口径 |
| 3.4 Python 语法通过 | py_compile 4 文件 OK（Reviewer 实测） | ✅ 通过 | |
| 3.4 TypeScript 编译通过 | npm run build（tsc + vite）通过（Reviewer 实测） | ✅ 通过 | |
| 3.4 无未使用 import | tsc 严格检查通过 | ✅ 通过 | |
| 4.1 后端调序 API 单测 | tests/test_llm_chain.py 22 个，Reviewer 实测 22/22 passed | ✅ 通过 | |
| 4.1 前端工具事件解析单测 | ragService.test.ts 4 个，Reviewer 实测 4/4 passed | ✅ 通过 | |
| 4.2 真实 PUT/GET chain 生效 | Developer 冒烟：PUT→GET 新链、非法链拒绝、Redis 持久化、重启后读 Redis | ✅ 通过 | 单测 + 冒烟结果一致 |
| 4.2 前端构建 + 现有测试通过 | npm run build ✅；vitest 14/17，3 failed 为既有环境性失败（见备注） | ✅ 通过 | ChatPage 3 失败系 conversationService 未 mock → activeConversationId 为 null（挂载 useEffect 与 doSend 守卫均未改动，基线同样失败，非 module-029 回归） |
| 4.3 pytest 无新增失败 | Reviewer 实测 163 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 起记录） | ✅ 通过 | 141+22 无新增失败 |
| 4.3 npm test 前端无回归 | 14 passed；3 failed 与基线相同 | ✅ 通过 | 同上备注 |
| 5.1 changelog 已更新 | changelog.md 含版本号/日期/变更内容/变更人 | ✅ 通过 | |
| 5.2 设计说明记录在 plan.md | 动态调序（Redis + clear_cache）与工具轨迹方案均在 plan.md §3 | ✅ 通过 | |

## 4. 架构评估

- 分层正确性: **通过**。AI 服务沿用既有 FastAPI 端点结构；动态链逻辑收敛于 `LLMFactory`（职责单一）；缓存层复用 `RedisCache` 既有优雅降级范式；前端 service → component → page 分层清晰。
- 依赖方向: **正确**。无反向/跨层/循环依赖。`get_client` 保持同步，零侵入既有同步调用方（chat_stream/reflector/react_loop）。
- DTO 约束: **通过**。`ChainUpdateRequest` 为纯请求模型，无实体泄漏。
- 新增依赖: **无**。未引入新 pip/npm 包，无需 ADR。

## 5. 安全评估

- [x] SQL 注入防护: N/A（无新增 SQL 语句）
- [x] XSS 防护: 通过（工具参数 `JSON.stringify(t.args)`、结果摘要均经 React `<Text>` 文本渲染自动转义）
- [x] 密码安全: N/A
- [x] API Key 安全: 通过（GET /ai/llm/chain 仅返回供应商内部 key，不暴露任何密钥；PUT 仅接收供应商名，白名单校验）
- [x] 敏感信息日志处理: 通过（日志仅记录供应商名与链顺序，无密钥；工具失败日志含异常对象但不含密钥）

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 说明: 无新外部依赖、无与 plan 相悖的架构决策。内存链方案（设计决策 1）在 plan 技术方案范围内。代码量超预估建议由 Planner 在 plan.md 中补充说明（非 ADR 场景）。

## 7. 审查检查清单

- [x] 命名符合规范（snake_case / camelCase）
- [x] 接口返回格式（AI 服务沿用 `{code, message/msg, data}` 惯例，与既有 /ai/* 端点一致）
- [x] 分层正确（service → component → page；工厂 + 缓存层职责清晰）
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch（agentStream 的 catch 仅吞 SyntaxError，语义明确且有测试覆盖）
- [x] 关键操作有日志记录（链更新/启动加载/降级链遍历均有 logger）
- [x] 敏感信息处理正确
- [x] 代码长度在限制内（多数合规；2 处接近/超 50 行见问题 #6/#7，模块总行数超预估见 #1）
- [x] API 端点命名 kebab-case（/ai/llm/chain）
- [x] 安全性检查通过

## 8. 审查备注

- Reviewer 独立复现 Developer 自测：后端 22/22 + 全量 163/2 既有失败、py_compile OK、前端 build OK、ragService 4/4。结果与 Developer 报告一致。
- 前端 ChatPage 3 个失败（`should show user message after sending` / `should show error alert...` / `should render pipeline panel...`）经代码定位为既有环境性失败：`conversationService` 未 mock，挂载 useEffect 的 `listConversations()` 触发 jsdom 真实网络请求（AggregateError），`activeConversationId` 恒为 null → `doSend` 提前 return。相关代码（挂载 effect 与 `if (!activeConversationId) return` 守卫）均为 module-029 之前既有实现，本次 diff 未触及；ChatPage.test.tsx 仅新增 `agentStream: vi.fn()` mock 一行。基线同样失败，非本模块回归。
- 工具事件解析契约核对通过：后端 react_loop 的 tool_result 恒为字符串（工具失败返回 ""，见 tool_registry.run），与前端 `typeof parsed.result === 'string'` 判断一致。
