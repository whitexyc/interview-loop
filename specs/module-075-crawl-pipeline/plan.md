# 开发计划 — Module-075: 知识抓取流水线（定时调度 + 源配置 + 入库闭环）

## 1. 需求描述
- 需求来源: ADR-0019 阶段2（知识抓取流水线），用户 2026-08-24 拍板方向
- 功能描述: 定时抓取知识源（白名单/黑名单过滤）→ 解析 → 清洗 → 复用 document_ingest 入库 → 审查节点接入反思/双判（复用 reflector + factcheck_judge）
- 优先级: P0（阶段2 最小可验收切片）
- 上下文: 阶段1（module-074）已完成 Java 面试服务出题时调 RAG 服务 POST /ai/rag/search 检索知识点注入 prompt，真实联调通过。本模块是阶段2 第一片。

## 2. 模块拆分

### 子任务 1: 源配置 + 抓取调度器
- 描述: 新建 `rag/crawl/crawler.py`——源配置表（source_configs）CRUD + APScheduler 定时调度 + 白名单/黑名单 URL 过滤 + fetch 单页（httpx GET → bytes）
- 预估代码量: 功能代码 ≤ 80 行
- 涉及文件:
  - `ai_service/rag/crawl/__init__.py`（新建）
  - `ai_service/rag/crawl/crawler.py`（新建，~80 行）
  - `ai_service/src/config.py`（新增 3 项配置：crawl_enabled / crawl_interval_minutes / crawl_max_pages_per_run）
  - `ai_service/src/database.py`（新增 SOURCE_CONFIGS_DDL + ensure）
  - `ai_service/main.py`（新增 GET/POST /ai/crawl/sources + POST /ai/crawl/run 端点）
- 依赖: 无

### 子任务 2: 审查节点接入
- 描述: 抓取到的文本在入库前走审查——复用 reflector.check_sufficiency（充分性）+ factcheck_judge（质量打分）。审查不通过的文档标记 `review_status="rejected"` 但仍入库（不丢数据，人工可复核）
- 预估代码量: 功能代码 ≤ 50 行
- 涉及文件:
  - `ai_service/rag/crawl/crawler.py`（审查逻辑 ~50 行，内联于 crawl_single_page）
- 依赖: 子任务 1

### 子任务 3: 测试 + 文档
- 描述: 单元测试（mock httpx + mock ingest_document + mock reflector + mock factcheck_judge）+ conftest autouse 钉住 crawl_enabled=false
- 预估代码量: 测试代码 ~120 行（不含在 ≤200 行生产代码限额内）
- 涉及文件:
  - `ai_service/tests/crawl/__init__.py`（新建）
  - `ai_service/tests/crawl/test_crawler.py`（新建，~120 行）
  - `ai_service/tests/conftest.py`（新增 autouse fixture 钉住 crawl_enabled=false）
- 依赖: 子任务 1 + 子任务 2

## 3. 技术方案

