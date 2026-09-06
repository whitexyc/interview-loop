# 开发计划 — Module-085: 可视化看板（成功率 / 延迟 P95 / 成本(token) / 工具调用次数）

> Planner: 2026-09-06 | 依据：`docs/AGENT-GROWTH-ROADMAP.md` 阶段 B（可观测：记录式 → 链路式）module-085 行——"可视化看板：成功率 / 延迟 P95 / 成本 / 工具调用次数（基于 request_logs/tool_call_logs）"，验收方向"**看板页面输出 4 指标，数据与落库一致**"
> 范围：只读聚合（1 个读端点 + 1 个前端看板页）；**零新表 / 零新依赖 / 零 config 新增 / 写入侧零改动**
> 预算：WP-A 1 天 + WP-B 2 小时 + WP-C 半天 + WP-D 1 天 + WP-E 半天 + WP-F 回归半天 ≈ 3.5 天
> Agent 配置：Developer ×1（Python 聚合 + React 页面，跨栈但量小）+ Reviewer ×1 + Tester ×1

## 0. Planner 已探明事实（勿重复调查）

- **request_logs 表**（database.py:57-77，module-058 WP-C）：`id / trace_id / identity / endpoint / intent / timings JSONB / usage JSONB / cache_hits / cache_misses / error BOOLEAN / created_at`。**无总延迟列**——每请求总延迟只能由 timings JSONB 各阶段毫秒求和得到。
- **timings JSONB 键集（真实库实测）**：`intent / triage_rewrite / hyde / retrieve / retrieve_fts / retrieve_vector / retrieve_graph / rerank / reflection / generate / verify / verify_submit`，值为 `round(seconds*1000, 1)` 浮点毫秒（写入点：main.py:488-606 + rag/engine.py 372/394/450/470/479/505/509/906/1038 + rag/retrieval/retriever.py:53 `_timed_channel` 按通道 label）。**空 timings 行存在**（agent 端点 error=true 样例行 `{}`）。
- **usage JSONB 结构（真实库实测）**：`{"deepseek": {"prompt": N, "completion": N}}`，按供应商分桶；**存在历史桶 `'llm'`**（module-058 Review 修复 `_provider_label` 前落库的旧数据）与探针端点行 `probe-engine.chat`；本地库 31 行中 28 行非空 usage。**表无价格/金额字段**。
- **tool_call_logs 表**（database.py:94-112，module-066 / ADR-0017 决策 2，一字不改红线）：`id / trace_id / tool_name / args JSONB / result_ok BOOLEAN / result_preview / duration_ms INTEGER / created_at`。**无 token / 无成本字段**（每次工具执行不消耗独立 LLM 调用计量）→ **"成本"指标只能从 request_logs.usage 聚合**（本 plan §2 决策 2 的口径依据）。**无 identity / endpoint 列** → 工具指标窗口过滤只能用自身 `created_at`。
- **写入点**：main.py `persist_request_log`（L290-317，fire-and-forget fail-open）在四端点调用——chat L476 / chat_stream L639 / agent L783 / agent-lg L860；落库经 observability.py:146 `save_request_log`。endpoint 实测取值：`chat / chat_stream / agent / agent-lg / probe-engine.chat`（开发探针行）。
- **开关**（config.py L140/L147）：`request_logs_enabled=True`（PW_REQUEST_LOGS）/ `tool_call_logs_enabled=True`（PW_TOOL_CALL_LOGS），conftest autouse 钉 false（hermetic）——本模块是读侧，**不加新开关**。
- **读侧 SQL 先例**：`rag/engine.py:120 resolve_tool_history`（module-072 WP-B）——request_logs / tool_call_logs 参数化查询 + `asyncio.wait_for` 超时 + 异常 `logger.warning` fail-open 返回 None；083 审批端点（main.py:1232/1254）确立 `{code, msg, data}` 返回格式与 `async_session_factory() + text()` 直查模式。
- **module-083 WP-C 预留**（config.py tool_default_timeout 注释原文）："tool_call_logs 已记 duration_ms，**module-085 看板拉 P95 后**按数据调整各工具值" → 工具级 duration P95 纳入看板 tools 指标（顺带兑现该预留）。
- **前端组织**（Planner 实测）：路由平铺在 `frontend/src/App.tsx` `<Routes>`（AppLayout 包裹，现有 `/` `/chat` `/edit-resume` `/knowledge` `/login`）；导航菜单是 `components/AppLayout.tsx` 顶部 `navItems` 数组（3 项）；API 封装模式 `services/ragService.ts`——`import { aiHttp } from '../api/client'`（baseURL `/ai`，vite 代理 → http://localhost:8001，自动附 Bearer）；页面用 antd（KnowledgePage 用 Table/Card）；测试先例 `src/__tests__/`（ragService.test.ts mock 全局 fetch；ResumePage.test.tsx `vi.mock` service 层）；`npm run build` = `tsc && vite build`，`npm test` = `vitest run`。
- **真实库现状（2026-09-06 Planner 探测）**：request_logs **31 行**（chat 5 / chat_stream 14 / agent 7 / agent-lg 4 / probe 1；error=true 1 行）/ tool_call_logs **467 行**（search_knowledge 285 / search_fts 102 / recall_memory 24 / search_vector 23 / generate_answer 11 / re_search 9 / extract_entities 7 / search_graph 4 / write_file 2（module-084 探针，全失败））——量级小，聚合查询无需索引优化。
- **测试布局**：端点向测试在 `tests/api/`（test_observability.py 即 module-058 测试，`_FakeSession` 打桩 `async_session_factory` + httpx `ASGITransport` 端点用例）——本模块测试放 `tests/api/test_dashboard.py` 对齐。
- **基线**：module-084 闭环后全量 **1564 passed / 2 failed（2×real_redis 环境性，Redis 6379 未启动）/ 3 skipped**——本模块红线：**新增 0 失败、存量测试零改动**。

