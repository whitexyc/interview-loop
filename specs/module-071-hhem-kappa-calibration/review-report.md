# Module-071 审查报告 — 幻觉检测 kappa 校准（阈值扫描 + 标注集扩充 + 达标决策）

> Reviewer：2026-08-18 | 对照 `acceptance-criteria.md`（28 项 AC）+ `plan.md` + ADR-0010 P1-④ 逐项核查
> 结论：**✅ 通过（PASS，进 Tester）**——第一轮 CONDITIONAL 的 2 项 mustFix 已于第二轮复审逐项验证修复（DB 证据），docs-only 修正轮零逻辑改动

## 一、独立验证（不采信 changelog 数字，逐项实测/查库）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 全量 pytest | 独立复跑 `python -m pytest tests/ -q` | **1182 passed / 0 failed（201.70s）** 与 changelog 一致（1163 基线 + 19 新增） |
| 单测文件 | 独立复跑 `python -m pytest tests/eval/test_factcheck_judge.py -q` | **57 passed**（38 存量 + 19 新增） |
| 数据集结构 | `load_factcheck_dataset()` 独立调用 | **136 条**，counts `{supported: 57, inferred: 20, unsupported: 59}` 与测试断言逐字一致；parts `{real_retrieval: 24, sufficiency: 95, constructed: 17}`（去重移除 6 条 = changelog 清单 G1×2/AQS/联合索引/synchronized/ZGC ✓） |
| 生产配置未变 | `settings.verify_hhem_threshold_high/low` | **0.7 / 0.3**（不达标分支 config 零改动 ✓） |
| DB id=49（旧 50 集扫描） | 直查 + 从 per_question 独立重算 | best=0.65/0.35 kappa3=0.3711 / kappa2=0.3697 / acc=0.60；0.7/0.3=0.3252（与 module-051 基线逐字一致）；**25 行对照表与 changelog 表格逐字一致（全 25 组核对）** |
| DB id=50/51（新 136 集重跑） | 直查 + 从 per_question 独立重算 | kappa3=**0.2981** / kappa2=0.3701 / acc=0.5515，thresholds={0.65, 0.35}；id=50/51 两行逐字一致（确定性复跑 ✓）；独立重算同值 ✓ |
| DB id=52（新集扫描） | 直查 + 独立重算 | best=0.65/0.40 kappa3=**0.3309** / kappa2=0.3701；全网格最优随标注集移动（0.65/0.35→0.65/0.40）声明成立 ✓ |
| 落库单行 | 直查 `eval_type='factcheck_scan'` 计数 | **恰好 2 行**（id=49 旧集 + id=52 新集），单次扫描 1 行无 25 行噪音 ✓ |
| 失败模式分类（总数） | 从 id=50 per_question 按 0.65/0.35 重映射统计 | supported 误杀 24 / inferred 混淆 15 / unsupported 漏判 22 = 61 条，**总数与 changelog 一致**；但 **inferred 混淆内部分解 10 supported + 5 unsupported ≠ changelog 声称的 12 + 3**（见 §三 发现 #1，mustFix） |
| 三态映射同口径 | reflector.py `_judge_by_hhem` L580-585 逐行比对 | `>=high→supported / >=low→inferred / else→unsupported` 与 `max_score_to_verdict` 逐字一致（含等号边界）✓ |
| 分数只算一次 | 单测 `test_no_extra_judge_calls_score_once`（mock 断言调用次数==样本数，扫描后不增）+ 真实 id=49（evaluated=50，25 组纯后处理） | ✓ |
| fixture 冒烟 | `--fixture --no-save` 独立运行 | 管线完整跑通（启发式判定 + 报告 + 不落库）✓ |
| 红线零改动 | git status + git diff | `factcheck_judge.py` / `reflector.py` / `src/config.py` / `tests/conftest.py` / 其他模块 **零 diff** ✓ |
| 存量测试零改动 | git diff tests/ 逐 hunk 核对 | 唯一改动 = `test_dataset_structure_50_three_classes` → `test_dataset_structure_100_three_classes`（验收许可，module-061/062 先例）；`test_dataset_borrows_from_sufficiency` 未改仍绿 ✓ |
| CONTEXT.md 只增不删 | diff 核查 | 末尾 +9 行纯新增，零删行 ✓ |
| METRICS.md | diff 核查 | 幻觉检测节 136 题表（0.2981 + 旧基线）+ 待办 #2 划除如实更新 ✓ |
| ADR-0010 | grep 核查 | P1-④ 状态行含 module-071 校准结果（0.2981 / 0.3309 / 0.3711 + 失败模式总数）✓ |
| 三记忆文件 | 读 project-context / file-index / agent-activity-log | module-071 行 + §5 进行中 + file-index 条目 + [PLAN]/[CODE] 行全在 ✓ |

