# 审查报告 — Module-075: 知识抓取流水线（定时调度 + 源配置 + 入库闭环）

> 本文件为复审轮最终报告（覆盖初版）。初审结论"不通过"（3 项阻塞，见 §1）；
> Developer 修复轮 v3 提交后复审，3 项阻塞全部修复属实，复审结论 **通过**（见 §2）。

---

## 1. 初审回顾（不通过，3 项阻塞）

初审（Reviewer，2026-08-25）发现 3 项阻塞问题，全部位于 `ai_service/main.py`
修复轮 v2 的 `event_stream` 198 行拆分重构代码中：

| # | 文件 | 问题描述 | 严重级别 |
|---|------|----------|----------|
| 1 | `ai_service/main.py` | `_stream_generate_verify` 引用未定义变量 `docs`（`generate_answer_stream`/`_extract_sources`/`submit_verify_task`/`verify_answer` 均用 `docs`，但函数内从未赋值）→ 每次 knowledge 路径 `chat_stream` 请求触发 `NameError`，主链路不可用 | 阻塞 |
| 2 | `ai_service/main.py` | `_stream_generate_verify` 签名缺少 `docs` 参数（与 #1 同根因） | 阻塞 |
| 3 | `ai_service/main.py` | 拆分后 `_chat_stream_events` 直接调用 `_stream_generate_verify`、跳过 `_stream_retrieve_rerank_reflect`，其内部 `_step` dict 未被消费 → 检索/重排/反思步骤的 SSE `event: step` 丢失，前端 PipelinePanel 管线进度缺失 | 阻塞 |

另外提出 5 项低优先级建议改进（见 §4）。

---

## 2. 复审结论（本轮）

- 结论: **✅ 通过**
- 审查时间: 2026-08-25
- 审查人: Reviewer（复审轮）
- 修复轮: v3（Developer 提交，changelog.md 已记录）
- 审查方式: 逐行代码审读 + AST 静态分析（签名/引用/调用点）+ 单测实跑

---

## 3. 初审阻塞问题的修复确认

### 阻塞 #1：`_stream_generate_verify` 引用未定义变量 `docs` → NameError

- **问题描述**：函数体 4 处引用 `docs`（生成、抽取 sources、提交验证、同步验证）但函数内从未赋值，运行时必然 NameError，主链路完全不可用。
- **修复方式**：函数签名补齐 `docs` 参数（`async def _stream_generate_verify(request, fastapi_req, identity, intent, _t, docs)`，`main.py:L507`），调用方 `_chat_stream_events` 在 `main.py:L605` 以 6 参数调用并传入检索结果。
- **验证结果**：✅ 修复属实
  - AST 验证：`_stream_generate_verify` 参数表含 `docs`（第 6 参）；函数体内 `docs` 引用行号为 L513 / L518 / L526 / L530，全部落在参数作用域内，**无未定义变量**。
  - 调用点验证：`_chat_stream_events` L605 调用 `_stream_generate_verify(request, fastapi_req, identity, intent, _t, docs)`，实参个数与签名一致。
  - 辅助符号验证：`submit_verify_task`（main.py:L25 `from src.verify_tasks import ...`）、`schedule_stream_persist`（main.py:L296 定义）、`MAX_ANSWER_LEN`（main.py:L46 定义）均存在，无悬空引用。
  - 语法验证：`ast.parse` 通过，`python -c "import main"` 冒烟（changelog 记录）通过。

### 阻塞 #2：`_stream_generate_verify` 签名缺 `docs` 参数

- **问题描述**：与 #1 同根因——签名没有 `docs`，内部无法获取检索结果。
- **修复方式**：签名改为 `async def _stream_generate_verify(request, fastapi_req, identity, intent, _t, docs)`（`main.py:L507`），并自调用方传入。
- **验证结果**：✅ 修复属实（与 #1 为同一处修复，AST 签名验证覆盖，见上）。

### 阻塞 #3：拆分后 SSE step 事件丢失

