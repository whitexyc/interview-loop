# 测试报告 — Module-089: 预算账本（任务级 token 预算 + 超预算熔断）

> Tester: 2026-09-06 | 测试对象：Reviewer PASS 后移交的实现（4 修改文件 + 1 新增测试文件，0 阻塞 / 3 LOW + 2 备忘移交核验）
> 测试依据：acceptance-criteria.md AC-1~27 + §5 T1-T6 真实对账方案
> 验证方法：命令表全项独立复跑（不采信 Developer/Reviewer 声明）+ 真实 PG 对账（真实驱动层 INSERT/UPDATE/SELECT + 真实 LLM 消耗 token，禁 mock 充数）+ AC 逐项签署 + Reviewer LOW/备忘逐项独立核验

---

## 1. 验证命令执行结果（独立复跑，ai_service 目录，.venv/Scripts/python.exe）

| # | 验证项 | 命令 | 实测结果 | 预期 | 判定 |
|---|--------|------|----------|------|------|
| 1 | 定向新增 | `pytest tests/api/test_budget.py -q` | **20 passed** / 0 failed（13.23s） | 20 passed | ✅ |
| 2 | 受影响存量 | `pytest tests/api/test_tasks.py tests/api/test_observability.py tests/api/test_tracing.py tests/agent/ tests/api/test_main.py -q` | **415 passed** / 0 failed（52.37s） | 415 全绿 | ✅ |
| 3 | 全量回归 | `pytest tests/ -q` | **1690 passed / 0 failed / 3 skipped**（113.85s） | 1690/0/3（=1670 基线 + 20 新增） | ✅ |
| 4 | py_compile | `py_compile src/tasks.py src/config.py agent/react.py tests/conftest.py tests/api/test_budget.py` | exit 0 无输出 | OK | ✅ |
| 5 | 红线 git diff | 10 文件逐 pathspec + `git status --short frontend backend` | 全空 | 全空 | ✅ |
| 6 | tests 变更面 | `git diff --numstat -- tests/` + `git status --short tests/` | 仅 conftest.py +13/-0 纯新增 + test_budget.py 新文件（332 行） | 同 | ✅ |
| 7 | AST 差分 | git show HEAD vs 工作树，ast.stmt 独立重算 | config 123→124（+1）/ tasks 61→86（+25）/ react 232→241（+9）= **+35 ≤ 200**；新增函数最大 set_task_budget 7 语句 | +35 ≤ 200 | ✅ |

### 1.1 全量回归差异逐根因归类

实测 1690/0/3 与预期 1690/0/3 **逐字一致，零差异、零新增失败**——无失败样本需要归因。3 skipped 为基线固有（与 1670 基线的 3 skipped 同源），非本模块引入。

## 2. 失败详情

**无测试失败**（定向/存量/全量三块全部一次通过，无收集 warning 级异常——仅 pydantic 弃用类 warning，属存量基线杂音）。

冒烟过程中遇到的环境性故障（非测试失败、非代码回归，均已按"修基建重跑"处理并全程留痕）：

| # | 现象 | 根因 | 失败类别 | 处置 |
|---|------|------|----------|------|
| E1 | DeepSeek 全部调用 401 Authentication Fails（key 尾号 bfa8） | .env 中 DeepSeek key 已失效——**存量环境劣化，与本模块无关**（LLM 基建面零 diff） | 环境性 | 探针期临时切换供应商（见 §5），测后环境全量还原 |
| E2 | ModelScope 免费推理 API 间歇性返回畸形 200 响应（空 choices / delta 体裁 / 解析 'NoneType' not iterable） | 供应商侧不稳定（直连复测三个模型均 200 但响应体质量差），与模型选择无关 | 环境性 | 重试/换供应商重跑；core 熔断证据已入库后不再依赖 LLM 稳定性 |
| E3 | 中文 query 经 Git Bash curl 传输 400 body 解析失败 | Windows 控制台编码 | 环境性 | 改 UTF-8 文件体 `--data-binary @file` + 英文 query |
| E4 | AC §6 命令表 `uvicorn src.main:app` 无法导入 | 实际应用在 ai_service/main.py:190（src/ 无 main.py），应为 `main:app` | 文档偏差 | 按 `main:app` 启动（已在 §8 申报，建议文档侧勘误） |

