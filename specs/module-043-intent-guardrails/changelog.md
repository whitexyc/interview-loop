# Module-043 变更记录 — 输入防护 + Intent 校验体系

> 各 WP 完成后按时间追加；与 ADR-0001 Q3、ADR-0003（L2 修订版）的一致性说明见各段。

## 2026-08-09 — WP1 三端点加固 + WP2 L1 度量（Dev-1）

### WP1 三端点加固（ADR-0001 Q3 落地）

- `ai_service/rag/schemas.py`：`SearchRequest.query` / `MemorySaveRequest.content` / `MemoryRecallRequest.query` 各补 `Field(..., max_length=2000)`，与 ChatRequest 同值（对齐 module-042 模式，每处一行 Field）
- 超长请求由 FastAPI 返回 422，不进业务逻辑；`/ai/memory/save` 落库防污染
- 测试：`tests/test_schemas_validation.py` +3 用例（对齐该文件现有风格，超长 2001 字符 → 422 ValidationError）

### WP2 L1 度量（ADR-0003 L1 落地）

- 新建 `ai_service/eval/golden_intent.py`：
  - 内嵌 30 条 intent 评测集（knowledge 14 / casual_chat 9 / realtime 7），含 4 条边界易混样本（"你们网站有什么功能"等——看似闲聊实为知识库，LLM 常见误判区）
  - 混淆矩阵输出（行=真实意图，列=预测意图）+ per-class 精确率/召回率/F1/support + 整体 accuracy（knowledge 行 = 漏检分布，重点）
  - eval_runs 版本化落库：eval_type='intent' + git_commit + rag_config 快照 + scores/per_question（复用 golden_retrieval.py 的 save_eval_run / get_git_commit / load_rag_config）
  - 降级：单条分类失败 → 跳过记录不中断；数据库不可用 → 落库警告不影响评估
  - 用法：`python -m eval.golden_intent`（默认落库）/ `--no-save` 纯跑分
- 新建 `tests/test_golden_intent.py`：11 用例（混淆矩阵计算、数据集结构校验、run_eval 打桩端到端、eval_runs 落库契约），异步路径 asyncio.run + stub，不依赖 DB/LLM

### 与 ADR 一致性

- ADR-0001 Q3：三端点全加 max_length=2000；422 错误消息不做前端友好化（前端 maxlength 兜底），对齐已定决策
- ADR-0003 L1：评测集按"闲聊/实时/边界易混"扩充；指标含 knowledge Recall（漏检率）重点；eval_runs eval_type='intent' 版本化回归
- ADR-0003 修订版：本 WP 无任何 LLM 二次确认动作（L2 属 WP3 范围，由确定性信号确认）
- 红线核查：未触碰其他会话未提交文件（agent/react.py、agent/langgraph_react.py、main.py、eval/faithfulness.py 等）

### L1 冒烟 baseline（真实 LLM 分类，--no-save）

`python -m eval.golden_intent --no-save` 全量跑通（30/30 评估，0 跳过）：

- Accuracy 0.9667；knowledge recall 0.9286（14 中漏 1）——**漏检样本正是边界易混样本**："你能做什么？这个系统能帮我解决什么问题？" 被 LLM 误判为 casual_chat（confidence 高），为 WP3 L2 确定性信号确认提供实证 baseline（LLM 高置信也会漏检，确认信号不能只依赖低置信触发，术语命中是独立防线）
- Per-class：casual_chat P=0.90/R=1.00、knowledge P=1.00/R=0.9286、realtime P=R=1.00
- 改 prompt 后重跑对比，即版本化回归基线

### 测试结果

- `pytest tests/test_schemas_validation.py tests/test_golden_intent.py`：16 passed（5 + 11）
- 全量 `pytest tests/ -q`：369 passed / 3 failed —— test_identity.py 1 项预存 top_k 环境问题 + test_rerank_langgraph.py 2 项外部 API 429 限流（环境问题，均与本次改动无关：改动仅 3 个无关请求模型字段 + 2 个新文件）

## 2026-08-09 — WP3 L2 前置校验 + WP4 L3 后置反证 + WP5 L4 分类器（Dev-2）

### WP3 L2 前置校验（ADR-0003 修订版落地，最关键）

