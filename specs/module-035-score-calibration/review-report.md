# 代码审查报告 — Module-035: 记忆/检索分数口径校准

> 本文件由 **Reviewer（m35-reviewer）** 在代码审查阶段输出。
> 结论：**✅ 通过（无阻塞问题，4 项非阻塞建议）**，可进入测试阶段。

---

## 审查元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-035 |
| 模块名称 | 记忆/检索分数口径校准 |
| 审查日期 | 2026-08-06 |
| 审查人 | Reviewer（m35-reviewer） |
| 提交人 | Developer（m35-dev） |
| 审查轮次 | 第 1 轮 |
| 关联 plan.md | `specs/module-035-score-calibration/plan.md` |
| 关联 changelog.md | `specs/module-035-score-calibration/changelog.md` |
| 代码分支 | worktree-m8-knowledge-panel（工作区未提交，git diff 审查） |

---

## 一、独立复现结果（Reviewer 实测）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 记忆单测 | `python -m pytest tests/test_memory.py tests/test_memory_extractor.py -q` | **95 passed**（81 基线 + 14 新增，与 Developer 一致） |
| 全量回归 | `python -m pytest tests/ -q` | **292 passed / 0 failed**（278 基线 + 14 新增，3 个既有 Redis setex 弃用 warning 与模块无关） |
| 身份回归 | `python -m pytest tests/test_identity.py -q` | **20 passed** |
| 下游消费者回归 | `python -m pytest tests/test_engine.py tests/test_stream_memory.py tests/test_session_memory.py -q` | **18 passed**（无回归） |
| 编译检查 | `python -m py_compile rag/memory.py src/config.py main.py tests/test_memory.py tests/test_memory_extractor.py` | **OK** |

新增单测 14 个核对：
- `TestRecallDynamicKAbsCosine` 7 个（三档真实可达 / 低分过滤 / 全低分空 / 空候选 / 嵌入失败降级）
- `TestRecallShortAbsCosine` 1 个（short 层绝对余弦 K=3）
- `TestChildEmbeddings` 3 个（按 id IN 取 embedding / 无 id 不查库 / DB 失败空 dict）
- `TestDedupThreshold035` 2 个（0.88 触发去重 / 0.80 不同事实）
- `TestConfig035` 1 个（0.85 / 0.4 默认值）

---

## 二、核心核对（任务 2）

### 2.1 动态 K 是否真用绝对余弦（query 嵌入 + 点积 + L2）而非 hybrid_score 相对分 — ✅ 通过

`memory.py` 新增 `_absolute_cosine_avg`（L632-674）：
1. `query_emb = await embedding_service.embed_text(query)` — query 经 bge-m3 嵌入并 **L2 归一化**（`embeddings.py` `_normalize`，点积=cosine）
2. `emb_by_id = await self._child_embeddings(docs)` — 候选子块 embedding 按 id **IN 查询**从库读取（module-033 存时已 L2 归一化）
3. `d["abs_cosine"] = self._cosine(query_emb, emb)` — `_cosine`（L588-604）对 L2 归一化向量做**点积**即余弦；维度不一致/空向量返回 0.0（宁缺毋滥）
4. 均值判定档位 `>0.85→5 / 0.75-0.85→3 / <0.75→1`（`_dynamic_k`，L570-585）

**关键确认**：不再使用 `hybrid_score`（min-max 相对分）作为档位判定依据。旧 bug（候选 ≥3 时 min-max 相对分均值恒 <0.75 → 恒 K=1）已消除，**K=5/3 档真实可达**（`test_high_quality_recalls_five` / `test_mid_quality_recalls_three` 实证）。

### 2.2 低分过滤是否实现（防"本批相对高但绝对烂"注入）— ✅ 通过

`_absolute_cosine_avg` L663-667：
```python
docs[:] = [d for d in docs if d.get("abs_cosine", 0.0) >= settings.memory_recall_min_score]
```
- 阈值 `memory_recall_min_score=0.4`（config.py，**绝对余弦口径**，可配）
- 过滤后 `if not docs: return 0.0` → `_expand_to_parents([])` → 返回空，**不崩**
- `test_low_score_candidates_filtered_out`（0.3 丢弃）/ `test_all_candidates_low_score_returns_empty`（全低分空）实证

### 2.3 去重阈值 0.85 是否与动态 K 同口径（都绝对余弦）— ✅ 通过

