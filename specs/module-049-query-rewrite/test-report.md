# Module-049 测试报告 — 分诊式 Query 改写（ADR-0009 实施）

> Tester | 2026-08-10 | 结论：**通过**（无阻塞问题）

## 1. 全量测试

```
python -m pytest tests/ -q
→ 567 passed, 5 warnings in 127.03s（EXIT_CODE=0）
```

- 567 = 533 存量全绿 + 34 新增（`tests/test_query_rewrite.py` 收集 34 例，独立复跑确认）
- 无存量用例失败；`git status` 确认未修改任何存量测试（仅有 `tests/test_query_rewrite.py` 新增）
- 5 个 warning 均为既有用例（cache setex 弃用、asyncpg 连接池告警），非本模块引入

## 2. 冒烟评测（fixture）

```
python -m eval.golden_query_rewrite --fixture --no-save
→ Dataset: 112 questions | Evaluated: 112 | Skipped: 0 | precise_ratio=1.0000 | EXIT_CODE=0
```

- 不依赖 LLM/DB 跑通（启发式分诊+改写演示管线）；输出如实标注"非真实指标，待环境补跑真实模式"
- 额外验证 `python -m eval.golden_query_rewrite --fixture`（不带 --no-save）：本机 DB 可用，实际落库 eval_runs id=14，正常输出不崩溃

## 3. 关键实现点抽查（与 changelog/review-report 一致）

| 要点 | 位置 | 验证结果 |
|------|------|----------|
| 分诊复用 FTS 术语命中 | `agent/router.py` 模块级 `fts_term_hit()`（router.py:105）+ `triage()`（query_rewrite.py:66） | `_fts_term_hit` 提取为模块级函数并委托（router.py:320），SQL 逻辑逐字搬移，L2 语义不变；`_kb_terms` 单一来源未复制 |
| 保真预检 | `fidelity_check()`（query_rewrite.py:120），`embed_documents` 异步 + `_normalize` L2 归一化（embeddings.py:109/127），点积即余弦 | 严格 `< rewrite_fidelity_threshold(0.6)` 回退（prepare:199），与 AC 一致 |
| 并行择优 | `prepare()` gather(return_exceptions=True) + `select_better()`（query_rewrite.py:149） | 严格 `>` 才用改写；相等/缺失/异常回退原；abs_cosine 缺失按 0 |
| 择优后 abs_cosine 存档 | engine.py:293 `_check_suspected_misclassify` round 0 存档 top1_abs，321 行 `_expand_to_parents` 之前（module-045 模式保持） | rerank 原地透传不丢字段 |
| 反思/保留环节 | chat 路径 check_sufficiency（engine.py:307）；`_retrieve` 路径 line 775 反思仍用**原始 query**（非改写/HyDE） | 均未删除；HyDE 保留（engine.py:704，改写作其扩展基础） |
| 配置 | config.py:108-109 `query_rewrite_enabled=False`（opt-in）/ `rewrite_fidelity_threshold=0.6`，PW_ 前缀 | 默认关闭保证存量零回归；测试经 monkeypatch 显式开启验证接线 |
| 降级 | 分诊失败→vague；改写失败/超时/空/无变化→None；保真未过→回退原；并行单路失败→用成功路；双路失败→空结果走无结果降级 | 34 例测试全覆盖 |

## 4. AC 对照表（acceptance-criteria.md 逐条）

### §1 功能验收 WP1 静态分诊 — 全部通过
- [x] 分诊逻辑存在：`triage()` → `fts_term_hit()`（jieba 分词 + `_FUNCTION_STOPWORDS` 过滤 + 长度≥2 + search_tokens 倒排）→ 命中 precise 直接检索
- [x] 判据"词表对得上"：零 LLM、零生成，纯 FTS SQL
- [x] 分诊失败（DB 异常/超时）→ 保守默认 vague 走改写（query_rewrite.py:79-84），测试 test_triage_error_conservative_vague
- [x] `_kb_terms` 复用而非复制：router 提取模块级 `fts_term_hit()`，方法委托，逻辑单一来源

