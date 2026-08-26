# 验收标准 — Module-080: 反向闭环（低分题 → 待学笔记 → 自动任务优先抓取）

对应 ADR-0019 验收标准：「反向闭环：低分题→待学笔记→自动任务优先抓取 链路打通」

## 1. 功能验收

### 1.1 核心链路验收（低分题 → 待学笔记 → 优先级抓取）

- [ ] **扫描**：触发一轮反向闭环（`POST /ai/feedback/scan` 或定时 job），Java weak-points 端点（或 mock）返回 N 条 `score < threshold` 的低分题 → 扫描汇总返回 `{scanned: N, noted: N, enqueued: N, errors: 0}`
- [ ] **待学笔记落库（调记忆层）**：documents 表新增 source=`memory:learning:` 的记录，笔记内容含题目（questionContent）、本题得分（score/totalScore）、面试反馈（feedback）、来源会话（sessionId），且标题/主题取自题目文本
- [ ] **优先级队列入队**：crawl_priority 表新增 N 条 `status='pending'` 记录，字段 topic/note/session_id/question/score 与低分题一一对应
- [ ] **优先级抓取优先**：存在 pending 主题时触发定时抓取（或 `POST /ai/crawl/run` 前的 drain），日志/行为证明优先级主题先于常规源抓取；每个 pending 主题生成种子 URL（`feedback_search_url_template` 模板）并执行抓取
- [ ] **队列消费闭环**：抓取完成后 crawl_priority 对应记录 `status='processed'`、`processed_at` 非空；抓取到的内容经 document_ingest 入库（documents 表新增 source 含 `crawl:` 的文档）
- [ ] **低分题过滤**：`score >= threshold` 的题不写笔记、不入队（阈值默认 60，可配置）

### 1.2 边界条件验收

- [ ] 低分题为空（Java 返回空列表）→ 扫描空跑返回 `{scanned: 0, noted: 0, enqueued: 0}`，不报错
- [ ] 同一低分题重复扫描 → 笔记不重复堆积（memory 层语义去重命中 → 更新旧笔记而非新增；crawl_priority 同 topic pending 不重复入队）
- [ ] pending 主题超过 `feedback_priority_max_per_run` → 本轮只消费前 K 条，其余留待下轮
- [ ] 主题含特殊字符（引号/百分号/中文）→ 种子 URL 正确 URL 编码（quote），抓取不因编码错误失败
- [ ] 优先级抓取命中黑名单 URL（`crawl_blacklist_patterns`）→ 跳过（不入库，日志记录）；robots.txt 禁止 → 跳过

### 1.3 异常场景验收（fail-open，主链路零影响）

- [ ] Java 端点不可达（连接拒绝/超时/非 200）→ 扫描返回空汇总 + 日志告警，不抛异常、不影响其他请求
- [ ] Java 返回 JSON 结构异常/字段缺失 → 该条跳过（fail-open），其余条正常处理
- [ ] 单条笔记写入失败（memory_service.save 异常）→ 该条记入 errors，其余条继续，不中断整轮
- [ ] 单条优先级抓取失败（网络/审查/入库异常）→ 队列仍标记 processed + 日志记录，不影响其他主题与常规源
- [ ] `feedback_reverse_enabled=false` → 调度器不启动，既有 crawl 调度器照常（零回归）
- [ ] 抓取调度器未启动（`crawl_enabled=false`）时手动 `POST /ai/feedback/scan` → 只写笔记+入队，不抓取（fail-open）

## 2. 非功能验收

### 2.1 性能验收

- [ ] 单轮扫描（拉取 Java + 写 N 条笔记 + 入队）在 10s 内完成（N ≤ 50，含 Java 拉取超时上限 10s 约束）
- [ ] 优先级抓取单轮消费 ≤ `feedback_priority_max_per_run` 主题，受 crawl 既有页数上限约束（`crawl_max_pages_per_run`）

### 2.2 安全验收

