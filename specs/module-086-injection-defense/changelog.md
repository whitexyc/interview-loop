# 变更记录 — Module-086: 注入防护实测（投毒用例集 → 入口 sanitize + canary → 量化拦截率）

> Developer: 2026-09-06（子 agent 按模块循环派发）| 依据：plan.md v1（WP-A~G + 8 大裁定，编排者已裁定 3 项待澄清：①信任分级移出后续模块承接 ②agent 路径泄漏检测留收口后小模块 ③生产默认档=strip）+ acceptance-criteria.md（AC-1~33）
> 基线：module-089 闭环后全量 **1690 passed / 0 failed / 3 skipped（2026-09-06）**——红线：**新增 0 失败、存量测试零改动、observability.py / 既有四段 DDL / router.py / tool_registry.py / mcp_server.py / requirements.txt / tracing.py / document_cleaner|ingest|parser / agent/react.py / knowledge-interview 整目录 零 diff**
> 活跃代码库 = ai_service/（plan §0.0 陷阱已核验：全程未触碰 knowledge-interview/rag-service 旧镜像）

---

## 一、实现总览（注入防护链路）

```
入口侧（爬虫，_crawl_page_and_store，裁定 1 顺序）：
  fetch_page（原始 HTML 文本，真注入面）
    → sanitize_crawl_content(content, mode)   ← 审查节点【之前】，防审查器自身被投毒
        载体族直接剥离：html_comment / script_style / hidden_unicode（零宽/双向控制字符）
        指令族只记 findings：instruction_override / exfiltration / destructive_tool / hidden_text
          （指令扫描在载体剥离后 + 代码围栏 ```...``` 掩码后的文本上做——围栏内教学文本零误伤，AC-21）
        strict 档：任一指令族命中 → rejected=True → review_status 强制 "rejected"（075 契约仍入库）
    → _review_content(清洗后文本)              ← 审查看到干净文本
    → strict rejected 合并（在 approved/rejected 计数分支之前，rejected 优先）
    → embed_canary(清洗文本, [canary:8hex])    ← 审查【之后】，HHEM 分数不被 canary 噪声污染
        ~250 字符间隔行边界插入；短文/无行边界文末补插；空文本不插（保 AC-20 IngestError 路径）
    → ingest_document（上传路径不经此链，零回归）
    → record_canary(doc_id, canary, url)       ← crawl_canaries 新表映射（ingest 有 id 才落行）
    → _extract_links 仍取原始 content          ← 递归行为零变化

输出侧（chat 两主路径，裁定 4）：
  engine.chat knowledge 路径 generate_answer 之后 → if crawl_canary_enabled: check_canary_leak(answer)
  main._stream_generate_verify answer_text 组装后 → 同构 1 次
  命中已登记 canary → logger.warning + record_span("canary_leak","security",decision="doc_id=… source=…",status="blocked")
  （走 module-088 既有通道零 schema 改动；未登记令牌静默跳过；DB 异常 fail-open）

量化侧（裁定 5/7，确定性零 LLM 零网络）：
  eval/benchmarks/eval_injection.py 对 22 恶意 + 4 良性用例跑 sanitize 管线（strip/strict 双轮）
  → 拦截率/误伤率落 eval_runs(eval_type='injection') + 控制台报告
```

## 二、WP 实现说明

### WP-A src/config.py（AC-1/23，AST +3）
- 3 字段紧邻 crawl_* 块之后：`crawl_sanitize_enabled: bool = True`、`crawl_sanitize_mode: Literal["detect","strip","strict"] = "strip"`、`crawl_canary_enabled: bool = True`。env 唯一口径 = PW_CRAWL_SANITIZE_ENABLED / PW_CRAWL_SANITIZE_MODE / PW_CRAWL_CANARY_ENABLED（088 PW_TRACE_SPANS 误名教训：注释写明全名，禁简称）。安全特性默认开（裁定 8，编排者确认 strip）；整体闸 crawl_enabled 默认 false 兜住；conftest 钉双 false 保证存量零漂移。

### WP-B src/database.py（AC-10，AST +10）
- `CRAWL_CANARIES_DDL` 常量（CREATE TABLE IF NOT EXISTS + UNIQUE INDEX uq_crawl_canaries_canary + 4 条 COMMENT，幂等拆分执行）+ `ensure_crawl_canaries_table()` + init_db 挂接 2 行（挂 tasks 之后）。列：id/doc_id/canary/source_url/created_at。**无 JSONB 列**（天然规避 087 asyncpg dict 绑定坑）。既有 TASKS/REQUEST_LOGS/TOOL_CALL_LOGS/REQUEST_SPANS 四段 DDL 一字不改（红线，git diff 实证空）。

