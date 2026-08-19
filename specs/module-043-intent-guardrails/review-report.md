# Module-043 审查报告 — 输入防护 + Intent 校验体系

> Reviewer | 2026-08-09 | 审查对象：Dev-1（WP1+WP2）+ Dev-2（WP3+WP4+WP5）全部产出

---

## 1. 结论

**verdict: approved**（无 critical / major；4 项 minor 见 §4，不阻塞合并）

全量回归实测：**404 passed / 3 failed**（与两位 Developer 自述一致；3 项失败均为预存环境问题，红线约定不计入模块）。

---

## 2. 红线核查记录（逐条实测）

| 红线 | 核查方法 | 结果 |
|------|---------|------|
| ① L2 确认路径零 LLM | grep `LLMFactory|\.generate\(|\.chat\(|classify` 于 `ai_service/agent/router.py`：仅 `classify()` 主路径（L174-176）使用 LLM；`_deterministic_confirm` / `_fts_term_hit` / `_graph_entity_hit` / `_rule_hits` 全程零 LLM 调用（jieba 分词 + SQL FTS + Cypher + Python 子串匹配）；不走依赖 LLM 的 `graph_extractor`。另有测试级双保证：`test_confirm_path_never_calls_llm` / `test_fts_hit_path_no_llm_dependency`（patch LLMFactory.get_client 抛错，确认仍正常返回） | ✅ 通过 |
| ② 三端点 max_length=2000 | `schemas.py`：`SearchRequest.query`(L9) / `MemorySaveRequest.content`(L59) / `MemoryRecallRequest.query`(L65) 均 `Field(..., max_length=2000)`，与 ChatRequest 同值同模式（声明式约束，超长 422 不进业务逻辑） | ✅ 通过 |
| ③ L4 失败回退 LLM | `router._get_classifier`：注入优先 → 配置开关惰性加载一次，`load()` 返回 False / 抛异常 → 回退 None → LLM 路径；`classify()` L4 推理异常 → except 落 LLM 路径（`test_classifier_failure_falls_back_to_llm` / `test_lazy_load_failure_falls_back_llm` 覆盖） | ✅ 通过 |
| ④ 测试真覆盖 | 实测 `python -m pytest tests/test_golden_intent.py tests/test_schemas_validation.py tests/test_intent_validation.py -q` → **51 passed**（11+5+35）；全量 `pytest tests/ -q` → **404 passed / 3 failed**。阅读源码确认用例非摆设：L2 触发/命中/未命中/异常保守/规则否决/零 LLM 各场景、L3 纯函数 + chat 链路全 mock 端到端、L4 fit/predict_proba/回退/开关全链路 | ✅ 通过 |
| ⑤ 只动自己文件 | `git status`：module-043 改动仅 schemas.py / router.py / retriever.py / engine.py / config.py + 4 个新文件（intent_classifier / golden_intent / train_intent_classifier / 3 个测试文件）+ changelog；`agent/react.py`、`agent/langgraph_react.py`、`main.py`、`eval/faithfulness.py` 等其他会话未提交改动均未在两位 Developer 的文件清单中 | ✅ 通过 |
| ⑥ 不 stage / 不 commit 他人改动 | `git diff --cached --stat` 为空（无任何 stage 内容）；`git log` HEAD 仍为 module-042 提交（5a6eab1），无 module-043 提交 | ✅ 通过 |
| ⑦ 预存失败不计入 | 实测 `test_identity.py` 仅 1 项失败（`assert 5 == 3`，top_k 环境问题，同源确认）；`test_rerank_langgraph.py` 2 项失败（`assert 429 == 200` 外部 API 限流 + 同源 SSE 空事件），均与本次改动无关 | ✅ 通过 |

---

## 3. 验收标准逐条对照（acceptance-criteria.md）

### §1 三端点加固
| AC | 结果 |
|----|------|
| SearchRequest.query max_length=2000 → 422 | ✅ schemas.py L9 + `test_search_request_query_too_long` |
| MemorySaveRequest.content max_length=2000 → 422 | ✅ schemas.py L59 + `test_memory_save_content_too_long` |
| MemoryRecallRequest.query max_length=2000 → 422 | ✅ schemas.py L65 + `test_memory_recall_query_too_long` |
| 与 ChatRequest 模式一致（Field 声明式，不进业务逻辑） | ✅ 同值同模式 |

