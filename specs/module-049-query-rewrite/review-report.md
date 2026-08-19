# Module-049 Review Report — 分诊式 Query 改写（ADR-0009 实施）

> Reviewer | 2026-08-10 | 第一轮审查 | 结论：approve（0 major / 5 minor）

## 1. 审查范围与方法

- 代码审查：`rag/query_rewrite.py`（新）、`rag/engine.py`、`agent/router.py`、`src/config.py`（改）、`eval/golden_query_rewrite.py`（新）、`tests/test_query_rewrite.py`（新）、`specs/module-049-query-rewrite/changelog.md`
- 独立验证：`python -m pytest tests/test_query_rewrite.py -q` → 34 passed；`python -m pytest tests/ -q` → **567 passed**（533 存量 + 34 新增，无存量失败、未改存量测试）；`python -m eval.golden_query_rewrite --fixture --no-save` → 112 题跑通
- 逐条核查 `acceptance-criteria.md`（见 §3），关键事实独立复核：
  - `RouterAgent._kb_terms` 是 `@staticmethod`，模块级 `fts_term_hit()` 直接调用合法；`_fts_term_hit` 保留方法签名委托之，`tests/test_intent_validation.py` 8 处 `mock.patch.object(_fts_term_hit)` 全部兼容
  - `embedding_service.embed_documents` 异步、内部 `_normalize` L2 归一化（embeddings.py:108），点积即余弦成立
  - reranker `rerank` 原地挂 `rerank_score` 不丢 `abs_cosine`；chat 路径 `top1_abs` 在 `_expand_to_parents` 前存档（engine.py:293→321，module-045 模式保持）
  - `check_sufficiency` 空文档 → `{"sufficient": False, "rewritten_query": query}`（reflector.py:179-181），双路检索失败时 round 0 后 break，无结果降级与注释一致，不崩溃
  - `compute_metrics`/`save_eval_run`/`load_golden`/`get_git_commit`/`load_rag_config` 签名与 eval 脚本调用全部匹配；`load_sufficiency_dataset` 存在（golden_sufficiency.py:1855）
  - golden.json 112 题含 question/golden_docs/category 键

## 2. 结论

**approve**。未发现正确性/回归问题。分诊判据是纯 FTS 术语命中（零 LLM/零生成）；保真预检用 bge-m3 余弦（严格 `<0.6` 回退，预检失败跳过直接并行）；择优方向正确（改写 top-1 abs_cosine 严格大于原才用改写，相等/缺失/异常回退原）；降级链路完整（LLM 失败/超时 → 回退原话、并行单路失败用成功路、分诊 DB 异常 → 保守 vague）。HyDE、check_sufficiency、retriever/reranker 全部未动，默认关闭（opt-in）保证存量行为零回归。

## 3. 验收对照（acceptance-criteria.md 逐条）

### §1 功能验收 WP1 静态分诊 — 全过
- [x] FTS 术语命中分诊存在：`triage()` → 模块级 `fts_term_hit()`（jieba + `_FUNCTION_STOPWORDS` + 长度≥2 + search_tokens 倒排）
- [x] 判据是"词表对得上"：零 LLM、零生成，纯 SQL
- [x] 分诊失败（DB 异常/超时）→ 保守默认 `vague` 走改写，不中断链路（query_rewrite.py:79-84）
- [x] `_kb_terms` 复用而非复制：router 提取模块级 `fts_term_hit()`（逻辑单一来源），`_fts_term_hit` 委托，L2 语义不变

### §2 功能验收 WP2 改写路径 — 全过
- [x] LLM 改写独立封装 `llm_rewrite()`：10s 超时、temperature=0.1，失败/超时/空/无变化 → None 回退原话
- [x] 保真预检 `fidelity_check()`：bge-m3 批量嵌入点积（L2 归一化），`fidelity < rewrite_fidelity_threshold(0.6)` → 直接用原 query，跳过并行（严格小于，与 AC 一致）
- [x] 并行检索 `asyncio.gather(return_exceptions=True)`，单路失败降级另一路，双路失败 → 空结果走无结果降级
- [x] 择优 `select_better()`：改写 top-1 abs_cosine **严格大于** 原 → 用改写；相等/缺失/空 → 回退原（保守）；缺失按 0（module-045 口径）
- [x] 择优后 abs_cosine 存档：chat 路径 round 0 判定处 `top1_abs` 在 `_expand_to_parents` 前存档（既有 module-045 模式未被破坏）；rerank 原地透传不丢字段

### §3 功能验收 WP3 评测闭环 — 全过
- [x] `eval/golden_query_rewrite.py` 存在：真实模式跑 golden 112 题原始 vs 改写 Recall@K(K=5)/MRR + delta + 不充分题子集
- [x] `save_eval_run(eval_type="query_rewrite", ...)` 落库（复用 golden_retrieval）
- [x] `--fixture` 模式启发式分诊+改写，不依赖 LLM/DB（实测跑通，112 题；save_eval_run 内部捕获落库失败不中断）
- [x] LLM 改写失败/超时 → 记 skipped（reason="rewrite_failed"）不中断
- [x] 评测只度量不接线：直接调 `query_rewrite.llm_rewrite`/`hybrid_retriever` 对比，不改生产行为

