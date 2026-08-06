# 测试报告 — module-036: Agent 端点接入会话记忆

> 📋 本文件由 Tester（m36-tester）维护，记录该模块的测试执行结果和验收结论。
> 验收结论已在 `acceptance-criteria.md` 签署：✅ **通过**。

---

## 模块信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-036 |
| 模块名称 | Agent 端点接入会话记忆 |
| 开发计划 | `specs/module-036-agent-memory/plan.md` |
| 验收标准 | `specs/module-036-agent-memory/acceptance-criteria.md` |
| 变更日志 | `specs/module-036-agent-memory/changelog.md` |
| 审查报告 | `specs/module-036-agent-memory/review-report.md` |
| 测试员 | Tester（m36-tester） |
| 测试日期 | 2026-08-07 |

---

## 1. 测试环境

| 字段 | 内容 |
|------|------|
| 后端框架 | Python FastAPI（ai_service） |
| 数据库 | PostgreSQL 15+（真实库 personal_website，5432） |
| 缓存 | Redis（6379） |
| 测试框架 | pytest 9.1.1 / Python 3.11.15 |
| 平台 / OS | Windows 11 |
| 已知环境坑 | ① 缺 pytest-asyncio（既有技术债务，module-018 起备案，本模块用例用 asyncio.run 规避）；② Windows ProactorEventLoop 下 asyncpg 连接池不可跨 `asyncio.run()` 复用（E2E 脚本需单 loop）；③ 3 个既有 Redis `setex` DeprecationWarning 与模块无关 |
| 依赖前置 | 真实 DeepSeek / ModelScope LLM key（.env 已配置）；真实 PG + Redis |
| 运行环境 | 本地开发环境（worktree-m8-knowledge-panel） |
| 测试命令 | `cd ai_service && python -m pytest tests/ -q` |
| 变更文件 | `ai_service/main.py` / `agent/react.py` / `agent/langgraph_react.py` / `agent/tool_registry.py` / `tests/test_agent_tools.py` |

---

## 2. 单元测试

### 2.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试文件数（agent 相关） | 2（test_agent_tools.py + test_rerank_langgraph.py） |
| 测试用例总数（agent 相关） | 45（27 + 18） |
| 通过 | 45 |
| 失败 | 0 |
| 跳过 | 0 |
| 其中 module-036 新增 | 6（TestAgentSessionMemory 4 + TestReactContextIdentity 2） |
| 覆盖率要求 | 模块内核心方法均已覆盖（不强制全量覆盖率，按 plan 约定） |

### 2.2 新增/更新用例明细（module-036 核心核对）

| 测试类 | 测试方法 | 场景描述 | 结果 |
|--------|----------|----------|------|
| `TestAgentSessionMemory` | `test_agent_restores_persisted_session` | 有持久化会话 → 恢复的 history 进入 ctx（LLM 消息历史含持久化条目 + 当前问题最后） | ✅ |
| `TestAgentSessionMemory` | `test_agent_uses_request_history_when_no_persisted` | 无持久化会话 → 回退当前请求 history（零回归） | ✅ |
| `TestAgentSessionMemory` | `test_agent_persists_session_after_loop` | agent 循环结束后触发 `_schedule_session_persist(identity, query, answer)`（assert_called_once + 参数断言：identity=XFF IP / query / answer） | ✅ |
| `TestAgentSessionMemory` | `test_agent_lg_restores_and_persists_session` | agent-lg 会话恢复 + 完成后保存（与 agent 一致） | ✅ |
| `TestReactContextIdentity` | `test_context_uses_identity_field` | ctx.identity 字段存在且无遗留 client_ip（`assert not hasattr(ctx, "client_ip")`） | ✅ |
| `TestReactContextIdentity` | `test_recall_memory_uses_ctx_identity` | `_recall_memory` 工具按 ctx.identity 召回（args[1]=="user-42"，行为不变仅命名） | ✅ |