- 去重 `_find_duplicate`（module-033 实现未变）：新事实 `embed_text`（L2 归一化）+ 存量子块 embedding（L2 归一化）**点积=cosine**，阈值 `settings.memory_dedup_threshold` 由 0.95 → **0.85**（config.py）
- 动态 K 档位判定同为绝对余弦（见 2.1）
- **同尺子确认**：动态 K / 去重 / 低分过滤三者均作用于 [0,1] 绝对 cosine，跨查询可比，语义一致
- 阈值调整依据充分：真实 bge-m3 同义改写 cosine≈0.88（module-033 Tester 实测观察）> 0.85 → 触发去重（`test_synonym_paraphrase_cosine_088_triggers_dedup` 实证）；0.80 不同事实不触发（`test_distinct_fact_cosine_080_no_dedup` 实证）

### 2.4 embedding 失败降级路径（不崩，回退 hybrid_score）— ✅ 通过

`_absolute_cosine_avg` 降级设计：
- **query 嵌入失败**：`except Exception` 捕获 → `query_emb=None` → 跳过绝对余弦分支 → 返回原 `hybrid_score` 均值（L672-674）
- **候选 embedding 读取失败**：`_child_embeddings` 异常捕获返回 `{}` → `emb_by_id` 空 → 同上回退 hybrid_score
- 全程只日志不抛（`recall` 的 5s 超时链路不受影响）；`_expand_to_parents` 降级路径仍取 `hybrid_score`（L741 `d.get("abs_cosine", d.get("hybrid_score", ...))`）
- `test_embedding_failure_degrades_to_hybrid_score` 实证（嵌入失败 → K=1 且 score 取 0.5）

### 2.5 min_score 校准语义正确 — ✅ 通过

`main.py` L391-395：移除失真阈值 `MIN_SCORE=0.3`（原作用于 min-max **相对分**，跨查询不可比，套绝对 0.3 语义失真），`relevant_count = retrieval_count`。
- plan §3.2 功能 3 明确允许"改为绝对余弦口径，**或移除该阈值只做统计展示**"
- `relevant_count` 仅供 UI 展示（`retrieval` step 事件），不影响回答正确性；前端无 `.relevant` 消费方（grep 确认），SSE 事件格式不变
- 检索步骤本身即相关性门控（`engine._retrieve` 已按 `min_score=0.6` 过滤），统计召回数语义自洽

---

## 三、契约核对（任务 3）— ✅ 全部通过

| 契约 | 核对结果 |
|------|----------|
| memory.save/recall 签名不变 | ✅ `save(content, identity, dedup)` / `recall(query, identity, top_k)` 未变（git diff 确认仅方法体内口径改） |
| recall 返回格式不变 | ✅ 仍 `[{content, score, title, created_at}]`，`_expand_to_parents` 返回结构不变（score 值语义改绝对余弦，但格式/字段不变） |
| chat/stream 端点不变 | ✅ `main.py` diff 仅 `chat_stream` Step 2 内部统计逻辑（relevant_count），端点签名/SSE 事件序列不变 |
| 三层 source 分层不变 | ✅ `_layer_pattern` / `_memory_source` / source 精确匹配未动（module-034 行为零回归） |
| 匿名降级不变 | ✅ `_normalize_identity` / `_escape_like` 未动，identity 隔离双保险保留 |
| 下游消费方 | ✅ `engine._recall_memory` / `tool_registry._recall_memory` 仅用 `format_memory_line`（content+created_at），不依赖 score 值，零回归（engine/stream 18 passed 实证） |

---

## 四、安全检查（任务 4）— ✅ 全部通过

- **无新注入面**：`_child_embeddings` 用 SQLAlchemy `select(...).where(Document.id.in_(ids))` 参数化查询，无 SQL 字符串拼接；ids 来自检索结果（服务端内部），非客户端直控
- **identity 隔离**：`_normalize_identity`（LIKE 元字符拒绝）+ `_escape_like`（转义双保险）保留，记忆检索仍按 source 精确匹配隔离
- **日志无敏感**：新增 2 条 `logger.warning`（query 嵌入失败 / embedding 读取失败）仅记录异常对象，不含 query 内容/用户数据/凭证
- **无新依赖**：diff 未引入任何依赖（无需 ADR）

---

## 五、架构检查（任务 1 复核）

- **分层**：memory.py（rag 层 Service）纯业务逻辑；config.py（配置）；main.py（Controller，仅统计展示调整）— 无跨层调用
- **依赖方向**：memory.py 依赖 embeddings/retriever/database，无反向依赖，无循环
- **代码量**：生产代码净增 ~95 行（memory.py +140 含 docstring、config.py +3、main.py 净 -6），单方法 `_absolute_cosine_avg` ~44 行 ≤50；符合 plan "≤300 行" 声明
- **命名/注释**：Python snake_case；三个新 public/内部方法均有 Docstring；魔法数（0.4/0.85/0.75）均已入 config 或常量注释

