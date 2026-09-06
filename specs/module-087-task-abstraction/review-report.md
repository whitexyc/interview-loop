# 审查报告 — Module-087: 任务抽象（task 表 + 一次请求 = 1 task + "子只读父写"所有权）

> Reviewer 审查 | 2026-09-06 | 审查依据：plan.md v1 + acceptance-criteria.md（AC-1~38）+ changelog.md（含 §五偏离 5 项申报）+ 编排者裁定基准（本派发随附）
> 审查方式：全文件通读（tasks.py/main.py/database.py/memory.py/config.py/conftest.py/test_tasks.py 逐字）+ 红线 git diff 实证 + 独立复跑（不采信 changelog 数字）

## 1. 审查结论

**不通过（NON-PASS，1 阻塞 + 2 LOW + 2 备忘）** — 2026-09-06 Reviewer

- 9 项重点核查中 8 项全过（088 兼容硬约束 / finish 幂等 / 中间件位置与 fail-open / 闸面边界 / 铁律 / 测试质量 / AC 覆盖 / 红线甄别），实现质量整体高于基线；
- 唯一实质缺陷：**编排者裁定"/ai/memory/save 被所有权闸拒绝时返回 code 1（拒绝可见，fail-closed 对齐 083）"未落地**——main.py:941-942 对 `{"status":"blocked"}` 仍走 `{"code":0,"data":result}` 透传，且 changelog 头部与 §五.5 将 code 0 申报为"编排者裁定已执行"，与本次审查基准直接矛盾（问题 #1，阻塞）；
- 修复面很小：1 个端点分支 + 1 个端点级断言测试 + 2 处文档勘误。修复后走快速复审通道（只复验 #1 与增量测试）。

## 2. 问题列表

### 阻塞（→ 不通过）

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|----------|----------|
| 1 | ai_service/main.py | 941-942 | `/ai/memory/save` 被所有权闸拒绝时：`memory_service.save()` 返回 `{"status":"blocked"}`（memory.py:335），端点原样透传为 `{"code":0,"data":{"status":"blocked"}}`。与本派发审查基准（编排者裁定：**拒绝时返回 code 1，拒绝可见，fail-closed 对齐 083**）直接相悖。同时 changelog 头部"编排者裁定已执行：…code 0 透传"与 §五.5 同口径申报与该裁定矛盾——或系裁定晚于开发送达，或系申报失实，二者必居其一，均须修正。另：该端点 blocked 路径**无任何测试锁定**（TestMemoryGate 只测 MemoryService.save 返回值，不测端点响应码） | 阻塞 | ① main.py `memory_save` 在 L941 之后补分支：`result.get("status") == "blocked"` → 返回 code 1（沿用本端点既有错误形状 `{"code":1,"message":...}`，main.py:944 先例，message 建议含"子只读父写"字样）；② tests/api/test_tasks.py TestMemoryGate 补 1 项端点级断言（read 模式 POST /ai/memory/save → code 1 + _save 未被调）；③ changelog 头部裁定行 + §五.5 + acceptance-criteria.md AC-34 勘误为 code 1 口径（AC-34 现文"code 0 透传"系待澄清 3 的旧缺省，已被裁定取代） |

### 建议（LOW，非阻塞）

| # | 文件 | 行号 | 问题 | 严重级别 | 修复建议 |
|---|------|------|------|----------|----------|
| 2 | memory/file-index.md | 201 | tasks.py 登记行之后残留孤立片段 `fJt`（Developer 更新记忆时的编辑残渣），破坏索引表格式 | 低 | 删除该行 |
| 3 | ai_service/src/tasks.py | 159-169 / 172-174 | AC-37 要求 public docstring"（Args/Returns/Raises）齐全"：`memory_write_allowed`（:172-174）仅单行 docstring 无 Args/Returns 分节；`set_memory_write_mode`（:159-169）无 Returns 节；`finish_task`（:134-156）无 Returns 节（返回 None）。行为语义已在正文描述，属字面出入 | 低 | 三个函数补结构化分节；或后续模块将 AC-37 措辞放宽为"返回非 None 的 public 函数须 Args/Returns 齐全" |

### 备忘（不计问题，供后续模块参考）