### §4 降级验收 — 全过
- [x] LLM 改写失败 → 回退原 query（测试 test_rewrite_failed_fallback / test_rewrite_error / timeout）
- [x] 并行单路失败 → 用成功路结果（test_parallel_rewrite_side_fails / original_side_fails）
- [x] 保真预检失败 → chat 路径跳过预检直接并行（test_fidelity_unavailable_still_parallel）；prepare_query 路径保守回退（changelog 决策 3 已说明差异）
- [x] 分诊 DB 不可用 → 保守走改写路径（test_triage_error_conservative_vague）
- [x] 全量 pytest：**567 passed**（533 存量全绿 + 34 新增），实测独立复跑

### §5 接口兼容 — 全过
- [x] ChatResponse / 现有端点不变（git diff 仅 router.py/engine.py/config.py）
- [x] check_sufficiency 保留（chat 与 _retrieve 均未删；_retrieve 反思仍用原始 query，engine.py:775 未动）
- [x] HyDE 保留（round 0 `_hyde_expand(current_query)`，改写作为 HyDE 基础，正交）
- [x] retriever/reranker 核心未改（git status 确认）

### §6 测试验收 — 全过
- [x] 34 例覆盖：分诊命中/不命中/失败默认 vague；改写成功/空/异常/超时/无变化；保真余弦/正交/嵌入失败/数量异常；择优改写优/原优/相等回退/缺失按 0/空改写回退；prepare 全管线（precise 零调用/改写失败/保真未过/并行四向/预检失败仍并行）；prepare_query 四向；engine 接入（chat 不重复检索/开关关闭不调用/_retrieve 改写作 HyDE 基础）
- [x] 未改任何存量测试（git status 仅新增 test_query_rewrite.py）

### §7 文档验收
- [x] changelog.md（决策、取舍、测试结果、已知边界、验收对照齐全）
- [x] review-report.md（本文件）
- [ ] test-report.md — 待 Tester
- [ ] 记忆文件 / ADR-0009 状态更新 — 由主会话收尾（ADR 索引在知识库 project-context.md，不在仓库 docs/adr/）

## 4. Findings

### Major（必须修复）
无。

### Minor（建议，不阻塞）

1. **`prepare()` 的 `top_k` 参数是死参数**（rag/query_rewrite.py:170）：签名声明 `top_k: int = 20` 但函数体从未使用；engine 注入的 retrieve_fn lambda 自行硬编码 `top_k=20`。建议删除该参数（调用方自行决定检索深度），或真正传递使用，避免投机性接口。

2. **`_retrieve` 路径改写可能挤占 30s 预算**（rag/engine.py:686-701）：deadline 在 `prepare_query` 前设定，改写 LLM（≤10s）+ 嵌入 + HyDE（≤10s）最坏叠加可能使 round 0 的预算检查（engine.py:708）直接 break → 返回空结果，而原行为（仅 HyDE）通常能跑完 round 0。仅在启用开关且极端延迟下发生，降级优雅（走无结果路径）。建议在 `prepare_query` 后补一次 deadline 检查，超预算时跳过改写直接回退原 query。

3. **chat 路径反思检查使用改写后的 query**（rag/engine.py:307）：used_rewrite=True 时 `check_sufficiency(current_query, docs)` 基于改写 query，而 _retrieve 路径（engine.py:775）仍用原始 query。语义上可接受（检索与检查同 query 自洽），但 changelog 决策 1 "反思仍用原始 query 检查"仅对 _retrieve 成立，建议 changelog 补充说明 chat 路径差异，避免后续维护误解。

4. **eval fixture 模式演示性有限**（eval/golden_query_rewrite.py:53-69）：启发式分诊以 `_kb_terms` 非空即命中，golden 112 题全部为 precise（实测 precise_ratio=1.0），vague 分支无法在 fixture 中演示。脚本已如实标注"非真实指标"，可接受；建议 fixture 模式补一条人工构造的泛词样例以演示 vague→改写管线。

5. **fixture 模式未带 `--no-save` 时会尝试写库**（eval/golden_query_rewrite.py:338-341）：`save_eval_run` 内部捕获异常返回 0，不崩溃，但严格说"fixture 不依赖 DB"需要配合 `--no-save`。建议在 fixture 分支强制跳过落库（或文档注明），使 `--fixture` 单独使用即零 DB 依赖。

## 5. 复审建议

minor #1/#2 可在后续模块顺手修复；#3-#5 仅文档/脚本级，不阻塞合入。全量 567 全绿已实测保持。
