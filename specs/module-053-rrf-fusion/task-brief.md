# Module-053 任务简报：检索融合升级（RRF 三通道消融验证）

> ✅ **已实施并放行（2026-08-12）**——详见本目录 `changelog.md`（放行决策表：RRF Hit@5=0.9905 > 基线 0.9714 > 加权=基线；645 passed；上线方式 `PW_RETRIEVAL_FUSION_MODE=rrf` 一键开启，默认保持 hybrid 零回归）。
> 自包含执行简报。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读），无需重新调研。

## 一、任务背景

**项目**：Agentic RAG 技术文档知识库（`.claude/worktrees/m8-knowledge-panel/ai_service`，FastAPI + asyncpg + pgvector + Apache AGE）。

**现状（代码实测，勿改口径）**：
- **混合检索**（`rag/retrieval/retriever.py`，hybrid 模式）：query 向量化 → **并行 FTS+向量** → **min-max 归一化 → alpha 加权融合**（`alpha=0.3`：FTS 30% / 向量 70%，`hybrid_score = 0.3×fts_norm + 0.7×vec_norm`）——**没有 RRF**
- **图谱通道**（`rag/engine.py` round 0）：`asyncio.gather(hybrid_retriever.retrieve, graph_store.search_related)` 并行 → **按 doc id 合并去重**（混合结果优先，图谱独有的追加，graph_score 与 hybrid_score 互不乘除）；**图谱只在 round 0 查一次**，round 1/2 只用混合检索
- **重排**（`rag/retrieval/reranker.py`）：**CrossEncoder**（bge-reranker-v2-m3）对 Top-20 精排取 Top-5——**不是 RRF**（CrossEncoder 是细排，RRF 是粗排，两层不同，可共存）
- **评估基线**：golden 112 题 Hit@5 **0.9714**（102/105，eval_runs id=13）——注意这是"两通道加权 + 图谱追加"口径

**要做的升级**：验证"把图谱从'按 id 追加'升级为'真正参与融合排序'（业界标准 RRF 三通道）"是否有增益。**用消融数据决定，不拍脑袋。**

## 二、已知事实（勿重新调查）

| # | 事实 |
|---|---|
| 1 | 业界多路融合三方案：**RRF**（`Σ 1/(k+rank)`，k=60，不看分数只看排名，零调参最稳健）/ 归一化加权（要同量纲+调权重，α 敏感）/ 学习排序（要标注+训练，上限最高） |
| 2 | **硬数据**（100 万条中文技术文档实测）：纯稠密 MRR@10 0.68/Recall 82%；稠密+稀疏加权 0.81/90%；**稠密+稀疏+图谱 RRF 0.87/94%（图谱融合 Recall +4%、MRR +0.06）**；RRF+CE 精排 0.93/96%；生产推荐 = **RRF 粗排 → 交叉编码器精排**（本项目已有精排层，缺粗排融合层） |
| 3 | RRF 是粗排层方案，CrossEncoder 是细排层方案——**两阶段共存**是业界标准，不冲突 |
| 4 | 量纲风险：graph_score 是离散命中计数（实体命中数 min-max），hybrid_score 是连续相似度——**直接加权会引入噪声**，这正是业界用 RRF 而非加权的核心理由 |
| 5 | 评估基建已有：`eval/golden_retrieval.py` + eval_runs 表（git_commit/config_snapshot/scores/per_question）+ `--compare` 版本对比 |
| 6 | L3 反证依赖 `abs_cosine`（retriever 归一化前存档，module-043）——改融合逻辑**不得破坏 abs_cosine 存档** |

## 三、任务步骤（按序，每步有通过标准）

### WP-A 基线复测（🔴 最先，低成本）
- 用当前代码跑 golden 检索评估，**确认 0.9714 基线可复现**（拿到本次 commit 的基线数字，作为后续对比锚点）
- **通过标准**：基线数字落地 eval_runs，与历史 0.9714 同口径可比

### WP-B RRF 三通道原型（🔴 核心）
- 实现 **RRF 融合**：FTS 排名 + 向量排名 + 图谱排名，`score(d) = Σ 1/(60 + rank_i(d))`（k=60 先取业界默认）
- **接入方式**：新增融合模式开关 `retrieval_fusion_mode: hybrid(现状默认) | rrf`——**默认 hybrid 零回归**，rrf 模式可切换
- 三路各自的排名来源：FTS 结果排名 / 向量结果排名 / 图谱结果排名（图谱仅 round 0 有——RRF 融合只在 round 0 生效，round 1/2 保持单路混合，语义要在注释里写明）
- 跑 golden，与基线 `--compare`
- **通过标准**：与基线对比有数据结论（提升/持平/下降），delta 落 eval_runs

### WP-C 加权三通道对照（🟡 可选，用于回答"RRF vs 加权哪个好"）
- 三路各自 min-max 归一化 → `α₁×fts + α₂×vec + α₃×graph`，权重消融（至少试 2-3 组，如 0.3/0.6/0.1、0.25/0.5/0.25）
- 跑 golden 对比 RRF 结果
- **通过标准**：产出"本项目场景下 RRF vs 加权"的实测对比结论

### 放行决策
```
RRF 或加权三通道 ≥ 基线（0.9714 同口径）？
├─ 是 → 选增益最大的方案上线（保留 hybrid 作为回退开关）
└─ 否 → 维持现状（图谱按 id 追加），记录否决理由，不强行改
```

## 四、纪律项（违反 = 返工）

1. **不破坏现状**：新融合必须是可切换模式（`retrieval_fusion_mode`），默认 `hybrid` 零回归——所有现有测试（614 个）必须全绿
2. **不改重排层**：RRF 是粗排、CrossEncoder 是细排，两阶段共存；reranker.py 不动
3. **不得破坏 abs_cosine 存档**：L3 反证依赖它（归一化前存档），改融合逻辑时保留
4. **评估口径一致**：新旧数字必须用同一 golden 集、同一评估脚本、同一 eval_runs 表对比——旧 0.9714 是"两通道+追加"口径，新数字要注明融合模式
5. **图谱 round 0 语义交代清楚**：RRF 融合只在 round 0 生效，round 1/2 单路——文档/注释写明，面试口径才站得住

## 五、交付物

1. WP-A 基线复测记录（eval_runs id）
2. WP-B/WP-C 对比表：基线 vs RRF vs 加权（Hit@5 / Recall@k / MRR，同口径）
3. 选型结论（是否上线、用哪个模式），写回 08 文档 2.4 节 + ADR（如需）