| # | 文件 | 行号 | 说明 |
|---|------|------|------|
| B1 | ai_service/main.py | 265 / 276 | 同一白名单请求内 `resolve_identity(request)` 被调用两次（088 块 + 087 块），每次含 JWT 解析。plan WP-C 草案逐字如此，量级小；多 Agent 时代若 task 块增多可考虑块间传递复用 |
| B2 | ai_service/main.py | 339-347 | tasks_enabled=false 时 persist_request_log 仍执行 `get_request_stats()` + tokens 求和（plan 决策 9 已声明，量级可忽略）；"开关关零开销"严格成立于中间件侧（main.py:271 短路），persist 侧为"零落库但有一次空快照" |

## 3. 验收标准核对

| 验收项 | 对应代码 文件:行号 | 状态 | 备注 |
|--------|--------------------|------|------|
| AC-1 TASKS_DDL 逐字 14 列 + idx_tasks_trace + ensure + init_db 挂接 | src/database.py:210-243（DDL）/ :245-250（ensure_tasks_table 拆分执行）/ :407-408（init_db 尾部挂接） | ✅ | 与 plan §2 WP-A 草案逐字一致（15 条语句）；test_tasks.py:170-197 锁定 |
| AC-2 建表幂等 | database.py:245-250（IF NOT EXISTS 语义）+ test_tasks.py:186-197 | ✅ | 真实 PG 二次执行归 Tester T6 |
| AC-3 三表 DDL + 红线清单零 diff | git diff 实证全空（observability/verify_tasks/router/tool_registry/mcp_server/engine/react/langgraph/requirements/backend/frontend） | ✅ | 独立核验非采信申报 |
| AC-4 开关关零落库仍 set var | src/tasks.py:121-124 + test_tasks.py:206-217 | ✅ | 32hex 断言含 |
| AC-5 INSERT 11 绑定列全字段 | tasks.py:125-131 + test_tasks.py:219-246 | ✅（按偏离 1 裁定） | checkpoint={} 在 INSERT 内——AC-28 冲突按 plan 主文裁定，见 §8 |
| AC-6 fail-open 双保险 + 引用池 | tasks.py:103-104（Exception+warning）/ :84-86（RuntimeError 窄捕获）/ :77,86-87（_pending_tasks + done_callback discard） | ✅ | 对齐 088 minor-1 先例 |
| AC-7 finish 幂等 + CASE + failed/completed + Python 侧 finished_at | tasks.py:51-56（_SQL_FINISH）/ :150-156 + test_tasks.py:248-287 | ✅ | WHERE task_id=:task_id AND status='running' 文本断言在 :260 |
| AC-8 空 task_id / 开关关首行 return | tasks.py:148 + test_tasks.py:267-278 | ✅ | 双分支各有专测（偏离 4 拆分合理） |
| AC-9 SQL 卫生 + 只读词边界 | tasks.py:39-72（三 SQL 全 :xxx）+ test_tasks.py:660-669 / :493-500 | ✅ | grep 无 f-string/%/+ 拼接，独立复核一致 |
| AC-10 四端点建 task + 087 块位置 | main.py:271-276（088 块 ：259-265 之后、call_next :278 之前）+ test_tasks.py:313-332 / 429 反向位置锁 :377-388 | ✅ | trace_id==state.trace_id==save record 同源断言 ：330 |
| AC-11 非白名单 / 429 零 task | test_tasks.py:334-352（/ai/memory/save）/ :377-388 | ✅ | 与 088 边界一致 |
| AC-12 tasks off 全链路零 task，058 逐字 | test_tasks.py:354-365（calls==[] 且 save_mock.called） | ✅ | 058 行为逐字由存量 test_observability（383 内）佐证 |
| AC-13 trace 缺失跳过 | main.py:272-273（getattr 默认空 → 内层 if 跳过）+ test_tasks.py:367-375 | ✅ | 聚合锚缺失边界如实 |
| AC-14 persist 收口钩子 + 独立开关 + 无 task_id no-op | main.py:343-347 + test_tasks.py:397-456 | ✅ | tokens 汇总 18 断言 =10+5+2+1 逐字口径 |
| AC-15 一次请求=1 task 集成 | test_tasks.py:626-651 | ✅ | 恰 1 INSERT + 1 UPDATE + 三面 trace_id 同值（含 088 根 span）——088 兼容硬约束终证 |
| AC-16 persist 既有语义不变 | git diff 实证仅 stats 上移（main.py:339）+ finish 追加（:343-347），record 构造 :350-360 逐字未动 | ✅ | test_observability 存量全绿（383 内） |
| AC-17 200 契约形状逐字 | main.py:1390-1408 + test_tasks.py:520-539 | ✅ | plan §7 字段集断言 ：528-531 |
| AC-18 不存在 / 异常 code 1 不 500 | test_tasks.py:541-557 | ✅ | 088 trace 端点同构 |
| AC-19 单 SQL 标量子查询 + obs 组装 | tasks.py:60-72 / :177-200 + test_tasks.py:465-484 | ✅ | 三计数键 pop 进 obs |
| AC-20 obs 三计数真实对账 | — | ⏳ | 归 Tester（T2 真实 PG） |
| AC-21 所有权原语五态 | tasks.py:159-174 + test_tasks.py:289-304 | ✅ | 非法值 no-op 双例（"child"/""） |
| AC-22 save 默认放行语义逐字 | memory.py:336-337 + test_tasks.py:566-572 | ✅ | 存量 tests/memory/ 全绿（383 内） |
| AC-23 read 拒绝 + warning + 不上抛 | memory.py:333-335 + test_tasks.py:574-588 | ✅ | warning 含"子只读父写"断言 ：588 |
| AC-24 save_short / session 不受影响 | test_tasks.py:590-617 | ✅ | 闸只设 save 入口，_save 未动（memory.py:330-337 注释与实现一致） |
| AC-25 config 字段 + PW_TASKS_ENABLED 唯一口径 | src/config.py:158-161 | ✅ | 注释明示勿写 PW_TASKS（088 发现-1 教训） |
| AC-26 conftest autouse 钉关，存量 fixture 零改动 | tests/conftest.py:144-157 + git diff（tests/ 仅此 14 行纯新增） | ✅ | docstring 对齐 088 先例 |
| AC-27 既有数据零迁移 | tasks 表为全新表；三表零 ALTER 实证 | ✅ | 上线前后行数对账归 Tester（T3） |
| AC-28 checkpoint v1 零读写 | FINISH 无 checkpoint 字样（tasks.py:51-56 + test_tasks.py:264）/ overview 原样透传（:197-199 + test :476）/ 生产零 checkpoint 逻辑 | ⚠️ | INSERT 含 checkpoint={}（tasks.py:128）——与 AC-28"INSERT 不含该列"字面冲突，按偏离 1 裁定成立（§8），实质意图满足 |
| AC-29 budget 零执法 | DDL 注释归属 089（database.py:234）+ FINISH 无该列（test_tasks.py:265）+ 生产代码无预算判断（grep 独立复核） | ✅ | |
| AC-30 parent_task_id 恒 "" | tasks.py:127 + test_tasks.py:237 | ✅ | |
| AC-31 悬挂 running v1 声明 | changelog §六 + plan §1 决策 3 | ✅ | 声明如实，单测不覆盖（per AC 设计） |
| AC-32 DB 不可用 fail-open | tasks.py:103-104（全异常 warning 不上抛） | ✅ | begin/finish 均经 _spawn 异步旁路 |
| AC-33 流 finally 收口 error=failed | main.py:692-693（finally 未动，058 既有）+ test_tasks.py:425-441 | ✅ | persist 四调用点（main.py:520/693/838/916）全覆盖核验 |
| AC-34 save 拒绝响应 | main.py:941-942 | ❌ | **阻塞 #1**：code 0 透传 ≠ 编排者裁定 code 1；且无端点级测试 |
| AC-35 全量回归 | — | ⏳ | 归 Tester（预期 1638+30=1668 / 0 failed / 3 skipped） |
| AC-36 行数 + 方法长度 | AST 独立复算 92 ≤200（database +10 / tasks 61 / main +16 / memory +4 / config +1，与 changelog §三逐字一致）；新增函数最长 get_task_overview 10 语句 | ✅ | |
| AC-37 docstring / 0 print / 0 裸 except | tasks.py 各 public 函数 | ⚠️ | LOW #3：三个函数 docstring 分节不全；0 print / 0 裸 except 独立复核通过（1×Exception+warning、1×RuntimeError 窄捕获，均 plan 钉死语义） |
| AC-38 红线总核验 | git status + git diff --stat 实证：改动面恰为 7 文件（database/tasks/main/memory/config/conftest/test_tasks）+ specs/ + memory/ | ✅ | 红线清单全空 |

