# 验收标准 — Module-085: 可视化看板（成功率 / 延迟 P95 / 成本(token) / 工具调用次数）

> 依据：`plan.md` v1（2026-09-06）| 验收口径：全量 **1564 passed / 2 failed（2×real_redis 环境性基线）/ 3 skipped** 新增 0 失败、**存量测试零改动** 红线
> roadmap 验收方向：**看板页面输出 4 指标，数据与落库一致**

## 1. 功能验收

### 1.1 聚合服务（WP-A src/dashboard.py）
- [ ] AC-1 `src/dashboard.py` 存在 4 条 SQL 常量，全参数化（仅 `:since` 绑定，grep 无 f-string/`%`/`+` 拼 SQL）
- [ ] AC-2 `_rows_to_requests(rows)`：分组行 → `{total, errors, success_rate, by_endpoint}`；success_rate = round((total-errors)/total, 4)；total=0 → success_rate=None（不伪造 0/1）
- [ ] AC-3 `_rows_to_latency(row)`：percentile_cont 数组行 → `{p50_ms, p95_ms, samples}`；NULL/无行 → None（latency 整体为 null）
- [ ] AC-4 `_rows_to_cost(rows)`：分桶行 → `{total_prompt, total_completion, by_provider:[{provider, prompt_tokens, completion_tokens}]}`，total 为各桶求和
- [ ] AC-5 `_rows_to_tools(rows)`：分组行 → `{total, by_tool:[{tool_name, calls, failures, duration_p95_ms}]}`，total 为各工具 calls 求和
- [ ] AC-6 `get_dashboard_metrics(hours)`：hours>0 → `:since` 绑定 `utcnow - timedelta(hours)`（假 session 断言绑定值）；hours=0 → 绑定 1970-01-01（全量窗口）
- [ ] AC-7 `get_dashboard_metrics` 假 session 下按序执行 4 条 SQL（requests → latency → cost → tools），返回 dict 四键 `requests/latency/cost/tools` + `window` 齐
- [ ] AC-8 **SQL 语义正确性（文本断言）**：latency SQL 含 `percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP` 与 `SUM((v)::float8) FROM jsonb_each_text(timings)` 与 `WHERE total_ms IS NOT NULL`；cost SQL 含 `jsonb_each(usage)` 与 `::bigint`；tools SQL 含 `percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)` 与 `SUM(CASE WHEN result_ok THEN 0 ELSE 1 END)`；requests SQL 含 `SUM(CASE WHEN error THEN 1 ELSE 0 END)`
- [ ] AC-9 聚合层异常**向上抛**不吞（端点层统一 fail-open——单测断言 session 抛错时 get_dashboard_metrics 同抛）

### 1.2 端点（WP-B GET /ai/observability/dashboard）
- [ ] AC-10 `GET /ai/observability/dashboard?hours=24` → 200 `{"code": 0, "msg": "success", "data": {window, requests, latency, cost, tools}}`（四指标键齐，字段名与 plan §8 契约逐字一致）
- [ ] AC-11 hours 缺省 24；`hours=0` → window.hours=0 全量窗口；`hours=168/720` → 正常透传聚合函数
- [ ] AC-12 **参数校验**：`hours=-1` 或 `hours=8761` → `{"code": 1, "msg": ...}` 提示"hours 参数非法"，不崩、不触达聚合函数；非 int（如 `hours=abc`）→ FastAPI 422（既有行为）
- [ ] AC-13 **fail-open**：聚合函数抛异常（mock）→ 200 `{"code": 1, "msg": "看板查询失败（fail-open）"}` + logger.warning，**不 500**
- [ ] AC-14 端点返回值 = 聚合函数结果透传（mock 返回 fixture → data 与 fixture 逐字一致，不被改写）

### 1.3 指标口径钉死（对账口径，Tester 真实验证用）
- [ ] AC-15 **成功率**：窗口内 `error=false` 占比；error=true 行计入分母（agent error 样例行影响成功率）；空窗口 success_rate=null
- [ ] AC-16 **延迟 P95**：每请求总延迟 = SUM(timings 各阶段)；**空 timings 行排除出分布但计入请求数/成功率**（两口径独立，AC-15 不矛盾）；P50/P95 = PG percentile_cont 连续插值法
- [ ] AC-17 **成本**：request_logs.usage 按供应商分桶 token 求和；**历史桶 `'llm'` 原样保留不合并**；无金额字段/无单价换算
- [ ] AC-18 **工具调用次数**：tool_call_logs 按自身 created_at 窗口过滤（无 endpoint 列不 JOIN）；含 per-tool `duration_p95_ms`（兑现 module-083 WP-C 预留）；failures = result_ok=false 计数
- [ ] AC-19 探针数据如实进统计：`probe-engine.chat` 端点行 / `write_file` 工具行不特判不过滤（数据与落库一致优先，plan §7 明确不做）

