# 测试报告 — Module-085 可视化看板（成功率 / 延迟 P95 / 成本(token) / 工具调用次数）

> Tester: 2026-09-06 | 测试对象：`specs/module-085-observability-dashboard/`（plan.md v2 / acceptance-criteria.md / changelog.md / review-report.md）+ 2 个新增后端文件（dashboard.py / test_dashboard.py）+ 4 个新增前端文件 + 3 个修改文件（main.py / App.tsx / AppLayout.tsx）
> 测试方法：命令表全项独立复跑（不采信 changelog/review-report）+ **真实 PG 对账（独立双实现逐值比对 = "数据与落库一致"验收实质）** + 全量差异逐根因重跑归类 + 红线 git diff 逐文件归属甄别 + uvicorn 独立冒烟（8010 端口）+ AC-38 真实 chat 落库终证 + AST 行数/方法长度独立复算 + 3 项 LOW 逐项独立验证
> 对账方法说明：一次性只读 asyncpg 脚本（系统临时目录，SELECT only，用后即删零痕迹）——侧 A = `dashboard.get_dashboard_metrics` 被测实现（PG percentile_cont 口径）；侧 B = 本脚本独立 Python 聚合（**完全独立实现**：直接计数 + 连续插值 P95 手算 + 逐桶累加），窗口取被测返回的 `window.since` 保证同窗可比

## 1. 验证命令执行结果（独立复跑）

| 验收项 | 验证命令 | 预期 | 实际 | 状态 |
|--------|---------|------|------|------|
| 定向单测 | `pytest tests/api/test_dashboard.py -q` | 26 passed | **26 passed, 2 warnings（16.81s）** | ✅ |
| 全量回归 | `pytest tests/ -q` | 基线新增 0 失败 | **1592 passed / 0 failed / 3 skipped / 164 warnings（127.53s）**，差异逐项归因见 §2（新增 0 失败成立，2 项基线失败反因环境改善转绿） | ✅ |
| 受影响存量 | `pytest tests/api/ tests/agent/test_tool_call_logs.py -q` | 全绿（存量零改动） | **147 passed, 2 warnings（18.89s）** | ✅ |
| py_compile | `py_compile src/dashboard.py main.py src/observability.py` | OK | **PY_COMPILE OK** | ✅ |
| 前端 build | `cd frontend && npm run build` | tsc + vite PASS | **PASS（built in 7.00s）** | ✅ |
| 前端测试 | `npx vitest run` | 63/63（含新增 7） | **9 files / 63 passed（7.59s，含 DashboardPage 3 + observabilityService 4）** | ✅ |
| 写入侧红线（AC-37） | `git diff --stat -- ai_service/src/observability.py` | 空 | **空（零 diff 实证）** | ✅ |
| uvicorn 冒烟 | 8010 端口 6 组 curl（hours=24/0/-1/8761/8760/abc） | {code,msg,data} + fail-open + 校验 | 全过（§4） | ✅ |
| 真实 PG 对账 | asyncpg 只读脚本（临时目录，用后删） | 四指标逐值一致 | **hours=0/hours=24 双窗口全部逐值一致**（§3） | ✅ |
| AC-38 落库终证 | 真实 chat 请求 + 行数前后对账 | request_logs 照常 +1 | **31 → 32**（endpoint=chat，timings/usage 如实落库） | ✅ |
| .env 核验 | grep PW_MCP_TOKEN/PW_JWT_SECRET | 存在即用 | **两项均在，.env 零改动（无需备份恢复）** | ✅ |

## 2. 全量回归差异逐根因归类（预期 1590/2/3 vs 实测 1592/0/3）

| # | 差异 | 根因（独立复跑证据） | 归类 |
|---|------|---------------------|------|
| 1 | **-2 failed / +2 passed**（2 项 real_redis 基线失败不再失败） | socket 探测 127.0.0.1:6379 返回 **+PONG**（Redis 本轮验收时已启动）；逐项重跑 `pytest tests/api/test_llm_chain.py tests/core/test_cache.py -k real_redis` → **2 passed, 28 deselected**（`test_set_get_roundtrip_real_redis` + `test_prefix_invalidation_real_redis`） | 环境性（Redis 由未启动变为可达，非本模块行为变化；与 083/084 基线中该 2 项失败同源） |
| — | **算术自洽校验** | 基线 1564+2+3=1569 收集量，+26 新增 = **1595**；实测 1592+0+3 = **1595** ✓ 逐项对账无缺漏 | — |
| — | 运行时长附注 | 127.53s（预估约 7 分钟）——Redis 可达后 2 项用例不再等待连接超时，与 #1 同因佐证 | — |

