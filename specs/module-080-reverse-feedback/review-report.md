# 审查报告 — Module-080 反向闭环（低分题 → 待学笔记 → 自动任务优先抓取）

- 审查人: Reviewer（module-080-reverse-feedback）
- 审查日期: 2026-08-26
- 审查对象: specs/module-080-reverse-feedback/（plan.md / acceptance-criteria.md / changelog.md 全文 + RAG 侧 6 文件全文 + Java 侧 4 文件全文 + 支撑文件）
- 审查结论: **通过（条件通过，P2/P3 见 §5，不阻塞验收）**

---

## 1. 验证执行结果（实测，非转述 changelog）

| 验证项 | 命令 | 结果 |
|---|---|---|
| RAG 单测（本模块 + 相关） | `cd ai_service && .venv\Scripts\python -m pytest tests/ -v -k "feedback or priority or weak"` | **60 passed / 0 failed**（38.8s；含本模块 test_feedback_scanner 21 项 + test_priority_crawl 10 项 + 并行会话 test_crawl_priority 7 项 / weak_topics 16 项 + 存量 feedback API 6 项，60 项全绿） |
| Java 编译（增量） | `cd admin && mvn -DforkCount=0 test-compile` | BUILD SUCCESS（但显示 "Nothing to compile"，增量缓存） |
| Java 编译（强制全量重编） | `mvn -DforkCount=0 clean test-compile` | **BUILD SUCCESS**（317 主源 + 40 测试源全量重编；仅既有文件 deprecation/unchecked 警告，无本模块文件警告） |
| py_compile | 实际 6 文件 | `feedback_scanner.py / priority_crawl.py / crawler.py / database.py / config.py / main.py` 全部通过 |
| 行数（Java，独立实测） | Get-Content 计数 | Controller 65 + DTO 31 + Service 21 + Impl 78 = **195 ≤ 200 ✓** |
| 行数（RAG，独立实测） | AST 语句行计数 | 新文件 feedback_scanner 78 + priority_crawl 38 = 116；加 config/database/crawler/main 四处增量 ≈ 190（AST 口径）≤ 200 ✓（全行口径 259，见 §5-P3-1） |

> 注：验收命令 `py_compile ... rag/feedback/low_score_feedback.py` 中的路径为 plan 旧文件名，实现按任务 brief 落在 `rag/crawl/feedback_scanner.py`（changelog §2.3 已登记偏差）——已用实际文件验证通过。

---

## 2. 审查要点逐项核验

### 2.1 跨系统集成（RAG→Java：httpx GET + 内部 token + fail-open）✅

- 路径契约一致：RAG `_WEAK_POINTS_PATH = "/api/xunzhi/v1/interview/weak-points"`（feedback_scanner.py:15）↔ Java `@RequestMapping("/api/xunzhi/v1/interview") + @GetMapping("/weak-points")`（WeakPointController.java）↔ SaToken `.notMatch("/api/xunzhi/v1/interview/weak-points")` 三者精确一致。
- 参数一致：RAG 传 `threshold=settings.feedback_low_score_threshold(60), days=7, limit=50` ↔ Java `@RequestParam` 默认 60/7/50，threshold 走配置可联动。
- token 头：`feedback_internal_token` 非空才带 `X-Internal-Token`（feedback_scanner.py:30-32）；空 → 不带头 → Java 403 → RAG fail-open `[]`（联调摩擦为遗留决策 4）。
- fail-open 全链路：连接失败/超时/非 200/JSON 异常/data 非列表/非 dict 项 → `[]` 或剔除（feedback_scanner.py:36-49，单测 6 项覆盖）。
- Java 聚合先例确证：`InterviewSessionRuntimeSnapshotService.loadPersistedTurns(String)`（:153，签名匹配 `record.getSessionId()` String 类型）与 `InterviewRecordServiceImpl.java:312` 完全同源；`InterviewRecordDO` 字段（sessionId/endTime/interviewStatus/delFlag）与 Impl 查询条件匹配；`interview_status ∈ {FINISHED, EVALUATED}` + `del_flag=0` + endTime 窗口与 plan §3 一致。

### 2.2 安全（Java 内部 token：常量时间比较、fail-closed）✅