## 4. 架构评估

- **分层与依赖方向（通过）**：main.py（中间件/端点/persist 收口）→ src/tasks.py（原语+聚合）→ src/database.py（会话工厂）；memory.py 闸经 `from src.tasks import memory_write_allowed`（memory.py:54）单向依赖原语函数，不反向触达 main；tasks.py 模块级仅依赖 src.config（tasks.py:26），database 会话工厂在函数内懒加载（tasks.py:98、:190）——无循环导入且与既有模块风格一致。
- **088 兼容硬约束（通过，本模块最重要约束）**：① request_logs/tool_call_logs/request_spans 三表既有 DDL 零 diff（git diff 实证）；② task 关联确走 trace_id 读侧 join——_SQL_OVERVIEW 三个标量子查询 `WHERE r.trace_id = t.trace_id`（tasks.py:64-69），无改列无改语义，request_spans 树结构零触碰；③ 中间件顺序自洽：058 块（main.py:227-230）→ health 早退（:233-234）→ 429 短路（:247-252）→ 088 块（:259-265，trace_id 终值 sanitize/自生成 + init_request 幂等覆盖）→ 087 块（:271-276，读 state.trace_id 建 task）→ call_next（:278）——087 在 088 后保证 trace_id 终值，TestOneRequestOneTask 断言 INSERT trace_id == 根 span trace_id == request_logs trace_id 三面同值（test_tasks.py:645-650）。
- **DTO/契约（通过）**：端点 `{code,msg,data}` + plan §7 字段名逐字（test_tasks.py:528-531 锁定）；memory save 返回 `{"status":"blocked"}` 对 engine 忽略返回值的两调用面兼容（engine.py:662/:687）。
- **新增依赖**：无（requirements.txt 零 diff）；无 ORM 模型（对齐 tool_call_logs/request_spans 先例）；无新 ADR 触发。