- **问题描述**：`_stream_retrieve_rerank_reflect` yield 的是内部 `_step` dict，但 `_chat_stream_events` 原实现未消费这些 yield，检索/重排/反思三步的 `event: step` SSE 事件全部丢失。
- **修复方式**：`_chat_stream_events`（`main.py:L590-606`）改为先迭代 `_stream_retrieve_rerank_reflect(request, identity, _t)` 并完整消费三种事件：
  - `_step`（L591-594）→ `_internal_step_to_sse(evt, _t)` 转换为 `event: step\ndata: {...}\n\n` 后 yield；
  - `_no_docs`（L595-598）→ 委托 `_stream_no_docs_fallback(query, intent, identity)` 生成 LLM 兜底回答 + done 事件后 return；
  - `_docs`（L599-601）→ 提取 `docs` 存入局部变量，供下一步传入 `_stream_generate_verify`；
  - 防御：若 `docs is None`（理论不可达），yield done + return（L602-604）。
- **验证结果**：✅ 修复属实
  - 转换函数 `_internal_step_to_sse`（`main.py:L552-567`）覆盖三步：retrieval（data 含 count/relevant/top_abs_cosine/suspected_misclassify/previews）、rerank（data 含 before/after）、reflection（data 含 sufficient/reason），字段结构与重构前一致；timing 由事件内 `t0` 与当前时间差计算。
  - 事件序列等价性（对照 changelog v3 等价表逐行核对）：intent step（L581）→ retrieval step（L470 yield）→ rerank step（L478 yield）→ reflection step（L486 yield）→ token×N / verified / done（L507-537），无遗漏步骤；casual_chat 分支（L582-587）与无文档兜底分支（L538-550）行为与重构前一致。
  - AST 调用点验证：`_chat_stream_events` 内 `_stream_retrieve_rerank_reflect` 调用 L590、`_stream_no_docs_fallback` 调用 L596、`_stream_generate_verify` 调用 L605，链路完整。

### 修复轮合规性小结

| 函数 | 行数 | docstring | 空 catch | 结论 |
|------|------|-----------|----------|------|
| `_build_step_event` | 3 行 | ✅ | 无 | ✅ |
| `_build_done_event` | 4 行 | ✅ | 无 | ✅ |
| `_extract_sources` | 3 行 | ✅ | 无 | ✅ |
| `_internal_step_to_sse` | 15 行 | ✅ | 无 | ✅ |
| `_stream_no_docs_fallback` | 12 行 | ✅ | 无 | ✅ |
| `_stream_retrieve_rerank_reflect` | 28 行 | ✅ | 无 | ✅ |
| `_stream_generate_verify` | 31 行 | ✅ | 无 | ✅ |
| `_chat_stream_events` | 44 行 | ✅ | 无 | ✅ |

- 全部辅助函数 ≤ 50 行（最大 `_chat_stream_events` 44 行，main.py:L569-612）✅
- 全部有 docstring（每函数体首行为字符串表达式）✅
- 无空 catch / 吞异常：`_chat_stream_events` 的 except 记录日志并 yield SSE error 事件 ✅
- 无新引入依赖（requirements.txt 零改动）、无新跨层调用 ✅

---

## 4. 初审建议改进项状态

初审 5 项低优先级建议，Developer 修复轮 v3 未处理（v3 仅修 3 项阻塞）。经复核，5 项均不阻塞，维持"未修复（低优先级）"标注：

| # | 文件/位置 | 建议 | 状态 | 复核说明 |
|---|-----------|------|------|----------|
| 1 | crawler.py `_review_content` 两个 try/except | except `Exception` 过宽，建议日志区分异常类型 | ⚠️ 未修复 | fail-open 为有意设计，`logger.warning` 已记录 message；建议改为 `type(e).__name__` 提升可观测性（低） |
| 2 | crawler.py `run_crawl` 入库 `filename="*.html"` | 按 content-type 动态扩展名，避免未来抓 PDF 等误路由 | ⚠️ 未修复 | 当前 httpx GET 返回原始 HTML，`.html` 恰好正确；留待支持多格式时处理（低） |
| 3 | test_crawler.py `test_returns_rows` / `test_db_error_returns_empty` | 4 空格缩进为模块级函数而非 `TestRunCrawl` 类方法，建议归入类 | ⚠️ 未修复（无功能影响） | 复核确认两函数仍为模块级函数（pytest 收集为 `test_crawler.py::test_returns_rows` 等，非类方法），但 pytest 正常收集且实跑通过（30 passed）；仅结构洁癖，可后续规整 |
| 4 | crawler.py `_review_content` factcheck 阈值 0.3 | 硬编码，建议提升为模块常量或 config | ⚠️ 未修复 | 常量内聚在审查函数内，暂无调参需求；可随 module-078 处理 |
| 5 | main.py `add_crawl_source` / `list_crawl_sources` 原始 SQL | 建议统一 ORM（与 `list_documents` 风格一致） | ⚠️ 未修复 | 参数化 SQL 安全无误，仅维护性偏好（低） |