- `MessageDigest.isEqual(内部token字节, 请求token字节)` 常量时间比较（WeakPointController.java:60-64）✓
- fail-closed：token 未配置（`@Value("${xunzhi-agent.security.internal-token:}")` 空串）/ 请求缺失 / 不匹配 → 一律 403（WeakPointController.java:48-56）✓
- 无硬编码：`application.yaml:93` `internal-token: ${XUNZHI_INTERNAL_TOKEN:}` 环境变量注入（铁律 9）✓
- 种子 URL 协议：`build_seed_url` 输出经 `_recursive_crawl → fetch_page → _is_safe_url` 双保险（仅 http/https，不安全的模板返回 error 而非崩溃）✓
- 日志：无 token 打印；优先级主题日志截断 `topic[:40]`、URL `[:80]`；扫描仅记汇总 ✓

### 2.3 待学笔记（memory_service.save 调用）✅

- 签名核验：`memory_service.save(content, identity='learning', dedup=True, memory_type='fact')`（memory.py:309-330 签名兼容，memory_type 为 module-062 已有参数）——feedback_scanner.py:112-113 调用正确 ✓
- source 格式：`_memory_source('learning')` = `memory:learning:`（尾冒号精确格式，memory.py:176-193）✓
- 隔离：retriever.py:854 `AND (source IS NULL OR source NOT LIKE 'memory:%')` 确证——待学笔记不进入知识库检索，零回归 ✓
- 语义去重：同 identity('learning')+layer('') 余弦 > `memory_dedup_threshold(0.85)` 命中 → 更新旧父块（重复扫描不堆积）✓
- 主题取自题目文本：`extract_topic` 确定性取 questionContent 前 30 字符（空白折叠、缺省 "未知主题"），笔记首行 `【待学笔记】<topic>` ✓（不调 LLM，符合 plan 省钱约束）

### 2.4 优先级抓取（drain_priority_seeds）✅

- 流程正确：`_load_pending_topics`（status='pending' ORDER BY id LIMIT max_per_run）→ `build_seed_url`（模板 `.format(query=quote(topic))`）→ `_recursive_crawl(seed, 0, feedback_priority_crawl_depth, whitelist=None, ...)` → 无论成败 `_mark_priority(id, 'processed')`（防死循环重试）✓
- 优先级先于常规源：`_scheduled_crawl_job` 开头函数级延迟导入 `drain_priority_seeds()` 并前置执行（crawler.py，防循环依赖，对齐既有 document_ingest 延迟导入先例）；测试 `test_scheduled_job_drains_before_sources` 断言顺序 drain→load ✓
- crawl_enabled=false → drain 直接跳过（与 run_crawl 同款总闸），验收 1.3「手动 scan 只写笔记+入队不抓取」满足 ✓
- 失败仍 processed：抓取异常 → errors+1 + 日志，队列照常流转（单测 test_crawl_failure_still_processed）✓

### 2.5 去重 ✅

- 同 topic pending 去重：`enqueue_priority` 先 `SELECT 1 FROM crawl_priority WHERE status='pending' AND topic=:t LIMIT 1`，命中 → 不 INSERT 返回 False（feedback_scanner.py:77-84；单测 test_skips_when_pending_dup / test_dedup_enqueued_skip 断言 enqueued 不计）✓
- 笔记层去重：memory 语义去重（§2.3）双保险 ✓
- 注：SELECT-then-INSERT 非原子 + 表无 (status,topic) 唯一约束，并发双触发理论可双入队（见 §5-P3-3，低风险）

### 2.6 配置向后兼容 ✅

- 10 项 `feedback_*` 配置全部带默认值（config.py）：`feedback_reverse_enabled=True / feedback_java_base_url=http://localhost:8002 / feedback_low_score_threshold=60 / feedback_scan_interval_minutes=1440 / feedback_http_timeout_s=10 / feedback_learning_identity=learning / feedback_search_url_template=Bing / feedback_priority_crawl_depth=1 / feedback_priority_max_per_run=5 / feedback_internal_token=""`——无必填项，存量部署零配置启动 ✓
- 环境变量覆盖：`model_config = {"env_prefix": "PW_", ...}` → `PW_FEEDBACK_*` 全量可覆盖 ✓

### 2.7 DDL 幂等 ✅

- `PRIORITY_QUEUE_DDL`：`CREATE TABLE IF NOT EXISTS crawl_priority`（8 列与 plan §5.1 逐列对齐：topic VARCHAR(200) NOT NULL / note TEXT / session_id VARCHAR(64) / question VARCHAR(500) / score INTEGER / status VARCHAR(16) DEFAULT 'pending' / created_at / processed_at）+ `CREATE INDEX IF NOT EXISTS idx_crawl_priority_status`（database.py）✓
- asyncpg 多语句拆分执行 + `init_db` 挂接 `ensure_priority_queue_table()`（database.py，与 feedback/request_logs 同款自愈建表模式）✓
- 常量名 `PRIORITY_QUEUE_DDL` 规避并行会话已占用的 `CRAWL_PRIORITY_DDL`（source_configs.priority 列）——同文件共存无冲突 ✓

