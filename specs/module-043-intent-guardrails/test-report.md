# 测试报告 — Module-043: 输入防护 + Intent 校验体系

> Tester | 2026-08-09 | 全量回归验证

---

## 1. 总览

| 项目 | 结果 |
|------|------|
| 执行命令 | `python -m pytest tests/ -q`（ai_service 目录） |
| 全量结果 | **404 passed / 3 failed**（114.57s，4 warnings） |
| 新增测试 | 51 个全部通过（test_golden_intent 11 + test_schemas_validation 5 + test_intent_validation 35） |
| 预存失败 | 3 个，均与本模块无关（见 §3） |
| 新增测试独立复跑 | 51 passed（46.56s） |
| test_rerank_langgraph 独立复跑 | 18 passed（证明全量中 2 个失败为限流/顺序环境问题） |
| 红线核查 | 四条全部通过（见 §4） |
| **verdict** | **pass** |

## 2. 验收标准逐条对照

### §1 功能验收（WP1 三端点加固）— 全过

| 验收项 | 实现证据 | 测试证据 |
|--------|----------|----------|
| SearchRequest.query max_length=2000，超长 422 | `rag/schemas.py` L9 `Field(..., max_length=2000)` | `test_search_request_query_too_long` PASSED |
| MemorySaveRequest.content max_length=2000，超长 422 | `rag/schemas.py` L59 `Field(..., max_length=2000)` | `test_memory_save_content_too_long` PASSED |
| MemoryRecallRequest.query max_length=2000，超长 422 | `rag/schemas.py` L65 `Field(..., max_length=2000)` | `test_memory_recall_query_too_long` PASSED |
| 与 ChatRequest 模式一致（声明式 Field，不进业务逻辑） | 三端点与 ChatRequest（L19）同为 `Field(..., max_length=2000)` | 既有 `test_query_too_long` 等用例通过 |

### §2 功能验收（WP3 L2 前置校验 — 修订版）— 全过

| 验收项 | 实现证据 | 测试证据 |
|--------|----------|----------|
| intent≠knowledge 且 confidence<0.5 才触发 | `router.py` L185-186（`_L2_CONFIDENCE_THRESHOLD = 0.5`，L54） | `test_low_confidence_casual_triggers_l2` / `test_low_confidence_realtime_triggers_l2` PASSED |
| 高置信/knowledge/缺 confidence 不触发 | 同 L185-186 条件 | `test_high_confidence_skips_l2` / `test_knowledge_intent_skips_l2` / `test_missing_confidence_skips_l2` PASSED |
| 确认动作确定性信号，**零 LLM** | `_deterministic_confirm`（L208-240）：① FTS 术语 `_fts_term_hit`（L261，SQL to_tsvector @@ plainto_tsquery，jieba 分词 + `_FUNCTION_STOPWORDS` 过滤）；② 图谱实体 `_graph_entity_hit`（L296，Cypher 拉实体名 + Python 子串匹配，不走依赖 LLM 的 graph_extractor）；③ 规则表 `_rule_hits`（L333，字符串特征词） | `test_confirm_path_never_calls_llm` / `test_fts_hit_path_no_llm_dependency` PASSED（patch LLMFactory 抛错确认路径仍正常）；grep 核查 LLMFactory/generate 仅出现在 classify() 主路径 L174-176 |
| 信号命中 → 修正为 knowledge | L188-194（reason 记录 `L2 信号确认(signal)`） | `test_confirm_hit_corrects_to_knowledge` / `test_fts_hit_confirms` / `test_graph_hit_confirms` PASSED |
| 信号未命中 → 保持原判 | L195-197（reason 记录 `L2 无确认信号`） | `test_no_signal_keeps_original` / `test_rule_veto_overrides_fts_hit` PASSED |
| 确认结果可观测 | logger.info + reason 字段带 signal | 同上（断言 reason 含信号标记） |

### §3 功能验收（WP4 L3 后置校验）— 全过