> `TestAgentSessionMemory._post` 用 httpx ASGITransport + mock 全链路（LLMFactory.get_client / `_resolve_session_history` / `_schedule_session_persist`），
> 不依赖真实 DB/Redis/LLM；同步用例内 asyncio.run 执行（套件同款模式）。

### 2.3 失败用例详情

> 无失败用例。

| 测试方法 | 预期结果 | 实际结果 | 失败原因 | 归类 | 严重度 |
|----------|----------|----------|----------|------|--------|
| — | — | — | — | — | — |

---

## 3. 集成测试

### 3.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试场景数 | 3（真实 E2E） |
| 通过 | 3 |
| 失败 | 0 |

### 3.2 测试场景明细（真实 E2E：uvicorn 8001 真实 HTTP 栈 + 真实 PG/Redis/DeepSeek，匿名 XFF 注入）

| 场景 | 描述 | 前置条件 | 预期结果 | 实际结果 | 状态 |
|------|------|----------|----------|----------|------|
| Agent 对话 → 会话落库 | 匿名 XFF=203.0.113.55 调 /ai/rag/chat/agent | AI 服务 8001 + 真实 PG/Redis/LLM | 会话消息写入 source=`memory:203.0.113.55:session:` | 真实落库 2 行（session:user + session:assistant），source 精确正确 | ✅ |
| 新对话恢复持久化会话 | 同 IP 再次调 agent（request.history 为空） | 已有持久化会话 | `_resolve_session_history` 优先持久化会话 | 二次对话 answer 连贯（1208 字符）且新轮次追加落库（2+2=4 行，无重复），恢复链路生效 | ✅ |
| 匿名按 client_ip 隔离 | IP_A=203.0.113.55 / IP_B=203.0.113.56 各自调 agent/agent-lg | 真实服务 | source 按身份隔离，互不串读 | IP_A 4 行 / IP_B 仅自己 2 行，无跨身份泄漏 | ✅ |

> E2E 细节：
> - 场景 1 SSE 事件序列：`tool_call/tool_result/tool_call/tool_result/token/tool_call/tool_result/tool_call/tool_result/token/done`，done 事件含 answer(355字) + tool_count=4 + sources=5，0 error。
> - 场景 2 第二轮 request.history 为空数组，`_resolve_session_history` 返回持久化会话 → 第二轮 answer 引用上轮主题（线程池队列）连贯，证明恢复生效。
> - 场景 3 用 /ai/rag/chat/agent-lg 验证 LangGraph 端点同样落库+隔离（2 行/身份），匿名降级 XFF → identity=client_ip 正确。
> - 测试数据已清理（203.0.113.55/56 残留 0 行）。

---

## 4. 回归测试

### 4.1 回归范围

| 已有模块 | 是否受影响 | 回归测试数 | 结果 |
|----------|-----------|-----------|------|
| module-028 agent 工具（test_agent_tools.py） | 是（新增会话接入 + 命名修正） | 27 | 全过 |
| module-030 LangGraph（test_rerank_langgraph.py） | 是（langgraph_react_agent 参数改名） | 18 | 全过 |
| module-034 会话记忆（test_session_memory.py） | 否（复用函数未动） | 11 | 全过 |
| module-025 流式记忆（test_stream_memory.py） | 否 | 5 | 全过 |
| module-032 身份（test_identity.py） | 否（resolve_identity 未动） | 20 | 全过 |
| 全量套件 | — | 298 | 全过 |

### 4.2 回归结果

| 统计项 | 值 |
|--------|-----|
| 回归测试总数 | 298（292 基线 + 6 新增） |
| 通过 | 298 |
| 失败 | 0 |
| 通过率要求 | 100% |
| 实际通过率 | 100%（0 失败） |

> Tester 独立复现与 Developer 自测 / Reviewer 独立复现完全一致（agent 27 / 全量 298 / 身份 20 / 会话 11 / 流式 5 / LangGraph 18）。
> 3 个既有 Redis `setex` DeprecationWarning（tests/test_cache.py）与模块无关。

---

## 5. 环境性失败归因

