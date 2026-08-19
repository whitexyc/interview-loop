# Module-071 测试报告 — 幻觉检测 kappa 校准（阈值扫描 + 标注集扩充 + 达标决策）

> Tester：2026-08-18 | 验收基线：plan.md / acceptance-criteria.md / changelog.md / review-report.md
> Review 结论：✅ Pass（第 2 轮复审，2 项 mustFix 已修复为 docs-only 修正轮，见 review-report.md §七）
> **验收结论：✅ 通过（全部 AC 达成；重跑 kappa 0.2981 < 0.7 不达标但如实记录、不改生产配置——AC-15 降级行为即验收要求）**

## 一、全量测试（Tester 独立复跑）

| 项目 | 结果 |
|------|------|
| 全量 pytest（Tester 独立复跑） | **1183 passed / 0 failed（206.37s，147 warnings）** = 1182 基线 + 1 新增（本模块基线 1163 + 19 新增 = 1182，与 changelog/Reviewer 复跑一致） |
| 新增单测 | `tests/eval/test_factcheck_judge.py` **58 项全绿**（57 存量 + 19 Developer 新增 + 1 Tester 新增） |
| Tester 新增 1 项 | `test_dataset_inferred_calibration_change_list`（inferred 口径变更清单回归锁，见 §二） |
| 存量测试改动 | **仅验收许可例外 1 处**（git diff 逐 hunk 核对）：`test_dataset_structure_50_three_classes` → `test_dataset_structure_100_three_classes`（重命名 + 断言更新，plan §WP-B + AC-17 明示，module-061/062 先例）；其余测试文件仅新增行 |
| 红线模块 | `factcheck_judge.py` / `reflector.py` / `src/config.py` / `tests/conftest.py` **git diff 为空**（AC-18） |
| 单测 mock 性 | 全 mock 不依赖真实模型/LLM/DB（fixture 模式本身零依赖，冒烟通过） |
| warnings | 与基线同源（sklearn UndefinedMetricWarning / SQLAlchemy / Redis 弃用），非本模块引入 |

## 二、新增单测抽查（按任务清单 5 项逐项核对）

| 任务项 | 覆盖点 | 结果 | 依据 |
|--------|--------|------|------|
| 1. max_score_to_verdict 三态边界 | ==high→supported / ==low→inferred / 区间→inferred / 低于 low→unsupported / 0.0 边界 | ✅ | TestMaxScoreToVerdict 7 项（test_above_high / test_equal_high / test_between_low_and_high / test_equal_low / test_below_low / test_zero_score + judge_factcheck 引用唯一实现） |
| 2. scan_thresholds 25 组后处理 | 25 行全输出 + 降序 + 最优规则写死 + **mock judge 调用次数==样本数（分数只算一次回归锁）** + skipped 排除 + 空输入/全 None | ✅ | TestScanThresholds 8 项（test_full_grid_25_rows_and_sorted / test_no_extra_judge_calls_score_once：run_eval 后 calls==5 不增 / test_best_combo_follows_written_rule / test_empty_input / test_all_none_scores_empty_table / test_apply_threshold_overrides / test_scan_cli_rejects_fixture / test_record_scan_run_contract） |
| 3. --fixture + --scan-thresholds 报错 | 组合显式 SystemExit（parser.error） | ✅ | test_scan_cli_rejects_fixture |
| 4. 标注集 100+ 结构校验 | ≥100 / 三类齐全 / keywords 非空 / question 唯一 / part 字段 + JSON 缺失/过小/重复/空 keywords → ValueError | ✅ | test_dataset_structure_100_three_classes（断言 136 = 57/20/59 精确分布）+ test_load_dataset_rejects_* 4 项 |
| 5. inferred 口径变更清单 | INFERRED_SAMPLES 保持 2 + 改判 8（具名）/ real neutral 改判 3 + contradiction 2 / 去重保留 real 版 / part×label 交叉计数与 changelog §六 记账封闭 | ✅ | **Tester 新增 test_dataset_inferred_calibration_change_list**（1 项）：① 保持集 = 线程池四种拒绝策略 + Redis 哨兵故障转移；改判集 = G1 调优/Kafka 生产者/联合索引/Spring AOP/Netty 粘包/JWT 刷新/CAS ABA/HashMap 扩容 8 条具名断言；② real_retrieval unsupported 5 条具名（3 neutral 改判 + 2 contradiction）；③ 联合索引在最终集 = (supported, real_retrieval)；④ 交叉计数 {sufficiency 48/47, constructed 10/7, real_retrieval 9/10/5} = 136 封闭——Review 修复② docstring 记账数字的实证底座 |

