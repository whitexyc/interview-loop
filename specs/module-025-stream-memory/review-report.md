# 审查报告 — Module-025: 流式记忆接入

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: ~20 分钟
- 验证命令（已实测）:
  - `python -m pytest ai_service/tests/test_stream_memory.py -v` → 5 passed
  - `python -m pytest ai_service/tests/` → 101 passed, 2 failed（均为 `tests/test_engine.py` 既有 async 技术债务：缺 pytest-asyncio，"async def functions are not natively supported"，module-018 已记录，非本次回归，无新增失败）

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/tests/test_stream_memory.py | L88-125 | 验收标准 1.2「client_ip 未取到 → 默认 'unknown'，不崩」分支未被单测直接覆盖：5 个用例全部经中间件发请求，`request.state.client_ip` 恒有值，`getattr(..., "unknown")` 默认路径未被执行 | 低 | 新增用例直接调用 `chat_stream` 内部逻辑（不经中间件），或显式断言当 `request.state` 无 `client_ip` 时 `_recall_memory` 入参为 'unknown' 且不崩 |

### 2.3 观察项（仅记录，可通过）

| # | 文件 | 行号 | 观察 | 说明 |
|---|------|------|------|------|
| 1 | ai_service/main.py | L321 | `_recall_memory` 为 RAGEngine 的下划线私有方法，跨模块被 main.py 调用 | 与同函数既有 `_retrieve`/`_rerank` 私有方法调用模式一致，且为 plan.md 明确决策「复用 engine._recall_memory」，不视为问题；如需长远优化可提公开包装，本次不改 |
| 2 | ai_service/main.py | L246-254 | 流式 casual_chat 分支不注入记忆，而同步 chat 路径（engine.py L193-206）会为 casual_chat 注入记忆 | 为 plan.md 3.2 明确决策（记忆注入仅知识库生成步骤），非缺陷；仅提示两条路径对闲聊的记忆行为存在差异，后续如需对齐可在独立模块处理 |
| 3 | ai_service/main.py | L321 | Step 5 记忆召回为串行 await，知识库流式请求首 token 前最长新增 5s（`_recall_memory` 超时上限） | 与同步 chat 路径行为一致（module-023 设计），属 plan 预期；最坏场景是"无记忆 + DB 慢"多花至 5s，可接受 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 1.1 流式记忆注入 | main.py L321-322 → reflector.generate_answer_stream(memory=) | ✅ 通过 | 单测 test_memory_injected_when_recalled |
| 1.1 无记忆零回归 | memory="" → sections=history_section（reflector L230），prompt 与旧版逐字节一致 | ✅ 通过 | 单测 test_empty_memory_zero_regression |
| 1.1 记忆检索超时降级 | 复用 engine._recall_memory：asyncio.wait_for(timeout=5) + 失败返回空串（engine L295-304） | ✅ 通过 | 超时降级为 engine 内部既有行为（module-023），本模块正确复用；单测覆盖失败返回空串契约 |
| 1.2 client_ip 未取到：默认 'unknown' | main.py L227 getattr(..., "unknown")，_recall_memory 内部 `if not client_ip: return ""` | ✅ 通过（代码级） | 默认分支未被单测直接覆盖，见建议 #1 |
| 1.2 记忆为空：memory 参数空串 | main.py L321 返回值直传 | ✅ 通过 | 单测 test_empty_memory_zero_regression |
| 1.3 记忆检索失败：返回空串，生成照常 | engine._recall_memory 异常 → "" → 流式照常 | ✅ 通过 | 单测 test_recall_failure_contract_returns_empty |
| 1.3 SSE 流式正常：事件格式不变 | 记忆召回不产出 SSE 事件，step/token/done 格式不变 | ✅ 通过 | 单测断言事件序列 step×4/token×2/done |
| 2.1 SSE 事件格式不变 | main.py L244/279/300/316/323/335 | ✅ 通过 | 同上 |
| 2.1 记忆注入不影响检索/反思步骤 | 召回在 Step 5，检索/反思在前（L258-316） | ✅ 通过 | 事件序列含 4 个 step 事件 |
| 2.2 generate_answer_stream 收到 memory | main.py L322 memory=memory | ✅ 通过 | 单测 gen.calls[0]["memory"] |
| 2.2 memory 为空串时行为不变 | reflector L230 `if memory` 条件拼接 | ✅ 通过 | |
| 3.1 记忆注入逻辑有行内注释 | main.py L226、L319-320 | ✅ 通过 | |
| 3.2 变量符合 snake_case | client_ip / memory / fastapi_req | ✅ 通过 | |
| 3.3 单个方法 ≤ 50 行 | 本模块新增约 5 行；event_stream 预存在超长（module-005 遗留，非本次） | ✅ 通过 | |
| 3.3 本模块新增代码 ≤ 50 行 | main.py +3 行有效逻辑 + 注释 | ✅ 通过 | |
| 3.4 Python 语法通过 | py_compile OK + 测试实际运行通过 | ✅ 通过 | |
| 3.4 无未使用 import | main.py 无新增 import；测试文件 import 均有使用 | ✅ 通过 | |
| 4.1 单元测试 | tests/test_stream_memory.py 5 用例 | ✅ 通过 | |
| 4.2 集成测试（有记忆/无记忆流式生成） | httpx ASGITransport + mock 全链路 | ✅ 通过 | |
| 4.3 回归测试无新增失败 | 全量 101 passed + 2 既有 async 失败（test_engine.py，非本次） | ✅ 通过 | 已实测 |
| 5.1 changelog.md 已更新（版本/日期/变更内容/变更人） | specs/module-025-stream-memory/changelog.md | ✅ 通过 | |
| 5.2 接入方案记录在 plan.md | plan.md §3.2 核心流程 | ✅ 通过 | |