## 二、WP 逐项核对（28 项 AC）

### WP-A：阈值校准扫描 — ✅ 通过（AC-1~6 全过）

- **AC-1 三态映射唯一实现**：`max_score_to_verdict`（golden_factcheck.py:88-106）边界语义与生产 `_judge_by_hhem`（reflector.py:580-585）逐字一致（>= 含等号）；`judge_factcheck`（L386-406）重构引用之，与旧 inline 映射逐字节等价（diff 确认）；boundary 单测 7 项（==high/==low/区间/低于 low/0.0）✓
- **AC-2 25 组全输出**：`scan_thresholds`（L441-482）SCAN_HIGHS/LOWS 5×5 网格；独立重算 25 行与 changelog 对照表**全 25 组逐字一致**；按三态 kappa 降序（并列二值→贴近 0.7/0.3 规则写死，L477-481）✓
- **AC-3 分数只算一次**：mock 回归锁单测断言 judge 调用次数 == 样本数且扫描后不增 ✓；真实扫描 evaluated=50 一次推理 ✓
- **AC-4 skipped 不参与**：`scan_thresholds` 过滤 max_score=None（L462）；全 None/空输入 → []；`--fixture + --scan-thresholds` `parser.error` 显式报错（L705-706，单测 SystemExit 断言）✓
- **AC-5 落库单行**：`record_scan_run`（L577-603）eval_type='factcheck_scan' 单行，scores 含 table/best/thresholds_used；`--no-save` 生效；DB 实测 factcheck_scan 恰 2 行 ✓
- **AC-6 不改生产配置**：config 0.7/0.3 保持；最优 0.65/0.35 记录入 changelog ✓

### WP-B：标注集扩充 + 口径重写 — ✅ 通过（AC-7~11 全过）

- **AC-7 100+ 结构校验**：136 条（57/20/59）；三类齐全、keywords 非空、question 唯一、part ∈ 三来源，独立调用验证全部通过；load 校验（L335-365）<100/重复/空 keywords/空 documents/非三态/缺类全 ValueError ✓
- **AC-8 JSON 缺失报错**：`load_factcheck_real_samples`（L268-271）文件缺失 ValueError，单测 monkeypatch 验证 ✓
- **AC-9 标注指南**：factcheck_annotation_guide.md 三态定义写死（inferred"部分覆盖"：≥1 核心断言被**直接**支持 + ≥1 未覆盖且无冲突；"相关背景≠支持"；矛盾→unsupported）；note 核心断言拆解要求 ✓
- **AC-10 存量复核 + 变更清单**：INFERRED_SAMPLES 10 条（2 保持 + 8 改判）+ real neutral 3 条改判，共 11 条变更清单（样本/旧→新/理由）入 changelog；独立核对 INFERRED_SAMPLES 代码内 label 与清单一致 ✓
- **AC-11 真实样本可溯源**：factcheck_real_samples.json 24 条 `part=real_retrieval`（claim 真实 LLM 答案句子 + doc=DB 检索片段，与 sufficiency 代理可区分）；meta.note 注明来源与复核口径 ✓

### WP-C：重跑 + 决策 — ✅ 通过（AC-12~15 全过，数字经独立重算确认）

- **AC-12 阈值覆盖生效**：`apply_threshold_overrides` + judge 每调用读 settings；单测两覆盖路径 ✓；**真实运行实证**：id=50/51 落库 thresholds={0.65, 0.35} ✓
- **AC-13 重跑数字落库**：id=50/51 eval_type='factcheck'，kappa3=0.2981 与 changelog 一致（独立重算同值）✓
- **AC-14 达标改配置**：不适用——未达标分支（0.2981 < 0.7），config 未动 ✓
- **AC-15 不达标如实标注**：changelog 如实记录新数字 + 失败模式分类（61 条总数独立重算一致）+ 入 backlog（中文专用 NLI/微调、两阶段拆句+保守门控、飞轮数据定向补样本）；诚实边界 4 条（混合口径/阈值对标注集敏感需复扫/单方标注/确定性复跑）✓ — **但 inferred 混淆的内部分解数字有误（见 §三 发现 #1，mustFix）**

