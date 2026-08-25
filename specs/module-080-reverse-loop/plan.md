# 开发计划 — Module-080: 反向闭环（低分题→待学笔记→自动抓取优先级）

## 1. 需求描述
- 需求来源: ADR-0019 验收标准最后一项「反向闭环：低分题→待学笔记→自动任务优先抓取 链路打通」
- 功能描述: 面试中低分题（候选人不熟悉/答错的知识点）沉淀为「待学笔记」（source='weak_topic:<identity>:'）→ 主题关键词提取 → 提升 source_configs 中匹配主题的源的抓取优先级（priority 列）→ 定时抓取时按 priority 降序优先抓取弱项主题对应源 → 形成"面试发现弱点→知识库补强"闭环
- 优先级: P0（ADR-0019 最后一个验收项，阶段3 完成后的收口模块）
- 上下文: 阶段1-3 全部完成（074 出题注入 / 075 抓取流水线 / 076 递归 / 077 反爬 / 078 审查增强 / 079 增量 append），本模块打通"反向"链路。

### 数据探查结论

#### 低分题来源
- **feedback 表**（database.py FEEDBACK_DDL）：`message_id + rating(1/-1) + comment + identity`，前端 👍👎 飞轮数据源。rating=-1 表示踩（低分），关联 AI 回复。
- **AI 回复内容**：通过 `message_id` 可关联到聊天记录（IP_SESSION_MESSAGES 内存态 / session_memory DB），但 message_id 在当前架构中为前端生成的标识符，**没有直接关联到 conversations/messages 表**（Java 面试系统侧的 InterviewQuestion/InterviewSession 在 MongoDB，Python RAG 侧无直连）。
- **实际可用路径**：`/ai/feedback` 端点已存在（main.py:384），rating=-1 的 feedback 落库后，其 `comment` 字段（可选 ≤500 字符）包含用户补充的薄弱知识点描述；**无 comment 时需从对应 AI 回复的 sources 中提取主题**——但 sources 不落 feedback 表。
- **待澄清**：Java 面试系统侧（InterviewQuestion / InterviewSession in MongoDB）是否有"题目+分数"结构化数据可调 Python 端 `/ai/feedback` 或新端点？当前 Python 侧仅有 feedback 表的 👍👎。**本模块优先基于 feedback 表 rating=-1 驱动**，Java 侧集成留后续扩展。

#### 待学笔记存储选型
- **选型：复用 documents 表，新 source 前缀 `weak_topic:<identity>:`**（对齐 module-023/033/034 的 `memory:<identity>:` 分层模式）
  - 理由：复用已有的分块/chunker/embedding/检索/去重全链路，零新表，与现有记忆体系同架构
  - source 隔离：`weak_topic:<identity>:` 精确匹配，不污染 memory/knowledge 检索
  - 待学笔记 = 一条 documents 记录（title=主题关键词，content=薄弱点描述+来源上下文，source=`weak_topic:<identity>:`）
- 备选方案排除：新建 `weak_topics` 表——需重写 CRUD + 向量化 + 检索，违反"不造轮子"原则

#### 优先级接法
- **source_configs 表新增 `priority INT DEFAULT 0`** 列（幂等 ALTER，对齐 module-076 max_depth 模式）
- 优先级语义：数字越大越优先；默认 0（正常）；待学笔记匹配的源 +N（N=待学笔记匹配主题命中数）
- **接线方式**：`_load_sources_from_db()` 按 `ORDER BY priority DESC, id ASC` 排序 → 同一 run_crawl 周期内高优先源先抓
- **优先级计算**：`run_crawl` 入口处扫描待学笔记 → 提取主题关键词 → 与各源 `url_pattern`/`name` 做关键词匹配 → 动态提升匹配源的内存态 priority（不写回 DB，每次 run 动态算）

## 2. 模块拆分

### 子任务 1: 待学笔记落库（feedback → weak_topic）
- 描述: 新增 `/ai/weak-topics/ingest` 端点：接收 feedback_id（或直接传 topic + context），从 feedback 表读取 rating=-1 的记录 → 提取主题关键词（LLM 提取或 comment 直接作为主题）→ 调 memory_service 风格的 `save_weak_topic(content, identity)` 写入 documents（source=`weak_topic:<identity>:`，复用分块/嵌入/去重链路）
- 预估代码量: 功能代码 ≤ 60 行
- 涉及文件:
  - `ai_service/rag/memory/weak_topics.py`（新建，~60 行：save_weak_topic + recall_weak_topics + 格式化）
  - `ai_service/main.py`（新增 1 个端点 POST /ai/weak-topics/ingest）
  - `ai_service/rag/schemas.py`（新增 WeakTopicIngestRequest）
