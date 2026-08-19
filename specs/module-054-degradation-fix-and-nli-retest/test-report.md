# Test Report — Module-054: 检索降级修复（reranker 路径 + RRF 向量化降级）+ mDeBERTa 矛盾复测

> Tester | 2026-08-12
> 验收基于 `specs/module-054-degradation-fix-and-nli-retest/plan.md` + `acceptance-criteria.md`

## 0. 结论

**验收通过（AC 33 项全过，0 阻塞）**。全量回归 667/0；冒烟全部真实环境复跑 PASS；
kappa 复测数字与 changelog / ADR-0010 / eval_runs id=21 逐位一致；记忆三文件硬核查通过。

---

## 1. 全量回归（§7-3）

```
python -m pytest tests/ -q
667 passed, 5 warnings in 142.49s (0:02:22)
```

- 648 基线 + 本模块新增 19（test_degradation_fix.py 9 + test_contradiction_dataset.py 10）=
  **667/0**，与 changelog / Reviewer 两次独立复跑一致。
- 5 个 warning 为存量（Redis setex 弃用 + SAWarning 连接池），与基线一致，非本模块引入。
- 存量测试零改动：git status 确认 tests/ 下仅有 2 个新增文件（untracked），无任何存量测试文件修改（未改测试掩盖）。

## 2. 新增单测（§7-1/§7-2）19/19 全绿

| 文件 | 用例数 | 覆盖 |
|------|--------|------|
| tests/test_degradation_fix.py | 9 | reranker 三级 dirname 解析断言（防 rag/models 回归）+ 真实目录权重校验；方案 A hybrid/rrf 向量化失败降级 + warning + `_vector_search` 零调用；vector_only 保持抛错；正常路径零开销（embed_text/向量检索各恰一次）；方案 B rrf retrieve 抛异常补图兜底 / 图兜底失败降级空 / 正常路径兜底 `await_count==0` |
| tests/test_contradiction_dataset.py | 10 | ≥30 矛盾 + claim_vs_doc/internal_contradiction 两类齐全；正例 entailment + neutral 对照及比例；question/claim/doc/verdict 四键 + verdict 合法；doc 真实内容（≥30 字符非占位符）；标注指南落盘；to_factcheck_item 三态映射 + roundtrip + JSON 文件存在 |

## 3. 冒烟复跑（全部真实环境，非 mock）

### 3.1 WP-1 reranker 真实加载（AC §1-2）

- `_LOCAL_MODEL_DIR` 解析为 `D:\AgentCoding\...\ai_service\models\bge-reranker-v2-m3`（三级 dirname，目录存在）。
- `CrossEncoderReranker()` 真实实例化，冷加载 2.17GB 权重 **8.4s**（Reviewer 复现 7.4s，量级一致），rerank [G1/Kafka/Redis 三文档] × "G1 垃圾收集器是什么"：G1 文档 **0.9995** 排首，无关文档 0.0002 / 0.0000。**重排通道恢复**。

### 3.2 WP-2 方案 A 真实验证（AC §2-1/§2-3）

真实 DB + `embed_text` mock 抛错（注意：mock 须打在 `emb.embed_text.side_effect` 子层，打在父 mock 上不会触发——Tester 首轮冒烟曾因此误判 vector_only 不抛错，修正后复验通过）：

- **hybrid**：warning「查询向量化失败，向量路降级为空」→ 返回 **5 篇 FTS 结果**（vector_score=0.0），不抛整体异常。
- **rrf（round 0）**：返回 **5 篇 FTS+图谱融合结果**（Redis 持久化文档 id=445 graph_score=1.0、vector_score=0.0），缺路不参与融合行为符合既有实现。
- **vector_only**：`RetrievalException("查询向量化失败")` **真实抛出**——消融语义保持，与 changelog 差异声明一致。

### 3.3 WP-2 方案 B 真实验证（AC §2-2）

引擎 rrf 分支 + `hybrid_retriever.retrieve` 抛 `RetrievalException`（方案 A 未覆盖异常）→ catch 后补 `_retrieve_graph_only` 兜底 → 返回 **2 篇真实图谱结果**（id=445「10-Redis持久化机制」hybrid_score=1.0、id=4005 0.625）。日志「round 0 三通道融合检索失败，引擎补图兜底」确认走防御路径。正常路径零开销由单测断言（兜底 `await_count==0`）+ 代码审查（仅 except 分支）确认。

### 3.4 AC §1-3 真实聊天路径 E2E（Reviewer 建议补跑）

