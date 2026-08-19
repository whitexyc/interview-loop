# Changelog — Module-047 数据实验批（真实 baseline + 阈值校准 + golden 扩样本 + 图谱消融）

> Developer | 2026-08-10 | 依据 plan.md / acceptance-criteria.md

## 1. 交付物清单

| WP | 交付物 | 文件 | 状态 |
|----|--------|------|------|
| WP1 | 真实 intent baseline 落库 | eval/golden_intent.py（未改动） | ✅ 实测 |
| WP1 | 真实 sufficiency baseline 落库 | eval/golden_sufficiency.py（未改动） | ✅ 实测 |
| WP2 | 阈值扫描脚本（新建） | eval/threshold_scan.py | ✅ 新建 |
| WP2 | 阈值扫描测试（新建） | tests/test_threshold_scan.py | ✅ 22 用例 |
| WP3 | golden 扩样本 30→112 | eval/golden.json | ✅ 实测回归 |
| WP3 | 检索回归测试适配 | tests/test_golden_retrieval.py（1 处断言改数据无关） | ✅ 必须的测试适配 |
| WP4 | 图谱消融运行 | eval/golden_retrieval.py --ablate | ⚠️ 环境不可用，交付方法学 |

## 2. WP1 真实 baseline（实测数字，2026-08-10 凌晨）

### 2.1 intent 分类（python -m eval.golden_intent，真实 LLM 100 条）

| 指标 | 值 |
|------|-----|
| 数据集 | 100 条（knowledge 50 / casual_chat 30 / realtime 20） |
| Evaluated / Skipped | 100 / 0（零失败，无需重试） |
| **Accuracy** | **1.0000** |
| 混淆矩阵 | 全对角（30/30 casual_chat，50/50 knowledge，20/20 realtime） |
| eval_runs 落库 | id=11，eval_type='intent'（首条正式 intent 记录），commit=2eac844c |

- 说明：此前 0.9667 是 --no-save 冒烟；本次为正式首条 intent 落库记录。
- LLM 自报 confidence 范围 [0.75, 1.00]，全样本 > 0.5 → L2 触发机制在本数据集零触发。

### 2.2 充分性判断（python -m eval.golden_sufficiency，真实模式 reflector 100 条）

| 指标 | 值 |
|------|-----|
| 数据集 | 100 条（充分 50 / 不充分 50，每条 2 篇文档） |
| Evaluated / Skipped | 100 / 0 |
| **Accuracy** | **1.0000** |
| **insufficient Recall** | **1.0000**（漏判 0） |
| 混淆矩阵 | 全对角（50/50 insufficient，50/50 sufficient） |
| eval_runs 落库 | id=12，eval_type='sufficiency'（首条正式 sufficiency 记录），commit=2eac844c |

- 说明：此前无充分性真实 baseline（只有 fixture 冒烟）；本次为正式首条记录。
- 层 1 硬闸门（top-1 abs_cosine < 0.4）+ LLM 层在当前标注集上 100% 判对。

## 3. WP2 阈值校准（实测数字，数据驱动）

脚本：`eval/threshold_scan.py`（新建）；数据收集缓存 `ai_service/.ua/m047_threshold_cache.json`（gitignore）。

### 3.1 ① L2 触发阈值扫描（t ∈ [0.20, 0.80] 步长 0.05）

数据：golden_intent 100 条 × 真实 LLM 原始分类（不走 L2）+ 真实确定性信号
（router._deterministic_confirm：FTS 术语命中/图谱实体/规则表否决/保守降级，零 LLM）。

**实测（最终运行，2026-08-10 03:52，缓存已再生）：**

| t | TP | FP | FN | Precision | Recall | F1 | final_acc |
|---|----|----|----|-----------|--------|-----|-----------|
| 0.20~0.70 | 0 | 0 | 2 | 0.0000 | 0.0000 | 0.0000 | 0.9800 |
| 0.75 | 1 | 1 | 1 | 0.5000 | 0.5000 | 0.5000 | 0.9800 |
| 0.80 | 1 | 1 | 1 | 0.5000 | 0.5000 | 0.5000 | 0.9800 |

