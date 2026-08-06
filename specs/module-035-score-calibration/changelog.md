# 变更日志 — Module-035: 记忆/检索分数口径校准

## 变更概述

校准记忆/检索的"分数语义"——把**相对分（min-max 排名信息）当绝对阈值（质量判断）用**的
用错尺子问题一次收敛（问题分析见 `score-issues.md`）。动态 K / 去重 / 低分过滤统一改
**绝对 embedding 余弦**口径：

1. **动态 K 改绝对余弦（P1，核心）** — `recall` / `recall_short` 的候选平均相似度由
   `hybrid_score`（min-max **相对**归一化，跨查询不可比）改为**绝对余弦**：
   query 经 `embedding_service.embed_text` 嵌入（L2 归一化）→ 候选子块 embedding 按 id
   从库读取（存时已 L2 归一化，点积=cosine）→ 每条算 `dot(query_emb, doc_emb)` → 低分过滤
   （`abs_cosine < memory_recall_min_score`=0.4 丢弃）→ 按绝对余弦降序 → 均值判定档位
   （>0.85→5 / 0.75-0.85→3 / <0.75→1）。**K=5/3 档真实可达，不再恒 K=1**。
2. **低分过滤（P1 加防）** — 绝对余弦 < 0.4 的候选丢弃，防"本批相对高但绝对烂"记忆注入。
3. **去重阈值校准（P5）** — `memory_dedup_threshold` 默认 0.95 → **0.85**（真实 bge-m3
   同义改写 cosine≈0.88，0.95 太严漏去重）；同义改写触发"更新旧记忆而非新增"，记忆库不膨胀。
4. **min_score 校准（P2）** — `main.py` chat_stream 移除失真阈值 `MIN_SCORE=0.3`（作用于
   min-max 相对分，语义失真）；`relevant_count` 改为统计检索召回数（检索即相关性门控，
   仅供 UI 展示，不影响回答正确性）。
5. **新增配置** — `memory_recall_min_score=0.4`（低分过滤阈值，绝对余弦口径，可配）。

**P3（三通道 RRF 融合）：评估后决定不采纳，保持 min-max 加权现状**（原因见下）。

全量单测 **292 passed / 0 failed**（278 基线 + 14 新增）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/memory.py | 修改 | 动态 K 改绝对余弦：新增 `_cosine` / `_child_embeddings` / `_absolute_cosine_avg`；recall/recall_short 走绝对余弦口径（低分过滤 + 降序 + 均值）；`_expand_to_parents` 优先用 `abs_cosine`；query 嵌入/embedding 读取失败降级用原 hybrid_score（不回退失败） |
| ai_service/src/config.py | 修改 | `memory_dedup_threshold` 0.95→0.85；新增 `memory_recall_min_score=0.4`；动态 K 档位阈值注释改绝对余弦口径 |
| ai_service/main.py | 修改 | chat_stream 移除失真 `MIN_SCORE=0.3`；`relevant_count = retrieval_count`（仅统计展示） |
| ai_service/tests/test_memory.py | 修改 | 更新既有 recall 用例为确定性降级/绝对口径；新增 `TestRecallDynamicKAbsCosine`（三档真实可达+低分过滤+空候选+嵌入失败降级）、`TestRecallShortAbsCosine`、`TestChildEmbeddings`、`TestDedupThreshold035`、`TestConfig035` |
| ai_service/tests/test_memory_extractor.py | 修改 | `TestRecallDynamicK` 改绝对余弦口径（mock query 嵌入 + 候选 embedding）；去重注释 0.95→0.85 |

## 关键设计说明

### 设计决策 1: 记忆统一绝对余弦口径（动态K / 去重 / 低分过滤同尺子）
- 决策: 动态 K 档位判定、去重命中判定、低分过滤全部用**绝对 embedding 余弦**
  （候选子块 embedding 存库已 L2 归一化 → 点积=cosine；query 经 embed_text 归一化）。
  阈值入 config：`memory_recall_high/mid_threshold`（0.85/0.75，档位不变，语义回归）、
  `memory_dedup_threshold`（0.85）、`memory_recall_min_score`（0.4）。
- 原因: `hybrid_score` 是 min-max **相对**归一化分（retriever.py `_normalize` 注释"跨查询
  不可比"），套 0.85/0.75 绝对阈值必然失真——候选 ≥3 时均值必跌破 0.75 → **恒 K=1**
  （K=5/3 档死代码）。绝对余弦跨查询可比，档位语义真实可达。
