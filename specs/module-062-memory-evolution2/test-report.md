# Module-062 测试报告 — 记忆进化 2（类型化衰减 + 冷记忆降权）

> Tester 产出 | 2026-08-13 | **验收通过（AC 全部通过，0 阻塞）**
> 对照 `specs/module-062-memory-evolution2/acceptance-criteria.md` 逐条核查 + 全量回归 + 冒烟复跑

## 一、全量回归数字

| 项目 | 结果 |
|------|------|
| 全量 pytest | **897 passed / 0 failed**（179.7s，3 个既有 Redis setex 弃用 warning + SQLAlchemy 连接清理 warning 与模块无关） |
| 基线 | 825（module-061 基线） |
| 新增 | 72 项（`tests/test_memory_evolution2.py`，collect 确认） |
| 存量改动 | `test_memory.py` 零改动；`test_memory_extractor.py` 仅 3 处精确结构断言按验收许可补 `type: "fact"` 字段（git diff 实证，见 §三） |
| conftest | +24 行，autouse 钉住（memory_type_mode='none' / cold_decay off / judge='nli' / conflict off） |

与 changelog §9 / Reviewer 第 2 轮复跑（897 passed / 0 failed）**逐位一致**。

## 二、冒烟复跑与 changelog 数字一致性

### 2.1 数据构造脚本（纯 Python，build 校验强制）
- `python -m eval.build_memory_type_dataset` → **Total 120**（preference 40 / fact 40 / event 40），校验含与评测集零重叠——与 changelog §2.1 一致。
- `python -m eval.build_memory_conflict_train` → **Total 142**（contradiction 82 / non_conflict 60），校验含与评测集零重叠——与 changelog §5.1 一致。

### 2.2 评测脚本冒烟（--fixture 确定性，--no-save 不落库）
- `python -m eval.memory_type_dataset --fixture --no-save` → Dataset 30 / Evaluated 30 / Accuracy **1.0000**，三类别 P/R/F1 全 1.0，达标线 Accuracy≥0.8 ✅。管线端到端可用（fixture 为关键词启发式，非真实指标）。
- `python -m eval.memory_conflict_dataset --fixture --no-save --judge nli` → Dataset 30 / Evaluated 30，fixture 启发式 Accuracy(3类) 0.70 / contradiction P 0.9412 / R 0.80。管线可用（fixture 非真实指标）。

### 2.3 eval_runs DB 实查（与 changelog §2.3/§5.2/§7 逐位一致）
| id | eval_type | model | 关键指标（scores JSONB 实查） | 达标 |
|----|-----------|-------|------------------------------|------|
| 32 | memory_type | clf | accuracy 1.0000，per_class 三全 1.0，gate_passed=true | ✅ |
| 33 | memory_type | llm | accuracy 1.0000，per_class 三全 1.0，gate_passed=true | ✅ |
| 34 | memory_conflict | clf | precision 0.9048 / recall 0.95 / f1 0.9268 / tp19 fp2 fn1 / acc_3class 0.7333 | Precision≥0.8 ✅ |
| 35 | memory_conflict | nli | precision 1.0000 / recall 0.5 / f1 0.6667 / tp10 fp0 fn10 / acc_3class 0.6 | Precision≥0.8 ✅ |

git_commit=8e014907 与 changelog §7 一致。id=35 gate_passed=false 系旧双门槛口径（Reviewer MINOR-3，changelog §5.3 已解释，非阻塞）。

### 2.4 真实模型推理冒烟（加载已训练 joblib）
- `memory_type_clf`：'用户喜欢喝咖啡'→preference / '用户明天去北京'→event / '用户是 Java 开发'→fact —— 与 changelog 冒烟一致。
- `resolve_memory_type` clf 模式：'用户偏好简洁回答'→preference（生产注入生效）。
- `memory_conflict_clf`：'喜欢喝咖啡' vs '讨厌喝咖啡'→contradiction；'喜欢喝咖啡' vs '养了一只猫'→contradiction —— **后者正是 changelog §5.3 如实标注的中性对误判（clf 2 个 fp 之一）**，诚实边界与实现一致。
- 模型文件在盘：models/memory_type_clf.joblib（25583 B）、models/memory_conflict_clf.joblib（33727 B）。