## 5. 安全评估

| 项 | 结论 | 依据 |
|----|------|------|
| SQL 注入 | **通过** | 三 SQL 全 `:xxx` 绑定（tasks.py:39-72）；端点路径参数 task_id 经 `{"task_id": task_id}` 绑定（tasks.py:193）；test_tasks.py:660-669 卫生断言 + Reviewer 独立 grep 复核 |
| XSS | 不适用 | 零前端改动（frontend/ 零 diff） |
| 密码 | 不适用 | 无认证面改动 |
| API Key | 不适用 | 无配置/凭据改动（.env、requirements 零 diff） |
| 敏感日志 | **通过** | _run_sql warning 仅含异常 `%s`（tasks.py:104）；闸 warning 无用户内容（memory.py:334）；端点降级日志 `%s` 形式（main.py:1399） |
| 异常处理 | **通过** | 0 裸 except：1 处 `except Exception as e` + logger.warning fail-open（tasks.py:103）+ 1 处 `except RuntimeError` 窄捕获（tasks.py:84，plan WP-B 钉死语义）+ 端点层 try/except 降级不 500（main.py:1397-1399） |

## 6. 五轴评分

| 轴 | 分数 | 依据 |
|----|------|------|
| 正确性 | 4/5 | 唯一实质缺陷为编排者裁定 code 1 未落地（#1）；其余语义（幂等 UPDATE/CASE、fail-open 链、白名单边界、trace 三面同值）逐项验证全对 |
| 完整性 | 4/5 | AC 33/38 直接通过 + 3 项如实归属 Tester；1 项阻塞（AC-34）+ docstring 分节字面出入（AC-37 部分）；偏离申报 5 项中 4 项成立、1 项反向矛盾 |
| 清晰性 | 5/5 | tasks.py 模块 docstring 完整交代生命周期/边界/不做清单；三 SQL 注释逐条说明语义与归属模块；changelog 链路图与实现一一对应 |
| 可维护性 | 5/5 | 打桩/开关钉桩/ContextVar 隔离全部对齐既有先例（test_tracing/test_dashboard/088 LOW-3 教训）；引用池防 GC；懒加载避环；089/090 挂载点注释到位 |
| 安全性 | 5/5 | §5 全通过；fail-open 面不掩盖拒绝语义（闸 warning 可观测），唯端点响应码待按裁定修正 |

