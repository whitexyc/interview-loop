# 代码审查报告 — Module-036: Agent 端点接入会话记忆

> 本文件由 **Reviewer（m36-reviewer）** 在代码审查阶段输出。
> 结论：**✅ 通过（无阻塞问题，4 项非阻塞建议）**，可进入测试阶段。

---

## 审查元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-036 |
| 模块名称 | Agent 端点接入会话记忆 |
| 审查日期 | 2026-08-07 |
| 审查人 | Reviewer（m36-reviewer） |
| 提交人 | Developer（m36-dev） |
| 审查轮次 | 第 1 轮 |
| 关联 plan.md | `specs/module-036-agent-memory/plan.md` |
| 关联 changelog.md | `specs/module-036-agent-memory/changelog.md` |
| 代码分支 | worktree-m8-knowledge-panel（工作区未提交，git diff 审查） |

---

## 一、独立复现结果（Reviewer 实测）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| Agent 工具单测（含新增） | `python -m pytest tests/test_agent_tools.py -q` | **27 passed**（21 基线 + 6 新增，与 Developer 一致） |
| LangGraph 回归 | `python -m pytest tests/test_rerank_langgraph.py -q` | **18 passed** |
| 全量回归 | `python -m pytest tests/ -q` | **298 passed / 0 failed**（292 基线 + 6 新增，3 个既有 Redis setex 弃用 warning 与模块无关） |
| 编译检查 | `python -m py_compile main.py agent/react.py agent/langgraph_react.py agent/tool_registry.py tests/test_agent_tools.py` | **OK** |
| 命名全量核对 | `grep ctx.client_ip / ReactContext(client_ip= / .client_ip\b`（ai_service/agent） | **0 残留**（agent 代码无 client_ip 记忆用途） |

新增单测 6 个核对（test_agent_tools.py 新增两个类）：
- `TestAgentSessionMemory` 4 个（agent 恢复持久化 / 无持久化回退 request.history / agent 完成后保存 / agent-lg 恢复+保存）
- `TestReactContextIdentity` 2 个（ctx.identity 字段 + 无 client_ip 残留 / recall_memory 按 ctx.identity 召回）

---

## 二、核心核对（任务 2）

### 2.1 agent/agent-lg 是否真走 `_resolve_session_history`（而非直接 request.history）— ✅ 通过

`main.py` 两处均先解析再构造 ctx：
- `/ai/rag/chat/agent` L516：`effective_history = await rag_engine._resolve_session_history(identity, request.history)` → L517 `ctx = ReactContext(request.query, identity, effective_history)`
- `/ai/rag/chat/agent-lg` L583-584 同

与 chat_stream Step 5（L460 `history = await rag_engine._resolve_session_history(identity, request.history)`）调用方式完全一致。**直接 `request.history` 的旧路径已移除**（git diff 确认 `ctx = ReactContext(request.query, identity, request.history)` 已不存在，仅此一行替换为会话恢复调用）。无持久化会话 / 恢复失败 / 身份为空 → `_resolve_session_history` 返回 `request.history or []`（engine.py L413-426），零回归。

### 2.2 会话保存是否在 react_loop / langgraph_react_loop 结束后触发（fire-and-forget 不阻塞 SSE）— ✅ 通过

两处均放在循环消费完（done 事件捕获 answer）后、最终 done 事件前：
- `agent` L546：`rag_engine._schedule_session_persist(identity, request.query, answer)`
- `agent-lg` L613：同

`_schedule_session_persist`（engine.py L428-442）内部 `asyncio.create_task(self._persist_session(...))` **只调度不 await**，后台写库不阻塞 SSE；`_persist_session` 异常全部降级捕获（logger.warning）。空 answer 守卫（`answer and answer.strip()`）在 engine.py L441 内部，与 chat/chat_stream 触发点一致。

`answer` 来源正确：循环内 done 事件被捕获到局部变量 `answer`（L530-532 / L588-590），持久化的是最终答案（含预算耗尽反射器兜底路径——兜底答案也在 done 事件里）。

**module-034 阻塞项（双重调度）专项核对**：agent 端点直接消费 `react_loop` / `langgraph_react_loop`，**不经 `engine.chat`**；循环本体、7 个工具、反射器均不调用 `_schedule_session_persist`。因此每个 agent 请求**恰好一个调度点**（main.py），无 TOCTOU check-then-insert 并发重复落库风险（与 module-034 阻塞的 chat 路径双重调度不同源）。

