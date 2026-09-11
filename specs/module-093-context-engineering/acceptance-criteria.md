# module-093 验收标准（AC-1~22 + T1~T6）

> Planner: 2026-09-11 | 配套 plan.md | 红线：`rag/` 与 092 封板资产（`eval/langgraph_parity.py` `parity_telemetry.py` `parity_io.py` `parity_events.py`）零 diff；基线 1849/0/0/3 零新增失败（junitxml 口径）

## 1. 逐条 AC

| # | 名称 | 判定标准 |
|---|------|---------|
| AC-1 | 估算器边界 | `estimate_tokens("")==0`；纯中文/纯英文/混合文本返回值 > 0 且随长度单调 |
| AC-2 | 估算器宁可高估 | 同一文本估算值 ≥ 真实 tiktoken 参考值（抽样 5 条标注样本，报告贴对比） |
| AC-3 | 估算器可单测锁定 | 无网络/无模型依赖，纯函数 |
| AC-4 | 五桶分类 | classify 对典型 messages 返回 `system/tools/user/assistant/tool_results` 五桶，各桶 count 正确 |
| AC-5 | tools 桶来源正确 | tools 桶基于 tool_schemas 序列化估算，与传入 schemas 一致 |
| AC-6 | 观测零行为变化 | observe_context 只读不写 messages；返回 dict 不 mutate 入参 |
| AC-7 | clearing 占位符 | 被清除 tool 消息 content 含 `[tool result cleared:` 与原工具名；**role/tool_call_id/顺序逐字不变** |
| AC-8 | clearing 保留窗口 | 最近 keep_recent 条 tool 消息原文保留；其余清除；清除计数准确 |
| AC-9 | clearing 可恢复 | 被清除的原始结果在 `tool_call_logs` 可查（对拍落库后抽 1 条对账） |
| AC-10 | compaction 块完整性 | 折叠后消息序列中不存在"无配对 assistant 的孤儿 tool 消息"（单测构造嵌套轮次验证） |
| AC-11 | compaction 保留项 | system 消息全部保留；首条 user 原文保留；最近 keep_recent 条保留；摘要为单条消息 |
| AC-12 | compress_view 编排 | 未启用/未超限 → 返回**原 list 引用**（`is` 断言）；启用且超限 → 返回新 list + 元信息四字段 |
| AC-13 | 默认关零行为 | `ctx_compress_enabled=False`（config 默认）时 compress_view 返回原引用；全量回归零新增失败 |
| AC-14 | 两环路共用 | react_loop 与 langgraph_react_loop 均调用 `agent/ctx_manager.compress_view`（无分叉实现）；各接入 diff ≤ 20 行 |
| AC-15 | 观测 span | 开启观测时每轮产出 `ctx_budget` span（decision 含五桶 JSON 摘要）；关闭开关可静音 |
| AC-16 | 压缩 span | 触发 clearing/compaction 时产出 `ctx_compress` span（含 before/after tokens 与计数） |
| AC-17 | 配置回退 | 三配置项 `PW_CTX_*` 环境变量可覆盖；config.py 纯增量（无存量行改动） |
| AC-18 | AST 红线 | `ctx_manager.py` ≤ 200 AST；`ctx_tasks.py + ctx_parity.py` 合计 ≤ 350 AST（plan §5 预申请） |
| AC-19 | 代码规范 | 方法 ≤50 行；public 函数 docstring；无空 except；无魔法数字（阈值全部来自 config） |
| AC-20 | 单测 | 新增单测全绿且断言行为（非 mock 次数凑数）；存量 67 项（parity 系列）不回归 |
| AC-21 | 对拍判据事前定死 | 三判据（质量 −0.10 / tokens ×0.70 / LLM 次数 ×1.15）在跑批**前**写入 plan/ADR，结果逐值照实 |
| AC-22 | 诚实记录 | ctx-report 含：三臂逐剧本明细、误差方向、规则式摘要保真局限、失败任务 fail_reason；不利结论不弱化 |

## 2. T1~T6 对账任务（Tester）

| # | 任务 | 判定 |
|---|------|------|
| T1 | 落库对账 | `agent_eval_runs` 中 `config_snapshot->>'module'='093'` 行数 = 剧本×臂 数；`ctx_mode` 三值齐全；git_commit 可对账 |
| T2 | 判据复算 | 从库内 per_question/元信息独立复算三判据，与 ctx-report 逐值比对 |
| T3 | span 曲线 | 从 spans 抽各臂 history est_tokens 随轮次曲线，验证压缩臂低于 off 臂且触发点与阈值一致 |
| T4 | 可恢复抽查 | 任抽 1 条 cleared 结果，`tool_call_logs` 中原文可查且内容一致（AC-9 实证） |
| T5 | 红线+回归 | `git diff --stat -- ai_service/rag` 为空；092 四文件零 diff；全量回归 junitxml `tests≥1900 量级 / failures=0 / errors=0 / skipped=3` |
| T6 | 清理还原 | 评测 trace 时间窗口径清理（`eval-%` + 日期窗）；临时文件清单处理；无后台进程残留 |

## 3. 真实环境冒烟（Tester 门槛）

```bash
cd interview-personal/ai_service
# 冒烟 1：默认关零行为（不改配置，跑一次真实问答，确认无 ctx_compress span）
# 冒烟 2：开压缩（PW_CTX_COMPRESS_ENABLED=true PW_CTX_TOKEN_THRESHOLD=3000 调低触发），
#         长追问对话 ≥6 轮，确认 ctx_compress span 与占位符进入后续请求
PW_LLM_PROVIDER=opencode .venv/Scripts/python.exe -u -X utf8 -m ...
```

## 4. 签署区

| 角色 | 结论 | 日期 |
|------|------|------|
| Planner | plan + AC 产出 | 2026-09-11 |
| Developer | | |
| Reviewer | | |
| Tester | PASS（附 1 项 minor 非阻塞：092 增强字段未继承） | 2026-09-11 |
