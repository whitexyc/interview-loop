# M14: HyDE 查询改写 — 项目计划

## 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | M14 |
| 模块名称 | HyDE Query Rewriting（假设文档嵌入查询改写） |
| 版本号 | 0.14.0-module-014 |
| 创建日期 | 2026-07-30 |
| 前置模块 | M5（RAG 核心）, M17（父子分块检索） |
| 范围 | ai_service only |
| 目标 | 检索前通过 LLM 生成假设性回答，利用假设回答的语义向量替代原始查询进行首轮检索 |

## Agent 配置

| 角色 | 实例数 | 职责 |
|------|--------|------|
| Developer | x1 | Python AI 服务 |
| Reviewer | x1 | 代码审查 |
| Tester | x1 | 集成测试 |

---

## 1. 需求概述

### 1.1 当前状态
- `_retrieve()` 接收原始 query 直接传入 `hybrid_retriever.retrieve()` 
- 问题查询通常简短（如"什么是G1 GC"），而文档是长文本段落，语义 gap 大

### 1.2 目标
检索前插入 HyDE：
```
用户 Query → LLM 生成假设性回答 → embed(假设回答) → 向量检索
```

### 1.3 非目标
- 不修改 retriever/embeddings/reranker/reflector
- 不新增文件（全部在 engine.py 内）

---

## 2. 技术方案

### 2.1 engine.py 变更

**新增 `_HYDE_PROMPT` 常量**：
```python
_HYDE_PROMPT = """你是一个知识库助手。根据用户问题，写一段2-3句话的假设性回答。
这段回答不是给用户看的，而是用来在知识库中检索相关文档。
请模仿知识库文档的语言风格来写。

用户问题: {query}

假设回答（2-3句话）:"""
```

**新增 `_hyde_expand()` 方法**：`async def _hyde_expand(self, query: str) -> str`
- 调用 `LLMFactory.get_client().generate(prompt)`
- 失败/超时时降级返回原始 query

**修改 `_retrieve()`**：
- 首轮检索前调用 hyde_expand
- `search_text = hyde_query if round_num == 0 else current_query`
- 反思始终使用原始 `query`（非 HyDE 查询）

### 2.2 检索流程变更

**变更前**：
```
query → embed(query) → hybrid search → (reflect) → rewritten query → search → ...
```

**变更后**：
```
query → hyde_expand → hypothetical_answer → embed(hypothetical) → search (round 0)
  → (reflect with original query) → rewritten → search (rounds 1-2)
```

---

## 3. 文件清单

| # | 文件 | 变更 |
|---|------|------|
| 1 | `ai_service/rag/engine.py` | 新增 `_HYDE_PROMPT` + `_hyde_expand()` + 修改 `_retrieve()` 首轮调用 |

---

## 4. 实施步骤

1. 添加 `_HYDE_PROMPT` 常量
2. 实现 `_hyde_expand()` 方法
3. 修改 `_retrieve()`：首轮使用 hyde_query，反思使用原始 query
4. 验证：启动服务，日志见 "HyDE 扩展完成"

---

## 5. 风险

| 风险 | 严重度 | 应对 |
|------|--------|------|
| LLM 超时 | 中 | asyncio.wait_for 10s，超时降级 |
| 假设回答质量差 | 低 | 异常时返回原始 query |
| 额外 LLM 成本 | 低 | 仅 50-100 tokens/次 |
