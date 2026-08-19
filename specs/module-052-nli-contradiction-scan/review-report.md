# Review Report — Module-052: NLI 矛盾扫描前置决策（mDeBERTa 中文实测 → 选型决策）

> Reviewer | 2026-08-12 | 第一轮审查
> **verdict: ✅ pass（0 阻塞）** — 全部核心数字独立复现一致，决策与 ADR 写回符合决策树，诚实边界完整。

---

## 1. 独立复现（全部与 changelog 逐一吻合，无伪造）

### 1.1 全量 100 对实测（`python -m eval.compare_nli_models` 独立重跑）

| 项 | changelog 声称 | Reviewer 复现 | 一致 |
|----|--------------|--------------|------|
| mDeBERTa kappa(三分类) | 0.4711 | 0.4711 | ✅ |
| mDeBERTa kappa(二值) | 0.7600 | 0.7600 | ✅ |
| mDeBERTa Acc(3类/2类) | 0.6800 / 0.8800 | 0.6800 / 0.8800 | ✅ |
| HHEM kappa(三分类) | 0.1351 | 0.1351 | ✅ |
| HHEM kappa(二值) | 0.4400 | 0.4400 | ✅ |
| HHEM Acc(3类/2类) | 0.3600 / 0.7200 | 0.3600 / 0.7200 | ✅ |
| mDeBERTa 混淆矩阵 | 46/3/1 + 8/22/20 | 46/3/1 + 8/22/20 | ✅ |
| HHEM 混淆矩阵 | 23/15/12 + 1/13/36 | 23/15/12 + 1/13/36 | ✅ |
| 两模型不一致条数 | 54 | 54 | ✅ |
| HHEM vs 人工不一致 | 64 | 64 | ✅ |
| HHEM 分数中位 | 0.359 | 0.3587 | ✅ |
| 数据分布 | E50/N50/C0 | E50/N50/C0 | ✅ |

抽查样本 [0]（G1 文档 + G1 问题：人工=entailment、mDeBERTa=entailment、HHEM=contradiction）与 changelog §2.5 描述一致。

### 1.2 WP-0 加载验证（`--smoke` 独立重跑）

| 参考对 | changelog 声称 | Reviewer 复现 | 一致 |
|--------|--------------|--------------|------|
| G1 → "G1 把堆划分为 Region" | entailment 0.9929 | entailment 0.9929 | ✅ |
| Kafka → "G1 是 JDK9 后默认 GC" | neutral 0.8932 | neutral 0.8932 | ✅ |
| "G1 广泛使用" → "G1 已被移除" | contradiction 0.9992 | contradiction 0.9992 | ✅ |

- 加载成功：标准 DebertaV2ForSequenceClassification（config.json 无自定义代码），离线加载（HF_HUB_OFFLINE=1）无 embed_tokens 类兼容坑 ✅
- id2label 非标准序（0=entailment/1=neutral/2=contradiction）已核对 config.json，脚本从 config 动态读取不硬编码 ✅
- 模型文件完整：model.safetensors 557,652,046 B + tokenizer 全家桶 + spm.model 全部就位 ✅

### 1.3 HHEM 阈值敏感性网格扫描（独立脚本复算，诚实校验的关键点）

changelog/ADR 声称"HHEM 最优 kappa(三分类)=0.2903 仍远低于 mDeBERTa 0.4711 → 差距是内在的，非阈值 artifact"。
Reviewer 用 step=0.01 的 (high, low) 网格（high∈[0.35,0.95)、low∈[0.05,high)）独立复算：

- 最优 kappa(三分类) = **0.2903**（我取到 high=0.39/low=0.05；开发者记 high=0.50/low=0.05——同一最优值平台区，0.2903 完全一致）✅
- 生产阈值 0.7/0.3 下 kappa = **0.1351**，与 changelog 完全一致 ✅
- 分数分布 p25=0.0578 / min=0.0053 / max=0.9122，印证"中文分数压缩" ✅
- 结论成立：HHEM 两口径最优仍显著低于 mDeBERTa，差距是模型能力内在差异 ✅

### 1.4 测试