### WP-C rag/crawl/sanitize.py 新建（AC-3/5/6/8/10/11/12/24/25，AST 91 代码句）
- `SanitizeResult` dataclass：cleaned_text / findings（{category, action, count, sample}，样例截 80）/ rejected。
- 正则全线性（单层 `.*?` + DOTALL，禁嵌套量词防回溯爆炸，plan WP-C 约束）；7 类目锁定 plan §7 命名；指令族中英双语 10 式（裁定 2 给定 6 组示例类目内微调措辞）。
- `sanitize_crawl_content(content, mode)`：detect 只扫不改（载体扫原文、指令扫围栏掩码后原文）；strip/strict 载体三正则 sub 剥离 → 指令族在**剥离后 + 围栏掩码后**文本扫描 → strict 且指令族命中 rejected=True。
- canary 四原语：`new_canary()`（uuid4 hex[:8]）/ `embed_canary()`（行累积越 `_CANARY_INTERVAL_CHARS=250` 在行边界插 `[canary:xxx]`，短文末尾补 1）/ `find_canaries()`（`canary:([0-9a-f]{8})` 锁定正则）/ `record_canary()`（raw 参数化 INSERT + commit，全异常 warning 不上抛）。
- `check_canary_leak(content)`：find_canaries → 去重保序 → 逐个 SELECT crawl_canaries → 命中 warning + record_span（canary_leak/security/blocked，decision 以 doc_id= 开头）；未登记静默；DB 异常 fail-open。**同步 await 直插不经 create_task**（调用处在 async 链内，规避引用池坑，plan WP-C 设计）。

### WP-D rag/crawl/crawler.py（AC-2/6/7/14/19/20/26/33，AST +18）
- `_crawl_page_and_store`：sanitize 挂 fetch 后、review 的 try **之前**（独立 fail-open try/except → warning → sanitize_result=None 原文路径，AC-26；审查抛异常时 sanitize 结果**不回退**——已清洗文本仍入何处语义不破坏）；rejected 合并在 `review_status = str(review)` 之后、计数分支之前；`summary.sanitized` 在 findings 非空时 +1；details 条目条件追加 `sanitize` 键（无 findings 零漂移）；canary 在 ingest try 内（`canary and content_for_review.strip()` 才嵌，空文本不嵌保 AC-20）；ingest 有 id 才 `await record_canary`。
- `CrawlSummary.sanitized: int = 0` 字段 +1；run_crawl 收尾日志加 sanitized=%d（改既有语句 0 新增）。
- `_extract_links(result.content, …)` 逐字未动（递归零变化，AC-14 有专测）。

### WP-E rag/engine.py + main.py（AC-11/13/27，AST +6）
- engine.py：import 1 行 + chat() knowledge 路径 `observability.timing("generate", …)` 之后 `if settings.crawl_canary_enabled: await check_canary_leak(answer)`（casual/无文档兜底路径不接，裁定 4）。
- main.py：import 1 行 + `_stream_generate_verify` 的 `answer_text = "".join(answer_parts)` 之后同构 1 次。
- 开关检查在**调用点**（AC-13 "开关关零调用" + mock 断言调用次数随开关变化的口径），check_canary_leak 自身不含开关判断。

### WP-F eval/datasets/injection_cases.json + eval/benchmarks/eval_injection.py（AC-15/16/17/18，脚本 AST 68 代码句，计入生产口径；JSON 数据不计）
- 用例集：版本化 `{"version": "2026-09-06", "cases": […]}`，22 恶意（hidden_unicode×4 / html_comment×4 / script_style×2 / hidden_text×3 / instruction_override×4 中英各半 / exfiltration×2 / destructive_tool×3）+ 4 良性（①代码围栏教学 ②script 标签科普 ③CSS display:none 讲解【已知语义：strict FP】④纯正常中文段落）= 26 条 8 类目，AC-16 验证命令实测输出 `22 4 8`。零宽字符用 `\uXXXX` 转义书写（可审查、JSON 合法）。
- 脚本：load_cases 结构校验（缺 version/cases、字段缺失、数量 <20/<4 均 ValueError 退出）→ evaluate 双模式（裁定 5 口径：载体=清洗后模式不再命中；指令 strip=findings/strict=rejected；良性 FP=strict rejected）→ scores 两模式六指标 + per_question 26 行（每用例 1 行带双模式明细，T3 对账口径）→ save_eval_run(eval_type='injection')（复用 golden_retrieval 通道）+ 控制台汇总表 + strict FP 归因注记。
- 脚本头部 `sys.path.insert(parents[2])`（+2 句）支持 AC-15 直接执行命令口径（`python -m eval.benchmarks.eval_injection` 亦兼容）。

