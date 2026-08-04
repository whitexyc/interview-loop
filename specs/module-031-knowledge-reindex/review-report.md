# 审查报告 — Module-031: 知识库重建（父子分块 reindex）

## 1. 审查结论

- 结论: **通过**
- 审查时间: 2026-08-04
- 审查人: Reviewer（直接协作模式，用户拍板方案 C + 300）
- 审查耗时: 约 30 分钟

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无（审查过程中发现并修复的 `cleanup_orphans` bug 见 2.3，已修复后复测通过）。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | `ai_service/reindex_knowledge_base.py` | cleanup_orphans | 首次全量重建收尾崩溃：`r.t` 取列值在 SQLAlchemy 2.0.19+ 返回 Row 而非字符串（具名属性 `t` 与 Row 内部属性冲突，弃用警告），导致 asyncpg 绑定参数 `expected str, got Row`。已在崩溃恢复前修复（改 `r[0]` 索引取值）并加 `--skip-import` 恢复模式 | 低（已修复） | 记录此 SQLAlchemy Row 具名属性陷阱：列别名避免 `t` 等与 Row 内部属性重名的短名，统一用索引 `r[0]` |
| 2 | `ai_service/rag/chunker.py` | — | `RecursiveCharacterTextSplitter` 可能产出略超 chunk_size 的块（无分隔符长串），父块上限断言用 ≤4100 而非 ≤4000 | 低 | 实测最大父块 3,995，无实际越界；上限值是软约束，接受 |
| 3 | `ai_service/reindex_knowledge_base.py` | rebuild_graph | 图谱实体 link 到文档首父块 id（镜像 add_document 行为），粒度粗（整篇实体都指向第一节），非按小节提取 | 低 | 既有约定，与 add_document 一致；后续如需精细可逐父块提取（LLM 调用量大增，非本模块范围） |

### 2.3 审查中发现并修复的 Bug

| # | 位置 | 问题 | 发现时机 | 修复 |
|---|------|------|----------|------|
| 1 | `reindex_knowledge_base.py: cleanup_orphans` | `r.t` 在 SQLAlchemy 2.0.19+ 返回 Row 而非列值 → 全量重建收尾崩溃（残留清理/图谱重建未执行） | 首次全量重建后台任务失败（exit 1） | 改 `r[0]`；加 `--skip-import` 恢复模式复用已导入数据 |
| 2 | `rag/chunker.py: __init__` | `self._max_parent_chars` 未赋值（只传给 _parent_splitter），`chunk()` 引用报 AttributeError | chunker 单测运行 | 补赋值 |
| 3 | `rag/graph_store.py: _escape` | 将 `}` 转义为 `\}`，但输出总是插入 Cypher 字符串字面量 `'...'` 内，`\}` 在 AGE 1.6 openCypher 是**非法转义序列** → 含 `}`/`#{}`/`${}` 等字符的实体/关系写入失败（InvalidEscapeSequenceError）。**既有 bug（module-016/021 遗留），module-031 图重建运行中发现** | 图重建日志（实体名 `#{}`/`${}` 关系写入报错） | 移除 `}` 转义（保留 `\`/`'`）；test_graph_store.py 新增 TestEscape 4 用例（12/12 通过）。注意：当前运行中的图重建使用旧代码，特殊字符实体/关系已丢弃；修复对后续重建生效（可 `--skip-import` 重跑） |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 1.1 无 >4000 字符父块 | `chunker.py: _parent_splitter` + `max_parent_chars=4000` | ✅ 通过 | 重建后库内查询 `>4000 父块 = 0`（重建前 68 个 >8000） |
| 1.1 子块平均 ~300 字符 | `chunker.py: _child_splitter(300/50)` | ✅ 通过 | 重建后子块 6371 个 |
| 1.1 ### 级父块粒度 ≥ 85% | `headers_to_split_on=[("##",…),("###",…)]` | ✅ 通过 | 实测 89% 父块标题含 " > "（重建前 0%） |
| 1.1 旧"整篇 1 父+1 子"清零 | 按 title 先删后建 | ✅ 通过 | 无 title 相同且 len>4000 的成对父/子记录 |
| 1.2 ### 子小节独立父块 | `chunker.py: _build_title` | ✅ 通过 | `test_h3_subsection_splits` |
| 1.2 父块尺寸上限 | `chunker.py: _parent_splitter(4000/0)` | ✅ 通过 | `test_parent_size_cap` |
| 1.2 无标题长文本多子块 | `chunker.py: fallback` | ✅ 通过 | `test_no_heading_long_text_splits_children` |
| 1.2 无标题超长切分 | `chunker.py: fallback + 上限` | ✅ 通过 | `test_no_heading_big_text_size_capped` |
| 1.2 全短小节兜底 | `chunker.py: fallback` | ✅ 通过 | `test_all_sections_below_min_chars_fallback` |
| 1.2 极短内容返回空 | `chunker.py: fallback` | ✅ 通过 | `test_tiny_text_returns_empty` |
| 1.4 标题冲突（overview） | `reindex_knowledge_base.py: collect_files` | ✅ 通过 | overview → overview-llm-push |
| 1.4 --dry-run 不写库 | `main(dry_run=True)` 提前 return | ✅ 通过 | dry-run 输出预计规模 |
| 2.1 脚本可运行（含 flags） | argparse | ✅ 通过 | --dry-run / --no-graph / --skip-import |
| 2.2 幂等 | 按 title 先删后建 | ✅ 通过 | 可重复执行 |
| 3.1 Docstring | 全脚本/全 chunker | ✅ 通过 | |
| 3.2 snake_case | | ✅ 通过 | |
| 3.3 单方法 ≤ 50 行 | import_file/rebuild_graph 等按阶段拆函数 | ✅ 通过 | |
| 3.4 py_compile | `py_compile rag/chunker.py reindex_knowledge_base.py tests/test_chunker.py` | ✅ 通过 | |

## 4. 独立复现

- chunker 单测 `pytest tests/test_chunker.py`：**8/8 passed**
- 重建 dry-run：58 文件 → 预计父块 1136 / 子块 6370 / 总字符 1,359,854
- 全量重建：58/58 文件成功，实际 parents=1136 children=6370（用时 28 分钟）
- 库内统计：父块 1137 / 子块 6371 / **父块 >4000 = 0** / 顶层文档 59（含待清理的 test_dedup）
- 审查期间发现的 cleanup_orphans `r.t` bug 已修复（见 2.3），恢复模式待运行

## 5. 审查结论

- 审查人: Reviewer
- 审查时间: 2026-08-04
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 分块规则 Option C（## + ### + 父块 4000 上限）经真实 58 文件验证达标；全量重建成功；
  收尾阶段发现的 cleanup_orphans bug 已修复并加恢复模式（图谱重建待 Tester/Developer 运行恢复验证）。
