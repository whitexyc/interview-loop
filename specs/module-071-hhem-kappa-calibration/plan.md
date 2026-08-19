# 开发计划 — Module-071: 幻觉检测 kappa 校准（阈值扫描 + 标注集扩充 + 达标决策）

## Agent 配置

- Developer x1（后端 Python，改动集中在 golden_factcheck.py + 数据 JSON + 标注指南 + config + conftest + 单测）
- Reviewer x1
- Tester x1

## 1. 需求描述

- 需求来源: METRICS.md 待办 #2「幻觉检测 kappa 校准（<0.7 未达标）」（task-brief 2026-08-18）
- 功能描述: HHEM 裁判三态 kappa 0.3252 < 0.7 未达门槛（module-051）——裁判模型层面已穷尽（mDeBERTa 0.5167 / 句级拆解+86 条证伪 0.3754，module-054/057），剩余优化空间 = **阈值校准 + 标注口径 + 标注集扩充**。本轮：① 在现有 50 条上 25 组阈值网格扫描找最优（分数只算一次，纯后处理）；② 标注集扩到 100+ 条 + inferred"部分覆盖"口径重写（标注指南写死边界 + 变更清单）；③ 新集 + 最优阈值重跑，**达标（三态 kappa ≥ 0.7）才改生产配置**，不达标如实标注；④ 回归 + 文档收口
- 优先级: P1

## 2. 模块拆分

### WP-A: 阈值校准扫描（先量尺子——现有 50 条上找最优阈值）

**描述**: 在现有 50 条标注集上做 25 组阈值网格扫描（high ∈ {0.5, 0.55, 0.6, 0.65, 0.7} × low ∈ {0.2, 0.25, 0.3, 0.35, 0.4}），产出阈值-kappa 对照表（三态 kappa + 二值 kappa + Accuracy）。**HHEM 分数只算一次**——`run_eval` 已把每条样本的 `max_score` 存进 `per_question`（golden_factcheck.py:373 `"max_score": round(float(max_score), 4)`），扫描只是纯后处理映射，无需新增缓存层。

**预估代码量**: 功能代码 ~70 行（max_score_to_verdict ~8 + scan_thresholds ~35 + CLI ~25 + judge_factcheck 重构 ~2）

**涉及文件**:
- `ai_service/eval/golden/golden_factcheck.py`:
  - 新增纯函数 `max_score_to_verdict(max_score: float, high: float, low: float) -> str`——三态映射唯一实现（`>= high → supported / >= low → inferred / else → unsupported`，与 reflector.py:580-585 生产映射逐字同口径）；`judge_factcheck`（293-299 行 inline 映射）重构为引用之，行为零变化
  - 新增纯函数 `scan_thresholds(per_question: list[dict], highs: list[float], lows: list[float]) -> list[dict]`——只消费 `per_question` 的 `label` + `max_score`（max_score 为 None 的跳过，与 kappa_metrics 只算 evaluated 同口径），对 25 组 (high, low) 组合各跑一次 `kappa_metrics`，返回 `[{high, low, kappa_three_state, kappa_binary_supported_vs_rest, accuracy, evaluated}]` 按三态 kappa 降序
  - CLI 新增 `--scan-thresholds`：`run_eval` 一次（真实 HHEM，每条样本推理一次）→ `scan_thresholds` → 打印 25 行对照表 + 最优组合 + 门槛提示；落库 **1 行** eval_runs（`eval_type='factcheck_scan'`，scores 含完整对照表 + best + thresholds_used，per_question 带 max_score——对齐 module-057 benchmark_rrf_k 'rrf_k_scan' 单行先例，不落 25 行噪音）；`--no-save` 生效
  - CLI 新增 `--threshold-high X --threshold-low Y`：启动时覆盖 `settings.verify_hhem_threshold_high/low`（judge_factcheck 每次调用时读 settings，覆盖即时生效；单进程 CLI 无需还原）——WP-C 重跑复用
- `ai_service/tests/eval/test_factcheck_judge.py` — TestGoldenFactcheck 扩展（详见 WP-D）
- **不动**: `factcheck_judge.py`（HHEM 推理路径零改动红线）、`reflector.py`（本轮不改，WP-C 达标才动 config 默认值）