### WP-G tests/conftest.py + tests/crawl/test_sanitize.py（测试不计生产行数）
- conftest 纯追加 `default_crawl_sanitize_disabled` autouse（钉 crawl_sanitize_enabled=False + crawl_canary_enabled=False，对齐 056/058/087/088/089 模式；+16 行 insertions 0 deletions，既有 fixture 一字未动）。
- tests/crawl/test_sanitize.py **40 项**（plan 预估 ~20，超出部分为逐类展开与 AC 边界）：三态矩阵 6 / 载体剥离逐类 3 / 指令族标记逐类 6 / canary 6 / config 2 / record_canary 2 / check_canary_leak 3（命中 span 断言 mock `_spawn_insert` 对齐 test_tracing）/ 爬虫接线 9（mock fetch/review/ingest/record_canary 全链）/ 输出侧接线 4（engine.chat 与 _stream_generate_verify 各 on/off，AC-13）。全 hermetic 零 DB 零网络。

## 三、行数统计（铁律 2；官方口径 = AST 可执行语句不含注释/docstring，plan §3）

| WP | 文件 | AST Δ（代码句） |
|----|------|----------------|
| WP-A | src/config.py（改） | +3 |
| WP-B | src/database.py（改） | +9（raw +10，含 1 条函数 docstring） |
| WP-C | rag/crawl/sanitize.py（新） | 91（raw 101，docstring 10） |
| WP-D | rag/crawl/crawler.py（改） | +18 |
| WP-E | rag/engine.py + main.py（改） | +6（plan 预估 +5，开关检查在调用点各 2 句 + 2 import，见偏离 3） |
| WP-F | eval/benchmarks/eval_injection.py（新） | 68（raw 73，docstring 5；**计入生产口径**） |
| **合计** | | **195 ≤ 200 ✓**（raw ast.stmt 口径 211；plan 预估 ~185，缓冲内） |

- 用例集 JSON 不计入（裁定 7，golden.json 先例）；测试 40 项 + conftest +16 豁免。
- AC-29 验证命令（raw 整文件含 docstring）实测：sanitize 101 / crawler 494 / engine 533 / main 684 / config 127 / database 219 / eval 73；crawler/engine/main/config/database 基线（改动前实测）476/530/681/124/209。
- 新增函数最长 `embed_canary` 15 语句 ≤ 50（AC-30）；sanitize.py 0 print、except 全部带类型 + warning（AC-30）。

## 四、自测结果（2026-09-06，Developer 自测；全量回归归 Tester）

| 命令（cwd=ai_service） | 结果 |
|------------------------|------|
| `.venv/Scripts/python.exe -m pytest tests/crawl/test_sanitize.py -q` | **40 passed**（15.87s） |
| `.venv/Scripts/python.exe -m pytest tests/crawl/ tests/api/ tests/core/ -q` | **730 passed / 3 skipped**（33.01s，3 skip 对齐基线） |
| `.venv/Scripts/python.exe -m pytest tests/agent/ tests/memory/ -q` | **603 passed**（83.95s，engine.py 受影响面加保险） |
| `.venv/Scripts/python.exe -m py_compile rag/crawl/sanitize.py rag/crawl/crawler.py rag/engine.py main.py src/config.py src/database.py eval/benchmarks/eval_injection.py` | COMPILE_OK（exit 0） |
| `.venv/Scripts/python.exe -c "from src.config import settings; print(...)"` | `True strip True`（AC-1 逐字） |
| `.venv/Scripts/python.exe -c "from src.config import Settings; Settings(crawl_sanitize_mode='aggressive')"` | ValidationError exit 1（AC-23） |
| `.venv/Scripts/python.exe -c "import json;d=json.load(open('eval/datasets/injection_cases.json',encoding='utf-8'));…"` | `22 4 8`（AC-16 逐字） |
| `.venv/Scripts/python.exe eval/benchmarks/eval_injection.py` | strip：22/22 拦截率 **1.0** 误伤 **0**；strict：22/22 **1.0** 误伤 **1**（benign-03 归因注记）；已落库 eval_runs id=60（AC-15/17/18） |
| 红线 git diff（observability/router/tool_registry/mcp_server/requirements/tracing/react/langgraph_react/document_cleaner|ingest|parser/tasks.py/knowledge-interview/backend/frontend/interview-admin） | **全空**（AC-28）；tests/ 仅 conftest +16 纯新增（AC-31） |
| 真实 PG 探针（用后清） | T3 式对账：eval_runs id=60 scores 与控制台逐值一致 + per_question=26 行 → DELETE 还原（injection 行归零）；`ensure_crawl_canaries_table()` 连跑 2 次幂等不报错、crawl_canaries 0 行 |

## 五、关键设计说明（决策 + 原因）

