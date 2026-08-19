# 功能规格说明书 — Module-054: 检索降级修复 + mDeBERTa 复测（矛盾样本）

> Planner | 2026-08-12

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-054 |
| 模块名称 | 检索降级修复（reranker 路径 + RRF 向量化降级）+ mDeBERTa 矛盾复测 |
| 版本号 | 0.54.0-module-054 |
| 优先级 | P0（reranker 影响真实聊天重排；RRF 切默认前置；mDeBERTa 替换放行前置） |
| 预估代码量 | 降级修复（~50 行）+ 矛盾样本构造（标注数据）+ 复测脚本适配 + 测试，≤ 450 行 |

---

## 2. 需求

| WP | 内容 | 来源 |
|----|------|------|
| WP-1 reranker 路径修复 | `rag/retrieval/reranker.py:34-37` `_LOCAL_MODEL_DIR` 二级 dirname → 三级（对齐 embeddings.py 修法），修复后真实加载验证（非 mock）重排正常 | module-053 known_issues（module-050 目录细分引入，与 embeddings 同款） |
| WP-2 RRF 向量化降级（方案 A 为主 + B 防御） | **方案 A**：retriever 向量化失败 → 向量路降级为空（不再抛整体异常），FTS+图谱两路照常融合出结果；**方案 B 防御**：引擎 rrf 分支 catch 到 RetrievalException 后补一次 graph_store.search_related 兜底。正常路径零开销；修复后 rrf 模式"少一路但还有两路" | 用户拍板（A 为主 + B 防御；C1 云端备胎/C2 并行向量化已评估否决） |
| WP-3 矛盾样本构造 | **随机构造 ≥30 条矛盾样本**（用户指示"多一些"）：从知识库真实文档抽取段落，人工构造两类——① claim vs 文档矛盾（文档支持 X / 答案声称 Y）② claim 内部自相矛盾；含正例（一致样本）作对照；标注指南 + 落盘 | module-052 复测计划（本批 C0 条矛盾样本无法验证矛盾判别，P1-③ 核心能力必须补验） |
| WP-4 mDeBERTa 复测 | 用真实答案句子（LLM 生成，非问题代答句）+ 矛盾样本集 + DB golden 112 题真实检索片段 → kappa 三分类 ≥0.7 放行替换；未达降级双轨（NLI 只做矛盾扫描） | module-052 决策放行条件（已入 ADR-0010） |
| WP-5 测试 + 回归 | tests/test_degradation_fix.py（reranker 路径/向量化降级 A+B/融合照常）+ tests/test_contradiction_dataset.py（样本集结构/标注一致性）；全量 pytest 648+ 全绿 | AC |

### 验收场景

```
场景 1：reranker 真实加载
  假设 直接实例化 reranker 并调用 rerank（真实模型，非 mock）
  那么 模型从 ai_service/models/bge-reranker-v2-m3/ 加载成功，返回重排结果不抛异常

场景 2：向量化失败降级（方案 A）
  假设 查询向量化抛异常（mock embedding 失败）
  那么 不再抛整体异常：FTS+图谱两路照常检索并融合出结果（rrf 模式），不空手

场景 3：向量化失败引擎兜底（方案 B）
  假设 rrf 分支 retrieve() 仍抛 RetrievalException（A 未覆盖的异常）
  那么 引擎补一次 graph_store.search_related，返回图结果（对齐 hybrid 图回退）

场景 4：矛盾样本构造
  假设 跑构造脚本
  那么 产出 ≥30 条矛盾样本（两类）+ 标注指南；与正例样本分开落盘，格式与 golden_factcheck 兼容

场景 5：mDeBERTa 复测
  假设 复测脚本跑真实答案句子 + 矛盾样本 + DB 检索片段
  那么 输出 kappa 三分类；≥0.7 → 放行替换结论；未达 → 如实标注降级双轨
```

---

## 3. 技术方案

### 3.1 涉及文件

