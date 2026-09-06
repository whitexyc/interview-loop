# 测试报告 — Module-086: 注入防护实测（投毒用例集 → 入口 sanitize + canary → 量化拦截率）

> Tester: 2026-09-06 | 测试对象：specs/module-086-injection-defense/（plan v1 / AC-1~33 / changelog v1 / review-report PASS）
> 测试方法：独立复跑（不采信 Developer/Reviewer 声明）+ 全量回归 + T1-T6 真实 PG 对账（真实 uvicorn + 本地投毒 HTTP 服务 + 真实爬虫管线）+ 红线 git diff 实证
> 环境：ai_service 目录 / .venv/Scripts/python.exe / 真实 PG（localhost:5432/personal_website）/ uvicorn :8010 / 本地投毒页 :8899（无外网出域）

## 1. 验证命令执行结果（独立复跑）

| 命令（cwd=ai_service） | 预期 | 实测 | 结论 |
|---|---|---|---|
| pytest tests/crawl/test_sanitize.py -q | 40 passed | **40 passed**, 2 warnings in 10.84s | ✅（2 warnings 为环境既有 starlette PendingDeprecationWarning，与本模块无关） |
| pytest tests/crawl/ tests/api/ tests/core/ -q | 730 passed / 3 skipped | **730 passed, 3 skipped** in 29.61s | ✅（3 skip 对齐基线） |
| pytest tests/agent/ tests/memory/ -q | 603 passed | **603 passed** in 84.99s | ✅ |
| py_compile 7 变更文件 | COMPILE_OK | COMPILE_OK（exit 0） | ✅ |
| config 冒烟（AC-1） | `True strip True` | `True strip True`（逐字） | ✅ |
| AC-23 非法 mode | ValidationError | pydantic literal_error（Input should be 'detect', 'strip' or 'strict'） | ✅ |
| AC-16 用例集统计 | `22 4 8` | `22 4 8`（逐字） | ✅ |
| AC-29 AST 语句数 | sanitize 101/crawler 494/engine 533/main 684/config 127/database 219/eval 73 | 101/494/533/684/127/219/73（逐值一致） | ✅ |
| 红线 git diff（observability/tracing/tasks/router/tool_registry/mcp_server/requirements/react/langgraph_react/document_cleaner\|ingest\|parser） | 全空 | 全空（git diff --stat 零输出） | ✅ |
| git status knowledge-interview backend frontend interview-admin | 无输出 | 无输出 | ✅ |
| 全量回归 pytest tests/ -q | 1730 / 0 / 3 | **1730 passed, 3 skipped** in 112.41s（exit 0） | ✅（1690 基线 + 40 新增，零新增失败；163 warnings 均为环境既有 Pydantic/starlette 弃用告警，与本模块无关） |

### 1.1 全量回归差异逐根因归类

- failed = 0：无差异项可归类。
- skipped = 3：与基线（089 闭环时 1690/0/3）逐字对齐，3 个 skip 为存量固有（非本模块引入，受影响存量分组复跑 730/3 同样复现同一批 skip）。
- passed = 1730 = 1690 + 40：40 新增全部来自 tests/crawl/test_sanitize.py（定向复跑 40/40 独立证实），存量 1690 零变动（受影响存量 crawl/api/core 730/3 + agent/memory 603 分组复跑零失败交叉印证）。
- collection warning：0（pytest 收集干净，无 IncompleteFieldDefinition 以外的收集期错误；该 warning 为 pydantic_settings 对既有 lifespan 前向引用的环境性提示，非本模块引入）。

变更面 numstat（git diff --numstat，全落在申报范围内）：main.py +5/0、rag/engine.py +5/0、rag/crawl/crawler.py +29/5（5 删除 = run_crawl 收尾日志行按 plan WP-D 授权的唯一既有语句改动）、src/config.py +13/0、src/database.py +32/0（0 删除 = 既有四段 DDL 一字未改）、tests/conftest.py +16/0（纯追加）；新增 4 文件（sanitize.py / eval_injection.py / injection_cases.json / test_sanitize.py）。

