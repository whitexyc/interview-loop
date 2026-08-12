# 用户画像（User Profile）

> 项目级共享记忆 | 2026-08-11 | 所有 Agent 遵循（vibe-coding-workflow 角色）

## 身份

用户是求职中的**大模型应用开发工程师（全栈）**，用本项目（Agentic RAG 技术文档知识库问答系统）作为求职简历的核心项目，面试导向很强（简历/弹药/面试话术是工作重点）。

## 沟通偏好

- 自称"我是小白"——讲解技术概念时**必须用大白话 + 类比**（考试正确率/质检员/备胎/游戏存档等），不要堆术语
- 习惯"**先规划、等我确认再执行**"（2026-08-11 明确指示："完成后等我通知再执行"）——规划后不要擅自执行
- 重视诚实：假数字/未验证结论比没有数字更不可接受（图谱消融 0.0000 是环境故障就不写，kappa 未达门槛就如实标注）

## 工作流要求

vibe-coding-workflow：
- Planner 写 specs（plan.md + acceptance-criteria.md）→ Workflow **一次性派发** Developer/Reviewer/Tester → 完成后单次提交
- 每个 agent prompt 三块式：上下文（spec 路径+涉及文件）、可用技能、交接协议（结构化 schema + 写对应文档）
- Review→Dev 回环在 pipeline 内：PASS 进 Tester，CONDITIONAL 自动回修（最多 3 轮），FAIL 终止
- 各 agent 写自己的文档 + 更新本目录三记忆文件（project-context / agent-activity-log / file-index）
- Planner **绝不接管** Developer/Reviewer/Tester 的工作
- 模板资产位置：`.claude/agents/*.md` 角色定义；`docs/vibe-coding-workflow-reuse-guide.md` 复用指南

## 技术背景（便于对齐解释深度）

已交付模块（截至 2026-08-11）：module-001~051，全量 pytest **614 全绿**。核心：Agentic RAG（分诊式改写 / 三通道检索 Hit@5 0.9714 / 记忆进化 / HHEM 专职幻觉裁判）。详细技术记录见 `project-context.md` 与 `file-index.md`。
