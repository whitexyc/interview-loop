# 开发计划 — Module-078: 审查节点增强（质量评分阈值校准 + 矛盾检测 + 审查策略强化）

## 1. 需求描述

- 需求来源: ADR-0019 决策1（审查改写：复用反思+双判）+ module-075 plan.md §8（阶段2 后续模块拆分表）
- 功能描述: 增强 module-075 的审查节点 `_review_content`——① factcheck_judge 阈值 0.3 硬编码配置化（可动态调整）② 接入矛盾检测（NLI 判定新抓取文档与库中已有文档是否矛盾，复用 `nli_judge` / `memory_conflict_clf`）③ 新增审查评分字段 `review_score`（入库记录质量分）④ 审查策略三档可配置（fail-open / lenient / strict）⑤ 审查日志增强（评分 / 矛盾检测结果 / 耗时）
- 优先级: P0（阶段2 第三片，审查质量兜底）
- 上下文: module-075 已实现基础审查（reflector.check_sufficiency + factcheck_judge 0.3 阈值，fail-open），module-076 已实现受控递归。本模块只增强审查节点，不动抓取/递归/入库主链路结构。

### module-075 审查现状核实（代码实证，2026-08-26）

| 局限项 | 现状（crawler.py `_review_content`） | 本模块处置 |
|--------|--------------------------------------|-------------|
| 阈值硬编码 | `if scores and scores[0] < 0.3` 字面量 0.3 写死，config 无来源 | 配置化 `crawl_hhem_threshold`（默认 0.3 零回归）+ strict 档 `crawl_hhem_threshold_strict` |
| 无矛盾检测 | 审查只用 sufficiency（reflector）+ 质量分（hhem），未与库中已有文档比对 | 新增 `_check_conflict`：embedding 候选 top-K + 复用 `settings.memory_conflict_judge` 判定器（clf/nli/dual，默认 dual 双确认） |
| 二元判定无评分 | 返回 "approved"/"rejected" 字符串，无质量分落库 | documents 新增 `review_score` 列（HHEM score，NULL=不可用），四层透传（crawler→ingest_document→add_document→Document ORM） |
| 异常默认放行 | 任何审查异常 → approved（fail-open），无策略区分 | `crawl_review_policy` 三档：fail-open（默认，零回归）/ lenient（矛盾参与判定，异常仍放行）/ strict（异常 fail-closed + 阈值更严） |
| 日志无细节 | logger.info 仅记录 rejected 原因 | 结构化日志一行：url / status / score / sufficient / conflict / policy / elapsed_ms |

## 2. 模块拆分

### 子任务 1: 阈值配置化 + 审查策略三档
- 描述: config 新增 `crawl_review_policy` / `crawl_hhem_threshold` / `crawl_hhem_threshold_strict`；`_review_content` 改造为按策略判定（阈值取值、异常默认值）
- 预估代码量: 功能代码 ≤ 35 行
- 涉及文件:
  - `ai_service/src/config.py`（新增 3 项配置）
  - `ai_service/rag/crawl/crawler.py`（`_review_content` 改造）
- 依赖: 无

### 子任务 2: 矛盾检测接入
- 描述: 新增 `_check_conflict`：抓取内容 embed → 查根父块向量候选（pgvector 余弦 top-K，cosine ≥ 下限过滤）→ 按 `memory_conflict_judge` 选判定器（clf / nli / dual，对称回退）→ 返回 `{"conflict": bool, "detail": str}`；任一环节失败 fail-open 跳过（回退基础审查）
- 预估代码量: 功能代码 ≤ 45 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（`_check_conflict` 新增，≤50 行铁律）
  - `ai_service/src/config.py`（`crawl_conflict_top_k` / `crawl_conflict_min_cosine`）
- 依赖: 子任务 1

