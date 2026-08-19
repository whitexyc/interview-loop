# Module-070 Task Brief：记忆矛盾检测——评测集扩展 + 双判共识决策

> 自包含执行简报（待办 #3"矛盾检测 Recall 提升"的完整落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读 + 评测集已扩 + 用户已确认标注），无需重新调研。

## 事实（代码实测 + 2026-08-18 评测集扩充）

1. **评测集已扩 30 → 70 条**（`eval/datasets/memory_conflict_dataset.py`，2026-08-18 已写入 + fixture 验证通过）：新增 40 条全部基于用户真实信息派生（真实分布打底），含 4 条**语义边界陷阱**（scenario=边界：计划 vs 事实 / 想法 vs 结果 / "不买"vs"不喝" / 场景限定并存——全部标 neutral，用户已确认标注）。
2. **两个裁判都有水分**（module-062 WP4 实测，同 30 条评测集）：
   - nli（mDeBERTa）：Precision 1.0000 / Recall 0.5000（eval_runs id=35）——但 module-052/057 已实测 mDeBERTa 中文矛盾判别短板（kappa 0.3754-0.5167 未达标），1.0 是"窄而准"的小评测集假象
   - clf（bge-m3+LR，142 人造案例训练）：Precision 0.9048 / Recall 0.9500（id=34）——人造分布数字，真实泛化未知
   - **结论：数字都不可信 → 不选单一裁判**（用户决策，2026-08-18）
3. **现有配置**：`memory_conflict_enabled=true` + `memory_conflict_judge="nli"`（config.py:206-207）；`_judge_conflict`（memory.py:540-577）按 judge 选裁判，clf 不可用回退 NLI，异常回退 None（旧行为零回归）。
4. **矛盾处理语义**（memory.py:472）：contradiction → 旧父块标 superseded=true + updated_at=now（**逻辑删除非物理删除**，可审计可回溯）；召回侧 `_is_superseded` 过滤。
5. **待办 #3 目标**：Recall 提升（0.5 → 更高）**同时不牺牲 Precision**（冤枉 = 误标 superseded = 用户记忆消失，代价高）。
6. **基线**：全量 1142/0（module-069 后）；test_memory_evolution2.py:792 断言 len >= 30（宽松，扩充无破坏）。
7. 评测脚本：`python -m eval.datasets.memory_conflict_dataset`（真实 NLI baseline）+ `--fixture`（关键词演示）。

## WP-A：评测集收尾 + 双裁判真实对比（数据说话）

- 新增 40 条样本已写入；补：单测更新（如 test_memory_evolution2.py:827-834 遍历样本的断言仍过）+ 校验通过确认
- `python -m eval.datasets.memory_conflict_dataset`（真实 nli）+ clf 对比跑分——**新 70 条口径下 nli vs clf 的 P/R/F1**
- 预期发现：nli Precision 1.0 大概率跌（边界陷阱 4 条 + 更多真实分布样本暴露短板）、clf 泛化水平未知
- **产出：对比表 + 数据驱动的裁判决策建议**（不预设结论）
- 通过标准：真实跑分落库（eval_runs）+ 对比表写入 changelog

## WP-B：双判共识 + 降级（行为层修复，不依赖数据）

- `_judge_conflict` 改造为双裁判流程：
  - **nli 判 contradiction + clf 判 contradiction** → "contradiction"（双确认才标 superseded，Precision 极保守）
  - **单裁判判 contradiction**（一方说矛盾另一方不判/不可用）→ 降级：不标 superseded，返回特殊标记（如 "conflict_hint"）→ 上层新旧并存（旧行为）
  - **双判都不 contradiction** → 按原语义处理（entailment/neutral → 正常合并）
- clf 不可用（模型缺失）→ 回退 nli 单判（现状行为零回归）；nli 不可用 → 回退 clf 单判（新增对称回退）
- 配置：`memory_conflict_judge` 语义扩展为 `"dual"`（默认值从 nli 改为 dual？——**决策留给 Developer 基于 WP-A 数据**，task-brief 倾向 dual 默认 + nli 回退保留）
- 通过标准：单测（双判矛盾→superseded / 单判→并存标记 / 双不可用→None 零回归 / clf 缺失回退 nli）+ 存量 1142 全绿

## WP-C：回归 + 文档收口

- 全量 1142 基线 + 新增单测全绿（存量测试零改动红线）
- changelog + CONTEXT.md（只增不删，先备份）+ 三记忆文件
- WP-A 对比表结论写入 changelog（nli/clf/dual 三方案数据 + 最终选择 + 理由）
- METRICS.md 待办区第 3 条标记完成（如达标）或如实更新

## 纪律项

1. 只动 `memory.py::_judge_conflict` + `config.py` + `eval/datasets/memory_conflict_dataset.py`（样本已写，只可增补不可删改 verdict）+ 相关单测——**其他模块一律不碰**
2. 双判共识是行为层修复，**不依赖 WP-A 数据**（数据只影响"最终选哪个配置默认值"，不影响实现）
3. 判定器确定性优先；评测集标注（4 条边界陷阱 verdict=neutral）**已由用户确认，不得改**
4. 编码调 ponytail skill（最简可行：_judge_conflict 双判分支 + config 字段，不重写记忆层）
5. 存量测试零改动（改了=FAIL）
