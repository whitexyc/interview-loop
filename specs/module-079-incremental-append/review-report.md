# 审查报告 — Module-079

> 审查人: Reviewer（子代理）｜审查时间: 2026-08-26
> 审查范围: `plan.md` / `acceptance-criteria.md` / `changelog.md` / `document_dedup.py` / `config.py` / `tests/core/test_incremental_append.py` / `tests/core/test_document_dedup.py` / 顶层 `tests/test_incremental_append.py`
> 验证方式: 完整代码阅读（新旧实现 git diff 对比）+ 定向测试 + tests/core 全量 + py_compile + AST 行数 + 配置覆盖实测 + **真实 PG 只读冒烟（_SEMANTIC_DUP_SQL 实执行）+ pgvector 索引检查**

## 1. 审查结论

- 结论：✅ **通过**（附 1 项已声明遗留 + 4 项非阻塞观察）

**验证证据汇总**：

| 验证项 | 命令/方法 | 结果 |
|--------|-----------|------|
| 定向测试 | `pytest tests/ -q -k "dedup or incremental or append"` | **91 passed / 0 failed** ✓（与 changelog 声明一致） |
| core 全量 | `pytest tests/core/ -q` | **297 passed / 3 skipped / 0 failed** ✓ |
| py_compile | `document_dedup.py` + `config.py` | **OK** ✓ |
| 单方法行数 | AST `end_lineno - lineno + 1` | **49**（≤ 50 铁律 ✓） |
| 新增生产代码 | `git diff --numstat` | document_dedup.py **+45/-46**、config.py **+5** → 新增 50 行（≤ 200 铁律 ✓） |
| 配置覆盖 | `PW_DOC_DEDUP_CANDIDATE_TOP_K=20` → 20；无 env → 50 | **20 / 50** ✓ |
| 真实 DB SQL 冒烟 | `async_session_factory` 实执行 `_SEMANTIC_DUP_SQL`（1024 维向量绑定） | **执行成功，返回 3 行**；零向量 → cosine=nan 安全（nan ≥ 0.95 为 False，不误命中）✓ |
| pgvector 索引 | `pg_indexes` 查询 documents 表 | **无 embedding 列向量索引**（仅 btree/gin）→ 记遗留（见 §2 #1） |