## 2. 失败详情

（全量回归后填写）

## 3. 真实 PG 对账（T1-T6）

### T1 真实爬虫投毒端到端 —— ✅ 通过

环境：本地 http.server :8899 投毒页（无外网出域）+ source_configs 探针行（id=5，既有 id=1 外网源临时钉 enabled=false）+ 真实 uvicorn :8010（PW_CRAWL_ENABLED=true，模式以进程环境变量注入，.env 零改动）+ POST /ai/crawl/run 真实管线（fetch_page → sanitize → review → ingest → record_canary）。

strip 档（e2e-086-poison.html，真实抓取返回 crawled=1）：

| 断言 | 结果 |
|---|---|
| documents 根行 id=17454（source=crawl:http://localhost:8899/e2e-086-poison.html） | ✅ 存在，1 根 + 7 子块 |
| content 无 `<!--` / `<script` / `<style` | ✅ 全 False |
| 零宽字符（U+200B/200C/200D/00AD/FEFF）残留 | ✅ NONE |
| `[canary:…]` 存在且计数 ≥1 | ✅ 根块 5 个、全树 10 个，同一令牌 14e40840（同文档唯一性） |
| 令牌间距（plan WP-C 口径 [250, 250+行长)） | ✅ 279/300/300/304，均在行边界插入 |
| crawl_canaries 映射行 | ✅ doc_id=17454 / canary=14e40840 / source_url 原样 |
| AC-5 指令族只记不改 | ✅ "忽略之前的所有指令"/"System prompt"/"删除所有"/attacker.example/隐藏文本可见正文全部逐字保留 |
| summary.sanitized（日志 抓取批次完成行） | ✅ sanitized=1 |

strict 档复跑（e2e-086-poison-strict.html，等价投毒内容换文件——同 URL 重抓会命中 module-064 L1 内容哈希去重返回无 id，观察不到 rejected 行，故用等价页；诚实注记）：

| 断言 | 结果 |
|---|---|
| 根行 id=17464 review_status='rejected' | ✅ |
| crawl_canaries 行 doc_id=17464 / canary=72265a19 | ✅ |
| 载体剥离 + canary 在内容中 | ✅ |
| 日志 sanitized=1（sanitize findings 计数真实链生效） | ✅ |
| 归因注记：真实链审查器（reflector sufficient=False）亦拒收，"review=approved 仍强制 rejected"反事实由单测 test_sanitize.py:309-315 覆盖 | ✅ |

AC-20 顺带覆盖（备忘 B2 兜底）：真·纯注释页（仅两行 HTML 注释无任何标签）strip 后空文本 → POST /ai/crawl/run 返回 **crawled=0 / errors=1**，uvicorn 日志出现"递归入库失败： 文档解析后无有效文本内容"（crawler.py:601 warning），**进程不崩、无新 documents 行、无新 canary 行**，批次继续。诚实注记：首版测试页带了完整 HTML 外壳（DOCTYPE/head/body），ingest 层 HTML 转文本提取出标题照常入库（存量行为非缺陷），已修正为无标签纯注释页后复测。

### T2 泄漏检测真实链 —— ✅ 通过

一次性探针脚本（进程内真实调用 check_canary_leak，真实 DB lookup + 真实 span 落库；探针先 init_request + begin_request 建立观测上下文——check_canary_leak docstring 明示无请求上下文时 span 静默跳过，故裸调不落库为设计内行为）：