- `ai_service/agent/router.py`：
  - `classify()` LLM 分类后新增 L2：`intent≠knowledge 且 confidence<0.5`（低置信触发；confidence 缺失不触发——降级/mock 结果无"不放心"信号，零回归既有测试）→ 确定性信号确认
  - `_deterministic_confirm()`（**与 LLM 完全无关**，红线：确认路径零 LLM 调用——测试级 + grep 级双保证）：
    - ① FTS 术语命中 `_fts_term_hit`：jieba 分词 → `documents.search_tokens` 倒排匹配（`to_tsvector('simple') @@ plainto_tsquery`，复用 module-020 通道；排除 memory:%；`_kb_terms` 过滤功能词/单字，"什么/区别"等无判别力词不参与），命中 ≥1 专有术语 → 确认
    - ② 图谱实体命中 `_graph_entity_hit`：Cypher 拉实体名（LIMIT 200）→ Python 子串匹配（确定性，不走依赖 LLM 的 graph_extractor）
    - ③ 规则表 `_rule_hits`（"几点/天气/你是谁"等，只收几乎不可能出现在知识库问题中的词——"时间/温度"会误伤"停顿时间模型"类问题，不收）→ 命中保持原判（否决 FTS/图谱的巧合命中，如"现在"出现在文档中）
  - 任何异常 → 保守 knowledge（宁多检不漏检，AC 场景 4）
  - 确认结果可观测：`result["reason"]` 带 `L2 信号确认(signal)` + logger.info
- 已知边界（诚实记录）：L2 只覆盖**低置信**漏检（ADR-0003 修订版单向信任：绝对值不可信，但低置信是有效的"不放心"信号）；WP2 baseline 显示高置信也会漏检（"你能做什么"误判 casual），该部分由 L3 后置反证 + L4 分类器兜底，不放大 L2 触发面

### WP4 L3 后置反证（先度量后干预）

- `ai_service/rag/retriever.py`：`_execute()` 归一化前保存向量通道原始绝对余弦 `abs_cosine`（pgvector `1 - (embedding <=> query)`，min-max 归一化会覆盖 score，故先存档；module-037 同名字段口径）
- `ai_service/rag/engine.py`：
  - `chat()` 检索精排后（round 0 top-1）`abs_cosine < 0.3` → `suspected_misclassify=True`（logger.info + ChatSteps 可观测）；**不阻塞、不改回答路径**（先度量后干预，干预留后续模块）
  - 新增静态方法 `_check_suspected_misclassify(docs, threshold=0.3)`（复用 `d.get("abs_cosine", 0.0)` 口径，缺字段视为 0.0 → 保守标记；空列表不标记）
  - 最终 ChatResponse 携带 `steps=ChatSteps(intent=..., retrieval={count, top_abs_cosine, suspected_misclassify})`——旧字段不变，仅新增键（接口兼容 AC §6）；L2 修正后的最终意图也在 steps 中可见
- 边界：流式端点（main.py，其他会话负责）暂未接入该标记，本次仅覆盖 engine.chat 非流式路径

### WP5 L4 分类器（bge-m3 冻结 + 逻辑回归头）

- 新建 `ai_service/agent/intent_classifier.py`：`IntentClassifier`（模型路径 `ai_service/models/intent_clf.joblib`，对齐本地模型存放约定）
  - 特征：复用 `rag.embeddings.embedding_service`（bge-m3 冻结 1024 维）
  - 分类头：`LogisticRegression(max_iter=500, class_weight="balanced")`（~1025 参数/类；balanced 抗 golden 天然不平衡，避免"永远猜 knowledge"——ADR-0003 L4 警告）
  - `fit(samples, save=True)` / `predict_proba()`（返回三类校准概率，和≈1，缺类补 0 保契约）/ `load()`（缺失/损坏 → False）
  - sklearn/joblib 惰性导入：主链路不硬依赖；requirements.txt 未动（环境已装，L4 启用时建议补录）
- 新建 `ai_service/eval/train_intent_classifier.py`：`python -m eval.train_intent_classifier`（--no-save 纯评估）
  - 样本组装容错：golden_intent 评测集（WP2 `INTENT_DATASET`，已对接）优先 → golden.json knowledge 样本 → 内置手工闲聊/实时/边界易混样本（ADR-0003 示例），去重保首见
  - **数据约束（验收 §8）**：真实飞轮数据（👍/👎）未积累，先以 golden 集训练；飞轮接口预留——样本回流后并入 `load_training_samples()` 重训即可，`fit()` 接口无需变更
- `ai_service/src/config.py`：+`intent_classifier_enabled: bool = False`（PW_INTENT_CLASSIFIER_ENABLED，配置开关，默认 false = 仍用 LLM）
- `ai_service/agent/router.py`：`RouterAgent(provider=None, intent_classifier=None)` 可插拔注入；未注入且开关开启 → 惰性加载一次（`_get_classifier`），模型缺失/加载/推理失败一律回退 LLM 分类（零影响，AC §5）
- 边界：模型产物（joblib）不提交仓库，由训练脚本本地产出；L4 上线即替换决策主体，L2 触发门槛从此可信（ADR-0003 修订记录）