- `tests/test_compare_nli.py` 独立运行 **15/15 passed**（全 mock，不加载真实模型）✅
- 全量回归（共享 worktree，module-053 并行改造在途）当前态 **645 passed / 0 failed**（117.5s）✅
  - 说明：changelog 记录的"628/1"是其在途时刻快照——唯一失败 `test_retrieve_under_50`（断言 retrieve ≤50 行）系 module-053 融合改造使 retrieve 一度扩至 66 行；现 module-053 已将其收敛回 47 行，该失败随之消失，当前全绿。归因与 grep 无 import 交集的说法一致，无 module-052 回归。

## 2. 审查要点逐项核对

| 审查维度 | 结论 |
|---------|------|
| 方法学：100 对构造同源同构（复用 build_pairs，SUFFICIENCY_DATASET 主源） | ✅ 代码核对：`from eval.compare_factcheck_models import build_pairs` 直接复用，doc=两篇文档句切拼接、claim=问题，与 module-050 完全同构 |
| 标注规范：三分类 + HHEM 映射（一套两用） | ✅ 标注指南在模块 docstring（entailment=充分/neutral=异主题/contradiction=矛盾构造成分，本源 0 条）；映射 entailment→supported/contradiction→unsupported/neutral→inferred；HHEM 三态按生产阈值 0.7/0.3（module-051 factcheck_judge 同口径） |
| 三分类 vs 二分类 kappa 两口径 | ✅ sklearn cohen_kappa_score 三分类直算 + entailment-vs-other 二值化，主对比=kappa，Acc 注明基线 33%/50% 口径声明 |
| 与 HHEM 同批数据对比 | ✅ 同一批 100 对、同一人工标注，脚本内顺序加载（mDeBERTa 用完释放再加载 HHEM） |
| 诚实性：口径声明、无伪造、模型缺失报错、真实数据未采纳 | ✅ 代理度量（claim=问题代答句）、无矛盾构造成分（C0 明确标注，三分类 kappa 实质退化为 E/N 判别——对 P1-③ 仅部分回答，复测计划列入）、XNLI 0.803 基准口径、512 截断、100 对方向性验证、messages 表明确不采纳 + DB golden 留复测——6 条声明齐全；`_require_model` 缺失报错含路径（3 测试覆盖）；脚本末尾打印全部诚实边界声明 |
| 加载正确性：参考对核对 + 离线加载 | ✅ 3 对已知中文用例语义核对全对（防 embed_tokens 类坑），HF_HUB_OFFLINE=1 离线加载 |
| WP-B 决策树执行 | ✅ mDeBERTa kappa 两口径 ≥ HHEM → 替换方向推荐（放行条件=复测通过）；非无条件替换——0 条矛盾样本无法验证矛盾判别是如实边界；替换方案含三态映射定义 + kappa 复测计划（≥20 条矛盾构造样本/真实答案句子/DB golden 真实检索/门槛 ≥0.7）+ 阈值校准计划（低置信→inferred 阈值扫描/512 截断验证/交叉打分预算）；未达门槛降级双轨有明确回退；否决理由无（无需否决，数据支持替换方向） |
| 测试：mock、覆盖 AC 场景、不改存量测试 | ✅ 15 项全 mock；覆盖数据构造/映射/指标两口径/模型缺失/降级；git 核对存量测试零改动 |
| 结果解读：不过度外推 | ✅ "方向性验证非最终结论，放行以复测为准"——ADR 与 changelog 均明确 |
| 记忆更新（硬性约束） | ✅ project-context.md module-052 行（含测试数字）+ 头部日期 2026-08-12 + ADR 索引行更新；agent-activity-log.md Developer 行已追加；file-index.md 两新文件行已追加；changelog 注明开工前已读 project-context.md |

## 3. 验收标准（acceptance-criteria.md）逐条核对