## 3. 真实 PG 对账（T1-T6，"超预算任务被熔断"验收实质）

> uvicorn 8010 真实起服（真实 .env 凭据 + PW_TASK_BUDGET_TOKEN_LIMIT 注入）+ 真实 LLM（ModelScope 链）+ 一次性 asyncpg 只读/清理脚本（用后已删）。全部断言走真实驱动层落库数据，无 mock。
> 探针前基线快照：tasks=0 / request_logs=38 / request_spans=19 / tool_call_logs=467。

| T | 步骤 | 实测结果 | 判定 |
|---|------|----------|------|
| **T1** | .env 注入 `PW_TASK_BUDGET_TOKEN_LIMIT=50` 重启 → 真实 `POST /ai/rag/chat`（真实 LLM 生成 RAG 回答，HTTP 200）→ SQL 查 tasks 最新行 | 新行 `budget_token_limit=50`（begin_task INSERT 解析 config 实证）、`tokens_used=6311>0`、`status=completed` | ✅ |
| **T2** | 同预算下真实 `POST /ai/rag/chat/agent`（强制检索型 query，LLM 真实请求工具）→ span/账目对账 | ① `request_spans` 出现 **2 条熔断证据**：`search_knowledge/tool/blocked`（decision=“phase=retrieval （任务 token 预算已耗尽，工具执行被熔断，module-089）”，**含熔断文本与 module-089**）+ `budget_break/decision/ok`（decision=**`used=5914 limit=50`**）② 同 trace tasks 行 `budget_token_limit=50` ③ request_logs `error=false`、HTTP 200、done 事件含兜底答案（"抱歉，未检索到相关信息。"）、tool_call_logs `search_knowledge ok=false`（审计可见）——**熔断不炸请求实证（AC-23）** | ✅ |
| **T3** | 收口账==预算账：对 3 个探针 trace 逐一对比 `task.tokens_used` 与 `Σ request_logs.usage`（各供应商 prompt+completion） | **5914==5914、5828==5828、5680==5680 逐值精确一致**（预算账与 087 收口账同式同源实证）；且 used(5914) > limit(50) 固有超出按裁定如实呈现、task 终态 completed 未被熔断改写 | ✅ |
| **T4** | `GET /ai/observability/task/{task_id}` 与库对账 + 分桶裁定 | 端点返回 `budget_token_limit=50 / tokens_used=5914` 与 DB 同值（另含 intent=agent、obs 三计数 1/4/1 一致）；`information_schema.columns` 实测 tasks **恰 14 列零新列**；供应商桶读侧可得：`jsonb_each(usage)` → `modelscope: prompt=5800 completion=114`——"分桶走读侧"实证 | ✅ |
| **T5** | `PW_TASK_BUDGET_TOKEN_LIMIT=50` + `PW_TASKS_ENABLED=false` 重启 → agent 请求 → 开关关边界 | tasks 行数 **13→13 零新增**；全局 `budget_break` 计数 1（=R1 探针那条，未新增）、blocked+module-089 文本计数 1（同左）——零 task 零熔断，存量行为逐字 | ✅ |
| **T5b** | 预算 0 默认态（AC-T3：零预算零执法，AC-18） | `PW_TASK_BUDGET_TOKEN_LIMIT=0` 下 agent 请求：工具 `search_knowledge`/`recall_memory` span 均 **status=ok** 真实执行（零拦截）、零 budget_break、task 行 `budget_token_limit=0`——与 087 基线行为逐字 | ✅ |
| **T6** | 探针清理与基线还原 | 一次性脚本用后即删；按探针时间窗圈定 **15 个 trace_id** 四表精确 DELETE：tool_call_logs 472→467 / request_spans 49→19 / request_logs 51→38 / tasks 13→0——**四表逐一还原探针前基线**；.env 从备份恢复 `diff` 全空、备份文件已删；Redis 降级链还原 `deepseek,qwen,zhipu`；8010 进程杀净（netstat 无 LISTENING） | ✅ |

### 3.1 T2 熔断证据链原文（真实驱动层落库数据）