## 1. 关键决策（Planner 裁定）

1. **交付形态 = 后端聚合端点 + 前端看板页（完整交付）**。roadmap 验收方向明文"看板**页面**输出 4 指标"；module-064 有前端先例（build + vitest 验收，不计入 Python 生产行数）；页面是纯只读展示，工作量可控（一个页面 + 一个 service 函数 + 一条路由 + 一个 nav 项）。仅端点+JSON 不满足验收方向，排除。
2. **4 指标口径**（精确写死，见 §3 WP-A；空窗口语义：请求数=0 时 `success_rate=null`、`latency=null`，前端显示"—"，不伪造 0/1）：
   - **成功率**：窗口内 request_logs `error=false` 行数 / 总行数（round 4 位）；附 by_endpoint 分组（total/errors 各端点）。
   - **延迟 P95**：每请求总延迟 = `SUM(timings 各阶段值)`（表无总延迟列，这是唯一可用口径；空 timings 行排除出分布，`WHERE total_ms IS NOT NULL`）；**P95/P50 用 PG `percentile_cont`**（连续插值法，非 nearest-rank——口径钉死，Tester 对账 SQL 同法复现即一致）；一条 SQL 数组参数同时取 P50/P95；附样本数 samples。
   - **成本 = token 用量按供应商分桶，不引入价格配置**。tool_call_logs 无 token 字段（§0）；request_logs.usage 无价格字段；引入单价表/配置 = 新状态面且供应商价格随时间变动 + 前缀缓存折扣（module-058 实测 cached tokens 计费差 ~98%）让"金额"严重失真——金额换算留给 module-089 预算账本届时定口径。**历史桶 `'llm'` 原样保留显示不合并**（合并 = 篡改历史落库事实，违背"数据与落库一致"）。
   - **工具调用次数**：窗口内 tool_call_logs 按 tool_name 分组 `{calls, failures(result_ok=false), duration_p95_ms}` + 总次数；直接按 created_at 过滤（无 endpoint 列，不 JOIN）。
3. **聚合层 = SQL 聚合（4 条独立参数化 SQL，单 session 顺序执行）**。本地单机量小（31/467 行），SQL 一次成型；percentile_cont 是 PG 内建；对齐 081 SAG / 072 resolve_tool_history / 083 approvals 的参数化 `text()` 先例。不做 Python 侧聚合（拉全行到应用层无意义），不做 ORM 聚合（JSONB 提取 SQL 更直白）。
4. **零新表 / 零新依赖 / 零 config**；**1 个新端点** `GET /ai/observability/dashboard?hours=24`（命名对齐 `/ai/tools/approvals` 风格 + 铁律 7 `{code, msg, data}` 格式）。聚合逻辑新建 `ai_service/src/dashboard.py`（observability.py 职责是"请求内写入侧"，跨请求读侧单独成模块，职责清晰且测试好对齐）。
5. **行数预算**：Python 生产代码按 **AST 可执行行口径**（module-075/080 先例）预估 **~95 行 ≤ 200 ✓**；**前端代码不计入 Python 生产行数口径**（module-064 先例：前端 build + vitest 验收，不入该口径）——前端自身软约束 DashboardPage.tsx ≤ 200 行 TSX。测试代码不计入。
6. **测试策略**：后端 `tests/api/test_dashboard.py`（假 session 打桩断言 SQL 文本/绑定参数，对齐 test_tool_call_logs / test_observability 模式；端点用 ASGITransport mock 聚合函数断言响应形状）+ 行→dict 组装抽纯函数直接单测；前端 vitest（service mock aiHttp + 页面 mock service 渲染断言）+ `npm run build`。"数据与落库一致"的真实验证 = Tester 对真实 PG 跑端点 + 手工对账 SQL（AC 命令表给出，同口径 percentile_cont），单测无法覆盖真实 SQL 语义，如实分层。