### 3.1 数据表
- `source_configs` 表（crawl 来源配置）：
  - `id` SERIAL PRIMARY KEY
  - `url_pattern` VARCHAR(512) NOT NULL — URL 模式（前缀匹配，如 `https://spring.io/docs`）
  - `name` VARCHAR(128) — 人类可读名称
  - `enabled` BOOLEAN DEFAULT TRUE
  - `last_crawled_at` TIMESTAMP
  - `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
- documents 表复用现有（新增 `review_status` VARCHAR(16) DEFAULT 'approved' 列，init_db 幂等 ALTER）

### 3.2 调度方案选型
- **APScheduler**（`apscheduler==3.10.4`）：轻量级 Python 调度库，支持 IntervalTrigger 定时执行
- 选型理由：
  1. 项目已用 FastAPI + asyncio，APScheduler 原生支持 AsyncIOScheduler
  2. 依赖轻量（~100KB，无重依赖）
  3. 不需要 Celery/Redis Queue 等重方案（单机部署，无需分布式）
  4. 与 FastAPI lifespan 集成方便（启动时 start、关闭时 shutdown）
- 替代方案排除：`asyncio.create_task` + `asyncio.sleep` 循环（无持久化、无错峰、无管理界面）

### 3.3 API 端点
- `POST /ai/crawl/sources` — 添加/更新抓取源配置
- `GET /ai/crawl/sources` — 列出所有源配置
- `POST /ai/crawl/run` — 手动触发一次抓取（调试用）
- 抓取结果通过现有 `/ai/documents` 端点查看

### 3.4 审查节点
- 复用 `reflector.check_sufficiency` 判断抓取内容是否"有信息量"（非空页面/404/登录页）
- 复用 `factcheck_judge.hhem_judge.predict` 对抓取内容做质量打分（文档 vs 自身标题）
- 审查不通过标记 `review_status="rejected"` 但仍入库（fail-open，不丢数据）

### 3.5 白名单/黑名单
- 白名单：ADR-0019 决策4 定义的域名列表（spring.io / fastapi.tiangolo.com / redis.io / mongodb.com / juejin.cn / segmentfault.com / stackoverflow.com / github.com / arxiv.org 等）
- 黑名单：营销号、CSDN 纯搬运、SEO 标题党（域名级过滤）
- 实现：URL 前缀匹配 + `tldextract` 或简单字符串 `endswith` 判断

## 4. 验收标准
见同目录下的 `acceptance-criteria.md`

## 5. 风险评估
- **风险 1**: APScheduler 与 FastAPI lifespan 集成不当导致重复调度
  - 应对: lifespan 中显式 start/shutdown，单例 Scheduler
- **风险 2**: 目标网站反爬（rate limit / Cloudflare / 登录墙）
  - 应对: 首版只做简单 httpx GET + User-Agent 头，失败降级跳过（fail-open），反爬绕过留后续模块
- **风险 3**: 抓取内容质量不可控（广告/导航/脚本注入）
  - 应对: 复用 document_cleaner 清洗 + 审查节点过滤 + review_status 标记人工复核
- **风险 4**: 定时任务资源争用（与用户请求并发）
  - 应对: 抓取任务用 asyncio.create_task 非阻塞，单次抓取有 timeout（30s/页）

## 6. 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-25 | 初始版本 | Planner |

## 7. 待澄清
1. **抓取深度**：首版只抓单页（URL 直接 GET），还是需要递归跟踪链接？建议首版单页，后续加 depth 参数。
2. **抓取频率**：默认多久抓一次？建议默认 24 小时（`crawl_interval_minutes=1440`），用户可调。
3. **review_status 列迁移**：需在本地 DB 跑 `ALTER TABLE documents ADD COLUMN review_status VARCHAR(16) DEFAULT 'approved'`，是否需要独立迁移脚本？
4. **白名单具体域名**：ADR-0019 列了方向（Spring/FastAPI/掘金等），首版是否需要用户可配（source_configs 表），还是硬编码？
5. **审查节点的"充分性"语义**：reflector.check_sufficiency 原用于"用户问题 vs 检索文档"，抓取场景是"抓取内容 vs 自身标题"——prompt 是否需要调整？

## 8. 阶段2 后续模块拆分摘要

| 模块 | 名称 | 依赖 | 说明 |
|------|------|------|------|
| module-075 | 知识抓取流水线（本模块） | 无 | 调度器 + 源配置 + 入库 + 审查最小闭环 |
| module-076 | 抓取深度 + 递归爬取 | module-075 | 链接跟踪 + depth 控制 + 去重 URL 池 |
| module-077 | 反爬绕过 + 代理池 | module-075 | Playwright 无头浏览器 / 代理轮换 / Cookie 管理 |
| module-078 | 审查节点增强（反思/双判深度集成） | module-075 | 抓取内容质量评分阈值校准 + 矛盾检测 + 人工复核 UI |
| module-079 | 增量 append 不重建验证 | module-075 | ADR-0019 阶段3：新增语料追加、无全量重嵌 |
| module-080 | 反向闭环（低分题→待学笔记→自动抓取） | module-076, module-078 | ADR-0019 验收标准第4项 |