### 测试（tests/test_intent_validation.py，35 用例全过）

- L2：触发条件 4 例（低置信触发/高置信跳过/knowledge 跳过/缺 confidence 跳过）+ 命中修正/未命中保持/异常保守 + 确定性确认 8 例（FTS/图谱/规则否决/异常降级/**红线：确认路径零 LLM 测试**——patch LLMFactory 抛错确认不调用）+ 术语过滤 + 规则表样本
- L3：`_check_suspected_misclassify` 5 例（命中/未命中/边界=阈值不标记/空列表/缺字段默认 0）+ chat 链路 steps 可观测 2 例（低相似标记 / 高相似不标记，全 mock 无 DB）
- L4：fit/predict_proba 校准概率（mock 特征向量，线性可分）+ 模型缺失 load=False + 未加载推理抛错 + router 注入/默认 LLM/失败回退/开关惰性加载 4 例

### 与 ADR 一致性

- ADR-0003 修订版：L2 确认动作**零 LLM**（同源复核否决落实）；低置信触发保留（单向信任）；任何异常保守 knowledge
- ADR-0003 L3：top-1 绝对余弦 < 0.3 反证，复用 module-037 abs_cosine 字段，只度量不改路径
- ADR-0003 L4：bge-m3 冻结 + 逻辑回归头（~1025 参数）、校准概率、可插拔开关默认 LLM、golden 集即训练集
- 红线核查：只动本 WP 文件（router.py / retriever.py / engine.py / config.py / 2 个新文件 + 测试）；未触碰其他会话未提交文件（react.py、langgraph_react.py、main.py、faithfulness.py 等）；未运行 git commit

### 测试结果

- `python -m pytest tests/test_intent_validation.py -q`：35 passed
- 全量 `pytest tests/ -q`：404 passed / 3 failed —— 与改动前基线（369 passed/3 failed，WP1+WP2 后 404 含本 WP 35 新用例）完全一致：test_identity.py 1 项预存 top_k 环境问题 + test_rerank_langgraph.py 2 项外部 API 429 限流（环境问题，均不计入模块）。零回归。
- 真实 DB 冒烟（L2 三验收场景）：confirm("你知道 GC 是什么吗") → True fts_term；confirm("现在几点了") → False rule_veto；confirm("周末去哪玩") → False no_signal

## 2026-08-09 — Tester 全量回归交接（test-report.md 详见）

### 回归结果

- 全量 `python -m pytest tests/ -q`：**404 passed / 3 failed**（114.57s）——与改动前基线完全一致，零回归
- 本模块新增 51 测试独立复跑：**51 passed**（test_golden_intent 11 + test_schemas_validation 5 + test_intent_validation 35）
- 3 个失败均为预存/环境问题，不计入模块（详见 test-report.md §3）：
  - `test_identity.py::test_identity_passed_to_service` — 预存 top_k 环境问题（assert 5 == 3，memory_service top_k 默认值不一致，非本模块引入）
  - `test_rerank_langgraph.py` 2 项（429 限流 / 事件流为空）— 全量运行本地限流器触发；**独立运行该文件 18 passed** 证实为顺序/限流环境问题
- 红线核查（Tester 复验）：确认路径零 LLM（grep router.py，LLMFactory 仅 classify() 主路径 L174-176）；未 stage/提交其他会话文件；未运行 git commit

### 验收对照结论（acceptance-criteria.md 8 节 27 项全过）

- §1 三端点 max_length=2000：schemas.py L9/L59/L65 同值同模式，3 个超长 422 用例通过
- §2 L2：低置信触发/零 LLM 确认/命中修正/未命中保持/可观测——35 用例中 L2 部分全过
- §3 L3：top-1 abs_cosine<0.3 标记 + ChatSteps 可观测 + 不阻塞——全过
- §4 L1/L4：混淆矩阵 + eval_runs 落库 + 边界样本 + fit/predict_proba + 注入开关默认 LLM + 训练脚本——全过
- §5 降级：L2 异常保守 knowledge / L4 回退 LLM / L3 无异常面 / 短请求零回归——全过
- §6 接口兼容：旧字段不变 / classify() 结构不变 / 工具未动 / 无 LLM 二次确认（grep + 测试双保险）——全过
- §7 测试验收：51 新增用例全过，全量仅 3 预存失败——全过
- §8 文档：changelog / review-report / test-report / 记忆文件 / L4 数据约束说明——完成

**verdict: pass**
