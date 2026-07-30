# M16: Graph RAG — 验收标准

## 1. 图存储
- [ ] ensure_graph 幂等创建 knowledge_graph
- [ ] upsert_entity MERGE 同义实体 doc_ids
- [ ] upsert_relation MERGE RELATED_TO 边

## 2. 实体提取
- [ ] extract_from_document 返回 {entities, relations}
- [ ] extract_from_query 返回实体名称列表
- [ ] LLM 返回非 JSON 时静默降级返回空

## 3. engine 集成
- [ ] add_document 入库后日志"Graph: extracted N entities"
- [ ] _retrieve round 0 并行向量+图搜索
- [ ] 合并去重（向量优先）
- [ ] 图搜索失败降级不阻塞

## 4. 代码质量
- [ ] 参数化 Cypher 查询（防注入）
- [ ] try/except 覆盖所有图操作
- [ ] 无新增 pip 依赖
- [ ] py_compile 通过

---

## 验收结论

- 验收人: Tester
- 验收时间: 2026-07-30
- 结论: **通过** ✅
- 全部 14 项验收标准通过。阻塞 bug（Cypher `:param` bindparams 在 `$$...$$` 内部失效）已修复 -- f-string + `_escape()` 转义，`_escape` 被调用 7 次。详见 `test-report.md`。
