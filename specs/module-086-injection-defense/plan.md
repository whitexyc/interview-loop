# 开发计划 — Module-086: 注入防护实测（知识库投毒用例集 → 入口 sanitize + canary → 量化拦截率）

> Planner 产出 | 2026-09-06（重派首规划，v1）
> 上游依据：`knowledge-interview/docs/AGENT-GROWTH-ROADMAP.md` 阶段 C module-086 行（验收方向：**用例集 ≥20 条，拦截率可量化上报**）+ `knowledge-interview/docs/缺陷补全任务规划-2026-08-30.md` **T4（P1）** 入库纵深防御
> 本模块是 roadmap 阶段 C（安全）唯一模块；A（083/084）/B（085/088）/D（087/089）已闭环

---

## 0. Planner 已探明事实（Developer 勿重复调查）

### 0.0 活跃代码库（重要陷阱，先读）

- **活跃代码库 = `<repo-root>\interview-personal\ai_service\`**。`<repo-root>\knowledge-interview\rag-service\` 是**冻结在 module-083 时代的旧镜像**（无 src/tracing.py / src/tasks.py / src/dashboard.py，git log 停在 module-083），**严禁改动**。本 plan 所有路径均相对 `ai_service/`。
- specs/记忆/上游 docs 位置不变：specs 与 memory 在 interview-personal；roadmap/T4 任务书在 knowledge-interview/docs/（只读）。

### 0.1 爬虫管线（module-075/076/077/078 遗产，sanitize 挂点）

- `rag/crawl/crawler.py`（794 行）：核心链 `_crawl_page_and_store(url, summary)`（L533-580）= `fetch_page`（httpx，UA/代理/重试）→ `_review_content`（审查节点）→ `ingest_document`（入库）→ `_extract_links`（递归链接，取自**原始** result.content）。
- 审查节点 `_review_content`（L311-357）：策略三档 `settings.crawl_review_policy` ∈ fail-open（默认）/lenient/strict；Step1 reflector 充分性（content[:3000]）→ Step2 HHEM 质量分（content[:2000]，阈值 0.3/strict 0.45）→ Step3 矛盾检测（fail-open 仅记录）。**module-075 契约：rejected 仍入库**（标记 review_status，非物理删除）。
- `CrawlSummary`（L81-89）字段 crawled/approved/rejected/conflict_count/skipped/errors/details——本模块新增 `sanitized` 计数。
- 爬虫入库的文档 `filename=crawl_xxx.txt`、`source=f"crawl:{url}"`、`review_status/review_score` 透传。
- **坑（探明）**：`_crawl_filename` 生成 `.txt` 后缀 → `document_parser.parse_document` 对 txt 纯文本解码（L431-434），`.html` 后缀才走 AnyDoc 转 Markdown。**因此爬虫抓回的页面以原始 HTML 文本形态入库**——HTML 注释指令、`<script>/<style>` 块、隐藏文本全部原样进知识库（真实注入面）；零宽字符是唯一例外（见 0.2）。

### 0.2 清洗管线（module-064 遗产，与 sanitize 的重叠与分工）

- `rag/retrieval/document_cleaner.py`（447 行）：`clean()` 五步清洗 + `normalize()` 无损归一化。**已探明：两者都对全区域剥 Unicode C 类字符**（`_strip_control` 保留 \n\t、其余 category 以 C 开头的一律删；零宽空格 U+200B/连字 U+00AD/BOM U+FEFF 等属 Cf → **零宽字符类在现有 ingest 管线内已被剥离**）。这层是"清洗质量"语义不是"安全"语义，但效果上构成第一道兜底。
- "先保护再清洗"⟦N⟧占位符哲学（U+27E6/27E7，代码/数学/表格/URL 白名单）——sanitize 层**不复用**该机制：sanitize 在 ingest_document **之前**、作用于原始抓取文本（尚未进清洗层），⟦N⟧ 保护是 clean() 内部机制，两者层级不同不冲突。
- `rag/retrieval/document_ingest.py`（214 行）：`ingest_document` 是**上传与爬虫共用入口**（`/ai/rag/documents/upload` 与 crawler 都调它）→ **sanitize 必须挂 crawler 调用侧而非 ingest 内部**，否则上传路径行为被改（存量回归风险）。
- module-064 三文件（document_cleaner / document_ingest / document_parser）本模块 **零 diff**（红线，见 §6）。

### 0.3 观测通道（module-088 遗产，拦截事件出口）

- `src/tracing.py`（232 行）：`record_span(name, kind, decision="", status="ok", duration_ms=0)`——开关 `trace_spans_enabled` 首行短路；无 trace 上下文（评测脚本/后台抓取任务）静默跳过；kind 为自由文本（现用 request/tool/decision/retrieval，**新增 "security" 值不改 schema**）；`status` 已有 "blocked" 三态语义（083/089 先例）。全异常 fail-open。
- `request_spans` 表 DDL 在 `src/database.py` L154——**既有 DDL 一字不改**（红线）；新表按 087 幂等 DDL 先例可新增（本模块新增 `crawl_canaries` 表）。

### 0.4 量化落库通道（module-019/066 先例）

- `eval_runs` 表（DDL 在 `eval/golden/golden_retrieval.py` L60-75，非 database.py）：`eval_type VARCHAR(20)`（**'injection' 9 字符放得下**）、`config_snapshot/scores/per_question JSONB`。`save_eval_run()`（L217+）+ `ensure_eval_runs_table()`（写库前自愈建表）现成可用。
- eval 脚本先例：`eval/golden/evaluate.py`、`eval/benchmarks/*`——asyncio.run(main()) + 控制台输出 + 落库。**行数口径先例：module-066 eval 脚本计入生产口径**（本模块沿用，见 §3 裁定）。
- 环境口径：pytest 在 `ai_service/` 目录跑，解释器 `.venv/Scripts/python.exe`。

### 0.5 测试与基建先例（照抄模式）

- conftest 钉桩惯例（tests/conftest.py，13 个 autouse fixture）：新开关 autouse 钉保守值（存量行为零漂移），新测试体内显式 setattr 开启。本模块钉 `crawl_sanitize_enabled=False` + `crawl_canary_enabled=False`。
- 定向测试落位：`tests/crawl/`（test_crawler.py / test_review_enhancement.py 等 7 文件既有）→ 新增 `tests/crawl/test_sanitize.py`。
- DB 访问先例：raw `text()` + 参数绑定（tracing._insert_span / crawler._conflict_candidates）；fire-and-forget 需任务引用池防 GC（tracing._pending_tasks 先例——**本模块 record_canary 用同步 await 直插，不经 create_task**，见 WP-C 设计，规避该坑）。
- JSONB 绑定坑（module-087 Tester 发现-1）：raw text() 绑 JSONB 列必须传 JSON 字符串——本模块新表**无 JSONB 列**，天然规避。
- 全量测试基线：**1690 passed / 0 failed / 3 skipped（2026-09-06，module-089 收口后）**。红线：新增 0 失败、存量测试零改动。

---

## 1. 关键决策（Planner 裁定）

**裁定 1 — sanitize 挂点与顺序**：挂 `crawler._crawl_page_and_store`，顺序 = fetch → **sanitize** → review → **canary 嵌入** → ingest → canary 映射落库。sanitize 在审查节点**之前**（审查看到干净文本，防审查器自身被投毒；sanitize 确定性规则零成本）；canary 在审查**之后**（审查输入不含 canary 噪声，HHEM 分数不被污染）。`_extract_links` 仍取原始 content（递归行为零变化）。

**裁定 2 — 处置三态语义**：规则按类目分两族、由 `crawl_sanitize_mode` 三档驱动：
- **载体族（strip）**：`html_comment`（`<!--…-->`）、`script_style`（`<script>/<style>` 整块）、`hidden_unicode`（零宽/双向控制字符）→ **直接剥离**（对可见正文零损伤：注释/脚本/不可见字符本就非正文）。
- **指令族（mark）**：`instruction_override`（忽略/无视既有指令）、`exfiltration`（数据外传指令）、`destructive_tool`（破坏性工具指令）、`hidden_text`（CSS 隐藏文本特征，仅检测不拆标签——正则拆任意标签有误伤内容风险）→ **只记 findings 不改内容**（防误伤代码围栏内教学文本；这是"标记"态）。
- 模式：`detect`（只记 findings，内容零改动——评估/逃生口）/ `strip`（默认：载体剥离 + 指令标记）/ `strict`（strip 全部 + **任一指令族命中 → 该页 review_status 强制 "rejected"**）。"拒绝入库"语义 = 对齐 module-075 既有 rejected 契约（仍入库但标记 rejected + 汇总计数），**不做物理删除**（与 078 审查语义一致，避免误杀不可逆）。

**裁定 3 — canary 形态**：每篇爬虫文档生成唯一 8-hex 令牌（`uuid4().hex[:8]`），以 `[canary:xxxxxxxx]` **纯 ASCII 内联形态**按 ~250 字符间隔（命名常量 `_CANARY_INTERVAL_CHARS`，子块 ~300 字符 → 绝大多数子块携带 ≥1 个）重复插入清洗后文本的行边界处。选型理由：纯 ASCII 对 NFKC/清洗/分块全稳定；短令牌检索噪声可控；重复插入保证父块（≤4000 字符，返回给 LLM 的单元）几乎必含 canary。映射行（doc_id/canary/source_url）在 ingest 返回 doc_id 后 INSERT 新表 `crawl_canaries`。

**裁定 4 — 输出侧泄漏检测范围（v1）**：`check_canary_leak(answer)` 接线 **两处 chat 主路径**——`rag/engine.py chat()` knowledge 路径（answer 生成后）+ `main.py _stream_generate_verify`（`answer_text` 变量既有，L588，加 1 次调用）。命中已登记 canary → `logger.warning` + `tracing.record_span("canary_leak", "security", decision=f"doc_id=… source=…", status="blocked")`。**agent/react.py 路径本模块不接**（行数预算外，见 §8 待澄清 ②）。模型复述 canary 具概率性——真实对账用**真实 canary 值走真实检测+落库链**（AC §5 T2，诚实边界）。

**裁定 5 — 拦截率口径**：拦截判定逐用例确定性计算（纯管线、零 LLM 零网络）：
- 载体族用例：intercepted = 清洗后文本中该载体模式不再命中；
- 指令族用例：strip/detect 模式 intercepted = findings 命中记录；strict 模式 intercepted = `rejected=True`；
- 良性用例（≥4 条，含代码围栏内 "ignore previous instructions" 教学文本）：false positive = strict 模式 `rejected=True`（strip 模式按构造不损可见正文，无 FP 面）；
- 指标 = `{poison_total, intercepted, interception_rate, benign_total, false_positives, false_positive_rate}` × strip/strict 两模式，逐用例明细进 `per_question`，落 `eval_runs(eval_type='injection')` + 控制台报告。
- 达标线（用例集与规则同源设计）：strict 拦截率 = 1.0、良性 FP = 0；**偏离须如实落库上报并归因，禁调分**。

**裁定 6 — 来源信任分级（T4 第③件）移出本模块**：编排者已授权可裁剪。理由：v1 核心（用例集+sanitize+canary+量化）预估 ~185 AST 已贴近 200 上限；信任分级需 source_configs 加列迁移 + 审查阈值联动 + 评测矩阵，独立成片才做得干净。列 §8 待澄清 ①（建议后续模块承接），本模块不做任何 source_configs 改动。

**裁定 7 — 行数口径**：eval 用例集 `eval/datasets/injection_cases.json` 是**数据非代码，不计入**生产行数（golden.json 先例）；`eval/benchmarks/eval_injection.py` 脚本**计入**（module-066 先例）。

**裁定 8 — 开关默认值**：`crawl_sanitize_enabled=True` + `mode="strip"` + `crawl_canary_enabled=True`（安全特性默认开；crawl_enabled 默认 false 整体闸住，实际影响面=生产爬虫开启时；conftest 钉 False 保证存量测试零漂移）。

---

## 2. WP 拆解（含 AC 映射）

> 每个 WP 列文件路径 + 预估 AST 行（不含注释/docstring/测试）。依赖：WP-A/B/C 无相互依赖可并行；WP-D 依赖 A/C；WP-E 依赖 A/C；WP-F 依赖 C；WP-G 随各 WP。

### WP-A：config 开关（src/config.py，~3 AST 行）

- 新增 3 字段（紧邻既有 crawl_* 块 L385-423 之后，注释写明 env 变量名与三态语义）：
  - `crawl_sanitize_enabled: bool = True`（PW_CRAWL_SANITIZE_ENABLED）
  - `crawl_sanitize_mode: Literal["detect", "strip", "strict"] = "strip"`（PW_CRAWL_SANITIZE_MODE；env 名 = PW_ + 字段名推导，**文档唯一口径，禁止在 .env 写简称**——088 PW_TRACE_SPANS 误名坑）
  - `crawl_canary_enabled: bool = True`（PW_CRAWL_CANARY_ENABLED）
- AC-1/23/28。

### WP-B：crawl_canaries 表（src/database.py，~12 AST 行）

- 新增 `CRAWL_CANARIES_DDL` 常量（照 087/088 幂等先例，`CREATE TABLE IF NOT EXISTS` + COMMENT 拆分执行）：
  ```sql
  CREATE TABLE IF NOT EXISTS crawl_canaries (
      id         BIGSERIAL   PRIMARY KEY,
      doc_id     BIGINT      NOT NULL,
      canary     VARCHAR(32) NOT NULL,
      source_url TEXT        NOT NULL DEFAULT '',
      created_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
  );
  CREATE UNIQUE INDEX IF NOT EXISTS uq_crawl_canaries_canary ON crawl_canaries (canary);
  ```
- `ensure_crawl_canaries_table()` + `init_db()` 挂接 1 行。**既有 DDL（TASKS/REQUEST_LOGS/TOOL_CALL_LOGS/REQUEST_SPANS）一字不改**。
- 无 JSONB 列（规避 087 asyncpg dict 绑定坑）。
- AC-10/28。

### WP-C：sanitize 模块（rag/crawl/sanitize.py 新建，~88 AST 行）

结构（Developer 照此实现，勿改口径）：
- `@dataclass SanitizeResult`: `cleaned_text: str`、`findings: list[dict]`（每项 `{category, action, count}`）、`rejected: bool = False`。
- 模块级正则常量（**线性时间模式，禁嵌套量词防回溯爆炸**）：
  - `_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)`
  - `_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)`
  - `_HIDDEN_UNICODE_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")`
  - `_HIDDEN_TEXT_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(px|em)?", re.IGNORECASE)`
  - `_INJECTION_PATTERNS: dict[str, list[re.Pattern]]`（指令族，IGNORECASE，中英双语，6 组示例——Developer 可微调措辞但类目名与语义锁定）：
    - `instruction_override`: `ignore\s+(all\s+)?(previous|prior|above|earlier)`、`(忽略|无视)\s*(之前|以上|上面|先前|前面)的(所有)?(指令|提示|设定|内容)`、`disregard\s+(all\s+)?(previous|prior|above)`
    - `instruction_override`: `(system\s*prompt|系统提示(词)?)\s*[:：]`、`你(现在|从现在起)是(新|真|真正的)?(系统|管理员|开发者)`、`<\|?(im_start|system)\|?>`
    - `exfiltration`: `(把|将)?(以下|上述|以上|这些|本页|本文)(内容|数据|信息|文本)(发送|上传|外传|提交)(到|至|给)`、`(send|post|upload|forward|exfiltrate)\s+(this|the|all)?\s*(data|content|text|information)\s+(to|via)\s+\S*(http|api|webhook)`
    - `destructive_tool`: `(删除|清空|销毁)(所有|全部|all)`、`(delete|drop|truncate|wipe)\s+(all|every)\s+(documents|records|data|rows)`、`(调用|执行|run|execute)\s*(删除|delete|drop)`
- `sanitize_crawl_content(text: str, mode: str) -> SanitizeResult`（~30）：detect → 只扫不改；strip/strict → 载体剥离（三正则 sub）+ 全类目扫描计数；strict 且指令族（含 hidden_text）命中 → `rejected=True`。findings 按 category 聚合计数，匹配样例截断 80 字符（防日志撑爆）。
- `new_canary() -> str`（~2）：`uuid4().hex[:8]`。
- `embed_canary(text: str, canary: str) -> str`（~8）：按行累积，每 ≥250 字符（`_CANARY_INTERVAL_CHARS`）在下一行边界追加 ` [canary:{canary}]`；末尾不足 250 亦补 1 个（保证短文也带标）。
- `_CANARY_TOKEN_RE = re.compile(r"canary:([0-9a-f]{8})")` + `find_canaries(text) -> list[str]`（~3）。
- `async def record_canary(doc_id: int, canary: str, source_url: str) -> None`（~10）：raw text() 参数化 INSERT + commit；**全异常 logger.warning 不上抛**（fail-open，不阻断入库）。同步 await 直插（调用处本就在 async 链内，不经 create_task，规避引用池坑）。
- `async def check_canary_leak(text: str) -> None`（~15）：find_canaries → 去重 → 逐个 `SELECT doc_id, source_url FROM crawl_canaries WHERE canary = :c LIMIT 1` → 命中：`logger.warning("canary 泄漏: doc_id=%s source=%s canary=%s", …)` + `tracing.record_span("canary_leak", "security", decision=f"doc_id={…} source={source_url[:100]}", status="blocked")`；未命中（历史残留/外部巧合文本）静默跳过；DB 异常 warning 不上抛。
- AC-3/4/5/6/8/10/11/12/24/25。

### WP-D：爬虫接线（rag/crawl/crawler.py，~12 AST 行）

`_crawl_page_and_store` 内改造（原 fetch→review→ingest 链保持，仅插入/替换变量）：
1. fetch 成功后：`sanitize_result = None`；`if settings.crawl_sanitize_enabled:` try/except Exception → warning → sanitize_result=None（fail-open 原文路径，~5 行含 except）；否则 `sanitize_crawl_content(result.content, settings.crawl_sanitize_mode)`。
2. `content_for_review = sanitize_result.cleaned_text if sanitize_result else result.content` → 传给 `_review_content`。
3. review 返回、`review_status = str(review)` 之后：`if sanitize_result and sanitize_result.rejected: review_status = "rejected"`（在既有 approved/rejected 计数分支之前，计数自然正确）。
4. `if sanitize_result and sanitize_result.findings: summary.sanitized += 1`；details 条目追加 `"sanitize": {"findings": sanitize_result.findings, "rejected": sanitize_result.rejected}`（无 findings 时该键省略，存量断言零漂移）。
5. ingest 前：`canary = new_canary() if settings.crawl_canary_enabled else ""`；`content_for_ingest = embed_canary(content_for_review, canary) if canary else content_for_review`；`ingest_document(data=content_for_ingest.encode("utf-8"), …)`。
6. ingest 成功且 `canary and ingest_result.get("id")` → `await record_canary(ingest_result["id"], canary, url)`。
7. `CrawlSummary` 增字段 `sanitized: int = 0`（1 行）。
- 注意：`_extract_links(result.content, …)` 保持原始 content（递归零变化）；`run_crawl` 收尾日志加 sanitized 计数（1 行）。
- AC-2/6/7/14/19/20。

### WP-E：输出侧接线（rag/engine.py + main.py，~5 AST 行）

- `rag/engine.py`：顶部 `from rag.crawl.sanitize import check_canary_leak`（1 行）；`chat()` knowledge 路径 `answer = await reflector.generate_answer(...)`（L518）之后 1 次调用：`if settings.crawl_canary_enabled: await check_canary_leak(answer)`。casual/无文档兜底路径不接（无检索即无 canary 泄漏面）。
- `main.py`：`_stream_generate_verify` 中 `answer_text = "".join(answer_parts)`（L588）之后同构 1 次调用（import 1 行）。
- 两处均 fail-open（check_canary_leak 自身不抛）。
- AC-11/13/27。

### WP-F：投毒用例集 + 量化脚本（eval/datasets/injection_cases.json 新建（数据不计行数）+ eval/benchmarks/eval_injection.py 新建，~65 AST 行，计入生产口径）

- 用例集 JSON（版本化，schema：`{"version": "2026-09-06", "cases": [{"id", "category", "kind": "poison"|"benign", "content"}]}`）：
  - **≥20 条恶意**，类目分布：hidden_unicode（零宽藏指令）×4、html_comment（HTML 注释指令）×4、script_style ×2、hidden_text（CSS 隐藏文本）×3、instruction_override（伪装系统提示/忽略指令，中英各半）×4、exfiltration（数据外泄指令）×2、destructive_tool（越权/破坏指令）×3 = 22 条；
  - **≥4 条良性对照**：①代码围栏内含 "ignore previous instructions" 教学文本 ②正常含 `<script>` 讨论的科普正文（strip 后可见正文不丢——脚本标签本身被剥属预期非 FP）③含 CSS 关键词的正常技术文档（不命中 hidden_text 语境，如 "display: none 的用法讲解"——该条会命中 hidden_text finding，strict 下 rejected 属**已知语义**，故此条设计为 strip 模式非 FP、strict 模式 FP 归因注释）④纯正常中文技术段落。
  - ③号条目诚实边界：hidden_text 正则按字面命中，strict 拒收该条**计入 FP 并在报告注记归因**（Planner 预判：这是三档设计里 strip 为默认档的原因）。
- 脚本 `eval_injection.py`（~65）：load JSON（结构校验）→ 逐用例跑 `sanitize_crawl_content(content, mode)`（mode ∈ strip/strict 两轮）→ 裁定 5 口径计算 → `save_eval_run(eval_type="injection", config_snapshot={"mode": "both", "case_version": …}, scores={…}, per_question=[…])` → 控制台打印汇总表。`asyncio.run(main())`；确定性可复跑（零 LLM 零网络零模型）。
- AC-15/16/17/18。

### WP-G：钉桩 + 单测（tests/conftest.py + tests/crawl/test_sanitize.py 新建；测试不计生产行数）

- conftest 新增 autouse fixture `default_crawl_sanitize_disabled`：钉 `crawl_sanitize_enabled=False` + `crawl_canary_enabled=False`（对齐 056/058/087/088/089 模式；**只增不改**，存量 13 个 fixture 一字不动）。
- `tests/crawl/test_sanitize.py`（~20 项，hermetic 零 DB）：三态矩阵 / 载体剥离逐类 / 指令族标记逐类 / strict rejected / canary 间隔嵌入与唯一性 / find_canaries / 代码围栏良性不拒收 / mode 非法值 pydantic 校验 / SanitizeResult 结构；DB 侧（record_canary/check_canary_leak）用假 session 打桩对齐 test_tracing 模式（fail-open 分支 + 命中分支 span 断言 mock _spawn_insert）。
- 爬虫接线单测进同文件：`_crawl_page_and_store` 开 sanitize 后 mock ingest 断言收到的 content 无 HTML 注释、review 收到清洗文本、strict 下 review_status="rejected"。
- AC-2/9/13/21/23/26/27。

---

## 3. 行数对照（铁律 2，AST 可执行语句口径，不含注释/docstring/测试）

| WP | 文件 | 预估 AST | 说明 |
|----|------|---------|------|
| WP-A | src/config.py（改） | +3 | 3 字段 |
| WP-B | src/database.py（改） | +12 | 新 DDL 常量 + ensure + init_db 挂接 |
| WP-C | rag/crawl/sanitize.py（新） | ~88 | 结果结构 + 6 类正则 + sanitize/嵌入/落库/检测 |
| WP-D | rag/crawl/crawler.py（改） | +12 | _crawl_page_and_store 接线 + summary 字段 |
| WP-E | rag/engine.py（改）+ main.py（改） | +5 | 泄漏检测 2 接线点 + 2 import |
| WP-F | eval/benchmarks/eval_injection.py（新） | ~65 | **计入生产口径（module-066 先例，裁定 7）**；用例集 JSON 不计入 |
| **合计** | | **~185 ≤ 200** | 缓冲 ~15 |

- 用例集 JSON 数据文件不计入（golden.json 先例，裁定 7）。
- 测试（tests/crawl/test_sanitize.py ~20 项 + conftest +8 行 fixture）默认豁免口径，不占上限。
- 偏差 >50% 时 Developer 在 changelog 用实际 AST 复算数据校准并如实申报。

---

## 4. 风险评估

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| 1 | canary 令牌污染子块 embedding（~250 字符间隔 ≈ 子块 300 字符的 5-6% 噪声） | 中 | 令牌短（17 字符）；golden 评测集全是人工上传文档无 canary，golden 指标零影响；爬虫文档检索质量无硬门槛（诚实边界入 plan §6/AC），FP 若实测显著可在后续模块改"仅父块级嵌入" |
| 2 | chunker 可能拦腰切断 canary 令牌（该子块检测失效） | 低 | 行边界插入降低概率；父块 ≤4000 内含多个 canary，父块级检测几乎必中；漏检属概率性非系统性，不阻断验收 |
| 3 | 正则剥离/检测误伤 | 中 | 载体族只剥非可见内容；指令族只标记不剥离；hidden_text 字面命中误报已预判（良性用例③），strip 默认档兜底；eval FP 指标持续量化 |
| 4 | 正则回溯爆炸（大页面） | 低 | 模式全线性（`.*?` 单层 + DOTALL），禁嵌套量词写入 WP-C 约束；crawler 接线 try/except fail-open 兜底 |
| 5 | 行数超 200 | 低 | 预估 185 留缓冲；若超，eval 脚本可拆策略对象/裁报告打印（不影响语义）；禁用"豁免口径"辩解——本 plan 已把 eval 计入 |
| 6 | strict 模式 rejected 与审查节点 approved 状态冲突 | 低 | 裁定 1 顺序 + WP-D 第 3 步在计数分支前合并，rejected 优先；与 075 契约（仍入库）一致 |
| 7 | 真实对账时投毒内容污染真实库 | 中 | Tester 用独立 source 标记 + T6 清理还原基线（DELETE 探针 doc 行 + crawl_canaries 行 + eval_runs 探针行），AC §5 写明 |

---

## 5. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-075/076/077 爬虫管线 | sanitize 挂 `_crawl_page_and_store`，fetch/review/ingest/递归四段行为契约零破坏；rejected 仍入库契约沿用 |
| module-078 审查节点（三档策略 + HHEM） | sanitize 前置于审查（裁定 1）；两套"策略档"独立（crawl_review_policy 管审查器失败语义，crawl_sanitize_mode 管清洗处置），strict 拒收只在 sanitize 侧生效 |
| module-064 清洗管线 | 分层互补：sanitize 在 ingest 之前（安全语义，防审查器/嵌入被投毒），cleaner/normalize 在 ingest 内（质量语义）；零宽字符双层剥离（重叠无害，纵深防御叙事的一部分）；module-064 三文件零 diff |
| module-043 意图校验四层 | 防线位置不同：043 防用户输入侧，086 防知识库内容侧（入口入库 + 输出泄漏），roadmap"输入/输出过滤"两翼合围 |
| module-074 Java 侧 kb_reference 出口守卫 | 本模块零接触 Java；纵深防御叙事 = 出口（074）+ 入口（086）两层 |
| module-088 request_spans | 拦截/泄漏事件经 `record_span(kind="security", status="blocked")` 进既有通道，零 schema 改动；`src/tracing.py` 本身零 diff |
| module-085 看板 | v1 不做 security span 聚合（读侧扩展留后续模块）；span 已落库，未来可查 |
| module-087/089 task/budget | 无直接耦合（crawl 后台任务无 task 上下文 → record_span 静默跳过，符合 088 设计）；新表幂等 DDL 照 087 先例 |
| module-019/066 eval_runs | 复用 save_eval_run 通道，eval_type='injection' 区分 |

---

## 6. 明确不做（Developer 勿越界）

1. **Java 侧任何改动**（interview-admin/、backend/）：074 出口守卫既有，不动。
2. **LLM 输出的内容级语义审查**：086 输出侧只做 canary 泄漏检测（确定性令牌匹配），不做"回答是否被注入指令操纵"的语义判断。
3. **多语种投毒全覆盖**：用例集中英双语为主（覆盖 T4 验收即够），不做日韩等语种矩阵。
4. **来源信任分级**（T4 第③件）：裁定 6 移出，source_configs 表零改动。
5. **agent/react.py / langgraph_react.py 路径的泄漏检测接线**：v1 只接 chat 双路径（裁定 4）。
6. **HTML→Markdown 全量转换**（爬虫文档解析升级）：属 module-064 解析域，086 只做注入面剥离。
7. **物理删除 rejected 内容**：对齐 075 契约只标记。
8. **085 看板 security 维度聚合**、**新外部依赖**（sanitizer 纯 stdlib/re，requirements.txt 零改动）、**frontend/backend 改动**。

## 7. 行为契约（口径锁定，Developer 勿改）

- canary 令牌格式：`[canary:{8位小写hex}]`；检测正则 `canary:([0-9a-f]{8})`。
- span 事件：name=`canary_leak`、kind=`security`、status=`blocked`、decision 以 `doc_id=` 开头。
- eval 落库：`eval_type='injection'`；scores 键名 `{strip: {poison_total, intercepted, interception_rate, benign_total, false_positives, false_positive_rate}, strict: {同}}`。
- 三档语义见裁定 2，类目名七者锁定：`html_comment / script_style / hidden_unicode / hidden_text / instruction_override / exfiltration / destructive_tool`（前三个载体族 strip，后四个指令族 mark）。

## 8. 待澄清（不阻塞开发，Developer 按本 plan 缺省执行）

1. **信任分级承接**：裁定 6 已移出；建议编排者决定后续模块（可与 T5 Supervisor 或独立 086b 承接），本模块无预留挂点成本（sanitize findings 已按 source 落 details，未来分级可直接消费）。
2. **agent 路径泄漏检测接入时机**：待 086 收口后由编排者决定是否并入后续小模块（1 个调用点 + ~3 AST，成本低但本模块预算已满）。
3. **生产默认档**：裁定 8 取 `strip`（保守直接生效）；若团队希望先观察可改 `detect` 起步——只需改 config 默认值一行，语义不变。Planner 缺省 strip。

## 9. 变更记录

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| v1 | 2026-09-06 | 初始版本（重派首规划：§0 七组探明事实含活跃代码库陷阱、8 项裁定、WP-A~G、行数对照 ~185 AST、风险 7 项、红线清单、AC 对齐） | Planner |