```
task: b5d4ddc7276940adba3aa3a00f33c4a4 ep=/ai/rag/chat/agent status=completed budget=50 used=5914
span search_knowledge/tool/blocked: phase=retrieval （任务 token 预算已耗尽，工具执行被熔断，module-089）
span budget_break/decision/ok: used=5914 limit=50
rlog: ep=agent error=False usage={'modelscope': {'prompt': 5800, 'completion': 114}} sum=5914
对账[收口账==预算账]: task.tokens_used=5914 vs Σusage=5914 ==
tclog: search_knowledge ok=False
```

## 4. Reviewer 3 LOW + 2 备忘逐项独立核验

| # | Reviewer 结论 | Tester 独立核验 | 属实 | 阻塞性 |
|---|---------------|-----------------|------|--------|
| LOW-1 | changelog 测试类计数 17≠20（TestPrimitives 实为 11）；"budget_exceeded 8 语句"不符 | 实测 TestPrimitives 11 个 test 方法（:88-166 逐一清点），1+11+2+3+2+1=20 自洽；AST 重算 set_task_budget 7 / budget_exceeded 6 语句——changelog 两处口径确与实况不符 | 属实 | 非阻塞（纯文档勘误；20 总数与 +35 关键数字本身正确） |
| LOW-2 | 三个零参函数 docstring 缺 Args 段（tasks.py:206-241） | 通读确认 get_budget_limit/budget_used/budget_exceeded 仅 Returns 段；同文件 087 先例 memory_write_allowed 有 "Args: 无（…）"（:196-198） | 属实 | 非阻塞（文档补齐即可，逻辑零影响） |
| LOW-3 | "开关关时 var 仍 set"无专项断言 | TestBeginTask 两例均显式 tasks_enabled=True（:174-202 无 False 分支断言）；代码核验 tasks.py:133-134 set 位于 :135 早退之前——行为正确仅缺回归锁 | 属实 | 非阻塞（建议随下轮变更补 1 项） |
| B1 | AC-16（spans 关执法仍在）无专项单测 + 测试文件头 AC 编号引用错位 | 核验属实：test_budget.py:6/:322 将 SQL 卫生标注为 AC-16；AC-16 真义机制已代码级核验（见 §5 AC-16 行）+ 本轮真实对账兜底 | 属实 | 非阻塞（文档侧统一编号，勿改代码） |
| B2 | AC-15（logs 关恒 False）为分段拼合覆盖 | 核验属实：无 limit>0+空 usage 直接组合断言；机制代码级核验（§5 AC-15 行）平凡成立 | 属实 | 非阻塞 |

## 5. 验收标准核对（AC-1 ~ AC-27 逐项签署）

### 5.1 功能验收