## 2. WP-A：聚合服务 `src/dashboard.py`（核心）

- 模块 docstring：读侧聚合（module-085），写侧在 observability.py 零改动。
- **4 条 SQL 常量**（全参数化 `:since`，无拼接；写法给出，Developer 照做）：
  - `_SQL_REQUESTS`：`SELECT endpoint, COUNT(*) AS total, SUM(CASE WHEN error THEN 1 ELSE 0 END) AS errors FROM request_logs WHERE created_at >= :since GROUP BY endpoint ORDER BY total DESC`（总体行由纯函数对分组求和，不二次查询）。
  - `_SQL_LATENCY`：
    ```sql
    SELECT percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (ORDER BY total_ms) AS p
    FROM (
        SELECT (SELECT SUM((v)::float8) FROM jsonb_each_text(timings) AS e(k, v)) AS total_ms
        FROM request_logs
        WHERE created_at >= :since
    ) sub
    WHERE total_ms IS NOT NULL
    ```
    返回 `double precision[]`（p[0]=P50, p[1]=P95；无行/全 NULL → NULL）。
  - `_SQL_COST`：`SELECT k AS provider, SUM((v->>'prompt')::bigint) AS prompt_tokens, SUM((v->>'completion')::bigint) AS completion_tokens FROM request_logs, jsonb_each(usage) AS e(k, v) WHERE created_at >= :since GROUP BY k ORDER BY prompt_tokens DESC`。
  - `_SQL_TOOLS`：`SELECT tool_name, COUNT(*) AS calls, SUM(CASE WHEN result_ok THEN 0 ELSE 1 END) AS failures, percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS duration_p95_ms FROM tool_call_logs WHERE created_at >= :since GROUP BY tool_name ORDER BY calls DESC`。
- **纯函数（可独立单测）**：`_rows_to_requests(rows)`（分组行 → `{total, errors, success_rate|None, by_endpoint:[...]}`，success_rate=round((total-errors)/total, 4)，total=0 → None）；`_rows_to_latency(row)`（数组行 → `{p50_ms, p95_ms, samples}|None`）；`_rows_to_cost(rows)`（→ `{total_prompt, total_completion, by_provider:[...]}`）；`_rows_to_tools(rows)`（→ `{total, by_tool:[...]}`）。
- **主函数** `async def get_dashboard_metrics(hours: int) -> dict`：
  - `since = datetime.utcnow() - timedelta(hours=hours)`；`hours==0` → `since = datetime(1970,1,1)`（全部数据，window.hours=0 透传）。
  - 单 `async with async_session_factory() as session` 顺序执行 4 条（`text()` + `:since` 绑定 datetime），组装 `{"requests":..., "latency":..., "cost":..., "tools":...}` 返回；**异常向上抛**（端点层统一 fail-open，见 WP-B——聚合层不吞异常，方便单测断言）。
  - `window` 字段（hours/since ISO 串/generated_at ISO 串）由端点层组装或本函数附带（裁定：本函数附带，端点只包装 code/msg）。
- **预估代码量**：~75 AST 行（SQL 常量含注释 ~30 + 纯函数 4 个 ~20 + 主函数 ~15 + import/docstring ~10）。
- **通过标准**：纯函数单测（含空行/None/精度 round）；`get_dashboard_metrics` 假 session 断言 4 条 SQL 全参数化（grep 无 f-string 拼接）+ `:since` 绑定值随 hours 正确偏移 + hours=0 → 1970 + 返回结构四键齐。

## 3. WP-B：端点 `GET /ai/observability/dashboard`（main.py）

