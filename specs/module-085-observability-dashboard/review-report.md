# 审查报告 — Module-085 可视化看板（成功率 / 延迟 P95 / 成本(token) / 工具调用次数）

> Reviewer: 2026-09-06 | 审查对象：`specs/module-085-observability-dashboard/`（plan.md v2 / acceptance-criteria.md / changelog.md）+ 6 个新增文件（dashboard.py 156 物理行 / test_dashboard.py 367 行 / observabilityService.ts 70 行 / DashboardPage.tsx 187 行 / 两前端测试文件）+ 3 个修改文件（main.py / App.tsx / AppLayout.tsx）
> 审查方法：全文件通读 + 独立测试复跑（后端 26/147 + py_compile + 前端 build/vitest）+ git diff 逐文件归属甄别 + AST 行数/方法长度机械化复算 + 铁律 7 返回格式与项目全部 GET 端点逐字比对 + 两处授权偏离（samples / COALESCE）正当性专项复核
> 083/084/085 归属区分口径：工作树混有 module-083/084 未提交遗留 diff，085 归属按"变更内容是否与看板相关"判定，逐文件甄别（见 §6 红线核验）

## 1. 审查结论

- **结论：✅ 通过（PASS）（0 阻塞 / 0 重大 / 3 项 LOW 非阻塞 + 2 项备忘）**

协调者指定的 10 项重点核查全部实测通过。4 条 SQL 全参数化（唯一绑定 `:since` 为 Python 侧 datetime，hours 永不入 SQL 文本，零注入面）；4 指标口径与 plan §1 决策 2 逐条一致（空窗口 null 不伪造 0/1、空 timings 行排除出分布但计入成功率、'llm' 历史桶原样保留）；2 处授权偏离（latency 加 COUNT samples / cost COALESCE 兜 0）均确在 plan/AC 授权范围内且 changelog 如实记录；fail-open 链（聚合层上抛 → 端点层 code 1 不 500 → 前端 Alert）逐环节成立；返回格式与 083 approvals GET 先例逐字对齐；红线文件（observability.py 零 diff 实证 + react.py/database.py/mcp_server.py/engine.py/router.py/requirements.txt/config.py 对 085 零归属）经 git diff 甄别成立；行数 AST 独立复算 dashboard.py **37 语句**与 Developer 声明逐字一致（085 合计 ~46-47 ≤ 200）；26 项定向 + 147 项受影响存量独立复跑全绿；前端 build PASS + vitest 63/63 全绿。

## 2. 重点核查表（协调者指定 10 项）

