# Changelog — Module-052: NLI 矛盾扫描前置决策（mDeBERTa 中文实测 → 选型决策）

> Developer | 2026-08-12
> 全量基线 614 passed → 新增 15 tests → **module-052 自身 15/15 全绿**
> 全量口径（共享 worktree，module-053 并行改造在途）：**628 passed / 1 failed**——唯一失败
> `tests/test_golden_retrieval.py::TestMethodLengthLimit::test_retrieve_under_50`
> （assert 66 <= 50）系 module-053 在途改动（retriever.retrieve 因融合模式扩至 66 行）触发其
> 自有方法长度测试，**与 module-052 新增文件无交集**（grep 证实无 import 关系）；614 基线全绿
> 由主会话在 module-053 收尾后复跑确认
> 开工前已读 memory/project-context.md（模块清单 module-001~051，迭代状态了解）

---

## 1. WP-0 环境准备

### 1.1 模型下载（curl resolve 直链 + 断点续传）

| 项 | 值 |
|----|----|
| 仓库 | MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 |
| 文件 | model.safetensors（557,652,046 B，fp16）+ config.json + tokenizer.json + tokenizer_config.json + special_tokens_map.json + added_tokens.json + spm.model + README.md |
| 落盘 | `ai_service/models/mdeberta-nli/`（gitignored） |
| 方式 | curl -L -C - resolve 直链（hf-mirror 302 → aws cdn，`-C -` 断点续传），一次性完成无中断 |

### 1.2 加载验证（transformers 5.14.1 离线加载，无 embed_tokens 类兼容坑）

- 标准 DebertaV2ForSequenceClassification（config.json 无自定义代码依赖），
  `AutoTokenizer + AutoModelForSequenceClassification.from_pretrained(local_dir, dtype=torch.float32)`
  直接离线加载成功（HF_HUB_OFFLINE=1）。**无 module-050 HHEM 那类 4.x 检查点键展开坑**。
- **注意**：本模型 id2label = `0=entailment / 1=neutral / 2=contradiction`（与 XNLI 常规
  contradiction/entailment/neutral 顺序不同）——脚本从 config 动态读取，不硬编码。
- 加载 6.2s，RSS 1.85GB（fp32；检查点本身 fp16，CPU 推理升 fp32 稳妥）。
- **3 对已知中文用例核对（README 无逐对参考分，用语义真值校验）**：

| 用例 | 期望 | 预测 | 置信度 |
|------|------|------|--------|
| G1 文档 → "G1 把堆划分为 Region 区域" | entailment | entailment | 0.9929 |
| Kafka 文档 → "G1 是 JDK 9 之后默认 GC" | neutral | neutral | 0.8932 |
| "G1 广泛使用" → "G1 已被移除" | contradiction | contradiction | 0.9992 |

- 基准分核对：README 官方 XNLI 表 **zh Accuracy 0.803**（⚠️ 与 Planner 探查的"86.4%"不一致——
  以 README 官方表 0.803 为准；86.4% 疑为其他模型卡分数）。基准分数仅作模型能力参考，
  非本项目场景分。

### 1.3 资源实测

| 项 | 值 |
|----|----|
| 25 对批量 CPU 耗时（短输入） | 5.03s（**0.201s/对**） |
| 100 对批量 CPU 耗时（长输入，padding 至 512） | 78.6s（**0.786s/对**） |
| 峰值内存 | **1.95GB**（fp32 推理峰值 RSS；加载后 1.85GB） |
| HHEM 同批对照 | 0.377s/对（与 module-050 的 0.364s/对一致） |
| 磁盘模型账 | models/ 合计 **6.21GB**（新增 mdeberta-nli 551.5MB）；机器 15.7GB RAM，常驻运行模型
  （bge-m3 + reranker + 裁判）理论 ~6.5GB 余量充足；脚本顺序加载（mDeBERTa 用完释放再加载 HHEM）|

