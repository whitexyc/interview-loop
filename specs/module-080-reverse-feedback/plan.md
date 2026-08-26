# 开发计划 — Module-080: 反向闭环（低分题 → 待学笔记 → 自动任务优先抓取）

## 1. 需求描述

- 需求来源: ADR-0019 验收标准最后一项「反向闭环：低分题→待学笔记→自动任务优先抓取 链路打通」+ 决策 1 反向链路原文：
  > 面试评分/薄弱点已落 `InterviewQuestion` + `InterviewSession`（Mongo），新增 `@Scheduled` 扫描低分题→调记忆层写入待学笔记→自动任务次日优先抓相关材料
- 功能描述: 定时扫描面试结果中的低分题（得分低于阈值）→ 提取技术主题生成「待学笔记」→ 调记忆层写入（documents 表，source=`memory:learning:`）→ 主题入抓取优先级队列 → 下次定时抓取时优先抓取相关材料 → 完成「面试发现弱点 → 知识库补强」闭环
- 优先级: P0（ADR-0019 最后一个验收项，阶段 3 收口模块）
- 上下文: 阶段 1-3 全部完成（074 出题注入 / 075 抓取流水线 / 076 递归 / 077 反爬 / 078 审查增强 / 079 增量 append），本模块打通「反向」链路

### 1.1 与既有 `specs/module-080-reverse-loop/` 的关系（并行会话产物，如实声明）

- 既有 plan（2026-08-26 并行会话产出）选择 **feedback 表（rating=-1）** 为低分数据源，将 **Java 侧 InterviewQuestion/InterviewSession 集成标为「待澄清」**，优先级接法为 source_configs 加 priority 列 + 关键词匹配。
- 本 plan 按本次任务要求重构：数据源改为 **Java 面试系统真实评分数据**（InterviewTurnLog 每题得分），显式评估三种跨系统集成方案并选定方案 A；优先级改为 **独立主题队列（crawl_priority 表）**，直接驱动「主题→搜索抓取」，不依赖用户已配置源与关键词的匹配度。
- 两目录并行存在，不删除对方产物；模块编号均为 080，若后续合并由调度员决策，本 plan 为当前任务的事实标准。

## 2. 数据探查结论（代码实测）

### 2.1 Java 面试系统侧（ai-meeting-project，Spring Boot 3，端口 8002）

| 事实 | 位置（文件:行） | 说明 |
|---|---|---|
| 服务端口 | `admin/src/main/resources/application.yaml:2` | `server.port: ${SERVER_PORT:8002}` |
| 每题得分 | `interview/service/model/InterviewTurnLog.java` | 字段 `questionNumber / questionContent / score / totalScore / feedback / isFollowUp`，即「低分题」最小数据单元 |
| 每轮得分落库链路 | `InterviewTurnLog` 经 Redis（`InterviewQuestionCacheServiceImpl.appendInterviewTurn`）、Mongo 运行时快照（`InterviewSessionRuntimeSnapshot.recentTurns`）、Mongo 轮次归档（`InterviewSessionTurnArchive.turnPayload`）、MySQL `interview_record.session_snapshot_json` 多路持久化 | 单一路径不可靠，必须走聚合读取 |
| 聚合读取先例 | `flow/report/InterviewRecordServiceImpl.java:312` | `runtimeSnapshotService.loadPersistedTurns(sessionId)` 合并 Redis+快照+归档，本模块 Java 端点直接复用 |
| 会话级总分 | `dao/entity/InterviewRecordDO.java`（MySQL `interview_record.interview_score`） | 会话粒度聚合，非每题粒度；低分题扫描需回到 turn 粒度 |
| 低分阈值先例 | `config/InterviewRuleEngineConfiguration.java:25` | `defaultLowScoreThreshold = 60`；`application/rule/node/LowScoreJudgeNode.java` 判定 `score < lowScoreThreshold` |
| 认证 | `auth/infrastructure/web/SaTokenAuthInterceptorConfig.java:23` | `/api/xunzhi/v1/**` 全部 `StpUtil::checkLogin`，仅白名单路径免登录；新内部端点需加 `notMatch` + 内部 token 校验 |
| 已有端点 | `api/InterviewRecordController.java` | 记录分页/单查均需 `@CurrentUser`（登录态），**无低分题专用端点** → 需新增 |

### 2.2 RAG 侧（ai_service，FastAPI，端口 8001）