| # | 核查项 | 结论 | 证据（文件:行号） |
|---|--------|------|------------------|
| 1 | **SQL 全参数化** | ✅ | dashboard.py 4 条 SQL（L26-34/L38-47/L51-59/L62-71）均为纯文本常量，唯一绑定参数 `:since`（4 条各绑定 1 次，dashboard.py:122/124/126/128）；**hours 从不进 SQL**——仅在 Python 侧换算 `since = utcnow - timedelta(hours)` 或 `datetime(1970,1,1)`（L118-119）后作为 datetime 绑定值，无数字内插；grep 实证 dashboard.py 0 处 f-string、测试 TestSQLHygiene 双断言（无 `{}`/`%s` 残留 test_dashboard.py:354-359 + 词边界只读正则 L361-366）；`jsonb_each(usage)` 隐式 LATERAL 与 `jsonb_each_text` 用法对齐 plan 给定写法 |
| 2 | **指标口径与 plan 一致** | ✅ | ① 成功率：`SUM(CASE WHEN error THEN 1 ELSE 0 END)`（L29）+ 纯函数 `round((total-errors)/total, 4) if total else None`（L79）——error 列 NOT NULL DEFAULT FALSE（database.py:68）无 NULL 歧义，空窗口 None 不伪造 0/1；② P50/P95：`percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (ORDER BY total_ms)` on `SUM((v)::float8) FROM jsonb_each_text(timings)`（L39/L42），`WHERE total_ms IS NOT NULL`（L46）排除空 timings 行——该行仍被 `_SQL_REQUESTS` 计入分母（两口径独立）；**samples 追加合理**：plan §1 决策 2 明文"附样本数 samples"而 plan §2 给定 SQL 只取 percentile 数组无法产出，同聚合（同一过滤集）加一列 `COUNT(*) AS samples`（L40）是最小改动且 AC-8 要求的三段文本一字未动（test_dashboard.py:210-212 逐段断言）；③ 成本：`jsonb_each(usage)` 按供应商分桶 `::bigint`（L53-55），'llm' 历史桶原样透传不合并（`_rows_to_cost` L92-98 无合并逻辑 + test_buckets_and_totals 断言 by_provider==["deepseek","llm"]），无价格字段无金额换算；④ 工具：按 tool_name 分组 calls/failures/`percentile_cont(0.95) ... duration_ms`（L63-66），按自身 created_at 过滤不 JOIN（L68），探针行如实进统计（无 WHERE 特判） |
| 3 | **COALESCE(SUM,0) 偏离** | ✅ | AC-23 原文"PG COALESCE 或如实 NULL，Developer 二选一并在 changelog 声明"——选 COALESCE 属授权二选一，changelog §二 WP-A 已如实声明（"防单桶全缺 prompt/completion 键时 SUM 全 NULL……纯函数层再 or 0 双保险"）；**双保险口径一致**：SQL 层 `COALESCE(SUM(...), 0)`（dashboard.py:53-54）+ 纯函数层 `int(r[1] or 0)`（L94-95），两层均产出 0 而非 NULL，语义同向无分叉；单测 `test_null_completion_defense`（test_dashboard.py:159-165）覆盖（SQL 层兜 0 的行为语义由纯函数层 fixture 模拟，真实 SQL 语义归 Tester 对账，plan §1 决策 6 如实分层）。注：兜 0 后空窗口 cost 显示 `total 0 + 空分桶列表` 与 AC-20 一致 |
| 4 | **fail-open 链** | ✅ | ① 端点 DB 异常：main.py:1299-1302 `except Exception as e: logger.warning("看板查询失败（fail-open）: %s", e)` → `{"code": 1, "msg": "看板查询失败（fail-open）"}` 200 返回不 500（`test_agg_exception_fail_open_no_500` 断言 status_code==200 + code==1 + msg 逐字）；② 聚合层不吞：dashboard.py 全文 0 处 try/except（grep 实证），`get_dashboard_metrics` 异常自然上抛（docstring L109 明示"异常向上抛由端点层统一 fail-open"），`test_db_error_propagates` 断言 RuntimeError 穿透（test_dashboard.py:263-269）；③ hours 非法零触达：main.py:1296-1297 校验先于 try 块，非法直接 return code 1（`test_invalid_hours_code_1_without_agg` 断言 `not agg.called` L330） |
| 5 | **铁律 7 返回格式** | ✅（按项目先例） | 端点成功/失败返回 `{code, msg, data}` 三键（main.py:1297/1302/1303），与 083 approvals GET 先例 main.py:1252 `{"code": 0, "msg": "success", "data": ...}` **逐字同构**，msg 成功值同为 "success"；plan §1 决策 4 / §0 已钉死以 083 为对齐先例。注（备忘 B1）：skill 模板铁律 7 全文为 `{code, msg, data, timestamp, request_id}`，但 main.py 全部既有端点（L368/887/977/1199/1252 等）实际均只返回 `{code, msg, data}` 或 `{code, data}`，timestamp/request_id 全库无先例——本端点与项目现实一致，模板差异属项目层面既有口径，非本模块引入 |
| 6 | **铁律 3/4** | ✅ | 最长方法 `get_dashboard_metrics`：物理 29 行（dashboard.py:108-136）/ AST 8 语句（Reviewer 复算，含 docstring），`get_observability_dashboard` 物理 15 行（main.py:1289-1303）/ AST 8 语句，均 ≤50；public 函数 docstring 齐全：`get_dashboard_metrics`（Args/Returns，L109-117）、`get_observability_dashboard`（main.py:1290-1295）、`getDashboard`（JSDoc @param/@returns/@throws，observabilityService.ts:55-60）；3 个 `_rows_*` 私有函数亦带单行 docstring |
| 7 | **前端** | ✅ | ① 路由/nav：App.tsx `/dashboard` Route（AppLayout 包裹，diff +8 行）+ AppLayout.tsx navItems `{ key: '/dashboard', label: '观测看板' }`（+1 行），diff 归属纯粹；② Bearer 复用：observabilityService.ts:13 `import { aiHttp } from '../api/client'` + L62 `aiHttp.get('/observability/dashboard', {params:{hours}})`——aiHttp 由 createHttp 统一构造（client.ts:62-72 请求拦截器自动附 `Authorization: Bearer`），无新建实例零绕过；③ Statistic 就地处理：`MetricCard` 统一 `groupSeparator=""` + 字符串值（DashboardPage.tsx:59-69/127/147），**共享 setup.ts 零 diff**（git status 无该文件）；ResizeObserver stub 仅在测试文件内 `beforeAll + vi.stubGlobal`（DashboardPage.test.tsx:23-34）；④ 断言真实：页面测试逐数字断言 96.67%/31/错误 1/4100.5 ms/8200.0 ms/146912/search_knowledge/285 共 8 处（L66-74），失败用例断言 Alert 文案 + 卡片消失（L77-84），空窗口断言 ≥3 处"—" + 无 NaN/undefined（L86-104），非空跑 |
| 8 | **测试质量抽查** | ✅ | 26 项 hermetic：纯函数 13 项纯内存；`get_dashboard_metrics` 5 项经 `_FakeSession` 打桩（test_dashboard.py:68-88，对齐 test_tool_call_logs 模式）零真实 PG/Redis；端点 6 项 ASGITransport + monkeypatch `main.get_dashboard_metrics`（不发 lifespan、不触 DB）；断言实质性：SQL 文本逐段（L207-217）、`:since` 绑定值随 hours 偏移的区间断言（L228-231）、hours=0 绑定 1970（L239-240）、异常穿透（L268）、非法 hours `not agg.called`（L330）、透传 fixture 逐字相等（L305，deepcopy 防共享变更）；conftest 对 085 **零改动**（diff 仅 084 的 `default_mcp_external_disabled` fixture，conftest.py:271-291） |
| 9 | **行数（铁律 2）** | ✅ | Reviewer 独立 AST 语句口径复算：**dashboard.py = 37 语句**（与 changelog §三逐字一致；函数分解 6+4+3+3+8）；main.py 085 归属 = 1 import（L25）+ `get_observability_dashboard` 8 语句（changelog 记 9，差异系 docstring 语句计入口径，见 LOW-1）→ 085 合计 **~46 ≤ 200**（Developer 口径 47 亦 ≤ 200，双口径均过线）；前端 DashboardPage.tsx 187 行 / observabilityService.ts 70 行（wc -l 实测与声明一致），不计入 Python 口径（module-064 先例）；`get_dashboard_metrics` 9 语句声明值与复算 8 的微差同 LOW-1 |
| 10 | **AC 覆盖抽查** | ✅ | 见 §3 |

