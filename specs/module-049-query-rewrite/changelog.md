# Module-049 Changelog — 分诊式 Query 改写（ADR-0009 实施）

> Developer | 2026-08-10 | 版本 0.49.0-module-049

## 1. 实施总结（按 WP）

### WP1 静态分诊 ✅
- 新建 `ai_service/rag/query_rewrite.py`，`triage()` 复用 router 的 FTS 术语命中：
  `agent/router.py` 把 `_fts_term_hit` 的 SQL 命中逻辑提取为模块级公开函数
  `fts_term_hit()`（jieba 分词 → `_FUNCTION_STOPWORDS` 过滤 → 长度≥2 →
  search_tokens 倒排逐词查），`RouterAgent._fts_term_hit` 委托之——**逻辑单一
  来源，L2 确认语义不变**（`tests/test_intent_validation.py` 对 `_fts_term_hit`
  的 `mock.patch.object` 仍有效）。
- 判据是"词表对得上"（检索质量信号），零 LLM、零生成；分诊 DB 异常 → 保守
  默认 `vague` 走改写路径（宁多检不漏检）。

### WP2 改写路径 ✅（chat 全管线 + 流式查询级）
- **① LLM 改写**：`llm_rewrite()` 独立封装（专用改写 prompt，temperature=0.1，
  10s 超时），失败/超时/空/无变化 → `None` 回退原话（与 HyDE 降级同哲学）。
- **② 保真预检**：`fidelity_check()` 用本地 bge-m3（现有 embedding 客户端
  `embed_documents` 一次批量嵌入两文本）算余弦；< 0.6（配置
  `rewrite_fidelity_threshold`）→ 直接用原 query 检索，省一次并行检索。
- **③ 并行检索**：`prepare()` 内 `asyncio.gather(return_exceptions=True)` 原
  query + 改写 query 各检索一次，单路失败降级为另一路，双路失败 → 空结果走
  现有无结果降级。
- **④ 择优**：`select_better()` 纯函数——改写检索 top-1 abs_cosine > 原检索
  → 用改写结果；相等/缺失/异常 → 回退原（保守，防合并噪声）；abs_cosine
  缺失按 0 处理（module-045 口径）。择优结果直接作为 round 0 文档，rerank 用
  择优 query，L3/父块映射 abs_cosine 存档链路不变。

### WP3 评测闭环 ✅
- 新建 `ai_service/eval/golden_query_rewrite.py`：真实模式跑 golden 112 题
  "原始 vs 改写" 检索对比（Hit@k/Recall@k/MRR，复用 golden_retrieval 的
  compute_metrics），eval_runs 落库 `eval_type='query_rewrite'`（复用
  save_eval_run/get_git_commit/load_rag_config）；`--fixture` 模式启发式
  分诊+改写（`_kb_terms` 拼接），不依赖 LLM/DB，如实标注"待环境"；
  `--no-save` 纯跑分。每题附带保真余弦（嵌入可得时）供阈值校准；交叉引用
  module-044 充分性标注集做"不充分题"子集增益分析。
- 评测只度量不接线（直接调 `query_rewrite.llm_rewrite` 对比检索，不改生产行为）。

### WP4 降级与回归 ✅
- 全链路降级：分诊失败 → vague 走改写；改写失败 → 回退原话；保真未过 →
  回退原话；并行单路失败 → 用成功路；双路失败 → 空结果走无结果降级。任何
  一环失败与现状行为完全一致（零回归）。
- HyDE 与 check_sufficiency 反思兜底**全部保留**，分诊改写只是"改写时机"前置。

## 2. 关键设计决策与取舍

