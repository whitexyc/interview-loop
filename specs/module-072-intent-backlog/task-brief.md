# Module-072 Task Brief：意图路由 Backlog 前三项（上下文改写接入 + WP-D 接线 + 改写喂路由评估）

> 自包含执行简报（docs/项目深挖/04-意图路由.md 第十一节 #1/#2/#3 落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读 + 历史模块结论），无需重新调研。

## 事实（代码实测，2026-08-19）

1. **#1 上下文改写 eval-only**：`contextual_rewrite`（eval/golden/golden_multi_turn.py:134）——把省略句补全成自包含 query，仅评测用；生产检索（engine.py:324 附近）只用当前句，多轮"为什么"检索落空（04 文档 #1 证据）。module-049 的分诊式改写（query_rewrite.py：llm_rewrite + fidelity_check + prepare 并行检索 + select_better）是生产就绪的改写基建——上下文改写应并入该链而非另起炉灶。
2. **#2 WP-D 工具历史信号未接线**：router.py:408-411 `_short_inherit` 已实现 tool_history 分支（含 search_knowledge/generate_answer 且短 query → 强制 knowledge，零 LLM）；但 classify 调用点 **main.py:521 / graph.py:89 / engine.py:268+271 全部没传 tool_history** → 恒 None 不生效（04 文档 #2 证据，低成本即生效）。
3. **#3 query_rewrite_enabled=False**（config.py:216 默认关）：module-049 分诊式改写只喂检索不喂路由；开启可省一次 LLM 路由调用（短路 knowledge）。04 文档 #3 要求"评测验证短路路由不破坏现状后开启"。
4. **历史结论**（module-063/049）：改写喂路由 = WP-C（改写成功且保真通过 → 用改写后 query 路由+检索）；分诊命中 FTS 术语（precise）且非闲聊/实时规则词 → 短路 knowledge。L4 多轮拼接（#4）已降级不做（METRICS 待办 #8，2026-08-16）——**#4 不在本模块范围**。
5. **基线**：全量 1183/0（module-071 后）。
6. **相关测试**：tests/agent/test_multi_turn_routing.py（WP-D 单测已有 3 项：test_kb_tool_history_forces_knowledge / test_generate_tool_history_forces_knowledge / test_non_kb_tool_history_normal_path——全部直调 classify 传 tool_history，接线后应保持绿）；eval/golden/golden_multi_turn.py（12 对多轮评测，三指标：自包含清晰度/意图保持/检索提升）。

## WP-A：#1 上下文改写接入生产（🔴 高）

- `contextual_rewrite` 从 golden_multi_turn.py 迁入生产（合理落点：rag/query_rewrite.py 扩展或新 rag/memory/… 视架构——**与 module-049 分诊式改写链合并**，不另起炉灶）
- 生产接入点：engine._retrieve（多轮场景 history 非空 + 当前句是省略句/指代句）→ 改写 query 喂检索；改写失败/保真不过 → 原 query（保守零回归）
- 开关：复用或新增 PW_ 配置（默认关？还是默认开？——决策留给 Developer 基于 WP-C 评测数据，task-brief 倾向默认开但需 WP-C 数据支持）
- 通过标准：单测（改写触发条件/保真回退/零回归）+ golden_multi_turn 重跑三指标对比（接入前 vs 接入后）

## WP-B：#2 WP-D 工具历史信号接线（🟠 中，低成本）

- classify 调用点接线：main.py:521 / graph.py:89 / engine.py:268+271——从 agent 轨迹（tool_calls 名字列表）取上一轮工具调用传入 tool_history
- 各调用点语境不同：engine.chat（非流式）无 ReAct 轨迹 → 传 None（现状）；agent 端点（react_loop）有轨迹 → 传工具名列表
- 存量单测 3 项保持绿（直调路径不变）；新增接线侧单测（调用点正确传参）
- 通过标准：接线完成 + 3 项存量单测绿 + 新增单测（调用点传参）+ 真实 agent E2E 短 query 命中强制 knowledge（tool_call_logs 可查）

## WP-C：#3 改写喂路由开关评估（🟠 中）

- 评测：golden_multi_turn + golden_intent（或短路路由定向集）对比——短路路由开启 vs 关闭的意图准确率/检索提升
- 达标（无破坏 + 有收益）→ query_rewrite_enabled 默认开（或改写喂路由开关独立）
- 不达标 → 如实标注 + 保持默认关
- 通过标准：评测数字 + 决策（开/不开 + 理由）写入 changelog

## WP-D：回归 + 文档收口

- 全量 1183 基线 + 新增单测全绿（存量测试零改动红线；conftest autouse fixture 若需钉开关对齐 056/058/066 模式）
- changelog + CONTEXT.md（只增不删先备份）+ 三记忆文件
- docs/项目深挖/04-意图路由.md 第十一节 #1/#2/#3 标记完成（或如实更新）

## 纪律项

1. 只动 `rag/query_rewrite.py`（或上下文改写落点）+ `engine.py`（检索/classify 调用点）+ `main.py`/`graph.py`（tool_history 接线）+ `config.py` + 相关单测——**router.py 逻辑零改动**（#2 只需传参不修改已实现逻辑）
2. 上下文改写必须走 module-049 保真预检（fidelity_check 余弦回退）——不引入无保护的新 LLM 调用
3. 判定器确定性优先；不引入 LLM-as-judge
4. 编码调 ponytail skill（最简可行：改写函数迁移 + 三处传参 + 开关评测，不重写路由）
5. 存量测试零改动（改了=FAIL）
6. L4 多轮拼接（#4）不在范围——已降级不做，勿误入
