# 开发计划 — Module-070: 记忆矛盾检测——评测集扩展 + 双判共识决策

## Agent 配置

- Developer x1（后端 Python，改动集中在 memory.py + config.py + eval/datasets/memory_conflict_dataset.py + 单测）
- Reviewer x1
- Tester x1

## 1. 需求描述

- 需求来源: 待办 #3「矛盾检测 Recall 提升」完整落地（task-brief 2026-08-18；用户决策：两个裁判数字都不可信 → **不选单一裁判，改双判共识**）
- 功能描述: 评测集 30 → 70 条（已写入，含 4 条用户确认的语义边界陷阱），`_judge_conflict` 扩展双裁判流程——**nli 与 clf 双确认 contradiction 才标 superseded**（Precision 极保守，冤枉 = 误标 superseded = 用户记忆消失，代价高），单判 contradiction 降级为 `conflict_hint`（新旧并存），任一裁判不可用回退单判（对称 fail-open）
- 优先级: P1

## 2. 模块拆分

### WP-A: 评测集收尾 + 双裁判真实对比（数据说话）

**描述**: 70 条评测集收尾（1 条措辞去重修复零重叠断言）+ eval 脚本支持 dual 评测 + nli/clf/dual 三方案真实跑分对比，产出数据驱动的裁判决策建议（不预设结论）。

**预估代码量**: 功能代码 ~20 行（`dual_judge` ~16 行 + CLI 1 行 + scores 字段 1 行 + 数据集 1 条措辞改动）

**涉及文件**:
- `ai_service/eval/datasets/memory_conflict_dataset.py` — 新增 `dual_judge` + `--judge` 扩展 `dual` + `scores["judge"]` 落库字段 + 1 条样本措辞去重
- `ai_service/tests/memory/test_memory_evolution2.py` — 零重叠断言（826-838 行）恢复通过的验证（**不改断言**）

**依赖**: 无（WP-A 与 WP-B 独立；WP-B 先行不阻塞本 WP）

**实现要点**:

1. **评测集措辞去重（前置，必做）**：
   - 已实测发现：新增中性样本 `{"scenario": "中性", "premise": "用户是物联网工程专业", "hypothesis": "用户喜欢摄影", "verdict": "neutral"}` 的 hypothesis **"用户喜欢摄影" 与训练集（memory_conflict_train_dataset.json，142 条）premise 字符串精确重叠**（`eval_texts & train_texts = {"用户喜欢摄影"}`，python 实测）
   - 后果：`test_train_dataset_balance_and_no_overlap`（test_memory_evolution2.py:826-838）**必然 FAIL**（零重叠不变式破坏 + clf 评测泄漏）
   - 修复：该条 hypothesis 措辞微调为 **"用户平时喜欢摄影"**——verdict=neutral 不变、语义不变、**非 4 条边界陷阱样本**（不触用户确认红线）；改后 `eval_texts & train_texts` 为空（Developer 用 python 一行验证）
   - 变更记录写入 changelog（数据修订节）
2. **eval 脚本扩展**：
   - `dual_judge(premise, hypothesis) -> str`：调 `memory_conflict_clf.load()`（False → clf_v=None）→ `clf.predict` → `nli_judge.predict`（各自 try/except → None）→ `from rag.memory.memory import dual_verdict` 复用生产共识纯函数（**单一来源防漂移**）→ 返回 `dual_verdict(nli_v, clf_v)`
   - **坑：`run_eval`（353-354 行）对 `pred not in VERDICTS` 抛 ValueError**——"conflict_hint" 不在 VERDICTS 会被 skip 按 neutral 计数。修复：`dual_judge` 内把 `"conflict_hint"` 映射为 `"neutral"`（对 contradiction P/R 主指标等价——hint 不贡献 tp/fp、fn 语义与 neutral 相同；仅 accuracy_3class 参考口径轻微失真，changelog 如实声明）
   - `--judge` choices `["nli", "clf"]` → `["nli", "clf", "dual"]`
   - `record_eval_run` 前 `scores["judge"] = args.judge`（**三方案落库区分必需**——否则 eval_runs 三行无法区分，对齐 module-062 memory_type eval `model` 字段先例）
