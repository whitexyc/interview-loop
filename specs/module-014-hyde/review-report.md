# 审查报告 — Module-014: HyDE Query Rewriting

## 1. 审查结论

- 结论: **PASS**（通过）
- 审查时间: 2026-07-30
- 审查人: Reviewer
- 审查耗时: ~30 分钟

**通过理由**: 代码完整实现了 plan.md 定义的全部技术方案项，全部 4 类验收标准通过，错误处理覆盖所有降级路径，代码质量达标。

---

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 高优先级问题（必须修复）

无。

### 2.3 建议改进（不阻塞，建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `engine.py` | L106-206 | `chat()` 方法含有自己的内联检索循环，未调用 `_retrieve()`，因此**非流式问答路径未受益于 HyDE**。plan.md 范围限定为"修改 `_retrieve()`"（供流式端点复用），所以此问题不超出范围，但建议后续对齐两条路径。 | 低 | 后续模块可考虑让 `chat()` 也调用 `_retrieve()`，或在其内联循环中同样加入 `_hyde_expand()`。当前流式端点 (`chat_stream` in main.py:241) 通过 `_retrieve()` 正确使用了 HyDE。 |
| 2 | `engine.py` | L288 | `check_sufficiency(query, docs)` 在所有反思轮次中始终使用原始 `query`。这与 plan.md 要求一致（"反思始终使用原始 query"），但与 `chat()` 方法 L159 使用 `current_query`（改写后的 query）的行为不一致。属设计差异，非 bug。 | 低 | 若 planner 决定统一行为，可考虑 `_retrieve()` 中后续轮次也使用 `current_query`。当前行为在语义上更合理（始终判断是否足以回答用户原始问题）。 |

---

## 3. plan.md 技术方案逐项核对

### 3.1 新增 `_HYDE_PROMPT` 常量

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| 中文 prompt，2-3 句话假设回答模板 | engine.py: L44-50 | PASS | 与 plan spec 字面一致 |
| 包含 `{query}` 占位符 | engine.py: L48 | PASS | |
| 注释说明 HyDE 设计思路 | engine.py: L40-43 | PASS | 额外添加了模块级注释 |

### 3.2 新增 `_hyde_expand()` 方法

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| 方法签名 `async def _hyde_expand(self, query: str) -> str` | engine.py: L208 | PASS | |
| 调用 `LLMFactory.get_client().generate(prompt)` | engine.py: L225-226 | PASS | |
| 失败降级返回原始 query | engine.py: L234-236 | PASS | 含 `asyncio.TimeoutError` (L231) 和通用 `Exception` (L234) 两条捕获路径 |
| 超时 10 秒 | engine.py: L227 | PASS | `asyncio.wait_for(..., timeout=10)` |
| 空字符串兜底 `answer or query` | engine.py: L230 | PASS | LLM 返回空字符串时也能降级 |

### 3.3 修改 `_retrieve()`

| 要求 | 代码位置 | 状态 | 备注 |
|------|----------|------|------|
| 首轮检索前调用 `_hyde_expand` | engine.py: L260 | PASS | |
| `search_text = hyde_query if round_num == 0 else current_query` | engine.py: L263 | PASS | 与 plan spec 字面一致 |
| 反思始终使用原始 `query`（非 HyDE 查询） | engine.py: L288 | PASS | `reflector.check_sufficiency(query, docs)` — 使用函数参数 `query`，即原始用户查询 |
| 后续轮次（round 1-2）使用改写后的 `current_query` | engine.py: L263, L296-297 | PASS | |

### 3.4 检索流程变更（plan 2.2 节）

| 要求 | 状态 | 备注 |
|------|------|------|
| query -> hyde_expand -> hypothetical_answer -> embed -> search (round 0) | PASS | L260 -> L263 (round_num==0 分支) |
| reflect with original query (rounds 1-2) | PASS | L288 使用原始 `query`；rounds 1-2 使用反射改写的 `current_query` |

---

## 4. 验收标准核对