`rag_engine.chat(ChatRequest(query="G1 垃圾收集器是什么？它的停顿可控吗？"))` 真实全链路（intent 分类 → 记忆召回 → query rewrite → 检索 → **真实 rerank** → 反思 → LLM 生成 → HHEM verify）：**72.0s，message=ok，sources=3，真实 G1 答案**（JDK 9 默认垃圾收集器、Region 设计）。**全程无 RerankerException**——module-053 期间真实聊天重排必挂的回归已修复。测试身份 `tester-module054-smoke` 未残留任何 DB 行（已核查清理）。

## 4. 复测 kappa 数字一致性（AC §4-3/§4-4）

双重核验：

1. **eval_runs 表实查（id=21，eval_type='nli_retest'）**：kappa_3class=0.4990724、kappa_binary=0.6176471、constructed_n=56、real_n=24、gate=0.7。
2. **独立重跑 `python -m eval.retest_nli --no-save`**（mDeBERTa 真实 fp32 打分，80 对）：

| 样本集 | 样本数 | kappa(三分类) | kappa(二值) | Acc(三分类) | Acc(二值) |
|--------|--------|--------------|------------|------------|-----------|
| **总体** | 80 | **0.4991** | 0.6176 | 0.6625 | 0.8375 |
| 人工构造 | 56 | 0.4488 | 0.7101 | 0.6429 | 0.8750 |
| 真实检索 | 24 | 0.4700 | 0.4146 | 0.7083 | 0.7500 |

混淆矩阵（行=人工，列=mDeBERTa）：contradiction 34 判对 19（11 判 neutral + 4 判 entailment）、neutral 21 判对 16、entailment 25 判对 18；误判 27 条。与 changelog §4 表逐位一致，与 ADR-0010「kappa 复测结果」节逐位一致。

**结论判定**：kappa 三分类 0.4991 < 0.7 → **降级双轨（NLI 只做矛盾扫描，不替换 HHEM 主裁判）**，ADR-0010 已写回结论 + eval_runs id=21 已落库。诚实边界成立：无伪造、无"待环境"降级（LLM/DB 本次均可用；real_retrieval_pairs.json 24 条 claim 全部为 deepseek-v4-flash 真实答案句子，无 [LLM_UNAVAILABLE]；doc 为真实 DB 检索片段）。

## 5. 抽查实现与 changelog 一致性

- **WP-1**：reranker.py `_LOCAL_MODEL_DIR` 三级 `os.path.dirname` + `abspath(__file__)`，注释对齐 embeddings.py 修法（含 module-053 回归说明）——与 changelog 一致。
- **WP-2 方案 A**：retrieve() 向量化失败 → warning + `query_embedding=None`（不再 raise）；`_execute`/`_execute_fusion` None 快路径（不建向量 session、不调 `_vector_search`）；vector_only 走 `_dispatch_mode` 保持抛错——与 changelog 差异声明一致。
- **WP-2 方案 B**：engine.py rrf 分支 catch → `hybrid_retriever._retrieve_graph_only`（15s wait_for + 失败降级空）——与 changelog 一致。
- **WP-3**：contradiction_dataset.json 实际分布 contradiction 32（claim_vs_doc 16 + internal_contradiction 16）+ entailment 16 + neutral 8 = 56，part=constructed；real_retrieval_pairs.json 24 条（E9/N13/C2）part=real_retrieval；标注指南落盘完整（判定标准/构造方法/JSON 映射/诚实边界）；`to_factcheck_item`/`from_factcheck_item` 双向转换有单测。
- **WP-4**：retest_nli.py 结构（--gen-real / 默认 / --no-save / --limit）、`GATE_KAPPA=0.7`、eval_runs 落库（eval_type='nli_retest'）——与 changelog 一致。
- **涉及文件核对**：git status 仅 ai_service 3 处修改（reranker/retriever/engine）+ 8 个新文件（build_contradiction_dataset / contradiction_dataset.py+.json / contradiction_annotation_guide.md / real_retrieval_pairs.json / retest_nli.py / 两个测试文件），与 changelog §7 一致。简历/文档类零改动。

## 6. 已知非阻塞项（Reviewer 已列待办，Tester 确认属实）

| # | 级别 | 问题 | 位置 | 影响 |
|---|------|------|------|------|
| 1 | [M] | AOF fsync 样本标 internal_contradiction 口径不成立（"关闭 fsync 更安全一点也不会丢" vs "默认 everysec 丢 1 秒"两半句主语为不同配置，按指南规则 3 应判 neutral） | contradiction_dataset.json:290 | 34 条 contradiction 中 1 条弱标；kappa 重算方向不变（仍 < 0.7），不影响结论 |
| 2 | [minor] | changelog §4 / activity-log 分布笔误 "entailment 10 / neutral 12" vs 实际文件 E9/N13 | changelog.md / memory | 纯文档笔误；复测以文件为准，kappa 数字不受影响 |
| 3 | [minor] | changelog §7 涉及文件表用例数 "16/3" vs 实际 9/10（§5 正确写 19=9+10） | changelog.md | 纯文档笔误 |
| 4 | [minor] | "阶段/段数陈述互斥"口径未入标注指南 §1 | contradiction_annotation_guide.md | 建议追加一句口径说明 |

