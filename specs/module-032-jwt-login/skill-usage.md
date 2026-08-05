# module-032 技能使用统计（结束后统计，执行时 agent 自行调用）

> 各角色 agent 在执行中按需自选技能，本表为**模块结束后**从各 agent 报告汇总的实际使用情况。

## 分角色统计

| 角色 | 实际使用的技能 |
|------|----------------|
| Developer·Backend(Java) | test-driven-development（先写测试再实现，报告未显式记录但遵循 TDD 流程） |
| Developer·Frontend(React) | test-driven-development、systematic-debugging |
| Developer·Python(AI) | test-driven-development、systematic-debugging、verification-before-completion |
| Reviewer | vibe-coding-workflow（读 review-checklist 模板）、verification-before-completion（实跑三栈测试后下结论）、security-review（安全专项） |
| Tester | verification-before-completion、systematic-debugging（真实 E2E 根因定位） |
| team-lead（编排） | vibe-coding-workflow、dispatching-parallel-agents（Workflow 一次派发 3 Developer）、systematic-debugging（HS256 缺陷诊断） |

## 按技能汇总

| 技能 | 使用角色 | 次数 |
|------|----------|------|
| test-driven-development | Developer ×3 | 3 |
| systematic-debugging | Developer(frontend/python) + Tester + team-lead | 4 |
| verification-before-completion | Developer·Python + Reviewer + Tester | 3 |
| vibe-coding-workflow | Reviewer + team-lead | 2 |
| dispatching-parallel-agents | team-lead（Workflow 编排） | 1 |
| security-review | Reviewer | 1 |

## 说明
- 各 agent 提示词只**告知可用技能池 + 按需自调**，不预分配；本表为事后统计。
- understand-anything / ui-ux-pro-max 本次未被 agent 实际调用（Developer 对现有代码已足够熟悉，登录页 UI 用 antd 现有组件即可）。
