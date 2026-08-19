# 功能规格说明书 — Module-040: Adaptive RAG（检索不足自动改写重查）

> Planner | 2026-08-08

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-040 |
| 模块名称 | Adaptive RAG — 检索不足自动改写重查 |
| 版本号 | 0.40.0-module-040 |
| 优先级 | P1（Agent 路径缺失自校正能力） |
| 预估代码量 | ≤ 100 行 |

---

## 2. 需求

### 2.1 现状

`reflector.check_sufficiency` 已实现：检查检索结果是否充分，不充分时返回 `rewritten_query`。但它只在 `engine.py chat()` 固定流水线中使用，**Agent ReAct 路径完全没有调用**。Agent 检索到不相关内容只能手动换工具或浪费预算。

### 2.2 目标

在 tool_registry 加一个 `re_search` 工具——Agent 看检索结果不够时，可主动调用。工具内部：调 `check_sufficiency` → 不充分则用 `rewritten_query` 重新检索 → 新结果累积到 ctx.docs。

### 2.3 验收场景

```
场景 1：Agent 检索结果不足
  假设 Agent 调用 search_knowledge 返回 3 条不相关文档
  当 LLM 调 re_search(query="原始问题")
  那么 check_sufficiency 判断不充分 → 用 rewritten_query 重检 → 新 docs 累积到 ctx

场景 2：检索已充分
  假设 Agent 已检索到足够文档
  当 LLM 调 re_search
  那么 check_sufficiency 返回 sufficient=true → 工具返回"当前检索结果已充分"

场景 3：所有检索都无结果
  假设知识库无相关内容
  当 re_search 改写后仍无结果
  那么 工具返回"改写检索后仍无结果"→ LLM 判断是否如实告知用户

场景 4：不影响现有工具
  验证：现有 8 个工具行为不变，regression 全绿
```

---

## 3. 技术方案

### 3.1 涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `ai_service/agent/tool_registry.py` | 修改 | 新增 `_re_search` 工具 + schema + 注册为第 9 个工具 |
| `ai_service/agent/react.py` | 修改 | 系统提示词更新：加入 re_search 工具说明 + 使用规则 |

### 3.2 核心逻辑

```python
async def _re_search(ctx, args):
    """检索不足 → 改写 query → 重检 → 累积 docs"""
    query = args.get("query") or ctx.query
    result = await reflector.check_sufficiency(query, ctx.docs)
    if result.get("sufficient"):
        return "（当前检索结果已充分，无需重检）"
    rewritten = result.get("rewritten_query", query)
    docs = await hybrid_retriever.retrieve(rewritten, top_k=5, mode="hybrid")
    ctx.add_docs(docs)
    if not docs:
        return f"改写查询 '{rewritten}' 后仍无结果，知识库可能无相关内容"
    return f"改写查询 '{rewritten}' → 检索到 {len(docs)} 篇文档：\n" + _format_docs(docs)
```

### 3.3 系统提示词更新

react.py `_SYSTEM_PROMPT` 加一条使用规则：
```
5. 检索结果与问题不相关时，调用 re_search 自动改写查询重检，
   无需手动换 search_fts/search_vector（与 engine 流水线的自动反思对齐）
```

### 3.4 降级

| 场景 | 处理 |
|------|------|
| check_sufficiency 失败 | 返回提示，不阻塞 |
| 改写后检索失败 | 返回"无结果"提示 |
| 无 ctx.docs 时调 re_search | 返回"请先检索" |

---

## 4. 验收标准

见 `acceptance-criteria.md`

## 5. 依赖

- module-028 (ReactContext / ToolRegistry)
- module-004 (Reflector.check_sufficiency)
- module-005 (hybrid_retriever)
