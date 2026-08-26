# module-082-sag-hardening 开发计划

## 1. 需求描述

在 module-081 已闭环的 SAG 检索能力基础上，进行**小步补强**，仅实现以下三项：

1. **`/ai/rag/search` 端点感知 `retrieval_mode`**：当 `retrieval_mode in (sag, hybrid_sag)` 时，search 也应先执行 SAG 检索并合成结果（对齐 chat 路径语义）。
   - `hybrid_sag`：SAG 结果与常规结果合并去重（SAG 结果附加到候选池）。
   - `sag`：search 端点返回纯 SAG 检索结果。
   - **保持 `hybrid`（默认）零行为变化。**

2. **SAG 查询实体提取的非 LLM 兜底**：`sag_retriever` Step1 当前依赖 `graph_extractor.extract_from_query`（LLM）。当 LLM 失败或返回空时，应启用**非 LLM 兜底**：
   - 用查询词直接做 ILIKE。
   - 简单分词：按空白/常见分隔符切词，过滤停用词与单字符，取前 N 个作为候选实体名。
   - 保证 SQL 通道在无 LLM 时也能启动；LLM 正常时仍优先用 LLM 结果。

3. **`hybrid_sag` 融合排序策略**：目前 SAG 结果只是简单 append（去重），排在最后。目标：轻量改进排序策略。
   - 候选方案：按现有 rerank 流程自然排序（仅记录观察）；或 SAG 命中项 score×1.2 轻 boost；或进 reranker 前与三通道同集。
   - **优先简单方案（符合 ponytail 哲学）**，产出明确选择与理由。

## 2. 子任务拆分

### 子任务 1：search 端点 SAG 感知（~40 行生产代码）

**涉及文件**：
- `ai_service/rag/engine.py`：`search()` 方法改造（~35 行）

**实现要点**：
- 当 `retrieval_mode in ("sag", "hybrid_sag")` 时：
  1. 先执行 `sag_retriever.retrieve(query, top_k*2)`（对齐 chat `_retrieve` 的 SAG 前置逻辑）。
  2. `hybrid_sag` 模式：SAG 结果与 `hybrid_retriever.retrieve()` 结果合并去重（用 `existing_ids` set），SAG 结果放在前面（当前 append 顺序即优先）。
  3. `sag` 模式：直接用 SAG 结果作为候选集，跳过 `hybrid_retriever.retrieve()`。
  4. 两模式都继续走 `_expand_to_parents` + `reranker.rerank` 正常流程。
- 当 `retrieval_mode == "hybrid"`（默认）时：走现有逻辑，零改动。
- SAG 检索失败时降级为仅常规结果（fail-open，对齐 chat 路径）。

**对接点**：
- `engine.py` L229-264 `search()` 方法：`results = await hybrid_retriever.retrieve(...)` 前插入 SAG 分支。
- `engine.py` L889-905 `_retrieve` SAG 分支：复用同一 `sag_retriever.retrieve` 调用模式。

### 子任务 2：SAG 查询实体提取非 LLM 兜底（~35 行生产代码）

**涉及文件**：
- `ai_service/rag/retrieval/sag_retriever.py`：改造 `retrieve()` 方法（~30 行）

**实现要点**：
- 在现有 `graph_extractor.extract_from_query(query)` 调用外包裹 try/except。
- LLM 正常返回非空实体列表时：使用 LLM 结果（现有行为不变）。
- LLM 失败（抛异常）或返回空列表时：启用 `_fallback_extract_entities(query)` 兜底。
  - 按空白 + 常见分隔符（`，。、；：？！,.:;?!\n\t`）切词。
  - 过滤：停用词集合（~50 个高频中文/英文停用词，硬编码常量）+ 单字符词。
  - 取前 `top_k`（默认 5）个候选实体名。
  - 无有效候选时返回空列表（保持现有空结果语义）。
- **LLM 正常时仍优先用 LLM 结果**，兜底只在 LLM 失败/空时触发。
- 兜底实体名直接做 ILIKE（复用 `_sql_entity_search` 现有逻辑）。

**对接点**：
- `sag_retriever.py` L15-30 `retrieve()` 方法：Step1 实体提取逻辑。
- `sag_retriever.py` L37-55 `_sql_entity_search()`：接收实体名列表，已参数化。

### 子任务 3：hybrid_sag 融合排序策略（~15 行生产代码）

**涉及文件**：
- `ai_service/rag/engine.py`：`_retrieve` SAG 分支 + `search()` SAG 分支（~10 行）

**实现方案选择（优先简单）**：
- **方案 A（推荐）：SAG 命中项 score×1.2 轻 boost**
  - 对 `sag_docs` 列表中每个 doc，将其 `hybrid_score` 乘以 1.2（上限 1.0 不变，截断）。
  - 理由：SAG 是精确实体匹配，理论上相关度应高于统计相似度；×1.2 轻 boost 在 reranker 精排前给予 SAG 命中稍高优先级，不干扰 reranker 最终排序。
  - 复杂度最低（纯数值变换），符合 ponytail 哲学。
- 实现位置：`_retrieve` SAG 分支合并前 + `search()` SAG 分支合并前。
- 仅对 SAG 命中项的 `hybrid_score` 做 boost，不改其他字段。
- `hybrid` 默认路径零影响（SAG 分支不执行）。

