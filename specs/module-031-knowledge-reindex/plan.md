# 功能规格说明书 — Module-031: 知识库重建（父子分块 reindex）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-031 |
| 模块名称 | 知识库重建（父子分块 reindex） |
| 版本号 | 0.31.0-module-031 |
| 优先级 | P0（修复当前知识库检索质量与 rerank 性能的根因） |
| 预估代码量 | ≤ 400 行（重建脚本 + chunker 加固 + 测试） |
| 创建日期 | 2026-08-04 |
| 最后更新 | 2026-08-04 |
| 负责人 | Planner: 规划执行, Developer: 直接协作模式 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：本次会话实机诊断（2026-08-04）
- 原始描述：用户反馈"py 服务运行不稳定"。逐层排查后定位根因——**知识库数据过期**：
  库里 45 篇文档 **100% 是旧版导入代码写入的"整篇 1 父块 + 1 子块"大块**（父块平均 2.1 万字符，最长 71,253 字符），当前父子两级分块从未真正执行过。
  这导致：① 子块嵌入在 bge-m3 8192 token 处截断 → 检索质量崩塌（"什么是G1 GC" 检索返回 Redis 文档）；② rerank 对超长块逐对推理 → 单次 200-641s + 同步阻塞事件循环（module-030 修复已用 500 字符截断止血，但治标不治本）。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 知识库按父子分块真正切分、重新嵌入
以便 检索命中正确文档、rerank 快速、问答质量恢复
```

### 2.3 验收场景（BDD 格式）

```
场景 1：库内无超大块
  假设 重建完成
  当 统计父块长度
  那么 无 >8000 字符父块（对比重建前 68/68 全部超大）

场景 2：子块粒度正常
  假设 重建完成
  当 统计子块长度
  那么 平均 ~300 字符（对比重建前 21,083 字符）

场景 3：检索质量
  假设 问"什么是 G1 垃圾收集器"
  当 真实检索
  那么 返回 G1 文档（不再返回 Redis 缓存文档）

场景 4：无 ## 文档
  假设 一篇无 ## 标题的长文档
  当 chunker.chunk
  那么 得到 1 父块 + 多个子块（不退化单一子块）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 幂等 | 重建脚本可重复执行，不产生重复记录 |
| 兼容 | documents 表结构 / 检索接口 / 返回格式不变 |
| 降级 | 图谱重建失败不阻断文档重建（非致命） |
| 可观测 | 脚本每篇文件打印进度与统计 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/chunker.py` | 修改 | 分块规则升级：## + ### 两级标题 + 父块 4000 上限 + fallback 加固 |
| `ai_service/tests/test_chunker.py` | 新增 | chunker 回归测试（8 个，已完成） |
| `ai_service/reindex_knowledge_base.py` | 新增 | 知识库重建脚本（核心） |

### 3.2 业务逻辑说明

#### 功能 1：chunker 分块规则升级（Option C，用户确认 2026-08-04）

```
规则（三级分块）:
  一级: MarkdownHeaderTextSplitter 按标题层级分割
        headers_to_split_on = [("##","section"), ("###","subsection")]
        父块粒度 = 最小标题单元，标题路径如 "板块6 > 题目2"
        （对比旧规则只认 ##，"板块6 面试题"整节 12k+ 字符并成一个父块）
  二级: 父块尺寸上限 max_parent_chars = 4000
        超过的父块用 RecursiveCharacterTextSplitter(4000/0) 按段落二次切分为
        多个子父块 → 父块（回答单元）尺寸有界
  三级: 子块用 RecursiveCharacterTextSplitter(300/50) 二次分割 → 检索单元

fallback: 无任何标题 → 整篇作单一父块（title=""）+ 子块分割，
          同样受 4000 上限约束（无标题的超长文档也会被切成 ≤4k 子父块）
          < min_chars(50) 的极短内容返回空，由引擎兜底 1 父 + 1 子

子块 300 字符保持: 检索聚焦 + 在 rerank 500 截断线之下（module-030），不触发截断。
                  父块（回答单元）提供上下文，故子块窄不丢上下文。

实测（58 个真实源文件）:
  父块 1136 / 子块 6370
  >4000 字符父块 = 0（旧 ## 规则 101 个），>8000 = 0（旧 57 个），最大 3,995
  89% 父块为 ### 级粒度（含 " > " 标题路径）

验证: tests/test_chunker.py 8/8 通过
      （## 多节 / ### 子小节标题 / 父块尺寸上限 / 无标题长文档 / 无标题超限切分 /
        全短小节兜底 / 极短内容 / 空文本）
```

#### 功能 2：重建脚本 `reindex_knowledge_base.py`

```
目标: 用当前源文件重新分块 + 嵌入，替换全部旧版"整篇大块"记录。