### 2.5 DB 列与迁移（本地先决已执行）
- documents.type：varchar(16) default 'fact'（DB 实查在）；documents.last_recalled_at：timestamp（无 tz，Reviewer MAJOR-1 已由 `_cold_ref_time` 源头 naive→UTC 规范化修复，见 changelog §9）。
- `scripts/migrate_module062.py` 存在且幂等（查 information_schema 跳过）；`src/database.py` `MEMORY_TYPE_COLUMNS_DDL` + `ensure_memory_type_columns` 幂等 ADD COLUMN IF NOT EXISTS。

## 三、实现抽查（关键实现与 changelog 一致性）

| 关键点 | 实现 | 与 changelog 一致 |
|--------|------|------------------|
| 类型判断双方案 | build/train/eval 三脚本 + `memory_type_mode="clf"`（clf/llm/none Literal）| ✅ |
| extract_facts type | `_EXTRACT_PROMPT` type few-shot + 缺失/非法→fact（memory_extractor.py:24,152-159）| ✅ |
| 类型化半衰期 | `_type_half_life`：preference 30 / event 1 / 其余=memory_short_half_life 3（memory.py:888-906）| ✅ |
| `_evolve_recall` 接 type | `memory_type_decay_enabled` 开关 → 按 type 选 half_life（memory.py:828-833）；公式结构不变 | ✅ |
| 冷记忆降权 | `_apply_cold_decay`：<30 天 ×1.0 → max(0.3, 1-(days-30)/100)，不删除 + fire-and-forget 刷新 + 新分重排（memory.py:908-985）| ✅ |
| naive→UTC 规范化 | `_cold_ref_time`：`ref.replace(tzinfo=timezone.utc)`（memory.py:156-157，Review 修复）| ✅ |
| WP4 启用判定 | `memory_conflict_enabled=True`（生产默认）+ `memory_conflict_judge="nli"`（config.py:167-168）；`_judge_conflict` clf→nli→None 降级（memory.py:559-577）；`_merge_duplicate` 矛盾分流（memory.py:513-514）| ✅ |
| 降级 fail-open | LLM 判型失败→fact / 类型化衰减异常→short_half_life / 冷降权异常→×1.0 / 裁判不可用→旧行为 | ✅ |
| 存量零回归 | `_memory_type_of`/`_cold_ref_time` 显式 isinstance 防 MagicMock 真值误伤 | ✅ |

## 四、AC 对照

图例：✅ 通过 / ⬜ 不适用。全部 8 节 **通过**，0 项不通过。

### §1 功能验收（WP1 类型判断 + 评测）
| AC | 判定 | 依据 |
|----|------|------|
| 双方案对比（clf vs LLM） | ✅ 通过 | 人造 120 条训练 → memory_type_clf.joblib；eval_runs id=32/33 同 30 条集 clf/LLM 双 1.0000 → 双达标同分取 clf |
| extract_facts 输出 type + 默认 fact | ✅ 通过 | memory_extractor.py type few-shot + 缺失/非法→fact；TestExtractFactsType 5 用例 |
| build/train 脚本 + 复用 intent 基建 | ✅ 通过 | build_memory_type_dataset.py 120 条零重叠 + train_memory_type_clf.py（bge-m3+LR）；真实运行通过 |
| 评测集 30 条 + clf vs LLM 同集对比 P/R/F1 | ✅ 通过 | eval/memory_type_dataset.py；DB scores 含 model 字段 + per_class P/R/F1 全 1.0 |
| 达标线 Accuracy≥0.8 + memory_type_mode | ✅ 通过 | gate_accuracy 0.8 / gate_passed=true；config memory_type_mode="clf" |
| 矛盾检测说明（mDeBERTa 不重复做） | ✅ 通过 | changelog/task-brief 声明 module-061 Recall 0.5<0.8 默认关；WP4 做对比非重复实现 |

### §2 功能验收（WP2 P2 类型化衰减）
| AC | 判定 | 依据 |
|----|------|------|
| documents 加 type 列 | ✅ 通过 | DB 实查 varchar(16) default 'fact'；init_db 幂等 ALTER + migrate_module062.py 已执行 |
| _evolve_recall 按 type 差异化半衰期 | ✅ 通过 | preference 30 / event 1 / 其余=3（`_type_half_life`）|
| 同 age 不同 type 系数不同 + 存量零回归 | ✅ 通过 | TestEvolveRecallTypeDecay（preference decay≈0.89 vs event≈0.03 @5 天）+ test_legacy_no_type_uses_short_half_life |
| 升级逻辑不动 | ✅ 通过 | changelog §3 声明未按类型区分 |
| PW_MEMORY_TYPE_DECAY 默认 true / false 回退 | ✅ 通过 | config memory_type_decay_enabled=True；test_switch_off_falls_back_to_global_half_life |

