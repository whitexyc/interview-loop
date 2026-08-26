# 验收标准 — Module-079: 增量 append 不重建路径验证（新增语料追加、无全量重嵌）

> 依据：ADR-0019 决策 3（增量 append 不重建索引）+ 阶段 3 验收标准第 3 项。
> 本模块为验证型模块：验收 1-4 锁定现有正确行为，验收 5 要求加固 `find_semantic_duplicate` 的 O(N)→O(K)（含 backlog ① ndarray bug 修复）。

## 1. 功能验收（对应 ADR-0019 阶段 3 五项）

### 1.1 增量嵌入（验收 1）
- [ ] 新文档入库时，`embedding_service.embed_documents` 仅对新文档的子块调用（调用次数 = 新文档子块数，mock 锁定）
- [ ] 入库过程对存量文档零嵌入调用（无全局重嵌）
- [ ] 嵌入服务抛异常时入库仍成功（fail-open，不阻断增量追加）

### 1.2 检索增量生效（验收 2）
- [ ] 新文档入库后，`_vector_search` 候选 SQL（`parent_id IS NOT NULL AND embedding IS NOT NULL`）能命中新文档子块（mock session 返回新 doc_id）
- [ ] `add_document` 提交后调用 `cache.delete_by_prefix("rag:retrieve:")` 清空检索缓存（缓存失效，新文档立即可检索）
- [ ] 真实冒烟（可选）：真实 PG + bge-m3 入库新文档后，`POST /ai/rag/search` 检索结果包含新文档

### 1.3 无全量重嵌（验收 3）
- [ ] 追加新文档前后，存量文档的 `embedding` 逐字节不变（mock session 记录 DML：仅出现 INSERT 新行，无 UPDATE/DELETE 存量行）
- [ ] 追加过程中无 reindex/rebuild/backfill 函数被调用（`reindex_knowledge_base.py` / `migrate_embedding_1024.py` / `backfill_graph.py` 均为手动运维脚本，不在自动入库路径）
- [ ] `graph_store.ensure_graph()` 幂等建图（非重建），`upsert_entity`/`upsert_relation` 幂等追加（重复执行不重复创建节点/边）

### 1.4 去重不破坏增量（验收 4）
- [ ] 入库文档 A → 相同内容再入库 → L1 `doc_content_hash` 命中返回 duplicate（不写库）→ 新文档 B 正常入库（duplicate=False，chunks>0）
- [ ] L1 去重命中不影响后续增量追加（去重分支与新增分支互不阻塞）
- [ ] `add_document` 内 title/content_hash 兜底去重命中返回 duplicate，不影响新文档追加

### 1.5 性能验证（验收 5，O(1) 而非 O(n)）
- [ ] `find_semantic_duplicate` 候选获取改为 pgvector SQL top-K：`ORDER BY embedding <=> :vec ASC LIMIT :k`，**K 固定**（`doc_dedup_candidate_top_k`，默认 50），不随存量文档数增长（SQL 断言带 `LIMIT :k`）
- [ ] 用不同存量文档数（mock）各跑一次入库，`embed_documents` 调用次数相同（增量成本与 N 无关）
- [ ] L2 语义去重只对 top-K 候选做余弦判定（不逐条遍历全表）
- [ ] 全链路增量环节复杂度：L1 哈希去重 O(log N)、L2 候选 O(log N + K)、嵌入 O(新文档子块数)、图提取 O(新文档)、缓存失效 O(1)（plan §4.1 论证成立）
- [ ] 真实冒烟（可选）：入库第 2 篇新文档的耗时与库中已有文档数无显著线性关系（同量级参考）

## 2. 边界与异常场景

### 2.1 语义去重 ndarray 兼容（backlog ① 修复）
- [ ] `find_semantic_duplicate` 候选 embedding 为 numpy ndarray（pgvector 0.2.5 返回形态）时不抛 ValueError，正常判阈值
- [ ] 候选 embedding 为 None / 维度不匹配时正确跳过
- [ ] 语义去重全链路（候选查询 → 余弦判定 → 标簇返回）失败时 fail-open（ingest 不阻断）

### 2.2 特殊字符与并发
- [ ] 含特殊字符的文档正常入库（去重链路不因字符崩）
- [ ] 两个并发入库请求互不干扰（各插入独立文档，无竞态）——已有并发基建覆盖，本模块不重复建，若存量测试已覆盖则标注引用

## 3. 非功能验收

### 3.1 代码质量（铁律）
- [ ] 本模块新增生产代码合计 ≤ 200 行（铁律 2；实际预计 ≤ 50 行，git diff --numstat 口径）
- [ ] 单方法 ≤ 50 行（铁律 3：`find_semantic_duplicate` 重写后）
- [ ] 所有新/改公开方法有 docstring（铁律 4）；魔法数字命名常量（`doc_dedup_candidate_top_k` 走 config）
- [ ] 无空 catch / 吞异常（铁律 5；fail-open 分支带日志注释即豁免）
- [ ] 复用 pgvector `<=>` 查询范式（retriever `_vector_search` / crawler `_conflict_candidates` 先例），无重写算法
- [ ] 测试代码不计入生产代码行数限制

### 3.2 性能
- [ ] 单条文档入库（mock 嵌入）候选查询不再全表拉取：SQL 带固定 LIMIT（断言锁定）
- [ ] 语义去重从 O(N) 降为 O(log N + K)，K=50 固定

### 3.3 健壮性 / 兼容性
- [ ] `find_semantic_duplicate` 返回契约不变（`{"id","title","cluster_id","cosine"}` 或 None），`ingest_document` 调用方零改动
- [ ] `doc_dedup_semantic_enabled`（默认 True）/ `doc_dedup_threshold`（0.95）/ `doc_dedup_boilerplate_enabled`（True）语义不变
- [ ] 存量 `tests/core/test_document_dedup.py` 行为断言不漂移（仅 mock 方式适配新查询形态）
- [ ] 全量回归 `tests/` 基线 1366 passed / 4 failed（module-028 proxies 环境性遗留）不降，0 新增失败

## 4. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 新增增量测试 | `cd ai_service && python -m pytest tests/core/test_incremental_append.py -v` | X passed, 0 failed |
| dedup 存量测试 | `cd ai_service && python -m pytest tests/core/test_document_dedup.py -v` | 存量断言全绿（含适配） |
| core 全量 | `cd ai_service && python -m pytest tests/core/ -q` | 存量 + 新增全绿 |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | 1366+X passed / 4 failed（基线遗留） |
| py_compile | `cd ai_service && python -m py_compile rag/retrieval/document_dedup.py src/config.py` | 无报错 |
| AST/行数 | REVIEW 阶段 `git diff --numstat` | 新增生产代码 ≤ 200 行 |
| 配置生效 | `$env:PW_DOC_DEDUP_CANDIDATE_TOP_K="20"; python -c "from src.config import settings; print(settings.doc_dedup_candidate_top_k)"` | 20 |
| pgvector 索引（REVIEW 检查项） | `psql -c "\d documents"` | embedding 列有向量索引（无 → 记遗留） |

## 5. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-08-26
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