| 断言 | 结果 |
|---|---|
| 阴性（AC-12）：未登记令牌 `[canary:deadbeef]` → 零告警零 span | ✅ delta=0 |
| 阳性：真实登记令牌 14e40840（T1 落库 crawl_canaries）→ warning + span | ✅ delta=1 |
| warning 原文 | ✅ `canary 泄漏: doc_id=17454 source=http://localhost:8899/e2e-086-poison.html canary=14e40840` |
| span 四要素 | ✅ name='canary_leak' / kind='security' / status='blocked' / decision='doc_id=17454 source=http://localhost:8899/e2e-086-poison.html'（走 088 record_span 既有通道） |

诚实边界（AC §5 已注记，照录）：模型是否复述 canary 具概率性、非本模块 AC；T2 以真实 canary 走真实检测+落库链为准。

### T3 eval 落库对账 —— ✅ 通过

`.venv/Scripts/python.exe eval/benchmarks/eval_injection.py` 控制台输出与 eval_runs 落库行（id=61，eval_type='injection'）逐值对账：

| 指标 | 控制台 | eval_runs.scores | 一致 |
|---|---|---|---|
| strip 恶意拦截 | 22/22 = 1.0 | intercepted=22, poison_total=22, interception_rate=1.0 | ✅ |
| strip 误伤 | 0（rate 0.0） | false_positives=0, false_positive_rate=0.0 | ✅ |
| strict 恶意拦截 | 22/22 = 1.0 | intercepted=22, interception_rate=1.0 | ✅ |
| strict 误伤 | 1（rate 0.25）= benign-03 | false_positives=1, false_positive_rate=0.25 | ✅（Reviewer 备忘 B3 口径：strict FP 期望值=1，benign-03 CSS 关键词讲解 hidden_text 字面命中，设计内语义） |
| 归因注记 | 控制台明示 benign-03 归因（plan 裁定 5） | per_question 26 行，每用例带 strip/strict 双模式 findings 明细（抽查 hu-01 含 hidden_unicode+instruction_override findings） | ✅ |

### T4 开关关真实环境 —— ✅ 通过

PW_CRAWL_SANITIZE_ENABLED=false + PW_CRAWL_CANARY_ENABLED=false（进程环境变量）重启 uvicorn，重抓投毒页（e2e-086-poison-raw.html，返回 crawled=1）：

| 断言 | 结果 |
|---|---|
| documents 新行（id=17467）content 含 `<!--` 原文 | ✅ 含注释原文与 XyQ7 探针标记、`<script>` 块原文保留 |
| 无 canary | ✅ 内容零 `[canary:` 子串 |
| crawl_canaries 零新行 | ✅ 总数保持 3（本次为零新增） |
| 零 sanitize/canary span | ✅ canary_leak span 总数保持 1（本次零新增；sanitize 本无 span 埋点，设计内） |
| review_status | rejected（审查链 HHEM 对原始 HTML 判拒，与 sanitize 无关——开关已关） |

诚实注记：content 零宽字符亦无残留——系 module-064 清洗层（ingest 内部既有行为）所为，与 sanitize 无关且 086 之前即如此，符合"存量行为逐字"要求。

### T5 上传路径零漂移 —— ✅ 通过

POST /ai/rag/documents/upload 上传含 HTML 注释的 .txt（返回 code=0，doc_id=17469，chunks=2，原件落盘 uploads\bfb007397b960a4e_e2e-086-upload-poison.txt）：

| 断言 | 结果 |
|---|---|
| source 非 crawl: 前缀 | ✅ `txt_upload:e2e-086-upload-poison.txt` |
| content 原样含 HTML 注释（无 sanitize） | ✅ `<!-- this html comment must survive upload path -->` 与 `<script>kept()</script>` 均保留 |
| 无 canary | ✅ 零 `[canary:` 子串 |
| crawl_canaries 零行 | ✅ doc_id=17469 映射行 0 |

### T6 残留清理与基线还原 —— ✅ 完成