**依赖**: 无

**实现要点**:
1. `max_score_to_verdict` 边界语义（`>=` 含等号）与生产逐字一致——boundary 单测钉死（==high / ==low / 区间 / 低于 low）
2. **"分数只算一次"的回归锁**：单测 mock judge 断言调用次数 == 样本数（扫描逻辑本身零模型调用）；`--fixture + --scan-thresholds` 组合不允许（启发式判官不产生 max_score，扫描表为空——CLI 显式报错）
3. skipped 样本（model_unavailable/error，无 max_score）不参与扫描
4. 最优组合选择规则（写死防歧义）：三态 kappa 最高者；并列取二值 kappa 高者；再并列取更贴近生产现状 0.7/0.3 者
5. 通过标准: 25 组扫描跑完 + 对照表入 changelog + 最优组合记录；**不改生产配置**（等 WP-C 数据）
6. 诚实边界: 50 条小样本的最优阈值是"方向性"的，标注集扩充后 WP-C 复扫确认

### WP-B: 标注集扩充 + inferred 口径重写（修尺子）

**描述**: golden_factcheck 50 → 100+ 条。真实 claim 来源（已核实）：① `eval/datasets/real_retrieval_pairs.json` **24 条真实检索对**（claim = deepseek-v4-flash 真实答案句子，doc = DB golden 112 题 hybrid 检索 top 片段，verdict 已人工标注：entailment 9 / neutral 13 / contradiction 2）——转换路径已存在 `contradiction_dataset.to_factcheck_item()`（entailment→supported / neutral→inferred / contradiction→unsupported，与 module-052 三态映射一致）；② SUFFICIENCY_DATASET 剩余（充分 50 / 不充分 50，当前只用前 20+20 → **还有 30+30 可用**，代理标注口径不变）；③ 新人工构造 inferred 样本。**inferred 标注口径重写**（module-051 归因②：HHEM 对"部分覆盖"判一致偏乐观——标注指南里"部分覆盖"的边界定义要写死）+ 存量 inferred 样本复核 + 变更清单。

**预估代码量**: 功能代码 ~35 行 + 数据文件（JSON 非代码）

**涉及文件**:
- `ai_service/eval/datasets/factcheck_real_samples.json`（**新增**）: 真实 claim 样本固化——含 real_retrieval_pairs.json 转换（`to_factcheck_item` 口径，labels 换算后写入并标注 `part=real_retrieval`）+ 新构造 inferred（`part=constructed`）；字段 `{question, documents: [{title, content}], label, keywords, category, note, part}`——**keywords 必填**（fixture 启发式 `heuristic_judge(question, documents, keywords)` 依赖，缺失会 KeyError）
- `ai_service/eval/golden/golden_factcheck.py`:
  - `build_factcheck_dataset()` 扩展: SUFFICIENCY_DATASET `sufficient[:50]` / `insufficient[:50]`（原 [:20] 扩到可用上限）+ INFERRED_SAMPLES + load factcheck_real_samples.json（**文件缺失 → ValueError 明确报错**，数据入库仓库不走降级）
  - `load_factcheck_dataset()` 校验升级: ≥100 条 + 三类齐全 + keywords 非空
- `ai_service/eval/datasets/factcheck_annotation_guide.md`（**新增**，对齐 contradiction_annotation_guide.md 位置与命名）: 三态判定口径写死——
  - **supported**: 文档内容直接支持 claim 全部核心断言（claim=问题时 = 文档能回答问题）
  - **inferred（部分覆盖，边界写死）**: claim 至少一个核心断言被文档支持，且至少一个核心断言未被文档覆盖（无冲突）——module-051 归因②的对症定义（被 HHEM 判成 0.8+ 的"部分覆盖"样例应落此档）
  - **unsupported**: 文档不包含支持 claim 任何核心断言的内容（含矛盾内容——按 module-052 三态映射口径 contradiction→unsupported）
  - 评审流程: 每条标注须在 note 字段给出核心断言拆解依据
- `ai_service/tests/eval/test_factcheck_judge.py` — 数据集结构断言更新（见下方存量影响）
- **不动**: 其他模块

**依赖**: 无（与 WP-A 独立；顺序按 task-brief: WP-A 先跑旧 50 条旧标注出方向性阈值，WP-B 后 WP-C 复扫）

