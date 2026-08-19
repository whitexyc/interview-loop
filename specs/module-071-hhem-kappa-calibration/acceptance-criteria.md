# 验收标准 — Module-071: 幻觉检测 kappa 校准（阈值扫描 + 标注集扩充 + 达标决策）

## 1. 功能验收

### 1.1 阈值扫描（WP-A）

- [ ] **AC-1 三态映射纯函数**：`max_score_to_verdict(max_score, high, low)` 边界语义与生产逐字一致（`>= high → supported / >= low → inferred / 其余 → unsupported`，含等号；reflector.py:580-585 同口径）；boundary 单测钉死 ==high / ==low / 区间 / 低于 low
- [ ] **AC-2 扫描 25 组全输出**：`--scan-thresholds` 产出 high ∈ {0.5,0.55,0.6,0.65,0.7} × low ∈ {0.2,0.25,0.3,0.35,0.4} 共 25 组对照表（三态 kappa + 二值 kappa + Accuracy），按三态 kappa 降序
- [ ] **AC-3 分数只算一次**：扫描运行中 HHEM judge 调用次数 == 评估样本数（单测 mock 断言——"分数只算一次"回归锁）；25 组阈值零额外模型调用（纯后处理）
- [ ] **AC-4 skipped 不参与扫描**：model_unavailable/error 样本（无 max_score）排除，与 kappa_metrics 只算 evaluated 同口径；`--fixture + --scan-thresholds` 组合显式报错（启发式判官无分数）
- [ ] **AC-5 落库单行**：扫描落库 1 行 eval_runs（`eval_type='factcheck_scan'`，scores 含完整对照表 + best + thresholds_used）；`--no-save` 生效；不落 25 行噪音
- [ ] **AC-6 WP-A 不改生产配置**：config 默认值 0.7/0.3 保持；最优组合（三态 kappa 最高 → 二值 kappa 高者 → 贴近现状者）记录入 changelog

### 1.2 标注集扩充 + 口径（WP-B）

- [ ] **AC-7 数据集 100+ 结构校验**：`build_factcheck_dataset()` ≥ 100 条、三类齐全、keywords 非空（fixture 启发式兼容）、question 唯一、含 `part` 来源字段（real_retrieval / constructed / sufficiency 代理）；`load_factcheck_dataset()` 校验通过（<100 抛 ValueError）
- [ ] **AC-8 JSON 缺失报错**：factcheck_real_samples.json 缺失 → load 明确 ValueError，不静默降级
- [ ] **AC-9 标注指南落盘**：`eval/datasets/factcheck_annotation_guide.md` 三态定义写死——supported（文档支持 claim 全部核心断言）/ **inferred（部分覆盖：至少一个核心断言被支持 + 至少一个未被覆盖且无冲突，边界写死）** / unsupported（无任何核心断言被支持，含矛盾内容）；每条标注须在 note 给出核心断言拆解依据
- [ ] **AC-10 存量复核 + 变更清单**：INFERRED_SAMPLES 10 条 + real_retrieval_pairs 转换的 neutral 样本按新口径逐一复核；label 变更记录变更清单（样本 / 旧→新 / 理由）入 changelog——可审计
- [ ] **AC-11 真实样本来源可溯源**：real_retrieval_pairs.json 24 条转换样本标 `part=real_retrieval`（claim=真实 LLM 答案句子 + doc=DB 检索片段），与 SUFFICIENCY_DATASET 代理标注可区分

### 1.3 重跑 + 决策（WP-C）

- [ ] **AC-12 阈值覆盖生效**：`--threshold-high X --threshold-low Y` 覆盖 settings 生效（judge_factcheck 按覆盖值映射），重跑用 WP-A 最优组合
- [ ] **AC-13 重跑数字落库**：新标注集 + 最优阈值重跑，eval_runs 落库常规行（`eval_type='factcheck'`），数字与 changelog 一致
- [ ] **AC-14 达标改生产配置**：三态 kappa ≥ 0.7 → config `verify_hhem_threshold_high/low` 默认值改最优组合 + 注释（校准依据: 标注集规模/日期/kappa/对照表出处）；`PW_VERIFY_HHEM_THRESHOLD_HIGH/LOW` 逃生口保留；reflector.py 零代码改动（读 settings 自动生效）
- [ ] **AC-15 不达标如实标注**：< 0.7 → 不改配置；changelog 如实记录新数字 + **失败模式分类**（supported 误杀 / inferred 混淆 / unsupported 漏判各多少，按 per_question 误判明细统计）+ 入 backlog 不隐藏