## 7. ADR

无新 ADR。task 关联走 trace_id 读侧 join 系 plan 裁定 1（plan §1），实现与 plan 一致，非新架构决策；checkpoint/budget 结构预留归属 089/090 已在 DDL COMMENT 声明（database.py:234/:237）。

## 8. 偏离裁定（changelog §五 5 项逐项）

| # | 偏离申报 | 裁定 | 复核证据 |
|---|----------|------|----------|
| 1 | AC-28 与 AC-5/WP-B 文本冲突：INSERT 是否含 checkpoint={}，按 plan 主文实现（含） | **成立** | 冲突真实：AC-5（AC 文件 L14）/ plan WP-B（L90"11 绑定列"）/ WP-F（L144）三处一致 vs AC-28 孤例（L47）；INSERT 值与 DDL default '{}' 同值无行为差异；AC-28 实质意图（v1 零读零写逻辑）完整满足——FINISH 不触碰（tasks.py:51-56 + test_tasks.py:264）、overview 原样透传（:197-199 + test :476）、生产零 checkpoint 逻辑；单测双向锁定（INSERT 含 ：244 / FINISH 不含 ：264） |
| 2 | save 生产调用面 3→4 处（第 4 处 rag/crawl/feedback_scanner.py:87） | **成立** | 独立实核 4 处：rag/engine.py:662（remember_content）/ rag/engine.py:687（extract_facts）/ main.py:941（/ai/memory/save）/ rag/crawl/feedback_scanner.py:87（低分题→待学笔记）；plan §0.3 盘点漏计；闸设 save 入口（memory.py:333）对第 4 处天然覆盖，该文件零 diff |
| 3 | session_memory 打桩经 sys.modules（rag.memory 旧路径别名遮蔽） | **成立** | test_tasks.py:595-597 实现与注释一致；系 module-050 rag 子包兼容机制的环境实测坑，对齐 reranker 同名 monkeypatch 先例 |
| 4 | 测试 30 项（plan 预估 ~28） | **成立** | 独立复跑 30 passed（29.30s）；拆分锁 AC-8 双分支（test_tasks.py:267-278 两条）与 AC-29/30（:237/:241）合理，均在 hermetic 口径内 |
| 5 | "其余全部按 plan 逐字执行……save 被拒 code 0 透传（编排者四项裁定之一）" | **不成立** | 该条将 code 0 归为编排者裁定；本次审查基准中编排者裁定为 **code 1（拒绝可见，fail-closed 对齐 083）**——实现（main.py:941-942）与申报口径均须按裁定修正，即阻塞 #1。其余三项裁定（tasks 不清理 / tokens_used 不分桶 / checkpoint 只预留）与实现核对一致 |

## 附：独立复跑记录（不采信 changelog，2026-09-06）

| 验证 | 结果 |
|------|------|
| `pytest tests/api/test_tasks.py -q` | **30 passed**（29.30s） |
| `pytest tests/api/ tests/agent/ tests/core/ -q` | **828 passed / 3 skipped**（92.07s）= 798 基线 + 30 新增，零新增失败 |
| `pytest tests/api/test_observability.py tests/api/test_dashboard.py tests/api/test_tracing.py tests/memory/ tests/agent/test_tool_call_logs.py -q` | **383 passed**（72.04s），与 changelog §四一致 |
| py_compile 7 变更文件 | OK（exit 0） |
| AST 行数复算（git HEAD 差分口径） | database 199→209（+10）/ tasks 0→61 / main 663→679（+16）/ memory 495→499（+4）/ config 122→123（+1）= **92 ≤ 200**，与 changelog §三逐字一致 |
| 红线 git diff | observability.py / verify_tasks.py / router.py / tool_registry.py / mcp_server.py / engine.py / react.py / langgraph_react.py / requirements.txt / frontend / backend 全空；tests/ 仅 conftest 纯新增 +14 行 |

## 9. 第二轮复审（post-fix，2026-09-06，PASS）

> 聚焦复验第一轮 3 项发现（格式对齐 module-069/088 二轮先例），不做全量重审；全部独立复验、不采信 changelog。

### 9.1 逐项复验