### 子任务 3: review_score 入库链路
- 描述: documents 新增 `review_score FLOAT NULL` 列（init_db 幂等 ALTER）；四层透传 review_score（ingest_document → add_document → Document ORM → 落库）；返回与响应携带
- 预估代码量: 功能代码 ≤ 30 行
- 涉及文件:
  - `ai_service/src/database.py`（REVIEW_SCORE_DDL + ensure_review_score_column + init_db 挂接）
  - `ai_service/rag/models.py`（review_score 列）
  - `ai_service/rag/retrieval/document_ingest.py`（参数 + 透传）
  - `ai_service/rag/engine.py`（add_document 参数 + 透传 2 处）
  - `ai_service/main.py`（run 响应补 conflict 字段）
- 依赖: 子任务 1

### 子任务 4: 日志增强 + 汇总扩展
- 描述: `_review_content` 返回结构化结果 dict；日志一行含 score / sufficient / conflict / policy / elapsed_ms；CrawlSummary 新增 `conflict_count`；summary.details 项补 review_score / conflict
- 预估代码量: 功能代码 ≤ 20 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（CrawlResult / CrawlSummary / `_crawl_page_and_store` 适配）
  - `ai_service/main.py`（POST /ai/crawl/run 响应补 `conflict`）
- 依赖: 子任务 2 + 3

### 子任务 5: 测试 + 回归
- 描述: 单元测试（阈值配置化生效、三档策略、矛盾 dual 双确认 / 单判 / 降级、review_score 四层透传、日志断言、fail-open 回退）+ conftest autouse 钉住 crawl_enabled=false（hermetic）+ 全量回归
- 预估代码量: 测试代码 ~160 行（**不含在 ≤200 行生产代码限额内**）
- 涉及文件:
  - `ai_service/tests/crawl/test_review_enhancement.py`（新建）
  - `ai_service/tests/conftest.py`（沿用现有钉住，无需新增 autouse）
- 依赖: 子任务 1-4

## 3. 技术方案

### 3.1 审查策略三档语义（核心表）

| 维度 | fail-open（默认，075 零回归） | lenient | strict |
|------|-------------------------------|---------|--------|
| 审查环节异常 | approved（放行） | approved（放行） | rejected（fail-closed，宁缺毋滥） |
| reflector 不充分 | rejected | rejected | rejected |
| HHEM 分 < 阈值 | rejected | rejected | rejected |
| 矛盾命中 | 仅记录（日志 + 统计） | rejected | rejected |
| HHEM 阈值 | crawl_hhem_threshold | crawl_hhem_threshold | crawl_hhem_threshold_strict（更严） |

- rejected 仍入库（不丢数据可复核，module-075 契约不变——review_status 语义与落库链路不改）
- 默认 fail-open：与 module-075 行为逐字一致（0.3 阈值 + 异常放行 + 无矛盾判定入决策），增强项仅附加记录，零回归

### 3.2 判定链（`_review_content` 重写，≤50 行铁律）

```
1. reflector.check_sufficiency（复用，不修改）→ 不充分 → status=rejected
2. hhem_judge.predict（复用，不修改）→ score；score < 当前策略阈值 → status=rejected
3. _check_conflict（新增）→ conflict 命中且策略 ∈ {lenient, strict} → status=rejected
4. 任一环节异常 → 按策略默认（fail-open/lenient → approved；strict → rejected）
5. 返回 {"status", "score", "sufficient", "conflict", "conflict_detail", "policy", "elapsed_ms"}
```

### 3.3 矛盾检测（`_check_conflict`，≤45 行）

- **候选获取**: `embedding_service.embed_text(新内容[:500])` → SQL
  `SELECT id, title, content FROM documents WHERE parent_id IS NULL AND embedding IS NOT NULL ORDER BY embedding <=> :vec LIMIT :k`
  （pgvector 余弦距离 `<=>`，距离 = 1 - cosine）→ cosine ≥ `crawl_conflict_min_cosine`（默认 0.6）才保留——不相干文档无矛盾语义，既浪费 NLI 推理又易误报
