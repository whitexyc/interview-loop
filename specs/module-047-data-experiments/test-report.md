# 测试报告 — Module-047 数据实验批（全量回归 + 新增测试验证）

> Tester | 2026-08-10 | 独立复跑（不依赖 dev/Reviewer 声明）

## 1. 结论

**verdict: pass（0 失败）**

| 项 | 结果 |
|----|------|
| 全量 pytest | **525 passed / 0 failed**（503 基线 + 22 新增），5 warnings（预存，非本模块引入） |
| 新增 tests/test_threshold_scan.py | 22/22 通过 |
| 红线 1（文件清单） | ✅ 通过（详见 §4） |
| 红线 2（数字真实性） | ✅ 通过（详见 §5） |
| 红线 3（未 git commit） | ✅ 通过（HEAD 仍为 2eac844） |
| 红线 4（503 全绿保持） | ✅ 通过（525 = 503 + 22） |

## 2. 全量测试（红线 4）

命令与实测输出（ai_service 目录）：

```
python -m pytest tests/ -q
525 passed, 5 warnings in 122.23s (0:02:02)
EXIT_CODE=0
```

- 5 warnings 均为预存项（test_cache.py setex DeprecationWarning ×4 + test_memory.py SAWarning ×2），
  与 module-047 改动无关（thresh_scan 测试无 warning）。
- 525 = 历史基线 503 + 本模块新增 22，无任何新失败。

## 3. 新增测试验证（tests/test_threshold_scan.py）

独立逐用例复跑：**22 passed / 0 failed**（52.83s）。

覆盖清单（与 acceptance-criteria §6 逐项对应）：

| 类 | 用例数 | 验证点 |
|----|--------|--------|
| TestComputePrf | 3 | P/R/F1 手工复算（含分母 0 降级） |
| TestScanScores | 5 | t=0.40/0.55/0.70 手工复算 TP/FP/FN/P/R/F1/acc；score=None 永不触发；空样本不崩 |
| TestRecommendThreshold | 4 | argmax F1；min_recall 约束；无候选回退 fallback；空 rows 返回 None |
| TestL2TriggerSamples | 2 | 触发窗口（raw_intent≠knowledge → score=confidence）；should 定义 |
| TestL2FinalAccuracy | 3 | 复现 router.classify L2 修正逻辑（含 t=0.5 手工样例、t 上调提升） |
| TestScanL2AndGate | 2 | 端到端扫描行结构（final_accuracy 字段）；闸门手工复算 |
| TestScanRanges | 3 | 扫描区间常量 0.20-0.80/13 点、0.20-0.60/9 点；经验值与生产代码一致（0.5/0.4） |

- 被测模块 `eval/threshold_scan.py` 已读阅：纯函数逻辑与测试断言逐行对齐
  （scan_scores 的 `score < t` 判定、compute_prf 分母 0 → 0.0、recommend 的
  fallback 语义、l2_final_accuracy 与生产 router.py L2 条件一致）。
- 测试全部为纯函数测试，无 LLM/DB/embedding 依赖（数据收集在脚本 main，符合设计意图）。

## 4. 红线 1 核查（只动 plan 3.1 文件）

git status/diff 实测（HEAD 2eac844）：

| 文件 | 状态 | 归属 |
|------|------|------|
| ai_service/eval/golden.json | modified（30→112，唯一数据改动） | plan 3.1 WP3 ✅ |
| ai_service/eval/threshold_scan.py | untracked（新建） | plan 3.1 WP2 ✅ |
| ai_service/tests/test_threshold_scan.py | untracked（新建） | plan 3.1 WP2 ✅ |
| ai_service/tests/test_golden_retrieval.py | modified（1 处断言改数据无关，changelog §4.3 说明） | 必须的测试适配（数据扩样后硬编码断言必失败），Reviewer 已确认可接受 ✅ |
| specs/module-033-long-term-memory/changelog.md | modified（47 行） | **非本模块改动**：2026-08-08 前序会话 Reviewer 记录的跨模块缺陷清单，未提交遗留，与 module-047 无关（不违反红线，Planner 提交时按既有状态处理） |
| ai_service/.ua/（含 m047_threshold_cache.json） | untracked | 实验产物缓存，Reviewer 建议提交时排除（.ua/ 会话前即未跟踪） |

eval 脚本零改动确认：`golden_intent.py / golden_sufficiency.py / golden_retrieval.py /
golden_memory.py / faithfulness.json` diff 为空。

## 5. 红线 2 核查（数字真实性，独立复验）

Tester 独立复算（非仅引用 dev 声明）：

| 数字 | 声明值 | 独立验证方式 | 结果 |
|------|--------|--------------|------|
| golden 总数 | 112 | 直接加载 eval/golden.json | ✅ 112（keys=question/golden_docs/category；空 question 0；重复题 0；空 golden_docs 7） |
| 原 30 题零改动 | 逐字节 | git show HEAD:... vs 工作副本 sort_keys 对比 | ✅ 30/30 逐字节一致 |
| 新增 82 题 | 82 | 上述对比差值 | ✅ 82，新增题空 golden_docs 0 |
| L2 缓存 | 100 条 / skipped 0 | .ua/m047_threshold_cache.json（collected_at 2026-08-10T03:52:45） | ✅ 100/0 |
| LLM confidence 域内下限 | 0.70 | 缓存实测 min=0.70 max=1.00 | ✅ |
| 闸门缓存 | 100 条 / errors 0 | 同上 | ✅ 100/0 |
| top-1 余弦分布 | 充分 0.490-0.807 / 不充分 0.322-0.550 | 缓存实测 n=50+50 | ✅ 0.4899-0.8075 / 0.3219-0.5500 |
| WP1/WP3/WP4 运行数字 | changelog §2/§4/§5 | 与 Reviewer 的 DB eval_runs（id=9/11/12/13）+ 日志交叉核对一致；Tester 复核缓存可复现 | ✅ 无编造 |
| WP4 graph_only 0.0000 | 环境故障 | changelog 如实标注"待环境"（UndefinedColumnError 缺迁移列 + 无图谱表），未当图谱贡献量引用 | ✅ 如实标注 |

## 6. 红线 3 核查

- `git log --oneline -1` = 2eac844（module-046 提交），本会话未执行 git commit。✅

## 7. 结论与建议

- **verdict: pass**。525/525 全绿，新增 22 用例全部有效且与被测实现一致，4 条红线全部通过。
- 建议（不阻塞）：Planner 提交时
  1. 将 `ai_service/.ua/`（含 m047_threshold_cache.json）排除出提交（Reviewer 同建议）；
  2. 提交说明注明 test_golden_retrieval.py 1 处断言适配的原因（数据扩样后硬编码断言必失败，changelog §4.3）；
  3. specs/module-033-long-term-memory/changelog.md 的未提交改动为前序会话遗留，与 module-047 无关，按既有状态处理。
