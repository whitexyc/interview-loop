# 变更日志 — Module-014: HyDE Query Rewriting

## 变更概述
在 RAG 检索链路中插入 HyDE (Hypothetical Document Embeddings) 查询扩展：首轮检索前通过 LLM 生成假设性回答，利用假设回答的语义向量替代原始查询进行检索，缩小短查询与长文档之间的语义 gap。失败或超时时静默降级为原始查询。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/engine.py | 修改 | 新增 `_HYDE_PROMPT` 常量、`_hyde_expand()` 方法、修改 `_retrieve()` 首轮检索使用 HyDE 查询、反思检查使用原始 query |

## 关键设计说明

### 设计决策 1: HyDE 仅限于首轮检索（round 0）
- **决策**: 首轮使用 `hyde_query`（LLM 生成的假设回答），后续轮次（round 1-2）使用反射改写后的 `current_query`
- **原因**: HyDE 的目的是用长文本语义向量替代短查询。反射改写后的 query 已经经过语义优化，再次 HyDE 会引入额外延迟且收益递减。同时反射改写的有效性依赖原始 query 的语义方向，混入 HyDE 文本会干扰改写的准确性。

### 设计决策 2: 反思检查始终使用原始 query
- **决策**: `reflector.check_sufficiency(query, docs)` 传入原始用户查询（非 HyDE 查询、非改写后的查询）
- **原因**: 反思检查需要判断检索结果是否足以回答用户的原始问题。使用 HyDE 查询或改写后的查询做检查会偏离用户真实意图，导致虚假的"充分"判断。

### 设计决策 3: 10s 超时 + 完整异常降级
- **决策**: `asyncio.wait_for(..., timeout=10)` 包裹 LLM 调用，`TimeoutError` 和 `Exception` 分别捕获，降级返回原始 query
- **原因**: HyDE 是优化而非必需环节。LLM 超时或失败时不应阻塞整个检索流程。分别捕获两种异常类型以区分日志（"超时" vs "失败"）。

### 设计决策 4: `_HYDE_PROMPT` 为模块级常量
- **决策**: 放在模块顶层（类外部），以 `_` 前缀标记为模块私有
- **原因**: 提示词与类实例无关，不需要每次实例化。方便后续调优时直接修改，也便于单元测试中 mock。

## 验证命令
| 验证项 | 命令 | 结果 |
|--------|------|------|
| Python 编译检查 | `python -m py_compile rag/engine.py` | PASS |
| 方法存在性检查 | `python -c "from rag.engine import rag_engine; print(hasattr(rag_engine, '_hyde_expand'))"` | True |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-07-30 | 初始实现：_HYDE_PROMPT + _hyde_expand() + _retrieve() round 0 使用 HyDE | Developer |