| 清理项 | 执行 | 还原核验 |
|---|---|---|
| 探针 documents 行（source LIKE '%e2e-086%'） | DELETE 17 行 | documents 总数 16382 → **16365 = 基线** |
| crawl_canaries 探针行 | DELETE 3 行 | **0 = 基线** |
| eval_runs 探针行（eval_type='injection'） | DELETE 1 行（id=61） | **0 = 基线** |
| request_spans 本会话行（4 次 /ai/crawl/run + 1 次 upload + /docs 就绪探测 + T2 探针 3 行，started_at>18:50 边界） | DELETE 13 行 | 本会话 span **0**（更早会话 07:1x-07:5x 的行非本会话产物，未触碰） |
| request_logs | 无需清理（该表只记 LLM 请求，crawl/upload 请求不产生行，实测 0 行） | — |
| source_configs | DELETE 探针行 id=5；UPDATE id=1 enabled=true（还原钉住） | 仅剩原 FastAPI 行，url_pattern/enabled 与测试前逐字段一致 |
| 物理原件（uploads\ 下 5 个探针文件） | 已删 | uploads/ 零 e2e-086 残留 |
| 探针目录 .e2e-086-www（投毒页 4 + 上传样本 1 + 生成器/探针脚本 2） | 整目录已删 | 目录不存在 |
| 进程 | uvicorn（3 次启停）+ http.server 8899 全部停止 | 8010/8899 端口 netstat 零监听 |
| .env | **全程零改动**（爬虫开关以进程环境变量注入，未使用 .env 备份/还原路径） | git status .env 无变更 |
| 清理后全量复跑 | pytest tests/ -q | **1730 passed, 3 skipped** in 115.69s（与清理前一致，库态还原终证） |

## 4. Reviewer 2 LOW + 4 备忘逐项独立核验

| 项 | 核验结果 | Tester 裁定 |
|---|---|---|
| LOW-1 sanitize.py:33 `from src.config import settings` 未使用 | **属实**——全文通读（Tester 独立读 sanitize.py 238 行）：settings 在代码中零引用（唯一出现是 :126 docstring 文字提及），mode 由参数传入、开关检查在调用点 | 确认存在，非阻塞；建议随下次 Developer 变更顺带删除（ Tester 不动生产代码，避免 AST 口径 195→194 引发 changelog/review 数字连锁修订） |
| LOW-2 find_canaries docstring 缺 Args/Returns + test_sanitize.py:125 `(self, )` 尾随逗号 | **属实**——sanitize.py:179-181 单行 docstring（同文件其余 4 个公开函数均有结构段）；测试签名尾逗号在 :125 实见 | 确认存在，非阻塞；同上随下轮顺带 |
| B1 AC-8 "≤250 字符间隔"与 plan WP-C "≥250 行边界追加"矛盾 | **属实**——实现语义为行累积越过 250 在当前行边界插入，间距 ∈ [250, 250+行长)； Tester 间隔抽样按 plan WP-C 口径执行：真实文档实测 279/300/300/304 全部落在区间内，**通过**；AC-8 字面"≤250"在行边界语义下不可满足，建议文档侧勘误 AC-8 措辞（本报告不判失败） |
| B2 AC-20 无专项单测 | **属实**——test_sanitize.py 40 项测试名逐一无空内容用例；补偿证据链完整：Reviewer 运行时探针 + 本轮 T1 真实链复现（errors=1 降级、进程不崩、零新行） | 确认，非阻塞；后续如补 1 项单测即可 |
| B3 strict FP=1（benign-03）设计内语义 | **属实**——T3 控制台注记明示 `['benign-03']` 归因；4 良性中仅 1 FP，数学上蕴含 benign-01/02/04 rejected=False（AC-18 括号口径两类均非 FP）；strip 档 FP=0 | 确认，T3 对账 strict FP 期望值取 1，通过 |
| B4 dt-01 治理措辞字面命中 | **属实**（用例集与规则同源设计的固有性质，per_question 26 行结构在 T3 删除前已核对存在双模式明细）；不要求改用例/规则 | 确认，留待信任分级模块联动消解 |

