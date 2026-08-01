# 审查报告 — Module-026: 检索并发修复 + Reflector 改造（低温度 + 走降级链）

## 1. 审查结论

- 结论: **通过**（附建议）
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: 约 30 分钟

**结论说明**：本次审查未发现阻塞或高风险问题。并发修复、Reflector 低温度/降级链、LLMFactory 温度支持三项核心变更逻辑正确，接口与返回格式保持兼容，Developer 自测结果已独立复核确认（新增单测 13/13 通过、全量回归 114 passed + 2 个既有 async 技术债务失败、py_compile 通过）。发现的 5 项均为建议级别（代码长度、验收项表述、链序 ADR、验收命令、极端并发理论风险），不阻塞进入测试阶段。

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）
无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/rag/retriever.py | L249-358 | `_execute` 方法体约 75 行（含注释），超过验收 §3.3「单个方法 ≤ 50 行」；module-026 并发分支新增约 28 行叠加既有归一化/融合逻辑 | 中 | 将 Step3-6（`_normalize` + merge + `hybrid_score` + sort）抽为私有 `_fuse(fts_results, vector_results, top_k)` 方法，`_execute` 聚焦 session 策略 |
| 2 | ai_service/agent/reflector.py L128-130 | 验收项 §1.3「低温度客户端构造失败 → 回退默认温度」未按字面实现；构造失败实际落入 `check_sufficiency` 的 except 兜底返回 `sufficient=true`（fail-soft），且无对应单测 | 中 | 该异常场景与 API key 缺失同源（环境性），回退默认温度无实际收益，当前 fail-soft 更安全；建议修正 acceptance-criteria.md 该验收项描述为「构造/调用失败 → sufficient=true 兜底」，并补一个构造失败 mock 单测覆盖 |
| 3 | ai_service/llm/client.py L371-374 | plan.md §3.2 叙述链序「deepseek→qwen→zhipu（deepseek 优先）」，实现采用全局 `PW_FALLBACK_CHAIN=qwen,zhipu,deepseek`，与 plan 叙述不一致（Developer 已在 changelog 记录取舍） | 中 | 建议记录 ADR（docs/adr/adr-026-reflector-fallback-chain.md），固化「Reflector 沿用全局降级链序、不改默认链」决策，避免后续误解；当前行为与现状一致（deepseek 未配 key，实际主模型为 qwen） |
| 4 | plan.md §4.1 验收命令 #2 | `LLMFactory.get_client(reflector._provider)._llm.temperature` 对 `FallbackClient` 无 `_llm` 属性，命令无法直接运行 | 低 | 更新验收命令为 `FallbackClient._temperature` 或链上各供应商实例温度（Developer 已用等价格标验证：fallback 反思 0.1 / 生成 0.7） |
| 5 | ai_service/rag/retriever.py L294 | 独立 session 使单次 retrieve 占用连接数翻倍；极端并发（≥15 个 `_execute` 同时各持 1 个 session 等待第 2 个）存在理论死锁窗口（pool 5 + overflow 10 耗尽后互相等待） | 低 | 个人站并发量下概率极低（plan §6.1 已评估「低」），仅记录；如需可对 `async_session_factory()` 获取加 `asyncio.wait_for` 超时兜底 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 并发竞态消除 | retriever.py L292-306 独立 session + gather；真实 DB smoke 5 次均 3 篇 ids 一致 [17,47,48] | ✅ 通过 | 独立验证 |
| 并行性能保留 | L294-299 两路独立 session + `asyncio.gather` 并行（非串行） | ✅ 通过 | 生产路径无调用方传外部 session，全走并行 |
| 异常降级 | L297-299 `return_exceptions=True` + L383-393 `_search_serial` try-except | ✅ 通过 | 单测覆盖单路失败/双路失败/session 创建失败 |
| 反思低温度 0.1 | reflector.py L128-130 `temperature=self._reflection_temperature`（0.1） | ✅ 通过 | 单测覆盖 |
| 生成保持 0.7 | reflector.py L185-186 / L233-234 `temperature=0.7` | ✅ 通过 | 单测覆盖 generate + generate_stream |
| 走降级链 | reflector.py L100 `_provider = provider or "fallback"` | ✅ 通过 | 消除硬编码 deepseek |
| 低温度贯穿降级链 | client.py L284/295/306 FallbackClient 温度透传链上各供应商 | ✅ 通过 | 单测验证 qwen/zhipu 反思 0.1 |
| 外部传入 session 兼容 | retriever.py L286-290 `_search_serial` 串行路径 | ✅ 通过 | 单测覆盖（无生产调用方使用外部 session） |
| 降级链全失败 | reflector.py L138-141 except → `sufficient=true` | ✅ 通过 | 既有行为保留 |
| 低温度客户端构造失败 → 回退默认温度 | — | ⚠️ 待对齐 | 实现为 fail-soft（sufficient=true），非字面「回退默认温度」，见问题 #2 |
| retrieve 签名/返回格式不变 | retriever.py L77-84 / L357 | ✅ 通过 | 全部调用方（engine/graph/memory/golden）经 retrieve 无外部 session |
| Reflector 接口不变 | reflector.py L97-249 | ✅ 通过 | check_sufficiency/generate_answer/generate_answer_stream 返回格式不变 |
| LLMFactory 低温度不影响其他调用方 | client.py L356-357 `None→0.7`，`(provider,temp)` 缓存 | ✅ 通过 | casual chat/HyDE/graph/router 均不带 temperature，行为不变 |
| 单测覆盖 | tests/test_retriever_concurrency.py（6 例）+ test_reflector_temperature.py（7 例） | ✅ 通过 | 13/13 通过（独立复核） |
| 回归测试 | `pytest tests/` | ✅ 通过 | 114 passed, 2 failed（test_engine.py 既有 async 债，module-018/024/025 已记录，非本次回归） |
| 注释/命名/编译 | 全部 public 方法有 Docstring、snake_case、py_compile OK | ✅ 通过 | 无未使用 import |
| 方法 ≤ 50 行 | retriever.py L249-358 | ⚠️ 超限 | 见问题 #1 |