## 3. AC 覆盖抽查（协调者指定 4 项 + 补充）

| AC | 要求 | 对应测试 | 断言质量 |
|----|------|----------|----------|
| AC-8 | P95 口径（percentile_cont/jsonb_each_text/排除空行 文本断言） | `test_four_sqls_in_order_with_metric_semantics`（test_dashboard.py:198-217） | 到位：lat_sql 三段必含文本逐一断言（L210-212）+ cost（L213）+ tools（L214-217）+ requests（L207-209），并断言 4 条按 requests→latency→cost→tools 顺序（L205-206） |
| AC-23 | 成本口径防御（缺键 NULL → 二选一 + 声明 + fixture） | `test_null_completion_defense`（L159-165） | 到位：单桶 completion=None → by_provider 值 0 + total_completion==0；changelog §二 WP-A 声明在案（§2 #3） |
| AC-12 | hours 校验（非法 code 1 零触达 / 非 int 422） | `test_invalid_hours_code_1_without_agg`（L321-330）+ `test_non_int_hours_422`（L342-348） | 到位：-1/8761 双拒绝值 + "hours 参数非法" msg 包含断言 + `not agg.called`；abc → 422 + 零触达 |
| AC-13 | fail-open（200 code 1 不 500） | `test_agg_exception_fail_open_no_500`（L332-340） | 到位：status_code==200 + code==1 + msg 与端点实现逐字一致 |
| AC-2/3/5/6/7/9/10/11/14/20/21 | 补充抽查 | 纯函数 13 项 + metrics 5 项 + 端点其余 4 项 | 全部到位：空窗口 None 语义（L118-121）、单样本 P50=P95（L142-145）、唯一 `:since` 绑定 + 偏移（L219-231）、四键 + window ISO（L243-261）、异常上抛（L263-269）、透传逐字（L300-305） |