| 复用点 | 文件 | 说明 |
|---|---|---|
| APScheduler 调度框架 | `rag/crawl/crawler.py`（`start_scheduler`/`_scheduled_crawl_job`） | interval 触发器 + `replace_existing=True`，lifespan 挂接（main.py:151）；反向闭环新增独立 job |
| HTTP 客户端 | `rag/crawl/crawler.py`（httpx） | 已引入，直接复用拉取 Java 端点 |
| 记忆层（ADR 原文「调记忆层写入待学笔记」） | `rag/memory/memory.py` `memory_service.save(content, identity, ...)` | 写 documents，source=`memory:<identity>:`，自带分块/嵌入/语义去重；retriever 默认排除 `memory:%`（retriever.py:854），笔记不污染知识库检索 |
| 抓取/审查/入库全链路 | `crawler.py` `fetch_page / _review_content / _crawl_page_and_store / _recursive_crawl` + `document_ingest.ingest_document` | 优先级主题抓取零改动复用 |
| 幂等建表先例 | `src/database.py:280-355` | `ensure_source_configs_table` + `ensure_source_configs_max_depth`（`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`），init_db 挂接模式 |
| 配置先例 | `src/config.py:342-386`（crawl_* 块） | pydantic-settings + 环境变量覆盖 |

## 3. 跨系统集成方案评估（关键问题 1 的回答）

| 方案 | 做法 | 结论 |
|---|---|---|
| **A. RAG 拉 Java API（选定）** | RAG 侧 APScheduler 定时任务用 httpx GET Java 新增只读端点 `/api/xunzhi/v1/interview/weak-points`，拿到低分题列表后本地生成笔记 + 入队 | **选定**。① 与「复用 APScheduler」约束一致（调度在 RAG 侧）；② Java 侧只需暴露一个只读查询端点，零侵入面试主链路；③ httpx 已在依赖中；④ 跨服务 URL 配置有 `kb.base-url` 先例（application.yaml 末行） |
| B. Java 推 RAG | Java `@Scheduled` 扫描后 POST RAG 新端点 | 否决。Java 侧需新增调度 + 幂等推送 + 重试，且 Java 已有多个 @Scheduled（turn-repair 等），职责更重；本需求是「次日扫描」低频拉取，拉取比推送简单可靠 |
| C. 共享数据库 | RAG 直读 Java 的 Mongo/MySQL | 否决。Java 用 MongoDB + MySQL，RAG 用 PostgreSQL（asyncpg），无共享库；asyncpg 无法连 MySQL；跨库直读违反分层，且 Java 每题得分散落多路存储，直读无法复用 `loadPersistedTurns` 聚合逻辑 |

**方案 A 的 Java 侧配套（本模块一部分，独立 ≤200 行核算）**：

1. 新增 `GET /api/xunzhi/v1/interview/weak-points?threshold=60&days=7&limit=50`
   - 查询最近 `days` 天 `interview_status ∈ {FINISHED, EVALUATED}` 且 `del_flag=0` 的 `interview_record`（MySQL）
   - 每会话 `runtimeSnapshotService.loadPersistedTurns(sessionId)` 聚合读取轮次（复用 InterviewRecordServiceImpl:312 先例）
   - 过滤 `score != null && score < threshold && !Boolean.TRUE.equals(isFollowUp)`
   - 返回 `[{sessionId, questionNumber, questionContent, score, totalScore, feedback, endTime}]`（最多 `limit` 条，按 endTime 倒序）
2. 认证：`SaTokenAuthInterceptorConfig` 加 `.notMatch("/api/xunzhi/v1/interview/weak-points")`；Controller 内校验内部 token（header `X-Internal-Token` 对比配置 `xunzhi-agent.security.internal-token`，默认空 = 拒绝 403，fail-closed；开发联调设环境变量放行）
3. 涉及文件：`api/WeakPointController.java`（新）、`service/WeakPointService.java` + `impl/WeakPointServiceImpl.java`（新）、`api/io/resp/WeakPointRespDTO.java`（新）、`SaTokenAuthInterceptorConfig.java`（+1 行）、`application.yaml`（+2 行）
4. 预估 Java 生产代码 ~110 行（controller 25 + service 60 + DTO 20 + 配置 5）

## 4. 模块拆分

### 子任务 1: Java 低分题查询端点（ai-meeting-project）
- 描述: 见 §3 方案 A 配套。只读、无副作用、阈值/窗口/条数均可调
- 预估: Java 生产代码 ~110 行（铁律 2 对 Java 侧同样适用）
- 依赖: 无