### 2.3 命名修正 client_ip → identity：grep 全量核对无遗漏引用、行为不变 — ✅ 通过

- `react.py`：`ReactContext.__init__` 参数 `client_ip → identity` + `self.identity` 属性 + docstring 全改（L63-79）；`react_agent` 参数同步改名（L119-139）
- `langgraph_react.py`：`langgraph_react_agent` 参数 `client_ip → identity`（L312-332）
- `tool_registry.py`：`_recall_memory` L189 用 `ctx.identity`（值不变，仅命名）；docstring 同步
- `main.py`：构造处本就走 `resolve_identity(fastapi_req)` 位置传参，无需改动

grep 全量核对：
- `ctx.client_ip` / `self.client_ip` / `ReactContext(client_ip=` → **0 处**（agent 目录）
- 全库剩余 `client_ip` 均为**语义正确的 IP 用途**，未误改：
  - `ratelimit.py`（限流按真实 IP，正确保留）
  - `main.py` `get_client_ip` / `request.state.client_ip` / `save_messages_to_session(client_ip, ...)` / `IP_SESSION_MESSAGES`（IP 会话兜底缓存，语义确为 IP，正确保留）
  - `identity.py` / `memory.py` / `session_memory.py` docstring（"identity = user_id 优先，否则 client_ip" 说明文字，正确保留）
- 调用方 `react_agent(...)` / `langgraph_react_agent(...)` / `ReactContext(...)` 全部**位置传参**（test_agent_tools.py / test_rerank_langgraph.py 实测），无 keyword `client_ip=` 调用 → 改名零破坏（18 passed 的 test_rerank_langgraph.py 实证）

### 2.4 无会话零回归（用 request.history）— ✅ 通过

`test_agent_uses_request_history_when_no_persisted` 实证：`_resolve_session_history` mock 为 `side_effect=lambda identity, h: h`（恒返回请求 history）时，LLM 消息历史含当前请求 history，行为与 module-036 之前一致。真实函数路径（engine.py L424-426）`return request_history or []` 同。

---

## 三、契约核对（任务 3）— ✅ 全部通过

| 契约 | 核对结果 |
|------|----------|
| agent/agent-lg 端点签名不变 | ✅ `main.py` diff 仅两端点内部新增会话解析/保存各 ~4 行，SSE 事件序列（tool_call/tool_result/token/done/error）与 done 事件字段（answer/sources/tool_count/budget）不变 |
| recall_memory 工具行为不变 | ✅ 仍调 `rag_engine._recall_memory(query, ctx.identity, top_k)`，仅字段名从 ctx.client_ip 改 ctx.identity（值相同），长短期召回行为不变 |
| 会话 source 不变 | ✅ 复用 `_schedule_session_persist` → `_persist_session` → `session_memory.save_session_messages`，`_session_source` = `memory:<identity>:session:`（session_memory.py L31/L35-42 确认未动） |
| 匿名降级不变 | ✅ `resolve_identity`（user_id 非空优先，否则 client_ip）未动；单测实测 XFF=10.0.0.8 → identity="10.0.0.8"（匿名降级正确） |

---

## 四、安全检查（任务 4）— ✅ 全部通过

- **无新注入面**：新增代码仅调用现有 `_resolve_session_history` / `_schedule_session_persist`（module-034 已审：SQLAlchemy 参数化 + `_normalize_identity` LIKE 转义双保险），无新 SQL、无新输入拼接、无新命令执行
- **会话按身份隔离**：恢复 `_resolve_session_history(identity, ...)` 与保存 `_schedule_session_persist(identity, ...)` 均按 identity（user_id 否则 client_ip）隔离；source 精确匹配防跨身份读取
- **日志无敏感**：新增代码无新日志输出（复用 engine 内部降级日志，仅记异常对象，不含 query/answer 内容）
- **无新依赖**：diff 未引入任何依赖（无需 ADR）

---

## 五、架构检查（任务 1 复核）

- **分层**：main.py（Controller，仅端点内部装配）；会话逻辑全部复用 engine 层现成函数（`_resolve_session_history` / `_schedule_session_persist`），无新增业务逻辑层、无跨层调用
- **依赖方向**：main.py → agent.react / agent.langgraph_react → rag.engine（既有方向），无反向依赖、无循环
- **代码量**：生产代码净增 ~28 行（main.py 两端点各 ~4 行有效 + 注释、react.py 字段改名、langgraph_react.py 参数改名、tool_registry.py 字段改名），**远低于 plan "≤150 行" 声明**
- **命名/注释**：Python snake_case（identity / effective_history）；新增/改动均有 `module-036` 标注注释；docstring 同步 identity 语义

