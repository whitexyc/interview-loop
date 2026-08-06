# 测试报告 — module-035: 记忆/检索分数口径校准

> 📋 本文件由 Tester（m35-tester）维护，记录该模块的测试执行结果和验收结论。
> 验收结论已在 `acceptance-criteria.md` 签署：✅ **通过**。

---

## 模块信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-035 |
| 模块名称 | 记忆/检索分数口径校准 |
| 开发计划 | `specs/module-035-score-calibration/plan.md` |
| 验收标准 | `specs/module-035-score-calibration/acceptance-criteria.md` |
| 变更日志 | `specs/module-035-score-calibration/changelog.md` |
| 审查报告 | `specs/module-035-score-calibration/review-report.md` |
| 测试员 | Tester（m35-tester） |
| 测试日期 | 2026-08-06 |

---

## 1. 测试环境

| 字段 | 内容 |
|------|------|
| 后端框架 | Python FastAPI（ai_service） |
| 数据库 | PostgreSQL 15+（docker my_postgres:5432，真实库 personal_website，7528 行） |
| 缓存 | Redis（docker my_redis:6379） |
| 测试框架 | pytest 9.1.1 / Python 3.11.15 |
| 平台 / OS | Windows 11 |
| 已知环境坑 | 无新增；3 个既有 Redis `setex` DeprecationWarning 与模块无关 |
| 依赖前置 | 本地 bge-m3 GGUF（models/bge-m3-gguf/bge-m3-q8_0.gguf，605.2MB） |
| 运行环境 | 本地开发环境（worktree-m8-knowledge-panel） |
| 测试命令 | `cd ai_service && python -m pytest tests/ -q` |
| 变更文件 | `rag/memory.py` / `src/config.py` / `main.py` / `tests/test_memory.py` / `tests/test_memory_extractor.py` |

---

## 2. 单元测试

### 2.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试文件数（记忆相关） | 2（test_memory.py + test_memory_extractor.py） |
| 测试用例总数 | 95 |
| 通过 | 95 |
| 失败 | 0 |
| 跳过 | 0 |
| 其中 module-035 新增 | 14（TestRecallDynamicKAbsCosine 7 + TestRecallShortAbsCosine 1 + TestChildEmbeddings 3 + TestDedupThreshold035 2 + TestConfig035 1） |
| 覆盖率要求 | 模块内核心方法均已覆盖（不强制全量覆盖率，按 plan 约定） |

### 2.2 新增/更新用例明细（module-035 核心核对）

