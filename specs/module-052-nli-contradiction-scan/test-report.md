# Test Report — Module-052: NLI 矛盾扫描前置决策（mDeBERTa 中文实测 → 选型决策）

> Tester | 2026-08-12
> **verdict: ✅ 验收通过（23/23 AC）** — 全量 645/0 全绿 + 新增 15/15 + 冒烟复跑与 changelog 数字一致 + 记忆三文件核查通过

---

## 1. 全量测试

| 项 | 结果 |
|----|------|
| 全量 `python -m pytest tests/ -q` | **645 passed / 0 failed**（115.08s；5 warnings 均为既有 Redis setex 弃用/SAWarning，与模块无关） |
| 口径 | 614 基线 + module-052 新增 15 + module-053 并行新增 16 = 645 |
| changelog 628/1 快照核实 | 唯一失败 `test_golden_retrieval::TestMethodLengthLimit::test_retrieve_under_50`（assert 66 <= 50）系 module-053 在途 retriever 融合改造的方法长度自检；module-053 已将 retrieve 收敛回 47 行，**当前全绿 645/0**——归因成立，无 module-052 回归 |
| module-052 自身测试 | `tests/test_compare_nli.py` **15/15 passed**（53.20s，全 mock 不加载真实模型） |

## 2. 冒烟复跑（NLI 对比脚本 --limit 5，真实模型，exit 0）

`python -m eval.compare_nli_models --limit 5`（脚本无 eval_runs 落库逻辑，无需 --no-save）：

| 项 | 结果 | 与 changelog 一致性 |
|----|------|---------------------|
| mDeBERTa 离线加载 | 成功（HF_HUB_OFFLINE，标准 DebertaV2ForSequenceClassification） | ✅ 无 embed_tokens 类兼容坑 |
| mDeBERTa 5 对 | 4.0s，0.801s/对，**5/5 entailment 全对** | ✅ 与全量 0.786s/对（长输入批量）同量级 |
| HHEM 5 对 | 2.0s，0.406s/对，分数中位 0.400 | ✅ 与全量 0.377s/对、中位 0.359 一致（中文分数压缩） |
| 不一致样本抽查 | [0][2] HHEM 判 contradiction、[3][4] 判 neutral（人工=mDeBERTa=entailment） | ✅ 与 changelog §2.3/§2.5 描述完全吻合（HHEM 对中文 entailment 误判 contradiction/neutral） |
| 诚实边界声明 | 6 条全部打印 | ✅ |
| 备注 | 单标签子集 kappa=nan 为 sklearn 单标签预期行为，非缺陷；决策对比行在 5 对子集上无统计意义，全量 100 对数字以 Reviewer 独立复现为准 | — |

## 3. 实现抽查（与 changelog 一致性）

| 抽查点 | 结论 |
|--------|------|
| 数据构造同源同构 | ✅ `from eval.compare_factcheck_models import build_pairs` 直接复用（doc=两篇文档句切拼接、claim=问题），与 module-050 完全同构 |
| 三分类标注 | ✅ `THREE_CLASS_LABELS` 从 SUFFICIENCY_DATASET 的 sufficient 标记派生（程序化 + 2026-08-12 人工复核），E50/N50/C0，与 module-050 二值标注映射一致性有测试断言（一套两用） |
| kappa 口径 | ✅ sklearn `cohen_kappa_score`：三分类直算 + entailment-vs-other 二值化两口径；Acc 注明基线（三分类 33% / 二分类 50%）仅参考 |
| id2label 处理 | ✅ 从 model.config 动态读取（0=entailment/1=neutral/2=contradiction 与 XNLI 常规序不同，不硬编码） |
| 模型缺失降级 | ✅ `_require_model` 报 FileNotFoundError 且含缺失文件与路径；3 测试覆盖 |
| 降级路径 | ✅ --skip 两侧时加载函数绝不被调用（测试断言） |
| 生产代码零改动 | ✅ git 核对：module-052 仅 2 个新文件（eval/compare_nli_models.py + tests/test_compare_nli.py）；存量修改均为 module-053 在途（golden_retrieval/engine/embeddings/retriever/config/migrate_module053/test_rrf_fusion） |
| golden_sufficiency.py 只读 | ✅ git status/diff 均无该文件 |
| 全量 100 对核心数字 | ✅ Reviewer 已独立复现与 changelog 逐一吻合（kappa3 0.4711 vs 0.1351、kappa2 0.7600 vs 0.4400、混淆矩阵 46/3/1+8/22/20 vs 23/15/12+1/13/36、不一致 54/64 条、阈值网格最优 0.2903）——Tester 冒烟行为一致性复核通过 |

## 4. 记忆文件硬核查（缺一项 = blocking）

| 文件 | 检查项 | 状态 |
|------|--------|------|
| memory/project-context.md | module-052 行存在、格式对齐（编号/名称/版本号 0.52.0/日期 2026-08-12/状态含测试数字 15/15 + 628/1 口径） | ✅ |
| memory/project-context.md | 头部"最后更新: 2026-08-12" | ✅ |
| memory/project-context.md | ADR 索引行 adr-010 状态含 module-052 结论 | ✅ |
| memory/agent-activity-log.md | Developer 活动行（2026-08-12 段） | ✅ |
| memory/agent-activity-log.md | Reviewer 活动行 | ✅ |
| memory/agent-activity-log.md | Tester 活动行（本次追加） | ✅ |
| memory/file-index.md | 新文件行 L64（compare_nli_models.py）+ L65（test_compare_nli.py）只追加 | ✅ |
| memory/file-index.md | spec 行（L106）数字修正：原"全量 629/0"不准确（快照实为 628/1、当前 645/0），已修正为"全量 645/0（2026-08-12 Tester 复跑；在途快照 628/1 系 module-053 并行改造，非本模块回归）"——对应 Reviewer minor#1 | ✅（修正完成） |