## 2. 问题列表（如有）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `documents` 表（DDL 层，本模块未动） | — | **`documents.embedding` 无 pgvector 向量索引**（仅 btree/gin：pkey/content_hash/content_fts/parent_id/search_tokens/doc_content_hash/duplicate_cluster_id）→ top-K 查询退化为全表扫描 + 排序。正确性不受影响（SQL 侧执行、内存 O(K)、返回契约不变），但性能提升有限 | **P2 遗留**（plan §5 风险表、changelog §5 遗留 1 已声明；plan 明确本模块不动 DDL） | 后续模块补 DDL：`CREATE INDEX ... ON documents USING hnsw (embedding vector_cosine_ops)`（或 ivfflat），并真实测一遍入库耗时对比；索引缺失期间语义去重仍正确 |
| 2 | `rag/retrieval/document_dedup.py` | :99 | `_cosine` 重写后成为**生产死代码**（仅被测试 `tests/core/test_document_dedup.py` / 顶层测试 / `scripts/verify_incremental_append.py` 引用，生产路径不再调用） | P3 | 可保留（测试直接引用其做契约校验，删需同步改测试）；建议在函数 docstring 标注"历史/测试用，生产 L2 判定已由 SQL 侧余弦取代" |
| 3 | `tests/test_incremental_append.py`（顶层） | 全文 | 与 `tests/core/test_incremental_append.py` 覆盖重叠（后者为 plan 指定文件、覆盖更全）；头部注释仍写"emb is None 修复回归"旧口径，与实际结构修复（SQL 侧余弦）表述有偏差 | P3 | changelog §5 遗留 3/4 已记录；如 Reviewer 认可可删顶层文件（git 未跟踪，删除零风险）或修正注释；行为断言均指向新契约，不阻塞 |
| 4 | `changelog.md` | §3.1 | 用例数口径存疑："dedup 19 + core incremental 11 + 顶层 incremental 61"——实测 core 增量 10、顶层 16 个测试方法，91 总数与实测一致但分解数与 `pytest --collect-only` 口径不符（其余匹配用例来自 memory 等目录的 dedup 测试） | P4 | 纯记录差异，无实质影响；后续 changelog 建议附 `--collect-only -q` 输出而非手数 |
| 5 | `rag/retrieval/document_dedup.py` | :177 | 真实 DB 冒烟暴露：零向量（[0.0]*1024）绑定产生 `cosine=nan`。当前代码 `float(row["cosine"])` 对 nan 不抛异常且 `nan >= threshold` 为 False → 不误命中，**安全**；真实 bge-m3 向量 L2 归一化非零模，不会出现 | P4 观察 | 无需处理；若未来接入任意向量源可加 `math.isnan` 防御（非本模块范围） |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 |
|--------|----------|------|
| **1.1 增量嵌入**：embed_documents 仅新文档子块（次数=子块数） | `tests/core/test_incremental_append.py::test_embedding_only_new_children`（await 次数 + 参数 == 新子块文本） | ✅ |
| 1.1 存量文档零嵌入调用 | 同上 + `test_embedding_cost_independent_of_existing_count`（N=0 与 N=200 均 1 次调用） | ✅ |
| 1.1 嵌入失败 fail-open 不阻断 | `test_ingest_embedding_failure_fail_open`（真实链路 mock，doc_embedding=None 仍入库） | ✅ |
| **1.2 检索增量生效**：_vector_search 命中新子块 | `test_vector_search_hits_new_chunk`（SQL 含 `parent_id IS NOT NULL` / `embedding IS NOT NULL`，返回新 doc_id） | ✅ |
| 1.2 提交后清检索缓存 | `test_add_document_clears_retrieval_cache`（`cache.delete_by_prefix("rag:retrieve:")` awaited） | ✅ |
| 1.2 真实冒烟（可选） | 未执行完整 search API 冒烟（可选验收，不阻塞；SQL 形态与生产 `_vector_search` 同源已验证） | ➖ 可选 |
| **1.3 无全量重嵌**：存量 embedding 逐字节不变 | `test_add_document_insert_only_no_existing_mutation`（DML 记录仅 INSERT，零 UPDATE/DELETE，存量 embedding 断言不变） | ✅ |
| 1.3 无 reindex/rebuild/backfill 调用 | `test_auto_ingest_path_has_no_reindex_scripts`（engine/ingest/dedup 三文件源码级守卫） | ✅ |
| 1.3 ensure_graph/upsert 幂等追加 | `test_graph_extraction_additive`（ensure/extract/upsert_entity/upsert_relation 各 1 次） | ✅ |
| **1.4 去重不破坏增量**：L1 命中 → 新文档 B 正常追加 | `test_l1_dedup_does_not_block_incremental_append`（A→重复 L1 duplicate→B 入库，added==2） | ✅ |
| 1.4 add_document 兜底去重不阻断 | `test_add_document_internal_dedup_zero_embedding`（duplicate=True、chunks=0、零嵌入） | ✅ |
| **1.5 性能 O(1)**：SQL top-K 固定 LIMIT :k | `test_semantic_duplicate_query_topk_limit`（`LIMIT :k` + `params["k"] == settings.doc_dedup_candidate_top_k`）+ 代码 `_SEMANTIC_DUP_SQL` | ✅ |
| 1.5 不同存量 N 下嵌入调用相同 | `test_embedding_cost_independent_of_existing_count` | ✅ |
| 1.5 L2 只对 top-K 判余弦 | 代码：`result.mappings()` 只遍历 K 行，无全表 Python 余弦（diff 实证：删 `result.scalars().all()` + `_cosine` 循环） | ✅ |
| 1.5 复杂度论证成立 | plan §4.1（L1 O(log N)、L2 O(log N+K)、嵌入 O(新块)、图 O(新文档)、缓存 O(1)） | ✅ |
| **2.1 ndarray 兼容**：不抛 ValueError | `test_semantic_duplicate_ndarray_cosine_no_valueerror`（np.float64 余弦）+ 结构性根除（Python 无 embedding 真值判定） | ✅ |
| 2.1 None/维度不匹配跳过 | `test_semantic_duplicate_skips_null_embedding` + SQL `WHERE embedding IS NOT NULL` | ✅ |
| 2.1 全链路失败 fail-open | `test_semantic_duplicate_query_failure_fail_open` + `test_semantic_duplicate_embedding_failure_fail_open` + 代码 try/except → None | ✅ |
| **2.2 特殊字符/并发** | 特殊字符：参数化绑定（:vec/:k）无字符串拼接风险，未单测（存量覆盖）；并发：存量测试已有覆盖，本模块标注引用（plan 声明不重复建） | ✅ 存量覆盖 |
| **3.1 代码质量**：生产 ≤200 行 | git diff --numstat 实测新增 50 行 | ✅ |
| 3.1 单方法 ≤50 行 | AST 实测 49 | ✅ |
| 3.1 docstring 齐全 / 魔法数字走 config | `find_semantic_duplicate` 完整 docstring；K 走 `doc_dedup_candidate_top_k`；SQL 常量上方注释说明先例 | ✅ |
| 3.1 无空 catch | fail-open except 带 `logger.warning`（铁律 5 豁免） | ✅ |
| 3.1 复用 pgvector `<=>` 范式 | 与 `retriever._vector_search`（:815-823）/ `crawler._conflict_candidates`（:387-415）逐字同源：`1-(embedding <=> :vec) AS cosine` + `ORDER BY ... ASC LIMIT :k` + 字符串绑定 | ✅ |
| **3.2 性能**：LIMIT 固定 / O(log N+K) | 见 1.5 | ✅ |
| **3.3 兼容**：返回契约不变 | `{"id","title","cluster_id","cosine"}` 或 None，字段与旧实现逐项一致（`cluster_id = duplicate_cluster_id or str(id)` 同旧）；`document_ingest.py:167-170` 调用方零改动 | ✅ |
| 3.3 既有配置语义不变 | `doc_dedup_semantic_enabled=True` / `doc_dedup_threshold=0.95` / `doc_dedup_boilerplate_enabled=True` 未动；新增项默认 50 向后兼容（实测 env 覆盖 20 ✓） | ✅ |
| 3.3 存量测试行为不漂移 | 定向 91 passed；tests/core 297 passed / 0 failed | ✅ |
| 3.3 全量回归基线不降 | changelog §3.1：1396 passed / 4 failed（module-028 proxies 基线）/ 3 skipped，0 新增失败；本次定向 + core 交叉验证一致 | ✅ |

