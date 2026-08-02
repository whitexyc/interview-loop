# 共享记忆库维护补充规范

> 本文是 vibe-coding-workflow 规范 §10 的**执行强化**，解决"规范存在但执行断裂"的问题。
> 背景：module-001~030 期间，`project-context.md` 有维护，但 `file-index.md` 和 `agent-activity-log.md` 停更在项目初期。

## 根因

规范要求"全体阶段交接时读写 project-context.md"，但缺少：
1. **强制检查**：阶段退出条件没有明确"必须更新三个记忆文件"
2. **责任到人**：Workflow 脚本 spawn 的 Agent 没被告知"完成时必须更新记忆库"
3. **可执行**：file-index 逐文件维护对几十模块不现实，需要"汇总式"维护策略

## 强制规则（Workflow 编排者执行）

每次模块闭环时，主会话（Planner）在 Workflow 脚本的每个 Agent prompt 中**强制加入**：

```
完成后必须：
1. 更新 ${WORKDIR}/memory/project-context.md（模块状态 → 👀 待审查 / 决策记录）
2. 若新增了重要文件，更新 ${WORKDIR}/memory/file-index.md（追加到对应分类）
3. 在 ${WORKDIR}/memory/agent-activity-log.md 追加一条活动记录
```

## 维护策略（务实版）

| 文件 | 策略 |
|------|------|
| **project-context.md** | 每模块完成更新（已完成模块清单 / 迭代版本 / 技术决策 / ADR 索引 / 待办） |
| **file-index.md** | 采用"分类汇总"而非逐文件：核心文件（ai_service/frontend 关键模块）+ specs 模块目录索引；新增重要文件时追加 |
| **agent-activity-log.md** | 阶段汇总（按模块一行，指向 specs/ 目录），不逐条琐碎记录 |

## 验证

新 Agent 入场时按规范读 `file-index.md` 应能定位到任一模块的文件（核心文件分类 + specs 目录索引兜底）。

---

关联：`<home>\.claude\skills\vibe-coding-workflow\CLAUDE.md` §10（原规范）、`vibe-coding-loop.md` §7（读写时机）。
