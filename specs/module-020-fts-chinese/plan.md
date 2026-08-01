# 功能规格说明书 — Module-020: 中文 FTS 复活（jieba 预分词）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-020 |
| 模块名称 | 中文 FTS 复活（jieba 预分词 + tsvector 列） |
| 版本号 | 0.20.0-module-020 |
| 优先级 | P0 |
| 预估代码量 | ≤ 300 行（含迁移脚本 + 入库改动，需调整上限） |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

> **代码量调整理由**：含 search_tokens 列迁移脚本（约 80 行）+ engine.add_document 改动（约 40 行）+ retriever._fts_search 改动（约 60 行）+ jieba 分词工具（约 40 行）+ 测试。合计约 300 行。

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-019 评估基线驱动 + 用户确认
- 原始描述：FTS 通道 Hit@5 = **0.0**（module-019 基线）。根因是 PG `to_tsvector('simple', content)` 对中文按"字"分词（每个汉字独立 lexeme），多字查询必然空召回。需用 jieba 预分词解决。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 关键词检索（FTS）能命中中文文档
以便 专有名词/代码片段查询（Java/Kafka 等）也能被召回，提升混合检索整体质量
```

### 2.3 验收场景（BDD 格式）

```
场景 1：入库时写入 jieba 分词
  假设 文档入库
  当 分块 + 写库
  那么 search_tokens 列包含空格连接的分词（如 "Java 线程 池 核心 参数"）

场景 2：中文查询 FTS 命中
  假设 检索 "Java线程池参数"
  当 走 FTS 通道
  那么 命中包含"线程池"的文档（而非空召回）

场景 3：评估基线提升
  假设 运行 golden_retrieval --mode fts_only
  当 计算指标
  那么 Hit@5 从 0.0 提升到 > 0.3
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | `_fts_search` SQL 兼容已有 documents 表 |
| 性能 | GIN 索引保证查询不退化 |
| 迁移 | 已有 136 篇文档需 backfill search_tokens |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/text_tokenizer.py` | 新增 | jieba 分词工具（缓存 + 空格连接） |
| `ai_service/rag/models.py` | 修改 | Document 增加 `search_tokens` 列 |
| `ai_service/rag/engine.py` | 修改 | add_document 写入 search_tokens |
| `ai_service/rag/retriever.py` | 修改 | `_fts_search` 改查 search_tokens + query 分词 |
| `ai_service/backfill_search_tokens.py` | 新增 | 已有文档 backfill 分词 |
| `ai_service/requirements.txt` | 修改 | 新增 jieba |

### 3.2 数据库变更

修改现有 `documents` 表，新增列：

```sql
ALTER TABLE documents ADD COLUMN IF NOT EXISTS search_tokens TEXT;
COMMENT ON COLUMN documents.search_tokens IS 'jieba分词后的空格连接文本（用于中文FTS检索）';

CREATE INDEX IF NOT EXISTS idx_documents_search_tokens
    ON documents USING GIN (to_tsvector('simple', search_tokens));
```

### 3.3 API 接口定义

无 HTTP API 变更（内部检索逻辑）。

### 3.4 业务逻辑说明

#### 核心流程

```
1. 分词工具 text_tokenizer.py:
   jieba.cut(text) → 空格连接 → 返回分词串
   结果缓存（dict），避免重复分词

2. 入库（engine.add_document）:
   分块后，对每个子块 content 调 tokenizer → search_tokens
   父块可不分词（检索只查子块）

3. FTS 检索（retriever._fts_search）:
   旧: to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
   新: to_tsvector('simple', search_tokens) @@ plainto_tsquery('simple', :tokenized_query)
   其中 tokenized_query = jieba分词(query) 空格连接
   WHERE search_tokens IS NOT NULL（过滤未分词文档）

4. backfill 脚本:
   遍历所有子块文档（parent_id IS NOT NULL），jieba 分词写 search_tokens
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| jieba 分词 + simple 配置 | 分词后空格连接，`simple` 按空格分词即正确（无需 zhparser 扩展） |
| 只查 search_tokens 不查 content | 避免旧未分词文档干扰 |
| query 侧也 jieba 分词 | plainto_tsquery 对空格分隔的词元逐词匹配 |
| 结果缓存 | dict 缓存，避免同一文本重复分词 |

### 3.5 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| jieba 未安装 | ImportError | 明确报错提示 pip install jieba |
| 某文档分词失败 | Exception | 跳过并记录（该文档 FTS 不可见） |
| search_tokens 列为空 | None | FTS 查询过滤（WHERE search_tokens IS NOT NULL） |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
# 1. 分词工具测试
cd ai_service
python -c "
from rag.text_tokenizer import tokenize
t = tokenize('Java线程池核心参数')
print(t)  # 期望: java 线程 池 核心 参数
"

# 2. backfill 已存在文档
python backfill_search_tokens.py

# 3. FTS 评估
python -m eval.golden_retrieval --mode fts_only

# 4. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
# 分词
java 线程 池 核心 参数

# FTS 评估
Hit@5: 0.3+（从 0.0 提升）
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 分词返回空 | jieba 加载失败 | 检查 jieba 安装 |
| FTS 仍为 0 | search_tokens 未 backfill | 检查 documents 表 search_tokens 是否为空 |
| 评估慢 | 未建 GIN 索引 | 检查索引是否存在 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-019 | golden_retrieval 评估基线 | ✅（Hit@5=0 基线） |
| — | jieba（需安装） | ⏳ |

### 5.2 下游依赖

| 被依赖模块 | 提供内容 | 状态 |
|------------|----------|------|
| 混合检索增强 | FTS 通道真正生效 | 📋 |

### 5.3 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| 无（jieba 本地库） | 中文分词 | — |

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| jieba 分词精度 | 部分词汇分词不准 | 低 | 可加自定义词典 |
| backfill 耗时 | 136 篇重新分词 | 低 | 纯本地 CPU，快 |

### 6.2 技术注意事项

- [x] search_tokens 只对子块写入（检索只查子块）
- [x] query 侧分词与入库侧一致（都用 jieba）
- [x] 需建 GIN 索引
- [ ] 旧文档需 backfill（否则 FTS 查不到旧文档）

### 6.3 开发建议

- 优先实现分词工具 + _fts_search 改动，backfill 后测
- 用 golden_retrieval fts_only 验证提升
- 分词语料为技术文档（Java/Redis/Kafka），如精度不足可加自定义词典

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-01 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