| # | 一轮发现 | 复验结论 | 证据（文件:行号） |
|---|----------|----------|-------------------|
| 1 | 阻塞：/ai/memory/save 被闸拒绝仍 code 0 透传，违编排者裁定 code 1 | **修复成立** | ① main.py:942-945 补 blocked 分支：`result.get("status") == "blocked"` → `{"code": 1, "message": "记忆保存被拒绝（task 所有权：子只读父写）"}`——沿用本端点既有 `{"code":1,"message":...}` 错误形状（main.py:948 ValueError 先例）；正常路径 `return {"code": 0, "data": result}`（:946）逐字未动；engine 侧两调用面（rag/engine.py:662/:687）忽略 save 返回值，不受影响；② 端点级测试 ×2 实质到位：test_tasks.py:632-656（read 模式 POST → code 1 + message 含"子只读父写" + _save 未被调；ContextVar set/复位与 POST 同一 asyncio.run，防共享上下文泄漏——088 LOW-3 教训）+ test_tasks.py:658-667（默认 write → code 0 + data.status=saved，存量透传语义锁定）；③ 文档勘误三处如实：changelog 头部（:6，明写"初版误按 plan §8 待澄清 3 的 code 0 缺省实现并误报'裁定已执行'"）+ §五.5（:100，明写"误报为编排者裁定"勘误）+ §八新增修复轮全记录（:114）；acceptance-criteria.md AC-34（:55）改 code 1 口径并注明"编排者裁定 2026-09-06 取代 plan §8 待澄清 3 旧缺省"——均为"误报更正"式如实记载，非掩盖 |
| 2 | LOW：memory/file-index.md:201 残留 `fJt` | **修复成立（含归因更正）** | grep 零命中；git diff 实证 `fJt` 系 HEAD 中已提交的既有脏行（一轮 diff 仅 +2 行为 tasks.py 登记行与 specs 目录行，fJt 被新行顶下暴露）——一轮报告将其归因为"Developer 编辑残渣"有误，特此更正；Developer 删除动作即一轮建议修复，其余行未触碰 |
| 3 | LOW：tasks.py 三函数 docstring 缺 Args/Returns 分节 | **修复成立** | ast.get_docstring 复验：finish_task（Args）/ set_memory_write_mode（Args + Returns: None）/ memory_write_allowed（Args: 无 + Returns 语义）分节齐全；代码逻辑零改动——tasks.py AST 复算仍 61（docstring 在既有 Expr 语句内扩写，不增语句） |

### 9.2 二轮独立复跑

| 验证 | 结果 |
|------|------|
| `pytest tests/api/test_tasks.py -q` | **32 passed**（19.12s，30 + 端点级 2） |
| `pytest tests/api/ tests/agent/ tests/core/ -q` | **830 passed / 3 skipped**（68.79s）= 798 基线 + 32 新增，零新增失败 |
| py_compile 7 文件 | OK（exit 0） |
| AST 复算（git HEAD 差分口径） | database +10 / tasks 61 / main **+18**（663→681，含 blocked 分支 2）/ memory +4 / config +1 = **94 ≤ 200**，与 changelog §三 v2 逐字一致 |
| 红线 git diff | 全空（observability/verify_tasks/router/tool_registry/mcp_server/engine/react/langgraph/requirements/frontend/backend 零修改；改动面仍限 087 七文件 + specs + memory） |

### 9.3 二轮结论

**通过（PASS，post-fix，2026-09-06）**——一轮 1 阻塞 + 2 LOW 全部修复复验成立，无新增问题；一轮 2 项备忘（B1 resolve_identity 二次调用 / B2 tasks 关闭时 persist 空快照）维持非阻塞备忘。行数 94 AST ≤ 200。

**移交 Tester 要点**：① 全量回归预期 **1670 = 1638 + 32** / 0 failed / 3 skipped（新增 0 失败红线）；② T1-T8 真实 PG 对账照 AC §5 执行；③ **注意口径变更**：/ai/memory/save 被闸拒绝现返回 **code 1**（编排者裁定，fail-closed 对齐 083；正常路径仍 code 0 透传）——AC-34 已按新口径勘误，Tester 对账与任何相关断言以此为准；④ AC-2/AC-27 真实幂等与零迁移对账（T3/T6）不变。