- `@app.get("/ai/observability/dashboard")`，`async def get_observability_dashboard(hours: int = 24)`：
  - 参数校验：`hours < 0 or hours > 8760`（一年上限防滥用）→ `{"code": 1, "msg": "hours 参数非法（0=全部，1-8760 小时）"}`；非 int 由 FastAPI 自动 422（既有行为，不特殊处理）。
  - 调 `get_dashboard_metrics(hours)`；成功 → `{"code": 0, "msg": "success", "data": {...4 指标 + window}}`；异常 → `logger.warning("看板查询失败（fail-open）: %s", e)` + `{"code": 1, "msg": "看板查询失败（fail-open）"}`（读侧友好降级，不 500——对齐 072 fail-open 哲学，区别于 083 审批写侧 fail-closed）。
  - 无新鉴权（与 /ai 现有端点同等待遇，§0 approvals 先例）。
- **预估代码量**：~20 AST 行。
- **通过标准**：ASGITransport 单测——200 + `{code:0, msg, data}` 四指标键齐 / hours 非法 → code 1 / 聚合函数抛异常 → code 1 不 500 / mock 返回值透传不被改写。

## 4. WP-C：后端单测 `tests/api/test_dashboard.py`

- 预计 **~26 项**：TestRowsToRequests 4（正常求和/全错/空→None/round 精度）+ TestRowsToLatency 3（正常双值/NULL→None/单样本）+ TestRowsToCost 3（分桶/求和/空）+ TestRowsToTools 3（分组/失败计数/空）+ TestGetDashboardMetrics 5（SQL 文本含 percentile_cont/jsonb_each_text/jsonb_each/参数化断言 + :since 绑定 + hours=0 + 四键齐 + 异常上抛）+ TestEndpoint 6（200 形状/参数透传/非法 hours/异常 code1/mock 透传/真实形状抽查）+ TestSQLHygiene 2（4 条 SQL 无 f-string 拼接 + 无 semgrep 违规）。
- `_FakeSession` 打桩模式照抄 test_tool_call_logs.py:34-51（class _FakeSession + _fake_factory：记录 execute 的 (SQL, params)）；端点用例对齐 test_observability.py TestEndpointWiring（ASGITransport + mock 聚合函数）。
- conftest **预计零改动**（无新开关；读侧测试不落库不污染）。

## 5. WP-D：前端看板页

- **`services/observabilityService.ts` 新增**（~35 行，独立文件职责清晰，不塞进已 400+ 行的 ragService）：`export interface DashboardMetrics {...}` 类型（对齐 WP-A data 结构）+ `getDashboard(hours: number): Promise<DashboardMetrics>`——`aiHttp.get('/observability/dashboard', { params: { hours } })`，`code===0` 解包 `data`，否则 `throw new Error(msg)`（对齐 ragService 错误策略）。
- **`pages/DashboardPage.tsx` 新增**（~170 行 TSX）：antd `Card + Statistic + Table + Select + Button + Empty`：
  - 顶部：窗口 Select（近 24h / 7 天(168) / 30 天(720) / 全部(0)）+ 刷新 Button（手动刷新，**不做自动轮询**）；
  - 四指标卡片区：请求总数（副行：错误数）/ 成功率（%，null 显示"—"）/ 延迟 P50 + P95（ms，null 显示"—"）/ token 总量（副行按供应商分桶）；
  - by_endpoint 简表（端点/请求数/错误数）+ by_tool Table（工具/调用次数/失败/耗时 P95 ms，按调用次数降序）+ by_provider 文本桶；
  - 加载 Spin / 请求失败 Alert 提示（fail-open 展示，不白屏）/ 空数据 Empty。
- **`App.tsx`**：import DashboardPage + `<Route path="/dashboard" element={<AppLayout><DashboardPage /></AppLayout>} />`（+8 行）。
- **`components/AppLayout.tsx`**：navItems 加 `{ key: '/dashboard', label: '观测看板' }`（+1 行）。
- 类型不进 `types/rag.ts`（dashboard 类型内聚在 observabilityService.ts 导出，避免无关文件膨胀——与 conversation.ts 拆分先例同哲学）。

## 6. WP-E：前端测试 + build