- 本轮应触发样本 2 条（LLM 把 2 条 knowledge 判成非 knowledge，confidence
  均 ∈ [0.5, 0.8)）→ **经验值 0.5 触发覆盖率 = 0**（2/2 漏检）。
- 上调到 0.75 抓到 1 条，但同时误触发 1 条（非 knowledge 样本被 FTS 信号
  误确认修正为 knowledge）→ F1 仅 0.5，**final_acc 与 0.5 持平（0.98）：
  修正 1 条 + 破坏 1 条，无净收益**。
- LLM 非确定性如实记录：首轮独立采样（03:47）应触发样本 = 0（100/100 判对，
  final_acc 0.99）；次轮（03:52）应触发样本 = 2。两轮共同事实：
  ① LLM 自报 confidence 域内偏高（两轮 min 均为 0.70）；② t=0.5 触发覆盖率
  两轮均为 0；③ 0.75+ 区间 FP 代价抵消修正收益。
- **结论（数据驱动）**：经验值 0.5 无法被证明最优，但**当前数据上不存在
  净改进空间**——上调阈值受 LLM confidence 校准限制（域内偏高），下调无
  应触发需求。建议保持 0.5 零回归；后续校准需更大/更难样本集（出现
  confidence<0.5 的漏判样本），可把扫描区间上移到 0.6-0.95 再做一轮。
- 附带发现：确定性信号中 FTS 术语命中会命中部分闲聊样本（如"谢谢""再见"
  命中 KB 倒排索引）→ 阈值上调时误修正风险显著（0.75 轮 FP=1 即此原因）。

### 3.2 ② 充分性硬闸门阈值扫描（t ∈ [0.20, 0.60] 步长 0.05）

数据：golden_sufficiency 100 条 × **实测 bge-m3 余弦**（生产同款本地嵌入：
question 与每条注入文档的余弦，取 top-1，100 条全成功 0 error）。
假设（报告中明示）：闸门未触发（score ≥ t）时默认判充分——隔离闸门单独判别力，
生产剩余样本走 LLM 层。

实测 top-1 余弦分布：

| 类别 | n | min | p25 | median | p75 | max |
|------|---|-----|-----|--------|-----|-----|
| 充分 | 50 | 0.490 | 0.664 | 0.714 | 0.764 | 0.807 |
| 不充分 | 50 | 0.322 | 0.381 | 0.422 | 0.452 | 0.550 |

P/R/F1 曲线（positive = 不充分，漏判最致命）：

| t | TP | FP | FN | Precision | Recall | F1 | Accuracy |
|---|----|----|----|-----------|--------|-----|----------|
| 0.20 | 0 | 0 | 50 | 0.0000 | 0.0000 | 0.0000 | 0.5000 |
| 0.25 | 0 | 0 | 50 | 0.0000 | 0.0000 | 0.0000 | 0.5000 |
| 0.30 | 0 | 0 | 50 | 0.0000 | 0.0000 | 0.0000 | 0.5000 |
| 0.35 | 6 | 0 | 44 | 1.0000 | 0.1200 | 0.2143 | 0.5600 |
| 0.40 | 20 | 0 | 30 | 1.0000 | 0.4000 | 0.5714 | 0.7000 |
| 0.45 | 37 | 0 | 13 | 1.0000 | 0.7400 | 0.8506 | 0.8700 |
| 0.50 | 46 | 1 | 4 | 0.9787 | 0.9200 | 0.9485 | 0.9500 |
| **0.55** | **49** | **1** | **1** | **0.9800** | **0.9800** | **0.9800** | **0.9800** |
| 0.60 | 50 | 3 | 0 | 0.9434 | 1.0000 | 0.9709 | 0.9700 |

**推荐阈值: 0.55**（argmax F1=0.98；不充分漏判率 2%，误杀充分样本 1/50）。
与经验值 0.40 对比：

- **经验值 0.40 明显偏低**：在当前标注集上只抓回 40% 的不充分样本
  （漏判 60% → 基于无关文档硬答的最致命风险高发）。
- 0.50~0.55 是分布间隙（充分 min=0.490，不充分 max=0.550），推荐 0.55
  落在间隙上缘；若追求"零漏判"可升 0.60（FN=0，但误杀 3 个充分样本）。