| WP | 文件 | 操作 |
|----|------|------|
| WP-1 | `ai_service/rag/retrieval/reranker.py`（`_LOCAL_MODEL_DIR` 三级 dirname + 注释） | 修改 |
| WP-2 | `ai_service/rag/retrieval/retriever.py`（向量化失败降级分支，不再整体抛）+ `ai_service/rag/engine.py`（rrf 分支 catch 后补图兜底） | 修改 |
| WP-3 | `ai_service/eval/build_contradiction_dataset.py`（新：矛盾样本构造 + 标注指南）或并入复测脚本；样本落盘 `ai_service/eval/contradiction_dataset.json` | 新建 |
| WP-4 | `ai_service/eval/retest_nli.py`（新：真实答案句子 + 矛盾样本 + DB 检索片段 → kappa）或复用 compare_nli_models.py 扩展 | 新建/修改 |
| WP-5 | `ai_service/tests/test_degradation_fix.py` + `ai_service/tests/test_contradiction_dataset.py` | 新建 |
| 文档 | changelog / review-report / test-report + memory/ 三文件 + ADR-0010 状态更新 | 修改 |

### 3.2 关键实现约束

- **WP-1**：三级 dirname（对齐 embeddings.py:27-32 修法与注释）；修后真实加载冒烟（CrossEncoder 真实实例 rerank 一条 query，非 mock）；红线解除——本模块可以动 reranker.py（053 的红线是当时的，现在专门修它）
- **WP-2 方案 A**：`retrieve()` 向量化失败 → 日志 warning + 向量路返回空列表（与各路失败降级同款），**不再 raise RetrievalException**；融合逻辑对"向量路空"天然兼容（缺路不参与 RRF——已有实现）；**注意**：vector_only 模式保持抛错（消融评估需要区分"向量通道真不可用"），只改 hybrid/rrf/weighted 的向量化降级语义——changelog 声明此差异
- **WP-2 方案 B**：engine.py rrf 分支 catch Exception 后，补一次 `graph_store.search_related`（实体提取 + 查询，复用 hybrid 分支的既有代码路径或抽公共函数）；B 是防御层，A 修复后正常不会触发
- **WP-3 矛盾样本**：① 从 SUFFICIENCY_DATASET 文档 + golden 真实文档抽取段落 ② 两类矛盾构造（claim vs doc / claim 内部自相矛盾）③ **正例对照**（一致样本等量或按比例）④ 标注指南（含"什么是矛盾"判定标准）⑤ 样本 JSON 结构与 golden_factcheck 兼容（question/claim/doc/verdict）⑥ 人工复核标注（Developer 造 + Reviewer 抽查一致性）
- **WP-4 复测**：真实答案句子来源——LLM 生成（deepseek 真实调用，环境可用则跑；不可用则如实标注"待环境"用构造句子替代并声明）；DB golden 检索片段——DB 已修复可用（module-053）；kappa 三分类 + 二值两口径；结论写入 ADR-0010（放行/未达降级双轨）
- **诚实边界**：矛盾样本是人工构造（非真实用户对话）——方向性验证，标注经 Reviewer 抽查；复测 kappa ≥0.7 才放行替换，未达如实标注不硬推
- **不改存量测试掩盖**；全量 648+ 全绿

### 3.3 降级

| 场景 | 处理 |
|------|------|
| LLM 生成真实答案句子不可用 | 如实标注"待环境"，用构造句子替代并声明口径差异 |
| DB 检索片段不可用 | 用 SUFFICIENCY 文档替代并声明（DB 已修复，预期可用） |
| 复测 kappa < 0.7 | 如实标注"未达门槛"，结论=降级双轨（NLI 只做矛盾扫描），不伪造 |
| reranker 修复后加载仍异常 | 定位（权限/文件损坏/transformers 版本）如实报告 |

---

## 4. 依赖

- module-052（mDeBERTa 模型 + 对比脚本 + 复测计划）、module-053（DB 修复 + retriever 融合结构 + reranker 路径问题定位）
- 网络：hf-mirror/github 200（模型已本地，本模块不需下载新模型）
- 真实答案句子需要 LLM 环境（deepseek 降级链，项目 .env 配置）

## 5. 已知边界

- 矛盾样本为人工构造（非真实对话），标注一致性经 Reviewer 抽查，非多人独立标注
- 方案 A 改变 vector_only 之外的向量化失败语义（不再抛错）——消融评估路径不受影响（vector_only 保持抛错）
- 本模块不切 RRF 默认（引擎 HTTP E2E 仍待做，后续模块）；不实施 mDeBERTa 替换（复测放行后另行模块）
- 文档类（简历/弹药）按用户指示"等优化完成后进行"——本模块不改简历
- 全量 pytest 648 全绿保持（本模块新增 +N）