> 说明：黑名单域名过滤（初审验收表 ⚠️ 未实现）为编排者决策 #4 留后续（白名单表驱动已实现），非本次修复范围，记入技术债务。

---

## 5. 验收标准核对表（复审更新）

| 验收项 | 对应代码 | 状态（复审） | 备注 |
|--------|----------|--------------|------|
| 1.1 添加源配置 POST /ai/crawl/sources 后 GET 返回 | main.py crawl sources 端点 | ✅ 通过 | 初审已通过，代码未变 |
| 1.1 手动触发抓取 POST /ai/crawl/run → 内容入库 | main.py + crawler.py `run_crawl` | ✅ 通过 | 初审已通过，fail-open 设计合理 |
| 1.1 白名单域名允许抓取 | crawler.py `_matches_any` | ✅ 通过 | 前缀匹配，case-insensitive |
| 1.1 黑名单域名跳过 | — | ⚠️ 未实现 | 编排者决策留后续（技术债务 #1） |
| 1.1 审查节点：reflector.check_sufficiency + factcheck_judge | crawler.py `_review_content` | ✅ 通过 | 双步审查 + fail-open |
| 1.1 审查通过 review_status="approved" | crawler.py 返回值 | ✅ 通过 | |
| 1.2 源配置 URL 为空返回错误 | main.py | ✅ 通过 | code=1, msg 明确 |
| 1.2 抓取目标 404/500 跳过 | crawler.py HTTPStatusError 分支 | ✅ 通过 | |
| 1.2 抓取目标超时 >30s 跳过 | crawler.py TimeoutException 分支 | ✅ 通过 | |
| 1.3 httpx 网络异常不阻断整批 | crawler.py `run_crawl` 单页 try/except | ✅ 通过 | errors += 1, continue |
| 1.3 reflector / factcheck_judge 调用失败默认 approved | crawler.py `_review_content` except | ✅ 通过 | fail-open |
| 2.1 抓取 URL 仅允许 http/https | crawler.py `_is_safe_url` | ✅ 通过 | 测试覆盖 6 项 |
| 2.3 生产代码 ≤ 200 行（module-075 部分） | crawler.py ~130 行功能代码 | ✅ 通过 | |
| 2.3 所有公开方法有 docstring | crawler.py + main.py 辅助函数 | ✅ 通过 | check-gates 已验证 |
| 2.3 无空 catch / 吞异常 | crawler.py + main.py | ✅ 通过 | 所有 except 有日志 |
| **chat_stream 主链路行为等价性** | main.py `_chat_stream_events` 编排链 | ✅ **通过（复审修复）** | **阻塞 #1-#3 全部修复：docs 传递链完整、SSE step 事件恢复、事件序列等价** |

---

## 6. 架构评估（复审回抽）

- **分层正确性**：通过。crawler.py 在 rag/crawl/ 子包，依赖 src/config、src/database、rag/retrieval/document_ingest、agent/reflector、rag/retrieval/factcheck_judge——同层或下层依赖，无反向调用。
- **依赖方向**：通过。crawler.py 仅被 main.py 的 3 个端点 + lifespan 调用。
- **DTO 约束**：通过。CrawlResult/CrawlSummary 为内部 dataclass，不暴露到 Controller 层。
- **新增依赖**：apscheduler==3.10.4（plan.md §3.2 已定义，ADR 决策已记录）。
- **修复波及面**：v3 仅改 main.py（`_chat_stream_events` 编排 + 3 个消费分支 + `_internal_step_to_sse` 等辅助函数），crawler.py / tests / requirements 未触及。

## 7. 安全评估（复审保持通过）

- [x] SQL 注入防护：source_configs INSERT 参数化查询
- [x] XSS / 密码 / API Key：N/A 或无敏感信息
- [x] URL 安全：`_is_safe_url` 仅 http/https
- [x] 敏感信息日志：URL 截断 `[:80]`，无密钥泄露
- [x] 抓取内容敏感路径：仅协议校验，靠 URL 白名单间接控制（已知局限，非本次范围）

## 8. 测试验证（复审实跑）