### 4.1 功能验收

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 流式聊天请求正确执行 HyDE：LLM 生成假设回答 -> 日志输出"HyDE 扩展完成" | engine.py: L229 `logger.info("HyDE 扩展完成: query=%s, hyde_len=%d", ...)` | PASS | main.py:241 `chat_stream` 调用 `rag_engine._retrieve()` -> 触发 `_hyde_expand()` |
| 首轮检索使用假设回答作为搜索文本 | engine.py: L263 `search_text = hyde_query if round_num == 0 else current_query` | PASS | |
| 反思检查使用原始用户问题判断充分性（非 HyDE 查询） | engine.py: L288 `reflector.check_sufficiency(query, docs)` | PASS | `query` 是 `_retrieve()` 的原始参数，未经 HyDE 或改写 |
| 检索结果仍正确返回给前端（格式不变） | engine.py: L307-316 | PASS | `_retrieve()` 返回值 `list[dict]` 格式不变，仅内部检索逻辑增加 HyDE |
| 前端流式展示不受影响 | main.py:241 | PASS | SSE 事件结构未变，HyDE 对前端透明 |

### 4.2 降级路径

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| LLM 调用失败时降级为原始 query（日志"HyDE 扩展失败"） | engine.py: L234-236 `logger.warning("HyDE 扩展失败，降级使用原始 query: %s", e)` | PASS | |
| LLM 超时（>10s）时降级为原始 query（日志"HyDE 扩展超时"） | engine.py: L231-233 `logger.warning("HyDE 扩展超时 (10s)，降级使用原始 query: %s", ...)` | PASS | `asyncio.wait_for(..., timeout=10)` |
| 降级后检索正常，不抛出异常 | engine.py: L232-233, L236 | PASS | 所有异常路径均 `return query`（原始查询），不 raise |

注意：L231 捕获 `asyncio.TimeoutError`，L234 捕获通用 `Exception`。`asyncio.TimeoutError` 在 Python 3.11+ 是 `TimeoutError` 的子类且是独立的异常类，这段代码正确。两条分支互斥，不会双重捕获。

### 4.3 代码质量

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 新增代码 <= 50 行 | engine.py: L40-50 (_HYDE_PROMPT 7行) + L208-236 (_hyde_expand 29行) + L260,263,288 (修改 3行) = 39 行 | PASS | 符合 |
| 无新增 Python 文件 | 仅 engine.py 变更 | PASS | 符合 plan 1.3 节 |
| `_hyde_expand()` 包含完整 docstring | engine.py: L209-221 | PASS | 13 行中文 docstring，含设计思路、Args、Returns |
| try/except 覆盖所有异常路径 | engine.py: L223-236 | PASS | `TimeoutError` + 通用 `Exception` + 空字符串兜底 |

---

## 5. 正确性分析

### 5.1 HyDE 查询作用域

```
round_num=0: search_text = hyde_query (HyDE 生成的假设回答)
  -> 检索 -> rerank -> check_sufficiency(query=原始query, ...)
  若不足且有改写: current_query = rewritten_query

round_num=1: search_text = current_query (反射改写的查询)
  -> 检索 -> rerank -> check_sufficiency(query=原始query, ...)

round_num=2: search_text = current_query
  -> 检索 -> 直接结束（不反思）
```

- **round 0 唯一使用 HyDE**: L263 `hyde_query if round_num == 0 else current_query` -- 正确
- **所有轮次反思使用原始 query**: L288 `reflector.check_sufficiency(query, docs)` -- 正确，符合 plan
- **后续轮次使用改写 query**: L296 `current_query = rewritten` -- 正确

### 5.2 调用链验证

```
API /ai/rag/chat/stream (main.py:200)
  -> event_stream() main.py:212
    -> rag_engine._retrieve(request.query, top_k=20) main.py:241
      -> self._hyde_expand(query) engine.py:260
        -> LLMFactory.get_client().generate(prompt) engine.py:225-226
      -> hybrid_retriever.retrieve(search_text, ...) engine.py:266
```

完整调用链已验证，HyDE 在正确的位置（检索前）执行。

### 5.3 边界情况

| 场景 | 行为 | 状态 |
|------|------|------|
| LLM 调用正常返回 | hyde_query = LLM 输出 | PASS |
| LLM 返回空字符串 | `answer or query` -> fallback to original query (L230) | PASS |
| LLM 超时 (>10s) | `asyncio.TimeoutError` -> return query (L231-233) | PASS |
| LLM 调用抛其他异常 | `Exception` -> return query (L234-236) | PASS |
| hyde_query 与 query 完全一致 | 可行，等效于无 HyDE | PASS |

---

## 6. 代码质量评估

### 6.1 注释覆盖率

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 函数 docstring | PASS | `_hyde_expand()` L209-221 包含 13 行完整 docstring |
| 常量注释 | PASS | `_HYDE_PROMPT` L40-43 有设计思路注释 |
| 行内注释 | PASS | `_retrieve()` L259 有 HyDE 行内注释 |
| 日志信息 | PASS | 成功/超时/失败三条日志路径，INFO/WARNING 级别正确 |