- **判定器**（复用 config `memory_conflict_judge`，与记忆写路径同源，默认 dual）:
  - `nli` → `nli_judge.predict(premise=候选, hypothesis=新内容)`（mDeBERTa 三分类）
  - `clf` → `memory_conflict_clf.load()` 后 `predict`（bge-m3+LR 二分类）
  - `dual` → nli + clf 双判：**双确认 contradiction 才算矛盾**（对齐 module-070 用户哲学"宁漏检也不错标"）；nli 不可用 → clf 单判 / clf 不可用 → nli 单判（对称回退，与记忆写路径一致）
- 任一候选矛盾 → `conflict=True` + detail（候选 id / 标题 / 判定器）
- 任何异常 / 模型缺失 / 返回 None / 嵌入失败 → `conflict=False`（fail-open 跳过，回退基础审查）

### 3.4 阈值配置化（config.py，动态调整）

- pydantic-settings 从 `PW_*` 环境变量 + `.env` 读取（改配置重启生效）；进程内 `settings` 属性修改即时生效（满足"可动态调整"）
- 新增 5 项:
  - `crawl_review_policy: Literal["fail-open", "lenient", "strict"] = "fail-open"`
  - `crawl_hhem_threshold: float = 0.3`（现状值，零回归）
  - `crawl_hhem_threshold_strict: float = 0.45`（strict 档更严）
  - `crawl_conflict_top_k: int = 3`（矛盾候选上限）
  - `crawl_conflict_min_cosine: float = 0.6`（候选余弦下限）
- Literal 枚举校验：非法策略值启动即抛 ValidationError（fail-fast，防静默落入错误分支——对齐 retrieval_fusion_mode 先例）

### 3.5 review_score 入库链路（对齐 module-075 review_status 四层透传模式）

- documents 新增 `review_score FLOAT NULL`（HHEM score 0-1；HHEM 不可用 → NULL，诚实不编造分数）
- DDL: `ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_score FLOAT;` + COMMENT（init_db 幂等，对齐 `ensure_review_status_column` 拆分执行模式）
- 透传: `_crawl_page_and_store` → `ingest_document(review_score=...)` → `add_document(review_score=...)` → `Document.review_score`；全部默认 None 向后兼容（存量调用零回归）
- 矛盾详情不入库（日志 + summary + run 响应承载，省 4 层改造；确需入库复核时后续加 review_meta JSONB 列）

### 3.6 日志与汇总

- `logger.info("审查完成: url=%s status=%s score=%s sufficient=%s conflict=%s policy=%s elapsed_ms=%d")` 一行
- CrawlSummary 新增 `conflict_count: int = 0`（检测到矛盾的文档数，与是否 rejected 独立计数）
- summary.details 项补 `review_score` / `conflict`
- POST /ai/crawl/run 响应 data 补 `conflict` 字段

### 3.7 生产代码行数预算（铁律 2 ≤ 200 行，AST 口径对齐 module-076 先例）

| 改动点 | 预估行数 |
|--------|---------|
| config.py（5 项配置 + 注释） | ~14 |
| crawler.py `_review_content` 重写 | ~45 |
| crawler.py `_check_conflict` 新增 | ~40 |
| crawler.py CrawlResult / CrawlSummary / `_crawl_page_and_store` 适配 | ~18 |
| database.py（REVIEW_SCORE_DDL + ensure + init_db 挂接） | ~12 |
| models.py（review_score 列） | ~5 |
| document_ingest.py（参数 + 透传） | ~7 |
| engine.py add_document（参数 + 透传 2 处） | ~8 |
| main.py（run 响应补 conflict） | ~4 |
| **合计** | **~153** |

## 4. 验收标准

见同目录下 `acceptance-criteria.md`

## 5. 风险评估

- **风险 1: 矛盾检测耗时**（1 次 embed + ≤3 次 NLI，单对 CPU 秒级）
  - 应对: 单页审查预算 +5s 内，30s 页超时与 10 页批次上限不变；embedding 与 NLI 均延迟加载、异常即跳过（fail-open）
