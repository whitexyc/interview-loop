# 验收标准 — Module-047: 数据实验批

> 图例：📋 功能 / 📦 降级 / 🧪 测试 / 📝 文档

## 1. 功能验收（WP1 真实 baseline）

- [ ] 📋 golden_intent.py 真实模式跑通（Accuracy/混淆矩阵）+ eval_runs eval_type='intent' 落库（首条正式记录）
- [ ] 📋 golden_sufficiency.py 真实模式跑通（Accuracy + insufficient Recall）+ eval_runs eval_type='sufficiency' 落库
- [ ] 📋 数字如实记录（含 skipped 样本数）

## 2. 功能验收（WP2 阈值校准）

- [ ] 📋 eval/threshold_scan.py：对 L2 触发阈值（0.2-0.8）与硬闸门阈值（0.2-0.6）扫描
- [ ] 📋 输出 P/R/F1 曲线 + 推荐阈值 + 与经验值（0.5/0.4）对比说明
- [ ] 📋 数据驱动结论（若推荐值≠经验值，给出理由；若一致，确认经验值合理）

## 3. 功能验收（WP3 golden 扩样本）

- [ ] 📋 eval/golden.json ≥100 题（30→100+）
- [ ] 📋 每题格式对齐现有结构（question + golden_docs + 可空 ground_truth）
- [ ] 📋 主题来自知识库真实内容（不编造），结构校验通过
- [ ] 📋 检索回归可跑（DB 可用则跑 Hit@5 对比，不可用则结构校验 + 冒烟标注）

## 4. 功能验收（WP4 图谱消融）

- [ ] 📋 --ablate graph_only / hybrid 跑通（DB 可用）→ 输出 Hit@5 差值（+X.X 或持平）
- [ ] 📋 DB 不可用 → 方法学 + 已就绪命令 + 标注"待环境"（不阻塞）

## 5. 降级验收

- [ ] 📦 LLM API 限流/超时 → 重试 1 次 + 记录 skipped，不中断
- [ ] 📦 DB 不可用 → 不伪造数字，如实标注
- [ ] 📦 全量 pytest 503 全绿保持（0 失败）

## 6. 测试验收

- [ ] 🧪 tests/test_threshold_scan.py：扫描逻辑/P-R 计算/推荐阈值选取
- [ ] 🧪 python -m pytest tests/ -q — 全量 503+ 全绿

## 7. 文档验收

- [ ] 📝 changelog.md / review-report.md / test-report.md（含全部实测数字）
- [ ] 📝 记忆文件更新
- [ ] 📝 简历弹药待办更新（0.96 扩样本口径、图谱增量数字如有）
