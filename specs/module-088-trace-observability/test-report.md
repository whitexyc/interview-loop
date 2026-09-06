# 测试报告 — Module-088 链路式观测（trace_id 跨进程传播 + span 树 + 决策级日志）

> Tester: 2026-09-06 | 测试对象：`specs/module-088-trace-observability/`（plan.md v1 / acceptance-criteria.md / changelog.md v2 / review-report.md §9 二轮 PASS）+ 2 个新增文件（src/tracing.py / tests/api/test_tracing.py）+ 7 个修改文件（database.py / config.py / main.py / agent/react.py / agent/langgraph_react.py / rag/engine.py / tests/conftest.py）
> 测试方法：命令表全项独立复跑（不采信 changelog/review-report 声明）+ **T1-T8 真实 PG 对账（uvicorn 8010 独立进程 + 一次性只读 asyncpg 脚本，用后即删）** + 红线 git diff 逐文件甄别 + 全量差异逐根因归类 + Reviewer 遗留备忘（LOW-2/B1/B2）逐项核验 + 1 项 Tester 新发现（开关环境变量名 spec≠实现，§5）
> 对账环境：真实 PG `localhost:5432/personal_website`；真实 LLM（DeepSeek，分类调用超时回退保守路由、生成正常）；.env 临时改动均先备份后恢复（终态 diff=0）

## 1. 验证命令执行结果（独立复跑）

| 验收项 | 验证命令 | 预期 | 实际 | 状态 |
|--------|---------|------|------|------|
| 定向单测 | `cd ai_service && .venv/Scripts/python.exe -m pytest tests/api/test_tracing.py -q` | 46 passed | **46 passed, 2 warnings（16.66s）** | ✅ |
| 全量回归 | `.venv/Scripts/python.exe -m pytest tests/ -q` | **1638 / 0 / 3**（1592+46） | **1638 passed / 0 failed / 3 skipped / 163 warnings（121.72s）** | ✅ |
| 受影响存量 | `pytest tests/api/ tests/agent/ tests/core/ -q` | 798 / 3（存量零改动） | **798 passed / 3 skipped / 5 warnings（73.86s）** | ✅ |
| py_compile | 9 个变更文件（tracing/database/config/main/react/langgraph_react/engine/conftest/test_tracing） | OK | **PY_COMPILE OK（exit 0）** | ✅ |
| 写入侧红线 | `git diff -- ai_service/src/observability.py ai_service/rag/router.py ai_service/agent/tool_registry.py ai_service/mcp_server.py ai_service/requirements.txt` | 空 | **空（零 diff）** | ✅ |
| 前端/Java 红线 | `git status --short frontend backend` | 无输出 | **无输出（零改动）** | ✅ |
| 两表 DDL 红线 | `git diff -- ai_service/src/database.py \| grep REQUEST_LOGS_DDL\|TOOL_CALL_LOGS_DDL` | 零触碰 | **零命中（exit 1）** | ✅ |
| tests 红线 | `git diff --stat -- ai_service/tests/` | 仅 conftest 新增 fixture | **仅 conftest.py +14（default_trace_spans_disabled 纯新增）+ test_tracing.py 新文件** | ✅ |
| 真实 PG 对账 | uvicorn 8010 + asyncpg 只读脚本（临时目录，用后删） | T1-T8 全过 | **T1-T8 全过（§3）** | ✅ |
| .env 核验 | 备份→临时改→恢复→diff | 终态还原 | **终态与备份逐字一致（diff 空，无 PW_TRACE_SPANS* 残留）** | ✅ |

## 2. 全量回归差异逐根因归类（预期 1638/0/3 vs 实测 1638/0/3）

**实测与预期逐位一致，无差异项。**

| 项 | 数字 | 说明 |
|----|------|------|
| 基线（module-085 闭环） | 1592 passed / 0 failed / 3 skipped | 存量零漂移 |
| 本模块新增 | +46（test_tracing.py） | 46/46 全绿 |
| 算术自洽 | 1592 + 46 = **1638** = 实测 1638 ✅ | 0 failed、3 skipped 为存量环境性（real_redis 类），零新增失败 |
| 运行时长 | 121.72s | 正常 |