### 6.2 命名规范

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 函数名 snake_case | PASS | `_hyde_expand` |
| 常量 UPPER_SNAKE_CASE | PASS | `_HYDE_PROMPT` |
| 私有前缀 `_` | PASS | `_hyde_expand`, `_HYDE_PROMPT` |
| 变量命名清晰 | PASS | `hyde_query` 语义自解释 |

### 6.3 代码长度

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `_hyde_expand` 方法 | PASS | 29 行，不超过 50 |
| `_HYDE_PROMPT` 常量 | PASS | 7 行 |
| 新增代码总计 | PASS | 39 行，不超过 50 |

### 6.4 异步模式

| 检查项 | 状态 | 说明 |
|--------|------|------|
| async/await 使用正确 | PASS | `_hyde_expand` 为 `async def`，内部 `await` |
| 超时控制 | PASS | `asyncio.wait_for` 正确包裹 LLM 调用 |
| 不阻塞事件循环 | PASS | 所有 I/O 均为 async |

### 6.5 日志规范

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 成功用 INFO | PASS | L229 `logger.info(...)` |
| 可恢复异常用 WARNING | PASS | L232, L235 `logger.warning(...)` |
| 日志含关键上下文 | PASS | 包含 query 截断、hyde_len、异常信息 |

---

## 7. 安全评估

- N/A（本模块为纯内部 Python 服务端改造，不涉及 HTTP 入参校验、数据库操作或用户输入渲染）
- HyDE prompt 中仅注入用户原始 query，由 LLM 内部处理，不存在注入风险
- 无文件操作、无外部 API key 泄露风险

---

## 8. 依赖审计

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 新增 Python 包依赖 | 无 | 仅使用已有的 `asyncio`, `logging`, `LLMFactory` |
| 新增文件 | 无 | plan 1.3 明确"不新增文件" |
| 新增配置项 | 无 | 超时值 10s 硬编码（符合 plan 风险应对） |

**ADR 需求**: 无需 ADR（无新依赖，无架构变更）。

---

## 9. 架构评估

- **分层正确性**: PASS。代码在 `rag/engine.py` 的 `RAGEngine` 类中，属于编排层（总导演），未侵入 retriever/reranker/reflector 子模块。符合 plan 1.3 节"不修改 retriever/embeddings/reranker/reflector"。
- **依赖方向**: N/A（内部方法调用，无跨模块新依赖）
- **新增方法可见性**: `_hyde_expand()` 使用单下划线前缀，正确标识为模块私有方法。
- **与 chat() 方法的关系**: `chat()` 未使用 `_retrieve()` 是其既有设计，不在 M14 范围内。

---

## 10. 审查检查清单

- [x] 已读取 plan.md 和 acceptance-criteria.md
- [x] 已阅读完整变更文件（engine.py 503 行）
- [x] plan.md 技术方案逐项核对（全部 8 项 PASS）
- [x] 验收标准逐项核对（4 类全部 PASS）
- [x] 正确性分析完成（调用链、作用域、边界情况）
- [x] 命名符合规范（snake_case 函数、UPPER_SNAKE 常量、下划线前缀）
- [x] 异常处理无空 catch（TimeoutError + Exception 均有日志 + 降级）
- [x] 安全评估完成
- [x] 依赖审计完成（无新增依赖）
- [x] 每个问题都标注了文件路径 + 行号
- [x] 每个建议都有具体操作说明
- [x] review-report.md 已输出

---

## 11. 总结

M14 HyDE Query Rewriting 实现质量优秀，是一次干净、紧凑的改动：

- **39 行净新增代码**，无新文件，无新依赖，完全在 plan 范围内
- **错误处理完备**：超时、异常、空返回值三条降级路径
- **设计意图清晰**：模块注释 + 方法 docstring + 行内注释形成完整文档链
- **语义正确**：round 0 使用 HyDE 假设回答检索，后续轮次用反射改写查询，反思始终检查原始 query
- **前端透明**：SSE 流式端点无需改动，HyDE 纯粹是服务端检索优化

**仅有的 2 个建议**（均为低优先级）：
1. `chat()` 非流式方法可从 `_retrieve()` 重构中受益（后续模块优化）
2. `check_sufficiency` 在两个方法中的参数选择（query vs current_query）可统一
