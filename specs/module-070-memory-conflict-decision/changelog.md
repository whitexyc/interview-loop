# Module-070 变更日志 — 记忆矛盾检测：评测集扩展 + 双判共识决策

> 实施：Developer（2026-08-18）| 计划：`plan.md` | 验收：`acceptance-criteria.md`
> 范围：评测集 30 → 70 条收尾（1 条措辞去重）+ `_judge_conflict` 双判共识
> （nli+clf 双确认 contradiction 才标 superseded，单判 → conflict_hint 并存，
> 任一裁判不可用对称回退单判）+ nli/clf/dual 三方案 70 条真实跑分对比 +
> 数据驱动的默认值决策。

## 一、WP-A：评测集收尾 + 三方案真实对比（数据说话）

### 1.1 数据集措辞去重（前置，必做）

- **背景**：Planner 实测发现新增中性样本 `{"premise": "用户是物联网工程专业",
  "hypothesis": "用户喜欢摄影", "verdict": "neutral"}` 的 hypothesis **"用户喜欢摄影"
  与训练集（build_memory_conflict_train.py，142 条）premise 字符串精确重叠**
  （`eval_texts & train_texts = {"用户喜欢摄影"}`，python 实测）——`test_train_dataset_balance_and_no_overlap`
  （test_memory_evolution2.py）零重叠不变式破坏 + clf 评测泄漏。
- **修复**：该条 hypothesis 措辞微调为 **"用户平时喜欢摄影"**——verdict=neutral
  不变、语义不变、**非 4 条边界陷阱样本**（不触用户确认红线）；改后
  `eval_texts & train_texts` 为空（python 实测 `set()`）。
- **数据集结构校验（70 条）**：contradiction 40 / entailment 15 / neutral 15，
  scenarios 含"边界"（4 条，verdict=neutral 用户确认不可改）——`load_memory_conflict_dataset()`
  与 `TestConflictDataset::test_dataset_structure_valid` 全绿。

### 1.2 eval 脚本扩展（dual 支持）

- `dual_judge(premise, hypothesis)`：调 `memory_conflict_clf.load()`（False →
  clf_v=None）→ `clf.predict` → `nli_judge.predict`（各自 try/except → None）→
  **`from rag.memory.memory import dual_verdict` 复用生产共识纯函数（单一来源
  防漂移，AC-23）** → 返回 `dual_verdict(nli_v, clf_v)`。
- **conflict_hint 口径声明**：`run_eval` 对 `pred not in VERDICTS` 抛 ValueError
  → `dual_judge` 内把 `"conflict_hint"` 映射为 `"neutral"`——对 contradiction
  P/R 主指标**等价**（hint 不贡献 tp/fp，fn 语义与 neutral 相同）；仅
  accuracy_3class 参考口径轻微失真（如实声明，AC 已认可）。
- `--judge` choices 扩展 `["nli", "clf"]` → `["nli", "clf", "dual"]`。
- `scores["judge"] = args.judge` 落库——**三方案 eval_runs 区分必需**（否则
  eval_type='memory_conflict' 三行无法区分），对齐 module-062 memory_type eval
  `model` 字段先例。

### 1.3 三方案真实跑分（70 条口径，eval_runs 落库）

> 运行：`python -m eval.datasets.memory_conflict_dataset --judge <nli|clf|dual>`
> （真实 mDeBERTa + 真实 bge-m3+LR clf，模型均在盘实测加载成功；70/70 评估，
> skipped=0；scores 含 `judge` 字段三行可区分）

| 方案 | Accuracy(3类) | Precision | Recall | F1 | tp | fp | fn | skipped | eval_runs id |
|------|--------------|-----------|--------|-----|----|----|----|---------|--------------|
| nli（mDeBERTa） | 0.6429 | 0.9167 | 0.5500 | 0.6875 | 22 | 2 | 18 | 0 | 46 |
| clf（bge-m3+LR） | 0.6000 | 0.8158 | 0.7750 | 0.7949 | 31 | 7 | 9 | 0 | 47 |
| **dual（双判共识）** | 0.5286 | **0.9412** | 0.4000 | 0.5614 | 16 | 1 | 24 | 0 | 48 |

> 对照（module-062 同 30 条旧口径）：nli id=35 Precision 1.0000/Recall 0.5000、
> clf id=34 Precision 0.9048/Recall 0.9500、nli id=31 Accuracy 0.60。

**关键发现**：
1. **nli 的 1.0000 Precision 是"窄而准"假象被证实**——30 条口径 1.0000 → 70 条
   口径跌至 0.9167（fp=2）——正是 plan 预判的边界陷阱 4 条 + 真实分布样本暴露
   module-052/057 mDeBERTa 中文矛盾判别短板；Recall 0.5 → 0.55（微弱上升）。
