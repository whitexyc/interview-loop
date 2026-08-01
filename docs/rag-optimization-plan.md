# RAG 优化实施计划

> 状态：已确认决策，待执行
> 关联文档：[rag-flow.md](./rag-flow.md)（RAG 完整流程基准）
> 确认日期：2026-08-01

---

## 背景

基于 `docs/rag-flow.md` 的完整流程分析，已确认 5 个关键问题，按依赖关系排定 4 个阶段实施。

### 已确认的问题

| # | 问题 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | Reflector 硬编码 deepseek，不走降级链 | P0 | 待改 |
| 2 | Graph 数据已入库但用户看不到（存于 AGE 专用表） | — | 已澄清 |
| 3 | Graph 检索结果 hybrid_score 硬编码 0.6 | P1 | 待改 |
| 4 | 检索反思循环串行 LLM 调用延迟高 | P2 | 待改 |
| 5 | bge-reranker-v2-m3 缺权重 → 重排从未生效 | P0 | 已下载替代模型 |

---

## 阶段 1：Rerank 修复（最高优先级）

### 现状

- `models/bge-reranker-v2-m3/` 只有 tokenizer（17MB），无权重 → `CrossEncoder` 加载抛 `OSError` → 上层静默降级为原始排序
- **重排从未真正生效**

### 方案（决策：直接本地，不回退 HuggingFace）

| # | 任务 | 说明 |
|---|------|------|
| 1.1 | reranker.py 指向 Qwen3-Reranker | `_LOCAL_MODEL_DIR` → `models/Qwen3-Reranker-0.6B`（已下载，1.14GB） |
| 1.2 | 本地缺权重时明确报错 | **决策：不回退 HF**。缺权重直接抛 `RerankerException`，让问题可见而非静默降级 |
| 1.3 | 分数归一化确认 | Qwen3-Reranker predict 输出确认范围，配合阶段 3 |
| 1.4 | rag_config 同步 | `reranker_model` → `Qwen/Qwen3-Reranker-0.6B` |
| 1.5 | 端到端验证 | 真实 query + docs 走 rerank，确认排序变化 |

### 风险

- 0.6B CPU 推理较慢（每对约 50-100ms）
- 首次加载 1.1GB 入内存较慢（后续复用实例）

---

## 阶段 2：降级链调整

### 决策（用户确认）

1. **全局降级链**：`deepseek → qwen → zhipu`（deepseek 优先）
2. **Reflector：只用 deepseek**，不改走 fallback 链

### 任务

| # | 任务 | 说明 |
|---|------|------|
| 2.1 | `.env` 改 `PW_FALLBACK_CHAIN=deepseek,qwen,zhipu` | 纯配置 |
| 2.2 | `config.py` 默认值同步 | `fallback_chain` 默认改同值 |
| 2.3 | Reflector 保持硬编码 deepseek | 不改代码（用户确认只用 deepseek） |

### 验证

- FallbackClient 降级顺序按新链
- Reflector 仍走 deepseek（不受链顺序影响）

---

## 阶段 3：Graph 分数归一化

### 决策（用户确认）

用**命中实体数**作为图结果的相关度，min-max 归一化到 [0,1]。

### 任务

| # | 任务 | 说明 |
|---|------|------|
| 3.1 | Cypher 返回每篇 doc 的命中实体数 | `search_related` 计算相关度 |
| 3.2 | 归一化 | 对所有图结果实体数做 min-max → [0,1] |
| 3.3 | 融合 | 保持 hybrid_score 语义（0-1），图结果与向量结果可比 |

### 关键点

- 现在 `hybrid_score=0.6` 常量 → 图结果永远排中间
- 归一化后反映真实相关度，排序更合理

---

## 阶段 4：检索延迟优化（P2-10）

### 决策（用户确认）

- **4a 全做**：超时收敛 + 提前终止 + HyDE 缓存 + round 0 超时降级
- **4b 只做 round 0 超时降级**；HyDE 并行化评估后再说

### 4a 任务（低风险，先上）

| # | 任务 | 改动 |
|---|------|------|
| 4a.1 | 超时收敛 | `_retrieve` 加总 deadline（约 20s），到点强制进入生成 |
| 4a.2 | 提前终止强化 | 第一轮反思 sufficient 立即 break |
| 4a.3 | HyDE 结果缓存 | HyDE 输出进 Redis 复用 |
| 4a.4 | **round 0 超时降级** | `asyncio.gather` 向量检索超时时降级为仅图结果，不整链路崩 |

### 4b 任务（评估后决定）

| # | 任务 | 状态 |
|---|------|------|
| 4b.1 | HyDE 与首次检索并行 | 设计决策（丢弃 vs 合并首轮）待评估 |
| 4b.2 | 反思循环并行化 | 待评估 |

---

## 依赖顺序

```
阶段 1（Rerank）→ 阶段 2（降级链）→ 阶段 3（Graph 分数）
        ↓
阶段 4a（超时/缓存/降级修复）
        ↓
阶段 4b（并行化，评估后）
```

**理由**：阶段 4 的"反思是否充分"判断依赖 Rerank 排序正确 → Rerank 优先。

---

## 验证标准

| 阶段 | 通过标准 |
|------|----------|
| 1 | rerank 返回归一化分数，排序与原始检索不同且合理；无静默降级 |
| 2 | 降级顺序 deepseek→qwen→zhipu；reflector 走 deepseek |
| 3 | Graph 结果 hybrid_score ∈ [0,1]，反映实体命中数 |
| 4a | 超时降级生效；缓存命中减少延迟；round 0 超时不崩链路 |
