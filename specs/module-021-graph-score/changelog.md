# 变更日志 — Module-021: 图分数归一化（graph_score 真实相关度）

> 版本号: 0.21.0-module-021 | 日期: 2026-08-01 | 变更人: Developer

## 变更概述

修复 `graph_store.search_related` 返回文档 `hybrid_score` 硬编码 0.6 的问题：
将图检索结果从「固定分数 + 任意排序」升级为「命中实体数驱动的真实相关度」。
每篇文档的相关度定义为被「查询实体 + 一跳邻居」中多少个实体引用（命中实体数），
经 min-max 归一化到 [0,1] 后作为 `hybrid_score`，并按真实命中数降序排序取 top_k。
接口 `search_related(entities, top_k=10) → list[dict]` 保持不变。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/graph_store.py` | 修改 | search_related 计算真实 graph_score；新增 `_count_doc_hits`、`_normalize_graph_scores` 两个辅助方法 |
| `ai_service/tests/test_graph_store.py` | 新增 | 归一化（含保底分支）、排序正确性、接口字段完整性、边界（空/无命中）单测 |

## 关键设计说明

### 设计决策 1: 命中实体数作为相关度
- 决策: `graph_score = 命中实体数`，即文档被「查询实体 e ∪ 一跳邻居 related」中多少个实体引用。
- 原因: 被越多实体引用的文档与查询越相关，指标可解释。Cypher 用 `UNWIND [e] + CASE WHEN related IS NULL THEN [] ELSE [related] END` 逐实体展开 `doc_ids`，`count(DISTINCT ename)` 去重计数。
- 验证: 本地 AGE（PostgreSQL 16 + AGE 1.6）实测 UNWIND 可用。

### 设计决策 2: min-max 归一化 + 全同分保底 0.6
- 决策: Python 层 `_normalize_graph_scores` 复用 `retriever._normalize` 的 min-max 范式，但全同分/单结果时返回 **0.6**（而非 `_normalize` 的 1.0）。
- 原因: 与历史硬编码 0.6 一致，避免图结果在无区分度时给三通道融合一个突兀的高分。
- 注意: 不能直接复用 `retriever._normalize`（其保底值为 1.0），故独立实现为 `GraphStore._normalize_graph_scores`。

### 设计决策 3: 排序用原始计数，归一化只改分数值
- 决策: 排序 key 用真实命中数（`hit_map`），归一化只影响 `hybrid_score` 数值。
- 原因: 归一化保持序关系（min-max 单调），但显式用原始计数排序更稳健，避免归一化数值精度问题影响顺序。
- Cypher 侧 `LIMIT top_k*2` 取 2 倍候选（符合 plan §4.3 诊断建议）。

### 设计决策 4: AGE 方言适配
- 决策: Cypher `ORDER BY` 必须用 `count(DISTINCT ename)` **表达式**而非别名。
- 原因: 实测 AGE 对别名排序报 `could not find rte for hits`（`ORDER BY hits DESC` 失败），改用表达式后通过。
- 候选池语义: 新查询同时含查询实体 e 自身与一跳邻居 related 的 doc_ids；旧查询用 `COALESCE(related.doc_ids, e.doc_ids)` 只在 e 无关系时才含 e.doc_ids。新池 ⊇ 旧池，召回不降。

## 验证命令与结果

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 分数测试 | `python -c "...graph_store.search_related(['Java','线程池'], top_k=5)..."` | 分数范围 OK: `[1.0, 0.833, 0.667, 0.5, 0.333]`，∈[0,1] 且有区分度，按命中数降序 |
| 边界 | 空实体 / 未知实体 | 均返回空列表 |
| 单元测试 | `python -m pytest tests/test_graph_store.py` | 8 passed |
| 回归 | `python -m pytest tests/` | 46 passed, 2 failed（`test_engine.py` 2 个 async 用例 — 既有问题，缺 pytest-asyncio，见 module-018 技术债务，非本模块回归） |
| FTS 回归 | `python -m eval.golden_retrieval --mode fts_only --no-save` | Hit@5 = 0.4348（与 module-020 基线一致，无回归） |
| graph_only 评估 | `python -m eval.golden_retrieval --mode graph_only` | ⚠️ 无法执行：LLM API（ModelScope qwen/zhipu）今日 429 配额超限，实体提取失败导致全题跳过。替代验证见下 |

### graph_only 评估替代验证（LLM 配额受限）

因 ModelScope LLM API 今日 429（`You have exceeded today's quota`），完整 LLM 驱动的
`graph_only` 评估无法运行（与 module-018 记录的 embedding 502 同类环境阻塞）。
改用确定性替代验证（真实图数据，不依赖 LLM）：

1. **机制隔离验证**：对 golden 集中 golden doc 被图实体引用的 19 题，用「真实引用该
   golden doc 的实体集合」作为查询实体 → 新实现 Hit@5 = **19/19 = 1.0000**。
   4 题（MoE/LoRA/KV Cache/RAG）golden doc 在图谱中无实体引用（module-016 数据覆盖
   缺口，非本次变更引入），无法经图通道召回。
2. **A/B 对比**：对 23 题用题目强相关实体（模拟 LLM 提取）→ 新实现 Hit@5 = 0.6957
   优于旧行为（硬编码 0.6 + 任意排序）= 0.6522，且 ≥ module-019 基线 0.50。

LLM 配额恢复后可重跑 `python -m eval.golden_retrieval --mode graph_only` 复核完整基线。

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：命中实体数 + min-max 归一化 + 真实排序 | Developer |
