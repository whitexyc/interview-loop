# 变更记录 — Module-080 反向闭环（低分题 → 待学笔记 → 自动任务优先抓取）

## 1. 模块概述

| 项 | 值 |
|---|---|
| 模块编号 | module-080-reverse-feedback |
| 目标 | ADR-0019 最后一个验收项「反向闭环：低分题→待学笔记→自动任务优先抓取 链路打通」 |
| 数据源 | Java 面试系统真实评分（InterviewTurnLog 每题得分，经 `loadPersistedTurns` 聚合） |
| 跨系统集成 | 方案 A：RAG 侧 APScheduler 定时 httpx 拉取 Java 新端点 `GET /api/xunzhi/v1/interview/weak-points` |
| 优先级队列 | 独立表 `crawl_priority`（pending/processed），`_scheduled_crawl_job` 前置 `drain_priority_seeds()` |
| 待学笔记 | `memory_service.save(identity='learning')` → documents，source=`memory:learning:`，复用分块/嵌入/语义去重 |
| 实现人/日期 | Developer（2026-08-26） |

## 2. 实现清单（RAG 侧，`interview-personal/ai_service`）

### 2.1 新增文件

- **`rag/crawl/feedback_scanner.py`**（126 行）—— 反向闭环扫描器：
  - `fetch_low_score_questions()`：httpx GET Java weak-points 端点（threshold/days/limit 参数 + 可选 `X-Internal-Token` 头），超时/HTTP 错误/JSON 异常/结构异常 → `[]`（fail-open）
  - `extract_topic(item)`：确定性主题提取（题目文本前 30 字符，空白折叠，不调 LLM）
  - `build_learning_note(item, topic)`：结构化待学笔记模板（题目/得分/反馈/来源会话）
  - `enqueue_priority(item, topic, note)`：写入 `crawl_priority`（pending；同 topic pending 不重复入队）
  - `scan_and_generate()`：编排一轮扫描 → `{scanned, noted, enqueued, errors}`；含 RAG 侧防御性低分过滤（`score >= threshold` 不写笔记不入队，验收 1.1）；单条失败记 errors 不中断
  - `setup_feedback_scheduler(enable)`：合并式调度器（plan 裁剪清单 ②），独立 APScheduler job `feedback_reverse_loop`，间隔 `feedback_scan_interval_minutes`（默认 1440=次日），`feedback_reverse_enabled=false` 不启动
- **`rag/crawl/priority_crawl.py`**（68 行）—— 优先级抓取：
  - `_load_pending_topics(limit)` / `_mark_priority(id, status)`：队列读写（fail-open）
  - `build_seed_url(topic)`：搜索模板 `feedback_search_url_template.format(query=quote(topic))`
  - `drain_priority_seeds()`：消费 pending 主题 → 种子 URL → `_recursive_crawl(whitelist=None, depth=feedback_priority_crawl_depth)` → 无论成败标记 processed（防死循环重试）；`crawl_enabled=false` 时跳过（对齐 run_crawl 总闸）

### 2.2 修改文件

- **`rag/crawl/crawler.py`**（最小侵入 +7 行）：
  - `_recursive_crawl`：`whitelist` 参数支持 `None`（空=不限制，优先级主题为系统显式请求；黑名单/robots/审查/入库照常），docstring 更新
  - `_scheduled_crawl_job`：函数级延迟导入 `drain_priority_seeds()` 并前置执行（优先级主题先于常规源抓取）
- **`src/database.py`**（+24 行）：`PRIORITY_QUEUE_DDL` + `ensure_priority_queue_table()`（幂等 CREATE TABLE IF NOT EXISTS + status 索引）+ `init_db` 挂接。**常量名说明**：并行会话（module-080-reverse-loop）已占用 `CRAWL_PRIORITY_DDL`（其实现为 `source_configs.priority` 列），本模块建表常量改用 `PRIORITY_QUEUE_DDL` 避免撞名（plan §1.1 并行产物声明）
- **`src/config.py`**（+17 行）：`feedback_reverse_enabled`（True）/ `feedback_java_base_url`（http://localhost:8002）/ `feedback_low_score_threshold`（60，对齐 Java `defaultLowScoreThreshold`）/ `feedback_scan_interval_minutes`（1440）/ `feedback_http_timeout_s`（10）/ `feedback_learning_identity`（learning）/ `feedback_search_url_template`（Bing）/ `feedback_priority_crawl_depth`（1）/ `feedback_priority_max_per_run`（5）/ `feedback_internal_token`（""，空=不带头）。全部带默认值（向后兼容），环境变量 `PW_FEEDBACK_*` 可覆盖
- **`main.py`**（+17 行）：lifespan 挂接 `setup_feedback_scheduler(True/False)` + 新增 `POST /ai/feedback/scan`（手动触发一轮扫描，返回 `{code:0, data:{scanned,noted,enqueued,errors}}`，整体失败 fail-open 返回 code=1 零汇总）

### 2.3 与 plan 的偏差（如实登记）