- **`src/__tests__/observabilityService.test.ts`**（~4 项）：`vi.mock('../api/client')` mock aiHttp——GET 路径与 params 断言 / code=0 解包 data / code!=0 抛错含 msg / 网络异常上抛。
- **`src/__tests__/DashboardPage.test.tsx`**（~3 项）：`vi.mock('../services/observabilityService')`——fixture 渲染断言 4 指标数字出现（如成功率 96.67%、P95 值、token 总量、工具表首行）/ 加载失败显示 Alert / 空数据（success_rate null）显示"—"。
- `npm run build`（tsc strict + vite）必须 PASS；`npm test` 全量 vitest 不低于存量基线（**ChatPage 3 failed 为既有环境性失败**，module-029 起备案——新增测试全绿即可，存量零改动）。

## 7. WP-F：回归 + 文档收口

- 全量 `python -m pytest -q` = **1564 passed / 2 failed（2×real_redis 环境性基线）/ 3 skipped——新增 0 失败、存量测试零改动**。
- 受影响存量定点：`tests/api/test_observability.py` + `tests/agent/test_tool_call_logs.py` + `tests/api/test_main.py`（写入侧/表结构红线回归确认）。
- 真实验证（Tester）：启动 uvicorn 8001 → `curl "http://127.0.0.1:8001/ai/observability/dashboard?hours=0"` → 与对账 SQL 逐值比对（AC 命令表 §5）。
- 涉及文件清单：
  - 新增：`ai_service/src/dashboard.py`、`ai_service/tests/api/test_dashboard.py`、`frontend/src/services/observabilityService.ts`、`frontend/src/pages/DashboardPage.tsx`、`frontend/src/__tests__/observabilityService.test.ts`、`frontend/src/__tests__/DashboardPage.test.tsx`
  - 修改：`ai_service/main.py`（+端点 ~20 行）、`frontend/src/App.tsx`（+路由）、`frontend/src/components/AppLayout.tsx`（+nav 1 行）
  - 文档：`specs/module-085-observability-dashboard/changelog.md`（Developer）→ review-report.md（Reviewer）→ test-report.md（Tester）；记忆三件套。
- **明确不做**：不做金额/单价换算（module-089 预算账本口径）；不做时间序列趋势图/按天分桶（v1 窗口快照，趋势留后续）；不做 trace 级明细与 span 树（module-088 链路式观测范围）；不做 identity 维度过滤与用户级看板（隐私 + 无需求）；不做自动刷新/推送/轮询；不做聚合缓存（查询轻量本地单机）；不做端点白名单过滤（probe-* 行如实进统计——"数据与落库一致"优先，特判反而制造口径分叉）；不做 tool_call_logs 按 endpoint 细分（表无该列，JOIN 超出 4 指标范围）；无新 ADR（读侧聚合无架构分歧，决策记录入 changelog）。

## 8. 技术方案汇总（响应结构契约，前后端以此对齐，Developer 勿改字段名）

```json
{
  "code": 0, "msg": "success",
  "data": {
    "window": {"hours": 24, "since": "2026-09-05T00:00:00", "generated_at": "2026-09-06T12:00:00"},
    "requests": {"total": 31, "errors": 1, "success_rate": 0.9677,
                 "by_endpoint": [{"endpoint": "chat_stream", "total": 14, "errors": 0}]},
    "latency":  {"p50_ms": 4100.5, "p95_ms": 8200.0, "samples": 30},
    "cost":     {"total_prompt": 123456, "total_completion": 23456,
                 "by_provider": [{"provider": "deepseek", "prompt_tokens": 100000, "completion_tokens": 20000},
                                  {"provider": "llm", "prompt_tokens": 23456, "completion_tokens": 3456}]},
    "tools":    {"total": 467,
                 "by_tool": [{"tool_name": "search_knowledge", "calls": 285, "failures": 0, "duration_p95_ms": 4200.0}]}
  }
}
```
（null 语义：requests.total=0 → success_rate=null；latency 无样本 → latency=null；空窗口各数组为空列表。前端 null/空一律"—"或 Empty。）

- **数据表**：零新增；request_logs / tool_call_logs 一字不改（红线）。
- **API**：新增 1 个——`GET /ai/observability/dashboard?hours=24`（0=全部，1-8760 合法，非法 code 1）。
- **依赖/配置**：零新增。
- **代码量口径**（铁律 2，AST 可执行行）：