3. **真实跑分（70 条口径）**：
   - `python -m eval.datasets.memory_conflict_dataset --judge nli`（真实 mDeBERTa）
   - `python -m eval.datasets.memory_conflict_dataset --judge clf`（模型已在盘 `models/memory_conflict_clf.joblib`，已实测存在；缺失先跑 `scripts/train_memory_conflict_clf.py`）
   - `python -m eval.datasets.memory_conflict_dataset --judge dual`
   - 预期：nli Precision 1.0 大概率跌（边界陷阱 4 条 + 真实分布样本暴露 module-052/057 中文矛盾短板）；clf 泛化水平未知；dual Precision 大概率 ≥ 两单判、Recall ≤ min(两单判)——**不预设结论，数据说话**
   - 产出：对比表（nli/clf/dual 的 P/R/F1/tp/fp/fn + 数据集 70 + skipped）+ eval_runs 三次落库（judge 字段区分）+ 对比表写入 changelog
4. **校验通过确认**（全部存量断言仍绿）：
   - `test_train_dataset_balance_and_no_overlap`（措辞去重后恢复）
   - `TestConflictDataset::test_dataset_structure_valid`（len≥20 / contradiction≥15 / 五类场景子集断言——70 条下仍满足：contradiction 40 / entailment 15 / neutral 15，scenarios 含"边界"不影响 `{"改口","迁移","过时","升级冲突","正例","中性"} <= scenarios`）
   - `load_memory_conflict_dataset()` 结构校验（≥20 / ≥15 contradiction / 有 entailment+neutral）

### WP-B: 双判共识 + 降级（行为层修复，不依赖 WP-A 数据）

**描述**: `_judge_conflict` 改造为双裁判流程（`dual_verdict` 纯函数 + dual 分支），`memory_conflict_judge` 扩展 `"dual"`；任一裁判不可用对称回退单判，双判都不可用 → None（旧行为追加）。

**预估代码量**: 功能代码 ~40 行（`dual_verdict` ~12 行 + `_judge_conflict` dual 分支 ~25 行 + `_merge_duplicate` conflict_hint 日志 2 行 + config 1 行）

**涉及文件**:
- `ai_service/rag/memory/memory.py` — `dual_verdict` 模块级纯函数 + `_judge_conflict`（540-577 行）dual 分支 + `_merge_duplicate`（513-524 行）conflict_hint 日志
- `ai_service/src/config.py` — `memory_conflict_judge`（207 行）Literal 扩展
- `ai_service/tests/memory/test_memory_evolution2.py` — `TestJudgeConflictDispatch` 新增 dual 单测（~8 项，存量 5 项零改动）
- `ai_service/tests/conftest.py` — **零改动**（autouse 已钉 `memory_conflict_enabled=False` + `memory_conflict_judge="nli"`，保持 hermetic）

**依赖**: 无（与 WP-A 完全独立；顺序建议 WP-B → WP-A → 默认值决策）

**实现要点**:

1. **`dual_verdict(nli_v: str | None, clf_v: str | None) -> str | None`**（模块级纯函数，可独立单测）：
   ```python
   def dual_verdict(nli_v, clf_v):
       """双判共识（module-070）：双方都出 verdict 时双 contradiction → "contradiction"；
       单 contradiction → "conflict_hint"（新旧并存，不标 superseded）；双方非矛盾 →
       nli 标签（entailment/neutral）。一方 None（不可用）→ 另一方单判结果
       （clf 缺失→nli 单判=现状零回归；nli 不可用→clf 单判=新增对称回退）；
       双方 None → None（上层追加，旧行为）。"""
       if nli_v is None:
           return clf_v
       if clf_v is None:
           return nli_v
       if nli_v == "contradiction" and clf_v == "contradiction":
           return "contradiction"
       if nli_v == "contradiction" or clf_v == "contradiction":
           return "conflict_hint"
       return nli_v
   ```