**结论：新增 0 失败成立（实测 0 failed 优于基线）；2 项差异全部为 Redis 可达性环境改善，非本模块行为变化。**

## 3. 真实 PG 对账（"数据与落库一致"验收实质）

库：`postgresql://localhost:5432/personal_website`（Planner 探测口径复现：request_logs **31 行** / tool_call_logs **467 行**）。侧 B 为独立实现（非复用 dashboard SQL），P95 采用与 PG `percentile_cont` 相同的连续插值定义在 Python 侧手算。

### 3.1 窗口 hours=0（全量）——四指标逐值比对

| 指标 | A：被测 `get_dashboard_metrics(0)` | B：独立手工聚合 | 一致 |
|------|-----------------------------------|----------------|------|
| requests | total=31, errors=1, success_rate=**0.9677**, by_endpoint=[chat_stream 14/0, agent 7/1, chat 5/0, agent-lg 4/0, probe-engine.chat 1/0] | 同左（逐 endpoint 逐值） | ✅ |
| latency | p50_ms=**13926.3**, p95_ms=**38882.24**, samples=**29** | 同左（Python 独立连续插值逐位一致，无浮点尾差） | ✅ |
| cost | total_prompt=**197277**, total_completion=**37315**, by_provider=[deepseek 185020/36598, **'llm' 12257/717**] | 同左（逐桶逐值） | ✅ |
| tools | total=**467**, by_tool 9 行：search_knowledge 285/0/5578.2、search_fts 102/0/9.95、recall_memory 24/0/8441.2、search_vector 23/0/202.6、generate_answer 11/0/15016.5、re_search 9/0/3411.2、extract_entities 7/0/3883.5、search_graph 4/0/1610.0、write_file 2/2/0.0 | 同左（逐行逐值，含 duration_p95） | ✅ |

### 3.2 窗口 hours=24——空 timings 行双口径分置的真实数据实证

24h 窗口恰好只覆盖 1 行 request_logs（正是 agent error=true、timings={} 的样例行）：

| 指标 | A：被测 | B：独立手工聚合 | 一致 | 说明 |
|------|--------|----------------|------|------|
| requests | 1 / 1 / success_rate=0.0, [agent 1/1] | 同左 | ✅ | 空 timings 行**计入**请求数与成功率分母 |
| latency | **null（整体）** | (None, None, 0) → 整体 None | ✅ | 空 timings 行**排除出**延迟分布；窗口无非空样本 → latency=null 不伪造 |
| cost | 0 / 0 / [] | 同左 | ✅ | usage={} 不进桶（AC-22） |
| tools | 2, [write_file 2/2/0.0] | 同左 | ✅ | tool_call_logs 按自身 created_at 独立过滤 |

### 3.3 专项探针（只读）

