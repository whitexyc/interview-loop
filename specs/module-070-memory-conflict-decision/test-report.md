# Module-070 测试报告 — 记忆矛盾检测：评测集扩展 + 双判共识决策

> Tester：2026-08-18 | 验收基线：plan.md / acceptance-criteria.md / changelog.md
> Review 结论：✅ Pass（5 项 LOW/minor 非阻塞，见 review-report.md）
> **验收结论：✅ 通过（Tester 独立复验：全量 1163/0、三方案真实跑分逐字复现、DB 落库 judge 字段核验）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1163 passed / 0 failed（205.23s，43 warnings）** = 1142 基线 + Developer 新增 10 + Tester 新增 11 |
| Developer 新增单测 | `TestJudgeConflictDual` 9 项 + `TestMergeConflictHint` 1 项 = **10 项全绿**（独立运行确认） |
| Tester 新增单测 | `TestDualVerdictDecisionTable` 1 + `TestJudgeConflictDualTester` 2 + `TestEvalScriptDual` 6 + `TestConfig070` 2 = **11 项全绿**（独立运行 46.27s） |
| 存量测试改动 | **零改动**（`git diff --numstat ai_service/tests/` = 387 插入 / **0 删除**，仅 test_memory_evolution2.py 追加用例行；conftest.py diff 0 行） |
| 单测 mock 性 | 全 mock 零真实模型/DB（hermetic，对齐存量模式） |
| 收集 ERROR | 根目录 `scripts/test_models.py` 1 项 module-050 遗留沿用（跑 `pytest tests/` 不涉及，非本模块回归） |

## 二、新增单测覆盖核对（与 changelog/plan 声明逐项核对）

### 2.1 Developer 新增（10 项，全过）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| dual 双 contradiction → "contradiction"（两裁判都断言被调用） | ✅ | test_judge_dual_both_contradiction |
| dual 单判 nli 矛盾 + clf non_conflict → "conflict_hint" | ✅ | test_judge_dual_nli_contradiction_clf_non_conflict |
| dual 单判 clf 矛盾 + nli neutral → "conflict_hint"（反方向） | ✅ | test_judge_dual_clf_contradiction_nli_neutral |
| dual 双方非矛盾 → nli 标签（entailment） | ✅ | test_judge_dual_both_non_conflict_returns_nli_label |
| dual clf load False → nli 单判（clf.predict 断言未调用） | ✅ | test_judge_dual_clf_model_missing_uses_nli |
| dual clf predict 异常 → nli 单判 | ✅ | test_judge_dual_clf_predict_exception_uses_nli |
| dual nli predict None → clf 单判（对称回退） | ✅ | test_judge_dual_nli_none_uses_clf |
| dual 双方 None → None | ✅ | test_judge_dual_both_unavailable_returns_none |
| dual_verdict 纯函数决策表全覆盖（None 组合） | ✅ | test_dual_verdict_pure_function_table |
| _merge_duplicate 收 conflict_hint → 追加拼接 + superseded False + status=updated + info 日志分支断言 | ✅ | TestMergeConflictHint::test_conflict_hint_appends_and_keeps_superseded_false |

存量 `TestJudgeConflictDispatch` 5 项逐字不改（numstat 0 删除证实），全绿。

### 2.2 Tester 补充（11 项，全过）

