# 审查报告 — Module-027: 嵌入并发修复 + backlog 收敛

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-02
- 审查人: Reviewer
- 审查耗时: ~30 分钟

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `specs/module-027-embedding-lock/acceptance-criteria.md` §3.3 | — | "本模块新增代码 ≤ 150 行"：若计入新增单测文件（`test_embedding_concurrency.py` 139 行），本模块新增总行数约 171 行超限；但生产代码新增仅约 32 行（embeddings.py +25 / engine.py +7），测试代码通常不计入模块代码量预算 | 低 | 在验收时明确该条预算是否含测试代码，或拆分测试文件后按惯例仅统计生产代码 |
| 2 | `ai_service/rag/engine.py` | L382 | 空 query 使用 `logger.warning` 每次打印，若被异常/恶意客户端高频提交空 query 会产生日志噪音 | 低 | 可降为 `logger.info`/`debug`，或仅首次告警 |
| 3 | `ai_service/tests/test_embedding_concurrency.py` | 全文件 | 6 个用例实测约 48s，主要耗时在 `import rag.engine`（→ `rag.reranker` → `llama_cpp` 重 import 链）而非用例逻辑本身（锁内 sleep 总计约 0.32s） | 低 | 可接受（既有测试环境惯例），仅记录；如需加速可将导入懒化到 conftest 层 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 并发嵌入安全（16 路 embed_text 不崩溃、结果正确） | `embeddings.py` L91-94 + `test_embedding_concurrency.py::TestConcurrentEmbedText` | ✅ 通过 | 实测 6/6 通过；真实 16 路并发 Developer 已自测 |
| 并发批量安全（8 路 embed_documents 不崩溃） | `embeddings.py` L103-106 + `TestConcurrentEmbedDocuments` | ✅ 通过 | 批量内部循环整批持锁 |
| 锁覆盖模型调用（所有 create_embedding 持锁） | `embeddings.py` L93 / L105（代码库仅此两处） | ✅ 通过 | grep 确认无未加锁调用 |
| 归一化在锁外 | `embeddings.py` L94 / L106 | ✅ 通过 | 锁内只收集原始向量，`_normalize` 在 `with` 块后 |
| 空文本嵌入抛 EmbeddingException | `embeddings.py` L118-119 + `TestEmptyInputBoundary` | ✅ 通过 | |
| 空列表批量返回空列表 | `embeddings.py` L128-132 + `TestEmptyInputBoundary` | ✅ 通过 | |
| 空 query 防护（不生成缓存 key） | `engine.py` L381-383 + `TestRetrieveEmptyQueryGuard` | ✅ 通过 | 位于 Redis 缓存检查之前；单测 mock `cache.get` 断言不被调用 |
| 模型调用失败锁释放正常（with 语句） | `embeddings.py` L91/L103 | ✅ 通过 | with 语义保证异常时释放 |
| 并发下不再 GGML_ASSERT | 锁设计 + Developer 真实模型自测 | ✅ 通过 | 16/8 路真实模型不崩、均 1024 维 |
| embed_text / embed_documents 签名不变 | `embeddings.py` L117 / L127 | ✅ 通过 | |
| 返回维度仍 1024 | `embeddings.py` L49 | ✅ 通过 | |
| threading.Lock 正确使用（非 asyncio.Lock） | `embeddings.py` L53 + 注释 L50-52 | ✅ 通过 | to_thread 真线程，asyncio.Lock 无法跨线程 |
| 批量内部循环持锁 | `embeddings.py` L103-105 | ✅ 通过 | 列表推导整体在 with 块内 |
| 锁逻辑有行内注释 | `embeddings.py` L50-52 / L86-89 / L99-101 | ✅ 通过 | |
| 变量 snake_case | 全部变更文件 | ✅ 通过 | |
| 单个方法 ≤ 50 行 | `_embed_sync` 12 行 / `_embed_documents_sync` 11 行 | ✅ 通过 | |
| Python 语法通过 | py_compile + 实测运行 | ✅ 通过 | 3 变更文件 OK |
| 无未使用 import | 全部变更文件 | ✅ 通过 | `threading` 已使用 |
| 并发嵌入/批量/空输入单测 | `test_embedding_concurrency.py` 6 用例 | ✅ 通过 | 实测 6/6 passed |
| 回归无新增失败 | `python -m pytest tests/ -q` | ✅ 通过 | 实测 120 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归） |
| changelog.md 已更新（含版本/日期/内容/人） | `specs/module-027-embedding-lock/changelog.md` v1 | ✅ 通过 | |
| 锁方案记录在 plan.md | `plan.md` §3.2 / 6.2 | ✅ 通过 | |

## 4. 架构评估

- 分层正确性: 通过 — 变更仅限 AI 推理层 `ai_service/rag/embeddings.py` 与 `engine.py`，不涉及 Controller/Service/Repository，无跨层调用
- 依赖方向: 正确
- DTO 约束: N/A（AI 层，无 Entity/DTO 概念）
- 新增依赖: 无 — `threading` 为 Python 标准库，未引入 plan.md 未定义的新依赖

## 5. 安全评估

- [x] SQL 注入防护: N/A（本次无 SQL 变更）
- [x] XSS 防护: N/A（本次无前端/HTML 变更）
- [x] 密码安全: N/A
- [x] API Key 安全: N/A（本地 GGUF 模型，无外部 API Key 新增）
- [x] 敏感信息日志处理: 通过 — 日志仅记录 query 前 50 字符/维度信息，无敏感数据；新增 warning 日志不含输入内容

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- 说明: `threading.Lock` 决策已在 `memory/project-context.md` 关键技术决策记录中登记（module-027 条目），且与 plan.md 一致，无需独立 ADR

## 7. 审查检查清单

- [x] 命名符合规范（snake_case）
- [x] 接口返回统一格式（本模块为 AI 层，非 HTTP 接口；`embed_text`/`embed_documents` 签名与返回格式不变）
- [x] Controller / Service / Repository 分层正确
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch（`with` 保证锁释放；`except Exception` 包装为 `EmbeddingException`）
- [x] 关键操作有日志记录
- [x] 敏感信息处理正确
- [x] 代码长度在限制内（方法 ≤ 50 行）
- [x] 安全性检查通过

## 8. 审查验证记录（Reviewer 实测）

- `python -m pytest tests/test_embedding_concurrency.py -v` → 6 passed（约 48s，耗时主要在 import 链）
- `python -m pytest tests/ -q` → 120 passed / 2 failed（test_engine.py async 债务，module-018 已记录，非本次回归）
- grep `create_embedding` → 代码库仅 2 处，均位于 `with self._lock:` 内
- grep `_lazy_load` → 仅 `_embed_sync` / `_embed_documents_sync` 内调用，均在锁内（双加载竞态已闭合）
- 空 query 防护位于 Redis 缓存检查之前，单测 mock `cache.get` 断言不被调用
- `_retrieve` 调用方（main.py 流式端点 / eval）对 `[]` 返回值均安全处理

---

> **下一步**：更新 `memory/project-context.md`（模块状态 → 审查通过），通知 Tester 进入测试阶段。
