# 变更记录 — Module-078: 审查节点增强（质量评分阈值校准 + 矛盾检测 + 审查策略强化）

## 1. 变更概述

- 功能：增强 module-075 的审查节点 `_review_content` —— ① factcheck_judge 阈值硬编码配置化 ② 接入矛盾检测（复用 `nli_judge` / `memory_conflict_clf`，dual 双确认）③ `review_score` 入库链路（四层透传）④ 审查策略三档（fail-open / lenient / strict）⑤ 结构化审查日志
- 范围：仅增强审查节点，未动抓取/递归/入库主链路结构；module-075/076 契约零回归
- 开发者：Developer（module-078）
- 日期：2026-08-26

## 2. 实现要点

### 2.1 阈值配置化（src/config.py，新增 5 项，PW_* 环境变量可覆盖）
- `crawl_review_policy: Literal["fail-open", "lenient", "strict"] = "fail-open"` —— 非法策略值启动即抛 ValidationError（fail-fast，对齐 `retrieval_fusion_mode` 先例，实测 `PW_CRAWL_REVIEW_POLICY=bogus` 启动报错）
- `crawl_hhem_threshold: float = 0.3` —— 与 module-075 硬编码值逐字一致（零回归）
- `crawl_hhem_threshold_strict: float = 0.45` —— strict 档更严阈值
- `crawl_conflict_top_k: int = 3` / `crawl_conflict_min_cosine: float = 0.6` —— 矛盾候选查询参数
- 进程内 `settings` 属性修改即时生效（实测阈值 0.3→0.5 后 score=0.4 由 approved 变 rejected）

### 2.2 审查策略三档（`_review_content` 重写，49 物理行 ≤50 铁律 3）
- 判定链：充分性（reflector）→ HHEM 质量分（阈值读 config）→ 矛盾检测（`_check_conflict`）→ 按策略定 status
- **fail-open（默认）**：审查异常 → approved；矛盾命中仅记录（日志 + conflict_count），不改变 status —— 与 module-075 行为逐字一致（零回归）
- **lenient**：矛盾命中 → rejected；审查异常仍 approved（放行）
- **strict**：矛盾命中 → rejected；审查异常 → rejected（fail-closed，宁缺毋滥）；阈值用 `crawl_hhem_threshold_strict`
- rejected 仍入库（module-075 契约不变：review_status 语义与落库链路未改）

### 2.3 矛盾检测（`_check_conflict` 新增，32 物理行 ≤50）
- 候选获取：`embedding_service.embed_text(内容[:500])` → SQL 向量查询根父块（`parent_id IS NULL AND embedding IS NOT NULL`，pgvector `<=>` 余弦距离 → cosine，embedding 字符串绑定对齐 `retriever._vector_search` 先例规避 asyncpg 类型编解码）→ cosine ≥ `crawl_conflict_min_cosine` 过滤 → top-K = `crawl_conflict_top_k`
- 判定器复用 `settings.memory_conflict_judge`（与记忆写路径同源，未重写）：
  - `nli` → `nli_judge.predict`（mDeBERTa 三分类，contradiction 才算矛盾）
  - `clf` → `memory_conflict_clf.load()` 后 `predict`（bge-m3+LR 二分类）
  - `dual`（默认）→ nli + clf 双确认 contradiction 才判矛盾（宁漏检也不错标）；任一不可用 → 另一单判（对称回退）；双不可用 → 跳过
- fail-open：任一环节失败（未启用 / 嵌入失败 / 模型缺失 / 返回 None / 推理异常）→ `{"conflict": False, "detail": ""}`，不阻断入库主链路
- **设计决策（plan 未列，本模块补充）**：矛盾检测受 `memory_conflict_enabled` 主开关门控 —— ① 对齐记忆冲突机制主开关语义（crawler 矛盾检测是判定器的新消费方）② conftest autouse 钉住 false 使 module-075/076 存量测试保持 hermetic（不触发真实 embed/DB/NLI），新测试体内显式开启验证

### 2.4 review_score 入库链路（四层透传，对齐 module-075 review_status 模式）
- documents 表新增 `review_score FLOAT NULL` 列（`REVIEW_SCORE_DDL` + `ensure_review_score_column` + init_db 幂等 ALTER，存量行 NULL 兼容，无迁移脚本）
- 透传：`_crawl_page_and_store` → `ingest_document(review_score=...)` → `add_document(review_score=...)` → `Document.review_score`（父块+子块同写）
- HHEM 不可用 → score=None → review_score=NULL（诚实不编造分数）
- 全部默认 None 向后兼容（存量调用零回归）
- 矛盾详情不入库（日志 + summary + run 响应承载，省 4 层改造；确需复核后续加 review_meta JSONB 列）

### 2.5 返回契约桥接（`ReviewResult(str)` 子类）
- module-075 契约：`_review_content` 返回 str、与 `"approved"` 直接比较（存量测试断言 `result == "approved"`）
- module-078 需求：入库/汇总需要 score/conflict 等结构化字段
- 桥接：`ReviewResult` 继承 str（值 == "approved"/"rejected"），额外携带 status / score / sufficient / conflict / conflict_detail / policy / elapsed_ms —— 既有字符串比较零回归，新消费方取字段
- `_crawl_page_and_store` 对 mock 返回的普通字符串兼容（getattr 兜底，测试内 mock `_review_content` 返回 "approved" 仍工作）