> 注：单机实测受并行负载影响（module-052/053 并行改造期间同机运行，Reviewer 复跑 25 对
> 为 0.388s/对 vs 本表 0.201s/对），上述耗时数字为参考区间，量级结论（短输入显著快于长输入、
> HHEM 快于 mDeBERTa）不受影响。

---

## 2. WP-A 中文实测（100 对三分类对比）

### 2.1 数据与标注（一套两用）

- **数据源**：SUFFICIENCY_DATASET 100 条，复用 `compare_factcheck_models.build_pairs()`
  （同源同构：doc=两篇文档中文句切拼接、claim=问题）。**代理度量，非真实检索结果**。
- **三分类标签**（由人工充分性标注程序化派生——sufficient→entailment /
  不充分→neutral，映射规则经人工复核；标注指南见 `eval/compare_nli_models.py`
  模块 docstring）：
  - entailment 50 条（= 充分样本，文档回答问题）
  - neutral 50 条（= 不充分样本，文档异主题无关，如 Kafka 文档配 G1 问题）
  - **contradiction 0 条**（本数据源无矛盾构造成分——诚实边界，见 §4）
- HHEM 支持度从三分类映射：entailment→supported / neutral→inferred /
  contradiction→unsupported；HHEM 三态按生产阈值 0.7/0.3（module-051
  factcheck_judge 同口径）从连续分数映射。

### 2.2 指标表（主对比 = Cohen's kappa，同批数据同人工标注，两模型直接可比）

```
模型                  kappa(3类)    kappa(二值)    Acc(3类,基33%)    Acc(二值,基50%)     s/对
mDeBERTa                 0.4711       0.7600          0.6800          0.8800   0.786
HHEM                     0.1351       0.4400          0.3600          0.7200   0.377
```

- **主对比 kappa：三分类 0.4711 vs 0.1351；二值化 0.7600 vs 0.4400 —— mDeBERTa 两口径均显著优**。
- Accuracy 仅参考（口径声明：HHEM 二分类随机基线 50% vs NLI 三分类基线 33%，直接比不公平）。

### 2.3 混淆矩阵（行=人工，列=模型）

```
[mDeBERTa]                    entailment     neutral  contradiction
entailment(50)                       46           3             1
neutral(50)                           8          22            20

[HHEM]                          entailment     neutral  contradiction
entailment(50)                       23          15            12
neutral(50)                           1          13            36
```

- mDeBERTa entailment 判别 46/50（92%）vs HHEM 23/50（46%）——支持度判定（supported 召回）差距显著。
- HHEM **48/100 判 contradiction**：中文分数压缩（p25=0.058 / 中位 0.359）致 0.3 低阈值下
  contradiction 泛滥——生产阈值 0.7/0.3 在中文场景严重失准（与 module-051 "分数压缩" 发现互相印证）。
- mDeBERTa 对 neutral 也有 20/50 判 contradiction（部分无关文档含主题词被误判），
  但远低于 HHEM 的 36/50。

### 2.4 HHEM 阈值敏感性（诚实校验，防"阈值 artifact"质疑）

全 (high, low) 网格扫描（**step=0.01 全网格**：high∈[0.35,0.95)、low∈[0.05,high)，共 3570 组；
本模块为一次性分析实现、未保留为正式脚本——minor 修复已复现确认，见下方方法学注），
HHEM **最优 kappa(三分类)=0.2903**（最高值平台区：本模块记 high=0.50/low=0.05；Reviewer
独立复算与 minor 修复复现均取到 high=0.39/low=0.05 同值点，kappa 完全一致）仍远低于
mDeBERTa 0.4711 → **差距是内在的，非阈值 artifact**；附带发现：生产阈值 0.7/0.3 在中文
场景 kappa 仅 0.1351，校准后最多 0.2903。