> 本模块测试过程中无**用例失败**，无环境性失败需要归因。记录以下环境观察（均不阻塞）：

| 现象 | 判断标准 | 归类 | 处理方式 |
|------|----------|------|----------|
| 全量回归首次运行 92.35s / 二次 85.24s（bge-m3 嵌入 + 重排测试耗时） | 既有性能特性，非失败 | 环境观察 | 不影响测试结论 |
| 库内残留 3 行 `memory:203.0.113.71:session:`（module-034 测试 IP，遗留数据） | 非本模块写入（本模块测试 IP 55/56 已清理为 0） | 环境观察（既有残留） | 记录不阻塞；建议后续清理（非本模块范围） |

---

## 6. 真实环境冒烟

> 单元 / 回归全部通过后，启动真实 AI 服务（uvicorn 8001，真实 PG/Redis/DeepSeek），沿验收核心路径端到端执行。

### 冒烟环境

- 真实 PG + 真实 Redis + 真实 DeepSeek（fallback 链；ModelScope key 亦已配置）
- 匿名降级路径：X-Forwarded-For 注入身份（无 JWT token，验证 client_ip 隔离）
- 测试身份 203.0.113.55 / 203.0.113.56（TEST-NET-3 保留网段），结束后全部清理

### 冒烟结果

| 冒烟项 | 命令/方式 | 结果 | 是否通过 |
|--------|-----------|------|----------|
| 服务健康 | GET /ai/health | status=ok | ✅ |
| Agent 对话 → 会话落库 | POST /ai/rag/chat/agent（XFF=203.0.113.55） | HTTP 200，SSE tool_call×4/tool_result×4/token×2/done，answer 355 字；落库 2 行 source=`memory:203.0.113.55:session:`（user+assistant） | ✅ |
| 新对话恢复 | 同 IP 二次 POST（history=[]） | answer 连贯（1208 字，引用上轮主题）；落库 2+2=4 行无重复 | ✅ |
| 匿名 client_ip 隔离 | IP_A agent + IP_B agent-lg 各自对话 | IP_A 4 行 / IP_B 2 行，source 精确隔离无串读 | ✅ |
| 数据真实落库 + 清理 | 清理后查残留 | 203.0.113.55/56 各 0 行 | ✅ |

---

## 7. 异常兜底测试

| 测试场景 | 输入 | 预期行为 | 实际行为 | 结果 |
|----------|------|----------|----------|------|
| 无持久化会话恢复 | request.history 非空、无持久化 | 回退 request.history（零回归） | 单测 `test_agent_uses_request_history_when_no_persisted` 通过 | ✅ |
| 空 request.history + 无持久化 | history=[] | 用空 history（行为与 module-036 前一致） | 单测 + E2E 场景 2 恢复持久化会话 | ✅ |
| 空 answer 不落库 | LLM 异常提前抛错（error 分支） | 不触发 `_schedule_session_persist`（与 chat 路径一致） | 代码核验：persist 在循环正常完成后触发；异常走 error 分支（Reviewer 建议 #3 记录，行为合理） | ✅ |
| 恢复失败降级 | `_resolve_session_history` 内部 DB 异常 | 返回 request.history or []（零回归） | engine.py L421-426 既有降级逻辑（module-034 已测） | ✅ |
| 身份为空 | identity="" | `_resolve_session_history` 返回 request.history；persist guard 跳过 | engine.py L413-414 / L441 既有逻辑 | ✅ |

---

## 8. 验收标准核对

> 逐项核对 `acceptance-criteria.md`（实际复选框 **29 项**：功能 8 / 接口 4 / 代码质量 6 /
> 测试 7 / 文档 4；原汇总表「代码质量 5 / 测试 8」已按实际修正——module-033/035 先例）。