**实现要点**:
1. **存量 50 条 inferred 复核**: INFERRED_SAMPLES 10 条 + real_retrieval_pairs 转换的 neutral 样本（13 条）按新口径逐一复核；label 变更 → 变更清单（样本 / 旧→新 / 理由）入 changelog——可审计
2. 转换的样本 questions 可能重复（real_retrieval_pairs 的 question 来自 golden 112 题，与 SUFFICIENCY_DATASET 前 20 有重叠）→ **按 question 去重**（保留 real 版本，note 标注）；结构校验强制 question 唯一
3. 存量测试影响（**验收许可，module-061/062 先例**，plan + AC 双声明，changelog 标注）:
   - `TestGoldenFactcheck::test_dataset_structure_50_three_classes`（test_factcheck_judge.py:478-487）断言 `len == 50` + counts `{20, 10, 20}` → 按新数据集更新（≥100 + 实际类分布）
   - `test_dataset_borrows_from_sufficiency`（:489-495）断言某 question 在集中 → sufficient[:20] 保留则大概率仍绿，Developer 验证（不改）
4. 通过标准: 100+ 条结构校验过（load 校验）+ 标注指南落盘 + 变更清单

### WP-C: 重跑验证 + 决策

**描述**: 新标注集（100+）+ WP-A 最优阈值 → 重跑 HHEM kappa。**达标（三态 kappa ≥ 0.7，ADR-0010 P1-④ 门槛）→ 改生产配置默认值**；不达标 → 不改配置，如实标注 + 失败模式分类。

**预估代码量**: config 2 行 + 注释（仅达标分支）

**涉及文件**:
- `ai_service/src/config.py` — 达标时 `verify_hhem_threshold_high/low`（263-264 行）默认值改最优组合 + 注释（校准依据: 标注集规模/日期/kappa/对照表出处）；`PW_VERIFY_HHEM_THRESHOLD_HIGH/LOW` 环境变量逃生口保留（pydantic env_prefix="PW_" 已核实）
- `ai_service/agent/reflector.py` — **零代码改动**（`_judge_by_hhem` 557-558 行读 settings，默认值变更自动生效；仅按 grep 结果确认 518-525 docstring 硬编码 "0.7"/"0.3" 字样是否需要注释级同步——如修改仅注释不动逻辑）
- eval_runs 落库: 常规 `eval_type='factcheck'` 1 行（最优阈值下）

**依赖**: WP-A + WP-B

**实现要点**:
1. 重跑命令: `python -m eval.golden.golden_factcheck --threshold-high <opt_high> --threshold-low <opt_low>`（真实 HHEM + 新标注集）
2. **决策规则（写死，Developer 无自由裁量）**:
   - 三态 kappa ≥ 0.7 → **达标**: config 默认值改最优组合 + 注释；conftest 钉旧值（WP-D）；METRICS 幻觉检测节更新；changelog 记录对照表 + 选择 + 理由（module-070 默认值决策先例）
   - < 0.7 → **不达标**: 不改配置；changelog 如实记录新数字 + **失败模式分类**（supported 误杀 n / inferred 混淆 n / unsupported 漏判 n，按 per_question 误判明细统计）+ 入 backlog 不隐藏
3. 达标时验证: 单测覆盖映射（max_score_to_verdict）+ conftest 钉旧值后存量断言零改动即满足；生产 verify 行为变化是本模块目标（阈值语义经单测锁定）
4. 诚实边界: 阈值最优基于 100+ 标注集，仍可能过拟合标注集本身——changelog 声明"标注集扩充后需复扫"

### WP-D: 回归 + 文档收口

**描述**: 全量 1163 基线（task-brief 口径；若实跑收集不同以实跑为准）+ 新增单测全绿 + conftest 钉旧阈值（达标分支）+ changelog / CONTEXT.md / METRICS.md / ADR-0010 / 三记忆文件。

**预估代码量**: conftest ~6 行（达标分支）+ 测试 ~150 行（含注释，按含注释/测试口径自动豁免）

