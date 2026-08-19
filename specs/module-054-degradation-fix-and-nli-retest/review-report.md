# 审查报告 — Module-054: 检索降级修复 + mDeBERTa 矛盾复测

> 审查人: Reviewer
> 审查日期: 2026-08-12
> 审查范围: WP-1~WP-5 全部代码 + 标注数据 + 复测结论 + 文档
> 审查方式: 代码级核对 + 标注逐条抽查（程序化 + 人工精读）+ 测试独立复跑

---

## 1. 审查结论

**VERDICT: PASS（0 阻塞）** — 代码与 plan/AC 对齐，降级路径完备，诚实边界声明到位；标注抽查通过（1 个 [M] 口径问题 + 3 项 minor 文档问题，均非阻塞，已入修复待办）。

### 分项统计

| WP | 内容 | 状态 |
|----|------|------|
| WP-1 | reranker 三级 dirname 路径修复 | PASS |
| WP-2 | RRF 向量化降级（方案 A + 方案 B） | PASS |
| WP-3 | 矛盾样本构造 + 标注指南 + 人工复核 | PASS（附 1 [M] + 1 minor） |
| WP-4 | mDeBERTa 复测 + kappa 门槛判定 | PASS（结论降级双轨，数字吻合） |
| WP-5 | 测试 + 全量回归 | PASS（19 新增独立复跑全绿） |
| 文档 | changelog / ADR-0010 / 记忆三文件 | PASS（附 2 项 minor 数字笔误） |

---

## 2. WP-1 reranker 路径修复 — PASS

### 代码核对

`ai_service/rag/retrieval/reranker.py:34-37`：

```python
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "bge-reranker-v2-m3",
)
```

- 三级 dirname + abspath：`rag/retrieval/reranker.py` → 三级回到 `ai_service/` 根 → `ai_service/models/bge-reranker-v2-m3` ✓
- 与 embeddings.py:27-32 修法完全同款（module-050 目录细分回归）✓
- 注释说明回归成因 + module-053 前车之鉴，符合本模块"修复 + 防再犯"意图 ✓

### 测试核验

- `test_resolves_to_ai_service_models`：断言 `_LOCAL_MODEL_DIR` 落在 models/ 下且**非** rag/models/ ✓
- `test_validate_model_dir_passes_on_real_dir`：真实实例化 CrossEncoderReranker + 权重目录校验通过（模型本地必备）✓
- changelog 冒烟数字（0.9996 排首 / 10.4s 冷加载）与 053 评审同类方法一致，可信 ✓

---

## 3. WP-2 RRF 向量化降级 — PASS

### 方案 A（retriever 向量化失败 → 向量路空）

`retriever.py` `retrieve()`（~112-118 行）：

- hybrid/rrf/weighted 向量化失败 → `logger.warning` + `query_embedding = None`，不再 raise ✓
- **vector_only 保持抛错**：消融模式走 `_dispatch_mode`（160-165 行），其中 vector_only 分支仍 `raise RetrievalException("查询向量化失败")`——与 plan §3.2 "只改 hybrid/rrf/weighted 语义"完全一致，changelog 声明到位 ✓
- `_execute` / `_execute_fusion` None 快路径：
  - `_execute`（282-303 行）：仅 FTS 一路，不建向量 session、不调 `_vector_search` ✓
  - `_execute_fusion`（434-456 行）：FTS + 图谱两路照常融合，`vector_results = []` 缺路不参与 RRF（已有实现天然兼容）✓
  - 快路径零额外调用：单测断言 `_vector_search.await_count == 0` ✓
- 融合快路径中 `_retrieve_graph_only` 未包 try/except —— **安全**：该方法内部对实体提取/图查询/超时全部降级返回空（216-246 行），不会向外抛 ✓

### 方案 B（引擎 rrf 分支补图兜底）

`engine.py` rrf round-0 catch（~735-754 行）：

- `retrieve()` 抛 RetrievalException（方案 A 未覆盖，如 DB 不可用）→ `logger.warning` + 补 `_retrieve_graph_only(query, top_k)`（15s 超时）✓
- 兜底再失败 → 降级空结果（嵌套 try/except）✓
- 正常路径零开销：兜底只在 except 分支，单测断言成功路径 `_retrieve_graph_only.await_count == 0` ✓
- 复用私有方法 `_retrieve_graph_only` 而非新增代码路径——与 hybrid 分支图回退同语义，避免重复实现 ✓

### 测试核验（独立复跑 19/19 通过，见 §7）

- 方案 A：hybrid 向量化失败 → 2 篇 FTS 结果 + vector_score=0 + warning + 零向量调用 ✓
- rrf 向量化失败 → FTS+图谱融合（{1,3} 两篇）✓
- vector_only 保持抛错（pytest.raises RetrievalException）✓
- 正常路径零开销（embed_text 1 次 + vector_search 1 次）✓
- 方案 B：retrieve 抛异常 → 图兜底 3 篇；图兜底失败 → 空；正常路径零调用 ✓

---

## 4. WP-3 矛盾样本构造 — PASS（附 1 [M] + 1 minor）

### 结构核验（程序化）

