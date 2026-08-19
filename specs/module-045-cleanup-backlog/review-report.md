# Module-045 Review Report

> Reviewer 审查 | 2026-08-10 | verdict: **approved**

## 1. 审查方式

- 实际读取改动代码（retriever.py / router.py / engine.py / main.py / train_sufficiency_classifier.py / 3 个测试文件 + 1 个新测试文件），不依赖 Dev 自述
- 亲自实跑全量测试：`python -m pytest tests/ -q` → **448 passed / 0 failed**（113.57s）
- 亲自实跑训练脚本：`python -m eval.train_sufficiency_classifier --no-save` → Accuracy 0.8000、insufficient Recall 1.0000，与 Dev 自述一致
- 亲自验证边界样本 `RouterAgent._rule_hits("你能做什么？这个系统能帮我解决什么问题？")` → False
- 亲自验证 SUFFICIENCY_DATASET 契约：100 条（充分 50 / 不充分 50）
- 亲自确认模型落盘：models/sufficiency_clf.joblib（9135 字节）

## 2. 红线核查

| 红线 | 结果 |
|------|------|
| 1. 只动 plan 列出的文件 | ✅ module-045 文件集与 plan 3.1 一致；react.py / langgraph_react.py / faithfulness.py / module-033 changelog / test_main.py 为其他会话改动（plan §4 已审查合理），本次未触碰 |
| 2. main.py 去个人化文案只可保留 | ✅ git diff 确认去个人化文案改动（入口 docstring / chat docstring / "你是个人网站的 AI 助手" prompt）均保留未回退；WP3 仅新增 suspected_misclassify 相关代码块 |
| 3. 不运行 git commit | ✅ HEAD 仍为 b729fd1，工作区改动未提交 |
| 4. 全量 428+ 全绿 | ✅ 亲自实跑：448 passed / 0 failed（428 基线 + 20 新增，历史首次全绿保持） |
| 5. 各 WP 实现约束 | ✅ 逐条对照 plan 3.2 通过（见下） |

## 3. 验收标准逐条对照（acceptance-criteria.md）

### §1 功能验收 WP1（retriever 透传）— 全部通过

- ✅ 双命中合并结果含 abs_cosine：`merged[doc_id]["abs_cosine"] = doc["abs_cosine"]`（retriever.py L356）；测试断言透传原始 0.65（非 min-max 相对分 1.0）
- ✅ fts-only 无字段：合并环只在 vec 分支赋值，测试断言 `"abs_cosine" not in by_id[1]`
- ✅ hybrid_score 零回归：合并环仅加字段赋值，Step 5 计算逻辑未动；全量测试通过

### §2 功能验收 WP2（043 四项 minor）— 全部通过

- ✅ 规则表移除"你能做什么/你会什么"；`_rule_hits(边界样本)` 亲自验证返回 False；规则表其余词不误命中该样本
- ✅ test_rule_table_keeps_kb_boundary_samples 断言更新（该样本 False + 规则表不含两词）+ 新增 test_boundary_sample_not_vetoed_when_fts_hit（FTS 命中 → confirmed, signal=fts_term）
- ✅ ChatSteps.top_abs_cosine 非恒 0.0：round 0 判定处 (flag, top1_abs) 同源存档（engine.py L259）+ _expand_to_parents 父块重建透传 abs_cosine（子块最大值，与 hybrid_score 同策略，L776-778/L799）；test_top_abs_cosine_archived_before_parent_mapping 验证展示值来自存档
- ✅ _check_suspected_misclassify 改为返回 (flag, top1_abs)，chat round 0 内联判定改调用（生产路径复用，消除重复）
- ✅ L4 分类器 intent 过白名单（非法 → knowledge，与 LLM 路径口径一致）；confidence 取白名单后 intent 概率

### §3 功能验收 WP3（流式 L3 标记）— 全部通过

- ✅ chat_stream retrieval step 事件补 suspected_misclassify + top_abs_cosine（复用静态方法，与 engine.chat 一致；空结果 (False, 0.0)/None）；TestChatStreamL3Flag 3 例覆盖低/高余弦/空结果
- ✅ main.py 去个人化文案未改动/回退

### §4 功能验收 WP4（充分性分类器训练脚本）— 全部通过

- ✅ `python -m eval.train_sufficiency_classifier` 端到端实跑成功（100 条，bge-m3 + LogisticRegression balanced）
- ✅ 输出 Accuracy + P/R/F1 + 大字标出 insufficient Recall（实跑：Accuracy 0.8000、insufficient R 1.0000）
- ✅ 模型落盘 models/sufficiency_clf.joblib（9135 字节）；--no-save 不落盘（测试 + 实跑双验证）
- ✅ 样本 <10 明确报错 sys.exit(1)（测试断言 SystemExit code=1）；--model-path 可配

### §5 功能验收 WP5（requirements）— 通过

- ✅ requirements.txt 追加 scikit-learn>=1.3.0 + joblib>=1.3.0

### §6 接口兼容 — 通过

- ✅ retriever 返回结构多一字段，读取方均为 d.get("abs_cosine", 0.0) 兼容
- ✅ ChatSteps 旧字段不变；check_sufficiency / classify() 无签名破坏（_check_suspected_misclassify 返回类型变更仅内部调用方 chat/chat_stream 同步更新，测试全过）
- ✅ 10 个 Agent 工具不受影响（全量测试通过）

### §7 测试验收 — 通过

- ✅ 新增/更新测试覆盖各 WP：retriever +2、intent_validation +5、stream_memory +3、sufficiency_classifier 新文件 10 例（mock 特征线性可分，不依赖真实 bge-m3）
- ✅ 亲自实跑全量：448 passed / 0 failed

### §8 文档验收 — 通过

- ✅ changelog.md 新建（WP1-5 + 测试回归详实）；review-report.md（本文档）
- ✅ 三个记忆文件更新：rag-architecture.md（module-045 条目）/ rag-agent-roadmap.md（模块列表 + 待办）/ MEMORY.md（已完成条目）
- ✅ 训练脚本 docstring 含用法（--model-path / --no-save / 数据源 / 特征设计 / 已知边界）

## 4. Minor 观察（不阻塞，供后续模块参考）

1. WP2d 白名单后 `confidence = probs[intent]`：若真实分类器概率字典缺 "knowledge" 键会 KeyError，被外层 except 捕获回退 LLM 分类（保守降级，行为安全；现 IntentClassifier 固定三键，理论场景）
2. 流式 L3 判定基于 _retrieve（已父块映射）的 top-1 abs_cosine，与非流式 round 0 rerank 后判定在 top-1 选择上存在细微语义差异（Dev 已在 issues_known 与代码注释注明）
3. 计数口径：448 = 428 基线（含其他会话未跟踪 test_main.py 1 例）+ module-045 新增 20（与本报告清点一致）

## 5. 结论

**approved** — WP1-5 全部满足验收标准，红线全过，全量 448/448 全绿（亲自实跑确认），无 critical/major 问题。