流程（每篇文件）:
  1. 收集源文件: backend-push/ + llm-push/ 下所有 .md（跳过 .workbuddy/ 子目录）
     title = 文件名去 .md；source = "{dir}:{filename}"
     标题冲突（overview 两目录都有）→ 后者追加 "-llm" 后缀
  2. 删除旧记录: DELETE WHERE title = :stem OR title LIKE :stem || ' > %'
  3. chunker.chunk(content) → parents + children
     （无父块时镜像引擎兜底：整篇 1 父 + 1 子）
  4. 插入父块: embedding=NULL, parent_id=NULL, content_hash=sha256(parent content)
  5. 批量嵌入子块: embedding_service.embed_documents(child_texts)（复用本地 bge-m3）
  6. 插入子块: embedding=向量, parent_id=父块id, content_hash, search_tokens=tokenize()
  7. commit（每篇独立事务，失败不影响其他篇）

图谱重建（独立阶段）:
  - 清空 knowledge_graph（MATCH (n) DETACH DELETE n）
  - 每文档 graph_extractor.extract_from_document(整篇) → upsert_entity/relation
    link 到该文档首父块 id（镜像 add_document 行为）
  - 失败不阻断（非致命，日志 warning）

收尾:
  - cache.delete_by_prefix("rag:retrieve:") 全量失效检索缓存

CLI:
  python reindex_knowledge_base.py            # 全量重建
  python reindex_knowledge_base.py --no-graph # 跳过图谱重建
  python reindex_knowledge_base.py --dry-run  # 只统计源文件与预计块数，不写库
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 先删后建（按 title） | 幂等 + 可重跑；不整表清空，避免失败丢全部数据 |
| 复用 embedding_service | 与 add_document 同一嵌入路径，维度/归一化一致 |
| 复用 chunker/graph_extractor | 不重复实现分块/提取逻辑 |
| 图谱 link 首父块 id | 与 add_document 行为一致（粗粒度但既有约定） |
| --no-graph 逃生 | 图谱 LLM 提取配额受限时可跳过，文档重建不受阻 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 单篇文件嵌入/入库失败 | Exception | 记日志跳过该篇，继续后续（不整批回滚） |
| 嵌入模型加载失败 | EmbeddingException | 脚本终止并明确报错（无嵌入则数据不完整） |
| 图谱提取失败（单篇） | Exception | 非致命，warning 后继续（可后补 backfill_graph.py） |
| 文件缺失/不可读 | OSError | 跳过并记 warning |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 重建前统计（基线：68 父块，子块平均 21,083 字符）
python -c "..."

# 2. 全量重建（--dry-run 先看规模）
python reindex_knowledge_base.py --dry-run
python reindex_knowledge_base.py

# 3. 重建后统计（应无 >8k 父块，子块平均 ~300）
python -c "..."

# 4. 检索质量 E2E（G1 GC 查询）
python -c "...真实检索，看返回文档标题..."

# 5. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
重建前: 68 父块 / 子块平均 21,083 字符 / 0 个" > "标题父块
重建后: ~1100 父块 / ~6300 子块 / 无 >4000 字符父块 / 89% 父块为 ### 级粒度 / 子块平均 ~300
E2E: "G1 GC" 返回 G1 垃圾收集器文档
回归: ===== 181 passed, 2 failed (既有 async 债务) =====
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 重建后仍有超大块 | 源文件无 ## 且 fallback 未生效 | 检查 chunker 版本 + 单篇日志 |
| 子块数异常少 | 嵌入批量失败被跳过 | 检查脚本日志 warning |
| E2E 仍返回错误文档 | 检索缓存未失效 | 检查 rag:retrieve: 前缀清理 |
| 图谱旧引用残留 | 未清空图 | 检查 MATCH (n) DETACH DELETE 执行 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-017 | 父子分块结构（documents.parent_id） | ✅ |
| module-020 | 本地 bge-m3 GGUF 嵌入 + search_tokens FTS | ✅ |
| module-027 | embedding_service 并发锁（线程安全） | ✅ |
| module-030 | reranker 截断修复（配合新子块粒度） | ✅ |

### 5.2 下游依赖

无（独立数据迁移）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 全量嵌入耗时长（~20-30 分钟） | 重建期间知识库半成品 | 高 | 后台运行 + 分篇进度日志；建议期间暂停问答 |
| 图谱 LLM 提取配额/失败 | 图不完整 | 中 | --no-graph 逃生 + backfill_graph.py 后补 |
| 标题冲突（overview 两目录） | 后者被跳过 | 中 | 脚本自动加 "-llm" 后缀 |
| 内存峰值（脚本 + 服务各加载模型） | OOM | 低 | 先查可用内存，必要时 --no-graph 或停服务 |

### 6.2 技术注意事项

- [x] 已确认当前 chunker 对现有源文件可正确切分（G1 → 8 父 + 178 子）
- [x] 已确认库里 0% 是正常分割（68 父:68 子 1:1，全为旧导入数据）
- [x] 重建脚本复用 embedding_service / chunker / graph_extractor（不重复实现）
- [ ] 运行前检查可用内存（脚本 + 服务双模型实例）

### 6.3 开发建议

- 先 --dry-run 统计规模，再全量执行
- 文档重建与图谱重建分阶段，图谱失败不影响文档

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-04 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-04 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