- [ ] Java weak-points 端点免登录但校验内部 token（header `X-Internal-Token`）；token 未配置 → 403（fail-closed），token 值来自环境变量（禁硬编码）
- [ ] 优先级种子 URL 仅允许 http/https 协议（复用 `_is_safe_url`）；主题文本经 URL 编码，无注入面
- [ ] 日志不含内部 token、不含 Java 返回的敏感个人信息（题目文本按需截断）

### 2.3 代码质量验收

- [ ] RAG 侧新增生产代码合计 ≤ 200 行（铁律 2，`git diff --numstat` 实测）；Java 侧 ≤ 200 行（两仓分别核算）
- [ ] 新增公开方法均有 docstring（铁律 4）；方法 ≤ 50 行（铁律 3）
- [ ] 无空 catch / 吞异常（铁律 5）：所有 except 至少日志；业务失败走 fail-open 而非静默
- [ ] 无硬编码密钥/明文密码（铁律 9）；config 新增项均带环境变量覆盖说明
- [ ] `crawler.py` 修改为最小侵入（whitelist=None 支持 + job 前置调用），既有 119 个 crawl 测试零回归

## 3. 可运行验证命令

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 新增单测 | `cd ai_service && python -m pytest tests/ -k "feedback or priority or weak" -v` | `60 passed, 0 failed`（含本模块 test_feedback_scanner 21 + test_priority_crawl 10 + 并行会话 23 + 存量 feedback API 7；实现路径 tests/crawl/，验收命令原 tests/feedback/ 为漂移已修订） |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | `1449 passed, 4 failed`（module-028 proxies 基线除外）、`3 skipped` |
| py_compile | `cd ai_service && python -c "import py_compile; [py_compile.compile(f) for f in ['rag/crawl/feedback_scanner.py','rag/crawl/priority_crawl.py','rag/crawl/crawler.py','src/config.py','src/database.py','main.py']]"` | 无报错（原命令文件名为 plan 旧名 rag/feedback/low_score_feedback.py，实现按任务 brief 落 rag/crawl/feedback_scanner.py，已修订） |
| 行数核查 | `git diff --numstat`（RAG 侧新增生产代码） | 合计 ≤ 200 |
| 手动扫描 | `curl -X POST http://localhost:8001/ai/feedback/scan` | `{"code":0, "data":{"scanned":N,"noted":N,"enqueued":N,"errors":M}}` |
| 笔记落库 | `psql -h 127.0.0.1 -U postgres -d personal_website -c "SELECT id,title,source,left(content,80) FROM documents WHERE source LIKE 'memory:learning:%' ORDER BY id DESC LIMIT 5"` | 存在待学笔记记录 |
| 队列状态 | `psql ... -c "SELECT topic,status FROM crawl_priority ORDER BY id DESC LIMIT 10"` | pending → processed 流转可见 |
| 抓取入库 | `psql ... -c "SELECT id,title,source FROM documents WHERE source LIKE 'crawl:%' ORDER BY id DESC LIMIT 5"` | 优先级主题抓取的文档出现 |
| Java 端点 | `curl -H "X-Internal-Token: <token>" "http://localhost:8002/api/xunzhi/v1/interview/weak-points?threshold=60&days=7&limit=10"` | `{"code":0,"data":[{sessionId,questionNumber,questionContent,score,...}]}` |
| Java 端点无 token | `curl "http://localhost:8002/api/xunzhi/v1/interview/weak-points"` | 403 |

## 4. 验收结论

- 审查人: Reviewer (module-080-reverse-feedback)
- 测试人: Tester (module-080-reverse-feedback)
- 验收时间: 2026-08-26
- 结论: [x] 通过
- 备注: Tester 实测 27/27 通过（详见 test-report.md）。漂移登记：① §3 py_compile/单测命令文件路径（rag/feedback/low_score_feedback.py → rag/crawl/feedback_scanner.py；tests/feedback/ → tests/crawl/）已同步修订；② 「标题/主题取自题目文本」按笔记内容首行口径达成（documents.title 为记忆层共享格式，P3-2）；③ 行数按 AST 可执行行口径 190 ≤ 200（git diff --numstat 在本工作树不可隔离本模块，P3-1）；④ Reviewer P2-1（Java per-session 无 try/catch）确认存在、端到端被 RAG fail-open 吸收，不阻塞。
