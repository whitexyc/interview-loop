# 验收标准 — Module-070: 记忆矛盾检测——评测集扩展 + 双判共识决策

## 1. 功能验收

### 1.1 核心路径验收（双判共识语义）

- [ ] **AC-1 双确认才 superseded**：`_judge_conflict` 在 `memory_conflict_judge="dual"` 下，nli 判 "contradiction" 且 clf 判 "contradiction" → 返回 "contradiction"；`_merge_duplicate` 收到后旧父块 `superseded=true` + `updated_at=now`（commit），返回 None 由 save 按正常新增入库（新旧并存可审计，旧记忆从召回面过滤——module-061 语义不变）
- [ ] **AC-2 单判 contradiction → conflict_hint 并存**：nli 判 "contradiction" 且 clf 判 "non_conflict"（或反之）→ `_judge_conflict` 返回 "conflict_hint"；`_merge_duplicate` 按追加拼接处理（新旧并存，**不标 superseded**，status="updated"，库内条数不涨），并打 info 日志（"记忆冲突提示（双判不一致）"）
- [ ] **AC-3 双方非矛盾 → 原语义**：nli 判 "entailment"/"neutral" 且 clf 判 "non_conflict" → 返回 nli 标签，追加拼接（module-046 行为不变）
- [ ] **AC-4 clf 模型缺失 → nli 单判零回归**：dual 模式下 `memory_conflict_clf.load()` 返回 False → 结果与 `judge="nli"` 逐字一致（nli "contradiction" → superseded；nli None → 追加）；clf.predict 断言未被调用
- [ ] **AC-5 nli 不可用 → clf 单判（新增对称回退）**：dual 模式下 nli 返回 None（模型加载失败/20s 超时/异常）→ 返回 clf 判定结果（clf "contradiction" → superseded；clf "non_conflict" → 追加）
- [ ] **AC-6 双方不可用 → None 旧行为**：dual 模式下 nli 与 clf 均不可用（None/异常）→ 返回 None → 追加拼接（零回归）
- [ ] **AC-7 存量分支逐字不变**：`judge="nli"` / `judge="clf"` 分支行为与 module-062 逐字一致（存量 `TestJudgeConflictDispatch` 5 项断言零改动全绿：nli 默认路径 / clf 命中不调 NLI / clf 失败回退 nli / clf None 回退 nli / clf 模型缺失回退 nli）
- [ ] **AC-8 开关关零回归**：`memory_conflict_enabled=False` 时 `_merge_duplicate` 不调用 `_judge_conflict`，完全旧行为（追加拼接）

### 1.2 评测集验收（WP-A）

- [ ] **AC-9 数据集 70 条结构校验**：`load_memory_conflict_dataset()` 通过（≥20 条 / contradiction ≥15 / 含 entailment+neutral）；`TestConflictDataset::test_dataset_structure_valid`（len≥20 / contradiction≥15 / 五类场景子集断言）全绿
- [ ] **AC-10 4 条边界陷阱不可改**：scenario="边界" 的 4 条样本（计划 vs 事实 / 想法 vs 结果 / "不买"vs"不喝" / 场景限定并存）**verdict=neutral 保持不变**（用户 2026-08-18 已确认标注，任何情况下不得修改其 verdict；仅可增补样本）
- [ ] **AC-11 训练/评测零重叠恢复**：`test_train_dataset_balance_and_no_overlap`（test_memory_evolution2.py:826-838）全绿——新增中性样本 hypothesis 措辞去重（"用户喜欢摄影" → "用户平时喜欢摄影"，verdict=neutral 不变）后 `eval_texts & train_texts` 为空（Developer 实测验证）
- [ ] **AC-12 dual 评测可跑**：`python -m eval.datasets.memory_conflict_dataset --judge dual --limit 5` 正常输出（"conflict_hint" 已映射 neutral，无 skip 异常）；`--judge nli` / `--judge clf` 存量行为不变
- [ ] **AC-13 三方案真实跑分落库**：70 条口径下 `--judge nli` / `--judge clf` / `--judge dual` 三次真实跑分 eval_runs 落库（eval_type='memory_conflict'），**scores 含 judge 字段可区分三行**；对比表（P/R/F1/tp/fp/fn + dataset_size 70 + skipped）写入 changelog
- [ ] **AC-14 数据驱动默认值决策**：对比表产出后决策默认值（brief 倾向 dual 默认 + nli 回退保留；改默认需 changelog 记录对比表 + 最终选择 + 理由）；不预设结论，数字未达预期如实标注