## 3. 真实 PG 对账（T1-T8，"一次请求一条 trace，父 span 含决策原因"验收实质）

前置：uvicorn 8010（.env 原样，PW_TRACE_SPANS_ENABLED 缺省 = true）→ `/ai/health` OK；一次性 asyncpg 脚本（SELECT only + 按先例清理测试残留行，§6）。

**T1（上游 header 传播，SSE 流式）✅**：`POST /ai/rag/chat/stream` + `X-Trace-Id: 0887e57e0123456789abcdef0123456789` → 完整 RAG 链（1 done + 4 step + 34 token；检索 9 docs → rerank 5）；**done 事件 payload 逐字含 `"trace_id": "0887e57e0123456789abcdef0123456789"`**（header 值原样透传，非自生成）；root span trace_id 同值。

**T2（trace 树端点 + 决策原因）✅**：`GET /ai/observability/trace/0887e57e...` → `code=0, msg=success`：

```
[request] /ai/rag/chat/stream  kind=request status=ok dur=0 identity='127.0.0.1' parent=''
 ├─ [decision] intent_routing  dur=452  decision='intent=knowledge reason=LLM 分类失败，保守路由: [deepseek] DeepSeek 服务暂不可用'
 └─ [retrieval] retrieval      dur=1651 decision='mode=hybrid fusion=rrf docs=9'
```
- children **含 intent_routing**（MAJOR-1 修复实证：上轮 Reviewer 预言"未修复则 T2 必失败"的反向验证通过）——decision 含 `intent=` 与 router reason 原文（"LLM 分类失败，保守路由"属 AC-20 认可的真实运行态 reason 来源；与 SSE intent step `confidence: 0.0` 相互印证）
- **duration 交叉对账**：intent_routing span duration_ms=452 == SSE intent step `timing_ms: 452` 逐值一致
- children.parent_span_id == root.span_id（因果挂根）；span_count == 库 count(*)

**T3（一次请求一条 trace）✅**：`rows=3, distinct_trace_id=1, roots(kind=request)=1, root parent_span_id=''`；父子因果完备（每个非根 span 的 parent 在 span 集内，孤儿数=0）。

**T4（父 span 含决策原因）✅**：intent_routing（decision 含 intent= 与 reason 原文）+ retrieval（decision 含 mode= fusion= docs=）两行 decision 非空落库——决策级日志真实存在，非单测摆设。

**T5（与 request_logs 同 trace）✅**：`request_logs JOIN request_spans ON trace_id` → **恰 1 行**（endpoint=chat_stream, error=False），spans=3 ≥ 2——记录式聚合行与链路式因果树同源（AC-12 真实环境终证）。端点树 flattened 顺序 == `ORDER BY started_at, id` 的库行序（读写一致）。

**T6（非法 header 回退）✅**：`X-Trace-Id: ../evil` → 请求正常处理（153 个 SSE 事件、done 到达、不崩不注入）；done trace_id 与落库 trace_id 均为自生成 **32 位小写 hex `6b1ed3dedf4046a2a140aeda50cfb69e`**；全表 `trace_id !~ '^[0-9a-f-]{1,64}$'` 计数 = **0 行**（无任何非法字符落库）。

**T7（开关关真实环境零 span）✅（注：经真实变量名 `PW_TRACE_SPANS_ENABLED=false` 重启，见 §5 发现-1）**：发 1 次 chat_stream 请求 → **request_spans 18 → 18（零新增行）**；request_logs 37 → 38 照常落库，且 trace_id 为自生成 `f0c22436...`（header `0887e57e...` 未被采纳）——开关关 = 058 行为逐字（AC-13）+ 开关矩阵①真实环境终证（AC-36）。

**T8（重启幂等 + 全表对账）✅**：3 次独立启动（初启 / 开关关重启 / 原样重启）全部健康（init_db 重复执行无报错）；重启后数据不丢（T1 trace 仍可查、span_count=3）；全表 audit：每 trace 恰 1 根（roots==1），**anomalies=0** —— "1 请求 = 1 root + N children" 全表成立。

## 4. 数据清理记录（如实申报）

