# Changelog — Module-054: 检索降级修复（reranker 路径 + RRF 向量化降级）+ mDeBERTa 矛盾复测

> Developer | 2026-08-12
> 开工前已读 `memory/project-context.md` 全文（module-001~053 迭代状态，避免重复/冲突）。

## 0. 结论先行

- WP-1 reranker 路径修复：**已修复 + 真实加载冒烟 PASS**（三级 dirname，模型从
  `ai_service/models/bge-reranker-v2-m3/` 真实加载，G1 查询重排正确 0.9996 排首）。
- WP-2 RRF 向量化降级：**方案 A（向量路空，不抛整体异常）+ 方案 B（引擎补图兜底）已实现**，
  真实验证 PASS（hybrid/rrf 双模式 + vector_only 保持抛错），正常路径零开销。
- WP-3 矛盾样本：**56 条构造样本落盘**（矛盾 32 = claim_vs_doc 16 + internal 16，
  正例 entailment 16，neutral 8）+ 标注指南。
- WP-4 mDeBERTa 复测：**kappa 三分类 0.4991 < 0.7 未达放行门槛，如实标注 —— 降级双轨
  （NLI 只做矛盾扫描，不替换 HHEM 主裁判）**，结论已写回 ADR-0010（eval_runs id=21）。
- WP-5 测试：新增 19 个用例（test_degradation_fix.py 9 + test_contradiction_dataset.py 10）；
  全量 pytest 回归结果见下。

## 1. WP-1 reranker 路径修复（module-050 目录细分回归）

- 缺陷：`rag/retrieval/reranker.py:34-37` `_LOCAL_MODEL_DIR` 用**二级** `os.path.dirname`
  解析到 `rag/models/bge-reranker-v2-m3`（不存在）→ 真实聊天重排抛 RerankerException。
  与 module-053 修复的 embeddings.py 同款回归（module-050 目录细分引入）。
- 修复：改为**三级** dirname + `abspath(__file__)`（对齐 embeddings.py:27-32 修法与注释），
  `models/bge-reranker-v2-m3` 解析正确。
- 真实加载冒烟（非 mock）：`CrossEncoder` 真实实例加载 2.17GB 权重，rerank
  [G1 文档 / Kafka 文档 / Redis 文档] × "G1 垃圾收集器是什么" → 相关文档 0.9996 排首、
  无关 0.0009/0.0000，10.4s（含冷加载）。**重排通道恢复**。

## 2. WP-2 RRF 向量化降级（方案 A 为主 + B 防御）

### 方案 A：retriever 向量化失败 → 向量路降级为空

- `retriever.retrieve()`：hybrid/rrf/weighted 模式 `embed_text` 失败 → warning +
  `query_embedding=None`（不再 `raise RetrievalException`）。FTS 与图谱照常检索融合。
- `_execute` / `_execute_fusion`：`query_embedding=None` 快路径——仅 FTS（fusion 模式
  FTS+图谱）检索，**不建向量 session、不调 `_vector_search`**（降级路径零额外调用）；
  下游融合对"向量路空"天然兼容（缺路不参与 RRF/加权，已有实现）。
- **差异声明（changelog 义务）**：`vector_only` 消融模式保持抛错（评估需要区分
  "向量通道真不可用"，`_dispatch_mode` 语义不变）——只改 hybrid/fusion 语义。
- 真实验证（真实 DB）：hybrid + mock embedding 故障 → 5 篇 FTS 结果返回无异常；
  rrf + 故障 → FTS+图谱融合出结果（graph_score/vector_score=0）；FTS 0 命中查询
  与 fts_only 对照一致（plainto_tsquery 全词 AND 召回特性，非降级问题）；
  vector_only 抛 RetrievalException。

### 方案 B：引擎 rrf 分支补图兜底（防御层）