### §3 功能验收（WP3 P3 冷记忆降权）
| AC | 判定 | 依据 |
|----|------|------|
| documents 加 last_recalled_at 列 | ✅ 通过 | DB 实查 timestamp；init_db 幂等 + migrate 已执行 |
| recall 降权 ×0.3-1.0 不删除 | ✅ 通过 | `_apply_cold_decay` 公式；test_long_unrecalled_downgraded（90 天→×0.4）/ test_cold_factor_floor_03 / test_recent_recall_keeps_full_score |
| 存量无 last_recalled_at → ×1.0 | ✅ 通过 | `_cold_ref_time` None→×1.0；test_legacy_no_last_recalled_uses_created_at / test_missing_times_keeps_full_score |
| 召回命中 fire-and-forget 刷新 | ✅ 通过 | `_refresh_last_recalled`；test_refresh_last_recalled_fire_forget |
| 短期层不降权 + PW_MEMORY_COLD_DECAY 默认 true | ✅ 通过 | 仅长期层 recall 调用；config memory_cold_decay_enabled=True；test_switch_off_no_decay |
| 降权顺序声明（检索→降权→动态K截断） | ✅ 通过 | memory.py docstring + changelog §4；test_resort_by_new_score / test_recall_invokes_cold_decay |

### §4 验收（WP4 矛盾检测训练启用 + WP5 收口）
| AC | 判定 | 依据 |
|----|------|------|
| build_memory_conflict_train.py 100+ 训练集 | ✅ 通过 | 142 条（contradiction 82 / non_conflict 60），零重叠校验；真实运行通过 |
| train_memory_conflict_clf.py 训练落盘 | ✅ 通过 | bge-m3 嵌入新旧两条→拼接+差+绝对差 4096 维 + LR → memory_conflict_clf.joblib（在盘）；test_feature_concat_shape |
| clf vs mDeBERTa 同集对比 Precision≥0.8 启用 | ✅ 通过 | id=34 clf P 0.9048 / id=35 nli P 1.0000——双达标取 Precision 高者 → nli 启用 |
| PW_MEMORY_CONFLICT=true + 矛盾分流真实生效 | ✅ 通过 | config memory_conflict_enabled=True + judge='nli'；`_merge_duplicate` 调 `_judge_conflict`；TestJudgeConflictDispatch 5 用例 |
| Recall 提升入 backlog | ✅ 通过 | changelog §5.3/§7 |
| test_memory_evolution2.py 新 | ✅ 通过 | 72 项 collect（类型/半衰期/降权/裁判/评测基线/DDL/配置）|
| conftest autouse 钉住新开关 false | ✅ 通过 | conftest.py:88-125（mode none / cold off / judge nli / conflict off）|
| ADR-0007 状态行更新 | ✅ 通过 | ADR-0007 行 3 含 P2+P3+WP4 已实施 |
| 面试口径更新点落盘 | ✅ 通过 | changelog §8 |

### §5 降级验收
| AC | 判定 | 依据 |
|----|------|------|
| LLM 判型失败/超时 → 默认 fact | ✅ 通过 | test_missing_type_defaults_to_fact / test_extract_failure_returns_empty |
| 类型化衰减异常 → short_half_life 兜底 | ✅ 通过 | `_type_half_life` 其余分支 + half_life<=0→3.0 |
| 冷降权异常 → ×1.0 | ✅ 通过 | `_apply_cold_decay` except→factor 1.0；test_db_failure_keeps_original |
| documents 缺列 → init_db 幂等 ALTER + migrate 先决 | ✅ 通过 | TestDdlIdempotency 2 用例 + 本地库列实查在 |
| 全量 pytest 825+N 全绿 | ✅ 通过 | 897 passed / 0 failed |