- **建议**：把 `reflector._SUFFICIENCY_MIN_ABS_COSINE` 从 0.4 上调至 0.5~0.55。
  建议具体实施时选 0.5（保守上移：Recall 0.92、误杀仅 1 个、与充分类
  min=0.490 紧贴）或 0.55（F1 最优）。⚠️ 注意：本扫描的分数源是
  question vs 数据集注入文档的实测余弦（文档为标注集代表内容），
  生产真实检索文档的分数分布可能不同——上线前建议用真实检索分数抽样复核；
  本次证据方向明确（0.4 明显偏低），量级判断可信。

（决策点留给 Planner/Reviewer：改阈值涉及 agent/reflector.py，不在本模块
红线文件清单内，本模块只交付校准证据。）

## 4. WP3 golden 扩样本 30 → 112

### 4.1 数据扩充

- 原 30 题原样保留（question/golden_docs/category 字段零改动）。
- 新增 82 题，主题全部来自知识库真实内容（50 个真实文档根标题，
  documents 表实测核对），覆盖：G1/JVM 类加载/线程池/AQS/HashMap/volatile/
  Spring IoC+AOP/MyBatis/MySQL 索引与事务与日志/Redis 持久化与缓存/
  Nacos/一致性哈希/ZooKeeper/雪花算法/Seata/Sentinel+Gateway/Kafka/RocketMQ/
  Netty/TCP/TLS/AI（推测解码/长上下文/归一化/DPO/量化/vLLM/ZeRO/预训练/
  多模态/评估/CoT/Reflexion）/Agent（工具/MCP/记忆/规划/安全/AgenticRAG/评估）/
  ES/单例。
- 新增题 golden_docs 全部非空且逐一核对存在于 documents 表（0 个悬空引用）。
- 结构校验通过：总数 112 ≥ 100；无空 question；新增题 golden_docs 非空。
- 格式对齐现有结构（question + golden_docs + category；ground_truth 可空
  ——现有条目本无该字段，保持一致不加）。
- 原 7 题空 golden_docs（5 简历 + HTTP/2 + Docker）按历史设计保留
  （简历走 resume_profiles 表、无文档覆盖题标空），检索评估按 no_gold_docs 跳过。

### 4.2 检索回归（DB 可用，实测）

`python -m eval.golden_retrieval --mode hybrid --top-k 5`（2026-08-10，commit=2eac844c）：

| 指标 | 扩前（30 题，id=9） | 扩后（112 题，id=13） | 变化 |
|------|--------------------|----------------------|------|
| 评估题数 | 23 | 105 | +82 |
| **Hit@5** | **0.9565**（22/23） | **0.9714**（102/105） | **+0.0149** |
| Recall@5 | 0.9130 | 0.9571 | +0.0441 |
| MRR | 0.9130 | 0.9270 | +0.0140 |
| 跳过 | 7 | 7（同 7 题） | 0 |

- 未命中 3 题（如实记录，均为标注/检索边界，非回归）：
  1. Transformer Self-Attention（golden: 4-RoPE + 11-归一化，检索到 AgenticRAG 等）——扩前已存在的历史漏检；
  2. 缓存一致性 Cache Aside（golden: 2-Redis缓存穿透击穿雪崩，检索到 HashMap/AQS/MySQL）——新题，标注覆盖弱，可后续校准或加"缓存一致性"文档；
  3. RocketMQ 与 Kafka 选型（golden: 11-RocketMQ，检索全返回 Kafka 文档）——新题，文档标题强相关干扰，可后续校准。
- 简历口径目标达成：80+/100 题命中 → 实测 102/105。
- degraded=0（无向量通道降级）。

### 4.3 测试适配（必须，说明原因）

- tests/test_golden_retrieval.py `TestRunEvalEndToEnd::test_cap_evaluated_and_docker_skipped`
  硬编码 `dataset_size==30 / evaluated==23 / skipped==7` → 数据扩样后必然失败。
  改为数据无关断言（dataset_size==len(load_golden())，evaluated+skipped==dataset_size，
  skipped==空 golden_docs 数），保留 CAP/Docker 标注回归意图。20/20 通过。
- 该文件不在 plan 3.1 红线清单内，但"503 全绿保持"红线要求它必须随数据
  扩充适配；改动仅此 1 处断言逻辑。