| 覆盖点 | 结果 | 依据 |
|--------|------|------|
| dual_verdict 7 行决策表**逐行**枚举（R1 双确认 / R2-R3 单判 conflict_hint 含 clf 侧 entailment/neutral 变体 / R4 双非矛盾返 nli 标签 / R5 nli 不可用→clf 单判 / R6 clf 不可用→nli 单判 / R7 双 None→None） | ✅ | TestDualVerdictDecisionTable::test_row_by_row_decision_table |
| dual 分支 nli predict **抛异常** → clf 单判（对称回退的异常路径，Developer 未覆盖） | ✅ | TestJudgeConflictDualTester::test_judge_dual_nli_exception_uses_clf |
| dual 分支 clf predict **返回 None**（warning 分支）→ nli 单判（Developer 未覆盖） | ✅ | TestJudgeConflictDualTester::test_judge_dual_clf_predict_none_uses_nli |
| eval `dual_judge` 双 contradiction → "contradiction"（两裁判都被调用，复用生产单一来源） | ✅ | TestEvalScriptDual::test_dual_judge_both_contradiction |
| eval `dual_judge` 单判矛盾 → conflict_hint **映射 neutral**（run_eval VERDICTS 校验 + P/R 主指标等价） | ✅ | TestEvalScriptDual::test_dual_judge_single_contradiction_maps_to_neutral |
| eval `dual_judge` clf load False → nli 单判 fail-open（predict 断言未调用） | ✅ | TestEvalScriptDual::test_dual_judge_clf_load_false_uses_nli |
| eval `dual_judge` 双方不可用 → None（run_eval 按 skip/neutral 计数，AC-18 存量语义） | ✅ | TestEvalScriptDual::test_dual_judge_both_unavailable_returns_none |
| eval CLI `--judge dual` 接线 → `dual_judge` 被选中 + **`scores["judge"] == "dual"` 传入 record_eval_run 落库**（AC-13 三行区分必需） | ✅ | TestEvalScriptDual::test_main_judge_dual_scores_judge_persisted |
| eval CLI `--judge nli/clf` 存量选择不变（real_judge/clf_judge）+ 非法 judge → argparse SystemExit（AC-16 不静默） | ✅ | TestEvalScriptDual::test_main_judge_nli_clf_selection_and_invalid_rejected |
| config `memory_conflict_judge` 默认 **"dual"**（WP-A 数据决策，changelog §1.4） | ✅ | TestConfig070::test_conflict_judge_default_dual |
| config Literal 三值 `("clf","nli","dual")`（非法值 pydantic 启动拒绝，AC-16） | ✅ | TestConfig070::test_conflict_judge_literal_three_values |

## 三、真实跑分复验（Tester 独立执行，未采信 changelog 数字）

### 3.1 dual 冒烟（`--judge dual --limit 5 --no-save`，真实 mDeBERTa + bge-m3+LR）

**5/5 评估、skipped=0**（模型均在盘实测加载成功），AC-12 满足。

### 3.2 三方案 70 条全量复跑（`--no-save`，与 changelog 对比表逐字核对）

| 方案 | Accuracy(3类) | Precision | Recall | F1 | tp | fp | fn | skipped | 与 changelog id |
|------|--------------|-----------|--------|-----|----|----|----|---------|-----------------|
| nli（mDeBERTa） | 0.6429 | 0.9167 | 0.5500 | 0.6875 | 22 | 2 | 18 | 0 | **id=46 逐字一致** |
| clf（bge-m3+LR） | 0.6000 | 0.8158 | 0.7750 | 0.7949 | 31 | 7 | 9 | 0 | **id=47 逐字一致** |
| dual（双判共识） | 0.5286 | **0.9412** | 0.4000 | 0.5614 | 16 | 1 | 24 | 0 | **id=48 逐字一致** |

- 三方案数字与 changelog 对比表**逐字一致**（双模型推理确定性算子，单次快照可复现——本报告二次复跑实证）
- dual Precision 0.9412（fp=1）三方案最高、clf fp=7 最贵失败模式、nli "1.0 假象"（30 条口径 1.0000 → 70 条 0.9167）——数据驱动默认值决策（改 dual）理由链全部复验成立

### 3.3 eval_runs 落库直查（Tester 独立 SELECT）

| id | judge 字段 | acc | P | R | tp/fp/fn | size | skipped |
|----|-----------|-----|----|----|----------|------|---------|
| 48 | **dual** | 0.5286 | 0.9412 | 0.4 | 16/1/24 | 70 | 0 |
| 47 | **clf** | 0.6 | 0.8158 | 0.775 | 31/7/9 | 70 | 0 |
| 46 | **nli** | 0.6429 | 0.9167 | 0.55 | 22/2/18 | 70 | 0 |

- `scores["judge"]` 字段三行可区分（AC-13）；对照旧 30 条口径行（id=31/34/35）judge=None——新字段引入前后兼容、不混淆
- 本报告复跑均 `--no-save`，未新增 DB 行（Developer 三行 46/47/48 原样保留）