### §6 接口兼容
| AC | 判定 | 依据 |
|----|------|------|
| _evolve_recall 公式结构不变 | ✅ 通过 | 只换 half_life 来源（memory.py:828-833）|
| recall/recall_short 返回结构不变 | ✅ 通过 | 仅加权不改结构；TestRecallIntegratesColdDecay |
| documents 加列为增量 | ✅ 通过 | DDL 幂等（重复启动不报错）|
| extract_facts 返回结构加 type 为增量 | ✅ 通过 | 旧调用方取 content/importance 不受影响；3 处存量断言按 AC §6 许可补 type |

### §7 测试验收
| AC | 判定 | 依据 |
|----|------|------|
| test_memory_evolution2.py 覆盖 | ✅ 通过 | 72 项（分类器推理/三模式/半衰期/降权系数·下限·存量·开关·DB 失败·重排·刷新/裁判切换/评测基线/DDL/配置）|
| mock LLM 类型判断 | ✅ 通过 | TestExtractFactsType 用 mock client，不依赖真实 LLM |
| 存量 test_memory.py 零改动全绿 | ✅ 通过 | git diff 确认未改；897 全绿 |
| 全量 825+N 全绿（不改存量测试掩盖） | ✅ 通过 | 897 passed / 0 failed |

### §8 文档验收（含记忆硬性约束）
| AC | 判定 | 依据 |
|----|------|------|
| changelog / review-report / test-report | ✅ 通过 | changelog §1-§9（含 Review 修复记录节）+ review-report（第 2 轮 pass）+ 本 test-report |
| project-context module-062 行 + 头部日期 | ✅ 通过 | 行 79 存在且格式对齐；头部"最后更新 2026-08-13（module-062 完成）"|
| agent-activity-log Dev/Rev/Test 三行 | ✅ 通过 | Developer（行 180）+ Reviewer 两轮（行 181/182）+ Tester（本条追加）|
| file-index 新文件行 | ✅ 通过 | 9 条代码/脚本/测试行 + specs 目录行（行 107-116）|
| ADR-0007 状态行更新 | ✅ 通过 | 行 3 含 P2+P3+WP4 已实施（module-062）|
| CONTEXT.md 只增不删 | ✅ 通过 | git diff：+8 行追加"记忆进化 2 领域"节，无删除 |
| 开工前必读 project-context.md | ✅ 通过 | changelog 头注明已读全文 |

## 五、记忆核查结论（硬性约束）

- ✅ project-context.md：module-062 行存在、格式对齐（编号/名称/版本/日期/状态含测试数字）、头部"最后更新"日期 2026-08-13。
- ✅ agent-activity-log.md：Developer / Reviewer（第 1 轮 conditional + 第 2 轮 pass）/ Tester（本条）三行均在 module-062 表格。
- ✅ file-index.md：module-062 新文件行 9 条 + specs 目录行（只追加，无删除）。
- ✅ ADR-0007 状态行已更新（P2+P3 已实施 + WP4 启用）。
- ✅ CONTEXT.md 只增不删（+8 行）。
- 注：Reviewer MINOR-7（修复新增 2 测试后 project-context/file-index 计数 895/70 未同步 897/72）为既有行内计数漂移，非新增文件行缺失，非阻塞。

## 六、非阻塞观察

1. `TestConfig062::test_conflict_enabled_default_off` 的注释"不预设成功（Precision≥0.8 达标才启用）"已过时——WP4 已达 Precision 门槛，生产默认 `memory_conflict_enabled=True`；该断言实际校验的是 conftest 钉住的 hermetic 值（False），行为正确，仅注释口径需更新。
2. Reviewer 7 项 minor（env 名 `PW_MEMORY_CONFLICT` vs `PW_MEMORY_CONFLICT_ENABLED` 不一致 / `_promote_memory` 长期副本 type 丢失 / gate_passed 旧双门槛 / clf 每次重载模型 / preference 30 vs 硬上限 30 交互 / `_apply_cold_decay` identity 参数未用 / 计数漂移）全部保持非阻塞，无一项影响合入。

## 七、结论

**验收通过。** 全量 897 passed / 0 failed；冒烟复跑（数据构造 / 评测 fixture / eval_runs DB 实查 / 真实模型推理 / DB 列与迁移）与 changelog 数字逐位一致；实现抽查 8 项关键点全部与 changelog 一致；记忆硬性约束五项全满足（含 Tester 活动行已追加）；AC 8 节全部通过。Reviewer MAJOR-1（P3 冷降权真实 DB naive/aware 时间差）已修复并锁定（`_cold_ref_time` 源头规范化 + 2 条 naive 单测）。无阻塞问题。