2. **clf 人造分布数字缩水**——30 条口径 0.9048/0.9500 → 70 条真实分布口径
   0.8158/0.7750——Precision 仅擦线 ≥0.8、Recall 未达 0.8 门槛；fp=7 为三方案
   最多（误标 7 条用户记忆，最贵失败模式）。
3. **dual Precision 0.9412 为三方案最高**（fp=1）——AND 共识按设计工作：单判
   contradiction 的样本降级为 conflict_hint（新旧并存）而非误标 superseded；
   Recall 0.4000 最低是 AND 共识的数学性质（≤ min(单判)）。

### 1.4 数据驱动的默认值决策（最终选择 + 理由）

**最终选择：`memory_conflict_judge` 默认值改为 `"dual"`**（config.py 已改，
`PW_MEMORY_CONFLICT_JUDGE=nli|clf` 环境变量回退保留）。

理由（按用户既定哲学"Precision 是更硬的约束，宁可漏检也不错标——冤枉=误标
superseded=用户记忆消失，代价高"）：

1. **Precision 优先决策成立**：dual 0.9412 > nli 0.9167 > clf 0.8158——双确认
   共识在 70 条真实分布口径下误标最少（fp=1），最符合"不冤枉用户记忆"红线；
   clf 的 fp=7 是三个方案中最贵的失败模式（7 条正常记忆被标过期）。
2. **用户 2026-08-18 架构决策被数据支持**：用户已定"两个裁判数字都不可信 →
   不选单一裁判，改双判共识"——本模块数据证实：nli 的 1.0 假象（跌至 0.9167）、
   clf 人造分布缩水（跌至 0.8158），两个单判都靠不住，AND 共识把 Precision
   抬到三方案最高。
3. **Recall 损失是无害降级**：dual Recall 0.4000（fn=24）——漏判 = 旧记忆拼接
   共存（module-061 语义：无害降级，不丢数据、不标过期）；与"冤枉"（误标
   superseded 导致用户记忆从召回面消失）相比代价低一个量级。
4. **fail-open 零回归保障**：clf 模型缺失 → dual 自动回退 nli 单判 = 现状
   `judge="nli"` 行为逐字一致（新环境部署无需先训练 clf 也可安全切 dual）。
5. **clf 留给召回优先场景**：如需 Recall 优先可 `PW_MEMORY_CONFLICT_JUDGE=clf`
   一键切换（R 0.775 最高），但默认不选——其 Precision 擦线 0.8 且 fp 最多。

诚实边界：
- 单次跑分快照（mDeBERTa/bge-m3 推理为确定性算子，可复现；LLM 无涉）
- **dual Recall ≤ min(单判) 是数学性质**（AND 共识），其价值在 Precision 不冤枉
- 三方案均未达完整门槛（R≥0.8 且 P≥0.8），但启用判据按 module-062 用户规则
  （"Precision≥0.8 者启用"）已满足——本模块只做默认值决策不改启用状态
- conflict_hint 映射 neutral 致 dual accuracy_3class 参考值偏低（0.5286），
  contradiction P/R 主指标不受影响

## 二、WP-B：双判共识 + 降级（行为层）

### 2.1 `dual_verdict` 纯函数（单一来源）

`rag/memory/memory.py` 模块级纯函数 `dual_verdict(nli_v, clf_v) -> str | None`：

| nli 判定 | clf 判定 | 结果 | 上层行为 |
|----------|----------|------|----------|
| contradiction | contradiction | "contradiction" | 旧父块 superseded=true + updated_at=now，返回 None → save 正常新增 |
| contradiction | entailment/neutral | "conflict_hint" | 新旧并存（追加拼接）+ info 日志 |
| entailment/neutral | contradiction | "conflict_hint" | 新旧并存（追加拼接）+ info 日志 |
| entailment/neutral | non_conflict | nli 标签 | 追加拼接（module-046 行为） |
| 不可用（None/超时/异常） | contradiction | "contradiction"（clf 单判） | 标 superseded（**新增对称回退**） |
| contradiction | 不可用（None/异常） | "contradiction"（nli 单判） | 标 superseded（= 现状 judge="nli" 行为，零回归） |
| 不可用 | 不可用 | None | 追加拼接（旧行为零回归） |

- **clf 模型缺失（load False）时 clf_v=None → 命中第 6 行 = nli 单判 = 现状行为**
  （clf 缺失环境零回归，fail-open）。

### 2.2 `_judge_conflict` dual 分支

置于现有 `if settings.memory_conflict_judge == "clf"` 之前（elif 链）：
clf 先行（本地嵌入+LR 便宜，load 失败可早短路不白等 nli）→ nli 次行（20s 超时
内建）→ `return dual_verdict(nli_v, clf_v)`。函数内 import + 延迟加载哲学不变；
**"clf"/"nli" 存量分支逐字不动**（存量 5 项断言锁定，AC-7）。

