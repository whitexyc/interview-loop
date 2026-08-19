# 功能规格说明书 — Module-053: 检索融合升级（RRF 三通道消融验证）

> Planner | 2026-08-12 | 依据 task-brief（代码已读，事实已确认）

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-053 |
| 模块名称 | RRF 三通道融合验证：基线复测 → RRF 原型 → 加权对照 → 放行决策 |
| 版本号 | 0.53.0-module-053 |
| 优先级 | P0（检索质量增强；用户明确要求"实现三通道融合后的 RRF 倒排"） |
| 预估代码量 | RRF 融合模式 + 评估脚本适配 + 测试，≤ 400 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-0 DB 修复 | documents 表补 `last_mentioned_at`/`mention_count` 两列（module-046 迁移缺失）+ feedback 表建表（module-048 init_db 自愈未跑过）——解锁图谱通道，让基线复测与 RRF 都跑得动 | 用户指示"DB 问题尝试解决" |
| WP-A 基线复测 | 用当前代码跑 golden 检索评估，确认 0.9714 基线可复现（拿本次 commit 锚点）；**同时钉死口径**：验证 golden 评估的 hybrid 模式是否含图谱通道（评估脚本直调 retriever，图谱在 engine 层——历史 0.9714 可能是纯两通道数字，新旧对比必须先声明） | task-brief |
| WP-B RRF 三通道原型 | RRF 融合（`score(d) = Σ 1/(60 + rank_i(d))`，k=60 业界默认）；新开关 `retrieval_fusion_mode: hybrid(默认) | rrf`——默认 hybrid 零回归；三路排名：FTS/向量/图谱（图谱仅 round 0 有，RRF 融合只在 round 0 生效，注释写明）；跑 golden `--compare` | task-brief |
| WP-C 加权三通道对照 | 三路 min-max 归一化 → 权重消融（≥2 组：如 0.3/0.6/0.1、0.25/0.5/0.25）→ 跑 golden 对比 RRF | task-brief（可选但推荐） |
| 放行决策 | RRF 或加权 ≥ 基线（0.9714 同口径）→ 选增益最大上线（保留 hybrid 回退开关）；否则维持现状记录否决理由 | task-brief |

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-0 | `ai_service/src/database.py`（迁移 DDL 模式）或独立迁移脚本（`scripts/` 下新建，对齐既有 create_*_table 模式） | 修改/新建 |
| WP-B | `ai_service/rag/retrieval/retriever.py`（RRF 融合分支 + `retrieval_fusion_mode` 开关）+ `ai_service/src/config.py`（fusion 模式配置） | 修改 |
| WP-A/B/C | `ai_service/eval/golden_retrieval.py`（如需支持 fusion mode 参数/图谱口径标注；只读适配） | 修改 |
| 测试 | `ai_service/tests/test_rrf_fusion.py`（RRF 公式/排名融合/开关零回归/abs_cosine 保留） | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + `docs/简历/08-项目经历-逐词深挖.md` 2.4 节 + ADR（如需） | 修改 |

### 3.2 关键实现约束

- **WP-0 DB 修复**：ALTER TABLE 幂等（IF NOT EXISTS 检查列存在与否）；feedback 表对齐 module-048 的 FEEDBACK_DDL 模式；修完验证 `graph_store.search_related` 不再报 `last_mentioned_at does not exist`（module-047 实测报错点）
- **WP-B RRF 接入点**：retriever 层做（`_dispatch_mode` 已有 graph_only 分支，加 rrf 模式在 hybrid 内部实现三路并行 + RRF 融合）；**round 0 语义**：RRF 融合只在 round 0 生效，round 1/2 保持单路混合（注释写明，面试口径站得住）
- **WP-B 开关**：`retrieval_fusion_mode` 默认 `hybrid`（现状零回归）；rrf 模式可切换；config.py PW_ 前缀
- **WP-B 排名来源**：FTS 结果排名 / 向量结果排名 / 图谱结果排名——三路各自 top-k 排名序号（1-based），RRF score = Σ 1/(60 + rank)；融合后按 RRF score 降序取 top-k
- **红线**：① 不破坏 abs_cosine 存档（L3 反证依赖，归一化前存档保留）② 不改 reranker.py（RRF 粗排 vs CE 细排两阶段共存）③ 不改存量测试掩盖 ④ 评估同 golden 集同脚本同 eval_runs 表，新数字注明 fusion 模式
- **WP-A 口径钉死**：评估脚本 hybrid 模式是否含图谱——查 `_eval_question` 直调 `hybrid_retriever.retrieve(mode="hybrid")`（引擎层图谱并行不在评估路径）→ 历史 0.9714 大概率纯两通道；**基线对比表要注明"两通道+图谱追加（engine 口径）vs 评估口径"差异**，WP-B 跑的数字与基线同口径才可比
- **降级**：RRF 三路任一失败（图谱降级空/向量超时）→ 该路排名缺失不参与融合（只融合可用路），不整链路崩；rrf 模式失败回退 hybrid

### 3.3 降级

| 场景 | 处理 |
|------|------|
| DB 修复后图谱仍不可用 | WP-A 基线用两通道口径跑（注明），图谱 RRF 数据如实标"图谱待环境" |
| RRF 单路失败 | 该路不参与融合（缺路 RRF 退化为两通道/单通道），不崩 |
| 开关 rrf 模式下异常 | 回退 hybrid（保守，与 query_rewrite 同哲学） |
| 全量 pytest | 614 全绿保持（默认 hybrid 零回归 + 新增测试） |

---

## 4. 依赖

- module-050/051（golden 112 题基线 0.9714、eval_runs 基建、目录细分后的 import 路径）
- DB 修复（WP-0）为 WP-A/B 前置；网络可用性不影响本模块（模型已本地）
- `docs/简历/08-项目经历-逐词深挖.md` 2.4 节（融合方案现状描述，放行后更新）

## 5. 已知边界

- 本模块默认 hybrid 零回归——上线与否由数据决定（≥0.9714 同口径才切）
- RRF k=60 先取业界默认，若提升明显可后续扫 k 值（本次不做 k 扫描，记录为后续）
- 评估口径差异（engine 图谱追加 vs retriever 纯两通道）必须声明，否则新旧数字不可比
- 若 WP-C 加权结果优于 RRF，上线加权——决策以数据为准