| WP | 内容 | 预估 AST 行 |
|----|------|------------|
| WP-A | src/dashboard.py（4 SQL + 4 纯函数 + 主函数） | ~75 |
| WP-B | main.py 端点 + 参数校验 + fail-open | ~20 |
| 合计 | | **~95 ≤ 200 ✓** |

  前端（observabilityService ~35 + DashboardPage ~170 + App +8 + AppLayout +1 ≈ 214 行 TSX/TS）**不计入 Python 生产行数口径**（module-064 先例：前端 build+vitest 验收；铁律 2 的"生产代码"在历次模块执行中均指 Python 侧）。若 Python 侧实际超 200，Developer 按 module-080 先例晒实际行数对照表 + 申请 `GATE_MAX_MODULE_LINES` 放宽。

## 9. 风险评估

- **P95 口径对账风险（中）**：总延迟 = timings 求和是"阶段覆盖口径"，不等于 HTTP 全墙钟（SSE 首包前中间件/序列化开销未计）；验收"数据与落库一致"以**对账 SQL 同口径**为准（不是与 curl 墙钟比）——口径已写死 §1 决策 2，Tester 对账即一致；未来若要墙钟口径须加列（明确不做，module-088 链路式观测再议）。
- **usage 历史桶 `'llm'`（低）**：旧数据如实显示不合并；前端按 provider 分桶展示天然兼容多桶。
- **timings 空行/异常值（低）**：空 timings（agent error 行）排除出延迟分布（WHERE total_ms IS NOT NULL），但**计入**成功率与请求数（error=true 本身就是成功率分母）——两口径独立，AC 写明。
- **探针数据污染（低）**：probe-engine.chat / write_file（084 探针）行如实进统计；真实库量小影响可忽略；如需清洗是数据操作不是代码逻辑，不在本模块。
- **JSONB 类型坑（低）**：jsonb_each_text 值是 text 须 ::float8；usage 求和用 ::bigint 防 int4 溢出（token 量大时不至于，但防御无害）；percentile_cont 数组参数返回 double[]，asyncpg 侧取 row[0] 为 list。
- **前端既有 vitest 环境性失败（零关联）**：ChatPage 3 failed 为 module-029 起既有基线，新增两测试文件独立，互不影响。
- **零回归面（小）**：写入侧（observability.py / persist_request_log / 两表 DDL / 四端点落库）零 diff；main.py 纯新增端点（083 approvals 先例：diff 纯新增即零回归）；conftest 零改动。

## 10. 与既有机制的关系

| 既有机制 | 关系 |
|----------|------|
| module-058 observability.py + request_logs | **写入侧零改动**（红线）；本模块是其读侧消费者（timings/usage JSONB 结构即 §0 实测契约） |
| module-066 / ADR-0017 tool_call_logs | 表结构一字不改（红线）；读侧聚合（calls/failures/duration_p95） |
| module-083 WP-C 预留 | "看板拉 P95 后按数据调整各工具值"——tools 指标输出 per-tool duration_p95_ms 兑现预留；**工具 timeout 调优本身不在本模块**（看板产出数据，调优留后续） |
| module-072 resolve_tool_history | 读侧 SQL 先例复用其模式：参数化 text() + fail-open + logger.warning；不修改该函数 |
| module-081 SAG 参数化 SQL | `text()` + 绑定参数直查先例；无新注入面（AC 含 SQL hygiene 断言） |
| module-083 approvals 端点 | `{code, msg, data}` 返回格式与 GET 端点写法先例 |
| module-064 前端先例 | 前端 build + vitest 验收、不计入 Python 生产行数口径 |
| module-088 链路式观测（后续） | 本模块是窗口聚合快照（记录式 → 链路式的中间步）；trace 级明细/spa 树留 088，本模块不预埋 |
| module-089 预算账本（后续） | 本模块只报 token 分桶；金额换算/预算口径届时定 |

## 11. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-09-06 | 初始版本（WP-A~F 拆解 + 4 指标口径钉死 + 响应契约 + 行数对照 + 风险与既有机制关系） | Planner |
| v2 | 2026-09-06 | Planner 复核轮（非实质变更）：§0 全部事实逐项独立核验（DDL/写入点/端点行号/前端结构逐字比对 + 真实库探测实证——request_logs 31 行按端点分布、tool_call_logs 467 行按工具分布、空 timings 2 行、非空 usage 28 行（其中 2 行同时含 deepseek+llm 双桶）、12 timings 键全对上；`_SQL_LATENCY` 实库演练通过返回 29 样本）；修正 2 处行号引用（retriever 完整路径 rag/retrieval/retriever.py / _FakeSession 行范围 34-51）；WP 拆解、口径、契约零变化 | Planner |
