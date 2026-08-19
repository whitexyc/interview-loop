# 功能规格说明书 — Module-047: 数据实验批（真实 baseline + 阈值校准 + golden 扩样本 + 图谱消融）

> Planner | 2026-08-10

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-047 |
| 模块名称 | 数据实验批：真实评测 + 校准 + 扩样本 + 消融 |
| 版本号 | 0.47.0-module-047 |
| 优先级 | P2（数据驱动决策：阈值/基线/置信度，无代码风险，主要跑实验） |
| 预估 | 4 个工作包（3 实验 + 1 数据扩充） |

---

## 2. 需求（未解决清单批 3）

| WP | 内容 | 目的 |
|----|------|------|
| WP1 | 真实模式 baseline：intent（`golden_intent.py` 真实 LLM 分类）+ 充分性（`golden_sufficiency.py` 真实模式 reflector）——之前只有 fixture/冒烟 | 拿到真实数字（此前 Accuracy 0.9667 是 --no-save 冒烟；充分性无真实 baseline） |
| WP2 | 阈值校准：L2 触发 0.5 / 充分性硬闸门 0.4 是经验值 → 用标注集做阈值扫描（precision/recall 曲线）确定 | 把 0.4/0.5 从"经验值"变"数据定"（ADR-0005 追问 2 已注明） |
| WP3 | golden 集扩样本：`eval/golden.json` 30 题 → 100+ 题（技术问答，覆盖知识库主题） | 0.96 命中率统计置信度（简历口径 23/30 题 → 80+/100 题） |
| WP4 | 图谱消融：`golden_retrieval.py --ablate` 跑 graph_only vs hybrid | 图谱增量收益数字（ADR-0004 决策 4 留白：+X.X Hit@5） |

### 验收场景

```
场景 1：真实 baseline 落库
  假设 跑 python -m eval.golden_intent（真实 LLM）
  那么 输出 Accuracy/混淆矩阵 + eval_runs eval_type='intent' 落库（正式首条记录）

场景 2：充分性真实 baseline
  假设 跑 python -m eval.golden_sufficiency（真实模式 reflector）
  那么 输出 Accuracy + insufficient Recall + eval_runs eval_type='sufficiency' 落库

场景 3：阈值扫描
  假设 跑阈值扫描脚本（0.2-0.8 步长 0.05）
  那么 输出 P/R/F1 曲线 → 推荐阈值（数据驱动，若与经验值不同给出理由）

场景 4：golden 扩到 100 题
  假设 load golden.json
  那么 ≥100 题，检索回归仍可跑（Hit@5 对比 0.96 前后差异）

场景 5：图谱消融
  假设 跑 golden_retrieval.py --ablate graph_only / hybrid
  那么 输出两模式 Hit@5 差值（+X.X 或持平，如实记录；环境不可用则交付方法学）
```

---

## 3. 技术方案

### 3.1 工作包与涉及文件

| WP | 内容 | 文件 | 操作 |
|----|------|------|------|
| WP1 | 真实 baseline 运行 + 落库 | `eval/golden_intent.py`、`eval/golden_sufficiency.py` | 运行（不改代码，除非发现 bug 修一行） |
| WP2 | 阈值扫描脚本 | `eval/threshold_scan.py`（新）：对 L2 触发阈值与硬闸门阈值做扫描，用 golden_intent / golden_sufficiency 数据集 + 启发式/真实判断器算 P/R/F1 | 新建 |
| WP2 | 测试 | `tests/test_threshold_scan.py` | 新建 |
| WP3 | golden 扩样本 | `eval/golden.json`（30→100+ 题，技术问答）| 修改 |
| WP4 | 图谱消融运行 | `golden_retrieval.py --ablate` | 运行（环境不可用则记录方法学） |

### 3.2 关键约束

- **WP1**：真实模式调 LLM API（eval 脚本直接走 LLMFactory，不经 HTTP 中间件，无本地限流；但外部 API 可能有频控——失败重试/记录）。100 条 intent × ~1.5s ≈ 2-4 分钟，可接受。落库 git_commit 为当前 HEAD（2eac844 后）
- **WP2**：扫描对象——① L2 触发阈值（intent≠knowledge 时 confidence < t 触发确认，用 golden_intent 数据模拟 LLM 置信度已知场景，扫描 t ∈ [0.2, 0.8]）② 硬闸门阈值（top-1 abs_cosine < t 判不充分，用 golden_sufficiency 文档分数模拟，扫描 t ∈ [0.2, 0.6]）。输出 P/R/F1 曲线 + 推荐值 + 与经验值（0.5/0.4）对比
- **WP3**：扩题原则——只加知识库内真实存在的内容主题（借已有 SUFFICIENCY/INTENT 数据集的主题，不编造知识库没有的内容）；每题含 question + golden_docs（文档名/标题）+ 可空 ground_truth。格式对齐现有 golden.json
- **WP4**：`--ablate graph_only` 需要真实 DB（图谱表 + 向量）；环境可用则跑，不可用则输出方法学 + 已就绪命令（不阻塞）

### 3.3 降级

| 场景 | 处理 |
|------|------|
| LLM API 限流/超时 | 重试 1 次 + 记录 skipped，不中断 |
| DB 不可用（WP4） | 交付方法学 + 命令，标注"待环境" |
| golden 扩样本后检索回归需 DB | 若 DB 不可用，结构校验 + 冒烟，数字标注待跑 |

---

## 4. 依赖

- module-043/044（golden_intent/golden_sufficiency 评测脚本）
- module-038（golden.json 结构 + --ablate 标志）
- 全量测试 503 全绿基线保持

## 5. 已知边界

- WP1/WP4 的"真实数字"依赖外部环境（LLM API / DB），尽力跑，不可用如实记录
- golden 扩样本是数据扩充（非逻辑），不改变评测口径（Hit@k/MRR 判定规则不变）