### WP-D：回归 + 文档收口 — ⚠️ CONDITIONAL（AC-16~28 全过，发现 #1/#2 例外）

- **AC-16 全量基线**：独立复跑 **1182/0** ✓（1163 基线 + 19 新增）
- **AC-17 存量测试零改动（明示例外）**：diff 逐 hunk 核对——唯一存量改动 = 结构断言测试重命名更新（验收许可）；`test_dataset_borrows_from_sufficiency` 未改仍绿 ✓
- **AC-18 红线模块零改动**：factcheck_judge / reflector 逻辑 / config / conftest / 其他模块 git diff 为空 ✓
- **AC-19 conftest 钉旧值**：不适用（配置未变，test_run_eval_end_to_end 的 `== 0.7` 断言天然仍绿）✓
- **AC-20 扫描成本**：50 条一次推理 + 纯 CPU 后处理（实测扫描落库完整完成）✓
- **AC-21 代码量**：功能代码（不含注释/docstring/数据 note）约 ~176 行 ≤ 200 ✓（超出 plan 预估 ~110 行约 60%，不阻塞，见 §三 发现 #4）
- **AC-22 单一来源**：max_score_to_verdict 唯一实现，judge_factcheck + scan_thresholds 均引用 ✓
- **AC-23 无新依赖无新表**：requirements 零改动；eval_runs 复用 ✓
- **AC-24 changelog**：25 组对照表（与 DB 逐字一致）+ 变更清单 11 条 + 重跑数字 + 决策 + 诚实边界 ✓（失败模式分解数字待修正，见发现 #1）
- **AC-25 CONTEXT.md 只增不删**：diff 纯新增 ✓
- **AC-26 METRICS.md**：幻觉检测节 136 题表 + 待办 #2 划除如实更新 ✓
- **AC-27 ADR-0010**：P1-④ 状态行补 module-071 结果 ✓
- **AC-28 三记忆文件**：project-context / file-index / agent-activity-log 全更新 ✓

## 三、发现

### 3.1 阻塞问题（mustFix）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | specs/module-071-hhem-kappa-calibration/changelog.md §三（失败模式分类段） | 约 L126-128（"inferred 混淆 15/20"段） | **inferred 混淆内部分解数字与 DB 不符**：声称"HHEM 把部分覆盖判成 supported **12 条** + 判 unsupported **3 条**"，且列出的判 supported 清单（Kafka ISR/RocketMQ/1.7vs1.8/AOF/EventLoop/redo log/Docker/RSet 8 条）+ 判 unsupported 清单（MyBatis/Seata/Kafka 消费者组 3 条）。按 eval_runs id=50 落库 per_question 以 0.65/0.35（任意口径 0.7/0.3、0.65/0.40 亦然）重算：**判 supported 实为 10 条、判 unsupported 实为 5 条**。清单漏列 2 条判 supported（Redis 哨兵 0.822、ConcurrentHashMap 扩容 0.653）与 2 条判 unsupported（JWT vs Session 0.071、Kafka Rebalance 0.286）。总数 15 正确，但分解与样本清单错误。**该数字同步进入了 METRICS.md 幻觉检测节与 CONTEXT.md module-071 段**（"判 supported 12 条"），需一并修正 | 高 | 按 DB 证据改 12→10、3→5，补全样本清单（或注明统计口径），并同步 METRICS.md + CONTEXT.md（只增不删——修订既有行的数字属于行内更正，不删行） |
| 2 | ai_service/eval/golden/golden_factcheck.py | 模块 docstring L20-32（数据集构成段） | **模块 docstring 数据集构成描述与实际不符**：声称 "unsupported **55 条**：不充分前 50（去重后 49）+ contradiction 2 + 改判的 **6** 条"（实为 59 = 50-4 去重 + 2 contradiction + 8 INFERRED 改判 + 3 neutral 改判）、"inferred **24 条**：保持 **3** 条 + neutral **13** 条 + 构造 8 条"（实为 20 = 保持 2 + neutral 保持 10 + 构造 8）；且 docstring 自述算术 57+55+24=138≠136、49+2+6=57≠55。与测试断言 `counts == {57, 20, 59}` 直接矛盾 | 中 | 按实际 57/20/59 与变更清单重写 docstring 数据集构成段（保持 2/改判 8、neutral 保持 10/改判 3、去重移除 6 条） |