1. **chat 主路径 = 全管线（分诊+改写+保真+并行择优）；流式/_retrieve 路径 =
   查询级（分诊+改写+保真门控，不做并行择优）**。
   理由：`_retrieve` round 0 已有向量+图并行与 HyDE 扩展（module-024），叠加
   并行检索成本翻倍且与 HyDE 语义重叠；且 `_retrieve` 有检索缓存与 30s 预算，
   改动面大、收益不确定。改写 query 通过保真后作为 HyDE 扩展的基础 query
   （改写与 HyDE 正交），反思仍用原始 query 检查（既有注释语义不变）。
   后续按真实评测数据决定是否把并行择优下沉到流式路径。
   **反思两路径差异**：chat 路径 `used_rewrite=True` 时 `check_sufficiency`
   用的是改写后的 `current_query`——改写 query 经并行择优验证优于原 query，
   反思基于更优 query 检查充分性合理；`_retrieve` 路径 `check_sufficiency`
   始终用原始 `query`（硬编码，不走 `current_query`）——无择优验证改写质量，
   保守用原 query 做充分性判据避免改写偏差影响反思质量。两条路径各从其判据
   来源，决策自洽。
2. **`query_rewrite_enabled` 默认 False（opt-in）**。与 `intent_classifier_enabled`
   / `sufficiency_self_check_enabled` 同款模式；开启方式 `PW_QUERY_REWRITE_ENABLED=true`。
   原因：① 存量 chat 测试 mock 的是 `rag.engine.LLMFactory` 命名空间，改写链路
   的 LLM 调用不在其内，默认开启会让存量用例发起真实网络 LLM 调用；② 保证
   全量回归零风险。测试通过 monkeypatch settings 显式开启验证接线。
3. **保真预检失败的处理差异**：chat 路径（有并行择优兜底）→ 跳过预检直接
   并行；`prepare_query`（无择优兜底）→ 保守回退原 query（"改写链路任何一环
   失败 = 回退原 query"的最保守解读）。
4. **router 提取采用"模块级函数 + 方法委托"**而非复制：`_fts_term_hit` 保留
   方法签名（存量测试 mock 兼容），实现唯一来源是 `fts_term_hit()`。
5. **评测 fixture 模式**：无 DB 检索 → 无 Recall 对比（如实标注待环境），
   演示分诊/改写管线 + 输出整体统计；真实模式才是 Recall/MRR 对比。
6. **改写无缓存**：`llm_rewrite` 未接 Redis 缓存（HyDE 有 `_hyde_cache_key`
   模式）。本次不加（改写是模糊 query 才触发，频率低于 HyDE；且改写带保真/
   择优判定，缓存命中语义需谨慎），列为已知边界待后续。

## 3. 测试结果

- 新增 `tests/test_query_rewrite.py` 34 例：
  - 分诊：FTS 命中→precise / 不命中→vague / 异常→保守 vague
  - 改写：成功 / 空 / 异常 / 超时（压缩 _REWRITE_TIMEOUT）/ 无变化 → 回退
  - 保真：余弦计算 / 正交为 0 / 嵌入失败→None / 数量异常→None
  - 择优：改写优 / 原优 / 相等回退原 / abs_cosine 缺失按 0 / 空改写回退原
  - prepare 全管线：precise 零调用 / 改写失败回退 / 保真未过跳过并行 /
    并行择优（改写优/原优/单路失败/双路失败）/ 预检失败仍并行
  - prepare_query：precise / 改写通过 / 保真未过与不可得回退 / 改写失败回退
  - engine 接入：chat 用并行择优文档不重复检索 / 开关关闭不调用 prepare /
    _retrieve 改写后 query 作 HyDE 基础
- 相关存量模块（intent_validation/engine/engine_latency/golden_retrieval/
  golden_sufficiency 等）88 例通过；**全量 `python -m pytest tests/ -q`：
  567 passed**（533 存量 + 34 新增），无存量用例失败、未改任何存量测试。
- `python -m eval.golden_query_rewrite --fixture --no-save`：112 题全量跑通
  （启发式管线演示）。

## 4. 涉及文件

