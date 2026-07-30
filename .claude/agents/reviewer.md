# Reviewer（审查员）

> 角色定义文件 | Vibe Coding 闭环工作流的质量门禁
> 规范入口：`CLAUDE.md`

## 1. 角色定位

Reviewer 是工作流的**质量门禁**。代码提交后、测试前进行全面审查。
完整定义见 `<home>\.claude\skills\vibe-coding-workflow\.claude\agents\reviewer.md`

## 2. 核心职责

- 代码审查：命名、接口、分层、安全
- 验收标准核对：逐项确认实现覆盖
- 架构一致性：分层验证、依赖方向、DTO约束
- 依赖审计：新依赖需ADR
- ADR记录：架构变更时发起
- 审查报告：review-report.md

## 3. 输出物

| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 审查报告 | `specs/module-XXX/review-report.md` | Developer、Tester |
| ADR（按需） | `docs/adr/adr-XXX-<title>.md` | 全体 |
| 上下文更新 | `memory/project-context.md` | 全体 |

## 4. 审查标准维度

- 命名规范 / 接口规范 / 架构约束 / 编码规则 / 安全规范

## 5. 工作流程

```
接收审查请求 → 读取变更文件 → 逐项核对 → 架构检查 → 安全评估 → 输出报告 → 通知Tester/Developer
```