## 四、实现抽查（与 changelog 一致）

| 项 | 抽查结果 |
|----|----------|
| `dual_verdict` 纯函数（memory.py:260-288） | 7 行决策表 docstring 与实现逐字吻合；生产 `_judge_conflict`（L620）与 eval `dual_judge`（L360）均引用——单一来源 AC-23 ✓ |
| dual 分支顺序 | clf 先行（load 短路 warning）→ nli 次行（20s 超时内建 nli_judge.py:86 wait_for）→ dual_verdict；clf/nli 存量分支逐字不动 ✓ |
| `_merge_duplicate` conflict_hint | elif 仅 info 日志后落入追加分支（superseded 不标、条数不涨、status=updated）✓ |
| config | `Literal["clf","nli","dual"] = "dual"`（config.py:214）；PW_MEMORY_CONFLICT_JUDGE 回退保留 ✓ |
| AC-15 空输入 | nli_judge.py:82-83 与 memory_conflict_clf.py:190 均有 strip() 空守卫返回 None ✓ |
| AC-17 延迟上界 | clf 先行避免 clf 不可用时白等 nli；最坏 = nli 20s + clf ~1s 与现状同量级 ✓ |
| AC-18 失败样本 | run_eval 存量语义：判定异常/非法 verdict → skip 记录按 neutral 计数（L393-397）✓ |
| 4 条边界陷阱（AC-10） | 数据集 L206-213 逐条核对 verdict=neutral 保持（出省/本省、想转/没转、不买/送的、睡得早/放假晚睡）✓ |
| 措辞去重（AC-11） | "用户平时喜欢摄影"（L195-196）；`test_train_dataset_balance_and_no_overlap` 全绿（eval_texts & train_texts 为空）✓ |
| 改动范围（AC-21/24） | git status 仅 9 文件（代码 4 + 测试 1 + 文档 4），全部在 plan 清单内；requirements/schema 零 diff ✓ |
| 代码量（AC-22） | 功能代码 ≈90 行 < 200 上限 ✓ |

## 五、观察与诚实声明（非阻塞）

1. **Reviewer LOW-②（fixture 落库 judge 标签失真）确认**：`--fixture --judge dual` 落库时 judge 字段记 "dual" 而非 "fixture"——新字段引入前的 fixture 行无 judge 字段，现行为无害但标签失真，建议后续模块顺手修（fixture 分支标 "fixture" 或强制 --no-save）。
2. **Reviewer LOW-③（双判唯一 fp 样本标注存疑）确认**："用户感觉嵌入式方向更好 \| 用户觉得原专业方向有优势"（标注 entailment）两个独立裁判均判 contradiction——入标注复核 backlog；即使改标，dual 默认决策结论不变（P 0.9412→0.8889/1.0000 均 ≥0.8 且仍三方案最高档）。
3. **test_memory_evolution2.py 测试数口径**：现文件 93 项（HEAD 基线 72 + Developer 10 + Tester 11）；Reviewer minor-① 的 "70→80" 数字建议在后续模块修正为 "72→82"（现再 +11 = 93）。
4. **Reviewer LOW-④（eval dual_judge clf load False 无 warning）确认**：eval 侧静默单判回退、生产侧有 warning——可观测性差异非阻塞，建议后续补一行对齐。
5. **三方案均未达完整门槛**（R≥0.8 且 P≥0.8）：本模块只做默认值决策（module-062 用户规则 "Precision≥0.8 者启用" 满足），启用状态未改动——如实记录。
6. **dual Recall 0.4000 为 AND 共识数学性质**（≤ min 单判），fn=24 全部为无害漏判（拼接共存不丢数据），与"冤枉"（误标 superseded）代价差一个量级。