### 1.4 回归 + 文档（WP-D）

- [ ] **AC-16 全量基线全绿**：`pytest tests/ -q` 基线 **1163/0**（task-brief 口径；实跑收集若不同以实跑为准）+ 新增单测全绿
- [ ] **AC-17 存量测试零改动红线（含明示例外）**：`git diff` 中测试文件仅新增用例行 + conftest 新增 autouse 行；**唯一例外**：`test_dataset_structure_50_three_classes`（test_factcheck_judge.py:478-487）按验收许可更新为新数据集结构断言（plan §WP-B 明示，changelog 标注；module-061/062 先例）；`test_dataset_borrows_from_sufficiency` 不改（Developer 验证仍绿）
- [ ] **AC-18 红线模块零改动**：`factcheck_judge.py`（HHEM 推理路径）/ `reflector.py` 逻辑 / 其他模块 `git diff` 为空；config 仅默认值行（达标分支）
- [ ] **AC-19 达标分支 conftest 钉旧值**：新增 autouse fixture `default_hhem_thresholds_pinned`（0.7/0.3），存量阈值断言（test_factcheck_judge.py:543 `== 0.7`）零改动全绿

## 2. 非功能验收

### 2.1 性能验收

- [ ] **AC-20 扫描成本**：HHEM 每样本仅 1 次推理（50 条 ≈ 1 次模型运行 + 后处理 < 1s）；25 组阈值映射为纯 CPU 后处理，零模型调用

### 2.2 代码质量验收

- [ ] **AC-21 代码量**：功能代码 ≤ 200 行（max_score_to_verdict ~8 + scan_thresholds ~35 + CLI ~25 + build/load 扩展 ~35 + config 2 + conftest 6 ≈ 110 行；JSON 数据文件非代码；测试按含注释/测试口径自动豁免）
- [ ] **AC-22 单一来源**：`max_score_to_verdict` 为三态映射唯一实现（judge_factcheck 引用之，防扫描与生产语义漂移）；扫描只消费 per_question.max_score
- [ ] **AC-23 无新依赖无新表**：不新增 requirements 条目、不新增数据表/列（eval_runs 复用）

### 2.3 文档验收

- [ ] **AC-24 changelog**：阈值对照表（25 组）+ 标注变更清单 + 重跑数字 + 决策 + 理由 + 诚实边界（小样本方向性 / 阈值可能过拟合标注集需复扫）
- [ ] **AC-25 CONTEXT.md**：只增不删，先备份（%TEMP% 副本）
- [ ] **AC-26 METRICS.md**：幻觉检测节（50-56 行）数字更新 + 待办 #2（237 行）标记（达标: 完成 + 新数字；不达标: 如实更新）
- [ ] **AC-27 ADR-0010**：P1-④ 状态行补 module-071 校准结果
- [ ] **AC-28 三记忆文件**：project-context / file-index / agent-activity-log 已更新

## 3. 可运行验证命令

| 验收项 | 验证命令（在 ai_service 目录） | 预期输出 |
|--------|----------|----------|
| AC-1~4 扫描 + 纯函数 | `python -m pytest tests/eval/test_factcheck_judge.py -q` | 存量 + 新增全部 passed |
| AC-7/8 数据集校验 | `python -c "from eval.golden.golden_factcheck import load_factcheck_dataset; print(len(load_factcheck_dataset()))"` | ≥ 100，无异常 |
| AC-2~6 真实扫描 | `python -m eval.golden.golden_factcheck --scan-thresholds` | 25 行对照表 + 最优组合 + 落库 1 行（--no-save 跳过） |
| AC-12/13 重跑 | `python -m eval.golden.golden_factcheck --threshold-high <opt> --threshold-low <opt>` | kappa 数字 + eval_runs 落库 |
| AC-16/17 全量回归 | `python -m pytest tests/ -q` | `1163 + 新增 passed / 0 failed`，存量零改动（明示例外） |
| AC-14 配置生效 | `python -c "from src.config import settings; print(settings.verify_hhem_threshold_high, settings.verify_hhem_threshold_low)"` | 达标分支 = 最优组合 |

## 4. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: YYYY-MM-DD
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