## 4. 问题列表（全部非阻塞）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | specs/module-085-observability-dashboard/changelog.md | §三 | 方法长度声明"最长 get_dashboard_metrics 9 语句"，Reviewer AST 复算为 **8 语句**（含 docstring Expr；main.py 端点同记 9 实为 8）。差异系 docstring 是否计入的口径差，双口径均远 ≤50，仅文档数字微差。 | LOW | 文档勘误即可（或统一声明"含 docstring 8 / 不含 7"） |
| 2 | specs/module-085-observability-dashboard/changelog.md | §四 | "受影响存量 147 passed" 的 147 中含本模块新增 26 项（tests/api/ 整目录 135 = 存量 109 + 新增 26，加 test_tool_call_logs 12）：严格存量口径应为 **121 passed**。计数本身准确可复现（Reviewer 复跑同为 147 passed），"存量零改动实证"结论不变，仅标签口径偏松。 | LOW | 文档注记 147 = 26 新增 + 121 存量即可 |
| 3 | frontend/src/pages/DashboardPage.tsx | 78-88, 115-121 | 刷新失败时 `load` 的 catch 只 setError 不清 metrics——旧数据卡片与错误 Alert 并存（首载失败则仅 Alert 无卡片，两条路径行为不一致且 changelog 未声明）。符合"fail-open 不白屏"精神且信息不误导（有 Alert 明示），非缺陷级。 | LOW | 如需一致：失败分支 `setMetrics(null)` 或在 changelog 明示"刷新失败保留旧数据 + Alert"为预期行为 |
| B1 | skill 铁律 7 模板 vs 项目现实 | — | （备忘）模板 `{code, msg, data, timestamp, request_id}` 中 timestamp/request_id 在 main.py 全部既有端点无先例；本端点对齐 083 先例 `{code, msg, data}`（plan §1 决策 4 钉死）。属项目层面既有口径，非本模块缺陷，无需动作。 | 备忘 | 如未来全库统一补 timestamp/request_id，应另立专项一次性对齐 |
| B2 | ai_service/tests/api/test_dashboard.py | 321-330 | （备忘）合法上界 hours=8760 无显式 hermetic 断言（仅 -1/8761 拒绝侧 + 168/720/0 透传侧）；AC-24 按设计归 Tester 真实 PG 冒烟。如需锁死边界可补 1 行 `assert_any_call(8760)`。 | 备忘 | 可选补充，不阻塞 |

## 5. 铁律合规检查

| 铁律 | 检查结果 | 证据 |
|------|----------|------|
| #2 新增生产代码 ≤200 行 | ✅ | AST 语句口径独立复算：dashboard.py 37 + main.py 085 归属 9（1 import + 8）= 46 ≤ 200（§2 #9）；测试代码 367 行与前端 ~267 行不计入 |
| #3 方法 ≤50 | ✅ | 最长 get_dashboard_metrics 物理 29 行 / AST 8 语句；get_observability_dashboard 物理 15 行 / AST 8；纯函数 3-6 语句 |
| #4 public 函数 docstring | ✅ | get_dashboard_metrics（Args/Returns）/ get_observability_dashboard / getDashboard（JSDoc）三处齐全 |
| #5 禁空 catch / 吞异常 | ✅ | dashboard.py 0 处 except（上抛设计，AC-9）；main.py 唯一 except 带 logger.warning + "# fail-open" 性质注释（main.py:1301）；grep 0 处 print |
| #8 日志禁敏感信息 | ✅ | main.py:1302 仅记录异常消息 e（无 token/密钥/args）；dashboard.py 无日志输出 |
| #9 禁 SQL 拼接 | ✅ | 4 条 SQL 纯常量 + 唯一 `:since` 绑定；0 处 f-string/`%`/`+` 拼接（§2 #1）；全程只读（TestSQLHygiene 词边界正则锁定） |
| #11 记忆收口 | ✅ | PASS 按流程更新三件套（file-index module-085 行 + activity-log [REVIEW]/[HANDOFF] + project-context 状态行） |

## 6. 红线核验（工作树遗留 diff 逐文件甄别）

| 文件 | 工作树 diff | 甄别结论 |
|------|-------------|----------|
| src/observability.py | 空（`git diff --stat` 无输出，Reviewer 独立复跑） | **零 diff，写入侧红线成立** ✅ |
| rag/retrieval/hhem_loader.py | +105（ONNX 双路径加载，"2026-09-01 扩展"） | **环境遗留**（与 requirements.txt onnxruntime==1.29.0 注记同源）；grep diff 0 处 dashboard/observability 关键词 → 085 零归属 ✅ |
| agent/react.py / src/database.py / requirements.txt / src/config.py / tests/conftest.py / agent/tool_registry.py / agent/langgraph_react.py | 混合 diff | **083/084 遗留**（084 review-report §6 已逐块甄别；本轮复核 conftest +21 全为 084 fixture、config +16 全为 083 三字段 + 084 四字段，0 处 085 归属内容）✅ |
| mcp_server.py / rag/engine.py / rag/router.py | 空（不在 git status 修改清单） | 零 diff ✅ |
| main.py | +107/-4 混合 | 085 归属仅 2 处：L25 import（1 行）+ L1285-1303 端点块（19 行含分隔注释），**零存量行改动**；其余为 083 审批端点/084 白名单接线（逐块读过 diff 确认）✅ |
| frontend/src/App.tsx / components/AppLayout.tsx | +9 / +1 | 全部为 085 归属（import + /dashboard Route；navItems 1 项），无夹带 ✅ |
| frontend/src/setup.ts / tests/api/test_observability.py / test_tool_call_logs.py / test_main.py | 空 / 空 | 零 diff，存量测试零改动 ✅ |
| config 新增 / 依赖新增 / 新表 | — | 零新增（config diff 无 085 字段；requirements 新增 3 行全为 083 jsonschema + openai 基线 + onnxruntime 遗留；DDL 零触碰）✅ |

