# Module-070 审查报告 — 记忆矛盾检测：评测集扩展 + 双判共识决策

> Reviewer：2026-08-18 | 对照 `acceptance-criteria.md` + `plan.md` + task-brief 逐项核查
> 结论：**✅ PASS（5 项 LOW/minor 非阻塞记录）**

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest tests/ -q` | **1152 passed / 0 failed（225.80s，43 warnings）** 与 changelog 一致 |
| memory 单测 | 独立复跑 `tests/memory/test_memory_evolution2.py` | **82 passed**（HEAD 基线 72 + 新增 10，逐函数核对 diff 恰好 +10） |
| AC-9/10/11 数据集 + 零重叠 | `TestConflictEvalBaseline + TestConflictDataset` | 6 passed（70 条结构 / 4 边界陷阱 neutral / `eval_texts & train_texts = set()`） |
| 存量 TestJudgeConflictDispatch | `git show HEAD` 计数 | 恰 5 项，diff 仅在其后追加新类，逐字未改 |
| conftest / 存量测试零改动 | git status + git diff tests/ | 仅 test_memory_evolution2.py 新增用例行，conftest 零 diff |
| eval_runs 真实跑分 | 直查 DB（id=46/47/48） | 与 changelog 表**逐字一致**：46 nli acc 0.6429/P 0.9167/R 0.55/tp22/fp2/fn18；47 clf 0.6/0.8158/0.775/tp31/fp7/fn9；48 dual 0.5286/0.9412/0.4/tp16/fp1/fn24；size=70、skipped=0、judge 字段区分三行 |
| AND 共识逐样本验证 | 直查 id=46/48 per_question 交叉 | nli fp=2 → dual fp=1：nli 独判误标样本（"用户现在大三 \| 用户是本科生"）被 clf 判 non_conflict → conflict_hint → neutral 中和；仅剩双方一致判矛盾的 1 条 |
| 判定器确定性 | 代码阅读 | dual_verdict 纯函数 + 双模型推理，零 LLM 介入，可复现 |
| py_compile | 4 个变更 py 文件 | OK |
| CONTEXT.md | git diff | 仅末尾 +10 行追加，零删行 |
| METRICS.md | git diff | 记忆矛盾检测段 70 条三方案表 + 待办③ 标记完成（量化更新） |
| ADR-0007 | 读状态行 | 补「P1 双判共识已实施（module-070）」+ 默认 dual 决策 + 跑分数字 |
| 记忆三件套 | 读 project-context / file-index / activity-log | module-070 行 + [PLAN]/[CODE] 全在（本条为 Reviewer 行） |

## 二、WP 逐项核对

### WP-A：评测集收尾 + 三方案真实跑分 — ✅ 通过

- **措辞去重**：`memory_conflict_dataset.py:196` "用户平时喜欢摄影"（verdict=neutral 不变、非边界陷阱样本）；零重叠断言实测通过（`test_train_dataset_balance_and_no_overlap` 全绿）✓
- **数据集结构**：70 条 = contradiction 40 / entailment 15 / neutral 15；scenarios 五类子集断言通过；4 条边界陷阱（L206-213）verdict=neutral 保持 ✓
- **eval 扩展**：`dual_judge`（L329-361）引用生产 `dual_verdict` 单一来源（AC-23）；conflict_hint→neutral 映射声明准确（contradiction P/R 主指标等价，accuracy_3class 失真如实声明）；`--judge dual`（L479）；`scores["judge"] = args.judge`（L501）落库区分三方案 ✓
- **三方案真实跑分**：DB 直查 id=46/47/48 数字与 changelog 对比表**逐字一致**（见 §一）——nli 30 条口径 1.0 假象证实（70 条 0.9167）、clf 人造分布缩水（0.8158 fp=7）、dual Precision 0.9412 fp=1 三方案最高 ✓
- **默认值决策数据驱动**：`config.py:213` 默认 "dual"——对比表 + 最终选择 + 理由（Precision 优先哲学 + fail-open 零回归 + clf 一键切换）全入 changelog §1.4；plan 要求"先保持 nli，数据产出后决策"流程正确执行（不预设结论）✓

### WP-B：双判共识 + 降级 — ✅ 通过

- **`dual_verdict` 决策表逐行核对**（`memory.py:260-288`，7 行全部正确）：
  1. nli None → clf_v（clf 单判，新增对称回退）✓
  2. clf None → nli_v（nli 单判 = 现状零回归）✓
  3. 双 contradiction → "contradiction" ✓
  4. 单 contradiction → "conflict_hint"（两种方向）✓
  5. 双非矛盾 → nli 标签 ✓
  6. 双 None → None（首分支自然返回 clf_v=None）✓
- **`_judge_conflict` dual 分支**（`memory.py:601-620`）：clf 先行 load 短路（False → warning + clf_v=None 不白等 nli）→ nli 次行（20s 超时内建）→ `dual_verdict`。降级路径全覆盖：clf load False / clf predict None / clf 异常 / nli 异常 / nli None / 双 None 全有测试覆盖（TestJudgeConflictDual 9 项全 mock）✓
- **存量分支逐字不动**：diff 确认 clf/nli 分支零改动，存量 5 项断言全绿（AC-7）✓
- **`_merge_duplicate`**（`memory.py:558-562`）：conflict_hint elif 仅打 info 日志后落入追加分支，superseded 不标、条数不涨（AC-2）；TestMergeConflictHint 断言 content 拼接 + superseded False + 日志 ✓
- **config**：`Literal["clf","nli","dual"] = "dual"`（`config.py:213`）；非法值 pydantic 启动拒绝（AC-16）；PW_MEMORY_CONFLICT_JUDGE 回退保留 ✓
- **AC-15 空输入**：`memory_conflict_clf.py:190` 与 `nli_judge.py:82` 均有 `strip()` 空守卫返回 None ✓
- **conftest 零改动** ✓

### WP-C：回归 + 文档收口 — ✅ 通过

- 全量 1152/0 独立复跑确认（225.80s）；新增 10 项全 mock hermetic ✓
- changelog：对比表 + 选择 + 理由 + 措辞去重记录 + conflict_hint 口径声明 + 诚实边界（单次快照 / AND Recall 数学性质 / 未达完整门槛但启用判据按 module-062 规则已满足）✓
- CONTEXT.md 只增不删（备份 %TEMP% 先行）✓；METRICS.md 待办③ 完成 ✓；ADR-0007 状态行 ✓；三记忆文件 ✓（§五 1 项陈旧见下）

## 三、发现（非阻塞 LOW/minor，已附证据）

| # | 文件 | 位置 | 问题描述 | 建议 |
|---|------|------|----------|------|
| 1 | memory/file-index.md L158 + changelog §五 | "70→80 项"/"80 项全部 passed" | **测试数口径偏 2**：HEAD 基线实测 72 个 `def test_`（非 70），现文件 82（+10 增量正确）。"70→80" 两处数字应 72→82 | 后续模块顺手修正两处数字 |
| 2 | ai_service/eval/datasets/memory_conflict_dataset.py | L501 `scores["judge"] = args.judge` | **fixture 落库标签失真**：`--fixture`（或 `--fixture --judge dual`）落库时 judge 字段记的是 `args.judge` 默认值（"nli"/"dual"）而非 "fixture"——新字段引入前 fixture 行无 judge 字段可混淆，现字段反而固化误标（无害但失真） | fixture 分支把 judge 字段标为 "fixture"，或 fixture 默认强制 --no-save 声明 |
| 3 | ai_service/eval/datasets/memory_conflict_dataset.py | L183-184 样本 + id=48 fp 实证 | **双判唯一 fp 样本标注存疑**："用户感觉嵌入式方向更好 \| 用户觉得原专业方向有优势"（标注 entailment）——两个独立裁判（mDeBERTa + bge-m3+LR）均判 contradiction，人类视角两句亦可读作互斥偏好；非 4 条用户确认边界陷阱，可复核。即使改标 neutral/contradiction，dual P 0.9412→0.8889/1.0000，"dual 默认"决策结论不变 | 入标注复核 backlog（与 4 条边界陷阱同批观察） |
| 4 | ai_service/eval/datasets/memory_conflict_dataset.py | L349-354 | eval `dual_judge` clf load 返回 False 时**无 warning 日志**（生产 `_judge_conflict` 同场景有 warning），仅静默单判回退——故障可观测性略弱 | 补一行 warning（对齐生产分支） |
| 5 | memory/project-context.md | §5 当前迭代状态 L103 | 仍为 "v0.69.0（module-069 Reviewer Pass，待 Tester）"——未更新到 v0.70.0（模块表行已更新，仅此节陈旧） | 本报告产出时顺带修正为 v0.70.0 |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| 存量测试零改动（改了=FAIL） | git diff tests/ 仅 test_memory_evolution2.py 追加 10 项；conftest 零 diff | ✅ |
| 4 条边界陷阱 verdict 不可改 | 数据集 L206-213 逐条核对 verdict=neutral 保持 | ✅ |
| 判定器确定性优先 | dual_verdict 纯函数 + 双模型推理零 LLM；eval 引用生产单一来源 | ✅ |
| 其他模块一律不碰 | git status 仅 9 文件，全部在 plan 涉及清单内 | ✅ |
| 无新 ADR / 无新依赖 / 无新表 | requirements/database/schema 零 diff | ✅ |
| CONTEXT.md 只增不删 | diff +10 行纯追加 | ✅ |

## 五、架构与代码质量评估

- **单一来源防漂移**：`dual_verdict` 模块级纯函数（`memory.py:260-288`）为共识唯一真源，生产 `_judge_conflict` 与 eval `dual_judge` 均引用——7 行决策表 docstring 与实现逐字吻合，AC-23 达成 ✓
- **降级哲学对齐**：clf 先行短路 + 全 try/except → None + fail-open，与 module-061/062 factcheck_judge/nli_judge 模式一致；clf 缺失环境 dual 自动 = judge="nli" 现状行为（零回归，新环境无需先训练 clf）✓
- **行数**：功能代码 ≈ 90 行（dual_verdict ~29 + dual 分支 ~20 + 日志 ~5 + config ~7 + eval ~30），远低于 AC-22 ≤200 上限 ✓
- **分层/依赖**：纯 Python 侧函数内 import 延迟加载哲学保持；无跨层/反向依赖；无新依赖 ✓
- **安全**：无新注入面（无 SQL/无网络）；日志无敏感信息；判定输入为记忆文本（内部数据）✓

## 六、结论

**✅ PASS（进 Tester）**。WP-A~C 全部通过标准达成：
- 三方案 70 条真实跑分 eval_runs id=46/47/48 与 changelog 逐字一致（DB 直查），AND 共识逐样本生效（nli fp=2 → dual fp=1）——"nli 1.0 假象"与"clf 人造分布缩水"均被 70 条真实口径证实，默认值改 "dual" 为数据驱动决策（不预设结论），理由链完整
- `dual_verdict` 7 行决策表逐行核对正确；降级路径全覆盖（clf load False/predict None/异常、nli None/异常、双 None）；存量 clf/nli 分支逐字不动
- 存量测试零改动红线守住（conftest 零 diff、TestJudgeConflictDispatch 5 项逐字）；全量 1152/0 独立复跑确认
- 文档收口完整（changelog 对比表 + CONTEXT.md 只增不删 + METRICS.md 待办③ + ADR-0007 + 三记忆文件）

§三 5 项 LOW/minor 均为文档数字口径 / eval 标签边缘 / 标注复核观察，不阻塞 Tester 验收；建议在后续模块顺手修正（#1 数字口径、#2 fixture 标签、#4 eval 日志），#3 入标注复核 backlog，#5 本报告已随附修正。