### 子任务 2: 待学笔记生成（RAG 侧核心）
- 描述: 新增 `rag/feedback/low_score_feedback.py`
  - `fetch_low_score_questions()` — httpx GET Java 端点，超时/异常/解析失败 → 返回 `[]`（fail-open）
  - `build_learning_note(item)` — 结构化模板生成笔记文本（含题目/得分/反馈/来源会话），主题取 `questionContent` 前 ~30 字符（确定性，不调 LLM）
  - `scan_and_generate()` — 编排：拉取 → 逐条 `memory_service.save(note, identity=settings.feedback_learning_identity)`（调记忆层，语义去重防堆积）→ 主题 `enqueue_priority` → 返回汇总 `{scanned, noted, enqueued, errors}`
- 预估: ~70 行
- 依赖: 子任务 1（Java 端点在线才有效，离线则 fail-open 空跑）

### 子任务 3: 抓取优先级队列（RAG 侧）
- 描述:
  - `src/database.py` 新增 `CRAWL_PRIORITY_DDL` + `ensure_crawl_priority_table()`（幂等，init_db 挂接）：新表 `crawl_priority(id, topic, note, session_id, question, score, status[pending/processed/failed], created_at, processed_at)`，`status` 索引
  - `rag/crawl/priority_crawl.py` 新增 `drain_priority_seeds()` — 消费 pending 主题：每个主题 → 种子 URL = `settings.feedback_search_url_template.format(query=quote(topic))`（默认 Bing 搜索）→ 复用 `_recursive_crawl`（深度 `feedback_priority_crawl_depth`，默认 1）抓取 → 无论成败标记 processed（失败记日志，避免死循环重试）
  - `crawler.py` 两处小改：① `_recursive_crawl` 支持 `whitelist=None`（空=不限制，优先级主题为系统显式请求；黑名单/robots/审查节点照常生效）② `_scheduled_crawl_job` 开头懒导入 `drain_priority_seeds()` 并前置执行（「优先」= 常规源之前先抓）
- 预估: ~55 行
- 依赖: 子任务 2（入队）

### 子任务 4: 定时调度 + 端点 + 测试
- 描述:
  - `low_score_feedback.py` 提供 `start_feedback_scheduler()/shutdown_feedback_scheduler()`（独立 APScheduler job `feedback_reverse_loop`，间隔 `feedback_scan_interval_minutes`，默认 1440 即次日；总开关 `feedback_reverse_enabled`，false 不启动）
  - `main.py` lifespan 挂接 + 调试端点 `POST /ai/feedback/scan`（手动触发一轮扫描，返回汇总）
  - 单测：`tests/feedback/test_low_score_feedback.py` + `tests/crawl/test_crawl_priority.py`（mock httpx/DB，覆盖 §5 验收断言）
- 预估: 生产 ~35 行 + 测试 ~130 行
- 依赖: 子任务 2 + 3

## 5. 技术方案

### 5.1 数据表变更（仅 1 张新表）

```sql
CREATE TABLE IF NOT EXISTS crawl_priority (
    id           BIGSERIAL   PRIMARY KEY,
    topic        VARCHAR(200) NOT NULL,
    note         TEXT        NOT NULL DEFAULT '',
    session_id   VARCHAR(64) NOT NULL DEFAULT '',
    question     VARCHAR(500) NOT NULL DEFAULT '',
    score        INTEGER     NOT NULL DEFAULT 0,
    status       VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending/processed/failed
    created_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_crawl_priority_status ON crawl_priority(status);
```

- 说明：不采用「source_configs 加 priority 列」——source_configs 是用户管理的 URL 白名单，主题是关键词非 URL，混入会污染用户视图且依赖关键词与已有源匹配（既有 reverse-loop plan 的接法，本模块显式弃用，理由见 §1.1/§5.3）

### 5.2 待学笔记（调记忆层写入）