- `engine._retrieve` round 0 fusion 分支：retrieve() 仍抛 RetrievalException（方案 A
  未覆盖的异常，如 DB 不可用）→ catch 后补一次 `hybrid_retriever._retrieve_graph_only`
  （实体提取 + 图查询 + 失败降级为空，与 hybrid 分支图回退同语义），15s 超时。
- 真实验证（真实图谱）：rrf + retrieve 抛异常 → 补图兜底返回真实图结果
  （Redis 持久化文档 id=445，hybrid_score=1.000）。
- 正常路径零开销：兜底只在 except 分支，单测断言 retrieve 成功时 `_retrieve_graph_only`
  await_count == 0。

## 3. WP-3 矛盾样本构造（≥30 条，实际 32 条矛盾 + 对照）

- 数据源：知识库真实文档段落（SUFFICIENCY_DATASET 同源内嵌片段，非虚构）。
- 构成 56 条（`eval/contradiction_dataset.json`）：
  - **contradiction 32**：claim_vs_doc 16（文档支持 X，答案声称 not-X，如"G1 是
    JDK 8 默认"vs 文档"JDK 9 默认"）+ internal_contradiction 16（claim 句内
    "X 且 not-X"，如"G1 是 JDK 9 默认，但它自 JDK 9 起不再使用"）。
  - **entailment 16**（正例对照，1:2 比例）：claim 为文档原文陈述。
  - **neutral 8**：claim 与文档主题无关。
- 标注指南落盘 `eval/contradiction_annotation_guide.md`："什么是矛盾"判定标准
  （NLI 三分类定义 + 复合 claim 规则）+ 两类矛盾构造方法 + 诚实边界。
- JSON 与 golden_factcheck 兼容（question/claim/doc/verdict ↔ question/documents/label，
  verdict→label 映射 entailment→supported / neutral→inferred / contradiction→unsupported，
  与 module-052 三态映射一致），`eval/contradiction_dataset.py` 提供
  to_factcheck_item / from_factcheck_item 双向转换（有单测覆盖）。
- 人工复核：Developer 构造 + Reviewer 抽查标注一致性（本模块产出后已提请 Reviewer 抽查）。

## 4. WP-4 mDeBERTa 复测（ADR-0010 P1-③ 放行前置）

- 复测脚本 `eval/retest_nli.py`：`--gen-real N` 生成真实候选对（LLM 答案句子 +
  DB golden 检索片段）→ 人工标注 verdict → 默认模式加载 contradiction_dataset.json +
  real_retrieval_pairs.json → mDeBERTa argmax 三分类 → kappa 三分类 + 二值两口径 +
  混淆矩阵 + 门槛判定（≥0.7 放行 / 未达降级双轨）+ eval_runs 落库（eval_type='nli_retest'）。
- 数据（80 对）：
  - 人工构造 56 对（如上）；
  - 真实检索 24 对：golden 112 题按步长抽样，LLM（deepseek-v4-flash 真实调用）
    生成答案句子为 claim，DB hybrid 真实检索 top 片段为 doc，人工标注
    （entailment 9 / neutral 13 / contradiction 2，标注口径见标注指南，严格三分类：
    全部子断言被支持才 entailment）。
- 实测（mDeBERTa-v3 本地 fp32，eval_runs id=21）：

| 样本集 | 样本数 | kappa(三分类) | kappa(二值) | Acc(三分类) | Acc(二值) |
|--------|--------|--------------|------------|------------|-----------|
| **总体** | 80 | **0.4991** | 0.6176 | 0.6625 | 0.8375 |
| 人工构造 | 56 | 0.4488 | 0.7101 | 0.6429 | 0.8750 |
| 真实检索 | 24 | 0.4700 | 0.4146 | 0.7083 | 0.7500 |

- **结论：kappa 三分类 0.4991 < 0.7 未达放行门槛，如实标注 —— 降级双轨（NLI 只做矛盾
  扫描，不替换 HHEM 主裁判）**，结论已写回 ADR-0010。
