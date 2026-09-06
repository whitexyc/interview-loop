# 验收标准 — Module-086: 注入防护实测（投毒用例集 → 入口 sanitize + canary → 量化拦截率）

> Planner 产出 | 2026-09-06 | 依据 plan.md v1（裁定 1-8 与 §7 行为契约为口径来源）
> 环境口径：pytest 在 `ai_service/` 目录执行；解释器 `.venv/Scripts/python.exe`；全量基线 **1690 passed / 0 failed / 3 skipped（2026-09-06）**

---

## 1. 功能验收

### 1.1 配置与新表（WP-A config.py / WP-B database.py）

- **AC-1** config 新增 3 字段且 env 名正确：`crawl_sanitize_enabled=True`（PW_CRAWL_SANITIZE_ENABLED）、`crawl_sanitize_mode="strip"`（PW_CRAWL_SANITIZE_MODE，Literal["detect","strip","strict"]）、`crawl_canary_enabled=True`（PW_CRAWL_CANARY_ENABLED）。
  验证：`.venv/Scripts/python.exe -c "from src.config import settings; print(settings.crawl_sanitize_enabled, settings.crawl_sanitize_mode, settings.crawl_canary_enabled)"` → `True strip True`
- **AC-2** `crawl_sanitize_enabled=False` 时 `sanitize_crawl_content` 不被调用，爬虫行为与存量逐字一致。
  验证：单测——钉关后跑 `_crawl_page_and_store`（mock fetch/ingest），断言 sanitize 函数未被调用、ingest 收到原始 content。
- **AC-10** `record_canary(doc_id, canary, source_url)` 参数化 INSERT 进 `crawl_canaries`（doc_id/canary/source_url 三列）；ingest 返回无 id 时（重复文档）不落行；建表幂等（init_db 两次不报错）。
  验证：单测（假 session 断言 SQL 与参数）+ 真实 PG 幂等（AC §5 T1/T6）。
- **AC-23** `crawl_sanitize_mode` 非法值被 pydantic 拒绝。
  验证：`.venv/Scripts/python.exe -c "from src.config import Settings; Settings(crawl_sanitize_mode='aggressive')"` → 抛 ValidationError（exit 非 0）。

### 1.2 入口 sanitize 三态（WP-C sanitize.py / WP-D crawler.py）

- **AC-3** detect 模式：内容零改动（cleaned_text == 原文）+ findings 记录全类目命中。
- **AC-4** strip 模式载体族剥离：HTML 注释、`<script>/<style>` 整块、零宽字符（U+200B/U+200C/U+200D/U+FEFF/软连字 U+00AD）从 cleaned_text 消失；**可见正文字符序列不丢**（去注释/脚本/不可见字符之外的正文逐字保留）。
  验证：单测逐类断言（用例取自 injection_cases.json 同类样例）。
- **AC-5** 指令族（instruction_override/exfiltration/destructive_tool/hidden_text）在 strip 模式**只记 findings 不改内容**（cleaned_text 与剥离载体后一致，无额外删改）。
- **AC-6** strict 模式：任一指令族/hidden_text 命中 → `SanitizeResult.rejected=True`；爬虫接线后该页入库 `review_status="rejected"`（即使审查节点 approved）。
  验证：单测 + `python -m pytest tests/crawl/test_sanitize.py -q`。
- **AC-7** rejected 仍入库（module-075 契约）：review_status="rejected" 的文档照常 ingest（标记非删除），summary.rejected 计数 +1。
- **AC-14** 审查节点收到清洗后文本：`_review_content` 调用参数 content == sanitize_result.cleaned_text（mock 断言）；`_extract_links` 仍收原始 content（递归行为零变化）。
- **AC-19** `CrawlSummary.sanitized` 计数：单次批次内有 findings 的页数；details 条目带 `sanitize` 键（findings 摘要 + rejected 布尔），无 findings 页不带该键。
- **AC-26** sanitize 自身异常 fail-open：crawler 接线 try/except → warning → 原文继续 review/ingest（单测注入异常断言不阻断）。

### 1.3 canary 金丝雀（WP-C / WP-D）