| 节 | 项 | 状态 |
|----|----|------|
| §1 WP-0 | 模型下载完整可加载（models/mdeberta-nli/） | ✅ |
| §1 | transformers 5.x 离线加载 + 参考对分数核对 | ✅ 复现一致 |
| §1 | 资源实测有数字（峰值内存 + 25 对耗时 + 全机模型账余量） | ✅ 有数字（实测值受并行负载影响，见 minor#3） |
| §2 WP-A | 100 对同口径构造 | ✅ |
| §2 | 三分类标注完成（含标注指南） | ✅（docstring 指南） |
| §2 | kappa 三分类+二值两口径 vs HHEM 同数据 | ✅ 数字复现一致 |
| §2 | 主对比=kappa + 口径声明 | ✅ |
| §3 WP-B | 决策树结论明确：替换（三态映射/kappa 复测/阈值校准）/双轨/放弃有回退 | ✅ |
| §3 | ADR-0010 已更新（状态行 + P1-③ 小节） | ✅ worktree 版已核对（specs/adr gitignored，主 checkout 副本由主会话合并时同步，对齐 module-050/051 先例） |
| §3 | 放行决定明确（通过才动代码） | ✅ 放行条件=复测通过，未达降级双轨 |
| §4 降级 | 模型失败报错路径 + 不伪造 | ✅ |
| §4 | 真实数据源不可用如实标注 | ✅ |
| §4 | 全量 pytest 保持 | ✅ 当前 645/0；628/1 快照归因 module-053 在途正确 |
| §5 接口 | 不改 verify_answer/检索链路 | ✅ git 核对：module-052 仅 2 新文件 + 文档，生产代码零改动 |
| §5 | golden_sufficiency.py 只读 | ✅ |
| §6 测试 | test_compare_nli.py 覆盖 + 全量绿 | ✅ 15/15 |
| §7 文档 | changelog/review-report/test-report | ✅ changelog 有；review-report 本文；test-report 移交 Tester |
| §7 | 记忆三文件 + ADR 状态 | ✅（file-index 一处数字笔误见 minor#1） |

## 4. Findings

### 阻塞（Major）：无

### 非阻塞（Minor）

1. **file-index.md module-052 行"全量 629/0"表述不准**（`memory/file-index.md`）：changelog 实际为 629 收集 → 628 passed / 1 failed（module-053 在途非本模块回归）。建议改为"628/1（module-053 在途）"或"当前 645/0"，避免后续误读为 0 失败。
2. **HHEM 阈值网格扫描无可复现脚本/参数落盘**：网格定义（步长）仅 changelog/ADR 记结果（0.2903），脚本内无实现。Reviewer 独立复算确认 0.2903 精确一致（可信），但建议按 module-047 threshold_scan.py 先例把网格扫描函数化（step/range 文档化）或至少注明步长，保证方法学可复现。
3. **资源实测值受并行负载影响，建议注明口径**：Reviewer 复跑 25 对批量 0.388s/对 / 加载 13.0s / RSS 1.08GB vs changelog 0.201s/对 / 6.2s / 1.85GB（共享 worktree 上 module-053 并行在途负载所致）。数字均合理（fp32 276M≈1.1GB），非伪造，但建议在 changelog/ADR 注明"单机实测，受并行负载影响"；另 smoke() 的"峰值 rss"为推理后采样而非真峰值仪器，可注明。
4. **"人工复核"措辞可更精确**：三分类标签为程序化从既有充分性人工标注派生（代码可见、一套两用设计本身合理且透明），docstring/changelog 用"人工复核全部 100 对"表述略宽松，建议措辞为"由人工充分性标注派生，映射规则经人工复核"。
5. **ADR"25 对交叉约 5-20s"预算与 15s 哲学**：已在 ADR 明确"需超时预算与批大小确认"为待办，非本模块缺陷，仅提示后续实施模块须落实批处理拆分。

## 5. 结论

- **verdict: pass**。核心选型数据（kappa 两口径、混淆矩阵、阈值敏感性、参考对分数）全部独立复现一致，诚实边界声明完整无伪造，ADR-0010 决策写回符合决策树且放行条件明确，生产代码零改动，测试全 mock 且当前全量全绿。
- 选型结论解读正确：mDeBERTa 方向推荐是"方向性验证"结论，矛盾判别能力（0 条样本）留待复测——此为诚实且符合 plan 的设计，非过度外推。
- 移交 Tester：test-report.md、真实 E2E 无（纯数据验证模块，无服务端 E2E 场景）、AC §7 记忆文件最终确认。