---

## 六、验收标准核对（任务 6，按实际复选框 29 项）

> 注：acceptance-criteria.md 汇总表记 **29 项**，实际复选框 **29 项**（总数一致）；分项统计有出入——代码质量实为 6（3.1×1 + 3.2×1 + 3.3×2 + 3.4×2，表记 5）、测试实为 7（4.1×3 + 4.2×2 + 4.3×2，表记 8，4.4 为命令块无复选框）。建议验收签署时按实际分项修正。

### 1 功能验收（8 项）
| 项 | 验收点 | 结果 | 依据 |
|----|--------|------|------|
| 1.1-1 | agent 端点恢复持久化会话 | ✅ | main.py L516 `_resolve_session_history` + `test_agent_restores_persisted_session` |
| 1.1-2 | agent-lg 端点恢复持久化会话 | ✅ | main.py L583 同 + `test_agent_lg_restores_and_persists_session`（history 断言） |
| 1.1-3 | 无会话零回归 | ✅ | `_resolve_session_history` 回退 request.history + `test_agent_uses_request_history_when_no_persisted` |
| 1.2-1 | agent 完成后保存会话 | ✅ | main.py L546 `_schedule_session_persist` + `test_agent_persists_session_after_loop`（assert_called_once + 参数断言） |
| 1.2-2 | agent-lg 完成后保存会话 | ✅ | main.py L613 同 + `test_agent_lg_restores_and_persists_session`（persist 断言） |
| 1.2-3 | 会话落库 source 正确 | ✅ | 复用 `_schedule_session_persist` → `save_session_messages`（`memory:<identity>:session:` 契约不变，代码核验；真实落库留 Tester E2E） |
| 1.3-1 | ReactContext.client_ip → identity | ✅ | grep 0 残留 + `test_context_uses_identity_field`（`assert not hasattr(ctx, "client_ip")`） |
| 1.3-2 | recall_memory 工具语义 | ✅ | tool_registry L189 `ctx.identity` + `test_recall_memory_uses_ctx_identity`（args[1]=="user-42"） |

### 2 接口验收（4 项）— ✅ 全部通过（见 §三契约核对）

### 3 代码质量验收（6 项）
| 项 | 验收点 | 结果 |
|----|--------|------|
| 3.1-1 | public 方法 Docstring | ✅（ReactContext / react_agent / langgraph_react_agent docstring 已同步 identity 语义） |
| 3.2-1 | Python snake_case | ✅ |
| 3.3-1 | 单方法 ≤50 行 | ✅（本模块新增逻辑每端点 ≤4 行；`chat_agent`/`chat_agent_langgraph` 端点函数本体为 module-028/030 既有，见建议 #2） |
| 3.3-2 | 模块生产代码 ≤150 行 | ✅（净增 ~28 行） |
| 3.4-1 | py_compile 通过 | ✅（独立复现 OK） |
| 3.4-2 | 无未使用 import | ✅（生产代码 diff 无新增 import；test_agent_tools.py 新增 `ReactContext` 导入已使用） |

### 4 测试验收（7 项）
| 项 | 验收点 | 结果 | 依据 |
|----|--------|------|------|
| 4.1-1 | agent 端点会话恢复测试 | ✅ | `test_agent_restores_persisted_session` + `test_agent_uses_request_history_when_no_persisted` |
| 4.1-2 | agent 端点会话保存测试 | ✅ | `test_agent_persists_session_after_loop` |
| 4.1-3 | 命名修正后引用一致性 | ✅ | `test_context_uses_identity_field` + `test_recall_memory_uses_ctx_identity` |
| 4.2-1 | 全量 pytest 292 基线 + 新增 / 0 失败 | ✅ | **298 passed / 0 failed**（独立复现） |
| 4.2-2 | agent 工具回归 | ✅ | **27 passed**（独立复现）+ **test_rerank_langgraph.py 18 passed** |
| 4.3-1 | 真实 E2E：Agent 对话 → 会话落库 → 新对话恢复 | ⏳ 留 Tester | — |
| 4.3-2 | 真实 E2E：匿名按 client_ip 隔离 Agent 会话 | ⏳ 留 Tester | — |