### 3.2 建议改进（不阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 3 | specs/module-071-hhem-kappa-calibration/changelog.md | §五 顶部 | 声称"全量 pytest 基线 **1152/0**（module-070 验收数）"——1152 为 module-070 Reviewer 复跑数，Tester 实际验收为 **1163/0**（1163+19=1182 与实跑一致）；changelog 已声明"实跑以 WP-D 收集为准"故不构成错误，仅口径陈旧 | 低 | 顺手改为 1163/0 |
| 4 | ai_service/eval/golden/golden_factcheck.py | 新增功能代码整体 | 功能代码（不含注释/docstring）约 ~176 行，超 plan §WP-A~D 预估 ~110 行约 60%（主要增量在 build/load 扩展与 record_scan_run/print_scan_report） | 低 | 不阻塞，记录即可；后续模块预估可参考实际 |

## 四、红线核对（纪律项）

| 红线 | 核对 | 结果 |
|------|------|------|
| factcheck_judge.py（HHEM 推理路径）零改动 | git diff 为空 | ✅ |
| reflector.py 逻辑零改动 | git diff 为空（_judge_by_hhem 读 settings 自动生效，默认值未变） | ✅ |
| config.py 零改动（不达标分支） | git diff 为空 | ✅ |
| conftest.py 零改动（不达标分支无需钉值） | git diff 为空 | ✅ |
| 存量测试零改动（明示例外） | 仅结构断言测试按验收许可更新 | ✅ |
| 不引入 LLM-as-judge | 扫描/判定全确定性纯函数 + HHEM | ✅ |
| 判定器确定性优先 | max_score_to_verdict / scan_thresholds / kappa_metrics 全纯函数 | ✅ |

## 五、架构与代码质量评估

- **单一来源落实**：`max_score_to_verdict` 三态映射唯一实现，judge_factcheck 与 scan_thresholds 双引用，与生产反射逐字同口径——扫描与生产语义不可能漂移（AC-22 核心）✓
- **纯后处理纪律**：scan_thresholds 只消费 per_question.max_score，25 组零模型调用；回归锁单测 + 真实 evaluated=50 双重证实 ✓
- **数据完整性**：JSON 缺失/结构非法全 ValueError 不静默降级；question 唯一强制 + part 优先级去重可审计 ✓
- **分层**：纯评测侧改动，生产路径零触碰；无新依赖无新表 ✓
- **安全**：无密钥/无敏感数据；JSON 数据无注入面 ✓
- **诚实标注**：不达标如实记录（0.2981 < 0.7 不改配置）、失败模式入 backlog、诚实边界 4 条——决策规则执行符合 plan §WP-C 写死规则（Developer 无自由裁量），未预设成功 ✓

## 六、结论

**⚠️ CONDITIONAL（2 项 mustFix，修复后 PASS）**。WP-A/WP-B/WP-D 全部通过标准达成；WP-C 决策规则执行正确（0.2981 < 0.7 → 不改生产配置，如实标注入 backlog）；全量 1182/0 独立复跑确认；eval_runs id=49/50/51/52 DB 直查 + 从 per_question 独立重算与 changelog 全部关键数字逐字一致（25 组对照表全核对）；红线全守；测试文件唯一存量改动在验收许可清单内。

2 项 mustFix 均为**文档数字与 DB 证据不符**（本模块以"可审计/诚实"为核心价值，changelog 失败模式分解 12/3 vs 实算 10/5 及其样本清单缺漏、docstring 数据集构成 55/24 vs 实 59/20），均为纯文档修正、不涉及逻辑/数据/测试改动，Developer 修复后 Reviewer 快速复核即可进 Tester。建议改进 #3/#4 非阻塞。

---

## 七、第二轮复审（Review 修复后，2026-08-18）—— **✅ 通过（PASS，进 Tester）**

Developer 已按第一轮 mustFix ①/② 完成修复（changelog §六 + 变更记录 v2 行；docs-only 修正轮）。本轮独立验证（不采信 changelog，全部重跑/重查）：