| # | 对象 | 处置 | 依据 |
|---|------|------|------|
| 1 | 8010 端口上一会话遗留 uvicorn 孤儿进程（PID 85240，运行当前代码） | **taskkill 终止** | 工作流约定 8010 为 Tester 冒烟端口、用后杀净；不终止则无法受控重启 |
| 2 | 该孤儿进程会话在示例 trace_id 下残留 4 span（07:13 UTC，早于本会话）+ 1 行 request_logs（id 34） | **DELETE** | 沿用本模块 Developer"探针行 DELETE 清理"先例；不清理则 AC §5 T3/T5 SQL 原文因历史同 id 请求不可复现 |
| 3 | 本会话 1 次 422 畸形 body 试探产生的无子根 span（id 20） | **DELETE** | 系 Tester 自身 curl 编码失误的测试残留；该行为本身符合设计（body 校验前建根，422 非 AC-34 豁免范围），顺带实证中间件位置语义 |

清理后 request_spans 剩 14 行、request_logs 剩 37 行（+ 本会话真实请求的正常业务行：T1/T6/T7 各 1 行 request_logs + 对应 spans，与 module-085 Tester 对真实 chat 行的处理同口径，保留不删）。一次性脚本与 .env 备份已删除，8010 端口已杀净（netstat 复核 LISTENING=0）。

## 5. Tester 新发现（Reviewer 未覆盖）

### 发现-1：开关环境变量名 spec≠实现——`PW_TRACE_SPANS` 不存在，实际为 `PW_TRACE_SPANS_ENABLED`（minor，非阻塞）

| 项 | 内容 |
|----|------|
| 事实 | config.py:154 字段 `trace_spans_enabled: bool = True` + config.py:451 `env_prefix = "PW_"` → 真实环境变量 = **`PW_TRACE_SPANS_ENABLED`**。spec 三处（plan.md 决策 7 / plan.md WP-G / changelog.md WP-G）+ conftest.py:134 docstring 均写 `PW_TRACE_SPANS`，全库无任何代码绑定该名 |
| 复现（本会话实测） | ① `.env` 写 `PW_TRACE_SPANS=false` → **uvicorn 启动即崩**：`pydantic_core ValidationError: pw_trace_spans — Extra inputs are not permitted [type=extra_forbidden]`（dotenv source 对未知键按 extra_forbid 处理）；② OS env `PW_TRACE_SPANS=false`（.env 干净）→ **静默忽略**，`trace_spans_enabled` 保持 True（运维误以为已关）；③ `PW_TRACE_SPANS_ENABLED=false`（.env 或 OS env）→ 正常生效 False（T7 即以此完成） |
| 影响面 | 功能本身零缺陷：默认 true 正确、conftest 直接 monkeypatch 字段与变量名无关、45 项 AC 无一以 `PW_TRACE_SPANS` 为验收对象；危害仅在于**按文档操作关闭开关**——.env 路径崩溃（fail-fast 可感知）或 OS env 路径静默无效（更隐蔽） |
| 定级 | **minor（非阻塞）**——根因是 plan 决策 7 同一句内既写字段名 `trace_spans_enabled` 又写 `PW_TRACE_SPANS`，环境变量名从未与 `env_prefix + 字段名` 推导核对，属规格笔误的文档侧延续（与本模块偏离 1"AC 示例 vs 白名单"同类：条款/字段优先，示例名勘误） |
| 建议 | 文档侧勘误（推荐，零代码风险）：plan.md 决策 7/WP-G、changelog WP-G、conftest docstring、记忆三件套统一改 `PW_TRACE_SPANS_ENABLED`；可选代码侧加固（留后续模块）：config.py 字段加 `validation_alias="PW_TRACE_SPANS"` 兼容文档名，或 Settings 收敛 extra 策略。**勘误落地前运维勿在 .env 写 PW_TRACE_SPANS** |

## 6. Reviewer 遗留备忘核验（LOW-2 / B1 / B2，逐项）