### 2.8 行数（铁律 2）✅（AST 口径，见 §5-P3-1）

- Java 独立实测 195 ≤ 200 ✓
- RAG 新文件全行 194；AST 可执行口径 ≈190 ≤ 200 ✓（module-075 先例口径）

### 2.9 docstring / 无空 catch / 方法长度 ✅

- 新公开方法（fetch_low_score_questions / extract_topic / build_learning_note / enqueue_priority / scan_and_generate / setup_feedback_scheduler / _load_pending_topics / _mark_priority / build_seed_url / drain_priority_seeds / Java 三件套）全部有 docstring（铁律 4）✓
- 无空 catch：RAG 侧全部 `except` 至少 `logger.warning/error`（铁律 5）；crawler 既有 `_check_robots_allowed` 的 bare except 为 module-077 存量代码非本模块改动 ✓
- 方法 ≤ 50 行：scan_and_generate ~27 行、drain_priority_seeds ~25 行、Java listWeakPoints ~25 行 ✓
- crawler.py 最小侵入：仅 `_recursive_crawl` whitelist=None 支持（docstring 同步更新）+ `_scheduled_crawl_job` 前置 drain（+7 行），既有 crawl 测试 0 回归（本次 60 项中 crawl 相关全部绿）✓

---

## 3. 与 changelog 声明的一致性核验

| changelog 声明 | 核验结果 |
|---|---|
| feedback_scanner 126 行 / priority_crawl 68 行 | ✓ 实测一致 |
| Java 生产 197 行 ≤ 200 | ✓ 实测 195（含配置 2 行口径 197，一致） |
| 31 项新单测 | ✓ test_feedback_scanner 21 + test_priority_crawl 10 |
| 全 mock 不触网不触库 | ✓ 实测（httpx/async_session_factory/memory_service.save/_recursive_crawl 全部 patch） |
| SaToken +1 行 notMatch | ✓ SaTokenAuthInterceptorConfig 确证 |
| application.yaml +1 行 internal-token | ✓ :93 确证（环境变量注入） |
| loadPersistedTurns 复用先例 | ✓ :312 确证 |

---

## 4. 验收标准对照

| 验收项 | 状态 | 依据 |
|---|---|---|
| 1.1 核心链路（扫描/笔记落库/入队/优先抓取/队列消费/低分过滤） | ✅ | 21+10 单测全绿；`_scheduled_crawl_job` 集成测试断言 drain 前置；pending→processed 流转有测试覆盖 |
| 1.2 边界（空列表/重复不堆积/单轮上限/特殊字符编码/黑名单与 robots） | ✅ | 空跑零汇总、同 topic pending 去重、max_per_run LIMIT、quote 编码断言、黑名单/robots 复用 `_recursive_crawl` 既有链路 |
| 1.3 异常（Java 不可达/JSON 异常/单条失败/抓取失败/开关关/手动不抓取） | ✅ | 全部 fail-open 有测试；crawl_enabled=false 时 drain 跳过；scan 端点不触发抓取 |
| 2.1 性能（单轮 ≤10s / 单轮消费上限） | ✅ | 拉取超时上限 10s 配置；消费 ≤ max_per_run（Java 侧 limit=50 封顶） |
| 2.2 安全（token fail-closed / URL 协议 / 日志无敏感） | ✅ | MessageDigest.isEqual + 403 fail-closed；_is_safe_url 复用；日志截断 |
| 2.3 代码质量（≤200 行 / docstring / ≤50 行 / 无空 catch / 无硬编码 / crawl 零回归） | ⚠️→✅ | 行数见 §5-P3-1（AST 口径 190 ≤ 200）；其余全部满足；crawl 测试 0 回归 |

---

## 5. 问题清单

### P1（阻塞）：无

### P2（建议修复，不阻塞）

1. **WeakPointServiceImpl「单轮异常 fail-open」声明与实现不符**：类 docstring 与 changelog §3 声明"单轮异常 fail-open"，但 `listWeakPoints` 的 session 循环（`loadFinishedRecords → loadPersistedTurns`）**没有任何 try/catch**——若单个 session 的 Redis/Mongo 聚合读硬失败，整个端点 500。缓解因素：① 底层 `loadPersistedTurns` 内部多处 try/catch 且空 sessionId/空数据均返回空列表（较防御）；② RAG 侧把非 200 视为 fail-open `[]`，端到端影响被吸收。建议在 per-session 聚合处包 try/catch（失败跳过 + 日志 + 继续），兑现文档承诺，顺带避免单条脏数据毁掉整轮扫描。