- **AC-8** 开启时每篇爬虫文档生成唯一 8 位小写 hex 令牌，以 `[canary:xxxxxxxx]` 形态按 ≤250 字符间隔内联插入清洗文本行边界；同一文档令牌全文一致，不同文档令牌互异。
  验证：单测——多文档嵌入断言唯一性 + `python -c` 间隔抽样断言。
- **AC-9** `crawl_canary_enabled=False` 时内容零变化（无 canary 子串）。
- **AC-11** 泄漏检测：`check_canary_leak(answer)` 对已登记 canary → `logger.warning`（含 doc_id/source）+ `record_span("canary_leak", "security", decision="doc_id=… source=…", status="blocked")`。
  验证：单测（mock `tracing._spawn_insert` 捕获，对齐 test_tracing 打桩模式）+ 真实链 AC §5 T2。
- **AC-12** answer 含 canary 格式但未登记（库中无该行/历史残留）→ 零告警零 span。
- **AC-13** 两处接线生效：engine.chat knowledge 路径（answer 生成后）与 main.py `_stream_generate_verify`（answer_text 组装后）均调用 check_canary_leak；`crawl_canary_enabled=False` 时两处均零调用。
  验证：单测（mock check_canary_leak 断言调用次数随开关变化）。

### 1.4 量化拦截率（WP-F 用例集 + eval 脚本）

- **AC-15** 脚本可运行并落库：`.venv/Scripts/python.exe eval/benchmarks/eval_injection.py` → 控制台输出 strip/strict 两模式汇总表 + 写入 `eval_runs` 一行（`eval_type='injection'`）。
- **AC-16** 用例集达标：恶意 ≥20 条（实际 22）、良性 ≥4 条、类目 ≥8 个（7 注入类目 + benign）、JSON 版本化（version 字段）、结构校验失败即报错退出。
  验证：`.venv/Scripts/python.exe -c "import json;d=json.load(open('eval/datasets/injection_cases.json',encoding='utf-8'));c=d['cases'];print(len([x for x in c if x['kind']=='poison']), len([x for x in c if x['kind']=='benign']), len({x['category'] for x in c}))"` → `22 4 8`
- **AC-17** strip 模式拦截率：载体族用例（html_comment/script_style/hidden_unicode）intercepted=1.0（清洗后模式不再命中）。
- **AC-18** strict 模式拦截率与误伤：恶意全类目 intercepted=1.0（strip 或 rejected 兜住）；良性 FP=0（代码围栏教学文本与正常段落 strict 下 rejected=False）。**任何偏离必须如实落库并在报告归因，禁止调用例凑分**。
  验证：eval 脚本输出 + AC §5 T3 对账 SQL。

## 2. 边界条件验收