- **风险 2: 向量候选查询性能**（无索引时全表余弦扫描，万级文档 ~百 ms）
  - 应对: 每文档仅 1 次查询可接受；LIMIT 3 + cosine 下限过滤 + `WHERE embedding IS NOT NULL`
- **风险 3: strict 档异常拒绝误杀**（网络抖动 / 模型加载失败 → 批量 rejected）
  - 应对: 默认 fail-open（零回归），strict 需用户显式 `PW_CRAWL_REVIEW_POLICY=strict` 切换
- **风险 4: review_score 列迁移**
  - 应对: init_db 幂等 ALTER（对齐 review_status 先例），存量行 NULL 兼容
- **风险 5: dual 双确认过保守漏标矛盾**
  - 应对: 对齐用户哲学（宁漏检也不错标）；单判模式可由 `PW_MEMORY_CONFLICT_JUDGE=clf|nli` 切换
- **风险 6: conftest autouse 钉 nli（default_memory_conflict_disabled）与 dual 测试冲突**
  - 应对: 测试体内显式 mock 判定器 + finally 还原 settings（对齐 module-070 测试模式）

## 6. 遗留决策清单（默认值已定，任务完成后统一汇报由用户决策）

| # | 决策点 | 本模块默认值 | 理由 |
|---|--------|-------------|------|
| 1 | 默认审查策略 | **fail-open** | 与 module-075 行为零回归；lenient/strict 由 PW_CRAWL_REVIEW_POLICY 显式切换 |
| 2 | strict 档 HHEM 阈值 | 0.45 | 更严但不过分（0.3 为宽松基线），可调 |
| 3 | 矛盾候选 top-K / 余弦下限 | 3 / 0.6 | 不相干文档无矛盾语义，下限过滤防误报；可调 |
| 4 | 矛盾判定模式 | 复用 memory_conflict_judge=dual（双确认） | 与记忆写路径同源一致；宁漏检也不错标 |
| 5 | HHEM 不可用时 review_score | NULL | 诚实记录，不编造分数 |
| 6 | 矛盾详情入库 | 不入库（日志 + summary + 响应） | 省 4 层改造；确需可复核再加 review_meta JSONB 列 |

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始版本 | Planner |

## 8. 复用既有逻辑清单

| 复用项 | 来源 | 说明 |
|--------|------|------|
| `reflector.check_sufficiency` | agent/reflector.py | 充分性检查，不修改 |
| `hhem_judge.predict` | rag/retrieval/factcheck_judge.py | HHEM 质量打分，不修改（阈值改读 config） |
| `nli_judge.predict` | rag/memory/nli_judge.py | mDeBERTa 三分类矛盾判定，不修改 |
| `memory_conflict_clf.predict/load` | rag/memory/memory_conflict_clf.py | bge-m3+LR 二分类矛盾判定，不修改 |
| `settings.memory_conflict_judge` | src/config.py | 判定器选型（clf/nli/dual，module-070 已配） |
| `embedding_service.embed_text` | rag/retrieval/embeddings.py | 矛盾候选向量化 |
| `fetch_page` / `_crawl_page_and_store` | rag/crawl/crawler.py | 抓取与入库链路，仅审查段适配 |
| `ingest_document(..., review_status)` | rag/retrieval/document_ingest.py | 入库管线，扩展 review_score 透传 |
| `add_document(..., review_status)` | rag/engine.py | 落库，扩展 review_score 透传 |
| `ensure_*_column` 幂等 ALTER 模式 | src/database.py | REVIEW_SCORE_DDL 同款 |
| conftest autouse 钉住 crawl_enabled=false | tests/conftest.py | hermetic 测试 |

## 9. 不在本模块范围

- 人工复核 UI（module-075 plan §8 提及；本模块仅落标记与日志，UI 留后续/独立模块）
- 反爬绕过 / 代理池 / robots 礼仪（module-077）
- 增量 append 不重建验证（module-079）
- 反向闭环（低分题→待学笔记→自动抓取，module-080）
- memory_conflict_judge 判定器本身改造（module-070 已定稿，本模块只复用）