### P3（记录/演进，均不阻塞）

1. **RAG 侧行数口径**：全行口径 259 > 200；AST 可执行口径 ≈190 ≤ 200。验收 2.3 字面命令 `git diff --numstat` 在本工作树**不可执行**（module-075~079 + 并行会话大批未提交改动，无法隔离本模块）——按 module-075 确立的 AST 口径放行（changelog §5.4 已如实声明，Reviewer 独立实测新文件 AST 语句行 78+38=116 + 增量 ≈190，与声明一致）。若后续要求全行口径 ≤200，可砍 `extract_topic`/`build_learning_note` 合并（-6）与去重 SELECT 改应用层（-4），但牺牲可测性，不建议。
2. **「标题/主题取自题目文本」的落地口径**：验收 1.1 要求笔记"标题/主题取自题目文本"——实现中主题（`【待学笔记】<topic>`，题目前 30 字符）位于**笔记内容首行**；而 `documents.title` 为记忆层共享格式 `记忆-YYYY-MM-DD-NN`（memory.py `_next_title`，全记忆写路径统一行为，无法在 memory_service.save 调用点定制）。若严格要求 title 字段取自题目，需扩展 memory_service 标题参数或落库后回写，属 P3 演进；建议在验收标准备注中登记此口径。
3. **入队去重非原子**：`enqueue_priority` 为 SELECT-then-INSERT，无 (status, topic) 唯一约束——手动 `POST /ai/feedback/scan` 与定时 job 并发触发时理论可同 topic 双入队（实际单 APScheduler job + 手动低频，风险极低）。加固：加 `UNIQUE INDEX ON crawl_priority(status, topic) WHERE status='pending'` 部分唯一索引（PG 支持）。
4. **enqueue DB 失败不计 errors**：`enqueue_priority` DB 异常返回 False 仅记日志，scan 汇总 `errors` 不 +1（验收 1.3 只要求 memory save 失败计 errors，故满足；语义上可把"入队失败"也计入 errors，可选改进）。
5. **RAG 侧 days=7 / limit=50 硬编码**：仅 threshold 走配置（feedback_scanner.py:28）；Java 端点三者皆可配。如需 RAG 侧调窗口/条数，后续可加配置（P3）。
6. **`POST /ai/feedback/scan` 无鉴权**：与既有 `POST /ai/crawl/run` 一致（服务内无强制鉴权），若对外暴露需网关/网络层保护（P3，现状非回归）。
7. **验收命令路径漂移**：acceptance-criteria.md §3 的 py_compile 命令含 `rag/feedback/low_score_feedback.py`（plan 旧文件名），实现为 `rag/crawl/feedback_scanner.py`——建议同步修订验收文件，避免后续 Tester 误判。

---

## 6. 备注（审查上下文）

- **DECISION.md（编排者合并决策，2026-08-26）**：本方案（Java InterviewTurnLog 评分 + crawl_priority 表 + Bing 种子）被**归档为增强方向**，主实现为 specs/module-080-reverse-loop/（feedback 表驱动）。本审查结论为"实现正确、可安全落地"——两方案产物已在同一工作树共存且互不依赖，本模块实现独立可运行（60 项相关测试全绿 + 全量重编通过）；是否按 DECISION.md 归档、何时将本方案作为更真实数据源接入，由调度员决策。
- 并行会话测试文件 `tests/crawl/test_crawl_priority.py`（TestPrioritizeSources/TestRunCrawlWithPriority）与 `tests/memory/test_weak_topics.py` 本次一并全绿（与 test_priority_crawl.py 无命名冲突）。
- 遗留观察：并行会话的 weak_topics 测试存在 `RuntimeWarning: coroutine ... never awaited`（其测试自身 mock 问题，非本模块代码），建议调度员知会对应会话。

---

## 7. 结论

- **审查结论: ✅ 通过（条件通过）**
- P1 阻塞项：0；P2 建议项：1（Java 单轮异常隔离声明与实现不符，端到端影响已被 RAG fail-open 吸收，不阻塞）；P3 记录项：7。
- 建议：P2-1 在后续迭代修复；P3-2（标题口径）与 P3-7（验收命令路径）在验收标准备注中登记同步修订。