## 三、真实重跑（Tester 独立执行，未采信 changelog 数字）

### 3.1 真实 HHEM 重跑（136 条新标注集 + WP-A/WP-C 最优阈值 0.65/0.35，CPU 438MB 本地模型）

```
Dataset: 136 | Evaluated: 136 | Skipped: 0
Thresholds: high=0.65 low=0.35
Cohen's kappa (三态): 0.2981
Cohen's kappa (二值 supported-vs-rest): 0.3701
==> 门槛判定: 三态 kappa 0.2981 < 0.7 未达门槛，如实标注（阈值/标注集可校准，不伪造数字）
```

- 与 changelog §三（eval_runs id=50/51）**逐字一致**：三态 0.2981 / 二值 0.3701 / 136/136 全评估零 skipped（HHEM 确定性，无 LLM 波动）。
- 误判明细独立核对：inferred 判 supported 含 ConcurrentHashMap 扩容 0.653、Kafka ISR 0.964、RocketMQ 0.924 等，判 unsupported 含 JWT vs Session 0.071、Kafka Rebalance 0.286、MyBatis 0.059 等——与 DB id=50 逐条对上。

### 3.2 DB 独立直查（Tester 独立 SELECT，未采信 changelog）

| 验证项 | 证据 | 结果 |
|--------|------|------|
| 基线行 | eval_runs id=15：kappa3=0.3252 @ 0.7/0.3（module-051 基线） | ✓ |
| 重跑行 | id=50/51：kappa3=0.2981 @ 0.65/0.35，两行逐字一致（确定性复跑） | ✓ 与 changelog 一致 |
| 扫描行 | id=49（旧 50 集）+ id=52（新 136 集），`factcheck_scan` 恰好各 1 行，零 25 行噪音（AC-5） | ✓ |
| id=52 新集扫描 | best = high=0.65 low=0.40 kappa3=0.3309 / kappa2=0.3701 / acc=0.5809，table 25 行 | ✓ 与 changelog 一致（最优随标注集移动 0.65/0.35→0.65/0.40） |
| **mustFix ① 复核**（inferred 混淆分解 10/5） | id=50 per_question 按 label=inferred 逐条重映射（0.65/0.35）：**判 supported 10**（含补列 Redis 哨兵 0.8222、ConcurrentHashMap 扩容 0.6532——实查分数一致）/ **判 unsupported 5**（含补列 JWT vs Session 0.0712、Kafka Rebalance 0.2863——实查一致）/ 判对 5；10+5+5=20 封闭 | ✓ 与 changelog §六修复后逐字一致 |
| 失败模式总数 | id=50 重映射统计：supported 误杀 24 / inferred 混淆 15 / unsupported 漏判 22 = 61 | ✓ 与 changelog 一致 |
| 配置未变 | `settings.verify_hhem_threshold_high/low` = **0.7 / 0.3**（AC-6/AC-14 不达标分支零改动） | ✓ |
| 测试无污染 | Tester 运行后 eval_runs id>52 新增行数 = **0**（--no-save 生效） | ✓ |

### 3.3 fixture 冒烟（零模型/DB，Tester 独立运行）

```
Dataset: 136 | Evaluated: 136 | Skipped: 0
==> [fixture] 三态 kappa 0.8719（启发式，非真实指标），不构成 ADR-0010 P1-④ 门槛判定
Not saved to eval_runs
```

管线完整跑通（136 条全评估 + [fixture] 门槛措辞正确 + 不落库），与 Reviewer 冒烟一致。

## 四、实现抽查（与 changelog 一致）

