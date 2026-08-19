# Test Report — Module-044: Rerank 截断验证 + 反思充分性精确化

> Tester | 2026-08-09 | 结论：**PASS**（全量 425 passed / 3 failed，3 项失败均为预存环境问题，不计入本模块）

## 1. 总览

| 项 | 结果 |
|---|---|
| 全量测试 | `python -m pytest tests/ -q` → **425 passed / 3 failed**（121.49s） |
| 本模块新增测试 | `tests/test_reflector.py`（TestCheckSufficiencyGates 9 例）+ `tests/test_golden_sufficiency.py`（12 例）→ **21 passed** |
| 既有用例适配 | `tests/test_reflector_temperature.py` 1 处（数量闸门 <2 篇短路 → 补 2 篇带 abs_cosine 文档）→ 通过，意图不变 |
| 模块相关文件单独复跑 | test_reflector.py + test_reflector_temperature.py + test_golden_sufficiency.py → **43 passed**（27.32s） |
| 预存环境失败 | 3 项（test_identity top_k 1 + test_rerank_langgraph 外部限流 2），与本模块无关，见 §3 |
| 相对 module-043 基线（404/3） | 净增 21（本模块全部新增用例），3 项失败同源同数 |

### WP1 实测数据与决策（AC §8 要求，数据来自 changelog / ADR-0004，经 Reviewer 独立重跑复核）

| 截断 | 2 pair 耗时 | 6 pair 耗时 | 相关文档分数 | 排序一致性 |
|---|---|---|---|---|
| 250 | 2.161s（1.08s/对） | 5.455s（0.91s/对） | 0.9907 / 0.9912 / 0.9988 | 6/6 与 500、1000 完全一致 |
| 500 | 4.128s（2.06s/对） | 9.900s（1.65s/对） | 0.9904 / 0.9930 / 0.9993 | — |
| 1000 | 7.269s（3.64s/对） | 19.618s（3.27s/对） | 0.9985 / 0.9955 / 0.9996 | 6/6 一致 |
| 2000 | 未跑（ADR-0004 历史：耗时线性涨、精度增益趋零） | | | |

**决策：采纳 250**——250 相关文档分数全部 ≥ 0.98（与 500 差 ≤ 0.002，噪声级）且 6 pair 耗时下降 44.9%，满足 plan 决策规则；`reranker.py::_MAX_PAIR_CHARS` 500 → 250。诚实记录：弱相关文档绝对分数随截断下降（g1/doc2 0.2195→0.0535）但相对排序 6/6 不变（ADR-0004 决策 3 已接受的压缩特性），重排只取 Top-5 不受影响。Reviewer 独立重跑验证数据真实可复现（分数确定性完全一致，耗时同量级）。

## 2. 验收标准测试对照

### §1 功能验收（WP3+5 层 1+3）
| AC | 测试依据 | 结果 |
|---|---|---|
| docs 为空 → 不充分（现有行为保留） | reflector.py:178-180 代码核验 | ✅ |
| 文档数 < 2 → 直接不充分，零 LLM | `test_gate_fewer_than_two_docs_no_llm`（mock_get.assert_not_called()） | ✅ |
| top-1 abs_cosine < 0.4 → 不充分 + rewritten_query，零 LLM | `test_gate_top1_score_below_threshold_no_llm`（0.25，assert_not_called） | ✅ |
| 分数达标 → 才进 LLM 判模糊地带 | `test_score_passes_gate_goes_llm`（0.7，assert_called_once） | ✅ |
| LLM 判不充分 → 尊重语义走 rewritten_query | `test_llm_insufficient_respected_high_score`（0.7 高分仍走改写） | ✅ |
| 返回结构不变（sufficient/reason/rewritten_query?） | 全路径代码核验 + 各测试断言（红线 5 通过） | ✅ |