## 4. 架构评估

- 分层正确性: **通过** — 变更限定在 ai_service/main.py 编排层（chat_stream），复用 rag/engine.py 与 agent/reflector.py 既有能力，无跨层反向依赖。
- 依赖方向: 正确 — main.py → engine._recall_memory → memory_service.recall，方向一致（main.py 调用 rag 层，rag 层不回调编排层）。
- DTO 约束: 通过 — 无 Entity 泄漏到接口层（本次为 Python 编排层，无 Java 三层约束适用）。
- 新增依赖: 无 — 未引入任何新第三方库（仅新增 `Request` 类型已在 import 中，main.py L12）。

## 5. 安全评估

- [x] SQL 注入防护: 通过 — 记忆召回走 memory_service.recall，其内部对 ip 做 `_normalize_ip` + `_escape_like` 双重防护（memory.py L46-80），client_ip 来自中间件注入而非用户可控原始值。
- [x] XSS 防护: 通过（N/A）— 后端无直接 HTML 渲染。
- [x] 密码安全（BCrypt）: N/A — 本模块不涉及认证。
- [x] API Key 安全: 通过 — 无新增密钥处理。
- [x] 敏感信息日志处理: 通过 — 记忆召回失败仅 logger.warning 记录异常，不记录记忆内容；无敏感数据入日志。

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 说明: 未引入新依赖，无与 plan.md 不同的架构决策（复用 `_recall_memory`、client_ip 取 `request.state`、记忆仅注入生成步骤 均为 plan.md 既有决策）。

## 7. 审查检查清单

- [x] 已读取 changelog.md / plan.md / acceptance-criteria.md
- [x] 已阅读全部变更文件完整内容（main.py、test_stream_memory.py、engine.py、reflector.py、memory.py）
- [x] 命名符合规范（snake_case）
- [x] client_ip 获取正确（request.state，getattr 默认 'unknown'，与同步 chat 端点同款模式）
- [x] _recall_memory 调用正确（签名 (query, client_ip)，5s 超时 + 失败返回空串，engine L295-304 已核实）
- [x] memory 正确传给 generate_answer_stream（main.py L322，签名含 memory=""，reflector L196-202 已核实）
- [x] 无记忆零回归（memory 空串 → sections 仅 history_section，prompt 逐字节一致）
- [x] SSE 事件格式不变（召回不产出事件，事件序列实测断言通过）
- [x] 异常处理无空 catch（复用 engine 降级 + event_stream 顶层 except → error 事件）
- [x] 关键操作有日志记录（engine._recall_memory 失败有 warning）
- [x] 代码长度在限制内（本模块新增 ≤ 50 行）
- [x] 安全性检查通过
- [x] 验收标准逐项核对（全部通过或代码级通过）

## 8. 结论

实现与 plan.md 技术方案完全一致，5 个新单测全部通过，全量回归无新增失败（2 个失败为既有 async 技术债务）。无阻塞问题，建议改进仅 1 项低严重度（默认 client_ip 分支测试覆盖），观察项 3 条均不阻塞。**审查通过**，可进入 Tester 阶段。