| # | 探针 | 结果 | 对应口径 |
|---|------|------|---------|
| 1 | 空 timings 行盘点：`timings IS NULL OR timings::text='{}'` | **2 行**（agent-lg error=False + agent error=True）；非空 timings **29 行**；requests.total=31（含 2 空行）vs latency.samples=29（不含）→ 分置 **OK** | plan §口径/AC-16：**error=true 与 error=false 的空 timings 行均同规则分置**（两行分别实证） |
| 2 | _SQL_COST COALESCE 路径：真实库缺 prompt/completion 键的桶 | 真实行数 **0**（防御性路径真实数据未触发）；**PG 合成空桶探针**：`jsonb_each('{"ghost":{}}')` 上 `SUM(...)=NULL` → `COALESCE(...,0)=0`，SQL 层 COALESCE 语义在真实 PG 实证 | AC-23（Developer 二选一裁定 COALESCE 兜 0，SQL 层兑现验证） |
| 3 | 'llm' 历史桶 | by_provider 含 **['deepseek','llm']** 两桶，'llm' 12257/717 原样保留不合并 | AC-17 |
| 4 | 探针数据如实进统计 | by_endpoint 含 **probe-engine.chat**；by_tool 含 **write_file**（084 探针，2/2 全失败） | AC-19 |
| 5 | hours=8760 大窗口 | 函数直调 + HTTP 冒烟双验证：正常返回 31/29/467，code 0 | AC-24 |
| 6 | hours=1 空窗口 | total=0 + success_rate=None + latency=None + cost (0,0)+0 桶 + tools 0 行——**null 语义不伪造 0/1** | AC-20 |
| 7 | 读写联动（冒烟期新行） | 真实 chat 新落库行（chat/error=true/usage={}）被看板实时吸收：32/2/**0.9375** = round(30/32, 4) 精确 | "数据与落库一致"动态终证 |

## 4. uvicorn 冒烟（8010 端口，独立进程）

前置：.env 已含 PW_MCP_TOKEN / PW_JWT_SECRET（**零改动、无需备份恢复**）；lifespan 正常（PG 表全就绪 + Redis 连接成功 + 模型预热完成）。

| curl | HTTP | 响应 | 判定 |
|------|------|------|------|
| `?hours=24` | 200 | `{"code":0,"msg":"success","data":{window,requests,latency:null,cost,tools}}` 五键齐，latency=null 为该窗口真实语义（§3.2） | ✅ |
| `?hours=0` | 200 | code 0 全量四指标，与对账表 §3.1 逐值一致（since=1970-01-01T00:00:00 实证 AC-6） | ✅ |
| `?hours=-1` | 200 | `{"code":1,"msg":"hours 参数非法（0=全部，1-8760 小时）"}` msg 逐字一致，不 500 | ✅ |
| `?hours=8761` | 200 | 同上 code 1（上界外拒绝） | ✅ |
| `?hours=8760` | 200 | code 0 正常返回（合法上界，AC-24） | ✅ |
| `?hours=abc` | **422** | FastAPI `int_parsing` 既有行为，未触达聚合 | ✅ |

收尾：进程已终止（TaskStop + 端口复核 connection refused，**杀干净确认**）。

## 5. Reviewer 3 LOW + 2 备忘独立验证（逐项）

| # | Reviewer 发现 | 独立验证 | 结论 |
|---|--------------|---------|------|
| LOW-1 | changelog"get_dashboard_metrics 9 语句"实为 8 | AST 独立复算：**含 docstring=8 / 不含=7**（与 Reviewer 复算一致；changelog 记 9 系 docstring 计数口径差） | **属实，非阻塞**（文档数字微差，双口径均远 ≤50，建议按"含 docstring 8 / 不含 7"勘误） |
| LOW-2 | changelog"受影响存量 147"实含新增 26 | `pytest tests/api/ --collect-only` = **135**（其中 test_dashboard.py 26 → 严格存量 109）+ test_tool_call_logs.py collect = **12** → 严格存量 **121**；147 = 121 + 26 | **属实，非阻塞**（计数本身准确可复现，仅标签口径偏松，"存量零改动实证"结论不变） |
| LOW-3 | DashboardPage 刷新失败保留旧 metrics 与 Alert 并存（首载失败无卡片） | DashboardPage.tsx L78-88 `load` 的 catch 仅 `setError` 不清 metrics；L115 Alert 与 L121 metrics 卡片渲染条件独立并存；首载失败 metrics=null → 仅 Alert 无卡片 | **行为描述准确，非阻塞**（刷新失败时旧数据与错误 Alert 并存：有 Alert 明示不误导、无 NaN/崩溃，符合 fail-open 不白屏精神；两条路径行为不一致属体验瑕疵非缺陷，可按 Reviewer 建议统一或声明） |
| B1 | 铁律 7 模板 timestamp/request_id 全库无先例 | main.py 端点 `{code,msg,data}` 与 083 approvals GET 同构（读证一致） | 确认属项目层面既有口径，非本模块缺陷，无需动作 |
| B2 | 合法上界 8760 无显式 hermetic 断言 | 属实；但 AC-24 已由 Tester 真实验证补位（§4：hours=8760 curl → code 0） | 备忘成立，实际覆盖已闭环，无需动作 |

## 6. 环境受限项（如实标注）

1. **浏览器 /dashboard 页面人工冒烟（AC §6 末行）未执行**：本轮验收为自动化代理运行，无浏览器交互通道。替代覆盖充分：DashboardPage.test.tsx 渲染断言（fixture 四指标数字 8 处 / 失败 Alert / 空态"—"无 NaN）全绿 + `tsc strict + vite build` PASS + 路由/nav diff 核验。属验收通道受限，非代码缺陷项。
2. **fail-open 的 HTTP 级真实 DB 停机触发未做**：PG 可达是本次真实对账冒烟的前提，按"除冒烟必需外不动环境"原则不人为停库。AC-13 由单测（ASGITransport mock 聚合抛异常 → 200 + code 1 + msg 逐字）+ 代码路径（main.py L1299-1302 except 带 logger.warning + fail-open 注释）覆盖。

## 7. 验收标准核对（AC-1 ~ AC-42 逐项）

### 7.1 功能验收
| AC | 验证证据（独立复跑/代码实证） | 结论 |
|----|------------------------------|------|
| AC-1 4 条 SQL 全参数化 | dashboard.py L26-71 四常量纯文本、唯一 `:since` 绑定（L122/124/126/128）；TestSQLHygiene 双断言绿；hours 仅 Python 侧换算不入 SQL | ✅ |
| AC-2 _rows_to_requests | L74-81（round 4 位/total=0→None）+ 单测 4 项绿 + 对账 0.9677/空窗口 None 实证 | ✅ |
| AC-3 _rows_to_latency | L84-89（无行/NULL→整体 None）+ 单测 3 项绿 + 对账 hours=24 latency=null 实证 | ✅ |
| AC-4 _rows_to_cost | L92-98（total 桶求和）+ 单测 3 项绿 + 对账逐桶一致 | ✅ |
| AC-5 _rows_to_tools | L101-105（total=calls 求和）+ 单测 3 项绿 + 对账 9 工具逐行一致 | ✅ |
| AC-6 :since 绑定 | L118-119（0→1970/否则 utcnow-offset）+ 单测绑定值区间断言绿 + 冒烟 window.since 实证（0→1970-01-01；24→utcnow-24h） | ✅ |
| AC-7 顺序执行四键齐 | L120-135（requests→latency→cost→tools）+ 单测绿 + 冒烟 data 五键实证 | ✅ |
| AC-8 SQL 文本口径 | test_four_sqls_in_order_with_metric_semantics 逐段断言绿（percentile_cont/jsonb_each_text/IS NOT NULL/jsonb_each/::bigint/CASE WHEN） | ✅ |
| AC-9 聚合层异常上抛 | dashboard.py grep **0 处 except/0 处 print** + test_db_error_propagates 穿透断言绿 | ✅ |
| AC-10 端点 200 形状 | 冒烟 hours=24/0 → 200 `{code:0,msg:"success",data}` 字段名与 plan §8 契约逐字一致 | ✅ |
| AC-11 缺省/透传 | main.py `hours: int = 24` + 单测（168/720/0 透传）绿 + 冒烟 hours=0 实证 | ✅ |
| AC-12 参数校验 | 冒烟 -1/8761 → code 1 msg 逐字；abc → 422；单测 `not agg.called` 零触达绿 | ✅ |
| AC-13 fail-open | 单测（mock 抛异常 → 200 + code 1 + msg 逐字）绿；HTTP 级真实触发环境受限（§6-2），代码路径读证一致 | ✅（单测覆盖） |
| AC-14 结果透传 | 单测 fixture 逐字相等（deepcopy）绿 | ✅ |
| AC-15 成功率口径 | 对账 errors=1 计入分母（31/1→0.9677）；新 error 行落库后 32/2→0.9375 实时复算精确 | ✅ |
| AC-16 延迟口径 | 对账 PG percentile_cont 与独立 Python 连续插值逐位一致；空 timings 2 行排除出分布（samples=29）但计入请求数（total=31）——双口径独立实证 | ✅ |
| AC-17 成本口径 | 对账 by_provider=['deepseek','llm'] 历史桶原样保留；表无价格字段、无金额换算（代码读证） | ✅ |
| AC-18 工具口径 | 对账 9 工具 calls/failures/duration_p95 逐行一致；SQL 按自身 created_at 过滤无 JOIN；duration_p95_ms 兑现 083 WP-C 预留 | ✅ |
| AC-19 探针行如实 | probe-engine.chat（endpoint）+ write_file（tool）均如实进统计，无 WHERE 特判（代码读证） | ✅ |

### 7.2 边界条件
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-20 空窗口 | get_dashboard_metrics(1) 真实调用：total=0/success_rate=None/latency=None/cost 0+空桶/tools 空——不崩不伪造 | ✅ |
| AC-21 单样本 | 单测绿（percentile_cont 对 1 行返回该值 P50=P95）；真实口径已由对账双实现交叉验证 | ✅ |
| AC-22 usage 空 {} 行 | 对账 Python 侧跳过空 usage 与被测一致（31 行中 28 行非空 usage，cost 总量仅含非空桶）；jsonb_each 空展开不产桶 | ✅ |
| AC-23 缺 completion 键防御 | **PG 合成空桶探针：SUM→NULL，COALESCE 后=0**（SQL 层实证）+ 单测 fixture 绿 + changelog 已声明二选一裁定 | ✅ |
| AC-24 hours=8760 大窗口 | 函数直调 + HTTP 冒烟双验证正常返回（31/29/467） | ✅ |
| AC-25 前端 null 渲染 | DashboardPage.test.tsx 空窗口断言（≥3 处"—"、无 NaN/undefined）绿 + fmtMs/fmtRate 统一处理 | ✅ |

### 7.3 前端
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-26 observabilityService | 4 项单测绿（GET 路径+params/code=0 解包/code!=0 抛 Error(msg)/网络异常上抛）；aiHttp 复用（client.ts 拦截器 Bearer） | ✅ |
| AC-27 DashboardPage 结构 | 文件读证（窗口 Select 24/168/720/0 枚举 + 刷新 Button + 四指标卡 + by_endpoint 表 + by_tool 表 + Spin/Alert/Empty）+ vitest 绿 | ✅ |
| AC-28 页面 vitest | 3 项绿（四指标数字 8 处断言/失败 Alert 不白屏/空态"—"） | ✅ |
| AC-29 路由导航 + build | App.tsx +8（/dashboard Route AppLayout 包裹）+ AppLayout navItems +1（"观测看板"）diff 归属纯粹；`npm run build` PASS（7.00s） | ✅ |
| AC-30 vitest 基线 | **63/63 全绿（9 files）**含新增 7 项；存量前端测试文件零改动（git status 仅新增两测试文件，setup.ts 零 diff） | ✅ |

### 7.4 异常场景
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-31 DB 不可用链 | AC-13 单测（后端 code 1）+ 前端 Alert 测试（service 抛 Error → 页面 catch）绿；HTTP 级真实触发环境受限（§6-2） | ✅（单测覆盖） |
| AC-32 前端传参边界 | WINDOW_OPTIONS 枚举约束无自由输入口（代码读证）；hours=0 冒烟 code 0（"全部"语义实证） | ✅ |
| AC-33 并发只读安全 | 4 条 SQL 纯 SELECT（词边界正则单测绿 + 对账实测同文）；无 INSERT/UPDATE/DELETE | ✅ |
| AC-34 SQL hygiene | 唯一 `:since` 参数化 + hours 永不入 SQL 文本 + TestSQLHygiene 绿（0 f-string/% 残留） | ✅ |

### 7.5 非功能
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-35 全量零新增失败 | **独立复跑 1592 passed / 0 failed / 3 skipped**；2 项基线失败因 Redis 可达转绿（§2 逐根因：socket +PONG + 定向重跑 2 passed）；算术 1595=1595 自洽 | ✅ |
| AC-36 存量测试零改动 | 受影响存量 147/147 全绿；git status 无存量测试文件修改（conftest.py 修改为 084 遗留，diff 0 处 dashboard 关键词甄别） | ✅ |
| AC-37 写入侧红线 | **observability.py 零 diff 实证**；main.py diff 无 persist_request_log 触碰（085 归属仅 import 1 行 + 端点块 19 行纯新增）；config.py/database.py/requirements.txt diff 0 处 dashboard 关键词（083/084 归属甄别） | ✅ |
| AC-38 落库行为不受影响 | **真实 chat 冒烟：request_logs 31 → 32**（endpoint=chat，error=true，timings 6 阶段/usage={} 如实落库）——写入侧零回归终证 | ✅ |
| AC-39 行数 ≤200 | AST 语句口径独立复算：dashboard.py **36**（不含 module docstring）/37（含）+ main.py 085 归属 ~9-10 → **45-47 双口径 ≤200** | ✅ |
| AC-40 方法 ≤50 + docstring | get_dashboard_metrics **8 语句**（含 docstring，Reviewer LOW-1 口径）/7（不含）≤50；三 public 函数 docstring 齐（读证）；DashboardPage.tsx **187 行**（wc -l）≤200 | ✅ |
| AC-41 无空 catch/无 print | dashboard.py 0 except 0 print（grep 实证）；main.py 唯一 except 带 logger.warning + "# fail-open" 性质注释；main.py 0 print | ✅ |
| AC-42 变更文件范围 | git status 甄别：新增 6 文件 + 修改 3 文件恰为 plan §7 清单；其余工作树 diff（config/database/requirements/conftest/react/tool_registry/langgraph_react/hhem_loader）**0 处 dashboard 关键词** → 083/084/环境遗留零 085 归属 | ✅ |

## 8. 已知边界 / 备注

1. **全量数字优于基线**：1592/0/3 vs 预期 1590/2/3——2 项 real_redis 基线失败因 Redis 6379 本轮已启动转绿（§2 归因），红线实质（新增 0 失败、存量零改动）成立。
2. **冒烟期新增 1 行真实数据**：AC-38 终证产生的 chat 行（error=true，LLM 侧 internal_error 兜底，与 module-085 读侧无关）为正常业务写入非测试污染；对账表 §3.1/3.2 数字为该行落库前快照，落库后看板实时复算一致（§3.3 #7）。
3. **LOW-1/LOW-2 为文档口径微差**：建议后续随文档勘误（9→8 语句；147=26 新增+121 存量注记），不阻塞闭环。
4. **AC-13/AC-31 的 HTTP 级真实触发**以单测 + 代码路径覆盖（§6-2）；**浏览器页面人工冒烟**以页面渲染测试 + build 覆盖（§6-1）。两者均为验收通道受限的如实标注，替代覆盖充分。
5. 全量 164 warnings 为存量 Pydantic/废弃警告源（含 `datetime.utcnow()` DeprecationWarning，plan 钉死沿用口径），非本模块引入。
6. 对账脚本为一次性只读（SELECT），已删除（临时目录零残留）；.env 零改动；uvicorn 进程已杀净（端口复核）。

## 9. 验收结论

- 审查人: Reviewer（2026-09-06，0 阻塞 / 0 重大 / 3 LOW 非阻塞 + 2 备忘，已通过）
- 测试人: Tester（2026-09-06）
- 验收时间: 2026-09-06
- 结论: **[x] 通过**
- 统计: **验收通过 42/42**
- 备注: 定向 26/26 + 受影响存量 147/147 + 全量 **1592/0/3**（2 基线失败因 Redis 启动转绿，新增 0 失败）+ 前端 build PASS + vitest 63/63 + py_compile 3/3 + 写入侧红线零 diff。**核心验收（"数据与落库一致"）：真实 PG 双窗口独立双实现对账四指标逐值一致**（含 P95 连续插值逐位吻合、'llm' 历史桶逐桶核对、空 timings 2 行在成功率与延迟分布两口径的分置、COALESCE 路径 PG 级合成探针、探针行如实进统计、空窗口 null 语义）；uvicorn 8010 冒烟 6 组 curl 全过（含 422/code 1/上界 8760）；AC-38 真实 chat 落库 +1 终证 + 新行被看板实时吸收。Reviewer 3 LOW 逐项独立验证属实且均非阻塞（文档计数口径差 ×2 + 刷新失败保留旧数据的行为描述准确），2 备忘确认无需动作。