### 5 文档验收（4 项）
| 项 | 验收点 | 结果 |
|----|--------|------|
| 5.1-1 | changelog.md 已更新 | ✅（版本/日期/变更/变更人齐全） |
| 5.2-1 | Agent 会话记忆方案记录在 plan.md | ✅（§3 技术方案 + §6.2 注意事项） |
| 5.3-1 | project-context.md 更新 | ✅（module-036 行 + 当前迭代状态"待 REVIEW"） |
| 5.3-2 | agent-activity-log.md 更新 | ✅（Developer [CODE] 行；本报告附 [REVIEW] 行） |

**核对汇总**：✅ 代码/单测核验 27 项 + ⏳ 留 Tester 真实 E2E 2 项。

---

## 七、发现的问题

### 阻塞问题
**无。**

### 非阻塞建议（4 项，不阻断测试阶段）

| 序号 | 严重度 | 问题描述 | 所在文件 | 位置 | 建议 |
|------|--------|----------|----------|------|------|
| 1 | 🟢 | acceptance-criteria.md 汇总表分项统计有出入：代码质量记 5 实际 6、测试记 8 实际 7（总数 29 一致；4.4 为命令块无复选框）。建议验收签署时按实际分项修正 | `specs/module-036-agent-memory/acceptance-criteria.md` | 汇总表 | 按 module-033/035 先例修正统计 |
| 2 | 🟢 | `chat_agent`（~57 行）/ `chat_agent_langgraph`（~59 行）端点函数本体超单方法 ≤50 行限制，但为 module-028/030 既有代码，本模块仅追加 ~2 行/端点，非本模块回归 | `ai_service/main.py` | L494-550 / L553-611 | 非本模块范围，记录即可；后续可抽公共事件处理函数收敛 |
| 3 | 🟢 | 会话保存 `answer` 来自循环内 done 事件捕获；若循环因 LLMException 提前抛错（降级链全失败），persist 不触发（走 error 分支）。此行为与 chat/chat_stream 一致（engine.chat 抛错时同样不触发 persist），非差异，仅记录 | `ai_service/main.py` | L546 / L613 | 行为合理（无 answer 不落库，与 `_schedule_session_persist` 空 answer 守卫语义一致），无需改动 |
| 4 | 🟢 | 会话恢复新增 3s 超时等待（`_resolve_session_history` 内 `asyncio.wait_for(timeout=3)`），agent 端点首事件延迟最坏 +3s（与 chat_stream Step 5 一致） | `ai_service/rag/engine.py` | L416-420 | 既有设计（module-034），与 chat 对齐，记录即可 |

### 需记录的 ADR
无（无架构决策变更；复用现成函数 + 命名修正均为低风险既有模式）。

---

## 审查总结

### 统计

| 类别 | 通过数 | 不通过数 | 不适用 |
|------|--------|----------|--------|
| 架构检查 | 4 | 0 | 0 |
| 编码规范检查 | 5 | 0 | 0 |
| 接口规范检查 | 4 | 0 | 0 |
| 安全检查 | 4 | 0 | 0 |
| 性能检查 | 3 | 0 | 0 |
| 验收标准核对 | 27 | 0 | 0（2 项 E2E 留 Tester） |
| 代码变更审查 | 6 | 0 | 0 |
| **合计** | **53** | **0** | **0** |

### 审查结论
- [x] ✅ **通过** — 核心四项全部实现正确：① agent/agent-lg 真走 `_resolve_session_history`（无持久化回退 request.history 零回归）；② 循环结束后 `_schedule_session_persist` fire-and-forget 不阻塞 SSE、空 answer 守卫、**单调度点无双重调度风险**（module-034 阻塞专项复核）；③ client_ip→identity 命名修正 grep 零残留、限流/IP 缓存语义正确未误改、行为不变；④ 契约（端点签名/SSE 格式/recall_memory/source/匿名降级）零变更。安全无新注入面、会话按身份隔离、日志无敏感。独立复现与 Developer 自测完全一致（agent 27 / rerank_langgraph 18 / 全量 298/0 / py_compile OK）。4 项非阻塞建议（均为 🟢 低级别）记录于 §七。
- 真实 E2E（4.3-1/2）留 Tester 验收。

### 审查人签名
- 审查人：Reviewer（m36-reviewer）
- 日期：2026-08-07
- 结论：✅ 通过