- 依赖: 无

### 子任务 2: 抓取优先级机制
- 描述: source_configs 表新增 `priority INT DEFAULT 0` 列（幂等 ALTER）；`_load_sources_from_db()` 返回含 priority 字段；`run_crawl` 入口扫描待学笔记关键词 → 与源 url_pattern/name 匹配 → 动态提升内存态 priority → 按 priority DESC 排序后执行抓取
- 预估代码量: 功能代码 ≤ 50 行
- 涉及文件:
  - `ai_service/src/database.py`（新增 CRAWL_PRIORITY_DDL + ensure_crawl_priority_column + init_db 挂接）
  - `ai_service/rag/crawl/crawler.py`（`_load_sources_from_db` 返回 priority + `run_crawl` 入口加 `_prioritize_sources` 函数）
  - `ai_service/src/config.py`（新增 `weak_topic_priority_boost: int = 10`）
  - `ai_service/main.py`（POST /ai/crawl/sources 端点支持 priority 字段 + GET 返回 priority）
- 依赖: 子任务 1

### 子任务 3: 端到端验证 + 测试
- 描述: 端到端链路测试（feedback rating=-1 → 待学笔记落库 → 抓取优先级生效）+ 单元测试
- 预估代码量: 测试代码 ~100 行（不含在 ≤200 行生产代码限额内）
- 涉及文件:
  - `ai_service/tests/memory/test_weak_topics.py`（新建，~60 行）
  - `ai_service/tests/crawl/test_crawl_priority.py`（新建，~40 行）
- 依赖: 子任务 1 + 子任务 2

## 3. 技术方案

### 3.1 数据表变更
- `source_configs` 新增列:
  - `priority INTEGER NOT NULL DEFAULT 0` — 抓取优先级（数字越大越优先，默认 0）
- DDL: `ALTER TABLE source_configs ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;`
- init_db 幂等 ALTER（对齐 module-076 max_depth / module-078 review_score 模式）

### 3.2 待学笔记存储（documents 表复用）
- source 前缀: `weak_topic:<identity>:`（对齐 `memory:<identity>:` 三层分层模式）
- 父块: title=主题关键词，content=薄弱点描述（含来源上下文），source=`weak_topic:<identity>:`
- 子块: 含向量（复用 embedding_service），供检索匹配
- 去重: 复用 memory_service._find_duplicate 逻辑（仅在 weak_topic 层内查重）
- 隔离: 检索时 source_pattern 精确匹配，不污染 memory/knowledge

### 3.3 优先级计算（动态内存态，不写回 DB）
```
run_crawl(sources):
  1. weak_topics = recall_weak_topics()  # 从 DB 读待学笔记
  2. keywords = extract_keywords(weak_topics)  # 提取主题关键词（简单：从 title 字段取）
  3. for src in sources:
       src["_priority"] = src["priority"]  # DB 静态优先级
       for kw in keywords:
         if kw in src["url_pattern"].lower() or kw in src["name"].lower():
           src["_priority"] += settings.weak_topic_priority_boost  # 动态提升
  4. sources.sort(key=lambda s: s["_priority"], reverse=True)
  5. 正常递归抓取...
```

### 3.4 API 端点
- `POST /ai/weak-topics/ingest` — 手动/自动录入待学笔记（传 topic + context + identity）
- `GET /ai/weak-topics` — 列出当前待学笔记（按身份隔离）
- `POST /ai/crawl/sources` — 新增可选 `priority: int = 0` 字段
- `GET /ai/crawl/sources` — 返回新增 `priority` 字段
- `POST /ai/crawl/run` — 行为变化：抓取前动态计算优先级

### 3.5 与现有机制的复用清单

| 复用项 | 来源 | 说明 |
|--------|------|------|
| documents 表 | 全局 | 待学笔记复用表，source 前缀隔离 |
| memory_service._save 分块/嵌入/去重 | memory.py | weak_topics.py 参考同款 save 逻辑 |
| embedding_service.embed_text | rag/retrieval/embeddings.py | 待学笔记向量化 |
| chunker.chunk | rag/retrieval/chunker.py | 待学笔记分块 |
| _load_sources_from_db | crawler.py | 扩展返回 priority 字段 |
| run_crawl / _recursive_crawl | crawler.py | 仅入口加优先级排序，递归逻辑零改动 |
| fetch_page / _review_content / _crawl_page_and_store | crawler.py | 抓取/审查/入库链路零改动 |
| APScheduler | crawler.py | 定时抓取零改动 |
| source_configs 表 | database.py | 新增 priority 列 |
| feedback 表 | database.py | 低分题数据源 |
| reflector / factcheck_judge | agent/rag/retrieval | 审查节点零改动 |