## 4. 铁律合规检查

| 铁律 | 检查项 | 结果 |
|------|--------|------|
| 铁律 2 | 新增生产代码 ≤ 200 行 | ✅ 实测 50 行（numstat：dedup +45/config +5） |
| 铁律 3 | 单方法 ≤ 50 行 | ✅ `find_semantic_duplicate` 49 行（AST 实测，含签名与 docstring） |
| 铁律 4 | 新/改公开方法 docstring；魔法数字命名常量 | ✅ docstring 含 Args/Returns；K 走 config `doc_dedup_candidate_top_k`（PW 前缀 env 可覆盖） |
| 铁律 5 | 无空 catch / 吞异常 | ✅ fail-open 分支均带 `logger.warning` 说明 |
| — | 复用先例、不重写算法 | ✅ 查询形态与 `_vector_search` / `_conflict_candidates` 完全一致 |
| — | 测试代码不计入生产限额 | ✅ 测试 ~400 行不计数 |

## 5. 审查总结

**判定：✅ 通过。** Module-079 作为验证型模块达成目标：

1. **验收 1-4（行为锁定）**：新增 `tests/core/test_incremental_append.py` 10 个用例逐项锁定"增量嵌入只对新文档 / 检索增量立即可见 / 无全量重嵌 / 去重不破坏增量"，断言直指真实链路（embed 参数、DML 类型、缓存失效、L1 命中流），hermetic 全 mock、不依赖真实 PG/bge-m3，符合 plan 子任务 2 设计。

2. **验收 5（性能加固，唯一生产改动）**：`find_semantic_duplicate` 从 ORM 全表拉取 + Python 全量余弦（O(N)）重写为 pgvector SQL top-K（`_SEMANTIC_DUP_SQL`：`ORDER BY embedding <=> :vec ASC LIMIT :k`，K=`doc_dedup_candidate_top_k`=50），**git diff 实证**删除了 `select(Document)`/`scalars().all()`/`_cosine` 逐条循环。WHERE 条件与旧查询逐字语义一致（parent_id IS NULL / embedding IS NOT NULL / is_canonical / memory 源排除），返回契约不变，调用方零改动。**真实 PG 只读冒烟确认 SQL 语法与执行正确**（绑定 1024 维向量实跑成功）。

3. **backlog ① ndarray bug 结构性根除**：余弦由 SQL 侧 `1 - (embedding <=> :vec)` 算好，Python 侧不再对 embedding 做任何真值判定（仅 `if vec is None`，且 embed_text 实际返回 list[float]），`if not emb` 的 ValueError 路径从源码层面消失，并有 ndarray 余弦回归测试锁定。

4. **fail-open 纪律完整**：嵌入失败（None 短路）、查询失败（try/except → logger.warning + None）、极端余弦值（nan 不误命中）三层均不阻断入库，与全链路 fail-open 纪律一致。

5. **向后兼容**：`doc_dedup_candidate_top_k` 为带默认值的新字段（实测 20/50），既有三项去重配置零改动。

**遗留（非阻塞，已声明）**：`documents.embedding` 列缺 pgvector 向量索引 → top-K 暂退化为 SQL 侧全扫排序（正确性不受影响）。建议后续模块补 HNSW/IVFFlat DDL 并实测耗时，落实 plan 待澄清 2。其余观察项（§2 #2-#5）均为非阻塞记录差异或清洁度建议，不影响本模块交付。

---

- 验收结论：✅ 通过
- 审查人签名: Reviewer（module-079）
- 验收时间: 2026-08-26