- `pytest tests/crawl`：**30 passed, 2 warnings（第三方库告警，非本模块），33.66s** ✅（与 changelog 记录一致）
- 全量 `pytest tests/`：1276 passed / 5 failed / 3 skipped——5 个失败全部为 `tests/agent/test_agent_tools.py` 的 `langchain-openai` SDK `proxies` 参数兼容问题（module-028 文件，环境性），与 module-075 变更文件零交集，不阻塞本模块。
- `python -c "import main"` 冒烟通过（changelog 记录）。

## 9. 五轴评分（复审更新）

| 轴 | 评分 | 依据 |
|----|------|------|
| 正确性（逻辑/边界/错误路径） | 5 | 阻塞 #1-#3 全部修复属实，docs 传递链完整（AST 验证无未定义变量），SSE 事件序列等价，无 NameError |
| 完整性（需求覆盖/测试覆盖） | 4 | crawl 功能 30 项单测全绿；黑名单过滤未独立实现（编排者决策留后续） |
| 清晰性（命名/注释/可读性） | 5 | docstring 齐全、注释清晰、辅助函数职责单一 |
| 可维护性（拆分/耦合/复杂度） | 5 | 8 个辅助函数均 ≤44 行，接口自洽，调用链完整 |
| 安全性（注入/密钥/敏感数据） | 5 | URL 协议校验、参数化 SQL、日志截断、fail-open |

> 无轴 ≤ 2 分，无阻塞。

## 10. 审查总结

- **复审结论：✅ 通过**。初审 3 项阻塞（NameError / 缺 docs 参数 / SSE step 事件丢失）在修复轮 v3 全部修复属实，AST 静态分析 + 逐行核对 + 单证实跑三重验证通过。
- 初审 5 项建议改进均未处理，但全部为低优先级、不阻塞（crawler.py 部分与模块-075 主链路无关；main.py 原始 SQL 属风格偏好），标注"未修复"留后续。
- 技术债务：黑名单过滤（module-076 候选）、factcheck 阈值参数化（module-078 候选）、except 类型日志、测试类归属规整、crawl 端点 ORM 化。
- Tester 关注项（延续初审）：① chat_stream 主链路真实 E2E（SSE step/token/done 完整）；② crawl 端点添加源→手动触发→入库真实 HTTP E2E；③ 审查节点 mock 验证 approved/rejected 标记。

### 审查人签名

- 审查人：Reviewer (module-075, 复审)
- 日期：2026-08-25
- 结论：✅ 通过（3 项阻塞全修复，0 新引入问题，30/30 crawl 单测通过，5 个全量失败归类环境性）

---

## 11. 修复轮复审（2026-08-26）

> 修复轮 v4 快速复审：2 个新发现问题（截断标记 SSE token 丢失、HTML 入库解析失败）。
> 审查方式：逐行代码核对 + git diff 核对 + 32/32 单证实跑 + html 解析路径冒烟实测。

### 阻塞问题修复确认

| # | 问题 | 修复方式 | 验证结果 |
|---|------|----------|----------|
| 1 | chat_stream 超长答案截断时，截断标记只 append 不 yield → SSE 流收不到截断标记 token，前端显示缺失 | `main.py _stream_generate_verify`（L516-519）：截断分支先 `answer_parts.append(trunc_msg)` 再 `yield` 截断标记 token 事件，最后 `break`；验证前 `clean_answer` 剥离标记（L526） | ✅ 逐行核对 append+yield+break 顺序正确、与 module-042 原始语义一致；`test_stream_truncation_marker_emitted` 实跑通过（断言 token 事件流含截断标记、总长 ≤ MAX_LEN+标记长） |
| 2 | 抓取 HTML 入库解析失败（AnyDoc 转 html 抛 unsupported input → DocumentParseError，入库链路中断） | A) `crawler.py` 入库 filename `.html` → `.txt`（扩展名路由 text 纯文本路径，绕开 AnyDoc html 转换）；B) `document_parser.py` AnyDoc except 块与 AnyDoc 不可用回退块均补 `fmt=="html"` → 纯文本透出（engine=text） | ✅ 冒烟实测：`crawl_page.html`（AnyDoc 探测 html 且 to_markdown 抛错，即原故障路径）→ 现 engine=text 透出不抛错；`crawl_page.txt` → format=text 直接解码不经 AnyDoc；`ingest_document` L112 确认 filename 透传 parse_document |