2. **`_judge_conflict` dual 分支**（置于现有 `if settings.memory_conflict_judge == "clf"` 之前，`elif` 链）：
   - clf 先行（本地嵌入+LR 便宜 + load 失败可早短路）→ `memory_conflict_clf.load()`（False → clf_v=None + warning"CLF 矛盾模型缺失，走 NLI 单判"）→ `clf.predict`（try/except → None）
   - nli 次行（20s 超时内建）→ `nli_judge.predict`（try/except → None）
   - `return dual_verdict(nli_v, clf_v)`
   - 函数内 import + 延迟加载哲学不变；**"clf"/"nli" 存量分支逐字不动**（存量 5 项断言锁定）
3. **双判共识决策表（本模块唯一行为真源，消除 task-brief 歧义）**：
   | nli 判定 | clf 判定 | 结果 | 上层行为 |
   |----------|----------|------|----------|
   | contradiction | contradiction | "contradiction" | 旧父块 superseded=true + updated_at=now，返回 None → save 正常新增 |
   | contradiction | entailment/neutral | "conflict_hint" | 新旧并存（追加拼接，旧行为）+ info 日志 |
   | entailment/neutral | contradiction | "conflict_hint" | 新旧并存（追加拼接，旧行为）+ info 日志 |
   | entailment/neutral | non_conflict | nli 标签 | 追加拼接（旧行为） |
   | 不可用（None/超时/异常） | contradiction | "contradiction"（clf 单判） | 标 superseded（**新增对称回退**） |
   | contradiction | 不可用（None/异常） | "contradiction"（nli 单判） | 标 superseded（= 现状 judge="nli" 行为，零回归） |
   | 不可用（None/超时/异常） | 不可用（None/异常） | None | 追加拼接（旧行为零回归） |
   - 注：clf 模型缺失（load False）时 clf_v=None → 命中第 6 行 = nli 单判 = 现状行为（**clf 缺失环境零回归**）
4. **`_merge_duplicate`**（513-524 行）：判定逻辑**零改动**（仅 `verdict == "contradiction"` 触发 superseded；"conflict_hint" 自然落入追加分支）；追加分支前加一行：
   ```python
   elif verdict == "conflict_hint":
       logger.info("记忆冲突提示（双判不一致）: 新旧并存，不标 SUPERSEDED (id=%d)", parent.id)
   ```
5. **config.py**（207 行）：
   ```python
   # module-070：双判共识——nli+clf 双确认 contradiction 才标 superseded（Precision
   # 极保守），单判 contradiction → conflict_hint 新旧并存；任一裁判不可用对称回退
   # 单判（clf 缺失→nli 单判=现状零回归）。默认值决策由 WP-A 数据定（brief 倾向
   # dual；改默认需 changelog 记录对比表+理由）。
   memory_conflict_judge: Literal["clf", "nli", "dual"] = "nli"  # 默认值先保持 nli
   ```
   - **默认值先保持 "nli"**（存量零回归红线），WP-A 对比表产出后由 Developer 按数据决策改默认（决策 + 理由入 changelog）；若改 dual，clf 缺失环境自动回退 nli 单判 = 现状行为（fail-open 无回归）
6. **新增单测（test_memory_evolution2.py `TestJudgeConflictDispatch` 扩展，~8 项，全部 mock 零真实模型）**：
   - dual 双 contradiction → "contradiction"（两裁判都断言被调用）
   - dual 单 contradiction（nli 矛盾 + clf non_conflict）→ "conflict_hint"
   - dual 单 contradiction（clf 矛盾 + nli neutral）→ "conflict_hint"
   - dual 双方非矛盾 → nli 标签（entailment）
   - dual clf load False → nli 单判（clf.predict 断言未调用）
   - dual clf predict 异常 → nli 单判
   - dual nli predict None → clf 单判（对称回退）
   - dual 双方 None → None
   - dual_verdict 纯函数边界（None 组合全覆盖）
   - 存量 5 项（nli/clf 显式 setattr）**逐字不改**；新用例沿用显式 setattr `"dual"` + finally 还原 `"nli"` 既有模式
   - `_merge_duplicate` 层 1 项：dual_judge 返回 "conflict_hint" → 追加拼接（content 拼接、superseded 仍 False、status="updated"）+ 日志分支

