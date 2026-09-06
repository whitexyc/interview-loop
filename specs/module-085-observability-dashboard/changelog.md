# 变更记录 — Module-085: 可视化看板（成功率 / 延迟 P95 / 成本(token) / 工具调用次数）

> Developer: 2026-09-06 | 依据：`plan.md` v2（2026-09-06，WP-A~F）+ `acceptance-criteria.md`（AC-1~AC-42）
> 基线：module-084 闭环后全量 **1564 passed / 2 failed（2×real_redis 环境性）/ 3 skipped**——本模块红线：**新增 0 失败、存量测试零改动、写入侧（observability.py/两表 DDL/config.py/requirements.txt）零 diff**
> 实施说明：单会话完成 WP-A~F；未跑全量回归、未启动 uvicorn、未改 .env（按分工留 Tester）

---

## 一、实现总览（读侧聚合链路）

```
前端 DashboardPage（/dashboard，nav"观测看板"）
  → observabilityService.getDashboard(hours) → aiHttp GET /ai/observability/dashboard?hours=N
后端端点（main.py，{code,msg,data} 格式，fail-open）
  → 参数校验（0=全部 / 1-8760 合法，非法 code 1 零触达）
  → src/dashboard.py get_dashboard_metrics(hours)
    → 单 async session 顺序执行 4 条参数化 SQL（仅 :since 绑定）：
      ① _SQL_REQUESTS  request_logs 按 endpoint 分组（total/errors）
      ② _SQL_LATENCY   SUM(timings 各阶段) 为每请求总延迟 → percentile_cont(ARRAY[0.5,0.95]) + COUNT 样本
      ③ _SQL_COST      jsonb_each(usage) 按供应商 token 分桶（COALESCE 兜 0）
      ④ _SQL_TOOLS     tool_call_logs 按 tool_name 分组（calls/failures/duration_p95_ms）
    → 4 个行→dict 纯函数组装 {window, requests, latency, cost, tools}
    → 异常向上抛（聚合层不吞）
  → 成功 code 0 / 异常 logger.warning + code 1（读侧友好降级不 500）
前端渲染：四指标卡片（null → "—"）+ Token 分桶 + by_endpoint 表 + by_tool 表
```

## 二、WP 实现说明

### WP-A src/dashboard.py（AC-1~AC-9，核心新文件）
- **4 条 SQL 常量**全参数化（唯一绑定参数 `:since`，无拼接）：文本与 plan §2 给定写法逐字对齐（AC-8 文本断言逐条覆盖）。两处 Developer 裁定微调（plan 授权范围内）：
  - `_SQL_LATENCY` 追加 `COUNT(*) AS samples`——plan §1 决策 2 要求"附样本数 samples"而给定 SQL 只取 percentile 数组，无法产出 samples；在同一聚合（同一过滤集）加一列 COUNT 是最小改动，不动 AC-8 要求的三段文本。
  - `_SQL_COST` 用 `COALESCE(SUM(...), 0)` 包裹（AC-23 二选一：**选 COALESCE 兜 0 而非如实 NULL**）——防单桶全缺 prompt/completion 键时 SUM 全 NULL，使端点总量为恒定 int；纯函数层再 `or 0` 双保险。单测 fixture 覆盖。
- **4 个行→dict 纯函数**（可独立单测）：`_rows_to_requests`（分组求和总体行，success_rate=round((total-errors)/total, 4)，total=0 → None）、`_rows_to_latency`（row=None 或数组位 NULL → latency 整体 None；单样本 P50=P95 天然成立）、`_rows_to_cost`（total 为各桶求和，历史桶 'llm' 原样透传不合并）、`_rows_to_tools`（total 为各工具 calls 求和）。
- **主函数** `get_dashboard_metrics(hours)`：hours=0 → since 绑定 `datetime(1970,1,1)`（全量窗口）；否则 `utcnow - timedelta(hours)`（plan 钉死口径）。单 session **按 requests→latency→cost→tools 顺序**执行（AC-7）；`window`（hours/since/generated_at ISO 串）由本函数附带；**异常向上抛**（AC-9，端点层统一 fail-open）。
- 写入侧 observability.py 零 import 零触碰；只读两表（SQL 文本断言无 INSERT/UPDATE/DELETE 等写关键字，词边界正则防 `created_at` 误报 CREATE——开发期自测抓到该误报后修正断言）。