| 验收项 | 实现证据 | 测试证据 |
|--------|----------|----------|
| top-1 abs_cosine < 0.3 → suspected_misclassify | `engine.py` L86 `_L3_ABS_COSINE_THRESHOLD = 0.3`，L249-256 round 0 top-1 判定（复用 module-037 `abs_cosine` 字段口径，缺字段视为 0.0） | `test_flag_when_top1_abs_below_threshold` / `test_missing_abs_cosine_defaults_zero_flagged` / `test_multiple_docs_uses_top1_only` PASSED |
| 标记写入 ChatSteps（面板可见） | `engine.py` L322-331 `retrieval={count, top_abs_cosine, suspected_misclassify}` | `test_suspected_misclassify_written_to_steps` PASSED |
| 不阻塞、不改回答路径 | 仅置标志 + logger.info，回答路径无分支 | `test_no_flag_when_abs_above_threshold` / `test_boundary_equal` / `test_no_docs_no_flag` PASSED |

### §4 功能验收（WP2 L1 度量 + WP5 L4 分类器）— 全过

| 验收项 | 实现证据 | 测试证据 |
|--------|----------|----------|
| golden_intent.py 混淆矩阵 + per-class 指标 | `eval/golden_intent.py` `compute_confusion_matrix`（L107，precision/recall/f1/support）+ `print_report`（L226） | `test_basic_matrix_and_metrics` / `test_perfect_predictions` / `test_unknown_predicted_class` PASSED |
| eval_runs 落库（git_commit + 配置快照） | `record_eval_run`（L204，eval_type='intent'，对齐 golden_retrieval 契约） | `test_eval_runs_contract` / `test_save_failure_returns_zero` PASSED |
| 评测集含闲聊/实时/边界易混样本 | `INTENT_DATASET` L58 边界样本 `"你们网站有什么功能？"` → knowledge | `test_boundary_samples_present` / `test_structure_valid_and_classes_complete` PASSED |
| intent_classifier 可 fit / predict_proba（校准概率） | `agent/intent_classifier.py`（bge-m3 冻结 1024 维 + LogisticRegression(max_iter=500, class_weight="balanced")，L72-138；predict_proba 三类键齐全和≈1） | `test_fit_and_predict_proba` PASSED |
| router 可注入分类器，默认仍用 LLM | `router.py` L111-137（构造器注入 + 配置开关 `_get_classifier` 惰性加载）；`config.py` L80 `intent_classifier_enabled: bool = False` | `test_injected_classifier_used` / `test_default_llm_when_not_injected` / `test_disabled_switch_skips_lazy_load` PASSED |
| 训练脚本可用（golden 集训练，模型落盘） | `eval/train_intent_classifier.py` 存在（--no-save 纯评估；样本组装容错 golden_intent → golden.json → 内置手工样本） | 静态验证（依赖本地 bge-m3 嵌入，未在测试中执行） |

### §5 降级验收 — 全过

| 验收项 | 实现证据 | 测试证据 |
|--------|----------|----------|
| L2 信号查询失败 → 保守 knowledge | `router.py` L237-240 `error_conservative` → (True, ...) | `test_signal_exception_conservative_knowledge` / `test_confirm_unexpected_error_conservative_knowledge` PASSED |
| L4 模型缺失/加载失败 → 回退 LLM，零影响 | `intent_classifier.py` `load()` 异常返回 False（L63-70）；`router.py` L135-136 / L170-171 | `test_load_missing_model_returns_false` / `test_predict_without_model_raises` / `test_classifier_failure_falls_back_to_llm` / `test_lazy_load_failure_falls_back_llm` PASSED |
| L3 反证异常 → 记日志不阻塞 | 判定为纯读取（`docs[0].get(...)` 比较），无异常面，不改变回答路径 | `test_no_docs_no_flag` 等 PASSED |
| 三端点正常请求（短 query）行为不变 | max_length 仅约束超长，短请求零改动 | 全量 404 passed 零回归 |

### §6 接口兼容 — 全过