| 验证项 | 方法 | 结果 |
|--------|------|------|
| **mustFix ① 修复**（inferred 混淆分解 12/3 → 10/5） | DB 直查 eval_runs id=50 per_question 按 label=inferred 逐条核对（20 条） | **判 supported 10 / 判 unsupported 5 / 判对 5** 与修复后 changelog §三逐字一致；具名样本与分数全部对上——判 supported 含补列的 **Redis 哨兵 0.822、ConcurrentHashMap 扩容 0.653**（实查 0.822/0.653 ✓），判 unsupported 含补列的 **JWT vs Session 0.071、Kafka Rebalance 0.286**（实查 0.071/0.286 ✓）；10+5+5=20 封闭 |
| METRICS/CONTEXT 同步 | grep 全库 `12/3` / `判 supported 12` / `55/24` 零残留（.md 全量） | METRICS 幻觉检测节 + CONTEXT module-071 段均为 10/5 口径 ✓ |
| **mustFix ② 修复**（docstring 55/24 → 57/20/59） | 读 golden_factcheck.py docstring（L19-36）+ 独立调 `build_factcheck_dataset()` 按 label×part 交叉核对 | docstring 构成 = 实查：supported 57 = sufficiency 48 + entailment 9；inferred 20 = 保持 2 + neutral 保持 10 + 构造 8；unsupported 59 = 不充分去重 3 实入 47 + contradiction 2 + INFERRED 改判去重 1 实入 7 + neutral 改判 3；57+20+59=136 ✓（原自述算术错误消除） |
| 去重保留语义 | 按 changelog 清单逐 question 查最终集 | G1/AQS/联合索引保留 real 版（supported/inferred/supported ✓）；synchronized/ZGC 保留 supported 版 ✓；总入 142 - 去重 6 = 136 ✓ |
| 代码零逻辑改动 | golden_factcheck.py 行号与第一轮全函数核对 | 全部函数相对第一轮均匀 +4 行位移（docstring 扩充所致），逻辑零改动 ✓ |
| 红线零改动 | git diff | factcheck_judge.py / reflector.py / config.py / conftest.py / 其他模块 **零 diff** ✓ |
| 单测 | `python -m pytest tests/eval/test_factcheck_judge.py -q` | **57 passed**（38 存量 + 19 新增）✓ |
| 数据集校验 | `load_factcheck_dataset()` | **136 条** 无异常 ✓ |
| 配置未变 | `settings.verify_hhem_threshold_high/low` | **0.7 / 0.3** ✓ |
| fixture 冒烟 | `python -m eval.golden.golden_factcheck --fixture --no-save` | 136 条全评估，管线跑通 ✓ |
| 全量回归 | `python -m pytest tests/ -q` 独立复跑 | **1182 passed / 0 failed（211.19s）** ✓（Developer 报 191.21s，环境波动；1163 基线 + 19 新增口径一致） |

### 7.1 新增发现（本轮）

| # | 文件 | 行号 | 问题描述 | 严重级别 |
|---|------|------|----------|----------|
| 5 | ai_service/eval/golden/golden_factcheck.py | 模块 docstring 诚实边界段（约 L56） | mustFix ② 修正了 docstring 数据集构成段，但**诚实边界段仍写"量级小（50 条）"**（module-051 遗留，数据集已 136 条）——数字过期 | 低（建议顺手改 50 → 136） |
| 6 | memory/agent-activity-log.md | module-071 Developer [CODE] 行（约 L273） | 记忆日志 [CODE] 行仍保留修复前"判 supported 12 条"数字（changelog/METRICS/CONTEXT 已改 10/5）——历史日志行数字过期 | 低（Reviewer 本轮记忆维护时已顺手订正为 10/5） |

第一轮 LOW #3（changelog 基线 1152/0 口径陈旧，有"以实跑为准"声明）/#4（功能代码 ~176 行超预估）维持非阻塞。

### 7.2 结论

**✅ PASS**。2 项 mustFix 均已按 DB 证据修复且全库无残留旧数字；修复为 docs-only（golden_factcheck.py 均匀 +4 行位移确认 docstring-only），红线文件零 diff；全量 1182/0 独立复跑通过；数据/决策零改动（三态 kappa 0.2981 < 0.7 不达标不改生产配置的结论保持）。2 项新 LOW（docstring 诚实边界 50 条过期、activity-log [CODE] 行 12 条过期）非阻塞，已记录并订正其一。**模块可进 Tester**。
