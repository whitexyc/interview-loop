# 验收标准 — Module-068: Agent 阶段推进死锁修复

> Reviewer/Tester 依据：`specs/module-068-agent-phase-fix/plan.md` + 本文件
> 验收基线：全量 **1102/0**（module-067 交付口径）+ 本模块新增单测全绿；**存量测试零改动**（改了 = FAIL）
> 验收命令工作目录：`ai_service/`

## 1. 功能验收

### 1.1 核心路径验收（WP-A：死锁修复）

- [ ] **AC-1 检索命中即切 generation**：react_loop 中任一检索工具（search_knowledge/search_fts/search_vector/search_graph/extract_entities/recall_memory）本轮返回非空真实结果 → 下一轮 LLM 收到的 schema 含 generate_answer（生成组 4 个）；单测断言 tools_seen 序列
- [ ] **AC-2 防空转兜底**：检索阶段轮次 ≥3 且始终未命中 → 强制切 generation（第 4 轮 schema 为生成组）；阈值参数化（`agent_retrieval_max_rounds`，PW_AGENT_RETRIEVAL_MAX_ROUNDS 可覆盖），默认 3
- [ ] **AC-3 原条件保留**：本轮调用过 generate_answer/verify_answer → 下一轮切 generation（旧行为不回归，兼容 tool_phase_split=false 路径）
- [ ] **AC-4 推进规则确定性**：检索命中判定为零 LLM 判断（无"LLM 自报检索完成"类机制），纯函数 `_retrieval_hit(name, result)` 按 工具名 ∈ 检索命中集合 + 结果非空 + 无空结果标记 + extract_entities JSON entities 非空 判定
- [ ] **AC-5 命中判定边界**（单测）：空结果标记 `"（无检索结果）"` / `"（无相关历史记忆）"` 不算命中（非空字符串坑）；工具执行失败空串不算命中；re_search（双组补检工具）不参与命中判定；非检索工具名不参与
- [ ] **AC-6 签名向后兼容**：`advance_phase(ctx, executed_names, executed_results=None)` 缺省 None 时行为 = 旧逻辑——存量 `test_tool_phase_split.py::test_advance_phase_unit` 单列表调用零改动通过
- [ ] **AC-7 真实 E2E 轨迹**：真实 agent chat（或 agent-lg）工具轨迹出现 generate_answer 调用，不再全检索至预算耗尽兜底（对比 066 冒烟 4 轮全检索）

### 1.2 核心路径验收（WP-B：预算按阶段）

- [ ] **AC-8 检索阶段截断**：检索阶段累计执行 3 次后，即使总预算仍剩额度，第 4 次检索工具调用被截断（`allowed` 阶段剩余 = 0 → 兜底/回答）
- [ ] **AC-9 生成阶段截断**：生成阶段累计执行 2 次后截断（生成组内第 3 个工具调用被截断）
- [ ] **AC-10 总预算兜底**：总预算（max_agent_tools 默认 5，PW_MAX_AGENT_TOOLS 覆盖）仍为硬上限——阶段预算让位于总预算（如 PW_MAX_AGENT_TOOLS=2 时总调用 ≤2）
- [ ] **AC-11 开关联动**：`tool_phase_split=false` 时阶段预算失效，回退纯总预算（存量行为逐字）——存量全量工具测试零影响
- [ ] **AC-12 阶段计数口径**：phase_count 按执行时 ctx.phase 计数（检索命中切 generation 后新执行工具计生成阶段）；两条循环（react_loop / langgraph_react_loop）同构

### 1.3 边界条件验收

- [ ] **AC-13 预算=0**：不调用工具、LLM 直接回答（既有路径不回归）
- [ ] **AC-14 预算耗尽兜底**：检索阶段始终未命中且兜底强制切前预算已尽 → 既有 reflector.generate_answer 兜底路径不变（测试钉住）
- [ ] **AC-15 generation 内 re_search**：不回退 retrieval（单向前进），补检口保留（存量回归用例带新参数版本复验）

## 2. 非功能验收

### 2.1 性能验收（WP-C：066 评测重跑）

- [ ] **AC-16 评测重跑完成**：`python -m eval.agent_tasks --mode agent --sample 10 --pass_k 3`（真实 LLM+DB）跑通，agent_eval_runs 落库（eval_type='agent_eval'），评测身份测后清理
- [ ] **AC-17 指标对比如实记录**：pass^1 / 工具正确率 / chat 指标 / pass^3 与 066 首跑（0.0 / 0.0 / 0.6667 / 0.1）对比，新数字如实记录（**不预设成功、不隐藏**）
- [ ] **AC-18 pass^1 显著提升**：pass^1 ≥ 0.8 期望（如未达如实记录数字 + 失败分类更新，不达标不隐藏）
- [ ] **AC-19 平均步数**：平均步数 ≤ 6（066 AC 既有标准）
- [ ] **AC-20 残余失败分类**：失败分类报告更新（预期 9/9 失败中大部分转 pass；残余失败按 判定器四规则分类如实标注），残余问题入 backlog

### 2.2 代码质量验收

- [ ] **AC-21 全量回归**：全量 pytest = **1102 基线 + 新增全绿**（0 failed；`scripts/test_models.py` 1 项 module-050 遗留收集 ERROR 沿用不计）
- [ ] **AC-22 存量测试零改动**：react.py 仅 advance_phase/阶段相关逻辑与预算截断 + config.py 预算字段可动；tool_registry.py / engine.py / 检索链路 / 066 判定器 / 评测集（agent_tasks.json / agent_tasks.py）零改动（git diff 核对）
- [ ] **AC-23 行数口径**：功能代码 ≤ 200 行（plan 预估 ~85 行）；新增单测文件 test_agent_phase_fix.py
- [ ] **AC-24 无新增依赖**：不引入新外部包；配置字段带 PW_ 环境变量覆盖（对齐既有模式）

## 3. 可运行验证命令

| 验收项 | 验证命令（工作目录 ai_service/） | 预期输出 |
|--------|----------------------------------|----------|
| 新增单测 | `python -m pytest tests/agent/test_agent_phase_fix.py -v` | 全部 passed |
| 阶段切分存量回归 | `python -m pytest tests/agent/test_tool_phase_split.py tests/agent/test_agent_tools.py -q` | 全部 passed（零改动） |
| 全量回归 | `python -m pytest -q` | 1102 基线 + 新增全部 passed，0 failed |
| 066 评测重跑 | `python -m eval.agent_tasks --mode agent --sample 10 --pass_k 3` | 输出三层指标 + 落库，对比 066 首跑 |
| 真实 E2E | 启动 uvicorn 后真实 agent chat | 工具轨迹含 generate_answer 调用 |

## 4. 验收结论

- 审查人: <Reviewer 签名>
- 测试人: <Tester 签名>
- 验收时间: 2026-08-XX
- 结论: [ ] 通过 / [ ] 不通过
- 备注: <说明>