### §2 功能验收（WP4 层 2）
| AC | 测试依据 | 结果 |
|---|---|---|
| _CHECK_PROMPT 含 few-shot 正反例各 ≥1 | `test_prompt_has_few_shot_and_cot`（示例 1/示例 2） | ✅ |
| _CHECK_PROMPT 含 CoT 信息点比对步骤 | 同测试（"信息点" / "判断步骤"断言） | ✅ |
| 自洽性检查配置开关默认 False，开启两温度各判一次、不一致保守充分 | `test_self_check_enabled_consistent_uses_result` / `test_self_check_enabled_disagree_conservative_sufficient`（各 2 次调用断言）；默认关恰好 1 次（并入达标用例 assert_called_once）；config.py `sufficiency_self_check_enabled=False` | ✅ |
| prompt 变更向后兼容（JSON 结构不变） | `test_prompt_has_few_shot_and_cot`（"sufficient": true/false 键存在）+ _parse_check 未动 | ✅ |

### §3 功能验收（WP2 层 0）
| AC | 测试依据 | 结果 |
|---|---|---|
| golden_sufficiency.py 跑通：Accuracy + P/R/F1 + 混淆矩阵 | 脚本实测（fixture 模式 12/12 评估 0 跳过，Accuracy 1.0，混淆矩阵 6/0/0/6）；`TestRunEval` 3 用例 | ✅ |
| eval_runs 落库 eval_type='sufficiency' + git_commit + 配置快照 | `TestRecordEvalRun` 2 用例（契约打桩验证 eval_type/scores 透传） | ✅ |
| 标注集含充分/不充分两类（fixture 模式可用） | `TestLoadSufficiencyDataset` 3 用例（≥10 条、两类 ≥5、含"完全不沾边" ≥3）+ `TestHeuristicJudge` 3 用例 | ✅ |
| 报告重点标出 insufficient Recall | `test_misclassification_recorded_and_recall_highlighted`（漏判时 insufficient_recall=0.0 如实反映）+ 脚本报告大字行 | ✅ |

### §4 功能验收（WP1 ADR-0004 验证）
| AC | 测试依据 | 结果 |
|---|---|---|
| benchmark_rerank.py 可配 --max-chars + 2/6 pair 计时 + 分数输出 | 脚本核验（argparse choices 250/500/1000/2000、--pairs 2/6、预热计时）；Reviewer 实跑通过 | ✅ |
| 实测 250 vs 500 → 数据记录 | §1 WP1 实测表（Reviewer 独立重跑复核真实） | ✅ |
| 四档选数表补齐 → 数据驱动决策 | ADR-0004 四档表（2000 档引历史数据，plan 只要求实测 250 vs 500，可接受）→ 采纳 250 | ✅ |

### §5 降级验收
| AC | 测试依据 | 结果 |
|---|---|---|
| abs_cosine 缺失/异常 → 不误杀走 LLM | `test_degrade_missing_abs_cosine_goes_llm`（缺失字段仍走 LLM 判充分）；异常值 TypeError/ValueError → warning 走 LLM（代码核验） | ✅ |
| 闸门/LLM 异常 → 默认充分 | `test_degrade_llm_exception_conservative_sufficient`（RuntimeError → sufficient=true，"默认通过"在 reason） | ✅ |
| 自洽开启时 LLM 异常 → 保守充分 | 统一 except → 默认充分路径（代码核验） | ✅ |
| 正常路径零回归 | `test_score_passes_gate_goes_llm`（0.7 + LLM 充分 → true，行为与旧版一致）；全量 425/3 仅预存失败 | ✅ |

### §6 接口兼容
| AC | 测试依据 | 结果 |
|---|---|---|
| check_sufficiency 返回结构不变 | 红线 5 核验（全路径） | ✅ |
| generate_answer / generate_answer_stream / verify_answer 不受影响 | git diff：generate/verify/stream 路径零改动；模块相关 43 用例全过（含 scratchpad/verify 回归） | ✅ |
| engine.py 调用点无需改动 | git diff：engine.py 未动（缺失时 reflector 侧兜底） | ✅ |