### 功能验收（8 项）— 全部通过

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 1.1-1 agent 端点恢复持久化会话 | `test_agent_restores_persisted_session` + 真实 E2E 场景 2（恢复链路生效） | ✅ |
| 1.1-2 agent-lg 端点恢复持久化会话 | `test_agent_lg_restores_and_persists_session`（history 断言） | ✅ |
| 1.1-3 无会话零回归 | `test_agent_uses_request_history_when_no_persisted` | ✅ |
| 1.2-1 agent 完成后保存会话 | `test_agent_persists_session_after_loop`（assert_called_once + 参数断言）+ 真实 E2E 落库 | ✅ |
| 1.2-2 agent-lg 完成后保存会话 | `test_agent_lg_restores_and_persists_session`（persist 断言）+ 真实 E2E（agent-lg 落库 2 行） | ✅ |
| 1.2-3 会话落库 source 正确 | 真实 E2E：source=`memory:203.0.113.55:session:`（复用 module-034 `_session_source`，契约不变） | ✅ |
| 1.3-1 ReactContext.client_ip → identity | grep 0 残留（agent 目录）+ `test_context_uses_identity_field`（`assert not hasattr(ctx, "client_ip")`） | ✅ |
| 1.3-2 recall_memory 工具语义 | `test_recall_memory_uses_ctx_identity`（args[1]=="user-42"）+ tool_registry L189 `ctx.identity` | ✅ |

### 接口验收（4 项）— 全部通过

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 2.1-1 agent/agent-lg 端点签名不变 | git diff 核对（仅内部新增会话解析/保存）+ 真实 SSE 调用（事件序列与 done 字段不变） | ✅ |
| 2.1-2 recall_memory 工具行为不变 | `test_recall_memory_uses_ctx_identity`（值不变，仅字段名）+ 27 全量 agent 回归 | ✅ |
| 2.1-3 会话 source 格式不变 | 复用 `_schedule_session_persist` → `save_session_messages`（`memory:<identity>:session:`，session_memory.py 未动） | ✅ |
| 2.1-4 匿名降级不变 | `resolve_identity`（user_id 否则 client_ip）未动 + 真实 E2E XFF=203.0.113.55 → identity="203.0.113.55" | ✅ |

### 代码质量验收（6 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 3.1-1 所有 public 方法有 Docstring | ✅（ReactContext / react_agent / langgraph_react_agent docstring 已同步 identity 语义） |
| 3.2-1 Python snake_case | ✅ |
| 3.3-1 单方法 ≤50 行 | ✅（本模块新增逻辑每端点 ≤4 行；chat_agent 端点函数本体为 module-028/030 既有，见建议 #2） |
| 3.3-2 模块生产代码 ≤150 行 | ✅（净增 ~28 行，远低于 plan 声明） |
| 3.4-1 py_compile 通过 | ✅（Tester 独立复现 5 文件 OK） |
| 3.4-2 无未使用 import | ✅（生产代码 diff 无新增 import；test_agent_tools.py 新增 ReactContext 导入已使用） |

### 测试验收（7 项）— 全部通过

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 4.1-1 agent 端点会话恢复测试 | `test_agent_restores_persisted_session` + `test_agent_uses_request_history_when_no_persisted` | ✅ |
| 4.1-2 agent 端点会话保存测试 | `test_agent_persists_session_after_loop` | ✅ |
| 4.1-3 命名修正后引用一致性 | `test_context_uses_identity_field` + `test_recall_memory_uses_ctx_identity` + grep 0 残留 | ✅ |
| 4.2-1 全量 pytest 0 失败 | **298 passed / 0 failed**（Tester 独立复现） | ✅ |
| 4.2-2 agent 工具回归 | **27 passed**（Tester 独立复现）+ test_rerank_langgraph 18 passed | ✅ |
| 4.3-1 真实 E2E：Agent 对话 → 会话落库 → 新对话恢复 | 真实 E2E：落库 memory:203.0.113.55:session: + 二次对话恢复（连贯引用 + 无重复追加） | ✅ |
| 4.3-2 真实 E2E：匿名按 client_ip 隔离 | 真实 E2E：IP_A 4 行 / IP_B 2 行，无跨身份泄漏 | ✅ |

