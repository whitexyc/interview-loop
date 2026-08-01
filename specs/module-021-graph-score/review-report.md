# 审查报告 — Module-021: 图分数归一化（graph_score 真实相关度）

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: 约 30 分钟

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `ai_service/rag/graph_store.py` | L290 | `OPTIONAL MATCH (e)-[r:RELATED_TO]->(related:Entity)` 绑定了未使用的边变量 `r`（后续只引用 `related`） | 低 | 去掉变量绑定，改为 `OPTIONAL MATCH (e)-[:RELATED_TO]->(related:Entity)` |
| 2 | `specs/module-021-graph-score/changelog.md` | 关键设计说明 4 | "新池 ⊇ 旧池"表述精度：新 Cypher 的 `LIMIT top_k*2` 作用于聚合后的 **doc_id 集**（最多 2k 个不同 doc_id），而旧 Cypher 的 `LIMIT` 作用于行（每行一个 doc_ids 数组，union 后原始规模可超过 2k）。方向上每 (e,related) 行新查询确实同时包含 e.doc_ids 与 related.doc_ids（旧查询仅 e 无 related 时才含 e.doc_ids），故"召回不降"结论成立，但建议补充"LIMIT 作用于去重后 doc_id"的说明 | 低 | 在 changelog 补一句"新池按命中数取 top 2k doc_id，池内选择更相关；A/B 0.6957>0.6522 与机制验证 19/19 佐证无召回下降" |
| 3 | `ai_service/tests/test_graph_store.py` | TestSearchRelated | 未覆盖 `ranked[:top_k]` 的 top_k 截断、以及命中数并列时的排序稳定性 | 低 | 补一条：Cypher 返回 5 行、top_k=3 时断言输出长度为 3；可选补并列命中数时输出稳定的断言 |

### 2.3 待复核项（非代码缺陷，环境阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 建议 |
|---|------|------|----------|----------|------|
| 1 | `ai_service/rag/graph_store.py`（评估对象） | 全局 | 验收 §1.1「graph_only 评估不下降 Hit@5≥0.50」无法当日端到端验证：ModelScope LLM API（qwen/zhipu）429 配额超限，`graph_only` 全量评估实体提取失败全题跳过（与 module-018 embedding 502 同类环境阻塞） | 中（环境） | 已用确定性替代验证：真实引用实体查询 19/19 = Hit@5 1.0000；固定实体 A/B 新实现 0.6957 > 旧行为 0.6522 ≥ 基线 0.50。LLM 配额恢复后由 Tester 重跑 `python -m eval.golden_retrieval --mode graph_only` 复核并回填 |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 图结果带真实分数（hybrid_score ∈ [0,1] 且有区分度） | graph_store.py `_normalize_graph_scores` L313-336 + search_related L243-254 | ✅ 通过 | 实测分数 [1.0, 0.833, 0.667, 0.5, 0.333] |
| 分数反映命中实体数（命中多者分高） | `_count_doc_hits` Cypher `count(DISTINCT ename)` + min-max | ✅ 通过 | 单测 test_minmax_distinct_counts |
| 排序按真实相关度（命中多者排前） | search_related L246-248 `sorted(..., key=hit_map.get, reverse=True)` | ✅ 通过 | 单测 test_sorted_by_hits_desc |
| graph_only 评估不下降（Hit@5 ≥ 0.50） | —（依赖 LLM 实体提取） | ⚠️ 环境阻塞待复核 | 替代验证 1.0000 / 0.6957 ≥ 0.50 |
| 单篇结果分数 0.6（保底） | `_normalize_graph_scores` score_range<1e-9 分支 | ✅ 通过 | 单测 test_single_count_fallback_06 |
| 无实体命中返回空列表 | search_related `if not hit_map: return []` | ✅ 通过 | 单测 test_no_cypher_hits_returns_empty |
| 所有文档命中数相同分数一致（保底） | `[0.6]*len(counts)` | ✅ 通过 | 单测 test_all_same_counts_fallback_06 |
| 实体为空返回空列表 | search_related L227-228 | ✅ 通过 | 单测 test_empty_entities |
| Cypher 查询失败降级返回空（不抛） | search_related `except Exception` L258-260 | ✅ 通过 | `_count_doc_hits` 异常传播被外层捕获 |
| AGE 不可用返回空（现有降级） | 同上 | ✅ 通过 | 与既有降级路径一致 |
| 接口 `search_related(entities, top_k=10)` 返回 list[dict] | graph_store.py L213 | ✅ 通过 | 签名未变 |
| 每项含 id/title/content/source/hybrid_score/parent_id | L250-254 | ✅ 通过 | 单测 test_interface_fields_and_score_range |
| hybrid_score 为 float ∈ [0,1] | `_normalize_graph_scores` 返回 float | ✅ 通过 | 单测断言 isinstance float |
| 返回顺序按 graph_score 降序 | L246-248 | ✅ 通过 | 排序用原始命中数 |
| retriever graph_only 模式兼容 | retriever.py `_retrieve_graph_only` L209-241 | ✅ 通过 | 接口不变零改动 |
| engine 图结果融合兼容 | engine.py L286-294 | ✅ 通过 | 接口不变零改动 |
| 所有 public 方法有 Docstring | search_related / _count_doc_hits / _normalize_graph_scores | ✅ 通过 | |
| 归一化逻辑有行内注释 | L243、L333-335 | ✅ 通过 | |
| 函数/变量 snake_case 且命名有意义 | 全部 | ✅ 通过 | |
| 单个方法 ≤ 50 行 | search_related 34 / _count_doc_hits 33 / _normalize 24 | ✅ 通过 | |
| 本模块新增代码 ≤ 200 行 | graph_store.py +约76行、测试 +约120行 | ✅ 通过 | |
| Python 语法通过 | pytest 收集运行正常 | ✅ 通过 | |
| 无未使用 import | diff 未新增 import | ✅ 通过 | asyncio 为既有未使用 import（非本次引入） |
| 分数归一化有单测（含保底分支） | test_graph_store.py TestNormalizeGraphScores（4 用例） | ✅ 通过 | |
| 排序正确性单测 | test_sorted_by_hits_desc | ✅ 通过 | |
| 真实调用 search_related 验证分数 | 分数测试（真实 AGE） | ✅ 通过 | [1.0,0.833,0.667,0.5,0.333] |
| graph_only 评估不下降 | — | ⚠️ 环境阻塞 | 见 §2.3 |
| `pytest tests/` 无新增失败 | 实测 46 passed, 2 failed | ✅ 通过 | 2 失败为 test_engine.py 既有 async 用例（缺 pytest-asyncio，module-018 技术债务，非本模块回归） |