### §7 测试验收
- [x] TestCheckSufficiencyGates 9 用例（硬闸门 2 + 达标 1 + 语义尊重 1 + prompt 结构 1 + 自洽 2 + 降级 2），零 LLM mock 断言 / assert_called_once / prompt 结构断言齐备——全部实测通过（注：Dev-B changelog 自述"10 用例"为计数口误，实为 9）
- [x] test_golden_sufficiency.py 12 用例全过
- [x] 全量 425 passed / 3 failed（121.49s），3 项失败即预存环境问题（§3），与本模块无关

### §8 文档验收
- [x] changelog.md（WP1+WP2 / WP3-5 两段，含实测数据与决策）
- [x] review-report.md（本文件之前已产出，结论 approved）
- [x] test-report.md（本文件，含 WP1 实测数据与决策）
- [x] ADR-0004 TODO 状态更新（已验证 + 四档选数表）；ADR-0005 状态更新（层 0-3 已实现，层 4 留待数据）
- [x] 层 4 明确说明"本模块不做"及理由（标注数据不足，与 ADR-0003 L4 同理）

## 3. 失败详情（全部为预存环境问题，不计入本模块）

| 失败用例 | 断言失败 | 原因 |
|---|---|---|
| `test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` | `assert 5 == 3` | 预存 top_k 环境问题（module-034 时代遗留，配置与实际不符，与 module-044 无关） |
| `test_rerank_langgraph.py::TestLangGraphEndpoint::test_sse_tool_trace_events` | `assert 429 == 200` | 外部 API 429 限流（全量运行时本地限流器 "IP 127.0.0.1 触发限流: 20 次/60s" 触发；独立运行该文件通过，module-043 同判） |
| `test_rerank_langgraph.py::TestLangGraphEndpoint::test_budget_zero_endpoint_direct_answer` | `assert [] == ['done']` | 同源限流导致 SSE 事件流为空 |

与 module-043 基线（404/3）对比：失败项同源同数，本模块未引入任何新失败。

## 4. 红线复核（Tester 独立核验）

| 红线 | 结果 |
|---|---|
| ① 只动工作包文件 | git diff 核对：reflector.py +76（纯增量）、reranker.py 5 行（常量+注释）、config.py +5、test_reflector.py +179、test_reflector_temperature.py 1 处适配、新建 benchmark_rerank.py / golden_sufficiency.py / test_golden_sufficiency.py；react.py/langgraph_react.py/main.py/faithfulness.py/module-033 changelog 为其他会话既有未提交状态未触碰 ✅ |
| ② 不 stage/提交他人改动 | git status：索引为空（全部 ' M'/??），HEAD 仍为 module-043 提交 0984c80，无新 commit ✅ |
| ③ 预存失败不计入 | 3 项失败与基线同源（§3）✅ |
| ④ 不运行 git commit | git log 无 module-044 提交（由 Planner 统一提交）✅ |
| ⑤ 返回结构不变 | 空/<2 篇/分数闸门 → {sufficient:false, reason, rewritten_query}；LLM 路径 _parse_check → {sufficient, reason, rewritten_query?}（仅不充分带）；异常 → {sufficient:true, reason}——全路径一致 ✅ |
| ⑥ 闸门失败/异常 → 回退 LLM 或保守充分 | abs_cosine 缺失/异常值 → 走 LLM；LLM 异常 → 默认充分；自洽不一致 → 保守充分；无新强制失败路径 ✅ |

## 5. 结论

**PASS**。全量 425 passed / 3 failed（仅预存环境问题）；本模块新增 21 用例（TestCheckSufficiencyGates 9 + test_golden_sufficiency 12）全部通过，fixture 评测管线实测跑通（Accuracy 1.0 / 混淆矩阵正确 / insufficient Recall 大字标出）；WP1 实测数据经 Reviewer 独立重跑复核真实可复现，采纳 250 决策满足 plan 决策规则；6 条红线全部遵守。