### 文档验收（4 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 5.1-1 changelog.md 已更新 | ✅（v1 2026-08-07，Developer） |
| 5.2-1 Agent 会话记忆方案记录在 plan.md | ✅（§3 技术方案 + §6.2 注意事项） |
| 5.3-1 project-context.md 更新 | ✅（module-036 行 + 技术决策，本次 Tester 标记 ✅ 完成） |
| 5.3-2 agent-activity-log.md 更新 | ✅（PLAN/CODE/REVIEW 已记录；本次 Tester 追加 [TEST] 行） |

---

## 9. 测试结论

### 总结

| 统计项 | 值 |
|--------|-----|
| 单元测试通过率 | 27/27 (100%) |
| 集成测试（真实 E2E）通过率 | 3/3 (100%) |
| 回归测试通过率 | 298/298 (100%) |
| 异常兜底测试通过率 | 5/5 (100%) |
| 真实环境冒烟通过率 | 5/5 (100%) |
| **总体验收结论** | **✅ 通过** |

### 验收结论

- [x] ✅ **通过** — 所有测试通过，验收标准全部满足（29/29），建议合并
- [ ] ❌ **不通过** — 存在失败用例，需 Developer 修复后重新测试
- [ ] ⚠️ **有条件通过** — 核心路径通过，非核心问题可后续修复

### 签署

| 字段 | 内容 |
|------|------|
| 测试人 | Tester（m36-tester） |
| 签署时间 | 2026-08-07 |
| 结论 | 通过 |
| 记忆库同步确认 | project-context 状态已标记 ✅ / file-index 已更新 ✅ / agent-activity-log 已追加 ✅ |

### 失败详情

> 无失败项。未执行 0 项（真实 E2E 已全部执行，非跳过）。

---

## 10. Reviewer 建议复核（Tester 实测）

| 序号 | 建议 | Tester 复核结论 |
|------|------|-----------------|
| #1 | acceptance 汇总表分项统计有出入（代码质量记 5 实际 6、测试记 8 实际 7） | **已修正**：汇总表按实际复选框 29 项修正（功能 8 / 接口 4 / 代码质量 6 / 测试 7 / 文档 4），module-033/035 先例 |
| #2 | `chat_agent`（~57 行）/ `chat_agent_langgraph`（~59 行）端点函数本体超单方法 ≤50 行 | **确认非本模块回归**：为 module-028/030 既有代码，本模块仅追加 ~2 行/端点（会话解析 1 行 + persist 1 行），diff 核对无误；后续可抽公共事件处理函数（非本模块范围） |
| #3 | 循环因 LLMException 提前抛错时 persist 不触发（走 error 分支） | **确认行为合理**：与 chat/chat_stream 一致（engine.chat 抛错同样不触发 persist）；且 `_schedule_session_persist` 空 answer 守卫语义一致，无 answer 不落库正确。真实 E2E 正常路径持久化确认 |
| #4 | 会话恢复新增 3s 超时等待，agent 端点首事件延迟最坏 +3s | **确认既有设计**：`_resolve_session_history` 内 `asyncio.wait_for(timeout=3)` 为 module-034 既有实现，与 chat_stream Step 5 对齐，非本模块新增；真实 E2E 正常 DB 路径 <3s（未触发超时） |

---

## 11. 改进建议

| 建议 | 优先级 | 建议处理时间 |
|------|--------|-------------|
| `chat_agent` / `chat_agent_langgraph` 端点事件处理逻辑（tool_call/tool_result/token/done 解析 + sources 组装 + persist）重复，可抽公共函数收敛（Reviewer #2） | 低 | 后续模块 |
| 库内残留 `memory:203.0.113.71:session:` 3 行（module-034 测试 IP 遗留），建议后续统一清理 | 低 | 后续模块 |
| 会话持久化写入与 chat 路径共用 documents 表，长期增长依赖 `memory_session_max_messages=50` 滚动上限；无物理清理任务，属既有设计 | 低 | 后续模块 |
| 测试数据已全部清理（203.0.113.55/56 残留 0 行）；临时 E2E 脚本已删除 | — | 已完成 |