> 方法学注（可复现）：网格 = step=0.01 全枚举 (high, low)，对每点 `hhem_to_three_class(
> scores, high, low)` 映射三态后算 cohen_kappa_score 与人工三分类——HHEM 100 对原始分数
> 由 `eval.compare_nli_models` 复算可得；复现结果：最优 kappa=0.2903、生产阈值 0.1351，
> 与本节数字逐位一致。

### 2.5 不一致样本抽查

- 两模型不一致 54 条；HHEM vs 人工不一致 64 条（mDeBERTa vs 人工 32 条）。
- 典型：`[0] 人工=entailment mDeBERTa=entailment HHEM=contradiction`（G1 文档 + G1 问题，
  HHEM 因中文分数压缩判 contradiction）；HHEM 对全部 12 条 entailment 误判 contradiction。

---

## 3. WP-B 选型决策（写回 ADR-0010）

**决策树结论：mDeBERTa kappa（两口径）≥ HHEM → 替换（推荐）**：

- **决策**：mDeBERTa-v3 多语言 NLI 作为逐句裁判的三态来源替代 HHEM（矛盾扫描与支持度判定
  统一走 NLI 三分类）；**放行条件 = 矛盾样本集 + 真实答案句子 + 真实检索文档的 kappa 复测通过**。
- **三态映射定义**：entailment→supported / neutral→inferred / contradiction→unsupported
  （NLI 原生三分类 argmax，无阈值）。
- **kappa 复测计划**：① 矛盾构造样本集 ≥20 条（本批 0 条无法验证矛盾判别——P1-③ 核心能力
  必须补验）② claim 用真实答案句子 ③ 文档用 DB golden 112 题真实检索片段 ④ 门槛 kappa ≥ 0.7。
- **阈值校准计划**：① 低置信预测（softmax 最大概率 <0.6 候选）→ 降级 inferred 的置信度
  阈值扫描校准（对齐 module-047 threshold_scan）② 512 token 截断在真实长文档上验证
  ③ 生产交叉打分（5 claims × 5 docs ≈ 25 对，5-20s）批处理与超时预算确认。
- **顺序纪律**：替换采纳后 HHEM 阈值校准项被取代（校准对象改 mDeBERTa）；重生成闭环仍等
  验证异步化之后。
- ADR-0010 已更新：状态行 + "P1-③ 选型结论" 小节（该文件在主 checkout 也存在，worktree 版
  编辑后主会话合并时同步）。

---

## 4. 诚实边界声明（口径声明 = 纪律 4）

1. **代理度量**：claim 用问题代答句（本题集只有问题，真实 verify_answer 用答案句子）；
   文档为注入代表性文档非真实检索结果（同 module-044/050 数据源）。
2. **无矛盾构造成分**：contradiction 0 条 → 矛盾判别能力本批无法验证，三分类 kappa 实质
   退化为 entailment/neutral 判别——**对 P1-③ 矛盾扫描选型仅部分回答**，复测计划已列入。
3. **中文泛化**：mDeBERTa 多语言训练，中文是泛化表现；XNLI zh 0.803 是基准分非本项目场景分；
   与 Planner 探查的 86.4% 不一致（以 README 官方表为准）。
4. **512 token 截断**：mDeBERTa max_position_embeddings=512，超长文档尾部信息丢失
   （本批文档平均约 250 token，影响有限）。
5. **100 对量级小**：方向性验证非最终结论，替换决策以复测为准。
6. **真实数据源（messages 表 38 条测试对话）= 明确不采纳为主源**（Planner 已与用户确认）；
   DB golden 112 题真实检索片段留作复测数据源（本模块环境不可用，如实标注）。

---

## 5. 测试（`tests/test_compare_nli.py`，15 项全部通过）

