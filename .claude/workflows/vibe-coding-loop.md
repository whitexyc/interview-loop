# Vibe Coding 闭环工作流编排

> 工作流定义文件 | Vibe Coding 闭环工作流的编排中枢
> 规范入口：`CLAUDE.md`（所有 Agent 必须遵循）
> Agent 定义：`.claude/agents/planner.md`、`developer.md`、`reviewer.md`、`tester.md`

## 目录

| 章节 | 标题 |
|------|------|
| 1 | [工作流概述](#1-工作流概述) |
| 2 | [工作流触发条件](#2-工作流触发条件) |
| 3 | [各阶段顺序和依赖关系](#3-各阶段顺序和依赖关系) |
| 4 | [每个阶段的输入 / 输出](#4-每个阶段的输入--输出) |
| 5 | [异常处理与回退路径](#5-异常处理与回退路径) |
| 6 | [版本管理规则](#6-版本管理规则) |
| 7 | [共享记忆库读写时机](#7-共享记忆库读写时机) |
| 8 | [工作流完整执行时序](#8-工作流完整执行时序) |
| 9 | [工作流配置](#9-工作流配置) |
| 10 | [工作流终止条件](#10-工作流终止条件) |
| 11 | [快速参考](#11-快速参考) |

---

## 1. 工作流概述

本文件定义 Vibe Coding 闭环工作流的完整执行流程，包括：

- 工作流触发条件
- 各阶段（Plan → Develop → Review → Test → Post-Completion Review）的顺序和依赖关系
- 每个阶段的输入 / 输出
- 异常处理与回退路径
- 版本管理规则
- 共享记忆库（`project-context.md`）的读写时机

### 1.1 参与角色

| 角色 | 定义文件 | 核心职责 | 可扩展 |
|------|----------|----------|--------|
| Planner | `.claude/agents/planner.md` | 需求拆解、计划制定、验收标准定义 | 固定 1 个 |
| Developer | `.claude/agents/developer.md` | 代码实现、变更记录、自我修复 | ✅ 按需（Frontend/Backend/Service） |
| Reviewer | `.claude/agents/reviewer.md` | 代码审查、架构检查、安全评估 | ✅ 按需（可按端分别审查） |
| Tester | `.claude/agents/tester.md` | 测试编写、验收执行、报告生成 | ✅ 按需（Unit/E2E） |
| Final Reviewer（终审 Agent） | 完工后独立启动 | 全项目文档一致性、技术栈验证、全量安全审计 | 固定 1 个 |

> **扩展规则**：Planner 在 plan.md 中声明每个模块的 Agent 配置清单。同名角色多个 Agent 独立工作，分别产出。

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **闭环驱动** | Plan → Develop → Review → Test 四阶段形成闭环，每模块必走完全流程 |
| **验收驱动** | 每个模块必须先定义验收标准，再进入开发 |
| **分步迭代** | 一次只处理一个模块（默认 ≤ 200 行，特殊情况可在 plan.md 调整），完成后再进入下一个。**例外（module-015）**：只读角色（下一模块的 Planner）可与当前模块的 Tester 并行——零写冲突，实测省 20-35 分钟/模块；写代码角色（Developer）严禁并行 |
| **异常回退** | 每个阶段失败有明确的回退路径和重试上限，存在进展证据时可申请放宽（见 §5.5） |
| **三记忆文件同步** | 所有阶段通过 `project-context.md` / `file-index.md` / `agent-activity-log.md` 三文件同步状态 |
| **定时监控** | 调度方每 2-5 分钟主动检查 Agent 状态，超时立即介入（见 §5.0） |

> **§5.0 定时检查**由补充内容升级为正式特性，全链路引用：§2.1 前置检查、§4.1 处理步骤、§5.5 升级申请。

---

## 2. 工作流触发条件

### 2.0 环境预检清单（任何模块启动前必须核对）

> 新项目首次触发时由 Planner 按 §2.1 前置检查逐项核对；每个模块启动前复核环境是否仍就绪，避免模块中途才发现环境问题。

- [ ] **子代理模型可用**：`CLAUDE_CODE_SUBAGENT_MODEL` 指向可用模型（必要时在 `.claude/settings.json` 的 `env` 块覆盖）；用 1 个最小子代理冒烟验证，应正常返回而非 400。
- [ ] **权限白名单已配置**：`.claude/settings.json` 已配置基线 `allow` 白名单，如 `PowerShell(git*,python*,pip*,uv*)` + `Write(*.md,*.py)`，防止权限分类器（LLM）临时不可用时 auto 模式命令被拦截。
- [ ] **平台工具链确认**：编译器、Windows 长路径设置（`LongPathsEnabled`）、`pytest-asyncio` 等测试收集依赖已就绪，避免 async 用例被静默跳过。

### 2.1 首次触发（新项目启动）

**触发条件**：用户提出第一个需求

**前置检查**：
- [ ] `CLAUDE.md` 已存在（项目规范就绪）
- [ ] `memory/project-context.md` 已初始化（共享记忆库就绪）
- [ ] 技术栈已确认（`tech-stack.md` 已填写完整）
- [ ] `CLAUDE_CODE_SUBAGENT_MODEL` 指向有效模型（启动 1 个最小子代理冒烟验证，应正常返回而非 400）
- [ ] `.claude/settings.json` 已配置基线权限 `allow` 白名单（如 `PowerShell(git*,python*,pip*,uv*)` + `Write(*.md,*.py)`）
- [ ] 如 Python 项目含 async 测试，确认 `pytest-asyncio` 等插件已安装

> **运行期间监控**：工作流运行期间由 **Planner** 执行 §5.0 定时检查，每 2-5 分钟主动检查 Agent 状态，超时立即介入。

**启动流程**：
1. Planner 接收用户需求
2. Planner 确认 `tech-stack.md` 已填写（如未填写，与用户沟通确认后填写）
3. Planner 输出第一个模块（module-001）的 plan.md + acceptance-criteria.md
4. 进入正常闭环流程（见第 3 节）

### 2.2 正常触发（后续模块）

**触发条件**（任一）：
- 上一模块测试通过，`project-context.md` 标记为 ✅
- 用户提出新需求
- 需求变更触发新模块拆解

**前置检查**：
- [ ] `project-context.md` 中有下一个待办模块
- [ ] 上一模块（如有）已完成闭环（测试通过）

### 2.3 异常触发（回退）

**触发条件**：
- Developer 连续 3 次开发失败
- Reviewer 连续 3 轮审查不通过
- Tester 连续 3 次测试不通过
- 模块标记为 `blocked`

**回退流程**：见第 5 节「异常处理与回退路径」

---

## 3. 各阶段顺序和依赖关系

### 3.1 闭环流程图

```
                        ┌─────────┐
                        │  用户   │
                        │  需求   │
                        └────┬────┘
                             ▼
                    ┌──────────────────┐
              ┌─────│     Planner      │◄──────────────┐
              │     │  需求拆解 & 计划  │               │
              │     └────────┬─────────┘               │
              │              │ plan.md                  │
              │              │ acceptance-criteria.md   │
              │              ▼                          │
              │     ┌──────────────────┐               │
              │     │    Developer     │◄──────┐       │
              │     │   编码实现        │       │       │
              │     └────────┬─────────┘       │       │
              │              │ 代码 + changelog │       │
              │              ▼                  │       │
              │     ┌──────────────────┐       │       │
              │     │    Reviewer      │──不通过──┘       │
              │     │   代码审查        │               │
              │     └────────┬─────────┘               │
              │              │ 审查通过                  │
              │              │ review-report.md         │
              │              ▼                          │
              │     ┌──────────────────┐               │
              └─────│     Tester       │               │
           测试不通过│   测试 & 验收      │               │
                    └────────┬─────────┘               │
                             │ 测试通过                  │
                             │ test-report.md           │
                             ▼                          │
                    ┌──────────────────┐               │
                    │  模块完成         │               │
                    │  更新 project-    │               │
                    │  context.md       │               │
                    │  进入下一模块      │───────────────┘
                    └────────┬─────────┘
                             │ 全部模块完成
                             ▼
                    ┌──────────────────┐
                    │  Final Reviewer  │
                    │  完工终审         │
                    │  (独立Agent启动)  │
                    └────────┬─────────┘
                             │ REVIEW-FINAL.md
                             ▼
                    ┌──────────────────┐
                    │  项目交付 ✅      │
                    └──────────────────┘
```

**每模块闭环**：Plan → Develop → Review → Test → 下一模块
**全项目闭环**：所有模块完成后 → 完工终审 → 项目交付

### 3.2 阶段依赖矩阵

| 阶段 | 前置阶段 | 输入依赖 | 输出物 | 下一阶段 |
|------|----------|----------|--------|----------|
| Plan | 无（或回退触发） | 用户需求 + project-context.md | plan.md + acceptance-criteria.md | Develop |
| Develop | Plan | plan.md + acceptance-criteria.md + CLAUDE.md | 源代码 + changelog.md | Review |
| Review | Develop | changelog.md + plan.md + acceptance-criteria.md + 源代码 | review-report.md + ADR（按需） | Test（通过）/ Develop（不通过） |
| Test | Review | review-report.md + acceptance-criteria.md + 源代码 + changelog.md | test-report.md + 测试代码 | 完成（通过）/ Develop（不通过） |
| Post-Completion Review | 全部模块 Test 通过 | 全部模块产出 + tech-stack.md + 全部 ADR + 全部源代码 | REVIEW-FINAL.md | 项目交付 |

### 3.3 阶段间数据流

```
project-context.md ←────── 全体读写 ──────→ project-context.md
     │                                            ▲
     ▼                                            │
plan.md ──→ Developer ──→ changelog.md ──→ Reviewer ──→ review-report.md ──→ Tester ──→ test-report.md
     │                          │                      │                       │              │
     │                          │                      │                       │              │
     └── acceptance-criteria.md ──────────────────────┴───────────────────────┘              │
                                                                                          │
                                                          project-context.md ◄────────────┘
                                                          （模块标记完成）
```

---

## 4. 每个阶段的输入 / 输出

### 4.1 Plan 阶段（Planner）

**执行者**：Planner

**输入**：
| 输入项 | 来源 | 说明 |
|--------|------|------|
| 用户需求 | 用户 | 原始需求，可能模糊 |
| project-context.md | 共享记忆库 | 项目当前状态、已完成模块 |
| 阻塞反馈（回退时） | Developer / Tester | 失败原因分析 |

**处理**：
1. 读取 `.claude/agents/planner.md` 确认职责与输出规范
2. 读取 `project-context.md` 了解项目状态
3. 需求澄清（列出问题 → 用户确认）
4. 模块拆分（编号 + 依赖图 + 每模块默认 ≤ 200 行，特殊情况可调整）
5. 编写 `specs/module-XXX-<name>/plan.md`
6. 编写 `specs/module-XXX-<name>/acceptance-criteria.md`
7. 更新 `project-context.md`（添加待办事项、更新迭代状态）
8. 更新 `agent-activity-log.md`（[PLAN]/[HANDOFF] 记录）+ `file-index.md`（模块索引行）
9. 按需编写 `docs/adr/adr-XXX-<title>.md`
10. 工作流运行期间按 §5.0 定时检查 Agent 状态并介入（调度方职责，每 2-5 分钟）

**输出**：
| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 开发计划 | `specs/module-XXX-<name>/plan.md` | Developer |
| 验收标准 | `specs/module-XXX-<name>/acceptance-criteria.md` | Reviewer、Tester |
| ADR（按需） | `docs/adr/adr-XXX-<title>.md` | 全体 |
| 上下文更新 | `memory/project-context.md` | 全体 |
| 通知消息 | SendMessage → Developer | Developer |

**阶段退出条件**：
- plan.md 和 acceptance-criteria.md 已输出
- memory/project-context.md 已更新（待办事项、迭代状态）
- memory/agent-activity-log.md 已追加当天/本阶段活动记录（[HANDOFF]/[CONTEXT]）
- memory/file-index.md 已追加/更新本次产出文件索引（plan.md / acceptance-criteria.md 模块行）
- 已通过 SendMessage 通知 Developer

### 4.2 Develop 阶段（Developer）

**执行者**：Developer

**输入**：
| 输入项 | 来源 | 路径 |
|--------|------|------|
| 开发计划 | Planner | `specs/module-XXX-<name>/plan.md` |
| 验收标准 | Planner | `specs/module-XXX-<name>/acceptance-criteria.md` |
| 项目上下文 | 共享记忆库 | `project-context.md` |
| 编码规范 | 项目 | `CLAUDE.md` |
| 审查反馈（不通过时） | Reviewer | `specs/module-XXX-<name>/review-report.md` |
| 测试反馈（不通过时） | Tester | `specs/module-XXX-<name>/test-report.md` |

**处理**：
1. 读取 `.claude/agents/developer.md` 确认职责与输出规范
2. 读取 plan.md + acceptance-criteria.md + project-context.md + CLAUDE.md
3. 输出实现计划（影响面分析 + 文件变更列表 + 关键设计说明）
4. 编码实现（遵循分层架构和编码规范）
5. 遇到报错：归因分析 → 修复 → 重新验证（最多 3 次）
6. 本地编译 + 自测
7. 输出 `specs/module-XXX-<name>/changelog.md`
8. 更新 `memory/project-context.md`（模块状态 → 👀 待审查）
9. 更新 `memory/agent-activity-log.md`（[CODE]/[HANDOFF] 记录）+ `memory/file-index.md`（changelog.md 与新增源码/迁移文件索引行）
10. 创建 Git 分支并提交代码（见第 6 节）

**输出**：
| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 源代码 | `backend/src/` 或 `frontend/src/` | Reviewer、Tester |
| 变更日志 | `specs/module-XXX-<name>/changelog.md` | Reviewer |
| 数据库迁移 | `backend/src/main/resources/db/migration/` | Reviewer |
| 上下文更新 | `memory/project-context.md` | 全体 |
| 通知消息 | SendMessage → Reviewer | Reviewer |

**阶段退出条件**：
- 本地编译通过（`make build`）
- 本地自测通过
- changelog.md 已输出
- memory/project-context.md 已更新（模块状态 → 👀 待审查）
- memory/agent-activity-log.md 已追加当天/本阶段活动记录（[CODE]/[HANDOFF]）
- memory/file-index.md 已追加/更新本次产出文件索引（changelog.md + 新增源码/迁移文件）
- 已通过 SendMessage 通知 Reviewer

### 4.3 Review 阶段（Reviewer）

**执行者**：Reviewer

**输入**：
| 输入项 | 来源 | 路径 |
|--------|------|------|
| 变更日志 | Developer | `specs/module-XXX-<name>/changelog.md` |
| 开发计划 | Planner | `specs/module-XXX-<name>/plan.md` |
| 验收标准 | Planner | `specs/module-XXX-<name>/acceptance-criteria.md` |
| 源代码 | Developer | `backend/src/` 或 `frontend/src/` |
| 项目上下文 | 共享记忆库 | `project-context.md` |
| 编码规范 | 项目 | `CLAUDE.md` |

**处理**：
1. 读取 `.claude/agents/reviewer.md` 确认职责与输出规范
2. 读取 changelog.md 了解变更范围
3. 读取 plan.md + acceptance-criteria.md 获取审查基准
4. 阅读变更的代码文件（完整文件，非仅 diff）
5. 逐项核对审查检查清单（命名、接口、架构、编码、安全）
6. 核对验收标准覆盖情况
7. 架构一致性检查（分层、依赖方向、DTO 约束）
8. 依赖审计（是否引入未计划依赖）
9. 安全评估（SQL 注入、XSS、密码安全、API Key）
10. 输出 review-report.md
11. 按需记录 ADR
12. 更新 `project-context.md`（审查结论、ADR）
13. 更新 `agent-activity-log.md`（[REVIEW]/[HANDOFF] 记录）+ `file-index.md`（review-report.md / ADR 索引）

**输出**：
| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 审查报告 | `specs/module-XXX-<name>/review-report.md` | Developer、Tester |
| ADR（按需） | `docs/adr/adr-XXX-<title>.md` | 全体 |
| 上下文更新 | `memory/project-context.md` | 全体 |
| 通知消息 | SendMessage → Tester（通过）/ Developer（不通过） | 对应角色 |

**阶段退出条件**：

通过路径：
- review-report.md 结论为通过
- memory/project-context.md 已更新（审查结论、ADR）
- memory/agent-activity-log.md 已追加 [REVIEW]/[HANDOFF] 记录
- memory/file-index.md 已追加/更新本次产出文件索引（review-report.md / ADR 条目）
- 已通过 SendMessage 通知 Tester

不通过路径：
- review-report.md 结论为不通过 + 问题列表
- memory/project-context.md 已更新（审查结论）
- memory/agent-activity-log.md 已追加 [REVIEW] 记录
- memory/file-index.md 已追加/更新本次产出文件索引（review-report.md）
- 已通过 SendMessage 通知 Developer 修复

### 4.4 Test 阶段（Tester）

**执行者**：Tester

**输入**：
| 输入项 | 来源 | 路径 |
|--------|------|------|
| 审查报告 | Reviewer | `specs/module-XXX-<name>/review-report.md` |
| 验收标准 | Planner | `specs/module-XXX-<name>/acceptance-criteria.md` |
| 开发计划 | Planner | `specs/module-XXX-<name>/plan.md` |
| 变更日志 | Developer | `specs/module-XXX-<name>/changelog.md` |
| 源代码 | Developer | `backend/src/` 或 `frontend/src/` |
| 项目上下文 | 共享记忆库 | `project-context.md` |
| 编码规范 | 项目 | `CLAUDE.md` |

**处理**：
1. 读取 `.claude/agents/tester.md` 确认职责与输出规范
2. 读取 review-report.md + acceptance-criteria.md + plan.md + changelog.md
3. 读取 `project-context.md` 确定回归范围
4. 编写测试用例（单元测试默认 ≥ 80% + 集成测试默认 ≥ 60% + 异常兜底测试，可按模块调整）
5. 运行单元测试
6. 运行集成测试
7. 运行真实依赖冒烟：凡模块涉及 DB/第三方服务/AI 调用，必须用真实 DB/真实服务（非 mock）跑通一条核心链路（读 + 写），通过后方可继续
8. 运行回归测试（全量已有测试，100% 通过要求）
9. 失败归因：回归/单元失败先分类——(a) 环境性失败（缺 mock、依赖服务未启动、测试收集失败如缺 `pytest-asyncio` 导致 async 用例未被收集）→ 修复环境/补齐 mock 后重跑，不消耗业务重试次数、不阻塞；(b) 真实回归 → 走 §5.4 失败回退
10. 生成 test-report.md（失败详情含『失败类别』字段：环境性 / 真实回归 / 待排查）
11. 在 acceptance-criteria.md 签署验收结论（如通过）
12. 更新 `project-context.md`（模块状态 → ✅ 完成）
13. 更新 `agent-activity-log.md`（[TEST]/[HANDOFF] 记录）+ `file-index.md`（test-report.md / 测试代码索引行）

**输出**：
| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 测试报告 | `specs/module-XXX-<name>/test-report.md` | Developer、Reviewer |
| 测试代码 | `backend/src/test/` 或 `frontend/src/` | 全体 |
| 上下文更新 | `memory/project-context.md` | 全体 |
| 通知消息 | SendMessage → Developer + team-lead（通过）/ Developer（不通过） | 对应角色 |

**阶段退出条件**：

通过路径：
- test-report.md 结论为通过
- 回归测试 100% 通过
- 真实环境冒烟通过（如模块含 DB/外部依赖交互）
- acceptance-criteria.md 已签署验收结论
- memory/project-context.md 模块标记为 ✅
- memory/agent-activity-log.md 已追加 [TEST]/[HANDOFF] 记录
- memory/file-index.md 已追加/更新本次产出文件索引（test-report.md / 测试代码）
- 已通过 SendMessage 通知 Developer 和 team-lead
- Git 提交代码（见第 6 节）

不通过路径：
- test-report.md 结论为不通过 + 失败详情（含『失败类别』字段）
- 环境性失败：按归因修复环境/测试后重跑，不消耗业务重试次数
- 真实回归：已通过 SendMessage 通知 Developer 修复

---

### 4.5 完工终审阶段（Post-Completion Review）

**触发条件**：
- project-context.md 中所有模块状态均为"已完成"
- 最后一个模块的 test-report.md 结论为通过

**执行**：启动一个独立的审查 Agent，对全项目进行最终验证（非 Reviewer 角色复用）。

**输入**：
| 输入项 | 路径 | 说明 |
|--------|------|------|
| 全部模块产出 | `specs/` 目录下所有子目录 | plan.md / changelog.md / review-report.md / test-report.md |
| 技术栈配置 | `tech-stack.md` | 验证实际依赖与配置一致性 |
| 全部 ADR | `docs/adr/` | ADR 链完整性验证 |
| 全部源代码 | `backend/src/` + `frontend/src/` | 全量安全审计 |
| 项目上下文 | `memory/project-context.md` | 技术债务清单 |

**审查内容**：
1. **文档一致性**：所有模块文档交叉比对，确保跨模块引用准确
2. **技术栈一致性**：`tech-stack.md` 配置 vs 实际依赖版本
3. **ADR 链完整性**：决策链是否完整，是否有未记录的架构变更
4. **全量安全审计**：SQL 注入、XSS、CSRF、密码安全、API Key、敏感信息日志
5. **技术债务汇总**：从各模块的 review-report.md 中汇总已知技术债务

**输出**：
| 输出物 | 路径 | 接收方 |
|--------|------|--------|
| 终审报告 | `REVIEW-FINAL.md` | 全体 Agent + 用户 |
| 上下文更新 | `memory/project-context.md` | 全体 |

**审查标准**：与 Reviewer（审查员）相同——每个问题必须有根因分析 + 修复示例，禁止留钩子。

**退出条件**：
- REVIEW-FINAL.md 已输出
- 所有 P0 问题已修复或记录为已知技术债务
- memory/project-context.md 已更新项目状态为"终审完成"

---

## 5. 异常处理与回退路径

### 5.0 定时检查与超时介入（Teammate 状态监控）

> 本节为**正式特性**（非补充内容）：由调度方（Planner / 工作流编排者）强制执行，全链路引用见 §2.1 前置检查、§4.1 处理步骤、§5.5 升级申请。

**原则**：工作流是长时间运行的多 Agent 协作，Agent（Teammate）可能因权限拦截、模型不可用、
死循环、等待用户输入等原因"卡住"。调度方（Planner / 工作流编排者）**必须主动定期检查**，
不能被动等待 Agent 汇报。

#### 5.0.1 检查频率

| 阶段 | 检查频率 | 说明 |
|------|----------|------|
| 任一 Agent 运行中 | 每 **2-5 分钟** | 检查 Agent 是否仍在产出（transcript 大小 / 最后活动时间） |
| 阶段交接等待 | 每 **2 分钟** | 确认上一阶段 Agent 已返回、文档已产出 |
| 无活动超过阈值 | **立即介入** | 见下方超时判定 |

#### 5.0.2 超时判定标准

| 场景 | 判定标准 | 可能原因 | 介入动作 |
|------|----------|----------|----------|
| Agent transcript 长时间不增长 | 最后活动 > **10 分钟** | 卡在权限拦截 / 等待输入 | 检查其最后输出，识别阻塞点 |
| Agent 反复执行同一失败操作 | 同错误出现 > 3 次 | 权限 deny / 模型不可用 / 死循环 | 修复权限配置，或 SendMessage 通知 Agent 换路径 |
| 阶段文档未按时产出 | 超时未出现 changelog/review-report | Agent 未完成任务 | 检查其进度，必要时介入或重试 |
| Agent 返回异常 | 返回值为 null / 报错 | 模型故障 / 工具失败 | 重试一次；仍失败则换 Agent 或回退 |

#### 5.0.3 常见阻塞及介入方式

| 阻塞类型 | 识别信号 | 介入方式 |
|----------|----------|----------|
| **权限拦截** | transcript 中出现 `denied` / `classifier` / `unavailable` | 检查 `settings.json` 权限白名单，补充 `allow` 规则后**重试该 Agent**；可直接复用白名单示例 `PowerShell(git*,python*,pip*,uv*)` + `Write(*.md,*.py)` |
| **模型不可用** | 出现 `temporarily unavailable` | 等待恢复或切换模型；子代理需确认 `CLAUDE_CODE_SUBAGENT_MODEL` 正确 |
| **死循环** | Agent 反复执行同一操作无进展 | SendMessage 告知其停止并换策略，或直接介入修改 |
| **等待输入** | transcript 停在 user 请求 | 检查是否需要人工确认，补充明确指令 |

#### 5.0.4 介入原则

1. **先观察后介入**：检查 transcript 确认 Agent 是真的卡住，还是在做合理的深度调查
2. **最小干预**：优先修复环境（权限/模型），而非打断 Agent 的工作
3. **记录介入**：每次介入在 `agent-activity-log.md` 追加 `[UNBLOCKED]` 记录，说明原因和动作
4. **超时升级**：介入后仍无法推进 → 按 5.5 模块阻塞处理，回退 Planner

### 5.1 异常分类与处理策略

| 异常场景 | 触发条件 | 处理策略 | 回退到 | 重试上限 |
|----------|----------|----------|--------|----------|
| Developer 编译失败 | `make build` 报错 | Developer 自行归因修复 | 自修复 | 3 次 |
| Developer 方案不可行 | 技术依赖不存在 | SendMessage 通知 Planner | Planner | - |
| Reviewer 审查不通过 | review-report.md 结论为不通过 | Developer 按 review-report.md 修复 | Developer | 3 轮 |
| Tester 测试不通过 | test-report.md 结论为不通过 | Developer 按 test-report.md 修复 | Developer | 3 次 |
| 模块连续阻塞 | 3 次重试耗尽 | Planner 重新拆解模块 | Planner | - |
| 依赖未就绪 | 前置模块未完成 | 等待或调整模块顺序 | Planner | - |

### 5.2 Developer 自修复流程

```
Developer 编码 → 编译/自测报错
    │
    ▼
归因分析（错误信息喂回给自己）
    │
    ├── 可修复 → 修复代码 → 重新编译/自测
    │              ├── 通过 → 继续 Review 阶段
    │              └── 仍失败 → 重试计数 +1
    │                   └── 重试 < 3 次 → 继续归因修复
    │                   └── 重试 ≥ 3 次 → 回退到 Planner
    │
    └── 不可修复（方案问题）→ SendMessage 通知 Planner
```

### 5.3 Reviewer 不通过回退流程

```
Reviewer 审查 → 不通过
    │
    ▼
Developer 读取 review-report.md 问题列表
    │
    ▼
逐项修复 → 重新提交 → Reviewer 重新审查
    │
    ├── 通过 → 进入 Test 阶段
    │
    └── 不通过 → 审查轮次 +1
         └── 轮次 < 3 → 继续修复
         └── 轮次 ≥ 3 → 模块标记 blocked → 回退到 Planner
```

### 5.4 Tester 不通过回退流程

```
Tester 测试 → 不通过
    │
    ▼
Developer 读取 test-report.md 失败详情
    │
    ▼
修复代码 + 新增回归测试
    │
    ▼
Reviewer 快速确认修复范围（非完整审查）
    │
    ▼
Tester 重新运行失败测试 + 回归测试
    │
    ├── 全部通过 → 模块完成
    │
    └── 仍有失败 → 重试计数 +1
         └── 重试 < 3 次 → 继续修复
         └── 重试 ≥ 3 次 → 模块标记 blocked → 回退到 Planner
```

### 5.5 模块阻塞处理

**触发条件**：Developer / Reviewer / Tester 任一阶段重试耗尽

**处理流程**：
1. **升级申请（有进展证据时）**：当存在进展证据（已复现根因 / 已缩小范围 / 已有复现测试）时，当前执行者可向 Planner/team-lead 申请放宽重试上限（如 3→8，对应 §9.1 的 `max_*_escalated` 参数）；Planner 评估批准后，在 `agent-activity-log.md` 追加 `[ESCALATE]` 记录，并按放宽后上限继续重试，不立即标记 blocked。升级申请被拒绝或放宽后仍耗尽 → 进入下一步。
2. 当前阶段执行者将模块标记为 `blocked`
3. SendMessage 通知 Planner（含失败原因摘要）
4. SendMessage 通知 team-lead（含阻塞摘要）
5. Planner 分析失败原因（读取 changelog / review-report / test-report）
6. Planner 决策：
   - **重新拆解**：更新 plan.md 版本号，重新通知 Developer
   - **补充澄清**：补充计划信息，重新通知 Developer
   - **降级处理**：缩减模块范围，更新验收标准
7. 重新进入正常闭环流程

### 5.6 快速审查通道

Tester 测试失败 → Developer 修复后，不需走完整 Review 流程，Reviewer 快速确认：

**快速审查范围**：
- 仅审查 Developer 修复的代码变更
- 确认修复不引入新问题（运行回归测试）
- 确认新增了回归测试

**快速审查输出**：
- 在原 `review-report.md` 追加快速审查记录
- 或输出 `review-report-fast.md`（附加到模块目录）

**快速审查退出条件**：

| 退出条件 | 结果 | 后续动作 |
|----------|------|----------|
| 修复变更通过 + 回归测试通过 | ✅ 快速审查通过 | 通知 Tester 重新运行失败测试 |
| 修复变更有问题 / 回归测试失败 | ❌ 快速审查不通过 | 回退到完整 Review 流程（Developer 重新修复） |
| 快速审查连续 2 次不通过 | 🚫 升级为完整审查 | 模块标记为需关注，通知 team-lead |
| 修复变更超过 50 行 | ⚠️ 自动升级为完整审查 | 不适用快速通道，走正常 Review 流程 |

---

## 6. 版本管理规则

### 6.1 Git 分支策略

```
main                              # 稳定主分支（仅合并发布版本）
├── develop                       # 开发分支（集成测试通过后合并）
│   ├── feature/module-001-<name>  # 功能分支（每个模块一个分支）
│   │   ├── fix/module-001-<name>  # 修复分支（审查/测试不通过时）
│   │   └── ...
│   └── feature/module-002-<name>
└── release/v1.0.0                # 发布分支
```

### 6.2 分支创建时机

| 事件 | 分支操作 | 执行者 |
|------|----------|--------|
| Plan 阶段完成 | 无操作（Planner 不创建分支） | - |
| Develop 阶段开始 | `git checkout -b feature/module-XXX-<name>` | Developer |
| 审查不通过修复 | 在原 feature 分支继续提交（不新建分支） | Developer |
| 测试不通过修复 | 在原 feature 分支继续提交 | Developer |
| Test 阶段通过 | `git merge` 到 develop 分支 | Developer |
| 发布版本 | `git checkout -b release/vX.Y.Z` 从 develop 分出 | team-lead |

### 6.3 Git 提交时机和格式

**提交时机**：

| 事件 | 提交操作 | 说明 |
|------|----------|------|
| Develop 完成自测 | `git add . && git commit` | 首次提交，包含完整模块代码 |
| 审查不通过修复 | `git add . && git commit` | 修复提交，包含修复内容 |
| 测试不通过修复 | `git add . && git commit` | 修复提交，包含修复 + 回归测试 |
| Test 通过 | `git add . && git commit` | 测试代码提交 |
| Test 通过 | `git checkout develop && git merge feature/module-XXX-<name>` | 合并到 develop |

**提交信息格式**（提交信息规范见本文件 §6.3）：

```
[类型] module-XXX: 简短描述

详细描述（可选）

关联: #issue-number
```

**类型标签**：
- `[feat]` — 新功能（Develop 首次提交）
- `[fix]` — Bug 修复（审查/测试不通过的修复提交）
- `[test]` — 测试代码（Tester 提交测试用例）
- `[refactor]` — 重构
- `[docs]` — 文档（Planner 提交 plan.md / acceptance-criteria.md）
- `[chore]` — 构建/工具

**提交信息示例**：

```
[docs] module-001: 输出用户注册模块开发计划

- 拆分为 3 个子任务：Controller、Service、Repository
- 定义验收标准：核心路径 + 边界条件 + 异常场景
- 预估代码量：180 行

[feat] module-001: 实现用户注册接口

- UserController: 注册接口 POST /api/v1/users
- UserService: 注册业务逻辑 + 密码加密
- UserRepository: 用户数据访问
- 数据库迁移: V001__create_users.sql

[fix] module-001: 修复密码加密强度不足问题

- BCrypt 盐值轮数从 10 提升到 12
- 新增回归测试: test_password_encoding_strength

[test] module-001: 添加用户注册测试用例

- 单元测试: UserServiceTest (8 个用例)
- 集成测试: UserControllerTest (5 个用例)
- 异常兜底: 并发注册幂等性测试
- 覆盖率: 行 92% / 分支 85% / 方法 100%
```

### 6.4 版本号规则

遵循本文件 §6.4 的语义化版本号规则：

```
主版本号.次版本号.修订号 - 模块编号
例：1.2.0-module-003
```

| 数字 | 递增条件 |
|------|----------|
| 主版本号 | 不兼容的 API 变更、架构升级 |
| 次版本号 | 新增向下兼容的功能（新模块完成） |
| 修订号 | Bug 修复、向下兼容的改动 |

**版本号更新时机**：
- 模块测试通过合并到 develop 时：次版本号 +1（如 1.0.0 → 1.1.0）
- 发布到 release 时：由 team-lead 确定发布版本号

---

## 7. 共享记忆库读写时机

### 7.1 project-context.md 读写规则

**文件位置**：`memory/project-context.md`
**结构定义**：以 `memory/project-context.md` 模板为准（更新规则见 `docs/rules/memory-rules.md`）

### 7.2 读写时机矩阵（三记忆文件）

#### 7.2.1 project-context.md 读写时机

| 阶段 | 执行者 | 读 | 写 | 写入内容 |
|------|--------|----|----|----------|
| Plan | Planner | ✅ 读取项目状态 | ✅ | 添加待办事项、更新迭代状态、记录技术决策 |
| Develop（开始） | Developer | ✅ 读取已完成模块 | ✅ | 模块状态 → 🔧 开发中 |
| Develop（完成） | Developer | - | ✅ | 模块状态 → 👀 待审查 |
| Review（完成） | Reviewer | ✅ 读取 ADR 索引 | ✅ | 审查结论、新增 ADR 记录 |
| Test（开始） | Tester | ✅ 读取已完成模块（确定回归范围） | - | - |
| Test（通过） | Tester | - | ✅ | 模块状态 → ✅，移至已完成清单，更新版本号 |
| 回退触发 | 当前执行者 | ✅ 读取失败上下文 | ✅ | 模块状态 → blocked |
| 回退处理 | Planner | ✅ 读取失败原因 | ✅ | 更新计划、变更记录 |

#### 7.2.2 file-index.md 读写时机（粒度：每模块 1 行 + 每入口文件 1 行，非逐文件）

| 阶段 | 执行者 | 读 | 写 | 写入内容 |
|------|--------|----|----|----------|
| Plan（完成） | Planner | ✅ 读取已有索引 | ✅ | 追加 plan.md / acceptance-criteria.md 模块行 |
| Develop（完成） | Developer | - | ✅ | 追加 changelog.md + 新增源码/迁移文件索引行（每入口文件 1 行） |
| Review（完成） | Reviewer | ✅ 读取 | ✅ | 追加 review-report.md / ADR 条目索引 |
| Test（通过） | Tester | - | ✅ | 追加 test-report.md + 测试代码索引行 |
| 回退/升级 | 当前执行者 | - | ✅ | 追加 `[BLOCKED]` / `[ESCALATE]` 记录 |

#### 7.2.3 agent-activity-log.md 读写时机（粒度：每模块每阶段 1 行）

| 阶段 | 执行者 | 读 | 写 | 写入内容 |
|------|--------|----|----|----------|
| Plan（完成） | Planner | ✅ 读取 | ✅ | 追加 `[PLAN]` / `[HANDOFF]` 记录 |
| Develop（完成） | Developer | ✅ 读取 | ✅ | 追加 `[CODE]` / `[HANDOFF]` 记录 |
| Review（完成） | Reviewer | ✅ 读取 | ✅ | 追加 `[REVIEW]` / `[HANDOFF]` 记录 |
| Test（通过） | Tester | ✅ 读取 | ✅ | 追加 `[TEST]` / `[HANDOFF]` 记录 |
| 回退触发 | 当前执行者 | - | ✅ | 追加 `[BLOCKED]` 记录 |
| 升级申请 | 当前执行者 | - | ✅ | 追加 `[ESCALATE]` 记录（经 Planner 批准） |
| 定时介入 | 调度方（Planner） | ✅ 读取 | ✅ | 每次介入追加 `[UNBLOCKED]` 记录 |

### 7.3 读写约束

- **读优先**：每个阶段开始前必须先读 `project-context.md`，确保上下文最新
- **写及时**：阶段状态变更后立即写入，不等阶段结束再批量更新
- **不覆盖**：更新时只追加/修改自己的部分，不覆盖其他 Agent 的记录
- **原子性**：状态更新和通知消息发送应连续完成，避免中间状态不一致
- **交接前置校验**：本阶段退出条件 = 三文件均已按 `docs/rules/memory-rules.md` 强制项更新（project-context 状态 + file-index 索引 + agent-activity-log 阶段日志），缺一不可；未写齐不得进入下一阶段（与 §4.1-4.4 阶段退出条件一致）

### 7.4 记忆库字段与阶段对应

| project-context.md 字段 | 更新阶段 |
|--------------------------|----------|
| 当前迭代状态 | Plan（更新正在进行模块） |
| 待办事项 | Plan（添加新模块）、Test 通过（标记完成） |
| 已完成模块清单 | Test 通过（新增行） |
| ADR 索引 | Review（新增 ADR 时） |
| 关键技术决策记录 | Plan（技术选型）、Review（架构变更） |

---

## 8. 工作流完整执行时序

以下是一个模块从 Plan 到 Test 通过的完整时序：

```
时间    角色            动作                              输出物
────    ────            ────                              ──────
T1      Planner         接收用户需求
T2      Planner         读取 project-context.md
T3      Planner         需求澄清（与用户交互）
T4      Planner         模块拆分
T5      Planner         输出 plan.md                      specs/module-XXX-<name>/plan.md
T6      Planner         输出 acceptance-criteria.md       specs/module-XXX-<name>/acceptance-criteria.md
T7      Planner         更新 project-context.md           project-context.md（待办 +1）
T7a     Planner         更新 file-index + activity-log     file-index.md（模块行）、agent-activity-log.md（[PLAN]/[HANDOFF]）
T8      Planner         SendMessage → Developer
                        ─────── 阶段交接 ───────
T9      Developer       读取角色文档 + 记忆三件套          读 .claude/agents/developer.md + file-index + activity-log + project-context + CLAUDE.md
T10     Developer       输出实现计划
T11     Developer       创建 Git 分支                      git checkout -b feature/module-XXX-<name>
T12     Developer       编码实现
T13     Developer       本地编译 + 自测                    make build && make test
T14     Developer       输出 changelog.md                 specs/module-XXX-<name>/changelog.md
T15     Developer       更新 project-context.md           project-context.md（状态 → 🔧）
T15a    Developer       更新 activity-log + file-index     agent-activity-log.md（[CODE]/[HANDOFF]）、file-index.md（changelog + 新增源码索引）
T16     Developer       Git 提交                          git commit -m "[feat] module-XXX: ..."
T17     Developer       SendMessage → Reviewer
                        ─────── 阶段交接 ───────
T18     Reviewer        读取角色文档 + 审查输入            读 .claude/agents/reviewer.md + changelog.md + plan.md + acceptance-criteria.md
T19     Reviewer        阅读变更代码文件
T20     Reviewer        核对审查检查清单
T21     Reviewer        核对验收标准
T22     Reviewer        架构一致性检查
T23     Reviewer        安全评估
T24     Reviewer        输出 review-report.md             specs/module-XXX-<name>/review-report.md
T25     Reviewer        更新 project-context.md           project-context.md（审查结论）
T25a    Reviewer        更新 activity-log + file-index     agent-activity-log.md（[REVIEW]/[HANDOFF]）、file-index.md（review-report/ADR 索引）
T26     Reviewer        按需记录 ADR                       docs/adr/adr-XXX-<title>.md
T27     Reviewer        SendMessage → Tester
                        ─────── 阶段交接 ───────
T28     Tester          读取角色文档 + 测试输入            读 .claude/agents/tester.md + review-report.md + acceptance-criteria.md + changelog.md
T29     Tester          读取 project-context.md（回归范围）
T30     Tester          编写测试用例
T31     Tester          运行单元测试
T32     Tester          运行集成测试
T33     Tester          运行真实依赖冒烟                  （如模块含 DB/外部依赖交互，真实服务跑通核心链路）
T34     Tester          运行回归测试
T35     Tester          失败归因分类                       环境性失败 → 修环境重跑；真实回归 → §5.4 回退
T36     Tester          输出 test-report.md               specs/module-XXX-<name>/test-report.md
T37     Tester          签署 acceptance-criteria.md        specs/module-XXX-<name>/acceptance-criteria.md
T38     Tester          更新 project-context.md           project-context.md（状态 → ✅）
T38a    Tester          更新 activity-log + file-index     agent-activity-log.md（[TEST]/[HANDOFF]）、file-index.md（test-report + 测试代码索引）
T39     Tester          Git 提交测试代码                  git commit -m "[test] module-XXX: ..."
T40     Tester          合并到 develop                     git checkout develop && git merge feature/module-XXX-<name>
T41     Tester          SendMessage → Developer + team-lead
                        ─────── 模块完成，进入下一模块 ───────
```

> **硬性校验**：三项记忆文件是阶段交接的硬性校验，缺一项不得进入下一阶段（见 §4.1-4.4 阶段退出条件与 §7.3）。新 T 编号（T7a / T15a / T25a / T38a）为各阶段对应的活动日志 + 文件索引写入步骤。

---

## 9. 工作流配置

### 9.1 可配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_planner_retry` | 3 | Planner 计划制定/澄清失败最大重试次数（执行脚本 PLAN 阶段轮次上限） |
| `max_developer_retry` | 3 | Developer 编译/自测失败最大重试次数 |
| `max_reviewer_rounds` | 3 | Reviewer 审查不通过最大轮次 |
| `max_tester_retry` | 3 | Tester 测试不通过最大重试次数 |
| `max_reviewer_rounds_escalated` | 8 | Reviewer 升级放宽后的审查最大轮次（经 §5.5 升级申请批准后生效） |
| `max_tester_retry_escalated` | 8 | Tester 升级放宽后的测试最大重试次数（经 §5.5 升级申请批准后生效） |
| `module_code_limit` | 200 | 单模块新增代码行数上限 |
| `unit_test_coverage` | 80 | 单元测试覆盖率下限（%） |
| `integration_test_coverage` | 60 | 集成测试覆盖率下限（%） |
| `method_line_limit` | 50 | 单方法行数上限 |
| `class_line_limit` | 500 | 单类行数上限 |

> **参数存储**：以上参数的默认值定义在本节中。如需自定义，在项目根目录创建 `.claude/config.json` 覆盖默认值：
> ```json
> { "max_developer_retry": 5, "module_code_limit": 300 }
> ```
> Agent 启动时先读取默认值，再读取 `config.json`（如存在）覆盖。
>
> **升级放宽**：复杂 bug 可走 §5.5 升级申请放宽重试上限，默认上限（3）不是硬顶；批准后按 `max_*_escalated`（默认 8）执行。
> **口径说明**：`module_code_limit` 只统计**生产代码新增行**，排除 docstring/注释/测试代码；测试代码单独统计且默认豁免，不占模块行数上限。

### 9.2 执行脚本（模块循环驱动）

> 每个模块的驱动脚本由 `templates/module-loop-template.js` 实例化生成。**脚本只做驱动不做业务判断，阶段内容以 §4 为准。**

- **实例化命令**：`node templates/module-loop-template.js <模块编号> <模块名称>`（传参模块编号/名称），生成 `module-XXX-loop.js` 后执行。
- **阶段驱动方式**：按 Plan → Develop → Review → Test 顺序依次驱动；每阶段完成后由 §5.0 定时检查循环确认 Agent 已返回、文档已产出，再进入下一阶段。
- **失败退出码**：任一阶段超时 / 重试耗尽 / 记忆文件校验不通过时，脚本以非 0 退出码终止（如 `1`=超时、`2`=重试耗尽、`3`=三记忆文件缺项），供调度方据此介入。
- **介入钩子**：监控间隔可用环境变量覆盖（如 `LOOP_MONITOR_INTERVAL=300` 秒，即 5 分钟），接入 §5.0 定时检查。
- **硬性校验**：每个阶段退出前校验三记忆文件（project-context / agent-activity-log / file-index）是否已写入，缺一项退出码非 0。

### 9.3 模板文件索引

| 模板 | 路径 | 使用者 |
|------|------|--------|
| 开发计划模板（简略版） | `templates/spec-template.md`（简略版结构） | Planner（简单模块 ≤ 100 行） |
| 开发计划模板（详细版） | `templates/spec-template.md` | Planner（复杂模块 > 100 行） |
| 验收标准模板 | `templates/acceptance-criteria.md` | Planner |
| 实现计划模板 | `templates/implementation-plan-template.md` | Developer（编码前产出） |
| 变更日志模板 | `templates/changelog-template.md` | Developer（编码后产出） |
| 审查检查清单 | `templates/review-checklist.md` | Reviewer |
| 测试报告模板 | `templates/test-report-template.md` | Tester |
| ADR 模板 | `templates/adr-template.md` | Planner / Developer / Reviewer / Tester |

> 注：模板以 `templates/` 目录为唯一权威来源（原 CLAUDE.md §11/§12 模板字段已并入对应模板文件）。

---

## 10. 工作流终止条件

### 10.1 正常终止

- 所有模块测试通过
- `project-context.md` 中待办事项为空
- 用户确认项目完成

### 10.2 异常终止

- 模块连续阻塞，Planner 重新拆解后仍无法通过
- 用户主动终止项目
- `tech-stack.md` 无法确定，项目无法启动

**异常终止流程**：
1. 当前执行者 SendMessage 通知 team-lead（含阻塞摘要）
2. team-lead 决策是否终止
3. 如终止：标记 `project-context.md` 为已终止，记录原因

---

## 11. 快速参考

### 11.1 Agent 间消息路由表

| 发送方 | 接收方 | 触发条件 | 消息内容 |
|--------|--------|----------|----------|
| Planner | Developer | plan.md 就绪 | 模块编号 + 路径 + 优先级 |
| Developer | Reviewer | 代码自测通过 | 模块编号 + changelog 路径 + 变更摘要 |
| Reviewer | Tester | 审查通过 | 模块编号 + review-report 路径 + 关注项 |
| Reviewer | Developer | 审查不通过 | 模块编号 + 问题数 + review-report 路径 |
| Tester | Developer | 测试不通过 | 模块编号 + 失败数 + test-report 路径 |
| Tester | Developer + team-lead | 测试通过 | 模块编号 + 通过率 + 覆盖率 |
| Developer | Planner | 方案不可行 | 问题描述 + 阻塞原因 |
| 任意 | Planner | 重试耗尽 | 模块编号 + 失败摘要 + 请求重新拆解 |
| 任意 | team-lead | 阶段完成 | 模块编号 + 阶段 + 结论摘要 |

### 11.2 文件产出索引

每个模块完成后，`specs/module-XXX-<name>/` 目录应包含：

```
specs/module-XXX-<name>/
├── plan.md                    # Planner 输出
├── acceptance-criteria.md     # Planner 输出（Tester 签署验收结论）
├── changelog.md               # Developer 输出
├── review-report.md           # Reviewer 输出
└── test-report.md             # Tester 输出
```

全局文件：

```
project-root/
├── memory/
│   └── project-context.md      # 全体读写（共享记忆库）
├── docs/adr/                  # Planner / Reviewer 输出（架构决策记录）
│   └── adr-XXX-<title>.md
└── docs/test-reports/         # Tester 输出（测试报告归档）
```