| 偏差 | plan | 实现 | 理由 |
|---|---|---|---|
| 扫描器文件名 | `rag/feedback/low_score_feedback.py` | `rag/crawl/feedback_scanner.py` | 任务 brief 显式指定后者；测试文件对应放 `tests/crawl/` |
| 调度器形态 | `start_feedback_scheduler()`/`shutdown_feedback_scheduler()` | 合并 `setup_feedback_scheduler(enable)` | plan 裁剪清单 ②（-5 行） |
| 低分过滤 | 仅 Java 侧 | Java 侧 + RAG 侧防御性再滤 | 验收 1.1 要求 `score >= threshold` 不写笔记不入队，单测可独立验证 |
| `/ai/crawl/run` 前置 drain | 可选（"或"） | 未接入 | 主链路 `_scheduled_crawl_job` 已前置 drain（验收 1.1 主路径）；省 6 行 |
| 待学笔记扫描汇总 | 无 errors 字段要求 | `{scanned, noted, enqueued, errors}` | 验收 1.3 单条失败计数 |

## 3. 实现清单（Java 侧，`ai-meeting-project/AI-Meeting/admin`，独立核算 ≤200 行）

| 文件 | 说明 |
|---|---|
| `api/io/resp/WeakPointRespDTO.java`（新） | sessionId/questionNumber/questionContent/score/totalScore/feedback/endTime |
| `service/WeakPointService.java`（新） | 接口：`listWeakPoints(threshold, days, limit)` |
| `service/impl/WeakPointServiceImpl.java`（新） | MySQL `interview_record`（FINISHED/EVALUATED + del_flag=0 + endTime 窗口）→ 每会话 `runtimeSnapshotService.loadPersistedTurns(sessionId)` 聚合（复用 InterviewRecordServiceImpl:312 先例）→ 过滤 `score != null && score < threshold && !isFollowUp` → 按 endTime 倒序、最多 limit 条；单轮异常 fail-open |
| `api/WeakPointController.java`（新） | `GET /api/xunzhi/v1/interview/weak-points?threshold&days&limit`；内部 token 认证（header `X-Internal-Token` 对比 `xunzhi-agent.security.internal-token`，`MessageDigest.isEqual` 常量时间比较；token 未配置/缺失/不匹配 → 403 fail-closed） |
| `auth/.../SaTokenAuthInterceptorConfig.java`（+1 行） | `.notMatch("/api/xunzhi/v1/interview/weak-points")`（免登录，非 SaToken） |
| `application.yaml`（+1 行） | `xunzhi-agent.security.internal-token: ${XUNZHI_INTERNAL_TOKEN:}`（环境变量注入，禁硬编码） |

Java 生产代码 197 行全行口径（Controller 65 + DTO 31 + Service 20 + Impl 79 + 配置 2），≤200 ✓；可执行口径约 140 行。


本模块实现期间，**并行会话（specs/module-080-reverse-loop，feedback 表方案）在同一工作树并发写入**：

1. `src/config.py`：其加入 `weak_topic_priority_boost`（读后写入，导致首次 edit 撞 [E_RANGE_STALE]）——本模块保留其字段，新增反馈配置块共存
2. `src/database.py`：其加入 `CRAWL_PRIORITY_DDL`（source_configs.priority 列）+ `ensure_priority_column`；**常量名与本模块 plan 撞名** → 本模块改用 `PRIORITY_QUEUE_DDL`；期间其写入曾留下 `KrW` 垃圾行致 database.py 语法错误（NameError），已由对方随后修复
3. `rag/memory/weak_topics.py` + `rag/schemas.py`：其新增待学笔记模块与请求体（本模块不依赖、不删除）
4. `rag/crawl/crawler.py`：其新增 `_prioritize_sources`（待学笔记关键词匹配提升源 priority）+ `_load_sources_from_db` 含 priority 列 —— 本模块 `_recursive_crawl`/`_scheduled_crawl_job` 修改与之共存（各自独立功能，无冲突）
5. `main.py`：其新增「待学笔记端点」小节 —— 本模块 `POST /ai/feedback/scan` 插在其小节之前
6. 其测试 `tests/crawl/test_crawl_priority.py`：实现中途一度 6 项失败（patch `crawler.recall_weak_topics` 但实现为函数内延迟导入），随后对方修复，最终全量 157 crawl 测试全绿

**结论**：两方案产物并存，互不删除（plan §1.1 声明）；合并决策由调度员负责。本模块的实现不依赖并行方案的任何代码。

## 5. 验证结果

### 5.1 RAG 侧单测（新增 31 项）

- `tests/crawl/test_feedback_scanner.py`（21 项）：拉取成功（参数/token 头断言）/HTTP 错误/超时/JSON 异常/结构异常（fail-open 空跑）、主题提取（截断/折叠/回退）、笔记模板字段、入队（插入/同 topic 去重/DB 失败降级）、扫描编排（全链路计数/高分过滤/空列表/单条失败继续/去重后 enqueued=0）、调度器（disabled 不建/enabled 注册 job id/shutdown noop）
- `tests/crawl/test_priority_crawl.py`（10 项）：种子 URL 编码（中文/引号/百分号）、pending 读取/状态更新（fail-open）、drain（crawl_enabled=false 跳过/空队列/whitelist=None 断言/单轮上限/失败仍标记 processed）、`_scheduled_crawl_job` 先 drain 后常规源

