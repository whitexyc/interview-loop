# 变更日志 — Module-031: 知识库重建（父子分块 reindex）

## 变更概述
① **chunker 分块规则升级（Option C）**：由"仅按 `##` 分割"升级为「`##` + `###` 两级标题层级
+ 父块尺寸上限 4000 字符」。父块粒度 = 最小标题单元（如"板块6 > 题目2"），超大父块按段落
二次切分为多个 ≤4000 的子父块。根治"板块6 面试题"整节 12k~32k 字符并成一个父块导致的
生成上下文爆炸。
② **知识库全量重建**：库里 45 篇文档全部是旧版导入代码写入的"整篇 1 父 + 1 子"大块
（子块平均 2.1 万字符），当前分块从未真正执行过，导致嵌入 8192 token 截断（检索质量崩塌）+
rerank 对超长块推理（200-641s）。新增 `reindex_knowledge_base.py` 用当前源文件（backend-push +
llm-push 共 58 篇）重新分块 + 批量嵌入 + 重建知识图谱。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/chunker.py` | 修改 | 分块规则升级：默认 headers_to_split_on = [("##","section"),("###","subsection")]；新增 max_parent_chars=4000 父块尺寸上限（超限按段落切分为子父块）；fallback 加固（无标题 → 整篇作父块 + 子块分割 + 受上限约束）；抽 _build_title |
| `ai_service/tests/test_chunker.py` | 新增 | chunker 回归测试 8 个（## 多节 / ### 子小节标题 / 父块尺寸上限 / 无标题长文本 / 无标题超限切分 / 全短小节兜底 / 极短内容 / 空文本） |
| `ai_service/reindex_knowledge_base.py` | 新增 | 知识库重建脚本（--dry-run / --no-graph；按 title 先删后建幂等；镜像 add_document 入库逻辑；图谱清空重建） |

## 关键设计说明
### 设计决策 1: chunker 分块规则 Option C（## + ### + 父块 4000 上限）
- 决策: 默认 `headers_to_split_on = [("##","section"), ("###","subsection")]`，父块粒度 = 最小
  标题单元，标题路径如 "板块6 > 题目2"；新增 `max_parent_chars = 4000`，超过的父块用
  `RecursiveCharacterTextSplitter(4000/0)` 按段落二次切分为多个子父块。
- 原因: 实测仅按 `##` 切时 58 个源文件有 **57 个 >8000 字符父块**（最大 32,335，几乎全是
  "板块6 面试题"整节）；父块是返回给 LLM 的回答单元，尺寸需有界。加 `###` 后父块变题目级
  粒度（含 " > " 标题路径占 89%），再加 4000 上限后 **>4000 父块 = 0、最大 3,995**。
- 子块保持 300 字符（重叠 50）：检索聚焦 + 在 rerank 500 字符截断线之下（module-030），
  不触发截断；上下文由父块提供，故子块窄不丢上下文。
- 数据对照: 重建前 68 父块 / 子块平均 21,083 字符 / 0 个" > "父块 → 重建后 ~1136 父块 /
  ~6370 子块 / 无 >4000 父块 / 89% " > "父块。

### 设计决策 2: 无标题 fallback 加固
- 决策: 无任何 ##/### 标题时，整篇作单一父块（title 空）+ 子块二次分割（不再返回空、
  由引擎兜底存整篇单一子块）；整篇 >4000 同样被切分为多个子父块。内容 < min_chars(50)
  时仍返回空（引擎兜底 1 父 + 1 子，符合预期）。

### 设计决策 3: 重建脚本先删后建（幂等）+ 复用现有组件
- 决策: 逐篇文件按 title 先删旧记录（title=stem 或 LIKE 'stem > %'）再插入，可重复执行；
  分块用 `chunker`、嵌入用 `embedding_service.embed_documents`（本地 bge-m3，与 add_document
  同路径）、FTS 用 `tokenize`、入库字段镜像 add_document（content_hash / search_tokens /
  parent_id）。收尾清空 `rag:retrieve:` 检索缓存。
- 标题冲突（backend-push/overview.md 与 llm-push/overview.md）→ 后者加 "-llm-push" 后缀。
- 残留清理：重建后删除未导入的孤儿记录（如 test_dedup）。

### 设计决策 4: 知识图谱清空重建
- 决策: 重建后 `MATCH (n) DETACH DELETE n` 清空 knowledge_graph，再逐文档
  `graph_extractor.extract_from_document` 提取实体/关系，link 到该文档首父块 id
  （镜像 add_document 行为）。单篇提取失败不阻断（warning 后继续），可用
  `backfill_graph.py` 后补。`--no-graph` 可跳过。

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| chunker 单测 | `python -m pytest tests/test_chunker.py` | 8 passed |
| 全量回归 | `python -m pytest tests/` | 181 passed / 2 既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 起备案，无新增失败） |
| 语法检查 | `python -m py_compile rag/chunker.py reindex_knowledge_base.py tests/test_chunker.py` | OK |
| 重建 dry-run | `python reindex_knowledge_base.py --dry-run` | 58 文件 / 预计父块 1136 / 子块 6370 / 总字符 1,359,854 |
| 全量重建 | `python reindex_knowledge_base.py` | parents/children 入库，无 >4000 父块 |
| 重建后库内统计 | SQL 查询 | 无 >4000 父块 / 子块平均 ~300 / 89% " > "父块 |
| 检索质量 E2E | 真实检索"什么是G1垃圾收集器" | 返回 G1 文档（不再返回 Redis 缓存文档） |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-04 | 初始实现 | Developer |