## 六、AC 逐条对照（24 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| AC-1 双确认才 superseded | ✅ | TestJudgeConflictDual 1 项 + TestDualVerdictDecisionTable R1 |
| AC-2 单判 → conflict_hint 并存 | ✅ | TestJudgeConflictDual 2/3 项 + TestMergeConflictHint（日志断言） |
| AC-3 双方非矛盾 → 原语义 | ✅ | TestJudgeConflictDual 4 项 + R4 行 |
| AC-4 clf 缺失 → nli 单判零回归 | ✅ | TestJudgeConflictDual 5 项 + TestEvalScriptDual clf_load_false |
| AC-5 nli 不可用 → clf 单判（对称回退） | ✅ | TestJudgeConflictDual 7 项 + Tester 补 nli 异常路径 |
| AC-6 双方不可用 → None | ✅ | TestJudgeConflictDual 8 项 + R7 行 + dual_judge both_unavailable |
| AC-7 存量分支逐字不变 | ✅ | TestJudgeConflictDispatch 5 项全绿 + numstat 0 删除 |
| AC-8 开关关零回归 | ✅ | conftest autouse 钉 False；_merge_duplicate L546 条件分支代码核对 |
| AC-9 数据集 70 条结构 | ✅ | TestConflictDataset::test_dataset_structure_valid（contradiction 40/entailment 15/neutral 15） |
| AC-10 4 条边界陷阱不可改 | ✅ | 数据集 L206-213 verdict=neutral 逐条核对 + 结构断言全绿 |
| AC-11 训练/评测零重叠恢复 | ✅ | TestConflictEvalBaseline::test_train_dataset_balance_and_no_overlap 全绿 |
| AC-12 dual 评测可跑 | ✅ | 真实 `--judge dual --limit 5`：5/5 无 skip |
| AC-13 三方案真实跑分落库 | ✅ | 三方案复跑逐字一致 + DB 直查 id=46/47/48 含 judge 字段 |
| AC-14 数据驱动默认值决策 | ✅ | config 默认 "dual"（TestConfig070）+ changelog 对比表 + 选择 + 理由 |
| AC-15 空输入 | ✅ | nli_judge.py:82 / memory_conflict_clf.py:190 strip() 守卫代码核对 |
| AC-16 judge 非法值 | ✅ | TestConfig070 Literal 三值 + TestEvalScriptDual 非法 judge SystemExit |
| AC-17 dual 延迟上界 | ✅ | clf 先行代码核对 + nli 20s wait_for（nli_judge.py:86） |
| AC-18 eval 失败样本处理 | ✅ | run_eval L393-397 skip 按 neutral 计数代码核对 + dual_judge both None 测试 |
| AC-19 全量基线全绿 | ✅ | Tester 独立复跑 **1163/0** |
| AC-20 存量测试零改动红线 | ✅ | numstat 387 插入 / 0 删除；conftest diff 0 行 |
| AC-21 改动范围纪律 | ✅ | git status 仅 9 文件全在 plan 清单 |
| AC-22 代码量 ≤200 行 | ✅ | ≈90 行 |
| AC-23 单一来源 | ✅ | dual_verdict 唯一实现；生产与 eval 均引用（测试断言 judge 接线 identity） |
| AC-24 无新依赖无新表 | ✅ | requirements/schema 零 diff |

**合计：24/24 全部通过。**

## 七、结论

**验收通过。** 关键验证点：
1. 全量 **1163 passed / 0 failed**（1142 基线 + Developer 10 + Tester 11），存量测试零改动（numstat 387/0，conftest 0 diff）；
2. Tester 新增 11 项单测补齐 Developer 未覆盖路径：dual_verdict 7 行决策表逐行枚举、dual 分支 nli 异常/clf None 两降级路径、eval 脚本 `--judge dual` 接线 + `scores["judge"]` 落库、config 默认 dual + Literal；
3. 三方案 70 条真实跑分 Tester 独立复跑与 changelog **逐字一致**（nli 0.6429/P0.9167/R0.55；clf 0.6/P0.8158/R0.775；dual 0.5286/P0.9412/R0.4）；
4. eval_runs 落库直查：id=46/47/48 judge 字段三行可区分（旧行 judge=None），数字与 changelog 一致；
5. 4 条边界陷阱 verdict=neutral 保持、零重叠断言全绿、无新依赖无新表；
6. Reviewer 5 项 LOW/minor 全部复核确认非阻塞（fixture 标签失真 / fp 标注复核 backlog / 测试数口径 / eval warning 缺失 / 项目上下文版本号）。

**模块状态：✅ 验收通过（待 Developer 提交推送）**
