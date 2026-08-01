# 测试报告 — Module-025: 流式记忆接入（chat_stream 记忆注入）

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 测试总数 | 103（全量 pytest）+ 2 个半真实 E2E 场景 |
| 通过数 | 101（全量）+ 2（E2E） |
| 失败数 | 0（新增）；2 个既有 async 技术债务失败（test_engine.py，非本次回归） |
| 跳过数 | 0 |
| 通过率 | 新增测试 100%；全量回归无新增失败 |
| 执行耗时 | 单测 ~46s；全量回归 ~53s；半真实 E2E ~10s |

**环境阻塞说明**：LLM 供应商当日 429 配额超限（qwen/zhipu）且 deepseek 未配置 API Key，完整 LLM 生成链路（意图识别→反思→生成）无法运行。按任务指引改为**验证逻辑正确性（记忆检索 + 参数传递）**：使用半真实 E2E（真实保存记忆 + 真实 `_recall_memory` 走真实数据库，仅 mock LLM 依赖环节）验证流式对话引用记忆。

## 2. 覆盖率报告

本模块为 ≤50 行小改动，`plan.md` 未单独约定覆盖率阈值，且环境未安装 coverage 工具（不额外引入依赖）。以测试用例对新增分支的覆盖情况定性评估：

| 覆盖维度 | 情况 | 说明 |
|----------|------|------|
| 记忆注入调用逻辑 | ✅ | test_memory_injected_when_recalled：`generate_answer_stream(memory=召回文本)` |
| 无记忆零回归 | ✅ | test_empty_memory_zero_regression + E2E：memory 为空串，prompt 不含记忆段 |
| 召回失败契约 | ✅ | test_recall_failure_contract_returns_empty：失败 → 空串 → 生成照常 |
| client_ip 透传 | ✅ | test_client_ip_passed_to_recall：X-Forwarded-For → `_recall_memory(query, ip)` |
| casual_chat 跳过召回 | ✅ | test_casual_chat_skips_memory_recall：提前 return 不触发召回 |
| 真实记忆检索数据路径 | ✅ | 半真实 E2E：真实保存 → 真实 `_recall_memory` → 真实命中 |

## 3. 验收标准核对

### 3.1 功能验收
| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 流式记忆注入 | test_memory_injected_when_recalled + E2E Test A | ✅ 通过 | 真实记忆注入为 `"历史记忆:\n- 用户偏好简洁回答，不要长篇大论。"` |
| 无记忆零回归 | test_empty_memory_zero_regression + E2E Test B | ✅ 通过 | memory 空串，SSE 照常 |
| 记忆检索超时降级 | engine L295 `asyncio.wait_for(timeout=5)` + 失败返回空串（module-023 既有行为，正确复用） | ✅ 通过 | 契约由 test_recall_failure_contract_returns_empty 验证 |
| client_ip 未取到默认 'unknown' | main.py L227 `getattr(..., "unknown")`（代码级）+ 实测 `_recall_memory("", ip)` → "" 不崩 | ✅ 通过 | Reviewer 建议 #1：默认分支未单测直接覆盖，已代码级核实 |
| 记忆为空：memory 空串 | test_empty_memory_zero_regression + E2E Test B | ✅ 通过 | |
| 记忆检索失败：返回空串，生成照常 | test_recall_failure_contract_returns_empty | ✅ 通过 | |
| SSE 流式正常：事件格式不变 | 单测 + E2E 断言 `step×4 / token×2 / done` | ✅ 通过 | 实际输出 `['step','step','step','step','token','token','done']` |

### 3.2 接口验收
| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| SSE 事件格式不变（step/token/done/error） | 事件序列断言 | ✅ 通过 | 记忆召回不产出 SSE 事件 |
| 记忆注入不影响检索/反思步骤 | 事件序列含 4 个 step（intent/retrieval/rerank/reflection） | ✅ 通过 | 召回在 Step 5 生成前 |
| generate_answer_stream 收到 memory 参数 | gen.calls[0]["memory"] | ✅ 通过 | 半真实 E2E 验证真实值传入 |
| memory 为空串时行为不变 | test_empty_memory_zero_regression | ✅ 通过 | |