---

## 六、验收标准核对（任务 6，按实际复选框 35 项）

> 注：acceptance-criteria.md 汇总表记 **33 项**，实际复选框 **35 项**（功能 12 vs 记 11、代码质量 6 vs 记 5），按实际 35 项核对（module-033 修正先例）。

### 1 功能验收（12 项）
| 项 | 验收点 | 结果 | 依据 |
|----|--------|------|------|
| 1.1-1 | 高质量候选召回多档（>0.85→K=5） | ✅ | `test_high_quality_recalls_five`（5 条） |
| 1.1-2 | 中质量召回 3 条（0.75-0.85） | ✅ | `test_mid_quality_recalls_three` |
| 1.1-3 | 低质量召回 1 条（<0.75） | ✅ | `test_low_quality_recalls_one` |
| 1.1-4 | 低分过滤（<min_score 丢弃） | ✅ | `test_low_score_candidates_filtered_out` / `test_all_candidates_low_score_returns_empty` |
| 1.1-5 | 空候选不崩 | ✅ | `test_empty_candidates_returns_empty` |
| 1.2-1 | 同义改写触发去重（0.88>0.85） | ✅ | `test_synonym_paraphrase_cosine_088_triggers_dedup` |
| 1.2-2 | 不同事实正常新增（0.80≤0.85） | ✅ | `test_distinct_fact_cosine_080_no_dedup` |
| 1.2-3 | 阈值可配置（默认 0.85） | ✅ | config.py + `TestConfig035` |
| 1.3-1 | chat_stream MIN_SCORE 语义正确 | ✅ | 移除失真阈值（plan 允许） |
| 1.3-2 | relevant_count 统计合理 | ✅ | `relevant_count = retrieval_count` |
| 1.4-1 | RRF 融合实现 | ⚠️ 不适用 | P3 评估后不采纳（见 §七-6） |
| 1.4-2 | golden_retrieval A/B | ⚠️ 不适用 | 同上 |

### 2 接口验收（5 项）— ✅ 全部通过（见 §三契约核对）

### 3 代码质量验收（6 项）
| 项 | 验收点 | 结果 |
|----|--------|------|
| 3.1-1 | public 方法 Docstring | ✅ |
| 3.2-1 | Python snake_case | ✅ |
| 3.3-1 | 单方法 ≤50 行 | ✅ |
| 3.3-2 | 模块生产代码 ≤300 行 | ✅ |
| 3.4-1 | py_compile 通过 | ✅ |
| 3.4-2 | 无未使用 import | ✅（diff 未新增 import，既有 import 均使用） |

### 4 测试验收（8 项）
| 项 | 验收点 | 结果 | 依据 |
|----|--------|------|------|
| 4.1-1 | 动态 K 绝对余弦测试 | ✅ | TestRecallDynamicKAbsCosine 7 个 |
| 4.1-2 | 去重阈值 0.85 测试 | ✅ | TestDedupThreshold035 2 个 + extractor 更新 |
| 4.1-3 | RRF 融合单测 | ⚠️ 不适用 | P3 未实施 |
| 4.2-1 | 全量 pytest 278+新增 / 0 失败 | ✅ | **292 passed / 0 failed**（独立复现） |
| 4.2-2 | 身份回归 | ✅ | **20 passed**（独立复现） |
| 4.3-1 | 真实 E2E：登录→多档召回 | ⏳ 留 Tester | — |
| 4.3-2 | 真实 E2E：二次同义→去重不膨胀 | ⏳ 留 Tester | — |
| 4.3-3 | 真实 E2E：低分记忆不注入 | ⏳ 留 Tester | — |

### 5 文档验收（4 项）
| 项 | 验收点 | 结果 |
|----|--------|------|
| 5.1-1 | changelog.md 已更新 | ✅ |
| 5.2-1 | 分数口径方案记录 plan.md + score-issues.md | ✅ |
| 5.3-1 | project-context.md 更新 | ✅（"待 REVIEW/TEST"） |
| 5.3-2 | agent-activity-log.md 更新 | ✅（Developer [CODE] 行；本报告附 [REVIEW] 行） |

**核对汇总**：✅ 代码/单测核验 30 项 + ⚠️ 不适用（P3 可选未实施）3 项 + ⏳ 留 Tester 真实 E2E 3 项。

---

## 七、发现的问题

### 阻塞问题
**无。**