- 存储：`memory_service.save(content, identity=settings.feedback_learning_identity("learning"), memory_type="fact")` → documents 表，source=`memory:learning:`，复用分块/嵌入/**语义去重**（同 identity+layer 内余弦 >0.85 命中则更新旧父块，重复扫描不堆积）
- 格式（结构化模板，确定性生成不调 LLM）：

```
【待学笔记】<topic>
面试问题: <questionContent>
本题得分: <score>/<totalScore>
面试反馈: <feedback>
来源会话: <sessionId>
```

- 隔离：retriever 默认排除 `memory:%`（retriever.py:854），笔记不进入知识库检索结果（是"待学记录"而非"知识"），零回归
- 备选（本次不做）：`ingest_document` 入知识库可被 `/ai/rag/search` 检索到，但会污染 KB 检索且需新增 source 排除；留作 P3 演进

### 5.3 优先级抓取流程

```
_scheduled_crawl_job:
  1. await drain_priority_seeds()      # 优先级主题先抓（本模块新增）
  2. sources = _load_sources_from_db() # 常规源照旧
  3. await run_crawl(enabled)          # 零改动

drain_priority_seeds:
  1. SELECT topic FROM crawl_priority WHERE status='pending' ORDER BY id LIMIT :max
  2. 每主题: seed = template.format(query=quote(topic))  # 默认 https://www.bing.com/search?q={query}
  3. await _recursive_crawl(seed, 0, feedback_priority_crawl_depth, whitelist=None, ...)
     # whitelist=None = 不限制（系统显式请求）；黑名单/robots/审查/入库照常
  4. UPDATE crawl_priority SET status='processed', processed_at=NOW()
```

### 5.4 配置清单（src/config.py，~10 行）

| 配置 | 默认 | 说明 |
|---|---|---|
| `feedback_reverse_enabled` | `True` | 总开关（false 不启动调度器，fail-open 主闸） |
| `feedback_java_base_url` | `http://localhost:8002` | Java 服务地址（对齐 kb.base-url 先例） |
| `feedback_low_score_threshold` | `60` | 低分阈值（对齐 Java `defaultLowScoreThreshold=60`） |
| `feedback_scan_interval_minutes` | `1440` | 扫描频率（次日） |
| `feedback_http_timeout_s` | `10` | Java 拉取超时 |
| `feedback_learning_identity` | `learning` | 待学笔记记忆身份 |
| `feedback_search_url_template` | `https://www.bing.com/search?q={query}` | 主题→种子 URL 模板 |
| `feedback_priority_crawl_depth` | `1` | 优先级抓取深度（0=仅搜索页，1=搜索页+结果文章） |
| `feedback_priority_max_per_run` | `5` | 单轮消费 pending 主题上限 |
| `feedback_internal_token` | `""` | 调 Java weak-points 的内部 token（空则跳过该头） |

### 5.5 端点清单

| 端点 | 作用 |
|---|---|
| `POST /ai/feedback/scan`（新增，调试/手动） | 立即执行一轮扫描（拉取→写笔记→入队），返回汇总 |
| `GET /api/xunzhi/v1/interview/weak-points`（Java 新增） | 低分题查询（threshold/days/limit 参数） |
| 既有 `POST /ai/crawl/run`、`GET /ai/crawl/priorities`（可选） | 手动抓取不变；优先级队列查看可选 |

## 6. 关键问题回答汇总

1. **低分题数据源（Java 侧）如何获取？跨系统集成方案？** → 方案 A：RAG 拉 Java 新端点 `GET /interview/weak-points`（Java 内部实现：interview_record + `loadPersistedTurns` 聚合 + `score < threshold` 过滤；SaToken notMatch + 内部 token）。方案 B（Java 推）与方案 C（共享库）否决理由见 §3。
2. **「待学笔记」格式和入库方式？** → 结构化模板（题目/得分/反馈/会话），经 `memory_service.save` 写记忆层（documents，source=`memory:learning:`），复用分块/嵌入/语义去重，见 §5.2。
3. **优先级队列实现（现有 crawl 调度如何支持优先级）？** → 新表 `crawl_priority`（pending/processed）+ `_scheduled_crawl_job` 前置 `drain_priority_seeds()`：主题→搜索种子 URL→复用递归抓取全链路，黑名单/robots/审查照常，见 §5.3。
4. **定时频率（多久扫描一次）？** → `feedback_scan_interval_minutes` 默认 1440（次日一次，对齐 ADR「自动任务次日优先抓」），独立 APScheduler job，可配。

## 7. 生产代码行数预算（铁律 2 ≤ 200 行）

| 改动点 | 预估行数 |
|---|---|
| `rag/feedback/low_score_feedback.py`（新，fetch/note/enqueue/scan/scheduler） | ~120 |
| `rag/crawl/priority_crawl.py`（新，drain） | ~40 |
| `crawler.py`（whitelist=None 1 行 + docstring、job 前置 2 行） | ~8 |
| `src/database.py`（DDL + ensure + init_db 挂接） | ~14 |
| `src/config.py`（新配置块） | ~10 |
| `main.py`（lifespan 挂接 + POST /ai/feedback/scan） | ~18 |
| **合计（RAG 侧）** | **~210 → 目标压到 ≤190** |

超支裁剪清单（按序执行）：① 砍 `GET /ai/crawl/priorities` 调试端点（-10）② `start/shutdown` 调度器合并为单函数对（-5）③ `build_learning_note` 模板压缩（-5）。铁律 2 以 `git diff --numstat` 实测为准，最终由 Developer/Reviewer 验证。
Java 侧独立核算 ~110 行 ≤ 200（铁律 2 两仓分别适用）。

## 8. 复用清单

| 复用项 | 来源 | 说明 |
|---|---|---|
| `memory_service.save`（分块/嵌入/语义去重） | rag/memory/memory.py | 待学笔记写入，零新增 |
| `fetch_page / _review_content / _crawl_page_and_store / _recursive_crawl / run_crawl` | rag/crawl/crawler.py | 优先级抓取全链路，仅 whitelist 参数放宽 |
| `ingest_document` | rag/retrieval/document_ingest.py | 抓取入库，零改动 |
| APScheduler + lifespan 挂接模式 | crawler.py / main.py | 新增独立 job |
| `ensure_*` 幂等建表 | src/database.py | crawl_priority 表 |
| `runtimeSnapshotService.loadPersistedTurns` | Java InterviewRecordServiceImpl:312 | 每题得分聚合读取 |
| httpx | crawler.py 既有依赖 | Java 拉取 |

## 9. 风险评估

- **风险 1: Java 端点不可达/超时** → fail-open：本轮返回空汇总 + 日志告警，下轮再试；主链路零影响
- **风险 2: 低分题数据稀疏（无评分轮次）** → 扫描结果为空即空跑，不报错；`POST /ai/feedback/scan` 可手动验证
- **风险 3: 搜索页质量低（审查 rejected）** → 沿用 module-075 契约（rejected 仍入库 + review_status 标记），后续可加"仅 approved 入库"开关（P3）
- **风险 4: 循环依赖（crawler ↔ priority_crawl）** → 按本仓库「延迟导入」哲学，`_scheduled_crawl_job` 内函数级 import（对齐 crawler.py 既有 `from rag.retrieval.document_ingest import ingest_document` 先例）
- **风险 5: 优先级抓取绕过白名单** → 仅系统显式请求（pending 队列）放行；黑名单/robots.txt/审查节点全链路保留，`feedback_priority_max_per_run` 上限防失控
- **风险 6: 笔记/队列重复堆积** → 笔记靠 memory 层语义去重（同 identity+layer）；队列靠「同 topic pending 不重复入队」+ 处理即标记 processed
- **风险 7: Java 新端点安全** → notMatch 免登录 + 内部 token fail-closed（默认空 = 403），token 走环境变量（铁律 9 禁硬编码）

## 10. 遗留决策清单（任务完成后统一汇报，用户决策）

1. 搜索种子默认用 Bing 搜索页（`feedback_search_url_template`）；是否需要改为白名单官方站点直抓（如 spring.io 检索页）——影响材料质量与抓取面
2. `feedback_learning_identity="learning"` 固定身份 vs 按 userId 隔离——当前面试数据含 userId，是否按用户隔离待学笔记（影响语义去重粒度）
3. 优先级主题抓取深度默认 1（搜索页+结果文章）；是否需要 0（仅搜索页入库）或 2
4. Java 端点内部 token 默认 fail-closed（403）——开发联调需显式配置，是否接受此摩擦
5. 低分阈值 60 与 Java 常量对齐但各自独立配置，是否统一收敛到一处

## 11. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|---|---|---|---|
| v1 | 2026-08-26 | 初始版本（数据源=Java 评分，方案 A，crawl_priority 队列） | Planner |

## 12. 不在本模块范围

- 待学笔记自动过期/「已掌握」标记（P3）
- LLM 主题关键词提取（首版确定性模板，不调 LLM 省钱）
- 面试评分系统 Java 侧 @Scheduled（调度统一在 RAG 侧）
- 「仅 approved 入库」开关、知识库检索面纳入待学笔记（P3）
- 前端待学列表 UI