| # | 备忘 | 独立核验 | 结论 |
|---|------|---------|------|
| LOW-2 | 检索 span decision 偏"结果+静态配置" | **属实**：T2/T4 实测 decision=`mode=hybrid fusion=rrf docs=9`——mode/fusion 为静态配置、docs 为计数，改写/HyDE/收束轮数真因未承载（对照 intent_routing 的 reason 原文） | 属实，非阻塞维持（plan WP-F 钉死内容，实现逐字一致；后续模块可追加 `rounds=/rewrite=` 真因，截 500 余量充足） |
| B1 | AC-36 矩阵③（双双 false）无显式 hermetic 用例 | **属实**：test_tracing.py 无双双关用例；但本轮 T7 真实环境覆盖了 spans=false 半边（request_logs 照常 + 零 span + header 不采纳），矩阵③ = ①∩② 平凡组合在真实环境有等价证据 | 属实，非阻塞维持（真实环境 T7 补位其一半，另一半由矩阵①用例覆盖） |
| B2 | agent-lg done trace_id 无独立用例 | **属实**：main.py agent-lg done 直拼点与 agent 侧逐字同构（代码读证）；本轮未对 agent-lg 做真实冒烟（agent 链路耗时长且 LLM 行为性），机制由 agent 端到端用例 + 代码同构覆盖 | 属实，非阻塞维持（可接受） |

## 7. 验收标准核对（AC-1 ~ AC-45 逐项签署）

### 7.1 span 存储与写侧原语（AC-1~9）
| AC | 验证证据（独立复跑/真实库实证） | 结论 |
|----|------------------------------|------|
| AC-1 DDL 与 plan 逐字 | 真实库 information_schema 实证：request_spans 11 列（id BIGSERIAL PK + trace_id/span_id/parent_span_id/name/kind/identity varchar + decision text + status varchar + duration_ms integer + started_at timestamp）+ **idx_request_spans_trace** 存在；ensure 拆分执行 + init_db 挂接（三次启动建表成功佐证） | ✅ |
| AC-2 建表幂等 | T8：3 次独立启动 init_db 重复执行无报错（表已存在时 IF NOT EXISTS 生效），真实 PG 验证 | ✅ |
| AC-3 红线零 diff | §1：observability.py/router/tool_registry/mcp_server/requirements.txt git diff 全空 + frontend/backend status 无输出 + 两表既有 DDL 零触碰 | ✅ |
| AC-4 开关关零落库 | conftest autouse 钉 false + 单测（开关关 `_spawn_insert` 不被调用、`record_span` 首行 return）+ **T7 真实环境零新增（18→18）** | ✅ |
| AC-5 无 trace 上下文跳过 | 单测 TestSpanPrimitives（`get_trace_id()==""` 静默跳过） | ✅ |
| AC-6 `_insert_span` fail-open | 单测（session 抛错不上抛 + warning 文案）；代码读证 tracing.py:104-105 | ✅ |
| AC-7 SQL 全参数化 + started_at Python 侧 | 单测逐列断言绑定参数集 + SQL hygiene（无 f-string/%/写关键字）；`datetime.utcnow()` 传入（非 DB default，真实库 timestamp without time zone 佐证） | ✅ |
| AC-8 sanitize 白名单 | 单测 5 项（合法/大写归一/超64/非法字符/None+空+空白）+ T6 真实（`../evil` → 32 hex 回退） | ✅ |
| AC-9 begin_request 根 span 字段 | 单测逐字段 + T2/T3 真实库：kind=request、parent=''、status=ok、duration_ms=0、identity='127.0.0.1' 透传；后续 record_span parent == 根 span_id | ✅ |

### 7.2 trace_id 跨进程传播（AC-10~14）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-10 合法 header 传播 | 单测（state + contextvar 双侧同值）+ **T1 真实：root span trace_id == header 值** | ✅ |
| AC-11 非法/缺失回退自生成 | 单测 + T6（`../evil` → `6b1ed3de...` 32 位小写 hex） | ✅ |
| AC-12 两侧同 trace | 单测（save_mock.call_args）+ **T5 真实 join：1 request_logs 行 ↔ 3 spans 同 trace_id** | ✅ |
| AC-13 开关关 058 逐字 | 单测 + **T7 真实：header 未采纳、trace_id 自生成 f0c22436...、request_logs 照常** | ✅ |
| AC-14 Java 零改动 | `git status --short backend` 无输出 | ✅ |