### WP-B main.py 端点（AC-10~AC-14）
- 纯新增 2 处零存量行改动：顶部 `from src.dashboard import get_dashboard_metrics`（1 行）+ 文件尾部 approvals 端点后追加 `GET /ai/observability/dashboard`（19 行，注释分隔线对齐 083 approvals 段落风格）。
- 参数校验：`hours < 0 or hours > 8760` → `{"code": 1, "msg": "hours 参数非法（0=全部，1-8760 小时）"}` 且不触达聚合函数；非 int 由 FastAPI 422（既有行为，测试断言锁定）。
- fail-open：`except Exception` + `logger.warning("看板查询失败（fail-open）: %s", e)`（带性质注释，非裸 except）→ code 1 不 500（读侧哲学对齐 072，区别于 083 审批写侧 fail-closed）。聚合结果 `data` 原样透传不被改写。
- 无新鉴权（与 /ai 现有端点同等待遇，083 approvals 先例）。

### WP-C tests/api/test_dashboard.py（26 项，hermetic）
- TestRowsToRequests 4 / TestRowsToLatency 3 / TestRowsToCost 3 / TestRowsToTools 3 / TestGetDashboardMetrics 5（4 SQL 顺序+文本口径 / 唯一 :since 绑定+hours 偏移 / hours=0 → 1970 / 四键+window ISO 字段 / 异常上抛）/ TestEndpoint 6（200 形状四指标键齐 / fixture 逐字透传 / 缺省 24+168/720/0 透传 / 非法 hours code 1 零触达 / 异常 fail-open 200 不 500 / hours=abc → 422）/ TestSQLHygiene 2（无 f-string/format/% 残留 + 全程只读）。
- `_FakeSession` 按序弹出预置结果并记录 (SQL, params)（对齐 test_tool_call_logs.py:34-51 打桩模式，扩展 _FakeResult 支持 fetchall/first）；端点用例 httpx ASGITransport + monkeypatch `main.get_dashboard_metrics`（对齐 test_observability 接线用例模式）。**conftest 零改动**（读侧测试不落库不污染，无新开关）。

### WP-D 前端（AC-26/27/29/32）
- `services/observabilityService.ts`：`DashboardMetrics` 类型内聚本文件导出（不进 types/rag.ts，plan §5 裁定）；`getDashboard(hours)` → `aiHttp.get('/observability/dashboard', { params: { hours } })`，code!==0 抛 Error(msg)（对齐 resumeService 错误策略），网络异常上抛。
- `pages/DashboardPage.tsx`（187 行 TSX ≤ 200 软约束）：窗口 Select（24/168/720/0 枚举约束无自由输入口）+ 刷新按钮（不做轮询）；四指标卡（请求总数+副行错误数 / 成功率% / P50+P95 ms / Token 总量+供应商分桶副行）；by_endpoint 简表 + by_tool 表（工具/次数/失败/耗时 P95，后端已按 calls 降序）；Spin / Alert（fail-open 不白屏）/ Empty。**null 一律"—"**（fmtMs/fmtRate 统一处理）。
- 实测坑（入档）：antd Statistic **对字符串数值同样套千分位分组**（146912 → "146,912" 且逗号独立 span 拆散文本断言）→ 统一 `groupSeparator=""` 传字符串值，渲染确定可断言。
- `App.tsx` +import + `<Route path="/dashboard">`（AppLayout 包裹）；`AppLayout.tsx` navItems 增 `{ key: '/dashboard', label: '观测看板' }`（+1 行）。

### WP-E 前端测试
- `observabilityService.test.ts` 4 项（GET 路径+params 断言 / code=0 解包 / code!=0 抛错含 msg / 网络异常上抛；vi.mock('../api/client')）。
- `DashboardPage.test.tsx` 3 项（fixture 四指标核心数字 ≥7 处断言 / 请求失败 Alert 不白屏且卡片不渲染 / 空窗口 null 全"—"且无 NaN/undefined；vi.mock service 层）。jsdom 无 ResizeObserver（antd Table 依赖）→ **测试文件内 vi.stubGlobal 就地 stub，共享 setup.ts 零改动**。

### WP-F 回归收口
- 全量回归未跑（Tester 的活）；Developer 自测范围见 §四。红线核验：`git diff --stat -- ai_service/src/observability.py` 为空（零 diff）；config.py/database.py/requirements.txt/react.py 等工作树 diff 均为 083/084 未提交遗留（本模块零触碰，文件清单见 AC-42 核对）。