## 5. WP4 图谱消融（环境不可用 → 方法学 + 已就绪命令）

### 5.1 环境核查结果（实测）

- DB 可用（documents 7506 行、eval_runs 表正常），但**图谱通道不可用**：
  1. 数据库无图谱表（information_schema 无 ag_catalog/entities/relationships 表）；
  2. graph_store 图搜索报 `UndefinedColumnError: documents.last_mentioned_at
     does not exist`（documents 表缺 module-046 迁移列）→ "图搜索失败，降级返回空"；
  3. graph_extractor 走 LLM 实体提取可用（日志正常），但下游图查询失败。
- 实测 `--ablate --top-k 5` 输出（112 题集，2026-08-10）：
  - graph_only: Hit@5 = **0.0000**（全题图搜索失败降级空，非真实图谱表现）
  - hybrid: Hit@5 = 0.9714 / Recall@5 = 0.9571 / MRR = 0.9270
  - delta = +0.9714 **不可作为图谱贡献量引用**——graph_only 侧为环境故障
    的零分，不是图谱能力的测量。
  **不伪造数字：图谱增量收益（ADR-0004 决策 4 留白 +X.X Hit@5）标注"待环境"。**

### 5.2 方法学（环境就绪后直接执行）

```bash
cd ai_service
python -m eval.golden_retrieval --ablate --top-k 5
# graph_only vs hybrid side-by-side delta（脚本已内置 ablate 报告）
```

前置条件：
1. 应用 module-046 迁移（documents 表补 last_mentioned_at/mention_count 列），
   或修 graph_store 查询避免引用缺失列；
2. 建图谱数据（entities/relationships，rag.graph_store GRAPH_NAME）；
3. graph_only 要求 golden 题实体的图谱链接完整。

判定口径：delta = hybrid.Hit@5 − graph_only.Hit@5；正 delta = 图谱贡献量；
评估集为扩样后 112 题（105 评估）。

## 6. 全量测试

- `python -m pytest tests/ -q`：**525 passed / 0 failed**（503 基线 + 22 新增
  threshold_scan 用例），95.23s，5 warnings（预存）。
- 新增测试文件：tests/test_threshold_scan.py（22 用例：compute_prf / scan_scores /
  recommend_threshold / l2_trigger_samples / l2_final_accuracy / scan_l2 / scan_gate /
  扫描区间常量）。
- 红线遵守：未运行 git commit（Planner 统一提交）；只新增了 plan 3.1 文件 +
  1 处必须的测试断言适配（test_golden_retrieval.py，见 §4.3）；golden.json
  是唯一数据文件改动。
- 实验产物落位：.ua/ 下 *.log 由 gitignore 规则 `*.log` 覆盖不入库；
  `m047_threshold_cache.json`（LLM 原始分类 + 实测余弦缓存，可复跑免 100 次
  LLM 调用）当前未被 ignore——.ua/ 目录在本会话开始前即为未跟踪状态
  （understand 工具产物），建议 Planner 提交时排除该文件（或后续模块将
  ai_service/.ua/ 纳入 gitignore）。

## 7. 已知问题 / 待办

| # | 事项 | 状态 |
|---|------|------|
| 1 | 硬闸门阈值 0.4 → 0.5~0.55 的代码修改（reflector.py）不在本模块红线内，已交付证据，待后续模块实施 | 决策待定 |
| 2 | WP4 图谱消融数字待环境（缺迁移列 + 缺图谱表；graph_only 实测 0.0000 为环境故障非真实表现） | 待环境 |
| 3 | golden 新题 2 处标注可优化（缓存一致性、RocketMQ 选型）——文档覆盖或标注调整 | 可选优化 |
| 4 | L2 触发阈值：两次采样均 t=0.5 零触发；0.75+ 无净收益（FP 抵消 TP）→ 经验值 0.5 保持零回归 | 已结论 |
| 5 | LLM confidence 分布全样本 ≥0.70（含漏判样本）——后续校准可把扫描区间上移 0.6-0.95，需更大/更难样本集 | 可选增强 |
| 6 | 硬闸门推荐 0.55 的分数源是标注集注入文档实测余弦；生产真实检索分数分布可能不同，上线前抽样复核 | 建议复核 |
