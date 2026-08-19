# 验收标准 — Module-062: 记忆进化 2（类型化衰减 + 冷记忆降权）

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档
> 范围（用户确认方向）：ADR-0007 **P2 类型化衰减（A-MAC）+ P3 冷记忆降权（Memory Decay）**；P4 反馈闭环留后续

## 1. 功能验收（WP1 类型判断 + 评测）

- [ ] 📋 **双方案对比**：方案 A 分类模型（bge-m3+LR，复用 module-056 intent 基建，人造 120 条训练 → memory_type_clf.joblib）vs 方案 B LLM（extract_facts 输出 type，few-shot）
- [ ] 📋 `extract_facts` 输出每条 fact 带 `type`（preference/fact/event）；type 缺失/非法 → 默认 "fact"
- [ ] 📋 `eval/build_memory_type_dataset.py`：人造训练集（120 条，与评测集**零重叠防泄漏**）+ `scripts/train_memory_type_clf.py`（复用 train_intent_classifier 模式）
- [ ] 📋 `eval/memory_type_dataset.py`：评测集（30 条）+ 分类模型 vs LLM **同集对比** Accuracy/P/R/F1（eval_runs eval_type='memory_type' 含 model 字段区分 clf/llm）
- [ ] 📋 达标线声明（Accuracy≥0.8）——**谁达标谁上**（双达标取高分）；都不达标 → 类型化回退（type 按默认），不预设成功；`memory_type_mode`（clf/llm/none）定生产注入
- [ ] 📋 矛盾检测说明：module-061 已用 mDeBERTa NLI 实现但评测 Recall 0.5<0.8 默认关，本模块不重复做（如实记录）

## 2. 功能验收（WP2 P2 类型化衰减）

- [ ] 📋 documents 加 `type` 列（VARCHAR(16) DEFAULT 'fact'，init_db 幂等 ALTER + migrate_module062.py 本地先决）
- [ ] 📋 `_evolve_recall` 按 type 差异化半衰期：preference=30 天（慢）/ event=1 天（快）/ 其余（含存量无 type）→ 现状 `memory_short_half_life=3` 天（**零回归**，推荐口径）
- [ ] 📋 同 age 不同 type 衰减系数不同（单测断言）；存量无 type 行为与 module-046 完全一致
- [ ] 📋 升级逻辑不动（≥2 次/7 天，未按类型区分，如实声明）
- [ ] 📋 开关 `PW_MEMORY_TYPE_DECAY` 默认 true；false 回退全局 half_life

## 3. 功能验收（WP3 P3 冷记忆降权）

- [ ] 📋 documents 加 `last_recalled_at` 列（TIMESTAMP，同批 ALTER）
- [ ] 📋 `recall`（长期层）降权：`cold_factor = 1.0`（最近召回）/ 平滑渐降 / 久未召回（≥30 天）→ ×0.3（下限可调 `memory_cold_decay_min`）；**不删除**
- [ ] 📋 存量无 last_recalled_at → cold_factor=1.0（零回归）
- [ ] 📋 召回命中 fire-and-forget 刷新 last_recalled_at（不阻塞；对齐提及刷新模式）
- [ ] 📋 短期层不降权（已有衰减），口径如实声明；开关 `PW_MEMORY_COLD_DECAY` 默认 true；false 回退
- [ ] 📋 降权顺序声明（检索 → 降权 → 动态 K 截断，如实记录）

## 4. 验收（WP4 矛盾检测训练启用 + WP5 收口）

- [ ] 📋 `build_memory_conflict_train.py`：100+ 记忆矛盾训练集（改口/迁移/过时/升级冲突/正例中性，与评测集零重叠）
- [ ] 📋 `train_memory_conflict_clf.py`：bge-m3 嵌入新旧两条记忆 + LR 二分类 → `models/memory_conflict_clf.joblib`（复用分类器基建）
- [ ] 📋 clf vs mDeBERTa NLI 同集对比表（Accuracy/P/R/F1）——**Precision ≥ 0.8 者启用**
- [ ] 📋 达标后 `PW_MEMORY_CONFLICT=true` 且 `_merge_duplicate` 矛盾分流真实生效（测试验证）；不达标保持关如实标注
- [ ] 📋 Recall 后续提升方向入 changelog backlog（扩充样本/调阈值/更强中文 NLI）
- [ ] 📋 `tests/test_memory_evolution2.py`（新）：类型判断双方案/类型化半衰期/开关回退/冷降权系数与刷新/矛盾检测 clf/DDL 幂等/评测基线一致性
- [ ] 📋 conftest autouse 钉住新开关 false（对齐 056/058/060/061 模式）；新测试显式开 true
- [ ] 📋 ADR-0007 状态行更新（P2+P3 已实施，注明并入 module-062）
- [ ] 📋 面试口径更新点落盘（记忆类型化衰减 A-MAC 参考 + 冷记忆降权不删旧 + 矛盾检测 Precision 达标启用）

## 5. 降级验收

- [ ] 📦 LLM 类型判断失败/超时 → facts 无 type → 默认 fact（fail-open）
- [ ] 📦 类型化衰减计算异常 → memory_short_half_life 兜底（现状行为）
- [ ] 📦 冷降权计算异常 → cold_factor=1.0 不降权（不影响召回）
- [ ] 📦 documents 缺新列 → init_db 幂等 ALTER 自动补 + migrate_module062.py 本地先决
- [ ] 📦 全量 pytest 825+N 全绿保持

## 6. 接口兼容

- [ ] 🔌 `_evolve_recall` 公式结构不变（只换 half_life 来源）；短期层衰减行为对存量零回归
- [ ] 🔌 `recall`/`recall_short` 返回结构不变（[{content, score, title, created_at}]）
- [ ] 🔌 documents 加列为增量（type 默认 'fact'、last_recalled_at 可空）；init_db 幂等（重复启动不报错）
- [ ] 🔌 `extract_facts` 返回结构加 type 为增量（旧调用方取 content/importance 不受影响）

## 7. 测试验收

- [ ] 🧪 `tests/test_memory_evolution2.py`（新）：extract_facts type 输出与默认 / 类型化半衰期系数（不同 type 同 age）/ 开关 false 回退现状 / 冷降权系数（久未召回 vs 最近）/ 存量无字段零回归 / last_recalled_at 刷新 fire-and-forget / DDL 幂等 / 评测基线一致性
- [ ] 🧪 mock LLM 类型判断（不依赖真实 LLM 跑全量）
- [ ] 🧪 存量 test_memory.py 零改动全绿（新字段默认值兜底）
- [ ] 🧪 `python -m pytest tests/ -q` — 全量 825+N 全绿（**不改存量测试掩盖**）

## 8. 文档验收（含记忆硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含类型 baseline 数字 + 达标判定 + 降级声明 + 口径变化）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-062 行** + 头部"最后更新"日期改为当天
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0007 状态行更新（P2+P3 已实施）
- [ ] 📝 **CONTEXT.md 只增不删**（类型化衰减/冷记忆降权术语追加；同步/合并永远取更全一侧）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