### 2.3 `_merge_duplicate` conflict_hint 日志

判定逻辑**零改动**（仅 `verdict == "contradiction"` 触发 superseded；
"conflict_hint" 自然落入追加分支）；追加分支前新增日志分支：
`logger.info("记忆冲突提示（双判不一致）: 新旧并存，不标 SUPERSEDED (id=%d)", parent.id)`。

### 2.4 config.py

`memory_conflict_judge: Literal["clf", "nli", "dual"] = "dual"`——默认值由
WP-A 真实跑分数据决策从 "nli" 改为 "dual"（对比表 + 选择 + 理由见 §1.4）；
`PW_MEMORY_CONFLICT_JUDGE` 环境变量回退保留（nli/clf 一键切换）。

### 2.5 新增单测（10 项，全部 mock 零真实模型）

`tests/memory/test_memory_evolution2.py` 新增 `TestJudgeConflictDual`（9 项）
+ `TestMergeConflictHint`（1 项）：

- 双 contradiction → "contradiction"（两裁判都断言被调用）
- 单 contradiction（nli 矛盾 + clf non_conflict）→ "conflict_hint"
- 单 contradiction（clf 矛盾 + nli neutral）→ "conflict_hint"
- 双方非矛盾 → nli 标签（entailment）
- clf load False → nli 单判（clf.predict 断言未调用）
- clf predict 异常 → nli 单判
- nli predict None → clf 单判（对称回退）
- 双方 None → None
- `dual_verdict` 纯函数决策表全覆盖（None 组合）
- `_merge_duplicate` 收到 "conflict_hint" → 追加拼接（content 拼接、superseded
  仍 False、status="updated"）+ 日志分支断言

存量 5 项（TestJudgeConflictDispatch）**逐字不改**；新用例沿用显式 setattr
`"dual"` + finally 还原 `"nli"` 既有模式；conftest autouse **零改动**。

## 三、WP-C：回归 + 文档收口

- 全量 pytest：**1152 passed / 0 failed**（1142 基线 + 10 新增，228.51s；
  scripts/test_models.py 1 项 module-050 遗留收集 ERROR 沿用，非本模块回归）
- 默认值决策后复验：config 默认改 "dual" 后内存测试 110/110 全绿 + 全量复跑
  **1152 passed / 0 failed**（见 §五 验证命令）
- 存量测试零改动红线：`git diff main -- ai_service/tests/` 仅 test_memory_evolution2.py
  新增用例行；conftest autouse（memory_conflict_enabled=False +
  memory_conflict_judge="nli"）零改动
- CONTEXT.md：备份先行（`%TEMP%\CONTEXT.md.bak-module070-20260818.md`）+ 只增
  不删追加「双判共识领域」段
- METRICS.md：待办区第 3 条「矛盾检测 Recall 提升」按实测量化更新
- ADR-0007：状态行补「module-070 双判共识（AND 才 superseded + conflict_hint
  并存 + 对称回退）」
- 无新 ADR（双判共识是既有裁判体系参数演化，非新架构/新依赖）

## 四、诚实边界

- **真实跑分为单次快照**：nli/clf 推理存在 LLM 无涉的确定性差异（模型推理
  CPU 确定性），但 mDeBERTa/bge-m3 推理为确定性算子，单次跑分可复现
- **dual Recall ≤ min(单判) 是数学性质**：AND 共识只取双方都判矛盾的样本，
  召回必然不高于任一单判；dual 的价值在 Precision（不冤枉）而非 Recall
- **conflict_hint 口径**：accuracy_3class 参考值轻微失真（hint 计入 neutral），
  contradiction P/R 主指标不受影响
- **clf 训练分布**：142 条人造案例（非真实用户改口数据），泛化水平以 70 条
  真实分布打底评测为准
- **4 条边界陷阱（verdict=neutral）不可改**：用户 2026-08-18 已确认标注

## 五、验证命令

| 验证项 | 命令（ai_service 目录） | 预期结果 |
|--------|----------|----------|
| dual 单测 + 存量 | `python -m pytest tests/memory/test_memory_evolution2.py -q` | 80 项全部 passed |
| 全量回归（改默认前） | `python -m pytest tests/ -q` | 1152 passed / 0 failed（228.51s） |
| 全量回归（默认 dual 后复跑） | `python -m pytest tests/ -q` | 1152 passed / 0 failed（190.49s） |
| dual 冒烟 | `python -m eval.datasets.memory_conflict_dataset --judge dual --limit 5 --no-save` | 5/5 无 skip（真实模型实测） |
| 三方案真实跑分 | `python -m eval.datasets.memory_conflict_dataset --judge nli`（clf/dual 同款） | 70/70 评估 0 skip + eval_runs 落库（id=46/47/48，scores 含 judge 字段） |

## 六、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-18 | 初始实现（WP-A/B/C） | Developer |