### WP-C: 回归 + 文档收口

**描述**: 全量 1142 基线 + 新增单测全绿（存量测试零改动红线）+ changelog（含 WP-A 对比表结论）/ CONTEXT.md / METRICS.md / ADR-0007 / 三记忆文件。

**预估代码量**: 测试 ~180 行（含注释）+ 文档

**涉及文件**:
- `specs/module-070-memory-conflict-decision/changelog.md`（Developer 产出）
- `CONTEXT.md`（**只增不删，先备份**——记忆纠错/矛盾检测领域节追加 module-070 段）
- `METRICS.md` — 待办区第 3 条（L236「矛盾检测 Recall 提升（当前 0.5…）」）标记完成（如达标）或如实更新（双判口径）
- `specs/adr/0007-memory-evolution.md` — 状态行 P1 补「module-070 双判共识（AND 才 superseded + conflict_hint 并存 + 对称回退）」
- `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`
- `ai_service/tests/memory/test_memory_evolution2.py`（WP-B 新增）

**依赖**: WP-A + WP-B

**实现要点**:
1. 全量 `pytest tests/ -q` 基线 **1142/0**（已实测收集 = 1142）+ 新增全绿；存量测试零改动（conftest 零改动、存量断言零改动）
2. changelog 必须包含：WP-A 对比表（nli/clf/dual 三方案 P/R/F1/tp/fp/fn + 70 条口径 + eval_runs id 标注）+ **最终选择 + 理由**（默认值决策记录）+ 数据集措辞去重记录 + conflict_hint 口径声明（accuracy 参考失真）+ 诚实边界（真实跑分单次快照 / dual Recall ≤ min 单判的数学性质声明）
3. CONTEXT.md 备份先行（复制留档），只追加不删除
4. 无新 ADR（双判共识是既有裁判体系参数演化，非新架构/新依赖）

## 3. 技术方案

- 涉及数据表: 无（不新增表，不改 schema）
- API 端点: 无（写路径内部改造，chat/chat_stream/agent 端点零改动）
- 外部依赖: 无新增（复用 module-061 nli_judge + module-062 memory_conflict_clf）
- 环境变量: `PW_MEMORY_CONFLICT_JUDGE`（扩展 `dual`；默认值决策后生效）
- 模型前置: `models/memory_conflict_clf.joblib`（已在盘，实测存在）+ `models/mdeberta-nli/`（已在盘）；缺失时 clf 跑分需先跑 `scripts/train_memory_conflict_clf.py`，生产 dual 自动回退 nli 单判

## 4. 验收标准

见同目录下的 `acceptance-criteria.md`

## 5. 风险评估

- **clf 模型缺失环境**: dual 模式 load False → clf_v=None → nli 单判 = 现状 judge="nli" 行为（fail-open 零回归）；changelog 声明
- **默认值决策依赖真实跑分**: WP-A 不预设结论；若 dual 的 Recall 远低于 nli（数学上 ≤ min 单判），决策权衡写入对比表 + 理由（用户原则：Precision 极保守优先，冤枉代价高；brief 倾向 dual）
- **conflict_hint 口径**: 映射 neutral 仅影响 accuracy_3class 参考值（contradiction P/R 主指标等价），changelog 如实声明
- **评测集-训练集重叠**: 1 条已实测确认（"用户喜欢摄影"）→ 措辞去重修复（verdict 不变，不触边界陷阱红线）；修复后零重叠断言恢复
- **存量测试兼容**: dual 分支不触碰 "clf"/"nli" 分支逐字语义（存量 5 项断言锁定）；conftest autouse 零改动；默认值保持 nli 直到数据决策
- **dual 延迟**: 最坏 = nli 20s 超时 + clf ~1s（本地嵌入）≈ 与现状 nli 单判同量级；clf 先行避免在 clf 不可用时白等 nli 前序路径
- **4 条边界陷阱不可改**: plan + AC 双声明（用户 2026-08-18 确认 verdict=neutral），单测断言结构校验不触碰其 verdict

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-18 | 初始版本 | Planner |