1. **sanitize 位于 review 的 try 之外**（偏离 plan 步骤顺序的一次修正）：首版把 sanitize 放进了审查 try 块，归因发现审查抛异常时会把**已清洗文本回退成原始投毒文本**入库（fail-open 反向放大攻击面）——修正为 sanitize 独立 try/except、review 独立 try/except，两 fail-open 互不吞没。
2. **指令族扫描目标 = 载体剥离后 + 围栏掩码后文本**：findings 反映"将入库文本的残留风险"；载体族计数取自原文（剥离对象）。代码围栏掩码（```` ```.*?(\Z|``` ````）只作用于扫描副本，输出内容零改动——同时满足 AC-21（围栏教学文本 strict 不拒收）与裁定 2"防误伤"动机（详见偏离 1）。
3. **canary 空文本不嵌**（`canary and content_for_review.strip()`）：否则纯 HTML 注释页清洗后为空、令牌会把空内容"救活"成垃圾文档，破坏 AC-20 的既有 IngestError("无有效文本") 降级路径；开关双关时行为逐字不变。
4. **诚实边界如实申报**：strict 模式良性 FP=1（benign-03 "display: none 的用法讲解" 字面命中 hidden_text）系 plan WP-F ③ 明文预判的设计结果，eval 控制台注记归因 + 落库 per_question 携带 findings 证据，未调用例凑分（裁定 5"偏离须如实落库上报并归因"）。strip（默认档）FP=0、拦截率 1.0。
5. **canary 间隔的诚实边界**：行累积越过 250 即在当前行边界插入，令牌间距 ∈ [250, 250+行长)；行边界不可得时（无换行长文）退化为文末补插（AC-22 明示允许）。父块 ≤4000 字符必含多个令牌，子块检测漏检属概率性非系统性（plan 风险 2）。
6. **消费方开关在调用点**：AC-13 验证口径"开关关零调用 + mock 断言次数随开关变化"要求调用点守卫（若开关在 check_canary_leak 内部，mock 后无法断言零调用）。

## 六、与 plan 的偏离清单（如实申报）

1. **代码围栏掩码（+3 语句，WP-C 函数规格未写但 AC 硬性要求）**：AC-21 要求"围栏内 ignore previous instructions 在 strict 下 rejected=False"，而 plan WP-C 的 strict 定义是"任一指令族命中 → rejected"，字面实现必然拒收围栏教学文本（正则按字面命中）→ AC-18"良性 FP=0"与 AC-21 双双无法达成。缺此掩码时 strict FP 至少 2（良性①围栏 + ③CSS）。按"AC 是验收硬标准、裁定 2 动机（防误伤教学文本）同向"裁决补齐，仅影响指令族**扫描范围**（内容仍零改动）。
2. **canary 空文本不嵌**（+0 语句，条件表达式加 `content_for_review.strip()`）：plan WP-D 第 5 步字面为 `embed_canary(…) if canary else …`，未考虑纯注释页清洗后为空的退化场景会破坏 AC-20 既有降级路径。
3. **WP-E 实际 +6（plan 预估 +5）**：两处接线点各为 `if 开关 + await 调用` 2 句（plan 计数口径按 1 句/点估算）；开关必须在调用点的原因见关键设计 6。
4. **WP-C 实际 91（plan 预估 ~88）/ WP-D 实际 +18（plan 预估 +12）**： crawler 多出的 6 句 = sanitize 独立 fail-open 结构（首版回退缺陷修正）+ sanitize_note 条件构造；总计 195 ≤ 200 在预算内，无裁剪需求。
5. **eval 脚本 sys.path 引导（+2 句）**：AC-15 验证命令为直接脚本执行（`python.exe eval/benchmarks/eval_injection.py`），无引导时 `No module named 'rag'` 实测报错；既有 eval 脚本均经 `python -m` 跑（docstring 口径），本脚本双口径兼容。
6. **plan 待澄清 3 项按编排者缺省执行**：信任分级未做（source_configs 零改动）；agent/react.py 泄漏检测未接（红线零 diff 实证）；生产默认档 strip（config 默认值）。

## 七、遗留与移交（Reviewer/Tester 注意）

1. **Tester T1-T6 真实对账**照 AC §5 执行；本模块真实 PG 探针已清零（eval_runs injection 行 0、crawl_canaries 0 行），T6 清理还原基线时无本模块残留。
2. **全量回归预期 1730 = 1690 + 40** / 0 failed / 3 skipped（新增 test_sanitize.py 40 项）。
3. strict 档 FP=1（benign-03）为设计内已知语义，非缺陷；若 Tester 对账 strict FP 期望 0，以 AC-18 括号注记（"代码围栏教学文本与正常段落 strict 下 rejected=False"）+ 裁定 5 归因条款为准。
4. git 提交按模块循环惯例在模块闭环时由编排者统一执行（087/088/089 先例），本阶段不建分支不提交。

## 八、变更记录

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| v1 | 2026-09-06 | 首版实现（WP-A~G 全量 + 40 项测试 + eval 拦截率 1.0/0 落库验证 + 6 项偏离申报） | Developer |