| AC | 要求 | 结论 | 证据（Tester 独立取得） |
|----|------|------|------------------------|
| AC-1 | config 字段默认 0、env 唯一口径 PW_TASK_BUDGET_TOKEN_LIMIT | ✅ | config.py:169 紧随 tasks_enabled；注释明示唯一口径（:167-168）；探针用该名注入成功解析（T1 budget=50 落库），全库无变体名 |
| AC-2 | begin_task 解析 config：=200→INSERT+var 同值；=0→INSERT 恒 0；开关关 var 仍 set | ✅ | tasks.py:133-134/:140；单测 :175-189（=50 双断言）+:191-202（=0 逐字）；**真实实证**：config=50 → tasks.budget_token_limit=50（T1）、config=0 → 0（T5b）；开关关 var-set 代码核验（:133-134 先于 :135 早退）+ T5 真实环境零 task 零执法佐证（专项断言缺位=LOW-3，非阻塞） |
| AC-3 | budget_used 与 087 收口逐字同式 | ✅ | tasks.py:228-229 与 main.py:346-347 并排比对算术式逐字同（仅容器访问多一层 None 防御，语义等价）；**真实对账三 trace 逐值精确一致**（§3 T3） |
| AC-4 | budget_exceeded 四态判定 + >= 边界 + 零 DB 访问 | ✅ | tasks.py:242-245；单测四态齐（:106-130 含 used==limit→True）；函数体仅 ContextVar 读 + observability 内存快照，无 _spawn/session 触达 |
| AC-5 | set_task_budget 语义 + _SQL_BUDGET 形状 | ✅ | 负数 no-op :262-263；正数 var+spawn :264-267（task_id 取 _task_id_var）；_SQL_BUDGET :79-82 两绑定零拼接；单测 :132-166 + SQL 精确串等 :328-332 |
| AC-6 | get_budget_limit 默认 0 / ContextVar default 0 | ✅ | tasks.py:37-38/:206-212；单测 :146-148 |
| AC-7 | 工具层熔断：tool.run 不调、文本含"熔断"+"module-089"、span blocked、record_tool_call 照旧 | ✅（真实实证） | **真实 span**：`search_knowledge/tool/blocked` decision 含熔断文本+module-089；单测 :218-233（assert tool.run 未 await）；tclog `search_knowledge ok=False` 真实落库；span 三态代码（:391-403）零 diff |
| AC-8 | 不触发路径逐字（未超限/limit=0） | ✅（真实实证） | T5b：budget=0 下 search_knowledge/recall_memory span 均 ok 真实执行、零预算 span；存量 tests/agent/ 415 内零改动全过 |
| AC-9 | 循环层熔断：chat_with_tools 不再调、兜底生成、budget_break span（含 used=/limit=）+ warning | ✅（真实实证） | **真实 span** `budget_break/decision/ok: used=5914 limit=50`；uvicorn 日志 warning"任务 token 预算耗尽 (used=5914 limit=50)"；请求 done 含兜底答案；单测 :299-309（assert chat_with_tools 不再调 + fallback 恰一次） |
| AC-10 | 循环层不触发路径零 budget_break | ✅ | T5b 真实：零 budget_break；单测负向 :311-319 |
| AC-11 | langgraph 自动继承 + langgraph_react.py 零 diff | ✅ | 共享 execute_tool_with_log 挂首分支；git diff langgraph_react.py 空（红线核验） |
| AC-12 | 守门重排零回归（if 降 elif 等价） | ✅ | 代码比对 react.py:368-383：budget 守门为首 if，原阶段/权限守门条件逐字降 elif，budget_exceeded=False 时短路等价；存量 test_tool_phase_split/test_tool_retry_dedup/test_tool_call_logs 等全过（415 内） |
| AC-13 | 熔断不改 task 终态、无新状态值 | ✅（真实实证） | T2 熔断 trace task status=**completed**（087 二值之一）；diff 全文无新 status 写入（grep 实证）；finish_task/_SQL_FINISH 零改动 |

### 5.2 边界条件验收

| AC | 要求 | 结论 | 证据 |
|----|------|------|------|
| AC-17 | DDL 零改动、14 列零新列 | ✅ | database.py/verify_tasks.py git diff 空；information_schema 实测恰 14 列（列名清单见 §3 T4） |
| AC-18 | 默认零行为变化 | ✅（真实实证） | T5b：config=0 下零执法零 budget_break 零 blocked、budget_token_limit 恒 0 |
| AC-19 | finish_task/_SQL_FINISH/get_task_overview 零改动 | ✅ | diff 仅新增块 + begin_task 两行；overview 端点真实调用返回 budget_token_limit/tokens_used 与库一致（T4） |
| AC-20 | 收口账==预算账；used 终值可 > limit 如实声明 | ✅（真实实证） | 三 trace 逐值一致（5914/5828/5680）；used 5914 > limit 50 固有超出按裁定呈现，非缺陷 |
| AC-21 | 改动面收口 | ✅ | git status 实证：代码面恰 4 修改（tasks/config/react/conftest）+ 1 新增（test_budget.py）；12 项红线清单 diff 全空 |
| AC-22 | DB 不可用 fail-open；budget_exceeded 不受 DB 影响 | ✅ | set_task_budget 经 _spawn→_run_sql（except Exception+warning :113-114 未触碰，不上抛）；budget_exceeded 零 DB 访问（AC-4 同证） |
| AC-23 | 熔断不炸请求 | ✅（真实实证） | T2：熔断请求 HTTP 200 + done 事件兜底答案 + persist status=completed + rlog error=false |

### 5.3 非功能验收