### 3.3 代码质量验收
| 验收项 | 对应验证 | 状态 | 备注 |
|--------|----------|------|------|
| 记忆注入逻辑有行内注释 | main.py L226、L319-320 | ✅ 通过 | |
| 变量符合 snake_case | client_ip / memory / fastapi_req | ✅ 通过 | |
| 单个方法 ≤ 50 行 | 本模块新增约 5 行；event_stream 超长为 module-005 遗留 | ✅ 通过 | |
| 本模块新增代码 ≤ 50 行 | main.py 有效逻辑 +3 行 | ✅ 通过 | |
| Python 语法通过 | `python -m py_compile main.py tests/test_stream_memory.py` → OK（Tester 独立复验） | ✅ 通过 | |
| 无未使用 import | main.py 无新增 import；测试文件 import 均有使用 | ✅ 通过 | |

### 3.4 测试验收
| 验收项 | 对应测试/验证 | 状态 | 备注 |
|--------|--------------|------|------|
| 单元测试：记忆注入调用逻辑 | tests/test_stream_memory.py 5 用例 | ✅ 通过 | 5 passed（httpx ASGITransport + mock 全链路） |
| 集成测试：有记忆时流式生成含记忆 | 半真实 E2E Test A（真实保存 + 真实召回） | ✅ 通过 | memory 参数收到真实记忆文本 |
| 集成测试：无记忆零回归 | 半真实 E2E Test B | ✅ 通过 | memory 参数空串 |
| 回归测试：`pytest -x` 无新增失败 | 全量 `python -m pytest tests/` | ✅ 通过 | 101 passed；2 failed 为 test_engine.py 既有 async 技术债务（缺 pytest-asyncio，module-018 已记录；test_engine.py 未被本模块修改，非本次回归） |
| chat_stream SSE 正常 | 单测 + 半真实 E2E 事件序列断言 | ✅ 通过 | status=200 |

### 3.5 文档验收
| 验收项 | 对应验证 | 状态 | 备注 |
|--------|----------|------|------|
| changelog.md 已更新 | specs/module-025-stream-memory/changelog.md | ✅ 通过 | |
| 包含版本号/日期/变更内容/变更人 | v1 / 2026-08-01 / 内容 / Developer | ✅ 通过 | |
| 接入方案记录在 plan.md | plan.md §3.2 核心流程 | ✅ 通过 | |

## 4. 失败详情

### 失败 #1（既有技术债务，非本次回归）
- 测试名: test_engine.py::test_search_returns_response
- 关联验收项: 无（与 module-025 无关）
- 失败原因: `async def functions are not natively supported` —— 测试环境缺 pytest-asyncio 插件，`async def` 用例无法被 pytest 收集执行。
- 关联文件: tests/test_engine.py:L6-16（本模块未修改该文件）
- 修复建议: 安装 `pytest-asyncio`（或 `pip install pytest-asyncio`），此问题属 module-018 已记录技术债务，建议单独模块处理。

### 失败 #2（既有技术债务，非本次回归）
- 测试名: test_engine.py::test_chat_returns_response
- 关联验收项: 无（与 module-025 无关）
- 失败原因: 同上（缺 pytest-asyncio）。
- 关联文件: tests/test_engine.py:L13-16
- 修复建议: 同上。

## 5. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-01
- 测试人: Tester
- 备注:
  - 专项单测 5/5 通过；全量回归 101 passed + 2 既有 async 技术债务失败（非本次回归，无新增失败）。
  - **半真实 E2E**（LLM 429 阻塞下的最强验证）：真实保存记忆（PG + 本地 bge-m3）→ 走真实 `chat_stream` 端点 → 真实 `_recall_memory` 从真实数据库召回 `"历史记忆:\n- 用户偏好简洁回答，不要长篇大论。"` → 传入 `generate_answer_stream(memory=...)`，SSE 事件格式 `step×4/token×2/done` 正常；无记忆 IP 时 memory 为空串，零回归成立。
  - 测试产生的临时记忆已清理（测试 IP 使用 TEST-NET 保留网段 203.0.113.x，避免污染真实数据）。
  - LLM 429 阻塞记录在案：配额恢复后可补跑完整端到端（保存记忆 → 真实流式对话 → 回答引用记忆）。