## 5. AC 逐条对照（23 项）

| 节 | 验收项 | 状态 | 依据 |
|----|--------|------|------|
| §1-1 | mDeBERTa 下载完整可加载 | ✅ 通过 | models/mdeberta-nli/ 8 文件就位（model.safetensors 557,652,046B + tokenizer 全家桶 + spm.model）；冒烟实跑加载成功 |
| §1-2 | transformers 5.x 离线加载 + 参考对核对 | ✅ 通过 | 标准架构无兼容坑；3 参考对分数 Reviewer 精确复现（0.9929/0.8932/0.9992） |
| §1-3 | 资源实测有数字（峰值内存 + 25 对耗时 + 模型账余量） | ✅ 通过 | changelog §1.3 数字齐全（0.201s/对、0.786s/对、峰值 1.95GB、磁盘账 6.21GB、RAM 余量充足）；附注：受并行负载影响（Reviewer minor#3），非阻塞 |
| §2-1 | 100 对同口径构造 | ✅ 通过 | build_pairs 复用同源同构，E50/N50/C0 |
| §2-2 | 三分类标注完成（含标注指南） | ✅ 通过 | THREE_CLASS_LABELS + docstring 标注规范；附注：程序化派生 + 人工复核措辞（Reviewer minor#4），非阻塞 |
| §2-3 | kappa 三分类+二值两口径 vs HHEM 同数据 | ✅ 通过 | 0.4711/0.7600 vs 0.1351/0.4400，Reviewer 独立复现一致 |
| §2-4 | 主对比 kappa + 口径声明 | ✅ 通过 | docstring + 输出打印：HHEM 二分类基线 50% vs NLI 三分类基线 33%，Acc 仅参考 |
| §3-1 | 决策树结论：替换（三态映射/复测/阈值校准）| ✅ 通过 | ADR P1-③：替换（推荐）+ 三态映射定义 + 复测计划（≥20 矛盾样本/真实答案/真实检索/≥0.7）+ 阈值校准计划；未达降级双轨有回退 |
| §3-2 | ADR-0010 已更新（状态行 + P1-③ 小节） | ✅ 通过 | worktree 版核对齐全（gitignored，主 checkout 副本由主会话合并时同步，对齐 module-050/051 先例） |
| §3-3 | 放行决定明确 | ✅ 通过 | 放行条件 = 复测 kappa ≥0.7 通过才动代码，不通过记录理由 |
| §4-1 | 模型失败 → 报错路径 + 不伪造 | ✅ 通过 | _require_model FileNotFoundError 含路径；3 测试；加载失败"待环境"哲学不变 |
| §4-2 | 真实数据源不可用如实标注 | ✅ 通过 | messages 表明确不采纳；DB golden 留复测，本模块环境不可用如实标注，主源结论不受影响 |
| §4-3 | 全量 pytest 614 全绿保持 | ✅ 通过 | 645/0 |
| §5-1 | 不改 verify_answer/检索链路 | ✅ 通过 | git 核对生产代码零改动（仅 2 新文件） |
| §5-2 | golden_sufficiency.py 只读 | ✅ 通过 | git 核对无 diff |
| §6-1 | test_compare_nli.py 覆盖 | ✅ 通过 | 15 项全 mock：数据构造（100 对/三分类/一套两用）/映射阈值/指标两口径/模型缺失/降级 |
| §6-2 | 全量 614+ 全绿 | ✅ 通过 | 645/0 |
| §7-1 | changelog / review-report / test-report | ✅ 通过 | changelog + review-report 已产出，test-report 本文 |
| §7-2 | project-context.md 行 + 头部日期 | ✅ 通过 | 见 §4 |
| §7-3 | activity-log Dev/Rev/Test 三行 | ✅ 通过 | 见 §4 |
| §7-4 | file-index.md 新文件行 | ✅ 通过 | 见 §4（spec 行数字已修正） |
| §7-5 | ADR-0010 状态更新 | ✅ 通过 | 见 §3-2 |
| §7-6 | 开工前已读 project-context.md | ✅ 通过 | changelog 头部注明 |

**AC 汇总：23 项全部通过（3 项附注非阻塞：资源实测口径、file-index 数字修正、标注措辞）。**

## 6. 非阻塞观察（记录不阻断）

1. 资源实测数字（0.201s/对、RSS 1.85GB）受共享 worktree 并行负载影响（Reviewer 复跑 0.388s/对/1.08GB），均已注明口径，非伪造（fp32 276M 模型 ≈1.1GB 合理）。
2. file-index spec 行"全量 629/0"数字不准确，已由 Tester 修正（见 §4）——对应 Reviewer minor#1。
3. HHEM 阈值网格扫描（最优 kappa3=0.2903）无独立脚本落盘，方法学可复现性建议后续模块按 module-047 threshold_scan 先例函数化（Reviewer minor#2）。

## 7. 结论

- **验收通过**：全量 645/0 全绿（614 基线保持 + 新增 15 全绿），冒烟复跑管线验证 + 数字与 changelog 一致，实现抽查无偏差，记忆三文件核查通过（含 Tester 行追加 + file-index 数字修正），AC 23/23 通过。
- 本模块为纯数据验证 + 决策模块，无服务端 E2E 场景（Reviewer 同结论）；核心选型数字（kappa 两口径/混淆矩阵/阈值敏感性）经 Reviewer 独立复现 + Tester 冒烟行为复核双重确认，诚实边界声明完整（代理度量/矛盾样本 0 条/100 对方向性验证）。
- **模块标记 ✅ 完成**