## 2. 边界条件验收
- [ ] AC-20 空窗口（hours 覆盖无数据区间）：requests.total=0 + success_rate=null + latency=null + cost 空数组/0 + tools 空数组——端点 200 code 0 不崩
- [ ] AC-21 timings 单样本：percentile_cont 对 1 行返回该行值（P50=P95=该值，samples=1）
- [ ] AC-22 usage 空 `{}` 行：不进 by_provider（jsonb_each 空展开），total 不含该行
- [ ] AC-23 usage 单桶缺 completion 键（防御）：`(v->>'completion')::bigint` 对 NULL → 端点不崩（PG COALESCE 或如实 NULL，Developer 二选一并在 changelog 声明；单测 fixture 覆盖）
- [ ] AC-24 hours 大窗口（如 8760）真实库可正常返回（全量 31/467 行量级，无性能问题）
- [ ] AC-25 前端 null 渲染：success_rate=null / latency=null → 页面显示"—"，不显示 NaN/undefined/0%

## 3. 前端验收（WP-D/WP-E，build + vitest，不计入 Python 生产行数口径）
- [ ] AC-26 `services/observabilityService.ts`：`getDashboard(hours)` GET `/observability/dashboard`（aiHttp，params 透传）+ `code===0` 解包 data / `code!==0` 抛 Error(msg) / 网络异常上抛（vitest mock aiHttp 断言）
- [ ] AC-27 `pages/DashboardPage.tsx`：窗口 Select（24/168/720/0）+ 刷新按钮 + **四指标卡片区**（请求总数+错误数 / 成功率% / 延迟 P50+P95 ms / token 总量+供应商分桶）+ by_tool Table（工具/次数/失败/耗时 P95）+ by_endpoint 展示
- [ ] AC-28 页面 vitest：mock service fixture → 四指标数字渲染断言（≥4 项核心数字可见）；请求失败 → Alert 提示不白屏；空数据 → 空态/"—"
- [ ] AC-29 路由与导航：App.tsx 注册 `/dashboard`（AppLayout 包裹）+ AppLayout navItems 增"观测看板"项——`npm run build`（tsc strict + vite）**PASS**
- [ ] AC-30 vitest 全量不低于存量基线（ChatPage 3 failed 为既有环境性失败），新增两测试文件全绿、存量测试文件零改动

## 4. 异常场景验收
- [ ] AC-31 **DB 不可用**：端点 fail-open code 1（AC-13）；前端收到 code 1 → Alert 展示后端 msg 不崩（service 抛 Error → 页面 catch）
- [ ] AC-32 **前端传参边界**：hours=0 页面正常（"全部"）；非法输入被 Select 枚举约束（页面无自由输入口）
- [ ] AC-33 **并发只读安全**：聚合全程只 SELECT 无写（SQL 文本断言无 INSERT/UPDATE/DELETE），多请求并发无锁风险
- [ ] AC-34 **SQL hygiene**：4 条 SQL 无注入面（参数化断言 AC-1 + 无动态拼接）；semgrep/手动 grep 无违规

## 5. 非功能验收

### 5.1 向后兼容零回归
- [ ] AC-35 全量 pytest = **1564 passed / 2 failed（2×real_redis 环境性基线）/ 3 skipped——新增 0 失败**
- [ ] AC-36 存量测试零改动：test_observability.py（module-058 写入侧）/ test_tool_call_logs.py（module-066）/ test_main.py 全过
- [ ] AC-37 **写入侧红线**（git diff 核验）：`src/observability.py` / `persist_request_log`（main.py 落库函数）/ REQUEST_LOGS_DDL / TOOL_CALL_LOGS_DDL / config.py / requirements.txt **零 diff**；main.py diff 纯新增端点（无存量行改动）
- [ ] AC-38 落库行为不受影响：一次真实 chat 请求后 request_logs 照常 +1 行（Tester 真实冒烟顺带核验）