**涉及文件**:
- `ai_service/tests/conftest.py` — **达标分支**新增 autouse fixture `default_hhem_thresholds_pinned`（`monkeypatch.setattr(settings, "verify_hhem_threshold_high", 0.7)` + low 0.3，对齐 056/058/060/069 模式）——`test_run_eval_end_to_end`（test_factcheck_judge.py:543）断言 `thresholds["high"] == 0.7` 依赖此钉，存量测试零改动
- `ai_service/tests/eval/test_factcheck_judge.py` — 新增 ~10 项（全 mock 零真实模型）:
  - `max_score_to_verdict` 边界（==high / ==low / 区间 / 低于 low）
  - `judge_factcheck` 重构后与旧 inline 映射逐字一致（mock hhem_judge.predict 固定分数）
  - `scan_thresholds`: 25 组全输出 / **只用 max_score（mock judge 断言调用次数 == 样本数——"分数只算一次"回归锁）** / skipped 排除 / 降序排序 / 空输入
  - `build_factcheck_dataset` 新结构（≥100 / 三类齐全 / keywords 非空 / question 唯一 / part 来源字段）
  - `load_factcheck_dataset` 校验（<100 抛 ValueError / JSON 缺失抛错）
  - `--threshold-high/--threshold-low` 覆盖 settings 生效
- `specs/module-071-hhem-kappa-calibration/changelog.md`（Developer 产出）: 阈值对照表（25 组）/ 标注变更清单 / 重跑数字 / 决策 + 理由 / 诚实边界
- `CONTEXT.md` — **只增不删，先备份**（%TEMP% 副本），幻觉检测领域节追加 module-071 段
- `METRICS.md` — 幻觉检测节（50-56 行）数字更新 + 待办 #2（237 行）标记（达标: 完成 + 新数字；不达标: 如实更新新数字）
- `specs/adr/0010-hallucination-detection-upgrade.md` — P1-④ 状态行补 module-071 校准结果（先例 module-051/054/057 均更新 ADR-0010）
- `memory/project-context.md` / `memory/file-index.md` / `memory/agent-activity-log.md`（Planner 已更新 PLAN 行）
- **不动（红线）**: `factcheck_judge.py` / `reflector.py` 逻辑 / 其他模块

**依赖**: WP-A + WP-B + WP-C

## 3. 技术方案

- 涉及数据表: eval_runs（复用，不新增表；eval_type 新值 'factcheck_scan'）
- API 端点: 无（纯评测侧 + config 默认值）
- 外部依赖: 无新增（HHEM 本地 models/hhem-2.1-open 438MB 已在盘 + sklearn 已有）
- 环境变量: `PW_VERIFY_HHEM_THRESHOLD_HIGH/LOW`（已有，逃生口保留）
- 模型前置: `models/hhem-2.1-open`（已核实）；模型缺失 → 全部 skipped 无法扫描，如实记录

## 4. 验收标准

见同目录下的 `acceptance-criteria.md`

## 5. 风险评估

- **存量测试结构断言**（test_factcheck_judge.py:478-487 断言 50 条精确结构）: 标注集扩充必然打破 → **验收许可更新**（plan + AC 双声明 + changelog 标注，module-061/062 先例——"存量零改动"红线在本项上有明示例外）
- **达标改默认值 → 存量阈值断言**（test_factcheck_judge.py:543 `== 0.7`）: conftest autouse 钉住旧值 0.7/0.3（WP-D 达标分支，hermetic）
- **WP-A 最优阈值漂移**: 基于旧 50 条旧标注的方向性结论，WP-B 标注重写后可能移动 → WP-C 复扫确认 + 诚实边界声明
- **real_retrieval_pairs neutral→inferred 语义映射**: 与重写后"部分覆盖"口径需逐一复核 → 标注指南写死边界 + 变更清单
- **HHEM 不可用**（模型缺失/加载失败）: 全部 skipped 无法扫描/重跑 → 如实记录 + fixture 模式管线验证
- **新增 JSON 数据与代码脱节**: load 结构校验强制（缺失抛错不静默）
- **25 组 × eval_runs 噪音**: 单行 factcheck_scan（对照表内嵌 scores）
- **基线数字口径**: task-brief 写 1163/0、module-070 验收为 1152/0 → 以实跑收集为准，changelog 如实记录

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-18 | 初始版本 | Planner |