- 失败模式：contradiction 34 条判对 19（11 判 neutral + 4 判 entailment）；
  **internal_contradiction 大量判 neutral**（mDeBERTa 对"X 且 not-X"混合断言取
  "部分相关"倾向中立）；claim_vs_doc 反转断言判 neutral/entailment 各半。
  对比 module-052 代理度量 0.4711（contradiction 0 条）——矛盾判别能力经本次
  **真实矛盾样本验证后确认仍是短板**，放行不成立。
- 诚实边界：矛盾样本人工构造（非真实用户对话）；真实检索对 claim 为 LLM 生成答案
  句子（真实链路）、doc 为真实检索片段，人工标注 Developer 完成 + Reviewer 抽查；
  LLM/DB 本次均可用（无"待环境"降级）。

## 5. 测试

- 新增 `tests/test_degradation_fix.py`（9 用例）：reranker 三级路径解析 + 真实目录
  校验；方案 A hybrid/rrf 向量化失败降级 + warning 断言 + 向量检索零调用；vector_only
  保持抛错；正常路径零开销（embed_text 一次 + 向量检索一次）；方案 B rrf retrieve
  抛异常补图兜底 / 图兜底失败降级空 / 正常路径兜底零调用。
- 新增 `tests/test_contradiction_dataset.py`（10 用例）：≥30 矛盾 + 两类齐全 + 正例
  对照比例；question/claim/doc/verdict 结构 + verdict 合法 + 文档真实内容 + 标注指南
  落盘；golden_factcheck 兼容（to_factcheck_item 映射 + roundtrip + JSON 文件存在）。
- 全量回归：**667 passed / 0 failed**（648 基线 + 19 新增；方法长度自检回归已修——
  方案 A 注释使 `retrieve` 53 行触发存量 `test_retrieve_under_50`，压缩注释回 50 行，
  非改测试掩盖）。
- 不改存量测试；mock 合理（方案 B 引擎级 mock、方案 A 通道级 mock）。

## 6. 已知边界（诚实记录）

1. 矛盾样本为人工构造（非真实用户对话），方向性验证；标注一致性经 Reviewer 抽查
   （非多人独立标注）。
2. 复测 kappa 0.4991 < 0.7 **未达放行门槛**，结论=降级双轨（NLI 只做矛盾扫描），
   不实施 mDeBERTa 替换；HHEM 保持现状主裁判。矛盾判别短板待后续：句级拆解后判别
   （internal_contradiction 拆子句）、置信度阈值校准（低置信降级 inferred）、标注集扩充。
3. 真实检索对中 contradiction 仅 2 条（检索质量高时真实答案与文档冲突少）——矛盾
   判别主要靠构造样本验证；真实部分验证了 entailment/neutral 判别（kappa 0.4700）。
4. 方案 A 改变了 vector_only 之外的向量化失败语义（不再抛错）——消融评估路径不受
   影响（vector_only 保持抛错），changelog 声明此差异。
5. 本模块不切 RRF 默认（引擎 HTTP E2E 仍待做，后续模块）；不实施 mDeBERTa 替换
   （复测未放行）。
6. 方法长度自检回归（module-053 同款）：方案 A 注释使 `HybridRetriever.retrieve`
   53 行 → 压缩注释回 50 行，全量复跑确认（非改测试掩盖）。
7. 文档类（简历/弹药）不改（用户指示：等优化完成后进行）。

## 7. 涉及文件