### 3.6 生产代码行数预算（铁律 2 ≤ 200 行）

| 改动点 | 预估行数 |
|--------|---------|
| weak_topics.py（save + recall + 格式化） | ~55 |
| database.py（PRIORITY_DDL + ensure + init_db 挂接） | ~10 |
| crawler.py（_load_sources 返回 priority + _prioritize_sources + run_crawl 排序） | ~25 |
| main.py（POST /ai/weak-topics/ingest + GET /ai/weak-topics + sources 端点 priority 支持） | ~30 |
| schemas.py（WeakTopicIngestRequest） | ~8 |
| config.py（weak_topic_priority_boost） | ~3 |
| **合计** | **~131** |

## 4. 验收标准
见同目录下的 `acceptance-criteria.md`

## 5. 风险评估
- **风险 1: 低分题数据稀疏**（feedback rating=-1 可能很少，或无 comment）
  - 应对: 支持手动录入待学笔记（POST /ai/weak-topics/ingest），不依赖 feedback 自动链路；feedback 自动链路为增量优化
- **风险 2: 关键词匹配过于简单**（url_pattern/name 与待学笔记关键词不匹配）
  - 应对: 首版用简单子串匹配（`in` 操作），后续可升级为 embedding 余弦匹配；匹配失败不阻断抓取（正常优先级 0）
- **风险 3: source_configs 表 priority 列迁移**
  - 应对: init_db 幂等 ALTER（对齐 max_depth/review_score 先例），存量行默认 0
- **风险 4: 待学笔记与知识库检索隔离**
  - 应对: source 前缀 `weak_topic:` 精确匹配，retriever._source_condition 默认排除 `weak_topic:%`（对齐 `memory:%` 排除模式）
- **风险 5: Java 面试系统侧数据未直连**
  - 应对: 如实标注为「待澄清」，本模块基于 Python 侧 feedback 表；Java 侧集成可通过调 `/ai/weak-topics/ingest` 端点实现
- **风险 6: 优先级提升过于激进**（所有源都被提升 = 无优先级）
  - 应对: `weak_topic_priority_boost=10` 可配置；匹配条件严格（子串精确匹配）

## 6. 待澄清
1. **Java 面试系统侧数据结构**：InterviewQuestion / InterviewSession（MongoDB）是否有"题目+分数"结构化数据可直接传给 Python 端？若有，需新增从 Java 侧调 `/ai/weak-topics/ingest` 的集成代码。
2. **feedback 与 AI 回复的关联**：当前 feedback 表仅有 message_id（前端生成标识），无法直接关联到 AI 回复的 sources/内容。是否需要在 feedback 落库时同时保存 AI 回复摘要？
3. **待学笔记自动过期**：是否需要 TTL（如掌握后自动标记已学）？首版建议不过期，手动管理。
4. **优先级提升幅度**：`weak_topic_priority_boost=10` 是否合适？需实际测试确定。

## 7. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本 | Planner |

## 8. 复用 module-075~079 逻辑清单

| 复用项 | 来源 | 说明 |
|--------|------|------|
| `fetch_page(url)` | crawler.py (075) | 单页抓取，不修改 |
| `_review_content(url, content, title)` | crawler.py (078) | 审查节点，不修改 |
| `_crawl_page_and_store(url, summary)` | crawler.py (076) | 递归页处理，不修改 |
| `_recursive_crawl(...)` | crawler.py (076) | 递归引擎，不修改 |
| `ingest_document(...)` | document_ingest.py (064) | 入库管线，不修改 |
| `run_crawl(sources, max_pages)` | crawler.py (075) | **仅入口加优先级排序** |
| `_load_sources_from_db()` | crawler.py (075) | **扩展返回 priority 字段** |
| `source_configs` 表 | database.py (075) | **新增 priority 列** |
| `documents` 表 | 全局 | **复用存待学笔记** |
| `memory_service._save` 分块/嵌入/去重 | memory.py (023/033/034) | weak_topics.py 参考同款 |
| `feedback` 表 | database.py (048) | 低分题数据源，不修改 |
| `APScheduler` | crawler.py (075) | 定时调度，不修改 |
| `review_status / review_score` 四层透传 | 075/078 | 抓取入库链路，不修改 |

## 9. 不在本模块范围
- Java 面试系统侧集成（InterviewQuestion/InterviewSession MongoDB → Python 端点调用）
- 待学笔记自动过期/掌握标记
- 高级关键词提取（embedding 余弦匹配替代子串匹配）
- 面试评分系统直连（需 Java 侧配合）
- Playwright 无头浏览器渲染（module-077 已排除，留后续按需）
