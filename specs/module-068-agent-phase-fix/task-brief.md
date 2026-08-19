# Module-068 Task Brief：Agent 阶段推进死锁修复

> 自包含执行简报（module-066 实测盲区的修复落地）。接手方不需要额外对话上下文，按步骤执行即可。所有"已知事实"均已确认（代码已读 + 066 实测），无需重新调研。

## 事实（代码实测 + module-066 评测，2026-08-17）

1. **死锁机制（react.py）**：`advance_phase`（react.py:154-163）推进条件 = "本轮调用过 generate_answer/verify_answer → 下一轮切 generation"（单向前进）；`schemas_for_phase`（react.py:143-150）按 `ctx.phase` 只暴露当前阶段工具（`tool_phase_split` 默认 true，config.py:105）——**生成工具在检索阶段不可见 → LLM 永远无法调用 → 永远切不到 generation → 死锁在检索阶段**（鸡生蛋）。
2. **066 实测印证**：默认配置 9/9 任务全 fail（4 轮全检索：search_knowledge×2-3 + extract_entities/search_fts/search_vector → 预算耗尽兜底，pass^1=0.0）；`PW_TOOL_PHASE_SPLIT=false` 仍 4 轮全检索（LLM 行为性不调生成工具，pass^1=0.0）；at-002 强行调 generate_answer → 15s AgentTool 超时截断（执行层不校验 schema 暴露——Tester 066 独立发现）。
3. **re_search 双组设计**：检索组+生成组都有（react.py:138 注释："generation 内调 re_search 不回退"）——生成阶段可补检，检索命中即切完全兼容。
4. **预算**：`max_agent_tools=4`（config.py:98）总预算；066 数据：fixture 模式平均步数 2.22（简单任务 2-3 步够）、复杂任务（记忆+检索+补检+生成）需 4-5。
5. **基线**：全量 1102/0（module-066 后：1075 + 27 新增；scripts/test_models.py 1 项 module-050 遗留收集 ERROR 未触碰）。
6. 评测脚本：`python -m eval.agent_tasks --mode agent`（066 交付，真实 LLM+DB 跑，agent_eval_runs 落库）。

## WP-A：死锁修复——检索命中即切 generation（核心，半天）

- `advance_phase(ctx, executed_names)` 签名扩展为接收检索命中信息；推进条件改为 **任一检索工具（search_*/extract_entities/recall_memory）本轮返回非空结果 → 下一轮切 generation**（确定性规则，零 LLM 判断——066 已证 LLM 行为性不可靠）
- 保留原条件（本轮调过生成工具也切，兼容 tool_phase_split=false 路径）
- **防空转兜底**：检索阶段轮次 ≥3 且始终未命中 → 强制切 generation（参数化，config 或常量，按 066 4 轮预算-1 取 3）
- 单测：① 检索命中 → 下轮 schema 含生成工具 ② 3 轮未命中 → 强制切 ③ generation 内 re_search 不回退（回归）④ 原条件（调过生成工具）仍生效
- **通过标准**：单测全绿 + 真实 agent E2E 轨迹出现 generate_answer 调用（不再全检索兜底）

## WP-B：预算按阶段（半天）

- `max_agent_tools=4` 语义细化为阶段预算：**检索阶段 ≤3 次 + 生成阶段 ≤2 次**（总 5；检索 3 轮覆盖 1-2 次检索 + 记忆/实体，生成 2 轮留一次 re_search 补检余量）
- 实现最简：不删总预算字段（兼容旧配置读取），新增阶段上限逻辑（复用现有截断点）；PW_MAX_AGENT_TOOLS 仍可作为总兜底
- 单测：阶段内截断正确（检索 3 次后即使预算剩 2 也不放检索工具）/ 生成 2 次截断 / 总预算兜底仍生效
- **通过标准**：单测全绿 + 066 评测重跑平均步数 ≤6（AC 既有标准）

## WP-C：066 评测重跑验证（半天）

- `python -m eval.agent_tasks --mode agent` 重跑（真实 LLM+DB），对比 066 首跑（pass^1=0.0 / 工具正确率 0.0 / chat 0.6667 / pass^3=0.1）
- 输出新数字 + 更新失败分类报告（预期 9/9 失败中大部分转 pass；残余失败分类更新）
- **不达标不隐藏**：如实记录新数字，残余问题入 backlog
- **通过标准**：pass^1 显著提升（≥0.8 更好，如实记录数字即可）；工具正确率提升

## WP-D：回归 + 文档收口（半天）

- 全量 1102 基线 + 新增单测全绿（存量测试零改动红线；conftest autouse fixture 若需钉开关对齐 056/058/066 模式）
- changelog（项目模板，参考 specs/module-066-agent-evaluation/changelog.md）+ CONTEXT.md（只增不删，先备份）+ 三记忆文件
- 不需要新 ADR（行为修复非架构决策；推进规则变更记录在 changelog）

## 纪律项

1. 只动 react.py 的 advance_phase/阶段相关逻辑 + config.py 预算 + 相关单测——**tool_registry.py / engine.py / 检索链路一律不碰**
2. 判定器/评测集（066 产物）不改不凑数
3. 确定性优先：推进规则零 LLM 判断（不引入"LLM 自报检索完成"类机制）
4. 编码调 ponytail skill（最简可行：改 advance_phase 签名+条件+兜底，不重写循环）
5. 存量测试零改动（改了=FAIL）
