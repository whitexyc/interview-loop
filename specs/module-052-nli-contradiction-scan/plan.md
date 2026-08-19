# 功能规格说明书 — Module-052: NLI 矛盾扫描前置决策（ADR-0010 P1-③ 数据验证）

> Planner | 2026-08-12 | 依据 task-brief v2（已吸收数据源口径/对比口径/标注复用/替换成本/环境前置）

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-052 |
| 模块名称 | NLI 矛盾扫描前置决策：mDeBERTa 中文实测 → 选型决策（替换/双轨/放弃） |
| 版本号 | 0.52.0-module-052 |
| 优先级 | P0（ADR-0010 P1-③ 矛盾扫描的上马前决策；不做可能白做/返工） |
| 预估代码量 | 实测脚本 + 标注集，≤ 300 行（模型下载为环境前置） |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-0 环境准备 | mDeBERTa-v3 多语言 NLI 下载（hf-mirror curl resolve 直链 + `-C -` 续传，勿用 huggingface.co 直连/勿依赖 hf-mirror Python 接口）+ transformers 5.x 离线加载验证（跑 2-3 对已知中文用例，分数与 HF README 参考值核对，防 embed_tokens 类兼容坑）+ 资源实测（峰值内存 + 25 对批量 CPU 耗时） | task-brief v2 |
| WP-A 中文实测 | 复刻 module-050 流程：100 对真实中文 (文档片段, claim) → mDeBERTa 三分类（entailment/contradiction/neutral）→ 人工标注 → Accuracy + Cohen's kappa，与 HHEM 中文 0.77 对比 | task-brief v2 |
| WP-B 选型决策 | 决策树：mDeBERTa kappa ≥ HHEM → 评估替换（含三态映射/kappa 复测/阈值校准）→ 写回 ADR-0010；否则双轨（HHEM 管支持度 + NLI 只做矛盾扫描）；太差则降级 LLM 或放弃（记录否决理由） | task-brief v2 |

### 数据源口径（🔴 必须声明，防"看似真实"）

- **主数据源 = SUFFICIENCY_DATASET**（module-050 同源，注入的代表性文档）——**代理度量，不是真实检索结果**；选型对比必须同口径（mDeBERTa vs HHEM 谁好才可比）
- **真实数据（messages 表 38 条测试对话）= 明确不采纳为主源**（Planner 已与用户确认：测试数据无用处不采纳）；DB 真实检索结果（golden 112 题）若环境可用作为可选辅助，不可用则如实标注

### 标注规范（一套两用，省一半成本）

- 人工一次标**三分类**（entailment / contradiction / neutral）→ HHEM 支持度从三分类**映射**得出（entailment→supported，contradiction→unsupported，neutral→inferred）——两套标签天然对齐可比

### 指标口径（防评审扯皮）

- **主对比指标 = Cohen's kappa**（天然校正随机一致：HHEM 二分类瞎猜基线 50% vs NLI 三分类基线 33%，直接比 Accuracy 不公平）
- Accuracy 仅作参考且注明口径，或把 NLI 二值化（entailment vs 其他）后算对齐 Acc 再比

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-0 | `ai_service/models/mdeberta-nli/`（下载，gitignored）+ 下载脚本（job tmp 不入仓库） | 下载 |
| WP-A | `ai_service/eval/compare_nli_models.py`（新：数据构造/加载/三分类打分/指标表）+ 可选复用 `compare_factcheck_models.py` 的加载适配模式 | 新建 |
| WP-B | `specs/adr/0010-hallucination-detection-upgrade.md`（状态更新 + 选型结论） | 修改 |
| 测试 | `ai_service/tests/test_compare_nli.py`（mock 模型：数据构造/指标/kappa/降级） | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0010 | 修改 |

### 3.2 关键实现约束

- **WP-0 下载**：照 module-050 已验证套路（curl resolve 直链 + `-C -` 断点续传）；`snapshot_download(endpoint=...)` 若 Python 侧可用也可试，但已知 hf-mirror 对 Python httpx 308 问题——失败即切 curl
- **WP-0 加载**：`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` 是 CrossEncoder 风格（sentence-transformers），transformers 5.x 用 `AutoModelForSequenceClassification` 加载（3 个 label）；**跑 2-3 对已知中文用例核对分数**（README 有参考），分数异常 = 兼容坑需解决
- **WP-A 数据**：100 对从 SUFFICIENCY_DATASET 构造（与 module-050 的 compare_factcheck_models.build_pairs 同源同构，可直接复用其构造逻辑）；标注三分类（含标注说明，Developer 需产出标注指南文件或注释）
- **WP-A 指标**：kappa 用 sklearn `cohen_kappa_score`（三分类直接算 + 二值化算）；与 HHEM 对比用同一批数据（同口径）；输出不一致样本抽查
- **WP-B 决策**：写回 ADR-0010（状态行 + 新增"P1-③ 选型结论"小节）；若替换必须列出三态映射定义（entailment→supported / contradiction→unsupported / neutral→inferred）+ kappa 复测计划 + 阈值校准计划
- **诚实边界**：代理度量声明不可省；模型为多语言训练但中文是泛化表现（XNLI 86.4% 是基准分数非本项目场景分数）；100 对标注量级小（方向性验证非最终结论）
- **不改生产代码**：本模块只做数据验证 + 决策，不动 verify_answer / 检索链路

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 模型下载失败/不完整 | 报错指出路径；如实标注"待环境"不伪造数字 |
| 模型加载失败（transformers 兼容坑） | 尝试修复（如 embed_tokens 类键展开）；修复不了如实标注 + 记录坑到 changelog |
| 标注工作量超预期 | 100 对必须完成（方向性验证需要量级）；标注指南先行 |
| 真实数据源不可用 | 如实标注"真实辅助未采纳/不可用"，主源 SUFFICIENCY 结论不受影响 |

---

## 4. 依赖

- module-050（实测流程可复刻 + HHEM 加载适配模式）、module-051（kappa 口径与评测模式）、task-brief v2
- 网络：hf-mirror 200 / github 200（已验证 2026-08-12）；huggingface.co 502 不可达
- 模型：`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`（~276M / ~1.1GB，MIT）

## 5. 已知边界

- 本模块产出**决策**（替换/双轨/放弃），不实施矛盾扫描代码——实施在决策通过后的后续模块
- 纪律项（task-brief v2 §四，违反=返工）：① 先完成 HHEM 校准再叠加 NLI（本模块不冲突，决策里注明顺序）② 重生成闭环必须等验证异步化之后 ③ 文档状态行与正文叙事统一 ④ 口径声明不可省
- 全量 pytest 614 全绿保持（本模块新增测试 +N，不加载真实模型）