### §2 L2 前置校验（修订版）
| AC | 结果 |
|----|------|
| intent≠knowledge 且 confidence<0.5 才触发 | ✅ L184-187 触发条件 + 4 用例（低置信/高置信/knowledge/缺 confidence） |
| 确认动作为确定性信号，零 LLM | ✅ 红线核查记录① |
| 信号命中 → 修正 knowledge | ✅ L187-194 + `test_confirm_hit_corrects_to_knowledge` |
| 信号未命中 → 保持原判 | ✅ L195-197 + `test_no_signal_keeps_original` |
| 确认结果可观测 | ✅ `result["reason"]` 带 `L2 信号确认(signal)` + logger.info |

### §3 L3 后置校验
| AC | 结果 |
|----|------|
| top-1 abs_cosine<0.3 → suspected_misclassify | ✅ engine.chat L249-256（round 0 精排后判定） |
| 写入 ChatSteps 可观测 | ✅ steps.retrieval.suspected_misclassify + top_abs_cosine（旧字段不变） |
| 不阻塞、不改回答路径 | ✅ 纯标记；`test_suspected_misclassify_written_to_steps` 验证 message="ok"、answer 原样 |

### §4 L1 度量 + L4 分类器
| AC | 结果 |
|----|------|
| golden_intent.py 跑通：per-class P/R + 混淆矩阵 | ✅ 代码 + 11 用例 + 冒烟 baseline（Accuracy 0.9667，knowledge recall 0.9286，changelog 如实记录） |
| eval_runs 落库（git_commit+配置快照） | ✅ 复用 golden_retrieval.save_eval_run（签名逐一核对），eval_type='intent'，契约测试 2 例 |
| 评测集含闲聊/实时/边界易混（"你们网站有什么功能"） | ✅ 30 条：knowledge 14 / casual_chat 9 / realtime 7，4 条边界样本 |
| intent_classifier fit / predict_proba 校准概率 | ✅ LogisticRegression(class_weight="balanced") + predict_proba 三类和≈1 |
| router 可注入分类器，默认 LLM | ✅ 构造器注入 + PW_INTENT_CLASSIFIER_ENABLED 开关（默认 false） |
| 训练脚本可用（golden 集训练落盘） | ✅ train_intent_classifier.py（golden_intent 优先 → golden.json → 内置样本，去重保首见） |

### §5 降级
| AC | 结果 |
|----|------|
| L2 信号失败 → 保守 knowledge | ✅ `error_conservative` 返回 (True, ...) + 用例 |
| L4 缺失/失败 → 回退 LLM 零影响 | ✅ 红线核查记录③ |
| L3 反证异常 → 记日志不阻塞 | ✅ 判定为纯 dict 读取不抛错；chat() 外层 try/except 兜底 |
| 三端点正常请求零回归 | ✅ 全量 404 passed（含既有 353 基线用例） |

### §6 接口兼容
| AC | 结果 |
|----|------|
| ChatRequest/ChatResponse/ChatSteps 旧字段不变 | ✅ 仅 retrieval 新增键 |
| router.classify() 返回结构不变 | ✅ intent/confidence/reason 三键保持 |
| 10 个 Agent 工具不受影响 | ✅ router 签名不变，L2/L4 均为内部逻辑 |
| 无 LLM 二次确认（grep 红线） | ✅ 红线核查记录① |

### §7 测试验收
| AC | 结果 |
|----|------|
| test_schemas_validation +3 用例 | ✅ 实测 5 passed（2 既有 + 3 新增） |
| test_intent_validation：L2/L3/L4 | ✅ 实测 35 passed |
| test_golden_intent：混淆矩阵 + eval_runs | ✅ 实测 11 passed |
| 全量仅 3 预存失败 | ✅ 实测 404 passed / 3 failed（test_identity 1 + rerank_langgraph 2） |

### §8 文档验收
| AC | 结果 |
|----|------|
| changelog.md / review-report.md / test-report.md | ✅ changelog 完整（两段 WP 记录 + ADR 一致性 + 已知边界）；review-report 本文；test-report 由测试角色产出 |
| 记忆文件更新 | ✅ MEMORY.md / rag-architecture.md / rag-agent-roadmap.md 三处均已追加 module-043 条目（逐文件核对） |
| L4 数据约束与飞轮接口说明 | ✅ changelog + intent_classifier.py / train_intent_classifier.py docstring（fit 接受 (query,label) 列表，样本回流重训即可） |

---