| AC | 要求 | 结论 | 证据 |
|----|------|------|------|
| AC-24 | 全量回归 1690/0/3 零新增失败 | ✅ | 实测 **1690 passed / 0 failed / 3 skipped**（113.85s）= 1670+20 逐字吻合（AC 文档 ≈1688 为计划期陈旧估值，以 1690 为准） |
| AC-25 | AST 合计 ≤200、新函数 ≤50 行 | ✅ | 独立重算 +35（config +1/tasks +25/react +9）；新增函数最大 7 语句（set_task_budget） |
| AC-26 | docstring 齐全、0 print、0 裸 except、无新 except | ✅（含 LOW-2 非阻塞） | 4 新函数 docstring 全有（Returns 齐；3 个零参函数缺 Args 段=LOW-2）；diff 增量行 grep 实测 0 print / 0 裸 except / 0 新 except |
| AC-27 | git diff --stat 红线实证 | ✅ | 12 项清单逐文件全空（含以 agent/router.py 与 rag/router.py 双写法核验——实际文件为 agent/router.py）；tests/ 仅 conftest +13 纯新增 + test_budget.py 新文件 |

**签署：AC-1~27 全部通过（26 项 ✅ + AC-26 ✅ 附 LOW-2 非阻塞文档项），无 ❌ 项。**

## 6. 环境申报（如实）

- **PG**：localhost:5432（postgres/123456/personal_website），asyncpg `SELECT 1` 通。
- **探针前基线**：tasks=0 / request_logs=38 / request_spans=19 / tool_call_logs=467；探针后四表精确 DELETE 15 个 trace，逐一还原基线（§3 T6）。
- **.env**：探针期临时注入 PW_TASK_BUDGET_TOKEN_LIMIT / PW_TASKS_ENABLED / PW_LLM_PROVIDER 三变量（改前备份）；终态从备份恢复，diff 全空，备份已删。原 .env 无这三项（默认态：limit=0、tasks_enabled=true、provider=deepseek）。
- **Redis**：降级链键 llm:fallback_chain 探针期临时改为 modelscope→zhipu，终态还原原值 `deepseek,qwen,zhipu`。
- **LLM 供应商劣化（存量环境问题，与本模块无关）**：DeepSeek key 401 失效（E1）；ModelScope 免费 API 间歇畸形响应（E2）。探针的真实 LLM 调用实际由 modelscope（V4-Pro）/zhipu（GLM-5.2）承载——usage 按供应商标签照常落库（modelscope/zhipu 桶），budget_used 汇总全供应商，预算机制与供应商选择无关。
- **端口**：uvicorn 8010 三轮启停，终态杀净（netstat 无 LISTENING）。
- **一次性对账脚本**（%TEMP%/m089_recon.py）与探针临时文件用后即删。
- **文档偏差申报**：AC §6 / 派发词的 `uvicorn src.main:app` 实际应为 `main:app`（src/ 无 main.py）；红线清单"rag/router.py"实际文件为 agent/router.py（两种 pathspec 均零 diff，红线结论不变）。

## 7. Tester 新发现

无新增代码缺陷。E1/E2 供应商劣化与 E4 启动命令文档偏差已在 §2/§6 申报；建议文档侧顺手勘误 E4 与红线清单 router 路径（与 Reviewer B1 的 AC 编号勘误同批处理即可）。

## 8. 验收结论

- **✅ 通过（PASS）——module-089 预算账本四阶段闭环验收完成**。
- 核心验收实质"超预算任务被熔断，成本可控"经真实驱动层实证：config 预算真实落库（T1）、双拦截点真实触发（工具层 blocked span 含 module-089 文本 + 循环层 budget_break span 含 used=/limit=，T2）、熔断不炸请求（兜底答案 + HTTP 200 + task completed，T2/AC-23）、收口账==预算账逐值精确（T3）、默认零执法（T5b）、开关关零 task 零熔断（T5）、分桶走读侧零加列（T4）。
- 全量回归 1690/0/3 零新增失败；红线 12 项零 diff；AST +35 ≤ 200；Reviewer 3 LOW + 2 备忘逐项核验属实且均非阻塞（纯文档/回归锁补齐类，建议随下轮变更顺手处理，不单独打回）。
- 遗留（非阻塞，均有归属）：LOW-1/LOW-2 文档勘误、LOW-3 可选补 1 项断言、B1 AC 编号引用由文档侧统一、E4 启动命令文档偏差。