## 5. 验收标准核对（AC-1 ~ AC-33 逐项签署）

### 5.1 功能验收

| AC | 要求 | 证据（独立复跑/复验） | 签署 |
|---|---|---|---|
| AC-1 | config 3 字段 + env 名 | CLI 冒烟 `True strip True` 逐字（本报告 §1）；字段位于 config.py:428-437，注释含 PW_CRAWL_SANITIZE_ENABLED/MODE/CANARY_ENABLED 全名 | ✅ |
| AC-2 | sanitize 关 = 不调用、行为逐字 | 单测 test_sanitize_off_zero_change（:318-327，mock assert_not_called + 原文直通）+ **T4 真实环境**（注释/脚本原文入库 + sanitized=0 日志 + 零 span + 零 canary 行） | ✅ |
| AC-3 | detect 零改动 + findings 全类目 | test_detect_zero_change_and_findings（:38-50） | ✅ |
| AC-4 | strip 载体族剥离、可见正文不丢 | TestCarrierStripping 3 项（:77-98，零宽 5 码点逐变体）+ **T1 真实链**（`<!--`/`<script`/零宽零残留，正文段落逐字在库） | ✅ |
| AC-5 | 指令族只记不改 | TestInstructionMarking 6 项（:100-133）+ **T1 真实链**（"忽略之前的所有指令"/"System prompt"/"删除所有"/外传 URL/隐藏可见文本逐字保留） | ✅ |
| AC-6 | strict 命中即 rejected | test_strict_rejects_instruction + test_strict_carrier_only_not_rejected（:58-66）+ 接线 test:309-315（review=approved 仍强制 rejected）+ **T1 strict 真实链**（root 17464 review_status='rejected'） | ✅ |
| AC-7 | rejected 仍入库（075 契约） | test:309-315（rejected=1 且仍 crawled）+ **T1 真实链**（17464 rejected 行照常入库且 canary 映射落库） | ✅ |
| AC-8 | canary 唯一令牌行边界间隔嵌入 | TestCanary（:136-167，唯一性/行边界/短文补插/跨文档互异）+ **T1 真实链抽样**（root 1584 字符 5 令牌，间距 279/300/300/304，同文档同令牌）——按 plan WP-C 口径（B1） | ✅ |
| AC-9 | canary 关 = 零变化 | test_canary_off_zero_change（:349-353）+ **T4 真实链**（零 canary 子串） | ✅ |
| AC-10 | record_canary 参数化 INSERT / 无 id 不落 / 建表幂等 | TestRecordCanary.test_insert_params（:219-227，SQL 与参数逐键断言）+ test_ingest_no_id_skips_record（:356-360）+ 建表幂等（DDL 全 IF NOT EXISTS 结构性幂等；本轮 3 次 uvicorn 启停均过 init_db 无报错）+ T1 真实映射行 | ✅ |
| AC-11 | 泄漏检测 warning + span | test_hit_warns_and_records_span（:236-251，mock _spawn_insert 四要素）+ **T2 真实链**（warning 原文 + span name/kind/status/decision 四要素） | ✅ |
| AC-12 | 未登记令牌零告警零 span | test_unregistered_token_silent（:253-266）+ **T2 阴性真实链**（delta=0） | ✅ |
| AC-13 | chat 双路径接线 + 开关关零调用 | TestLeakWiring 4 项（engine on/off :404-411 + stream on/off :439-447，mock 断言调用次数随开关变化） | ✅ |
| AC-14 | 审查收清洗文本 / 递归取原始 | test_review_and_ingest_receive_cleaned（:299-306）+ test_extract_links_uses_original_content（:363-366） | ✅ |
| AC-15 | eval 脚本可运行 + 落库 | **T3 实跑**：控制台双模式汇总 + eval_runs id=61（eval_type='injection'） | ✅ |
| AC-16 | 用例集 22/4/8 版本化 | CLI 复跑 `22 4 8` 逐字 | ✅ |
| AC-17 | strip 载体族拦截 1.0 | T3 scores.strip.interception_rate=1.0 + per_question 抽查（hu-01 含载体+指令族 findings） | ✅ |
| AC-18 | strip FP=0；strict 全拦 1.0 | T3 六指标逐值对账：strip FP=0；strict 22/22=1.0、FP=1（benign-03，设计内归因注记在控制台与 per_question 双落）——"偏离必须如实落库归因"条款已满足 | ✅ |
| AC-19 | sanitized 计数 + details sanitize 键 | 单测双向断言（:305-306/326-327）+ **T1 真实链 sanitized=1** / **T4 真实链 sanitized=0**（日志 抓取批次完成行两次实证） | ✅ |
| AC-20 | 清洗后空内容 IngestError 降级 | **T1 真实链**（纯注释页 crawled=0/errors=1，日志"文档解析后无有效文本"warning，进程不崩、零新行）+ Reviewer 运行时探针；专项单测缺项见备忘 B2（非阻塞） | ✅ |
| AC-21 | 围栏教学文本 strict 不拒收 | test_code_fence_teaching_not_marked（:125-129）+ T3 strict FP 仅 benign-03（benign-01 围栏非 FP） | ✅ |
| AC-22 | 无行边界退化 | test_embed_no_line_boundary_appends（:151-154，1000 字符无换行文末补插不抛异常）；诚实边界（子块切断令牌漏检/父块覆盖）为 plan 风险 2 申报语义 | ✅ |
| AC-23 | 非法 mode 被拒 | CLI 复跑 pydantic literal_error | ✅ |
| AC-24 | record_canary DB 异常 fail-open | test_db_error_fail_open（:228-231） | ✅ |
| AC-25 | check_canary_leak DB 异常 fail-open | test_db_error_fail_open（:268-271） | ✅ |
| AC-26 | sanitize 异常 fail-open | test_sanitize_exception_fail_open（:330-337，注入 RuntimeError 原文继续） | ✅ |