### 1.3 边界条件验收

- [ ] **AC-15 空输入**：dual 模式下空/空白 premise 或 hypothesis → None（`nli_judge.predict` 与 `memory_conflict_clf.predict` 内建守卫，不抛异常）→ 追加
- [ ] **AC-16 judge 非法值**：`memory_conflict_judge` 配置非法值（非 clf/nli/dual）→ pydantic Literal 启动拒绝（配置校验，不静默）
- [ ] **AC-17 dual 延迟上界**：dual 模式最坏延迟 = nli 20s 超时 + clf 本地嵌入推理（~1s 内），与现状 nli 单判同量级；clf 先行调用（不因 clf 不可用白等 nli 前序路径）
- [ ] **AC-18 eval 失败样本处理**：单条判定异常 → skip 记录按 neutral 计数（run_eval 存量语义，不污染 contradiction 统计），skipped 数如实打印

## 2. 非功能验收

### 2.1 回归验收

- [ ] **AC-19 全量基线全绿**：`pytest tests/ -q` 基线 **1142/0**（已实测收集 = 1142）+ 新增单测全绿（scripts/test_models.py 1 项 module-050 遗留收集 ERROR 沿用，非本模块回归）
- [ ] **AC-20 存量测试零改动红线**：`git diff main -- ai_service/tests/` 仅新增测试用例行（test_memory_evolution2.py 内新增），存量断言、conftest autouse（`memory_conflict_enabled=False` + `memory_conflict_judge="nli"`）**零改动**；`TestJudgeConflictDispatch` 存量 5 项逐字不改

### 2.2 代码质量验收

- [ ] **AC-21 改动范围纪律**：只动 `memory.py`（`_judge_conflict` + `_merge_duplicate` 日志 + `dual_verdict`）+ `config.py`（memory_conflict_judge）+ `eval/datasets/memory_conflict_dataset.py` + `tests/memory/test_memory_evolution2.py`；其他模块零改动
- [ ] **AC-22 代码量**：功能代码 ≤ 200 行（dual_verdict ~12 + dual 分支 ~25 + 日志 2 + config 1 + eval 脚本 ~20 ≈ 60 行；含注释/测试口径自动豁免）
- [ ] **AC-23 单一来源**：`dual_verdict` 纯函数为共识逻辑唯一实现（生产 `_judge_conflict` 与 eval `dual_judge` 均引用之，防语义漂移）；`_judge_conflict` dual 分支保持函数内 import 延迟加载哲学
- [ ] **AC-24 无新依赖无新表**：不新增 requirements 条目、不新增数据表/列

## 3. 可运行验证命令

| 验收项 | 验证命令（在 ai_service 目录） | 预期输出 |
|--------|----------|----------|
| AC-9/10/11 数据集 + 零重叠 | `python -m pytest tests/memory/test_memory_evolution2.py::TestConflictEvalBaseline tests/memory/test_memory_correction.py::TestConflictDataset -q` | 全部 passed |
| AC-1~8/15 dual 行为 | `python -m pytest tests/memory/test_memory_evolution2.py::TestJudgeConflictDispatch -q` | 存量 5 项 + 新增 dual 项全部 passed |
| AC-19/20 全量回归 | `python -m pytest tests/ -q` | `1142 + 新增 passed / 0 failed`，存量零改动 |
| AC-12 dual 冒烟 | `python -m eval.datasets.memory_conflict_dataset --judge dual --limit 5 --no-save` | 5/5 无 skip，正常输出 |
| AC-13 真实跑分 | `python -m eval.datasets.memory_conflict_dataset --judge nli`（clf/dual 同款） | 70 条评估 + eval_runs 落库（scores 含 judge 字段） |
| AC-14 对比表 | changelog.md WP-A 节 | 三方案 P/R/F1 表 + 选择 + 理由 |

## 4. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