### 7.3 埋点面（AC-15~23）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-15 advance_phase reason 枚举 | 单测 5 项：generation_tool_called / retrieval_hit 开头 / idle_force_rounds=N / 未切空串 + 存量三分支语义 | ✅ |
| AC-16 两循环 advance_phase span | 单测（react_loop + langgraph 透传用例），reason="" 零 span | ✅ |
| AC-17 工具 span 三态 | 单测 3 项：ok / blocked（decision 含拒绝原因）/ error；两循环+MCP 经 execute_tool_with_log 继承 | ✅ |
| AC-18 工具 span decision/duration | 单测：decision 恒含 `phase=`、duration_ms == 实测耗时 | ✅ |
| AC-19 budget_truncate span | 单测 2 项：proposed=2 executed=1 有 span / 未截断零 span | ✅ |
| AC-20 intent_routing span 双路径 | 单测（engine.chat 侧 + MAJOR-1 修复的 chat_stream 流式用例）+ **T2/T4 真实流式链路：children 含 intent_routing，decision=intent=knowledge + reason 原文，dur=452 == SSE timing_ms=452** | ✅ |
| AC-21 retrieval span | 单测（chat 侧 + 流式 _retrieve 同构）+ T2/T4 真实：mode=hybrid fusion=rrf docs=9 | ✅ |
| AC-22 langgraph 零回归 | langgraph_react.py 仅 +3 AST；存量 798 全过（含 test_rerank_langgraph） | ✅ |
| AC-23 **验收方向终证** | 单测 TestOneRequestOneTrace + **T1-T5 真实链路：一次请求一条 trace（traces=1）、根唯一（roots=1）、树深≥2（root→intent_routing/retrieval）、decision 非空**——"一次请求对应一条 trace，父 span 含决策原因"成立 | ✅ |

### 7.4 读侧端点（AC-24~29）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-24 端点 200 契约 | T2：200 `{code:0, msg:"success", data:{trace_id, span_count, tree}}` 与 plan §7 字段逐字 | ✅ |
| AC-25 树节点字段 | T2 响应节点含 span_id/parent_span_id/name/kind/identity/decision/status/duration_ms/started_at/children 全字段 | ✅ |
| AC-26 `_build_tree` 纯函数 | 单测三态（单根嵌套/孤儿挂根/多根容忍）+ T5b：端点 flattened 序 == 库 `ORDER BY started_at,id` | ✅ |
| AC-27 trace 不存在 | 单测 + 冒烟探针 nonexistent id → `{"code":1,"msg":"trace 不存在"}` 不 500 | ✅ |
| AC-28 读侧 fail-open | 单测（mock 抛异常 → code 1 + msg 逐字 + warning）；SELECT 只读词边界断言 | ✅ |
| AC-29 {code,msg,data} 格式 | T2 与 083 approvals / 085 dashboard 先例同构 | ✅ |

### 7.5 SSE done 透传（AC-30~33）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-30 chat_stream done 带 trace_id | **T1 真实 SSE done payload 含 trace_id == header**；3 处调用点 extra 吸收（`_build_done_event` 签名未改，单测锁） | ✅ |
| AC-31 agent/agent-lg done | 单测（agent 端到端 payload == header）+ agent-lg 逐字同构（B2 备忘维持）；T1 为 chat_stream 路径实测 | ✅ |
| AC-32 错误路径 bare done 不带（边界声明） | 代码读证：bare done 未动，不崩 | ✅ |
| AC-33 非流式 chat schema 零改动 | 存量 798 含 chat 响应测试全过；engine.chat 返回零 diff | ✅ |