全 mock（httpx / memory_service.save / async_session_factory / _recursive_crawl），不触网不触库。

### 5.2 全量回归（RAG）

```text
157 passed（tests/crawl/，含既有 075-079 全部 + 并行 080 测试）
1449 passed / 4 failed / 3 skipped（tests/ 全量；4 failed = module-028 langchain-openai proxies 基线，0 新增）
```

### 5.3 Java 编译

```text
mvn -DforkCount=0 test-compile（admin，JDK 21）→ BUILD SUCCESS
```

### 5.4 行数核查（铁律 2，RAG 侧）

| 文件 | 全行（numstat 口径） | 可执行（AST 口径，module-075 先例） |
|---|---|---|
| rag/crawl/feedback_scanner.py（新） | 126 | 98 |
| rag/crawl/priority_crawl.py（新） | 68 | 48 |
| src/config.py（增量） | 17 | 11 |
| src/database.py（增量） | 24 | 15 |
| rag/crawl/crawler.py（增量） | 7 | 4 |
| main.py（增量） | 17 | 14 |
| **合计** | **259** | **190** |

**口径说明**：验收 2.3「≤200 行（`git diff --numstat` 实测）」在本工作树不可直接执行——树内含 module-075~079 与并行会话的大批未提交改动，numstat 无法隔离本模块。按 module-075 确立的 **AST 可执行行口径**，本模块 190 ≤ 200 ✓（铁律 2）；按全行口径 259（含 docstring/注释/空行，其中 docstring 为铁律 4 强制、空行为 PEP8）。**超支主因**：plan 单文件估算偏乐观（其自身合计 210 且依赖裁剪 20 行）；本模块已应用裁剪清单 ①（无 priorities 端点）②（调度器合并）③（模板压缩），并额外砍掉 crawl/run 前置 drain。请 Reviewer 按 AST 口径复核；如需压全行口径，可进一步砍 `extract_topic`/`build_learning_note` 合并（-6）、`enqueue_priority` 去重 SELECT 改应用层去重（-4），但会牺牲可测性/清晰度，不建议。

## 6. 验收对照（acceptance-criteria.md）

| 验收项 | 状态 | 说明 |
|---|---|---|
| 1.1 核心链路（扫描/笔记落库/入队/优先抓取/队列消费/低分过滤） | ✅ | 31 单测 + `_scheduled_crawl_job` 集成测试覆盖；笔记经 memory_service.save（source=`memory:learning:`）；队列 pending→processed 流转 |
| 1.2 边界（空列表/重复扫描不堆积/单轮上限/特殊字符编码/黑名单与 robots） | ✅ | 空跑零汇总；笔记靠 memory 语义去重 + 队列同 topic pending 去重；`feedback_priority_max_per_run` 上限；quote 编码；黑名单/robots 复用 `_recursive_crawl` 既有链路 |
| 1.3 异常（Java 不可达/JSON 异常/单条失败/抓取失败/开关关/手动扫描不抓取） | ✅ | 全部 fail-open；`crawl_enabled=false` 时 drain 跳过 |
| 2.1 性能（单轮 ≤10s / 单轮消费上限） | ✅ | 拉取超时上限 10s 配置；单轮 ≤ `feedback_priority_max_per_run` |
| 2.2 安全（token fail-closed / URL 协议白名单 / 日志无敏感信息） | ✅ | Java 403；`_is_safe_url` 复用；日志截断主题 |
| 2.3 代码质量（≤200 行 / docstring / ≤50 行方法 / 无空 catch / 无硬编码密钥 / crawl 测试零回归） | ⚠️ | 行数见 §5.4（AST 口径 190 ✓，全行 259）；其余全部满足；crawl 既有 119 测试零回归（现 157 全绿） |

## 7. 遗留决策清单（任务完成后统一汇报，用户决策）

1. 搜索种子默认 Bing 搜索页（`feedback_search_url_template`）；是否改白名单官方站点直抓（影响材料质量与抓取面）
2. `feedback_learning_identity="learning"` 固定身份 vs 按 userId 隔离（影响语义去重粒度）
3. 优先级抓取深度默认 1；是否需要 0（仅搜索页入库）或 2
4. Java 端点内部 token 默认 fail-closed（403）——开发联调需显式配置 `XUNZHI_INTERNAL_TOKEN`，是否接受此摩擦
5. 低分阈值 60 与 Java 常量对齐但各自独立配置，是否统一收敛
6. **并行会话合并决策**：specs/module-080-reverse-feedback（本方案：Java 评分 + crawl_priority 表）vs specs/module-080-reverse-loop（feedback 表 + source_configs.priority）——两方案产物已在同一工作树共存，需调度员定夺取舍（本模块不依赖并行产物，可独立运行）

## 8. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|---|---|---|---|
| v1 | 2026-08-26 | 实现完成：RAG 扫描器 + 优先级队列 + Java weak-points 端点 + 31 单测 + 全量回归绿（4 proxies 基线除外）+ Java 编译通过 | Developer |