| 文件 | 操作 |
|------|------|
| `ai_service/rag/query_rewrite.py` | 新建：triage/llm_rewrite/fidelity_check/select_better/prepare/prepare_query |
| `ai_service/rag/engine.py` | 修改：chat 接入 prepare（round 0 用择优文档）；`_retrieve` 接入 prepare_query（改写作 HyDE 基础） |
| `ai_service/agent/router.py` | 修改：`_fts_term_hit` 逻辑提取为模块级 `fts_term_hit()`，方法委托 |
| `ai_service/src/config.py` | 修改：`query_rewrite_enabled`(默认 False)、`rewrite_fidelity_threshold`(0.6) |
| `ai_service/eval/golden_query_rewrite.py` | 新建：评测闭环（真实/fixture 模式，eval_type='query_rewrite'） |
| `ai_service/tests/test_query_rewrite.py` | 新建：34 例 |
| `specs/module-049-query-rewrite/changelog.md` | 本文档 |

## 5. 已知边界 / 未完成项（诚实列出）

1. **真实模式评测待环境补跑**：`python -m eval.golden_query_rewrite`（非
   --fixture）需 DB+LLM 环境；本机未跑（与 module-047 图谱消融同类待环境项）。
2. **不充分题子集分析依赖标注对齐**：golden 112 题与 module-044 充分性标注集
   题目完全一致的数量有限，`insufficient_subset` 可能为空（脚本如实输出"待
   标注对齐后补分析"）。
3. **0.6 保真阈值是经验值**（同义改写 cosine≈0.88 实测口径），真实评测落库
   后按每题 fidelity 分布校准（脚本已带 fidelity 字段，数据就绪）。
4. **流式路径无并行择优**（见决策 1），改写收益以 chat 主路径验证为准。
5. **改写无缓存**：热点模糊 query 每次重复调 LLM（成本上限=一次 LLM 调用 +
   一次并行检索，ADR-0009 已声明）；后续可按 `_hyde_cache_key` 模式补缓存。
6. **改写质量依赖 LLM**（deepseek-v4-flash）：保真预检只拦"跑偏"不保证"更优"，
   择优失败即回退，损失上限有限；P2 专用重写器等后续模块按评测数据决定。

## 6. 验收对照（acceptance-criteria.md）

- WP1 分诊 ✅（复用而非复制，router 提取单一来源；失败保守走改写）
- WP2 改写路径 ✅（独立封装/保真预检配置化/并行 gather/择优保守回退/择优后
  abs_cosine 存档链路不变）
- WP3 评测闭环 ✅（eval 脚本 + eval_type='query_rewrite' + --fixture + 失败记
  skipped + 只度量不接线）
- WP4 降级 ✅（LLM 失败回退、单路失败用成功路、预检失败跳过/保守回退、分诊
  DB 不可用保守走改写、全量 567 全绿）
- 接口兼容 ✅（ChatResponse/端点不变；check_sufficiency 与 HyDE 保留；
  retriever/reranker 核心未动）

## 7. Minor 修复记录（2026-08-10）

以下 5 条为 Reviewer approve 后的 minor 修复，全量 567 passed 保持不变：

1. **rag/query_rewrite.py** — `prepare()` 移除未使用的 `top_k` 参数（死参数，`retrieve_fn` 闭包自行控制 top_k），同步更新 engine.py 调用处与 9 处测试调用。
2. **rag/engine.py** — `_retrieve` 路径 `prepare_query` 之后、HyDE 之前补 deadline 检查：改写 LLM（≤10s）可能消耗大部分预算导致 round 0 直接 break 返回空结果；超预算时回退原 query，保持降级优雅。
3. **specs/module-049-query-rewrite/changelog.md** — 决策 1 补充反思两路径差异说明：chat 路径 `used_rewrite=True` 时反思用改写后 query（择优已验证改写质量）；`_retrieve` 路径反思始终用原始 query（无择优验证，保守判据）。
4. **eval/golden_query_rewrite.py** — fixture 模式注入 2 条人工泛词样例（"有没有什么好办法提高性能""系统老是崩怎么办"），使输出可同时看到 precise 与 vague 两分支演示；不影响真实模式数据。
5. **eval/golden_query_rewrite.py** — fixture 模式强制跳过 eval_runs 落库（与 --no-save 等价），输出一行说明不依赖 DB 的语义。