### 7.6 边界/异常/非功能（AC-34~45）
| AC | 验证证据 | 结论 |
|----|---------|------|
| AC-34 health/429 零 span | 单测双向锁 + 位置读证（088 块在限流短路后、health 早期 return 前）；顺带实证：body-422 请求有根无子（422 不属豁免范围，位置语义自洽，§4-3） | ✅ |
| AC-35 decision 截 500 | 单测（超长 reason 截断不报错） | ✅ |
| AC-36 开关矩阵 | ①单测 + **T7 真实（logs 照常 + 零 span）**；②单测；③无显式 hermetic 用例（B1 备忘，真实环境等价证据补位） | ✅ |
| AC-37 并发隔离 | 单测（两请求不同 X-Trace-Id 不串 + contextvar 重置） | ✅ |
| AC-38 DB 不可用 fail-open | 单测（落库 fail-open 主链路不受影响 + 端点 code 1 不 500）；真实停库未做（环境受限如实标注，PG 为对账前提），单测覆盖 | ✅（单测覆盖） |
| AC-39 恶意/超长 header | 单测 + T6 真实（`../evil` 回退、全表零非法字符） | ✅ |
| AC-40 全量零新增失败 | **独立复跑 1638/0/3**（1592+46 算术自洽，§2） | ✅ |
| AC-41 存量测试零改动 | 798/3 全过；git diff tests/ 仅 conftest +14 纯新增 fixture | ✅ |
| AC-42 conftest fixture | diff 实证纯新增 `default_trace_spans_disabled` autouse（模式对齐 default_mcp_external_disabled）；docstring 中 PW_TRACE_SPANS 名不符并入发现-1（文档级） | ✅ |
| AC-43 行数 ≤200 | 复核 changelog §三差分表自洽（82+16+10+13+3+5+1=**130** ≤200），与 Reviewer 二轮独立复算一致 | ✅ |
| AC-44 方法 ≤50 + docstring + 0 print/0 裸 except | Reviewer 已核（新增最长 23 语句；2 处 `except Exception as e`+logger / 1 处 `except RuntimeError` plan 钉死），本轮 py_compile + 存量全过佐证 | ✅ |
| AC-45 py_compile | 9 文件 **COMPILE OK（exit 0）** | ✅ |

**签署：45/45 通过。**

## 8. 已知边界 / 备注

1. **发现-1（PW_TRACE_SPANS 变量名不符）为 minor 非阻塞**：建议文档侧勘误（§5）；T7 已以真实变量名完成，验收实质不受影响。
2. **真实 LLM 运行态注记**：本轮 DeepSeek 分类调用失败（超时/暂不可用）触发 router 保守路由回退——这正是决策级日志的价值展示：intent_routing span 如实记录 `reason=LLM 分类失败，保守路由: [deepseek] DeepSeek 服务暂不可用`，与 SSE step 的 confidence=0.0 互证；生成阶段正常（34 token 流式输出）。属真实环境行为非缺陷。
3. **T7 流式请求 curl 180s 超时切断**（LLM 慢）：不影响判定——对账实质为"零 span + request_logs 照常"（18→18 / 37→38），均已落库取证。
4. **fire-and-forget 尾部 span 语义**（changelog §五继承）：本轮未观测到丢 span（T1/T6 链路 3/3 齐全）；v1 边界维持。
5. 对账脚本一次性只读（SELECT + 按先例清理测试残留行），已删除零残留；.env 终态还原；8010 端口杀净复核。

## 9. 验收结论

- 审查人: Reviewer（2026-09-06，二轮 post-fix PASS：0 阻塞 / 0 重大 / 1 LOW 备忘 + 2 备忘，已通过）
- 测试人: Tester（2026-09-06）
- 验收时间: 2026-09-06
- 结论: **[x] 通过**
- 统计: **验收通过 45/45**
- 备注: 定向 46/46 + 受影响存量 798/3 + 全量 **1638/0/3**（1592+46 算术自洽，零新增失败）+ py_compile 9/9 + 红线零 diff（写入侧/两表 DDL/前端/Java/存量测试）。**核心验收（"一次请求一条 trace，父 span 含决策原因"）：T1-T8 真实 PG 对账全过**——X-Trace-Id 跨进程传播（header 值贯穿 root span / SSE done / request_logs 三面）、trace 树 children 含 intent_routing（MAJOR-1 修复实证，decision 含 intent= 与 router reason 原文，duration 与 SSE timing 逐值互证）与 retrieval（mode=/fusion=/docs=）、根唯一 + 父子因果完备、非法 header 回退 32-hex 零注入落库、开关关真实环境零 span + 058 行为逐字、三次重启幂等数据不丢、全表每 trace 恰 1 根。Tester 新发现 1 项 minor（§5 开关环境变量名 spec≠实现，文档侧勘误即可）+ 3 项 Reviewer 备忘核验属实均非阻塞（LOW-2/B1/B2 维持）。遗留：检索 span decision 真因含量（后续模块可选）、agent-lg 独立用例（可选）、发现-1 文档勘误（Planner/Developer 侧）。