| 文件 | 操作 |
|------|------|
| `ai_service/rag/retrieval/reranker.py` | 修改：`_LOCAL_MODEL_DIR` 三级 dirname |
| `ai_service/rag/retrieval/retriever.py` | 修改：方案 A（retrieve 降级 + _execute/_execute_fusion None 快路径） |
| `ai_service/rag/engine.py` | 修改：方案 B（rrf 分支 catch 补图兜底） |
| `ai_service/eval/build_contradiction_dataset.py` | 新建：矛盾样本构造脚本 |
| `ai_service/eval/contradiction_dataset.py` | 新建：样本集加载/校验/golden_factcheck 转换 |
| `ai_service/eval/contradiction_dataset.json` | 新建：56 条构造样本落盘 |
| `ai_service/eval/real_retrieval_pairs.json` | 新建：24 条真实检索对（人工标注） |
| `ai_service/eval/contradiction_annotation_guide.md` | 新建：标注指南 |
| `ai_service/eval/retest_nli.py` | 新建：mDeBERTa 复测脚本（kappa + 门槛判定 + 落库） |
| `ai_service/tests/test_degradation_fix.py` | 新建：9 用例 |
| `ai_service/tests/test_contradiction_dataset.py` | 新建：10 用例 |
| `specs/adr/0010-hallucination-detection-upgrade.md` | 修改：P1-③ 复测结论（未达 → 降级双轨） |
| `memory/` 三文件 | 修改（Developer 活动行/模块清单/file-index 追加） |

## 8. Minor 修复记录（Reviewer 非阻塞待办 5 项，2026-08-12 修复）

| # | 修复内容 | 文件 | 结果 |
|---|---------|------|------|
| 1 | **[M]** AOF fsync 弱标样本改判 neutral：两半句主语为不同配置（no-fsync vs everysec），非同一主语 X/not-X，句内自相矛盾不成立，doc 未覆盖 no-fsync（信息不足）→ 按指南规则 3 判 neutral；样本从 internal_contradiction 移入 neutral 类（note 注明改标理由），分布 C32/E16/N8 → **C31/E16/N9**（总数 56 不变） | `eval/build_contradiction_dataset.py` + `eval/contradiction_dataset.json`（重生成） | **kappa 重算（80 对真实 mDeBERTa，eval_runs id=22）：三分类 0.4991 → 0.5167**，二值 0.6176 不变（改标在非 entailment 类内部），Acc 0.6625 → 0.6750，误判 27 → 26；**仍 < 0.7，降级双轨结论不变**（改标样本模型原判 neutral，改后由误判变判对） |
| 2 | 真实检索对分布笔误 "entailment 10 / neutral 12 / contradiction 2" → 实际 **9 / 13 / 2**（与 real_retrieval_pairs.json 一致） | 本 changelog §4 + `memory/agent-activity-log.md` Developer 行 | 纯文档修正，kappa 数字不受影响 |
| 3 | 涉及文件表用例数笔误 16/3 → 实际 **9/10**（与 §5"19 = 9 + 10"及 test-report 一致） | 本 changelog §7 | 纯文档修正 |
| 4 | "阶段/段数穷尽性陈述互斥"口径入指南：claim 与 doc 对同一事物做数字互斥的穷尽性断言（类加载 5 vs 7 阶段、雪花三部分 vs 四段）→ contradiction；并附不同主语（不同配置）互不否定的 AOF 反例 | `eval/contradiction_annotation_guide.md` §1 判定要点 4（build 脚本 GUIDE_MD 同步） | 判定标准可复现，与真实检索对 note 口径一致 |
| 5 | 真实聊天路径 E2E 冒烟补记录（AC §1-3）：`rag_engine.chat(ChatRequest("G1 垃圾收集器是什么？它的停顿可控吗？"))` 真实全链路（intent → 记忆 → 检索 → **真实 rerank** → 生成 → verify） | 本 changelog（Tester 已补跑 72.0s 后再独立验证） | **76.0s，message=ok，sources=3（真实 G1 文档），全程无 RerankerException —— 通过**；HHEM verify 15s 超时走既有 LLM 判分降级（module-039 设计，与 rerank 修复无关） |

- 改标后单测零改动仍全绿（19/19：test_contradiction_dataset 10 + test_degradation_fix 9，C31 ≥ 30、两类齐全断言不受影响——数据修正非掩盖）。
- 全量回归复跑：**667 passed / 0 failed**（与基线一致，5 存量 warning）。