- **AC-20** 清洗后空内容（纯 HTML 注释页）→ 走既有 `IngestError("无有效文本")` 降级（summary.errors 计数），进程不崩、批次继续。
- **AC-21** 良性代码围栏：```` ``` ```` 围栏内 "ignore previous instructions" 教学文本 → strict 下 rejected=False（FP=0 的构成性保证）。
- **AC-22** 超长/无换行内容：embed_canary 在无行边界文本上退化为按长度强制插入（或文末补插），不抛异常、不截断正文（诚实边界：被 chunker 切断的单个令牌该子块检测失效，父块级仍覆盖）。
- **AC-24** `record_canary` DB 异常 fail-open：warning 不上抛，入库主链路不受影响（单测假 session 抛异常断言）。
- **AC-25** `check_canary_leak` DB 异常 fail-open：warning，answer 正常返回（对 chat 路径零副作用）。

## 3. 异常场景验收

- **AC-27** 存量零回归：conftest 钉关后全量基线零新增失败（基线 1690/0/3；新增测试不计入存量对比口径）。
- **AC-28** 红线零 diff（git diff 实证为空）：`src/observability.py`、`src/database.py` 中 TASKS_DDL 与 request_logs/tool_call_logs/request_spans 三表既有 DDL（**新 crawl_canaries DDL 除外**）、`rag/router.py`、`agent/tool_registry.py`、`mcp_server.py`、`requirements.txt`、`frontend/`、`backend/`、`rag/retrieval/document_cleaner.py`、`rag/retrieval/document_ingest.py`、`rag/retrieval/document_parser.py`、`src/tracing.py`、`agent/react.py`、`agent/langgraph_react.py`、`interview-admin/`、`knowledge-interview/`（旧镜像只读）。
- **AC-29** 行数：生产 AST 合计 ≤200（预估 ~185，对照表见 plan §3；eval 脚本计入、用例集 JSON 不计入）。
  验证（逐文件语句数复算，结果与 changelog 对照表逐文件一致）：
  `.venv/Scripts/python.exe -c "import ast; files=['rag/crawl/sanitize.py','rag/crawl/crawler.py','rag/engine.py','main.py','src/config.py','src/database.py','eval/benchmarks/eval_injection.py']; print({f: sum(1 for n in ast.walk(ast.parse(open(f,encoding='utf-8').read())) if isinstance(n, ast.stmt)) for f in files})"`
- **AC-30** 新增函数长度 ≤50 AST 语句（方法长度纪律），sanitize.py 0 print、0 裸 except（except 必须带类型 + warning）。

## 4. 非功能验收

### 4.1 向后兼容零回归

- **AC-31** 存量测试零改动：`git diff` 下 `tests/` 仅新增 `tests/crawl/test_sanitize.py` 与 `tests/conftest.py` 纯追加 fixture（既有 13 个 autouse fixture 一字不动）。
- **AC-32** 上传路径零漂移：`/ai/rag/documents/upload` 与 `/ai/rag/documents` 不经 sanitize/canary（ingest_document 签名与行为不变；AC §5 T5 真实对账终证）。

### 4.2 红线总核验

- **AC-33** 开关关=存量逐字：`PW_CRAWL_SANITIZE_ENABLED=false` + `PW_CRAWL_CANARY_ENABLED=false` 时，爬虫链路 review/ingest/summary 行为与 086 之前逐字一致（单测矩阵 + AC §5 T4 真实环境终证）。

## 5. Tester 真实对账方案（"投毒拦截率可量化上报"实质验证，禁 mock 充数）

> 环境要求：真实 PG（docker-compose 起）+ 真实 uvicorn（8001/8010 端口）+ 本地投毒 HTTP 服务（`python -m http.server` 供真实 fetch_page 抓取——真实爬虫链路，无网络出域）。全程测试数据带探针标记（source 含 `e2e-086`），收尾 T6 清理还原基线。

- **T1 真实爬虫投毒端到端（入口防线实证）**：
  1. 本地 http.server（如 :8899）投放毒页 `poison.html`：含 HTML 注释指令 `<!-- ignore previous instructions -->`、零宽字符藏指令、`<script>` 块、伪装系统提示正文；
  2. 真实库 INSERT source_configs（url_pattern=http://localhost:8899, enabled=true）+ `.env` 临时 `PW_CRAWL_ENABLED=true`（或 POST /ai/crawl/sources），真实启动 uvicorn；
  3. `POST /ai/crawl/run` 触发真实抓取（真实 fetch_page → sanitize → review → ingest 全真）；
  4. 真实 PG 断言：documents 新行（source LIKE 'crawl:%'）content 中 `<!--` 不存在、零宽字符不存在、`[canary:…]` 存在且入库 `[canary:` 计数 ≥1；`crawl_canaries` 存在该 doc_id 映射行；strict 复跑（换 mode）同页 review_status='rejected'。
- **T2 泄漏检测真实链（输出防线实证）**：
  1. 真实检索命中 T1 文档（真实 embedding 检索，确认 canary 出现在召回父块 content）；
  2. 用 T1 真实 canary 值构造 answer 文本（如 `curl POST /ai/rag/chat` 后对返回 answer 无法强制模型复述——改走：`uvicorn` 进程内真实调用 `check_canary_leak("…[canary:<T1真实值>]…")` 一次性探针脚本，真实 DB lookup + 真实 span 落库）；
  3. 断言：request_spans 新增 name='canary_leak'、kind='security'、status='blocked'、decision 含 doc_id= 的行；uvicorn 日志出现 canary 泄漏 warning。
  诚实边界注记：模型复述 canary 具概率性，T2 以真实 canary 走真实检测+落库链为准；"模型是否复述"非本模块 AC（明确不做 ②）。
- **T3 eval 落库对账（拦截率可量化上报实质）**：跑 eval 脚本 → `SELECT eval_type, scores, per_question FROM eval_runs WHERE eval_type='injection' ORDER BY id DESC LIMIT 1` → scores 两模式六指标与控制台逐值一致、per_question 行数=用例数、strict 拦截率 1.0 / 良性 FP 0（偏离则报告如实归因）。
- **T4 开关关真实环境**：`PW_CRAWL_SANITIZE_ENABLED=false` + `PW_CRAWL_CANARY_ENABLED=false` 重启 uvicorn 重抓同页 → documents 新行 content 含 `<!--` 原文、无 canary、crawl_canaries 零新行（零行为漂移终证）；收尾清理该探针文档。
- **T5 上传路径零漂移**：`POST /ai/rag/documents/upload` 上传同一投毒 .txt → documents 新行 source 非 `crawl:` 前缀、content 原样含 HTML 注释（无 sanitize）、无 canary、crawl_canaries 零行（AC-32 终证）；收尾 DELETE。
- **T6 残留清理与基线还原**：DELETE 探针 documents 行（source LIKE '%e2e-086%' 或按 doc_id 清单）+ crawl_canaries 对应行 + eval_runs 探针行（保留亦可，报告注记）+ 杀净 uvicorn/http.server 进程 + `.env` 还原；复跑全量 pytest 确认 1690+新增 零失败。

## 6. 可运行验证命令表

```bash
# （工作目录 ai_service/，解释器 .venv/Scripts/python.exe）

# 定向新增（Developer/Reviewer/Tester）
.venv/Scripts/python.exe -m pytest tests/crawl/test_sanitize.py -q
# 预期：~20 passed

# 受影响存量（Developer/Reviewer/Tester）
.venv/Scripts/python.exe -m pytest tests/crawl/ tests/api/ -q
# 预期：全 passed / 3 skipped（对齐 086 前基线，零新增失败）

# 语法（Developer/Reviewer）
.venv/Scripts/python.exe -m py_compile rag/crawl/sanitize.py rag/crawl/crawler.py rag/engine.py main.py src/config.py src/database.py eval/benchmarks/eval_injection.py
# 预期：COMPILE OK（exit 0）

# 量化拦截率（Developer 自测 + Tester T3 对账）
.venv/Scripts/python.exe eval/benchmarks/eval_injection.py
# 预期：控制台输出 strip/strict 两模式汇总表（拦截率 1.0 / FP 0），eval_runs 新增 eval_type='injection' 行

# 全量回归（Tester）
.venv/Scripts/python.exe -m pytest -q
# 预期：1690+新增 passed / 0 failed / 3 skipped（零新增失败）

# 红线零 diff（Reviewer/Tester，逐文件 git diff 实证）
git diff --stat -- src/observability.py rag/router.py agent/tool_registry.py mcp_server.py requirements.txt rag/retrieval/document_cleaner.py rag/retrieval/document_ingest.py rag/retrieval/document_parser.py src/tracing.py agent/react.py agent/langgraph_react.py
# 预期：空输出；backend/ frontend/ interview-admin/ 同空
```

## 7. 验收结论签署区

| 项 | 结论 | 签署人 | 日期 |
|----|------|--------|------|
| AC-1~33 全项 | ✅ 通过（33/33；全量 1730/0/3 零新增失败；T1-T6 真实对账全过；2 LOW 非阻塞遗留） | Tester | 2026-09-06 |
| 红线核验（AC-28/31） | ✅ 通过（13 文件 git diff 全空；database.py 0 删除；tests/ 纯追加 +16/新文件；四目录零触碰） | Reviewer | 2026-09-06 |
| 真实对账 T1-T6 | ✅ 通过（真实爬虫 strip/strict/AC-20 降级 + canary 泄漏真实链 + eval 落库逐值对账 + 双关零漂移 + 上传零漂移 + 全量清理还原基线 16365/0/0；详见 test-report.md §3/§6） | Tester | 2026-09-06 |