| 项 | 抽查结果 |
|----|----------|
| max_score_to_verdict 单一来源 | golden_factcheck.py L92-110 三态映射唯一实现，judge_factcheck（L390-410）+ scan_thresholds（L445-486）双引用，与 reflector.py `_judge_by_hhem` 逐字同口径（>= 含等号） | ✓ |
| scan_thresholds 纯后处理 | 只消费 label + max_score（None 跳过）；25 组零模型调用（回归锁单测 + 真实 evaluated=136 一次推理） | ✓ |
| 数据集结构 | build_factcheck_dataset() = 136（57/20/59）；parts {sufficiency 95, real_retrieval 24, constructed 17}；question 唯一强制 | ✓ |
| mustFix ② docstring | golden_factcheck.py 模块 docstring 数据集构成 = 实际 57/20/59（48+9 / 2+10+8 / 47+2+7+3，136 封闭）；与代码/测试断言一致 | ✓ |
| 旧数字残留 | 全库 grep `12/3` / `判 supported 12` / `55/24` / `inferred 24` = **零残留**（.md 全量） | ✓ |
| CONTEXT.md 只增不删 | git diff 删行 = 0（纯新增）；TEMP 备份存在 `CONTEXT.md.backup-module071-20260818-223621.md`（AC-25） | ✓ |
| METRICS.md | 6 行删除均为幻觉检测节旧 50 题表格 + 待办 #2 旧行的许可更新（替换为 136 题新数字 0.2981/0.3309 + 10/5 失败模式行，AC-26） | ✓ |
| 红线零改动 | factcheck_judge / reflector / config / conftest git diff 为空（AC-18） | ✓ |

## 五、AC 逐条对照（28 项）

| AC 项 | 结果 | 依据 |
|-------|------|------|
| AC-1 三态映射纯函数 | ✅ | TestMaxScoreToVerdict 7 项（==high/==low/区间/低于 low/0.0），与生产逐字同口径 |
| AC-2 扫描 25 组全输出 | ✅ | 单测 25 行降序 + DB id=52 实查 25 行对照表 + best 0.65/0.40 |
| AC-3 分数只算一次 | ✅ | 回归锁单测（calls==5 扫描后不增）+ 真实扫描 evaluated 一次推理 |
| AC-4 skipped 不参与 + fixture 报错 | ✅ | 单测（全 None→[] / SystemExit）+ 实跑 skipped=0 |
| AC-5 落库单行 | ✅ | DB 实查 factcheck_scan 恰 2 行（id=49/52）；--no-save 生效 |
| AC-6 不改生产配置 | ✅ | config 0.7/0.3 保持；最优 0.65/0.35 记录入 changelog |
| AC-7 数据集 100+ 结构校验 | ✅ | 136 条 57/20/59、三类齐全、keywords 非空、question 唯一、part 三来源；load 校验全 ValueError |
| AC-8 JSON 缺失报错 | ✅ | test_load_dataset_rejects_missing_json（monkeypatch 路径） |
| AC-9 标注指南落盘 | ✅ | factcheck_annotation_guide.md 三态定义写死（inferred 部分覆盖边界 + 相关背景≠支持 + 矛盾→unsupported） |
| AC-10 存量复核 + 变更清单 | ✅ | **Tester 新增回归锁单测**具名钉死 2 保持/8 改判 + 3 neutral 改判 + 去重保留语义；changelog 清单可审计 |
| AC-11 真实样本可溯源 | ✅ | 24 条 part=real_retrieval（claim=真实 LLM 答案句子 + doc=DB 检索片段），与 sufficiency 代理可区分 |
| AC-12 阈值覆盖生效 | ✅ | test_apply_threshold_overrides + test_judge_factcheck_uses_pure_mapping + 实跑落库 thresholds={0.65, 0.35} |
| AC-13 重跑数字落库 | ✅ | id=50/51 实查 kappa3=0.2981 与 changelog 一致；Tester 独立重跑同值 |
| AC-14 达标改生产配置 | ✅（不适用） | 未达标分支，config 未动 |
| AC-15 不达标如实标注 | ✅ | changelog 新数字 + 失败模式分类（61 = 24/15/22，inferred 分解 10/5/5 经 DB 实证修正）+ backlog 入册不隐藏 |
| AC-16 全量基线全绿 | ✅ | Tester 独立复跑 **1183/0**（1163 基线 + 19 新增 + 1 Tester 新增） |
| AC-17 存量测试零改动（明示例外） | ✅ | diff 逐 hunk：唯一改动 = 结构断言测试重命名更新（许可）；borrows_from_sufficiency 未改仍绿 |
| AC-18 红线模块零改动 | ✅ | factcheck_judge / reflector / config / conftest 零 diff |
| AC-19 conftest 钉旧值 | ✅（不适用） | 配置未变，test_run_eval_end_to_end 的 ==0.7 断言天然仍绿 |
| AC-20 扫描成本 | ✅ | 136 条一次推理 + 纯 CPU 后处理 < 1s（扫描落库完整完成） |
| AC-21 代码量 ≤ 200 行 | ✅ | 功能代码 ~176 行（Reviewer 实测口径），超出 plan 预估但 ≤ 上限 |
| AC-22 单一来源 | ✅ | max_score_to_verdict 唯一实现双引用 |
| AC-23 无新依赖无新表 | ✅ | requirements 零改动；eval_runs 复用 |
| AC-24 changelog | ✅ | 25 组对照表（DB 逐字核对）+ 变更清单 + 重跑数字 + 决策 + 诚实边界 4 条 |
| AC-25 CONTEXT.md 只增不删 | ✅ | diff 删行 0 + TEMP 备份存在 |
| AC-26 METRICS.md | ✅ | 幻觉检测节 136 题新数字 + 待办 #2 如实更新（10/5 口径） |
| AC-27 ADR-0010 | ✅ | P1-④ 状态行补 module-071 结果（Reviewer grep 核查） |
| AC-28 三记忆文件 | ✅ | project-context / file-index / agent-activity-log 已更新（Reviewer 核查） |