### 5.2 边界与异常、非功能验收

| AC | 要求 | 证据 | 签署 |
|---|---|---|---|
| AC-27 | 存量零回归 | 全量 **1730/0/3**（=1690+40，零新增失败）；受影响存量分组交叉印证 730/3 + 603 | ✅ |
| AC-28 | 红线零 diff | git diff --stat 13 文件全空；database.py numstat +32/**0 删除**（既有四段 DDL 一字未改）；git status knowledge-interview/backend/frontend/interview-admin 无输出 | ✅ |
| AC-29 | 生产 AST ≤200 | 逐文件复算 sanitize 101/crawler 494/engine 533/main 684/config 127/database 219/eval 73（与 changelog §三逐值一致），代码句合计 **195 ≤ 200** | ✅ |
| AC-30 | 函数 ≤50 语句、0 print、无裸 except | grep print 计数 0；except 仅 2 处均 `except Exception as e` + warning；函数级复算最大 20 语句（Reviewer §8 与本轮 AST 口径一致） | ✅ |
| AC-31 | 存量测试零改动 | git numstat tests/ 仅 conftest.py +16/**0** + test_sanitize.py 新文件，无其他测试文件出现 | ✅ |
| AC-32 | 上传路径零漂移 | 代码级（main.py:1073 upload 端点直调 ingest_document）+ **T5 真实链**（注释/脚本原样、无 canary、零映射行、source=txt_upload:） | ✅ |
| AC-33 | 双关=存量逐字 | AC-2 结构 + **T4 真实环境终证** + test_canary_off_zero_change | ✅ |

## 6. 环境申报（如实，全部已还原）

1. **.env：全程零改动**（未采用 AC §5 建议的 .env 临时改写方案，改用 pydantic-settings 进程环境变量注入 PW_CRAWL_ENABLED / PW_CRAWL_SANITIZE_MODE / PW_CRAWL_SANITIZE_ENABLED / PW_CRAWL_CANARY_ENABLED / PW_CRAWL_INTERVAL_MINUTES=600，随 uvicorn 进程生灭，无需备份还原）。
2. **数据库**：临时写入已全部 DELETE 还原——documents 17 行（源 LIKE '%e2e-086%'，17454-17470）、crawl_canaries 3 行、eval_runs 1 行（id=61）、request_spans 13 行（本会话 4 次 /ai/crawl/run + 1 次 upload + /docs 就绪探测 + T2 探针 3 行）；source_configs DELETE 探针行 id=5、UPDATE id=1 还原 enabled=true。还原核验：documents=16365 / crawl_canaries=0 / eval_injection=0 / source_configs 仅原 FastAPI 行（逐字段一致）——**与测试前基线逐表一致**。
3. **文件系统**：投毒页目录 ai_service/.e2e-086-www/（4 投毒页 + 1 上传样本 + 生成器/探针脚本）整目录删除；uploads\ 下 5 个探针原件文件删除。
4. **进程**：uvicorn（strip/strict/双关 3 次启停，:8010）与 http.server（:8899）全部停止，netstat 双端口零监听。
5. **网络出域**：零外网爬取——抓取目标全部为 localhost:8899；既有外网源（fastapi.tiangolo.com）测试期间钉 enabled=false 且已还原；ingest 链内嵌的 ModelScope embedding API 调用为存量行为（与 086 前一致）。
6. **真实链 LLM/审查依赖**：reflector/HHEM 调用按 fail-open 语义失败降级（审查链非本模块验收面），不影响 sanitize/canary 对账断言。

## 7. Tester 新发现

1. **T1 测试设计教训（非缺陷）**：AC-20"纯 HTML 注释页"若带完整 HTML 外壳（DOCTYPE/head/body/title），sanitize 三族剥离后仍余标签文本，ingest 层 HTML 转文本提取出标题照常入库——与 086 前行为一致，非缺陷；但复现 AC-20 必须使用无任何标签的纯注释内容。
2. **T2 探针脚本的上下文要求（非缺陷）**：check_canary_leak 在无观测上下文时 span 静默跳过（tracing.record_span 设计：非请求链路零落库），一次性探针必须先 init_request + begin_request；裸 asyncio.run 直调不落 span 是**设计内**行为，后续对账者勿误判。
3. **strict 真实链归因注记**：真实审查器（reflector sufficient=False）对投毒页同样拒收，"review=approved 仍强制 rejected"的反事实由单测覆盖；真实链与单测互补，无矛盾。
4. 无新增缺陷；无收集警告；无环境性失败。

## 8. 验收结论

- **结论：✅ 通过（PASS）——module-086 注入防护实测验收通过，建议编排者收口（版本 v0.86.0）**
- 全量回归 **1730 passed / 0 failed / 3 skipped**（=1690 基线 + 40 新增，零新增失败）；受影响存量 730/3 + 603；py_compile 7 文件 OK。
- **T1-T6 真实对账全部通过**：T1 strip 载体剥离/canary 嵌入映射/strict 拒收 + AC-20 降级；T2 真实 canary 泄漏检测（阴性对照零增量 + span 四要素）；T3 eval 六指标逐值落库一致（strict FP=1 设计内归因）；T4 双开关关零行为漂移；T5 上传零漂移；T6 全量清理还原（逐表对账回基线 + 清理后全量复跑 1730/0/3）。
- **AC-1~33 全项签署通过**（33/33 ✅）；Reviewer 2 LOW 属实非阻塞（留待下轮顺带）、4 备忘全部独立核实成立。
- 红线 13 文件 + 3 目录零触碰实证；.env 零改动；变更面 numstat 全部落在申报范围内。