## 三、行数统计（铁律 2，AST 语句口径）

| WP | 文件 | 行数 |
|----|------|------|
| WP-A | src/dashboard.py（新） | **37**（AST 语句；全文件 156 行含 docstring/SQL 注释） |
| WP-B | main.py（改，085 归属部分） | 9（端点函数体 AST）+ 1（import 行）≈ **10**（源码行：1 import + 19 端点块） |
| **合计** | | **47 ≤ 200 ✓**（预估 ~95，实际更精简——SQL 常量为单赋值语句、纯函数压缩） |
| WP-C | tests/api/test_dashboard.py（新，不计入） | 239（AST 语句，测试代码） |

前端（不计入 Python 生产行数口径，module-064 先例）：

| 文件 | 行数（wc -l） |
|------|------|
| pages/DashboardPage.tsx（新） | 187（≤ 200 软约束 ✓） |
| services/observabilityService.ts（新） | 70 |
| App.tsx（改） | +9（import 1 + 路由块 8） |
| components/AppLayout.tsx（改） | +1（nav 项） |
| __tests__/observabilityService.test.ts（新，测试） | 77 |
| __tests__/DashboardPage.test.tsx（新，测试） | 105 |
| **前端合计（生产）** | **~267 行 TS/TSX** |

方法长度：最长 `get_dashboard_metrics` 9 语句 ≤ 50 ✓；类数 0 ≤ 500 ✓；public 函数（get_dashboard_metrics / get_observability_dashboard / getDashboard）均有 docstring ✓；无 print、无裸 except（唯一 except 带 logger.warning + fail-open 性质注释）✓。

## 四、测试结果（Developer 自测，2026-09-06）

| 验证 | 命令 | 结果 |
|------|------|------|
| 定向 | `.venv/Scripts/python.exe -m pytest tests/api/test_dashboard.py -q` | **26 passed**（29.88s） |
| 受影响存量 | `.venv/Scripts/python.exe -m pytest tests/api/ tests/agent/test_tool_call_logs.py -q` | **147 passed**（38.53s，含 test_observability / test_main / test_tool_call_logs，存量零改动实证） |
| py_compile | dashboard.py / main.py / test_dashboard.py | COMPILE OK |
| 前端 build | `cd frontend && npm run build` | tsc strict + vite build **PASS**（built in 10.12s） |
| 前端测试 | `npx vitest run` | **63 passed / 9 文件全绿**（含新增 2 文件 7 项；ChatPage 既有 3 failed 亦全绿——基线 3 failed 未复现，优于存量基线） |
| 红线核验 | `git diff --stat -- ai_service/src/observability.py` | 空（零 diff）；写入侧/DDL/config/requirements 零触碰 |

（全量 pytest 回归未跑——按分工归 Tester；预期 1564+26=1590 passed / 2 failed（real_redis 环境性）/ 3 skipped。）

## 五、遗留与明确不做

- plan §7 明确不做逐条继承：金额/单价换算（module-089 预算账本口径）、时间序列趋势图/按天分桶、trace 级明细与 span 树（module-088）、identity 维度过滤、自动刷新/轮询、聚合缓存、端点白名单过滤（probe-* 行如实进统计）、tool_call_logs 按 endpoint 细分；无新 ADR。
- **Tester 待办**（AC 命令表 §6）：全量回归 + 真实 PG 四条对账 SQL 逐值比对（"数据与落库一致"验收实质）+ uvicorn 冒烟（hours=0 / hours=-1 curl）+ 浏览器页面冒烟（http://localhost:3001/dashboard）。Developer 环境未启动服务，端点真实性由 ASGITransport 端点用例 + hermetic 单测覆盖，真实 SQL 语义（percentile_cont/jsonb_each）无法在假 session 下覆盖，已按 plan §1 决策 6 如实分层。
- `datetime.utcnow()` 按 plan 钉死采用（Python 3.12+ DeprecationWarning 但功能正常；全库 created_at 为 naive TIMESTAMP 口径一致）；若未来升 Python 需全局统一换 `now(timezone.utc)`，不在本模块。
- 前端 vitest 基线说明：plan §6 备案"ChatPage 3 failed 为既有环境性失败"，本轮实测 63/63 全绿（3 failed 未复现），较基线偏好，无回归。