## 7. 验收对照（AC 33 项）

| 节 | 内容 | 结果 |
|----|------|------|
| §1-1 | reranker 三级 dirname 修复 | ✅ 通过（代码 + 单测断言防回归） |
| §1-2 | 真实加载验证（非 mock） | ✅ 通过（8.4s 冷加载，G1 0.9995 排首） |
| §1-3 | 真实聊天路径重排恢复正常 | ✅ 通过（真实 chat E2E 72s message=ok，无 RerankerException） |
| §2-1 | 方案 A：hybrid/rrf/weighted 向量化失败降级 + warning | ✅ 通过（真实 DB：hybrid 5 篇 FTS / rrf 5 篇 FTS+图谱） |
| §2-2 | 方案 B：rrf 分支 retrieve 抛异常 → 补图兜底 | ✅ 通过（真实图谱：2 篇，id=445 hybrid_score=1.0） |
| §2-3 | vector_only 保持抛错 | ✅ 通过（真实抛 RetrievalException） |
| §2-4 | 正常路径零开销 | ✅ 通过（单测 await_count 断言 + 代码审查） |
| §3-1 | ≥30 矛盾两类（实际 32） | ✅ 通过 |
| §3-2 | 正例对照（entailment 16 + neutral 8） | ✅ 通过 |
| §3-3 | 标注指南落盘 | ✅ 通过（含"什么是矛盾"判定标准） |
| §3-4 | JSON 与 golden_factcheck 兼容 | ✅ 通过（to/from_factcheck_item 单测 3 项） |
| §3-5 | 人工复核（Reviewer 抽查） | ✅ 通过（1 [M] 弱标非阻塞已入待办） |
| §4-1 | 真实答案句子 LLM 生成 | ✅ 通过（24 条真实，无降级标记） |
| §4-2 | DB golden 真实检索片段 | ✅ 通过（真实 hybrid 检索） |
| §4-3 | kappa 三分类 + 二值两口径 | ✅ 通过（0.4991/0.6176，独立重跑一致） |
| §4-4 | 结论写回 ADR-0010 | ✅ 通过（未达 → 降级双轨） |
| §5-1 | LLM 不可用如实标注 | ✅ 通过（脚本降级逻辑；本次可用未触发） |
| §5-2 | DB 不可用 SUFFICIENCY 替代声明 | ✅ 通过（脚本声明；本次 DB 可用） |
| §5-3 | kappa < 0.7 如实标注 | ✅ 通过（0.4991 如实，降级双轨） |
| §5-4 | 全量 648 全绿保持 | ✅ 通过（667/0） |
| §6-1 | retriever 返回结构不变 | ✅ 通过（向量路空 = 缺路不参与，冒烟结构一致） |
| §6-2 | engine rrf 返回结构不变 | ✅ 通过（补图兜底返回图结果列表） |
| §6-3 | reranker 接口/行为不变 | ✅ 通过（仅路径修复） |
| §7-1 | test_degradation_fix.py 覆盖 | ✅ 通过（9/9） |
| §7-2 | test_contradiction_dataset.py 覆盖 | ✅ 通过（10/10） |
| §7-3 | 全量 pytest 648+ 全绿 | ✅ 通过（667/0，存量零改动） |
| §8-1 | changelog / review-report / test-report | ✅ 通过（本报告补全） |
| §8-2 | project-context module-054 行 + 头部日期 | ✅ 通过（格式对齐 + "2026-08-12（module-054 完成）"） |
| §8-3 | agent-activity-log Dev/Rev/Test 三行 | ✅ 通过（Dev + Rev 两轮 + 本行 Test） |
| §8-4 | file-index 新文件行 | ✅ 通过（8 行） |
| §8-5 | ADR-0010 状态更新 | ✅ 通过（复测结论节 + eval_runs id=21） |
| §8-6 | 开工前必读 project-context | ✅ 通过（changelog 注明） |
| §8-7 | 文档类（简历/弹药）不改 | ✅ 通过（git status 确认零改动） |

**33/33 通过，0 失败，0 阻塞**。模块标记 ✅ 完成。