## 4. Findings（4 项 minor，均不阻塞）

### F1（minor）`router.py` 规则表含 "你能做什么"/"你会什么"，与 golden 边界样本自相矛盾
- **文件**：`ai_service/agent/router.py` L66（`_RULE_TABLE`）
- **现象（实测）**：`RouterAgent._rule_hits("你能做什么？这个系统能帮我解决什么问题？")` → **True**。该样本是 `golden_intent.py` 标注为 knowledge 的边界易混样本（L59），且规则表注释声称"只收录几乎不可能出现在知识库问题中的词"。当 LLM 低置信误判该样本为 casual_chat 时，L2 的 FTS/图谱确认会被规则表否决 → 漏检保持原样，与 Dev-1 文档中"该样本留给 WP3 L2 兜底"的预期不符。现有测试 `test_rule_table_keeps_kb_boundary_samples` 只断言了"你们网站有哪些功能"/"你知道 GC 是什么吗"，恰好漏掉此样本。
- **影响范围**：有限——L2 仅低置信触发；基线显示该样本本就高置信误判（走 L3/L4 兜底）；无新增回归。
- **修复建议**：从 `_RULE_TABLE` 移除 "你能做什么"/"你会什么"（或保留但把该样本加入 `test_rule_table_keeps_kb_boundary_samples` 断言，明确接受此取舍）。WP3 冒烟三场景不受影响。

### F2（minor）`engine.py` ChatSteps 的 top_abs_cosine 在父块映射后失真
- **文件**：`ai_service/rag/engine.py` L328-329
- **现象**：`_expand_to_parents` 为父块重建 dict（仅 id/title/content/source/hybrid_score，无 abs_cosine），随后 `(docs[0].get("abs_cosine") or 0.0)` 取到 0.0。即 top-1 是父块映射结果时，steps 展示的 `top_abs_cosine` 恒为 0.0（误导）。`suspected_misclassify` 标志本身正确（round 0 展开前判定）。
- **修复建议**：round 0 判定处把 `top1_abs` 存档供 steps 展示（与标志同源），或父块映射时透传 abs_cosine。

### F3（minor）`_check_suspected_misclassify` 静态方法生产路径未使用
- **文件**：`ai_service/rag/engine.py` L118-137 vs L249-256
- **现象**：engine.chat 内联了相同判定（逻辑一致：`(docs[0].get("abs_cosine") or 0.0) < 0.3`，空列表不标记），静态方法仅被测试引用。
- **修复建议**：chat() 内调用该静态方法复用一处实现（或删除方法只留测试断言的内联语义——不建议后者，保留方法更好）。

### F4（minor）L4 路径返回的 intent 未经白名单校验
- **文件**：`ai_service/agent/router.py` L161-169
- **现象**：L4 分类器路径直接 `max(probs, key=probs.get)` 返回 intent，无 LLM 路径 `_parse_response` 的白名单兜底。内置 `IntentClassifier` 恒返回三类固定键（setdefault 补 0），仅自定义注入分类器可能产出白名单外类别。
- **修复建议**：对 L4 结果同样套用白名单校验（非法 → knowledge），一行防御。

---

## 5. 与 ADR 一致性

- **ADR-0001 Q3**：三端点 `max_length=2000` 全加、422 不做前端友好化（前端 maxlength 兜底）——严格按已定决策，未越权。
- **ADR-0003（L2 修订版）**：LLM 二次确认已否决并落实——确认动作零 LLM（grep + 测试双保证）；低置信触发保留（单向信任语义）；异常保守 knowledge；L3 用 top-1 绝对余弦 <0.3 反证（复用 module-037 abs_cosine 口径，先度量后干预）；L4 bge-m3 冻结 + 逻辑回归头（class_weight="balanced" 防不平衡学成"永远猜 knowledge"）、校准概率、可插拔注入默认 LLM。全部与 ADR 一致。

## 6. 备注

- 已知边界已如实记录（changelog）：L2 只覆盖低置信漏检（高置信漏检由 L3/L4 兜底）；流式端点（main.py，其他会话文件）未接 L3 标记；sklearn/joblib 未入 requirements.txt（环境已装，L4 启用时补录）；模型产物 joblib 不提交仓库。
- 冒烟 baseline 与训练为真实 API 运行（环境存在 429 限流），建议择时重跑获取稳定 baseline；eval_runs 首条 intent 记录待 Planner 统一提交后正式运行产生。