**拒绝的方案**：
- "按现有 rerank 流程自然排序"：当前已是 append 后统一 rerank，但 SAG 结果排最后（append 顺序），需至少调整合并顺序。
- "SAG 独立进 RRF 公式"：超出小步补强范围，且 module-081 plan §5.2 已拍板"不做 SAG 独立进 RRF"。

## 3. 技术方案

### 3.1 search 端点 SAG 感知

```python
# engine.py search() 方法改造（伪代码）
async def search(self, request: SearchRequest) -> SearchResponse:
    ...
    results = []
    sag_docs = []

    # SAG 前置（对齐 _retrieve 分支语义）
    if settings.retrieval_mode in ("sag", "hybrid_sag"):
        try:
            sag_docs = await sag_retriever.retrieve(request.query, top_k=top_k*2)
            # boost SAG 命中项（子任务 3）
            for sd in sag_docs:
                sd["hybrid_score"] = min(sd.get("hybrid_score", 0.0) * 1.2, 1.0)
        except Exception as e:
            logger.warning("search SAG 检索失败，降级: %s", e)

    if settings.retrieval_mode != "sag":
        # 常规检索（hybrid/hybrid_sag）
        regular = await hybrid_retriever.retrieve(...)
    else:
        regular = []

    # 合并：SAG 在前 + 常规在后，去重
    existing_ids = set()
    for doc in sag_docs + regular:
        doc_id = doc.get("id")
        if doc_id and doc_id not in existing_ids:
            results.append(doc)
            existing_ids.add(doc_id)

    # 后续：_expand_to_parents + reranker.rerank（不变）
    ...
```

### 3.2 非 LLM 兜底实体提取

```python
# sag_retriever.py 改造（伪代码）
_STOPWORDS = {"的", "了", "是", "在", "和", "有", "不", "这", "我", "你", "他", "她",
              "它", "们", "那", "就", "都", "也", "还", "但", "而", "如果", "因为",
              "所以", "虽然", "或者", "什么", "怎么", "为什么", "如何", "哪些", "哪个",
              "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
              "have", "has", "had", "do", "does", "did", "will", "would", "could",
              "should", "may", "might", "shall", "can", "to", "of", "in", "for",
              "on", "with", "at", "by", "from", "as", "into", "about", "that",
              "this", "these", "those", "it", "its", "not", "no", "nor", "or",
              "and", "but", "if", "then", "else", "when", "up", "out", "so", "than"}

def _fallback_extract_entities(query: str, max_entities: int = 5) -> list[str]:
    """非 LLM 兜底：从查询中提取候选实体名（按空白/分隔符切词，过滤停用词和单字符）"""
    import re
    tokens = re.split(r'[\s，。、；：？！,.:;?!\n\t]+', query)
    candidates = [t.strip() for t in tokens if len(t.strip()) > 1 and t.strip().lower() not in _STOPWORDS]
    return candidates[:max_entities]

async def retrieve(query: str, top_k: int = 5) -> list[dict]:
    # Step 1: 提取查询实体（LLM 优先，失败/空时兜底）
    entity_names = []
    try:
        from rag.graph.graph_extractor import extract_from_query
        entity_names = await asyncio.wait_for(extract_from_query(query), timeout=10)
        entity_names = [e for e in (entity_names or []) if e.strip()]
    except Exception as e:
        logger.warning("SAG 查询实体 LLM 提取失败，启用兜底: %s", e)

    if not entity_names:
        entity_names = _fallback_extract_entities(query, max_entities=top_k)
        if entity_names:
            logger.info("SAG 兜底提取实体: %s", entity_names)

    if not entity_names:
        return []  # 无有效候选，返回空

    # Step 2: SQL 检索（复用现有逻辑）
    ...
```

### 3.3 SAG 命中项 boost

- boost 系数 1.2（硬编码常量 `_SAG_SCORE_BOOST = 1.2`）。
- 应用位置：`sag_docs` 列表每个 doc 的 `hybrid_score` 字段。
- 上限截断：`min(score * 1.2, 1.0)`。
- 仅对 SAG 命中项生效，常规结果不受影响。
- reranker 精排不受 boost 影响（reranker 用自己的 cross-encoder 分数重排）。

## 4. 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| search 端点 SAG 改造引入回归 | search 行为变化 | `hybrid` 默认路径零改动；conftest 钉住 hybrid |
| 非 LLM 兜底分词质量低 | 候选实体不精准，SAG 命中率下降 | 仅作降级兜底，LLM 正常时不用；兜底实体做 ILIKE 模糊匹配 |
| SAG boost 系数 1.2 未经验证 | SAG 命中项排序偏高 | boost 仅在 reranker 前生效，reranker 会用自己的分数重排；1.2 是轻 boost，不过度干扰 |
| LLM 超时增加 search 延迟 | search 端点响应变慢 | extract_from_query 有 10s 超时；兜底逻辑零 LLM 调用 |
| 200 行预算紧张 | 功能裁剪 | 三项合计 ~90 行，充裕 |

## 5. 待澄清

无。三项需求在 task-brief 中已明确定义，实现方案已对齐 module-081 现有架构。
