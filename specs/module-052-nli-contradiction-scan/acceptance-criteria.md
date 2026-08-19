# 验收标准 — Module-052: NLI 矛盾扫描前置决策

> 图例：📋 功能 / 📦 降级 / 🔌 接口 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP-0 环境准备）

- [ ] 📋 mDeBERTa-v3 模型下载到 `models/mdeberta-nli/`（curl resolve 直链 + 断点续传，完整可加载）
- [ ] 📋 transformers 5.x 离线加载成功（分数与 HF README 参考值核对，无 embed_tokens 类兼容坑）
- [ ] 📋 资源实测有数字：峰值内存 + 25 对批量 CPU 耗时（防超 15s 哲学）+ 全机模型账（~5GB）余量确认

## 2. 功能验收（WP-A 中文实测）

- [ ] 📋 100 对真实中文 (文档片段, claim) 构造完成（SUFFICIENCY_DATASET 主源，同口径可对比）
- [ ] 📋 人工标注三分类完成（entailment/contradiction/neutral，含标注指南）
- [ ] 📋 输出：mDeBERTa Accuracy + Cohen's kappa（三分类 + 二值化两口径）vs HHEM 同数据对比
- [ ] 📋 主对比指标 = kappa（注明口径：HHEM 二分类基线 50% vs NLI 三分类基线 33%，Acc 仅参考）

## 3. 功能验收（WP-B 选型决策）

- [ ] 📋 决策树产出明确结论：替换（含三态映射定义 + kappa 复测计划 + 阈值校准计划）/ 双轨 / 放弃（记录否决理由）
- [ ] 📋 ADR-0010 已更新（状态行 + "P1-③ 选型结论"小节）
- [ ] 📋 放行决定明确（通过才动代码；不通过则记录理由）

## 4. 降级验收

- [ ] 📦 模型下载/加载失败 → 报错路径 + 如实标注"待环境"，不伪造数字
- [ ] 📦 真实数据源（messages/DB）不可用 → 如实标注，主源结论不受影响
- [ ] 📦 全量 pytest 614 全绿保持

## 5. 接口兼容

- [ ] 🔌 不改 verify_answer / 检索链路（本模块只做数据验证 + 决策）
- [ ] 🔌 eval/golden_sufficiency.py 只读 import 不动

## 6. 测试验收

- [ ] 🧪 tests/test_compare_nli.py：数据构造（100 对/三分类标注映射）、指标（Accuracy/kappa 两口径）、模型缺失报错、降级（mock）
- [ ] 🧪 python -m pytest tests/ -q — 全量 614+ 全绿

## 7. 文档验收（含记忆更新硬性约束）

- [ ] 📝 changelog.md / review-report.md / test-report.md（含全部实测数字 + 口径声明）
- [ ] 📝 **memory/project-context.md 模块清单追加 module-052 行**（格式对齐：编号/名称/版本号/日期/状态含数字）+ 头部"最后更新"日期
- [ ] 📝 **memory/agent-activity-log.md**：Developer/Reviewer/Tester 各追加自己的活动行
- [ ] 📝 **memory/file-index.md**：本模块新文件行（只追加）
- [ ] 📝 ADR-0010 状态更新（P1-③ 前置决策完成/结论）
- [ ] 📝 开工前必读 project-context.md（Developer 在 changelog 注明已读）