## 4. 架构评估

- 分层正确性: 通过 — `GraphStore` 仅作为 RAG 推理层存储操作类，改动局限在 `search_related` 及其私有辅助方法，无跨层调用
- 依赖方向: 正确 — `_count_doc_hits` / `_normalize_graph_scores` 为 GraphStore 私有方法，`retriever._retrieve_graph_only` 与 `engine` 融合路径对 `search_related` 的调用契约零改动
- DTO 约束: 通过 — 返回 list[dict]（与 vector/FTS 通道同格式），不泄漏 ORM Entity 到上层
- 新增依赖: 无 — 未引入 plan.md 之外的新依赖，无需 ADR

## 5. 安全评估

- [x] SQL 注入防护: 通过 — 实体值经 `_escape`（转义 `'` `\` `}`）+ 单引号包裹，外层 `$$...$$` dollar-quoting 提供 PG 级防护（既有设计，见模块 docstring 决策 4）
- [x] XSS 防护: N/A — 后端检索逻辑不输出 HTML
- [x] 密码安全（BCrypt）: N/A
- [x] API Key 安全: 通过 — 不涉及密钥处理
- [x] 敏感信息日志处理: 通过 — 日志仅记录 entities 数量与 docs 数量，不打印实体原文

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否
- ADR 编号: —
- ADR 路径: —
- 决策摘要: 无新依赖、无 plan.md 之外的新架构决策。AGE 方言限制（`ORDER BY` 须用 `count(...)` 表达式而非别名）已记录于 project-context.md 关键决策

## 7. 审查检查清单

- [x] 已读取 changelog.md / plan.md / acceptance-criteria.md
- [x] 已阅读全部变更文件完整内容（graph_store.py / test_graph_store.py）
- [x] 命名符合规范（snake_case）
- [x] 接口返回格式兼容（search_related 签名/字段不变）
- [x] 分层正确、无跨层调用或反向依赖
- [x] 异常处理无空 catch（Cypher 失败降级返回空，有 warning 日志）
- [x] 关键操作有日志记录（图搜索完成/失败均有 logger）
- [x] 敏感信息处理正确
- [x] 代码长度在限制内（方法 ≤ 50 行，新增 ≤ 200 行）
- [x] 安全性检查通过
- [x] 验收标准逐项核对
- [x] 已通过运行 `pytest tests/test_graph_store.py`（8 passed）与 `pytest tests/`（46 passed，2 个既有 async 失败）实证验证

---

> **下一步**：审查通过，可进入 Tester 测试阶段。Tester 需重点覆盖：① 真实 AGE 分数测试（分数 [0,1] 有区分度）；② LLM 配额恢复后重跑 `python -m eval.golden_retrieval --mode graph_only` 复核 Hit@5≥0.50 基线；③ 回归 `python -m pytest ai_service/tests/ -x`（预期仅 2 个既有 async 失败）。