- 兼容: recall/recall_short 的 source 精确匹配、`_expand_to_parents` 同父块去重取最高分、
  recall 返回格式（content/score/title/created_at）、chat/stream 端点签名均不变。

### 设计决策 2: 嵌入失败降级用原 hybrid_score（不回退失败）
- 决策: query 嵌入失败 **或** 候选 embedding 读取失败 → 跳过绝对余弦，退回原 `hybrid_score`
  均值判定 + 原排序（不做低分过滤）。任何异常只日志，不向上抛（recall 的 5s 超时链路不受影响）。
- 原因: 嵌入是记忆召回链路的**可选增强**；失败时保留既有行为保证"宁缺毋滥"仍有结果，零回归。

### 设计决策 3: 去重阈值 0.95 → 0.85
- 决策: `memory_dedup_threshold` 默认 0.85。0.88（真实同义改写）> 0.85 → 命中去重（更新
  旧记忆而非新增）；0.80（不同事实）≤ 0.85 → 正常新增。
- 原因: 0.95 对真实 bge-m3 同义改写（cosine≈0.88）过严 → 措辞变化时"二次同义对话不膨胀"
  不成立，记忆缓慢膨胀。下调后平衡漏去重/误合并（plan 风险 #2，可配）。

### 设计决策 4: min_score 校准 = 移除失真阈值（仅统计展示）
- 决策: chat_stream 的 `MIN_SCORE=0.3` 作用于 min-max 相对分（跨查询不可比），绝对 0.3
  阈值语义失真；`relevant_count` 仅供 UI 展示、不影响回答正确性 → **移除阈值**，改为统计
  检索召回数（检索步骤本身即相关性门控）。
- 原因: 绝对余弦口径在该处需额外 query 嵌入 + 候选 embedding 读取（docs 不携带 embedding），
  对一个纯展示统计不值得增加请求延迟；plan §3.2 功能 3 明确允许"移除该阈值只做统计展示"。

### 设计决策 5（评估）: P3 三通道 RRF **不采纳**，保持 min-max 加权
- 决策: 评估后决定**不实施** RRF 排名融合，保持现状（`hybrid_score = alpha*fts + (1-alpha)*vector`）。
  记录为 backlog 后续项（需联动处理 `engine._retrieve` 的 min_score 过滤口径）。
- 评估依据:
  1. **RRF 分数量纲与现有过滤不兼容（硬阻塞）**：RRF `1/(60+rank)` 得分约 0.017–0.033，
    而 `engine._retrieve(query, top_k=20)` 默认 `min_score=0.6` 对 `hybrid_score` 做低分过滤
    （`if d.get("hybrid_score", 0) >= min_score`，engine.py:655）。min-max 加权下最高分恒为
    1.0，0.6 相当于"保留本批 Top 段"；RRF 下全批 <0.033 → **聊天路径全部文档被过滤掉 →
    检索结果恒空**。采纳 RRF 必须级联重设 `_retrieve` 过滤语义，超出 P3 声明范围（"融合改 RRF"）。
  2. A/B 充分性不足：仅靠 golden_retrieval Hit@k/MRR 无法暴露上述生产路径回归（该过滤在
     `engine._retrieve` 内，golden 评估直连 `hybrid_retriever.retrieve`，不经过该过滤）。
  3. 本模块核心（P1 动态K / P5 去重 / P2 min_score）已交付并回归通过；P3 属 backlog 优化
     （score-issues.md §P3），环境（DB/embedding）可用但"采纳路径不安全"，故保持现状。
- 结论: 按 plan §3.4 "RRF 走评估，不盲目替换融合"，本次不采纳；后续模块需在引入 RRF 时
  一并校准 `engine._retrieve` 的 min_score 过滤语义（与本次绝对余弦口径同思路）。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 记忆单测 | `python -m pytest tests/test_memory.py tests/test_memory_extractor.py -q` | 95 passed（81 基线 + 14 新增） |
| 全量回归 | `python -m pytest tests/ -q` | **292 passed / 0 failed**（278 基线 + 14 新增） |
| 编译检查 | `python -m py_compile rag/memory.py src/config.py main.py tests/test_memory.py tests/test_memory_extractor.py` | OK |
| P3 A/B（未实施） | `python -m eval.golden_retrieval` | 不执行（评估后决定不采纳，见设计决策 5） |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-06 | 初始实现（动态K绝对余弦+低分过滤 / 去重阈值 0.85 / min_score 移除失真阈值 / P3 评估不采纳 + 14 单测） | Developer(m35-dev) |
