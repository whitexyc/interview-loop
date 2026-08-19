# Module-045 changelog

> 遗留清理批：retriever 透传 + 043 minor + 流式 L3 + 充分性训练脚本 + requirements
> Developer: dev-045 | 2026-08-10 | 全量 448 passed（基线 428 + 新增 20，0 失败）

## WP1 retriever 合并环 abs_cosine 透传（044 minor #1）

- `rag/retriever.py` `_execute` Step 4 合并环：vec 分支（doc_id 已在 merged 中）更新
  `vector_score` 的同时补 `merged[doc_id]["abs_cosine"] = doc["abs_cosine"]`（原始绝对
  余弦，归一化前存档值；vec_normalized 的 doc 源自 vector_results，必带该字段）。
  fts-only 文档保持无该字段（下游 `d.get("abs_cosine", 0.0)` 保守处理，语义不变）。
- 影响：双命中文档不再丢字段 → L3 分数闸门（check_sufficiency 层 1 top-1 <0.4）与
  L3 后置反证（engine top-1 <0.3）对双命中文档的覆盖提升；hybrid_score 计算零回归。
- 测试：`tests/test_retriever_concurrency.py` +2（`TestExecuteAbsCosinePassThrough`：
  双命中透传 0.65 原值 / fts-only 无字段、vector-only 带字段）。

## WP2a 规则表移除"你能做什么/你会什么"（043 minor #1）

- `agent/router.py` `_RULE_TABLE` 移除"你能做什么""你会什么"——golden 边界样本
  "你能做什么？这个系统能帮我解决什么问题？"标注 knowledge（问系统能力而非闲聊），
  原规则表命中 → rule_veto 否决 FTS/图谱确认信号，误伤边界样本。
- 测试：`test_intent_validation.py::test_rule_table_keeps_kb_boundary_samples` 更新
  断言（该样本 `_rule_hits` 返回 False + 规则表不再含两词）+ 新增
  `test_boundary_sample_not_vetoed_when_fts_hit`（FTS 命中 → confirmed，
  signal=fts_term，不再被否决）。

## WP2b ChatSteps top_abs_cosine 失真修复（043 minor #2）

- 根因：`_expand_to_parents` 重建 dict 丢 abs_cosine → chat 的
  `steps.retrieval.top_abs_cosine` 对父块映射结果恒 0.0。
- `rag/engine.py` 双管齐下：
  1. chat round 0 判定处 `top1_abs` 与 `suspected_misclassify` 同源存档（由
     `_check_suspected_misclassify` 一次返回），steps 展示存档值（父块映射后不丢）；
  2. `_expand_to_parents` 父块重建时透传 abs_cosine（子块最大值，与 hybrid_score
     同策略）——流式路径 `_retrieve` 同样不丢（WP3 依赖）。
- 测试：`test_intent_validation.py` +3（`TestExpandToParentsAbsCosine` 2 例：
  子块最大值透传 / 无字段默认 0.0；`test_top_abs_cosine_archived_before_parent_mapping`：
  patch 判定返回 (True, 0.42) → steps 展示 0.42，证明展示值来自存档而非映射后 dict）。

## WP2c _check_suspected_misclassify 生产路径复用（043 minor #3）

- `rag/engine.py` 静态方法改为返回 `(flag, top1_abs)`（空列表 `(False, 0.0)`）；
  chat round 0 内联判定改调用该方法（消除重复）；流式路径（main.py WP3）同源复用。
- 测试：`test_intent_validation.py::TestL3PostValidation` 6 例断言更新为元组解包
  （flag + top1_abs 双断言）。

## WP2d L4 分类器 intent 白名单（043 minor #4）

- `agent/router.py` L4 分支：`intent = max(probs, key=probs.get)` 后过白名单
  （非法 → knowledge，与 LLM 路径 `_parse_response` 口径一致，防类别外漂移）。
- 测试：`test_intent_validation.py` +1（`test_classifier_bogus_intent_whitelisted_to_knowledge`：
  最高分 "bogus" 被拦截 → intent=knowledge，confidence 取白名单后 intent 概率）。

## WP3 流式端点 ChatSteps 补 suspected_misclassify（044 遗留）

- `main.py` `chat_stream` Step 2（retrieval）step 事件数据补
  `suspected_misclassify` + `top_abs_cosine`（经 `rag_engine._check_suspected_misclassify`
  判定，与 engine.chat 非流式路径同源复用；`_retrieve` 已做父块映射，abs_cosine 经
  WP2b 透传，流式不再恒 0.0 恒标记）。空结果 → `(False, 0.0)` / top_abs_cosine=None。
- 未改动其他会话的去个人化文案（"张三"→"个人"等）。
- 测试：`tests/test_stream_memory.py` +3（`TestChatStreamL3Flag`：低余弦标记 True +
  top_abs_cosine 0.1 / 高余弦不标记 / 空结果不标记且 SSE 照常 done）。

## WP4 充分性分类器训练脚本 + 端到端训练

- 新建 `eval/train_sufficiency_classifier.py`（结构对齐 train_intent_classifier.py）：
  - 数据源 `eval.golden_sufficiency.SUFFICIENCY_DATASET`（100 条：充分 50 / 不充分 50，
    `load_sufficiency_dataset()` 结构校验）
  - 特征 = bge-m3 冻结 embedding 对"问题 + 检索文档"拼接文本编码（`build_feature_text`；
    充分性由问题能否被文档回答决定，特征必须含文档内容）
  - `SufficiencyClassifier`：`fit`（LogisticRegression max_iter=500,
    class_weight="balanced"，80/20 split random_state=42）/ `predict_proba`
    （{"sufficient": p, "insufficient": p}）/ `load`
  - CLI：`--model-path`（默认 models/sufficiency_clf.joblib）/ `--no-save`
  - 样本 < 10 条 → 明确报错 `sys.exit(1)`（与 intent 脚本一致）
  - 输出 Accuracy + per-class P/R/F1 + 大字标出 **insufficient Recall**
- 端到端训练（本地 bge-m3 GGUF，2026-08-10）：**Accuracy 0.8000**；test split 20 条
  （insufficient 8 / sufficient 12）：insufficient P 0.67 / **R 1.00** / F1 0.80，
  sufficient P 1.00 / R 0.67 / F1 0.80。模型落盘
  `ai_service/models/sufficiency_clf.joblib`（9,135 字节，本地约定不进仓库）。
- 测试：新建 `tests/test_sufficiency_classifier.py` 10 例（mock 特征线性可分）：
  fit/predict_proba/落盘/重载方向断言、--no-save 不落盘、模型缺失 False、
  未加载 RuntimeError、样本 <10 SystemExit(1)、数据集契约 100=50/50、特征拼接。

## WP5 requirements 补依赖（044 遗留）

- `requirements.txt` 追加 `scikit-learn>=1.3.0` + `joblib>=1.3.0`（L4/L3 分类器依赖，
  环境已装 sklearn 1.9.0 / joblib 1.5.3，声明补齐）。

## 测试与回归

- 新增/更新测试共 +20：retriever +2、intent_validation +5、stream_memory +3、
  sufficiency_classifier +10（新增文件）；更新断言：TestL3PostValidation 6 例、
  test_rule_table_keeps_kb_boundary_samples 1 例。
- 全量 `python -m pytest tests/ -q`：**448 passed / 0 failed**（基线 428 + 20，
  历史首次全绿保持，未引入任何新失败）。