| 项 | 期望 | 实际 | 状态 |
|----|------|------|------|
| 总样本数 | ≥30 矛盾 + 对照 | 56（C32 + E16 + N8） | ✓ |
| 矛盾两类 | claim_vs_doc / internal 各半 | 16 / 16 | ✓ |
| 正例对照 | entailment 等量或按比例 | 16（1:2） | ✓ |
| neutral 对照 | 存在 | 8 | ✓ |
| schema | question/claim/doc/doc_title/verdict/contradiction_type/note/part | 80 条全部齐备 | ✓ |
| verdict 值 | 三分类合法 | 全部合法 | ✓ |
| 真实对 | 24 条（LLM 答案 + DB 检索片段） | 24 条 | ✓ |

### 标注一致性抽查（本次重点）

逐条精读 16 条 internal_contradiction + 5 条 claim_vs_doc + 全部 24 条真实对：

- claim_vs_doc：反转语义精确（如"JDK 8 默认被 CMS 取代"vs 文档"JDK 9 默认"、漏桶/令牌桶双向反转、HashMap"与容量无关"vs"需 ≥64"）✓
- internal_contradiction 15/16 为同一主语 X/not-X ✓；**1 条口径不成立**：
  - **[M] AOF fsync 样本**（contradiction_dataset.json 第 290 行）："关闭 fsync 后数据更安全一点也不会丢，而默认每秒 fsync 反而会丢 1 秒数据"——两半句主语是**不同配置**（no-fsync vs everysec），非同一主语的 X/not-X，指南 §2② 不成立；doc 未提及 no-fsync 模式无冲突 → 按指南规则 3 应判 **neutral**。影响：34 条 contradiction 中混入 1 条弱标（kappa 重算可能微幅变化，方向不变）
- 真实 24 对：严格三分类口径贯穿一致——RocketMQ（"大部分一致但心跳/直连未覆盖"）、MyBatis、Seata、FullGC 均正确判 neutral，未因部分支持放松为 entailment ✓
- 点名的 2 条 contradiction：雪花"三部分 vs 四段"成立（claim 穷尽性断言被 doc 四段含符号位直接否定）；类加载"5 vs 7 阶段"可辩护但最弱（5 ⊂ 7 子集，"若 doc 为真 claim 必为假"不严格成立）——按"阶段数陈述互斥"口径自洽，已建议写入指南保证可复现
- **[minor] 口径文档化**：真实 C 用的"阶段/段数互斥"口径仅存于逐条 note，未入指南 §1，建议追加一句（已入修复待办）

### 转换层核验

`contradiction_dataset.py`：
- `load_contradiction_dataset`：≥30 校验 + 四键非空 + verdict 合法 + 正例存在 ✓
- `to_factcheck_item` / `from_factcheck_item`：三态映射（entailment→supported / neutral→inferred / contradiction→unsupported，对齐 module-052）+ roundtrip 一致 ✓（单测覆盖）

---

## 5. WP-4 mDeBERTa 复测 — PASS（结论降级双轨，数字吻合）

### 脚本核对（retest_nli.py）

- `--gen-real N`：LLM（deepseek 降级链，30s 超时）生成答案句子 + DB hybrid 真实检索（20s 超时）；环境不可用如实标注 `[LLM_UNAVAILABLE: ...]` / `[NO_DOCS]` / `[EMPTY_ANSWER]` 并计数声明 ✓
- 评估模式：constructed + real 合并 → mDeBERTa argmax 三分类 → kappa 三分类 + 二值两口径 + 混淆矩阵 + 门槛判定（≥0.7 放行 / 未达降级双轨）+ eval_runs 落库 ✓
- 降级：模型缺失明确报错（_require_model）；单条打分异常跳过其余继续 ✓

### 复测结论核验

- kappa 三分类 0.4991 / 二值 0.6176，Acc 0.6625 / 0.8375（80 对）——changelog 与 ADR-0010 记录一致 ✓
- 分部分：构造 56 对 0.4488 / 真实 24 对 0.4700，与 changelog 表格逐位吻合 ✓
- 失败模式分析诚实：internal_contradiction 大量判 neutral（矛盾判别短板确认），与 module-052 代理度量 0.4711 对比口径正确 ✓
- **结论判定正确**：0.4991 < 0.7 → 降级双轨（NLI 只做矛盾扫描，不替换 HHEM 主裁判）——如实标注不硬推，符合 ADR-0010 门槛纪律 ✓
- ADR-0010 已更新复测结果节（80 对数据表 + 失败模式 + 后续方向）✓

---

## 6. 文档核验

| 项 | 状态 |
|----|------|
| changelog.md | PASS（结论先行 + 方案 A/B 细节 + 复测表 + 诚实边界 7 条） |
| ADR-0010 复测结论写回 | PASS（"kappa 复测结果"节，数字/结论/失败模式/后续全） |
| project-context.md module-054 行 + 头部日期 + ADR 索引 | PASS |
| agent-activity-log.md Developer 行 | PASS（Reviewer/Tester 行待各自追加） |
| file-index.md 8 个新文件行 | PASS |
| 文档类（简历/弹药）未改 | PASS（用户指示遵守） |

