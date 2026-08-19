# Module-045 测试报告

> 遗留清理批：retriever 透传 + 043 minor + 流式 L3 + 充分性训练脚本 + requirements
> Tester: tester-045 | 2026-08-10 | 结论：**PASS**（0 失败）

## 1. 全量回归

```
python -m pytest tests/ -q
→ 448 passed, 3 warnings in 126.10s (0:02:06)
```

- **448 = 428 基线（历史首次全绿）+ 20 新增**，0 失败 —— 红线 4 保持
- 3 warnings 为既有 DeprecationWarning（redis setex 等），与 module-045 无关
- 新增测试分布（与 Dev/Reviewer 统计一致）：
  - `tests/test_retriever_concurrency.py` +2（WP1 双命中透传）
  - `tests/test_intent_validation.py` +5（WP2a 边界样本 FTS 确认 + WP2b 存档/透传 3 + WP2d 白名单）
  - `tests/test_stream_memory.py` +3（WP3 流式 L3 标记）
  - `tests/test_sufficiency_classifier.py` 新文件 10（WP4 mock 特征）

## 2. 新增测试逐项验证（均在本次全量运行中通过）

| 验收点 | 测试 | 关键断言 |
|--------|------|----------|
| WP1 双命中透传 | `TestExecuteAbsCosinePassThrough::test_double_hit_doc_preserves_abs_cosine` | 双命中合并结果 `abs_cosine == 0.65`（原始绝对余弦，非 min-max 相对分）；`vector_score == 1.0`（相对分照旧，两者语义区分明确） |
| WP1 fts-only 无字段 | `test_fts_only_doc_has_no_abs_cosine` | fts-only 文档不含 `abs_cosine` 键；vector-only 带 `0.6`（下游 `d.get(..., 0.0)` 语义不变） |
| WP2a 规则表边界样本 | `test_rule_table_keeps_kb_boundary_samples` | `_rule_hits("你能做什么？这个系统能帮我解决什么问题？")` 为 False；`_RULE_TABLE` 不含"你能做什么/你会什么" |
| WP2a FTS 确认不被否决 | `test_boundary_sample_not_vetoed_when_fts_hit` | FTS 命中 → confirmed=True, signal=fts_term |
| WP2b 判定/展示同源存档 | `test_top_abs_cosine_archived_before_parent_mapping` | patch 判定返回 (True, 0.42) → `steps.retrieval.top_abs_cosine == 0.42`（证明展示值来自 round 0 存档而非映射后 dict） |
| WP2b 父块映射透传 | `TestExpandToParentsAbsCosine` 2 例 | 子块 abs_cosine 最大值透传父块（0.55）；子块无字段 → 父块 0.0 |
| WP2c 生产路径复用 | 全量中 `TestL3ChatStepsObservable` + engine.py:260 / main.py:397 调用点 | `_check_suspected_misclassify` 返回 `(flag, top1_abs)` 二元组，chat 与 chat_stream 均调用（6 例 L3 测试更新后全部通过） |
| WP2d L4 白名单 | `test_classifier_bogus_intent_whitelisted_to_knowledge` | bogus 最高分被白名单拦截 → intent=knowledge，confidence 取白名单后概率 0.1 |
| WP3 流式 L3 标记 | `TestChatStreamL3Flag` 3 例 | top-1 abs_cosine 0.1 → retrieval step `suspected_misclassify=True, top_abs_cosine=0.1`；0.7 → False；空 docs → (False, None)，SSE 照常 done |
| WP4 训练脚本 | `tests/test_sufficiency_classifier.py` 10 例 | fit/predict_proba（mock 特征线性可分）/ 落盘重载 / --no-save 不落盘 / 模型缺失 False / 未加载 predict 抛 RuntimeError / 样本 <10 SystemExit(1) / 数据源 100 条 50:50 / CLI 参数 |

## 3. WP4 端到端实跑（独立验证，--no-save 不落盘）

```
python -m eval.train_sufficiency_classifier --no-save
→ 训练样本组装完成: 100 条, 类别分布: {'sufficient': 50, 'insufficient': 50}
→ 加载本地嵌入模型 bge-m3-q8_0.gguf, dim=1024
→ Samples: 100 | Accuracy: 0.8000
→ insufficient precision 0.67 / recall 1.00 / f1 0.80（support 8）
→ sufficient  precision 1.00 / recall 0.67 / f1 0.80（support 12）
→ --no-save：未落盘
```

- 端到端训练成功（exit code 0）；重点指标 insufficient Recall 1.0000（不放过"不充分"）
- `--no-save` 未修改已落盘模型（`models/sufficiency_clf.joblib` 9135 字节、mtime 2:11:06 不变）
- 落盘模式已有产物佐证（9135 字节，Dev 端到端训练生成）

## 4. 红线核查（Tester 独立复核）

1. **只动 plan 3.1 文件**：`git status` 核对——module-045 文件集（router.py / engine.py /
   retriever.py / main.py / requirements.txt / 3 个测试文件 / train_sufficiency_classifier.py 新建）
   与 plan 一致；react.py / langgraph_react.py / faithfulness.py / module-033 changelog /
   test_main.py 为其他会话改动（plan §4 已审查），未触碰
2. **main.py 去个人化文案保留**：grep 确认 main.py 无"张三"残留；"AI 推理服务入口"入口
   docstring、"你是个人网站的 AI 助手" prompt 均保留；WP3 仅新增 suspected_misclassify
   代码块（diff 确认）
3. **未执行 git commit**：HEAD 仍为 b729fd1
4. **全量 448 全绿保持**：0 失败（上表）

## 5. 结论

**PASS** —— 全量 448/448 通过（基线 428 + 新增 20，0 失败，126.10s），新增测试全部通过，
WP4 端到端训练实测成功（Accuracy 0.8000 / insufficient Recall 1.0000 / --no-save 不落盘），
四条红线全部保持。
