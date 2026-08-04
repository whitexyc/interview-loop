# 测试报告 — Module-031: 知识库重建（父子分块 reindex）

## 1. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-04
- 测试人: Tester
- 测试耗时: 约 60 分钟（含 28 分钟全量重建）

## 2. 单元测试

### 2.1 chunker 回归测试（tests/test_chunker.py）

```
$ python -m pytest tests/test_chunker.py -q
8 passed in ~31s
```

| # | 用例 | 覆盖 |
|---|------|------|
| 1 | test_split_multi_section | 多个 ## 小节 → 多个父块 + 子块二次分割 |
| 2 | test_h3_subsection_splits | ### 子小节独立父块，标题 "小节 > 子小节" |
| 3 | test_parent_size_cap | 超大 ## 小节 → 多个 ≤ 上限子父块 |
| 4 | test_no_heading_long_text_splits_children | 无 ## 长文本 → 1 父 + 多子块 |
| 5 | test_no_heading_big_text_size_capped | 无 ## 超长文本 → 多个子父块 |
| 6 | test_all_sections_below_min_chars_fallback | 全短小节 → 整篇兜底 + 多子块 |
| 7 | test_tiny_text_returns_empty | 极短内容 → 返回空（引擎兜底） |
| 8 | test_empty_and_blank | 空文本/纯空白 → 返回空 |

### 2.2 全量回归

```
$ python -m pytest tests/ -q
193 passed, 2 failed  （module-031 后）
```
- 基线口径：module-030 后全量 181 passed / 2 既有 async 债务失败（module-031 改动前实测）
- module-031 新增 12 个测试（test_chunker 8 + test_graph_store 4）全部通过 → 181 + 12 = **193 passed**
- 2 项既有 async 技术债务失败（`tests/test_engine.py` 缺 pytest-asyncio，module-018 起备案，
  非本模块回归，与基线完全相同，零新增失败）

## 3. 数据验证（重建后真实库查询）

### 3.1 库内统计（对比重建前）

| 指标 | 重建前 | 重建后 | 达标 |
|------|--------|--------|------|
| 父块 >4000 字符 | 68（全部，平均 2.1 万字符） | **0** | ✅ |
| 子块数 | 68 | **6371** | ✅ |
| 父块标题含 " > "（### 级粒度） | 0% | **~89%** | ✅ |
| 顶层文档数 | 45 | **58**（+llm-push 新增 6 篇 + 笔记/overview） | ✅ |
| 子块平均长度 | 21,083 字符 | **~300 字符** | ✅ |

### 3.2 重建过程日志

```
[1/58] 0-java定时任务提示词 | parents=17 children=33 (13s)
[2/58] 1-G1垃圾收集器... | parents=23 children=183 (61s)
...
[58/58] 笔记 | parents=1 children=1 (1679s)
=== 文档重建: parents=1136 children=6370 用时 1679s ===
```
58/58 文件全部成功，实际 parents=1136 / children=6370 与 dry-run 预估一致。

## 4. 图谱与 E2E

### 4.1 知识图谱重建（--skip-import 恢复模式）

- [x] 图谱已清空 + 逐文档 LLM 提取（59 篇全部处理，**ok=59 / failed=0**）
- [x] 提取结果：**实体 1746 / 关系 1745**（提取含 test_dedup 1 个死引用实体，指向已删文档，清理中）
- [x] 全量重建失败收尾已恢复：cleanup_orphans `r.t` bug 修复 + `--skip-import` 模式
- [x] 既有 `_escape` bug（`}` 转义致 AGE 非法转义）已修复，当前图重建使用旧代码（特殊字符实体丢弃），修复对后续重建生效

### 4.2 检索质量 E2E（真实服务，uvicorn + SSE）

- [x] **"什么是G1垃圾收集器的Region分区机制"** → retrieval count=2 relevant=2，previews 首条
      **`1-G1垃圾收集器的Region分区机制与MixedGC全流程`** ✅（重建前此查询返回 Redis 缓存文档）
- [x] **"Redis缓存穿透击穿雪崩怎么解决"** → retrieval count=4 relevant=4，首条
      `10-Redis持久化机制` + 相关 Redis 文档 ✅
- [x] reflection=sufficient（两条查询均判定文档充足）
- [x] rerank 性能：冷路径（含 2.17GB 模型加载）8.7s；暖路径 4 pair ~6s（截断 500 字符内）
- [x] 端到端耗时：冷 32.0s / 暖 21.3s（对比重建前 400-700s 卡死）
- [x] 无 error 事件，token 流正常（331 / 654 tokens）

## 5. 测试命令

```bash
cd ai_service
python -m pytest tests/test_chunker.py -q
python -m pytest tests/ -q
python reindex_knowledge_base.py --dry-run
python reindex_knowledge_base.py          # 全量重建
python reindex_knowledge_base.py --skip-import  # 恢复：清残留 + 图谱重建
```

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-04 | 初始实现 | Developer |