### 复审结论
- 结论：✅ 通过
- 备注：
  - 2 项修复均验证属实：git diff 核对（document_parser.py 新增 2 处 html 透出分支；crawler.py 现为 `.txt`）＋ 32/32 单证实跑（30 crawl + 2 截断流，33.37s，2 warnings 均为第三方库告警）＋ html 冒烟实测。
  - 非阻塞建议：① `tests/crawl/test_crawler.py` 两个 ingest 用例仅断言 `assert_called_once`，未断言 filename 扩展名，建议补断言防 `.txt` 改动回归；② `tests/core/test_document_parser.py` 无 html 用例，建议补 3 条透出路径单测（anydoc=None 早退 / AnyDoc 抛错 / 回退块）；③ html 透出为带标签原始文本（fail-safe 设计接受），下游 cleaner 不剥离 HTML 标签，入库内容含标签为已知局限，可后续 strip 增强。
  - 过程观察：本轮修复与整个 module-075 重构均处于未提交工作区（main.py 修改、crawler.py 未跟踪、document_parser.py 修改），changelog.md 尚无 v4 记录——提交与 changelog 更新建议随模块闭环一并完成。
---
 
## 12. review_status 落库修复复审（2026-08-26）
 
> 修复内容：调用链底部往上 4 个文件透传 `review_status`（crawler → ingest_document → add_document → Document），
> 修复"审查状态不落库"断链。审查方式：逐行代码核对（4 层调用链 + 默认值）＋ 30/30 单证实跑。
 
### 修复确认
 
| # | 修改点 | 验证结果 |
|---|--------|----------|
| 1 | Document 模型字段 | ✅ |
| 2 | add_document 参数 | ✅ |
| 3 | ingest_document 参数 | ✅ |
| 4 | crawler 调用传参 | ✅ |
| 5 | 单测断言 | ✅ |
 
**验证明细：**
1. **Document 模型字段**（`rag/models.py` L112）：`review_status = Column(String(16), nullable=False, default="approved", comment="审查状态：approved（通过）/ rejected（不通过，仍入库可复核）——module-075")`；`src/database.py` L306 另有幂等 DDL `ALTER TABLE ... ADD COLUMN IF NOT EXISTS review_status VARCHAR(16) NOT NULL DEFAULT 'approved'`（init_db 兜底，存量行零迁移）。✅
2. **add_document 参数**（`rag/engine.py` L1113）：签名末位新增 `review_status: str = "approved"`（追加在末尾，既有位置实参调用不受影响）；**父块**（L1206）与**子块**（L1238）两处 `Document(...)` 构造均传入 `review_status=review_status`，docstring 同步更新。✅
3. **ingest_document 参数**（`rag/retrieval/document_ingest.py` L87）：`*` 后关键字参数 `review_status: str = "approved"`（关键字限定，不破坏既有位置调用）；L191 透传给 `rag_engine.add_document`。✅
4. **crawler 调用传参**（`rag/crawl/crawler.py`）：`CrawlResult` dataclass 含 `review_status: str = "approved"`（L39）；审查后 `result.review_status = review`（L211）；`ingest_document(...)` 调用传入 `review_status=result.review_status`（L221）。✅
5. **单测断言**（`tests/crawl/test_crawler.py` `test_rejected_still_ingested`）：新增 `mock_ingest.assert_called_once()`（rejected 仍入库不丢数据）＋ `call_kwargs.get("review_status") == "rejected"`（透传值断言，直接覆盖本次断链修复点）。✅
 
**默认值向后兼容确认**：4 个新参数/字段（models Column / add_document / ingest_document / CrawlResult）默认值均为 `"approved"`；既有调用方（上传端点、smoke 脚本等未传 review_status）行为不变。
 
### 复审结论
- 结论：✅ 通过
- 备注：
  - 调用链完整：`crawler.py`（`result.review_status`）→ `ingest_document(review_status=...)` → `add_document(review_status=...)` → 父块+子块 `Document(review_status=...)` 落库，无断点、无遗漏构造点。
  - 单证实跑：`pytest tests/crawl/ -v` → **30 passed, 2 warnings in 31.58s**（2 warnings 为 starlette multipart 弃用提示与 pydantic_settings lifespan 前向引用，均为第三方库告警，与本次修复无关）；`test_rejected_still_ingested` 通过。
  - 非阻塞建议（后续可做）：`document_ingest.ingest_document` 返回 dict 未回带 `review_status`（结果消费方如需复核标识可补）；`tests/crawl` 对 `add_document` 层无直接断言（当前靠 ingest_document mock 覆盖，engine 层真实透传依赖 module-064 既有测试）。