### 5.2 代码质量验收（铁律）
- [ ] AC-39 Python 生产代码 ≤200 行（AST 可执行行口径，预估 ~95：dashboard.py ~75 + main.py ~20；**前端不计入该口径**——module-064 先例）；超限晒行数对照表 + 申请 GATE_MAX_MODULE_LINES
- [ ] AC-40 方法 ≤50 行 + public 函数 docstring；前端 DashboardPage.tsx ≤200 行 TSX（软约束，超限拆子组件）
- [ ] AC-41 无空 catch/吞异常：dashboard.py 不吞（AC-9），main.py fail-open except 带 logger + 注释；无 print
- [ ] AC-42 变更文件范围（plan §7 清单）：新增 6 文件（dashboard.py / test_dashboard.py / observabilityService.ts / DashboardPage.tsx / 两前端测试）+ 修改 3 文件（main.py / App.tsx / AppLayout.tsx）；**无其他文件 diff**（git status 核验）

## 6. 可运行验证命令表

| 验收项 | 验证命令 | 预期输出 |
|--------|----------|----------|
| 全量回归 | `cd ai_service && python -m pytest -q` | 1564 passed / 2 failed（real_redis 基线）/ 3 skipped，**新增 0 失败** |
| 定向单测 | `cd ai_service && python -m pytest tests/api/test_dashboard.py -q` | 全部 passed（预计 ~26 项） |
| 受影响存量 | `cd ai_service && python -m pytest tests/api/test_observability.py tests/agent/test_tool_call_logs.py tests/api/test_main.py -q` | 全部 passed（存量零改动实证） |
| 写入侧红线 | `git diff --stat -- ai_service/src/observability.py ai_service/src/config.py ai_service/src/database.py ai_service/requirements.txt` | 空（零 diff） |
| 端点真实冒烟 | 启动 uvicorn 8001 后 `curl "http://127.0.0.1:8001/ai/observability/dashboard?hours=0"` | `{"code":0,...,"data":{requests,latency,cost,tools,window}}` 四指标齐 |
| 参数校验冒烟 | `curl "http://127.0.0.1:8001/ai/observability/dashboard?hours=-1"` | `{"code":1,"msg":"hours 参数非法..."}` |
| **成功率对账** | `psql`：`SELECT COUNT(*) total, SUM(CASE WHEN error THEN 1 ELSE 0 END) errors FROM request_logs WHERE created_at >= now() - interval '24 hours'` | errors/total 与端点 `requests.total/errors` 一致，success_rate=round((total-errors)/total,4) |
| **延迟对账** | `psql`：`SELECT percentile_cont(ARRAY[0.5,0.95]) WITHIN GROUP (ORDER BY total_ms) FROM (SELECT (SELECT SUM((v)::float8) FROM jsonb_each_text(timings) e(k,v)) total_ms FROM request_logs WHERE created_at >= now() - interval '24 hours') s WHERE total_ms IS NOT NULL` | 与端点 `latency.p50_ms/p95_ms` 一致（同 percentile_cont 口径） |
| **成本对账** | `psql`：`SELECT k, SUM((v->>'prompt')::bigint), SUM((v->>'completion')::bigint) FROM request_logs, jsonb_each(usage) e(k,v) WHERE created_at >= now() - interval '24 hours' GROUP BY k` | 逐桶与端点 `cost.by_provider` 一致（含 'llm' 历史桶） |
| **工具对账** | `psql`：`SELECT tool_name, COUNT(*), SUM(CASE WHEN result_ok THEN 0 ELSE 1 END), percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) FROM tool_call_logs WHERE created_at >= now() - interval '24 hours' GROUP BY tool_name ORDER BY 2 DESC` | 与端点 `tools.by_tool` 逐行一致 |
| 前端 build | `cd frontend && npm run build` | tsc + vite build PASS |
| 前端测试 | `cd frontend && npm test` | 新增两测试文件全绿；全量不低于存量基线（ChatPage 3 failed 既有） |
| 页面冒烟（Tester） | 浏览器打开 `http://localhost:3001/dashboard` | 四指标卡片区数字可见，切窗口/刷新生效，工具表渲染 |

## 7. 验收结论
- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-09-06
- 结论: [ ] 通过 / [ ] 不通过
- 备注: Tester 重点关注 **AC-15~19 口径钉死**（对账 SQL 四条逐值比对 = "数据与落库一致"的验收实质）+ AC-13 fail-open + AC-29 页面 build + AC-35 全量零新增失败；环境受限（PG/Redis 不可达）时对账 SQL 项如实标注改期，hermetic 单测先行闭环
