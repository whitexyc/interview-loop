# 变更日志 — Module-020: 中文 FTS 复活（jieba 预分词）

## 变更概述
复活 PG 全文检索通道对中文文档的召回能力。根因：PG `to_tsvector('simple', content)` 对无空格连续中文文本按整个字符串作为单个 lexeme（如 `'Java线程池核心参数'`），多字查询必然空召回（module-019 基线 FTS Hit@5=0）。本次引入 jieba 预分词：入库侧将子块内容分词后以空格连接写入新列 `search_tokens`，查询侧对用户 query 同样用 jieba 分词后走 `plainto_tsquery`，使中文词元可精确匹配。`python -m eval.golden_retrieval --mode fts_only` 实测 **Hit@5 从 0.0 提升到 0.4348**。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/text_tokenizer.py` | 新增 | jieba 分词工具（dict 缓存 + 空格连接 + 标点过滤） |
| `ai_service/backfill_search_tokens.py` | 新增 | search_tokens 列迁移 DDL + 已有子块分词回填（幂等，可重跑） |
| `ai_service/tests/test_text_tokenizer.py` | 新增 | 分词工具单元测试（中文/英文/空/标点/缓存，10 用例） |
| `ai_service/rag/models.py` | 修改 | Document 增加 `search_tokens` 列（Text, nullable） |
| `ai_service/rag/engine.py` | 修改 | add_document 子块写入 `search_tokens=tokenize(content)` |
| `ai_service/rag/retriever.py` | 修改 | `_fts_search` 改查 `search_tokens` + query 侧 jieba 分词 |
| `ai_service/requirements.txt` | 修改 | 新增 `jieba==0.42.1` |

## 关键设计说明
### 设计决策 1: jieba 分词 + `simple` 配置，不引入 zhparser 扩展
- 决策: 分词后空格连接写入 `search_tokens` 列，FTS 用 `to_tsvector('simple', search_tokens)`。
- 原因: `simple` 配置按空格切分即得到中文词元，无需安装 zhparser 扩展；分词逻辑收敛在 Python 层，可复用缓存、可控标点过滤。

### 设计决策 2: 只对子块分词，检索只查子块
- 决策: `add_document` 仅对子块（parent_id 非空）写入 `search_tokens`，父块不写；backfill 也只处理 `parent_id IS NOT NULL` 的行。
- 原因: 检索（FTS/向量）只查子块，命中后由 `_expand_to_parents` 映射回父块；父块无向量也不参与检索，写分词属浪费。

### 设计决策 3: query 侧分词与入库侧一致（都用 jieba）
- 决策: `_fts_search` 内先 `tokenize(query)` 再传给 `plainto_tsquery('simple', :tokenized_query)`。
- 原因: 两侧一致才能逐词精确匹配；`plainto_tsquery` 对空格分隔词元做 AND 匹配。query 分词后为空（纯标点/空串）时提前返回空列表。

### 设计决策 4: WHERE search_tokens IS NOT NULL 过滤未分词文档
- 决策: FTS SQL 只查 `search_tokens` 列且加 `IS NOT NULL` 过滤。
- 原因: 避免旧未分词文档干扰（旧文档即使 backfill 前也会被过滤）；分词失败/空内容的文档在 FTS 中不可见（检索降级，不影响向量通道）。

### 设计决策 5: backfill 脚本内嵌幂等迁移 DDL，单事件循环执行
- 决策: `backfill_search_tokens.py` 内置 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `COMMENT` + `CREATE INDEX ... GIN`，先迁移再回填。
- 原因: 一条命令完成"迁移+回填"，幂等可重跑；`--dry-run` 也先迁移（否则查询 `search_tokens` 列报错）。全部逻辑放在单 `asyncio.run()` 内，避免 Windows ProactorEventLoop 双 loop 复用 asyncpg 连接池导致 `'NoneType' object has no attribute 'send'`。

### 设计决策 6: 分词结果缓存（dict）
- 决策: `Tokenizer` 用 `dict` 缓存 `text -> tokens`，同一子块/查询串不重复分词。
- 原因: 入库批量分词与多轮检索会重复命中同一文本，缓存避免重复 CPU 计算；`jieba.cut` 是纯本地计算，GIL 保护下并发安全。

## 验证命令
| 验证项 | 命令 | 预期结果 | 实际结果 |
|--------|------|----------|----------|
| 分词工具 | `python -m pytest tests/test_text_tokenizer.py -v` | 10 passed | 10 passed ✅ |
| backfill | `python backfill_search_tokens.py --dry-run` → 迁移 + 计数 | 迁移成功，统计待回填数 | 迁移完成，待回填 68 ✅ |
| backfill | `python backfill_search_tokens.py` | 68 篇回填成功 | updated=68, failed=0 ✅ |
| FTS 评估 | `python -m eval.golden_retrieval --mode fts_only --no-save` | Hit@5 > 0.3 | Hit@5=0.4348, Recall@5=0.4348, MRR=0.3783 ✅（基线 0.0） |
| 入库写入 | 临时脚本 `_tmp_add_doc_check.py`（已清理） | 子块 search_tokens 非空 | child search_tokens='Java 线程 池 的 核心 参数 ...' ✅ |
| 回归 | `python -m pytest tests/ -v` | 无新增失败 | 34 passed + 2 failed（既有 test_engine async 收集问题，非本模块引入） |

> 注：2 个 failed 为 `tests/test_engine.py` 中 async 用例在缺 `pytest-asyncio` 环境下无法收集（project-context 已记录的既有技术债务），与 module-020 无关。

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：jieba 分词 + search_tokens 列 + FTS 改造 + backfill | Developer |