### 2.6 日志与汇总
- `_review_content` 每次审查一行结构化日志：`审查完成: url=... status=... score=... sufficient=... conflict=... policy=... elapsed_ms=...`
- 矛盾命中另记一行：`矛盾命中: 与库中文档 id=... 标题=... 矛盾（判定器=...）`（含候选 id / 标题 / 判定器）
- `CrawlSummary` 新增 `conflict_count`（与 approved/rejected 独立计数）
- summary.details 项新增 `review_score` / `conflict`
- POST /ai/crawl/run 响应 data 新增 `conflict` 计数

## 3. 复用清单（零重写）
| 复用项 | 来源 | 说明 |
|--------|------|------|
| reflector.check_sufficiency | agent/reflector.py | 充分性检查，未修改 |
| hhem_judge.predict | rag/retrieval/factcheck_judge.py | HHEM 质量打分，未修改（阈值改读 config） |
| nli_judge.predict | rag/memory/nli_judge.py | mDeBERTa 三分类矛盾判定，未修改 |
| memory_conflict_clf.load/predict | rag/memory/memory_conflict_clf.py | bge-m3+LR 二分类矛盾判定，未修改 |
| embedding_service.embed_text | rag/retrieval/embeddings.py | 矛盾候选向量化，未修改 |
| settings.memory_conflict_judge | src/config.py | 判定器选型（clf/nli/dual，module-070 已配） |
| ensure_*_column 幂等 ALTER 模式 | src/database.py | REVIEW_SCORE_DDL 同款 |
| conftest autouse 钉住 crawl_enabled=false | tests/conftest.py | hermetic 测试（沿用，未新增） |

## 4. 代码质量指标
- 本模块新增生产代码 AST 口径 ≈112 语句 ≤ 200（铁律 2，对齐 module-076 AST 口径先例）
- 单方法物理行数：`_review_content` 49 / `_check_conflict` 32 / `_conflict_candidates` 30 / `_judge_conflict` 25 / `_crawl_page_and_store` 42，均 ≤ 50（铁律 3）
- 所有新公开方法有 docstring（铁律 4）；无空 catch（铁律 5，所有 except 均记录日志）
- 新测试 28 个（tests/crawl/test_review_enhancement.py）；未修改 module-075/076 存量测试（只追加）

## 5. 测试结果

### 新增单测
```bash
pytest tests/crawl/test_review_enhancement.py -v
# 28 passed, 0 failed
```

### crawl 全量
```bash
pytest tests/crawl/ -v
# 91 passed（63 存量 + 28 新增）, 0 failed
```

### 全量回归
```bash
pytest tests/ -q
# 1338 passed, 3 skipped, 4 failed（全部为 langchain-openai proxies 基线遗留，module-028 环境性，与本模块无关）
```

### 阈值配置验证
```bash
PW_CRAWL_HHEM_THRESHOLD=0.5 python -c "from src.config import settings; print(settings.crawl_hhem_threshold)"
# 0.5 ✓（实测）
```

### 策略配置验证
```bash
PW_CRAWL_REVIEW_POLICY=strict python -c "from src.config import settings; print(settings.crawl_review_policy)"
# strict ✓（实测）
```

### 非法策略 fail-fast
```bash
PW_CRAWL_REVIEW_POLICY=bogus python -c "from src.config import settings"  # 启动报 ValidationError ✓（实测）
```

### py_compile
```bash
python -c "import py_compile; [py_compile.compile(f) for f in ['rag/crawl/crawler.py', 'src/config.py', 'src/database.py', 'rag/memory/nli_judge.py', 'rag/memory/memory_conflict_clf.py', 'rag/retrieval/factcheck_judge.py', 'rag/retrieval/embeddings.py']]"
# 无报错 ✓（实测）
```

## 6. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始实现（阈值配置化 + 策略三档 + 矛盾检测 + review_score 四层透传 + 结构化日志 + 28 单测） | Developer |

## 7. 遗留决策清单（默认值已定，待用户确认；一般问题统一汇报由用户决策）

| # | 决策点 | 本模块默认值 | 理由 |
|---|--------|-------------|------|
| 1 | 默认审查策略 | fail-open | 与 module-075 行为零回归；lenient/strict 由 PW_CRAWL_REVIEW_POLICY 显式切换 |
| 2 | strict 档 HHEM 阈值 | 0.45 | 更严但不过分（0.3 为宽松基线），可调 |
| 3 | 矛盾候选 top-K / 余弦下限 | 3 / 0.6 | 不相干文档无矛盾语义，下限过滤防误报；可调 |
| 4 | 矛盾判定模式 | 复用 memory_conflict_judge=dual（双确认） | 与记忆写路径同源一致；宁漏检也不错标 |
| 5 | HHEM 不可用时 review_score | NULL | 诚实记录，不编造分数 |
| 6 | 矛盾详情入库 | 不入库（日志 + summary + 响应） | 省 4 层改造；确需可复核再加 review_meta JSONB 列 |
| 7 | 矛盾检测门控 | 受 memory_conflict_enabled 主开关控制 | 对齐记忆冲突机制主开关语义 + 存量测试 hermetic（本模块补充决策） |

## 8. 注意事项 / 遗留
- 全量回归预期仅 langchain-openai `proxies` 4 个基线遗留失败（module-028 环境性，非本模块）
- 并行会话 module-077（反爬/代理池）生产改动已在工作树中（fetch_page 重试/代理/UA 轮换 + config 6 项），本模块未触碰 fetch_page，两者共存兼容
- crawler.py 行数口径：本模块新增按 AST 口径计（对齐 module-076 先例，实测 ~112 语句）
- 矛盾检测耗时预算：单页 1 次 embed + ≤3 次判定（top-K=3），CPU 热态秒级，未超 AC 2.1 的 10s 预算（异常即跳过 fail-open）
- `_crawl_page_and_store` docstring 为控制方法行数做了精简（3 行），语义保留