| 测试类 | 测试方法 | 场景描述 | 结果 |
|--------|----------|----------|------|
| `TestRecallDynamicKAbsCosine` | `test_high_quality_recalls_five` | 绝对余弦均值 >0.85 → K=5 真实可达（不再恒 1） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_mid_quality_recalls_three` | 绝对余弦均值 0.78 ∈ [0.75,0.85) → K=3 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_low_quality_recalls_one` | 绝对余弦均值 0.5 <0.75 → K=1（宁缺毋滥） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_low_score_candidates_filtered_out` | 候选 abs_cosine=0.3 < min_score(0.4) → 丢弃不注入 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_all_candidates_low_score_returns_empty` | 全部候选低分 → 返回空（不崩） | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_empty_candidates_returns_empty` | 无候选 → 返回空，_expand_to_parents 不被调用 | ✅ |
| `TestRecallDynamicKAbsCosine` | `test_embedding_failure_degrades_to_hybrid_score` | query 嵌入失败 → 降级用原 hybrid_score（不回退失败，K=1） | ✅ |
| `TestRecallShortAbsCosine` | `test_recall_short_abs_cosine_reaches_three` | recall_short 绝对余弦口径（K=3，TTL 内保留） | ✅ |
| `TestChildEmbeddings` | `test_fetches_embeddings_by_child_ids` | 按子块 id IN 查询读存储 embedding（参数化，无注入） | ✅ |
| `TestChildEmbeddings` | `test_no_ids_returns_empty_without_db` | 无 id 不查库直接返回空 | ✅ |
| `TestChildEmbeddings` | `test_db_failure_returns_empty` | DB 失败返回空 dict（由调用方降级） | ✅ |
| `TestDedupThreshold035` | `test_synonym_paraphrase_cosine_088_triggers_dedup` | 0.88 > 0.85 → 命中重复（更新而非新增） | ✅ |
| `TestDedupThreshold035` | `test_distinct_fact_cosine_080_no_dedup` | 0.80 ≤ 0.85 → 不同事实正常新增 | ✅ |
| `TestConfig035` | `test_dedup_threshold_and_min_score_defaults` | config 默认：dedup 0.85 / min_score 0.4 / 档位 0.85/0.75 | ✅ |

既有用例更新核对：`TestRecall` 两个用例（source_pattern 透传 / 同父块去重取最高分）与
`TestRecallShort` TTL 用例改为 mock `embedding_service.embed_text` 抛异常走**降级路径**，
断言语义不变；`test_memory_extractor.py::TestRecallDynamicK` 四例改绝对余弦口径
（mock query 嵌入 + 候选 embedding），去重注释 0.95→0.85。

### 2.3 失败用例详情

> 无失败用例。

| 测试方法 | 预期结果 | 实际结果 | 失败原因 | 归类 | 严重度 |
|----------|----------|----------|----------|------|--------|
| — | — | — | — | — | — |

---

## 3. 集成测试

### 3.1 测试概况

| 统计项 | 值 |
|--------|-----|
| 测试场景数 | 6 |
| 通过 | 6 |
| 失败 | 0 |

### 3.2 测试场景明细（下游消费者零回归核对）

| 场景 | 描述 | 前置条件 | 预期结果 | 实际结果 | 状态 |
|------|------|----------|----------|----------|------|
| 下游引擎 | tests/test_engine.py（chat/_recall_memory 消费） | 真实 DB/Redis | 无回归 | 通过 | ✅ |
| 流式记忆 | tests/test_stream_memory.py | mock 全链路 | 无回归 | 通过 | ✅ |
| 会话记忆 | tests/test_session_memory.py | 真实 DB | 无回归 | 通过 | ✅ |
| 身份隔离 | tests/test_identity.py | 真实 DB | 20/20 无回归 | 20 passed | ✅ |
| 编译检查 | `python -m py_compile rag/memory.py src/config.py main.py tests/test_memory.py tests/test_memory_extractor.py` | — | OK | OK | ✅ |
| 无未使用 import | git diff 核对（未新增 import，既有均使用） | — | 通过 | 通过 | ✅ |

---

## 4. 回归测试

### 4.1 回归范围

| 已有模块 | 是否受影响 | 回归测试数 | 结果 |
|----------|-----------|-----------|------|
| module-023/033/034 记忆（long/short/session） | 是（口径改） | 95（记忆单测） | 全过 |
| module-032 身份隔离 | 否（隔离逻辑未动） | 20 | 全过 |
| module-025/034 流式/会话消费方 | 否（仅用 content/created_at） | 18 | 全过 |
| 全量套件 | — | 292 | 全过 |

### 4.2 回归结果

| 统计项 | 值 |
|--------|-----|
| 回归测试总数 | 292（278 基线 + 14 新增） |
| 通过 | 292 |
| 失败 | 0 |
| 通过率要求 | 100% |
| 实际通过率 | 100%（0 失败） |

> 与 Developer 自测 / Reviewer 独立复现结果完全一致（记忆 95 / 全量 292 / 身份 20 / 下游 18）。
> 3 个既有 Redis `setex` DeprecationWarning（tests/test_cache.py）与模块无关。

---

## 5. 环境性失败归因

> 本模块无失败用例，无需归因。下表为预置矩阵确认状态（供后续模块参考）。

| 现象 | 判断标准 | 归类 | 处理方式 | 本模块状态 |
|------|----------|------|----------|-----------|
| 依赖包缺失 | 补依赖后重跑即通过 | 环境性失败 | 修复基建 | 未发生 |
| mock 缺失 / 依赖服务未启动 | 单独跑该用例失败，基线同模块通过 | 环境性失败 | 补齐后重跑 | 未发生 |
| 平台差异 | 其他平台通过本平台失败 | 环境性失败 | 记录差异 | 未发生 |
| 代码行为不符预期 | 环境正常输出不符 | 真实回归 | 反馈 Developer | 未发生 |
| 无法确定 | 环境与代码均无线索 | 待排查 | 记录现场 | 未发生 |

**E2E 说明**：全栈 HTTP 服务（Java 8081 + AI 8001 uvicorn）未启动，采用**半真实 E2E**
（真实 PG + 真实本地 bge-m3 + MemoryService 直连，绕过 HTTP 栈），与 module-033/034
Tester 半真实 E2E 先例一致。chat 路径 `_recall_memory` 仍 `top_k=3`（既有，见 §9 建议），
故 K=5 档按任务指引直接调 `memory_service.recall(query, identity, top_k=5)` 验证。

---

## 6. 真实环境冒烟（半真实 E2E）

> 单元 / 回归 / 下游测试全部通过后，使用真实 PG + 真实本地 bge-m3 沿 acceptance 4.3
> 三条核心路径执行半真实 E2E（服务层直连，真实模型推理）。

### 冒烟环境

- 真实 PG（docker my_postgres，personal_website，7528 行）
- 真实本地 bge-m3 GGUF（605.2MB）
- 测试身份使用时间戳唯一标识，结束后全部清理（残留校验 0）

### 冒烟结果

| 冒烟项 | 命令/方式 | 结果 | 是否通过 |
|--------|-----------|------|----------|
| 4.3-1 高质量记忆多档召回 | save 5 条高相似记忆（dedup=False）→ `memory_service.recall(query, ident, top_k=5)` | **K=5 真实可达**：5 候选 abs_cosine [1.0, 0.9987, 0.9972, 0.9935, 0.9474]，均值 0.987 > 0.85 → K=5 | ✅ |
| 4.3-1 中质量召回 3 条 | save 5 条中相似记忆 → recall | **K=3 真实可达**：5 候选 abs_cosine [1.0, 0.803, 0.796, 0.735, 0.632]，均值 0.793 ∈ [0.75,0.85) → K=3 | ✅ |
| 4.3-2 二次同义对话去重不膨胀 | save 首次 → save 同义改写（dedup=True） | 首次 status=saved → 同义 status=**updated**（id 不变），parents 1→1 条数不涨 | ✅ |
| 4.3-3 低分记忆不注入 | 仅存 1 条无关记忆 → recall 无关 query | **K=0**：实测 abs_cosine=0.3104 < 0.4 → 候选被过滤返回空（旧相对分口径下 min-max 会给该单候选高分而注入） | ✅ |
| 数据真实落库验证 | 清理前查询父块数 | 高质批 parents=5 / 中质批 parents=5 / 去重批 1→1 / 低分批 parents=1，均与预期一致 | ✅ |
| AI 真实调用 | bge-m3 真实模型嵌入（非桩数据） | 全部 abs_cosine 为真实推理值（如 0.9474/0.8030/0.3104） | ✅ |

> 注：K=3 档已通过调试输出确认是**档位判定**（5 候选均值 0.793 落 [0.75,0.85)），
> 而非候选数截断（旧实现恒 K=1 的语义偏差已消除）。

---

## 7. 异常兜底测试

| 测试场景 | 输入 | 预期行为 | 实际行为 | 结果 |
|----------|------|----------|----------|------|
| query 嵌入失败 | `embedding_service.embed_text` 抛异常 | 降级用原 hybrid_score（不回退失败） | K=1 且 score 取 hybrid_score | ✅ |
| 候选 embedding 读取失败 | `_child_embeddings` DB 异常 | 返回空 dict → 降级 hybrid_score | 降级正常，不抛 | ✅ |
| 空候选 | 检索返回 [] | recall 返回空，不调用 _expand_to_parents | 返回空 | ✅ |
| 全低分候选 | 全部 abs_cosine < 0.4 | 返回空（不崩） | 返回空 | ✅ |
| 无 id 候选 | `_child_embeddings([])` | 不查库直接返回空 | 返回空，0 次 DB 调用 | ✅ |
| 维度不一致 embedding | `_cosine` 长度不同 | 返回 0.0（视为不相似） | 返回 0.0 | ✅ |
| 空/空白 query（recall 入口） | 空串 query | 返回空（既有防护） | 返回空 | ✅ |
| 低分过滤 + 排序 | 混合高分低分候选 | 低分丢弃后按绝对余弦降序排序 | 过滤正确，排序正确 | ✅ |

---

## 8. 验收标准核对

> 逐项核对 `acceptance-criteria.md`（实际复选框 **35 项**：功能 12 / 接口 5 / 代码质量 6 /
> 测试 8 / 文档 4；原汇总表记 33 有误，已按实际修正——module-033 先例）。

### 功能验收（12 项：10 通过 + 2 P3 不适用）

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 1.1-1 高质量候选召回多档 | `test_high_quality_recalls_five` + 半真实 E2E K=5 | ✅ |
| 1.1-2 中质量召回 3 条 | `test_mid_quality_recalls_three` + 半真实 E2E K=3 | ✅ |
| 1.1-3 低质量召回 1 条 | `test_low_quality_recalls_one` | ✅ |
| 1.1-4 低分过滤 | `test_low_score_candidates_filtered_out` + E2E（0.31 过滤） | ✅ |
| 1.1-5 空候选不崩 | `test_empty_candidates_returns_empty` | ✅ |
| 1.2-1 同义改写触发去重 | `test_synonym_paraphrase_cosine_088_triggers_dedup` + E2E（updated） | ✅ |
| 1.2-2 不同事实正常新增 | `test_distinct_fact_cosine_080_no_dedup` | ✅ |
| 1.2-3 阈值可配置 | `TestConfig035`（0.85 默认）+ config.py | ✅ |
| 1.3-1 chat_stream MIN_SCORE 语义正确 | main.py diff（移除失真阈值） | ✅ |
| 1.3-2 relevant_count 统计合理 | main.py（relevant_count = retrieval_count） | ✅ |
| 1.4-1 RRF 融合实现 | ⚠️ 不适用：P3 评估后不采纳 | ⚠️ |
| 1.4-2 golden_retrieval A/B | ⚠️ 不适用：同上 | ⚠️ |

### 接口验收（5 项）— 全部通过

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 2.1-1 save/recall 签名不变 | git diff 核对 + 全量回归 | ✅ |
| 2.1-2 recall 返回格式不变 | `_expand_to_parents` 结构不变（content/score/title/created_at） | ✅ |
| 2.1-3 chat/stream 端点不变 | main.py diff 仅内部统计 | ✅ |
| 2.1-4 三层 source 分层不变 | 精确匹配逻辑未动，记忆单测 95 全过 | ✅ |
| 2.2-1 配置默认值 | config.py（0.85 / 0.4）+ `TestConfig035` | ✅ |

### 代码质量验收（6 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 3.1-1 所有 public 方法有 Docstring | ✅（新增 `_absolute_cosine_avg` / `_child_embeddings` / `_cosine` 均有） |
| 3.2-1 Python snake_case | ✅ |
| 3.3-1 单方法 ≤50 行 | ✅（`_absolute_cosine_avg` ~44 行） |
| 3.3-2 模块生产代码 ≤300 行 | ✅（净增 ~95 行） |
| 3.4-1 py_compile 通过 | ✅ |
| 3.4-2 无未使用 import | ✅ |

### 测试验收（8 项：7 通过 + 1 P3 不适用）

| 验收项 | 测试用例 | 结果 |
|--------|----------|------|
| 4.1-1 动态 K 绝对余弦测试 | TestRecallDynamicKAbsCosine 7 + TestRecallShortAbsCosine 1 + TestChildEmbeddings 3 | ✅ |
| 4.1-2 去重阈值 0.85 测试 | TestDedupThreshold035 2 + extractor 更新 | ✅ |
| 4.1-3 RRF 融合单测 | ⚠️ 不适用：P3 未实施 | ⚠️ |
| 4.2-1 全量 pytest 0 失败 | **292 passed / 0 failed** | ✅ |
| 4.2-2 身份回归 | **20 passed** | ✅ |
| 4.3-1 真实 E2E 多档召回 | 半真实 E2E：K=5（均值 0.987）/ K=3（均值 0.793） | ✅ |
| 4.3-2 真实 E2E 二次同义去重不膨胀 | 半真实 E2E：updated，parents 1→1 | ✅ |
| 4.3-3 真实 E2E 低分不注入 | 半真实 E2E：K=0，abs_cosine 0.31 < 0.4 | ✅ |

### 文档验收（4 项）— 全部通过

| 验收项 | 结果 |
|--------|------|
| 5.1-1 changelog.md 已更新 | ✅ |
| 5.2-1 分数口径方案记录 plan.md + score-issues.md | ✅ |
| 5.3-1 project-context.md 更新 | ✅ |
| 5.3-2 agent-activity-log.md 更新 | ✅ |

---

## 9. 测试结论

### 总结

| 统计项 | 值 |
|--------|-----|
| 单元测试通过率 | 95/95 (100%) |
| 下游/集成测试通过率 | 44/44 (100%) |
| 回归测试通过率 | 292/292 (100%) |
| 异常兜底测试通过率 | 8/8 (100%) |
| 真实环境冒烟通过率（半真实 E2E） | 3/3 (100%) |
| **总体验收结论** | **✅ 通过** |

### 验收结论

- [x] ✅ **通过** — 所有测试通过，验收标准全部满足，建议合并
- [ ] ❌ **不通过** — 存在失败用例，需 Developer 修复后重新测试
- [ ] ⚠️ **有条件通过** — 核心路径通过，非核心问题可后续修复

### 签署

| 字段 | 内容 |
|------|------|
| 测试人 | Tester（m35-tester） |
| 签署时间 | 2026-08-06 |
| 结论 | 通过 |
| 记忆库同步确认 | project-context 状态已标记 ✅ / file-index 已更新 ✅ / agent-activity-log 已追加 ✅ |

### 失败详情

> 无失败项。未执行 3 项为 P3 三通道 RRF（可选，评估后不采纳，非失败）。

---

## 10. Reviewer 建议复核（Tester 实测）

| 序号 | 建议 | Tester 复核结论 |
|------|------|-----------------|
| #1 | `docs.sort(key=lambda d: d["abs_cosine"], reverse=True)` 硬键访问；min_score≤0 配置下无 abs_cosine 候选会 KeyError | **默认配置下无影响（确认）**：默认 `memory_recall_min_score=0.4`，无 `abs_cosine` 键的候选 `d.get("abs_cosine", 0.0)`=0.0 < 0.4 会在过滤步骤被移除，不可能到达 sort。仅当 `PW_MEMORY_RECALL_MIN_SCORE` 配置 ≤0 时理论可达，属配置护栏问题，非生产默认路径。建议（低优先级）改为 `d.get("abs_cosine", 0.0)` 或对 min_score 做下限校验 |
| #2 | 无存储 embedding 的候选被静默丢弃（abs_cosine 缺省 0.0 < 0.4） | **确认语义正确**：绝对质量口径下"无法验证质量→丢弃"合理；建议补 debug 日志（非阻塞） |
| #3 | chat 路径 `engine._recall_memory` 仍 `top_k=3`（engine.py L290），K=5 档 chat 不可达 | **确认既有行为（非本模块回归）**：`engine.py:290` `top_k: int = 3`，chat/stream 调用未传 top_k 用默认 3 → chat 候选池最多 3 条，K=5 档在 chat 路径不可达。直接调 `memory_service.recall(query, identity, top_k=5)` 已真实可达 K=5（半真实 E2E）。属 module-033 review #3 既有观察，建议后续模块评估 `_recall_memory` 默认 top_k 提至 5 |
| #4 | acceptance 汇总表 33 vs 实际 35（功能 11 vs 12、代码质量 5 vs 6） | **已修正**：汇总表按实际复选框 35 项修正（功能 12 / 接口 5 / 代码质量 6 / 测试 8 / 文档 4），module-033 先例 |

---

## 11. 改进建议

| 建议 | 优先级 | 建议处理时间 |
|------|--------|-------------|
| `_absolute_cosine_avg` 排序硬键改 `d.get("abs_cosine", 0.0)`（或对 `memory_recall_min_score` 配置加下限校验），消除 min_score≤0 理论 KeyError（Reviewer #1） | 低 | 后续模块 |
| 低分过滤丢弃候选时补 debug 日志（含 id 数），便于排查静默丢弃（Reviewer #2） | 低 | 后续模块 |
| `engine._recall_memory` 默认 `top_k` 3→5，使 chat 路径也能多档注入（Reviewer #3） | 中 | 后续模块（记忆体系收尾） |
| P3 三通道 RRF 引入时须联动校准 `engine._retrieve` 的 `min_score=0.6` 过滤语义（与绝对余弦口径同思路），记录 backlog | 低 | 引入 RRF 时 |
| 测试数据已全部清理（e2e-m035 残留 0）；临时 E2E 脚本已删除 | — | 已完成 |