## 7. 独立复跑输出（Reviewer，2026-09-06）

```
定向：     pytest tests/api/test_dashboard.py -q                → 26 passed, 2 warnings in 32.75s
受影响存量：pytest tests/api/ tests/agent/test_tool_call_logs.py -q → 147 passed, 2 warnings in 38.44s
           （= 存量 121 + 本模块新增 26；与 Developer 自测声明逐字一致）
py_compile：src/dashboard.py main.py src/observability.py          → PY_COMPILE OK
前端 build：cd frontend && npm run build                           → tsc + vite PASS（built in 10.56s）
前端测试：  npx vitest run                                         → 9 files / 63 passed（11.63s，与声明 63/63 一致）
行数审计：  AST 语句口径自动脚本 → dashboard.py 37 / get_observability_dashboard 8
           （085 合计 ~46 ≤ 200）；get_dashboard_metrics 8 语句（≤50）
           wc -l → DashboardPage.tsx 187 / observabilityService.ts 70（与声明一致）
收集核对：  pytest tests/api/ --collect-only → 135（其中 test_dashboard.py 26 → 严格存量 109+12=121）
红线核验：  git diff --stat -- src/observability.py → 空输出（零 diff）
           mcp_server.py / rag/engine.py / rag/router.py / frontend/src/setup.ts → 零 diff
```

## 8. 审查总结

### 8.1 读侧聚合链路——逐环节还原成立
1. **聚合层**（dashboard.py）：单 session 顺序 4 条参数化 SQL（L120-128）→ 4 个行→dict 纯函数（求和/round/None 语义，L74-105）→ `{window, requests, latency, cost, tools}` 与 plan §8 契约字段名逐字一致（对照 _FIXTURE test_dashboard.py:33-48）；异常零吞上抛。
2. **端点层**（main.py:1288-1303）：参数校验（0=全部/1-8760，非法 code 1 零触达）→ 聚合 → `{code:0, msg:"success", data}` 透传；异常 `logger.warning` + code 1 不 500。
3. **前端**（observabilityService + DashboardPage）：aiHttp Bearer 复用 → code!==0 抛 Error(msg) → 页面 catch Alert 不白屏；null 一律"—"（fmtMs/fmtRate L33-38）；窗口 Select 枚举约束无自由输入口 + 手动刷新不轮询。

### 8.2 授权偏离复核（Developer 声明重点）
- **latency 加 COUNT samples**：正当（plan §1 决策 2 要求输出 samples 而 plan §2 给定 SQL 结构性无法产出；同聚合加列最小改动），AC-8 三段必含文本未动且有逐段断言，changelog §二 WP-A 如实记录。
- **cost COALESCE 兜 0**：正当（AC-23 明文"二选一"），纯函数层 `or 0` 与 SQL 层口径同向（双 0 无分叉），changelog 如实声明 + 单测覆盖。

### 8.3 结论
Developer 的 WP-A~F 实现与 plan/AC 一致，changelog 声明（26 项测试、147 受影响复跑、AST 37/47、两端点 8-9 语句、fail-open 链、两处偏离授权）经独立复跑与复算**全部成立**（仅 2 处文档口径微差见 LOW-1/2）。3 项 LOW（changelog 语句数微差 / 147 口径标签 / 刷新失败保留旧数据未声明）+ 2 项备忘均非阻塞，已附建议。

**建议 Tester 重点复核**：AC-35 全量回归（预期 1564+26=1590 passed / 2 real_redis / 3 skipped 零新增失败）；AC §6 四条对账 SQL 逐值比对（"数据与落库一致"验收实质——hermetic 单测无法覆盖 percentile_cont/jsonb_each 真实语义，特别是 _SQL_COST 隐式 LATERAL 与 COALESCE 路径、'llm' 历史桶逐桶核对）；AC-24 hours=8760 大窗口真实返回；uvicorn 冒烟（hours=0 / hours=-1 curl）；浏览器 /dashboard 页面冒烟（四卡片渲染 + 窗口切换 + 刷新）；AC-38 一次真实 chat 后 request_logs 照常 +1（写入侧零回归终证）。