**[minor] changelog §4 分布笔误**：写 "entailment 10 / neutral 12"，实际文件 **E9 / N13**（复测 80 对总数没错，mDeBERTa 打分以文件为准，不影响 kappa 数字）；同一笔误传播到 agent-activity-log.md Developer 行（"E10/N12/C2"）。已入修复待办。

**[minor] changelog §7 涉及文件表数字错误**：写 "test_degradation_fix.py：16 用例 / test_contradiction_dataset.py：3 用例"，实际 **9 / 10**（§5 正确写 19 = 9 + 10；§7 为复制笔误）。已入修复待办。

---

## 7. 测试独立复跑

### 新增单测（本审查独立执行）

```
python -m pytest tests/test_degradation_fix.py tests/test_contradiction_dataset.py -q
19 passed in 47.98s
```

与 changelog 声称的 19 项一致，全部通过。

### 全量回归（本审查独立复跑）

```
python -m pytest tests/ -q
667 passed, 5 warnings in 122.40s (0:02:02)
```

与 changelog 声称的 667/0（648 基线 + 19 新增）完全一致，0 failed。5 个 warning 为存量 asyncpg 连接清理 SAWarning（非本模块引入）。

### 方法长度自检

changelog 声明方案 A 注释曾致 `retrieve` 53 行触发存量 `test_retrieve_under_50`，已压缩回 50 行（非改测试掩盖）——由全量回归验证（该存量用例存在于 test_rrf_fusion.py 邻近套件）。

---

## 8. 问题清单（全部非阻塞，已入修复待办）

| # | 级别 | 问题 | 位置 | 处置 |
|---|------|------|------|------|
| 1 | [M] | AOF fsync internal_contradiction 口径不成立（两半句不同配置主语，按指南规则 3 应判 neutral） | contradiction_dataset.json:290 | 改标或改写 claim；kappa 影响方向不变 |
| 2 | [minor] | changelog §4 + activity-log 分布笔误 E10/N12 → 实际 E9/N13 | changelog.md / agent-activity-log.md | 同步修正 |
| 3 | [minor] | changelog §7 测试用例数 16/3 → 实际 9/10 | changelog.md | 同步修正 |
| 4 | [minor] | "阶段/段数陈述互斥"口径未入指南 | contradiction_annotation_guide.md §1 | 追加口径说明 |

---

## 9. 结论

WP-1~WP-5 全部达成，降级路径（方案 A 向量路空 / 方案 B 图兜底 / vector_only 抛错）语义正确且单测覆盖，诚实边界（kappa 未达标如实标注降级双轨）符合项目纪律。4 项问题均为文档/标注层 minor，不影响放行；标注 [M] 项修标后 kappa 重算方向不变（仍 < 0.7）。

**审查结论：PASS。** Tester 可开始验收。

---

## 10. 独立复核补充（Reviewer-054 轮次，2026-08-12）

本补充节由本轮审查独立完成（与上文结论相互印证，全部通过），补充上文未覆盖的独立证据：

| 独立核验项 | 方法 | 结果 |
|------|------|------|
| **WP-1 真实加载冒烟（非 mock，独立复现）** | `CrossEncoderReranker().rerank()` 真实加载 2.17GB 权重 | 模型从 `ai_service/models/bge-reranker-v2-m3/` 加载成功，G1 文档 **0.9996 排首**、无关文档 0.0/0.0，冷加载 7.4s——与 changelog §1 数字吻合，重排通道回归确认修复 |
| **WP-4 eval_runs 数据一致性** | eval_runs 表实查 id=21 per_question（80 条）vs 当前 JSON 文件 | scores：kappa_3class 0.4990724 / kappa_binary 0.6176471 / acc 0.6625/0.8375 与 ADR-0010 表逐位一致；**stored label vs real_retrieval_pairs.json 当前文件 mismatch = 0**——kappa 可从当前文件复现，无事后改数 |
| 全量回归 | `python -m pytest tests/ -q` | **667 passed / 0 failed（120.77s）**，与 changelog 648+19 一致 |
| golden 题数 | eval/golden.json | 112 题（17 类，含 resume 5）——--gen-real 抽样源确凿 |

**与上文问题清单的印证**：独立核验确认上文 §8 全部 4 项问题属实（[M] AOF fsync 样本两半句主语为不同配置（no-fsync vs everysec），按标注指南规则 3 应判 neutral——1/34 条弱标，kappa 方向不变；changelog §4/activity-log 分布笔误 E10/N12 vs 实际 E9/N13；changelog §7 测试用例数 16/3 vs 实际 9/10；"阶段/段数互斥"口径未入指南）。无新增问题。

**补充 minor（1 项，非阻塞）**：AC §1 第 3 项"真实聊天路径 E2E 冒烟"在 changelog 中仅记录了直接 reranker 真实加载冒烟（路径回归根因已覆盖），未记录 HTTP chat/stream 端点级冒烟——建议 Tester 验收时补一次真实聊天端点 E2E（rerank 真实加载不抛 RerankerException）。

**结论：PASS（0 阻塞）。** 与上文一致，Tester 可开始验收。