| 验收项 | 证据 |
|--------|------|
| ChatRequest / ChatResponse / ChatSteps 旧字段不变 | `schemas.py` 仅新增 Field 约束，结构未变；`engine.py` steps 仅新增 retrieval 键（top_abs_cosine / suspected_misclassify） |
| router.classify() 返回结构不变 | 仍返回 `{intent, confidence, reason}`（L153，L168-169，L204） |
| 现有 10 个 Agent 工具不受影响 | 本模块未触碰 tools 目录；全量回归零新增失败 |
| 无 LLM 二次确认调用 | grep `router.py`：`LLMFactory.get_client` / `generate` 仅出现在 classify() 主路径 L174-176；`_deterministic_confirm` 及其调用的三个信号函数全为确定性实现；测试级双保险 `test_confirm_path_never_calls_llm` |

### §7 测试验收 — 全过

| 验收项 | 结果 |
|--------|------|
| test_schemas_validation.py +3 用例（三端点 422） | 5 用例全过（含 3 个新增） |
| test_intent_validation.py：L2 触发/命中/未命中/降级 + L3 反证 + L4 分类器 | 35 用例全过 |
| test_golden_intent.py：混淆矩阵 + eval_runs | 11 用例全过 |
| 全量 `pytest tests/ -q`：仅 3 个预存失败 | 404 passed / 3 failed（1 预存 top_k + 2 外部限流，见 §3） |

### §8 文档验收 — 本次完成

- changelog.md（Dev-1/Dev-2 已追加，本报告追加 Tester 交接）、review-report.md（Reviewer 产出）、test-report.md（本文件）
- 记忆文件更新（rag-architecture.md / rag-agent-roadmap.md / MEMORY.md）
- L4 数据约束与飞轮接口说明：changelog "数据约束"条目（真实飞轮 👍/👎 未积累，先 golden 集训练；`fit()` 接口预留增量重训）

## 3. 失败详情（均预存/环境问题，不计入模块）

全量运行 3 failed，与模块改动无关，且与改动前基线一致：

| 失败项 | 断言 | 定性 |
|--------|------|------|
| `tests/test_identity.py::TestEngineRecallIdentity::test_identity_passed_to_service` | `assert 5 == 3` | 预存 top_k 环境问题：memory_service.recall 的 top_k 默认值（5）与测试期望（3）不一致，其他会话改动/环境既有，非本模块引入（本模块不涉及 memory_service） |
| `tests/test_rerank_langgraph.py::TestLangGraphEndpoint::test_sse_tool_trace_events` | `assert 429 == 200` | 全量运行本地限流器触发（`src.ratelimit` 20 次/60s，日志可见 "IP 127.0.0.1 触发限流"）；**单独运行该文件 18 passed**，确认是测试顺序/限流环境问题 |
| `tests/test_rerank_langgraph.py::TestLangGraphEndpoint::test_budget_zero_endpoint_direct_answer` | `assert [] == ['done']` | 同上（限流导致事件流为空）；单独运行通过 |

独立复跑证据：
- `python -m pytest tests/test_identity.py -q`：1 failed / 19 passed（仅上述 top_k 项）
- `python -m pytest tests/test_rerank_langgraph.py -q`：18 passed（全量中的 2 个失败在独立运行下通过）

## 4. 红线核查

| 红线 | 核查结果 |
|------|----------|
| 只动自己工作包涉及的文件 | 测试/文档交接仅写 specs 与记忆文件，未改任何代码 |
| 不 stage/提交其他会话未提交改动 | 未执行 git add / git commit（react.py、langgraph_react.py、main.py、faithfulness.py 等保持未提交原状） |
| test_identity.py 预存失败不计入 | 已按预存处理（见 §3） |
| 不运行 git commit | 未执行，由 Planner 统一提交 |

## 5. 结论

**verdict: pass** — 本模块无新增失败。全量 404 passed / 3 failed 与改动前基线完全一致（3 个失败均为预存/环境问题）；本模块新增 51 个测试全部通过，覆盖 WP1-WP5 全部验收场景（含 L2 零 LLM 红线测试、L3 ChatSteps 可观测、L4 注入与降级）。