### 非阻塞建议（4 项，不阻断测试阶段）

| 序号 | 严重度 | 问题描述 | 所在文件 | 位置 | 建议 |
|------|--------|----------|----------|------|------|
| 1 | 🟡 | `docs.sort(key=lambda d: d["abs_cosine"], reverse=True)` 用硬键访问；若 `PW_MEMORY_RECALL_MIN_SCORE` 配成 ≤0，无 embedding 候选（无 abs_cosine 键）会通过低分过滤后在排序处 **KeyError 崩溃**。默认 0.4 下不可达 | `ai_service/rag/memory.py` | L670 | sort key 改 `d.get("abs_cosine", 0.0)`，或对 min_score 下限做 config 校验 |
| 2 | 🟡 | 无存储 embedding 的候选（如 FTS 命中但 embedding 为 NULL，仅历史/残缺数据可能）被**静默丢弃**（`abs_cosine` 缺省 0.0 < 0.4）——module-033 行为是含 hybrid_score 排名保留。绝对质量口径下"无法验证质量→丢弃"语义正确，但建议补 debug 日志记录被静默丢弃的候选 | `ai_service/rag/memory.py` | L664-667 | 丢弃时加 debug 级日志（含 id 数），便于排查 |
| 3 | 🟡 | chat 路径 `engine._recall_memory` 仍传 `top_k=3`（L290 默认），K=5 档在 chat 路径仍不可达（直接调 `memory_service.recall` 时已真实可达）。属 module-033 review #3 既有观察，非本模块范围 | `ai_service/rag/engine.py` | L290 | 后续模块评估是否将 `_recall_memory` 默认 top_k 提到 5，使对话路径也能多档注入 |
| 4 | 🟢 | acceptance-criteria.md 汇总表记 33 项，实际复选框 35 项（功能 11 vs 12、代码质量 5 vs 6），建议验收签署时按实际修正 | `specs/module-035-score-calibration/acceptance-criteria.md` | 汇总表 | 按 module-033 先例修正统计 |

### 需记录的 ADR
无（无架构决策变更；P3 不采纳为记录在案的评估结论，非架构变更，backlog 记录即可）。

---

## 八、P3 三通道 RRF 评估结论复核（Developer 决策）

Developer 决定**不采纳 RRF**，理由复核通过：
1. **分数量纲硬阻塞（实锤）**：RRF `1/(60+rank)` 得分 ~0.017–0.033，而 `engine._retrieve(query, top_k=20)` 默认 `min_score=0.6` 对 `hybrid_score` 过滤（engine.py:655 `if d.get("hybrid_score", 0) >= min_score`）。min-max 加权下最高分恒 1.0，0.6 语义="保留本批 Top 段"；RRF 下全批 <0.033 → **聊天路径文档全被过滤 → 检索恒空**。采纳 RRF 必须级联重设 `_retrieve` 过滤语义，超出 P3 声明范围（"融合改 RRF"）
2. **A/B 充分性不足**：`golden_retrieval` 直连 `hybrid_retriever.retrieve`，不经 `engine._retrieve` 的过滤，无法暴露上述生产路径回归

结论与 plan §3.4"RRF 走评估，不盲目替换融合"一致，保持 min-max 加权现状合理。**记录为 backlog**：后续引入 RRF 时须与 `engine._retrieve` min_score 过滤语义一并校准（与本次绝对余弦口径同思路）。

---

## 审查总结

### 统计

| 类别 | 通过数 | 不通过数 | 不适用 |
|------|--------|----------|--------|
| 架构检查 | 4 | 0 | 0 |
| 编码规范检查 | 5 | 0 | 0 |
| 接口规范检查 | 5 | 0 | 0 |
| 安全检查 | 4 | 0 | 0 |
| 性能检查 | 3 | 0 | 0 |
| 验收标准核对 | 30 | 0 | 3（P3 可选未实施） |
| 代码变更审查 | 6 | 0 | 0 |
| **合计** | **57** | **0** | **3** |

### 审查结论
- [x] ✅ **通过** — 核心四项（动态K 绝对余弦 / 低分过滤 / 去重阈值 0.85 同口径 / 嵌入失败降级）实现正确，min_score 校准语义符合 plan；契约与安全零违规；独立复现与 Developer 自测完全一致（记忆 95/全量 292/身份 20/引擎流会话 18/py_compile OK）。4 项非阻塞建议记录于 §七。
- 真实 E2E（4.3-1/2/3）留 Tester 验收。

### 审查人签名
- 审查人：Reviewer（m35-reviewer）
- 日期：2026-08-06
- 结论：✅ 通过