| 类 | 覆盖 |
|----|------|
| TestThreeClassLabels (3) | 100 对三分类派生（E50/N50/C0）/ 合法类集 / 与 module-050 二值标注一套两用一致性 |
| TestHHEMMapping (3) | 0.7/0.3 阈值映射边界 / 自定义阈值 / 二值化 entailment-vs-other |
| TestMetrics (4) | kappa 完美=1 / 全反<0 / 随机≈0（校正随机一致）/ 模型预测多余类不崩 |
| TestMdebertaScoreMock (1) | mock tokenizer/模型不加载真实模型（truncation=512 参数断言 + argmax 正确） |
| TestRequireModel (3) | 缺失目录/文件报错含路径 / 完整目录通过 |
| TestDegradation (1) | --skip 两侧后加载函数绝不被调用（降级路径） |

- 全部 mock，不加载真实模型；不改存量测试。
- 新增测试独立跑：`python -m pytest tests/test_compare_nli.py -q` → **15/15 passed**。
- 全量回归（共享 worktree，module-053 并行改造在途）：629 收集 → **628 passed / 1 failed**；
  唯一失败 `TestMethodLengthLimit::test_retrieve_under_50`（assert 66 <= 50）为 module-053
  在途 retriever 方法长度自检，非本模块回归（本模块仅新增 2 文件，grep 无其他测试引用）。

---

## 6. 变更文件清单

| 文件 | 操作 |
|------|------|
| `eval/compare_nli_models.py` | 新建（数据构造复用 + 三分类标注 + 加载/打分 + 指标表 + 混淆矩阵 + 不一致抽查 + --smoke） |
| `tests/test_compare_nli.py` | 新建（15 tests，全 mock） |
| `specs/adr/0010-hallucination-detection-upgrade.md` | 修改（状态行 + P1-③ 选型结论小节） |
| `models/mdeberta-nli/` | 模型下载（gitignored 环境文件） |
| memory/ 三文件 | project-context.md 模块清单行 + agent-activity-log.md 活动行 + file-index.md 新文件行 |

## 7. 已知边界 / 待办

- 矛盾判别能力未验证（0 条构造样本）→ 复测计划已写入 ADR-0010，需后续模块实施。
- mDeBERTa 生产接入（factcheck_judge 替换）未实施——本模块只做数据验证 + 决策。
- DB golden 真实检索片段复测留待环境可用时补跑（同 module-047 图谱消融"待环境"哲学）。
- HHEM 生产阈值 0.7/0.3 中文失准（最优 0.2903）——替换采纳后随替换处置，不单独校准。

---

## 8. Minor 修复记录（Reviewer 5 条，2026-08-12）

| # | 文件 | 修复内容 |
|---|------|---------|
| 1 | `memory/file-index.md` | module-052 行测试数字表述已修正（工作区已为"全量 645/0 + 在途快照 628/1 系 module-053 并行改造"），无需再改 |
| 2 | `specs/module-052-nli-contradiction-scan/changelog.md` §2.4 | HHEM 阈值网格参数落盘：step=0.01 全网格（high∈[0.35,0.95)、low∈[0.05,high)，3570 组）+ 方法学注；已复现验证最优 kappa=0.2903 与生产阈值 0.1351 逐位一致（最优平台区 high=0.39 与 0.50 同值，kappa 一致） |
| 3 | `specs/module-052-nli-contradiction-scan/changelog.md` §1.3 | 资源实测注明"单机实测受并行负载影响，数字为参考区间"（Reviewer 复跑 25 对 0.388s/对 vs 本表 0.201s/对，量级结论不受影响） |
| 4 | `eval/compare_nli_models.py`（docstring + 注释）+ changelog §2.1 | "人工复核全部 100 对"措辞改为"由人工充分性标注程序化派生，映射规则经人工复核" |
| 5 | `specs/adr/0010-hallucination-detection-upgrade.md` | 选型结论·阈值校准计划补"后续实施模块须落实批处理拆分/超时预算（15s 哲学）"（25 对全量单批可能超预算上限，须按批拆分或分级抽样） |