## 4. 架构评估

- 分层正确性: 通过。变更集中在 AI 推理层（rag / llm / agent），未触碰 Java 后端与前端，符合模块范围。
- 依赖方向: 正确。`retriever` → `src.database.async_session_factory`、`reflector` → `llm.client.LLMFactory`，均为下层依赖，无反向/循环依赖。
- DTO 约束: 不涉及（Python AI 层无 Java DTO 概念），retrieve/check_sufficiency 返回结构不变。
- 新增依赖: 无。未引入 plan.md 未定义的新第三方库（全部为既有依赖：sqlalchemy / asyncpg / langchain 等），无需 ADR。
- 并发方案评估: 独立 session + gather 是正确修复——每个 session 独占 asyncpg 连接，消除单连接 `concurrent operations` 竞态，同时保留 I/O 并行；外部 session 串行路径保证事务/连接安全，语义自洽。

## 5. 安全评估

- [x] SQL 注入防护: 通过（SQL 全参数化 `:query`/`:query_embedding`/`:limit`/`:source_pattern`，无 f-string 拼接用户输入）
- [x] 敏感信息日志处理: 通过（logger 仅记录 provider/model/query 前缀/结果数，不记录 API key；`LLMException` 包装原始异常不外泄）
- [x] API Key 安全: 通过（API key 来自 settings 环境配置，未硬编码；构造时校验缺失即抛 LLMException）
- [x] XSS / CSRF / 密码: N/A（Python AI 推理层不涉及）

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 建议（非强制）
- 建议 ADR 编号: adr-026-reflector-fallback-chain
- 决策摘要: Reflector 沿用全局 `PW_FALLBACK_CHAIN`（qwen,zhipu,deepseek），不改默认链序；链序差异已在 changelog 记录，建议补 ADR 固化（见问题 #3）

## 7. 审查检查清单

- [x] 已读取 changelog.md / plan.md / acceptance-criteria.md 了解变更范围
- [x] 已阅读全部变更文件完整内容（retriever.py / client.py / reflector.py / 2 个新测试文件，非仅 diff）
- [x] 命名符合规范（snake_case）
- [x] 接口返回格式不变（retrieve / check_sufficiency / generate_answer / LLMFactory.get_client）
- [x] 并发独立 session 正确性（独立连接、并行保留、外部 session 串行兼容、session 创建失败降级）
- [x] 反思低温度 0.1（仅反思）、生成保持 0.7、走 fallback 链、低温度贯穿降级链
- [x] 异常处理无空 catch（全部有日志）
- [x] 关键操作有日志记录（降级/失败均 logger.warning）
- [x] 敏感信息处理正确
- [x] 代码长度（方法 ≤ 50 行）: ⚠️ `_execute` 超限（建议，见问题 #1）
- [x] 依赖审计: 无新增依赖
- [x] 安全性检查通过
- [x] 独立验证: 13/13 单测、114 passed / 2 既有失败、py_compile OK 均已复核