### §2 功能验收 WP2 改写路径 — 全部通过
- [x] LLM 改写独立封装 `llm_rewrite()`：10s 超时、temperature=0.1；失败/超时/空/无变化 → None 回退（5 例测试）
- [x] 保真预检：余弦 < 0.6（配置化）→ 直接用原 query 检索跳过并行（严格小于，测试 test_fidelity_reject_skips_parallel）
- [x] 并行检索：`asyncio.gather(return_exceptions=True)`，单路失败降级另一路（测试双路单向失败/双路失败）
- [x] 择优：改写 top-1 abs_cosine 严格大于原才用改写；相等/缺失 → 回退原（保守）；缺失按 0（5 例测试）
- [x] 择优后 abs_cosine 存档：round 0 判定处先存档后父块映射（engine.py:293→321），链路不丢

### §3 功能验收 WP3 评测闭环 — 全部通过
- [x] `eval/golden_query_rewrite.py` 存在：原始 vs 改写 Recall@K(K=5)/MRR + delta + 不充分题子集 + 每题保真余弦
- [x] eval_runs 落库 `eval_type='query_rewrite'`（复用 save_eval_run；实测落库 id=14）
- [x] `--fixture` 模式启发式分诊+改写，不依赖 LLM/DB（实测 112 题跑通）
- [x] LLM 改写失败/超时 → 记 skipped（reason="rewrite_failed"）不中断
- [x] 评测只度量不接线：直接调 `query_rewrite.llm_rewrite`/`hybrid_retriever` 对比，不调 prepare/prepare_query

### §4 降级验收 — 全部通过
- [x] LLM 改写失败 → 回退原 query（test_rewrite_failed_fallback / test_rewrite_error / test_rewrite_timeout_returns_none）
- [x] 并行单路失败 → 用成功路结果（test_parallel_rewrite_side_fails_uses_original / test_parallel_original_side_fails_uses_rewritten）
- [x] 保真预检失败 → chat 路径跳过预检直接并行（test_fidelity_unavailable_still_parallel）；prepare_query 路径无择优兜底，保守回退原 query（changelog 决策 3 已说明，plan §3.3 允许）
- [x] 分诊 DB 不可用 → 保守走改写路径（test_triage_error_conservative_vague）
- [x] 全量 pytest 567 全绿（533 存量 + 34 新增）

### §5 接口兼容 — 全部通过
- [x] ChatResponse / 现有端点不变（git diff 仅 router.py / engine.py / config.py；schemas 未动）
- [x] check_sufficiency 反思兜底保留（chat engine.py:307；_retrieve engine.py:775 仍用原始 query）
- [x] HyDE 保留（_retrieve engine.py:704，改写 query 作其扩展基础，正交）
- [x] retriever / reranker 核心未改

### §6 测试验收 — 全部通过
- [x] tests/test_query_rewrite.py 34 例：分诊命中/不命中/失败默认 vague；改写成功/空/异常/超时/无变化；保真余弦/正交/嵌入失败/数量异常；择优改写优/原优/相等回退/缺失按 0/空改写回退；prepare 全管线（precise 零调用/改写失败/保真未过/并行四向/预检失败仍并行）；prepare_query 四向；engine 接入（chat 用择优文档不重复检索/开关关闭不调用/_retrieve 改写作 HyDE 基础）
- [x] `python -m pytest tests/ -q` — 567 全绿

### §7 文档验收 — 部分完成
- [x] changelog.md（实施决策/取舍/测试结果/已知边界/验收对照齐全）
- [x] review-report.md（approve，0 major / 5 minor 不阻塞）
- [x] test-report.md（本文件）
- [ ] 记忆文件 / ADR-0009 状态更新 — ADR 索引在知识库 project-context.md（不在仓库 specs/adr/ 下，无 adr-0009 文件），由主会话收尾，非本模块可验证项

## 5. Review Minor 复核（均不阻塞）

1. `prepare()` 的 `top_k` 死参数（query_rewrite.py:170）— 属实，仅接口整洁问题，不阻塞
2. `_retrieve` 改写可能挤占 30s 预算 — 仅在开启开关 + 极端延迟下发生，降级优雅，不阻塞
3. chat 路径反思用改写 query vs _retrieve 用原 query 的差异 — 语义自洽，changelog 决策 1 已部分说明，不阻塞
4. fixture 启发式分诊 golden 112 题全 precise — 已如实标注"非真实指标"，不阻塞
5. fixture 不带 --no-save 会尝试写库 — 实测本机 DB 可用时正常落库（id=14），不崩溃，不阻塞

## 6. 结论

**通过**。全量 567 全绿（533 存量 + 34 新增）、fixture 冒烟跑通、AC 逐条全部通过（除 §7 ADR-0009 状态更新待主会话收尾，属流程项非实现缺陷）。无阻塞问题。