**合计：28 项全部通过（AC-14/19 不适用分支按通过计）；核心指标三态 kappa 0.2981 < 0.7 未达标——但 AC-15 要求的"不达标如实标注、不改配置、入 backlog"全部落实，即模块验收目标达成。**

## 六、观察与诚实声明（非阻塞）

1. **Tester 新增 1 项单测**（`test_dataset_inferred_calibration_change_list`）：本轮为 Review 文档修正轮（Developer newTests=0），任务清单 5 项中前 4 项已由 WP-D 19 项新增覆盖，第 5 项（inferred 口径变更清单）缺回归锁——Tester 补 1 项，全量 1182 → 1183。
2. **mustFix ① 独立实证**：inferred 混淆分解 12/3 → 10/5 的修复经 DB id=50 per_question 逐条重算确认（10 supported / 5 unsupported / 5 判对，含 4 条补列样本分数逐字一致）——修复真实，非文档自洽。
3. **mustFix ② 独立实证**：docstring 57/20/59 记账 = part×label 交叉计数（48+9 / 2+10+8 / 47+2+7+3 = 136）与 Tester 新增单测双向锁定——修复真实。
4. **决策维持不达标**：重跑 0.2981 < 0.7，config 0.7/0.3 零改动；新集最优 0.65/0.40（0.3309）仅参考记录（阈值对标注集敏感，changelog 诚实边界声明成立）。
5. **Tester 无新增发现**：Reviewer 2 项 LOW（docstring 诚实边界"50 条"过期、activity-log [CODE] 行 12 条过期）经复核——LOW #5 已在 docstring L57"module-071 扩至 136 条"修订，LOW #6 已订正为 10/5，均非阻塞。

## 七、结论

**验收通过。** 关键验证点：
1. 全量 **1183/0** 全绿（Tester 独立复跑 206.37s），存量测试唯一改动在验收许可清单内（结构断言测试重命名更新），红线四文件零 diff；
2. 任务清单 5 项全部有单测覆盖（4 项 Developer 19 项新增 + 1 项 Tester 补充变更清单回归锁），全 mock 零真实模型；
3. **真实 HHEM 重跑**（136 条 @ 0.65/0.35，CPU）：三态 kappa **0.2981** / 二值 0.3701，与 changelog/DB id=50/51 逐字一致；
4. DB 独立直查：id=49/50/51/52 全部关键数字（含 mustFix ① 10/5 分解、id=52 最优 0.65/0.40 = 0.3309）与 changelog 逐字吻合，factcheck_scan 单行落库无噪音；
5. **不达标如实记录**：0.2981 < 0.7 → 不改生产配置（0.7/0.3 保持），失败模式分类 61 条入 backlog，诚实边界 4 条声明——AC-15 降级行为完整落实；
6. 文档收口：CONTEXT.md 只增不删（TEMP 备份在）+ METRICS/ADR/记忆三文件全更新，全库无旧数字残留。

**模块状态：✅ 验收通过（待 Developer 提交推送后 team-lead 收口）**
