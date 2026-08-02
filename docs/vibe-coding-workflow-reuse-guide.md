# Vibe Coding 闭环工作流 · 复用指南

> **一句话结论**：`vibe-coding-workflow` 技能文件只是**模板源头**（规范 / 角色定义 / 模板），**不是执行器**。真正驱动闭环的是"主会话内化规范 + 用 Workflow JS 脚本确定性编排 4 个角色"。复用 = 在新项目落地副本目录 + 让主会话自动获得该模式，**无需继承本 session**。

---

## 1. 模式速览（30 秒版）

| 环节 | 执行者 | 产出物 |
|------|--------|--------|
| Plan | Planner（主会话兼任） | `specs/module-XXX/plan.md` + `acceptance-criteria.md` |
| Develop | Developer（Workflow spawn） | 源代码 + `changelog.md` |
| Review | Reviewer（Workflow spawn） | `review-report.md`（不通过 → 回退 Developer，轮次上限可调） |
| Test | Tester（Workflow spawn） | `test-report.md` + 测试代码（不通过 → 回退 Developer） |
| 终审 | Final Reviewer（完工后） | `REVIEW-FINAL.md` |

**闭环核心**：每模块 Plan → Develop → Review → Test 四阶段闭环；重试用 `for` 循环确定性控制；主会话按 §5.0 每 2-5 分钟监控 Agent，超时介入。

**角色文档位置**：`<home>\.claude\skills\vibe-coding-workflow\.claude\agents\{planner,developer,reviewer,tester}.md`

---

## 2. 复用的三层

### 第 1 层：同项目复用（零操作）

在项目根目录**打开任意新 Claude Code session** → `CLAUDE.md` 自动加载 → 模式自动生效，不需要延续本 session。直接下指令即可（见 §3），**不要调技能**。

### 第 2 层：新项目落地

可复用资产 = 全局技能目录（跨项目全局挂载，任何 session 都能读到）：

```
<home>\.claude\skills\vibe-coding-workflow\
├── CLAUDE.md                 # 完整规范（15 章）
├── .claude\agents\*.md       # 4 个角色定义
├── .claude\workflows\vibe-coding-loop.md  # 编排文档（含 §5.0 监控、回退路径）
├── templates\                # 8 个文档模板
└── memory\                   # 记忆库模板
```

**落地命令**（新项目根目录执行）：

```powershell
$src = "$env:USERPROFILE\.claude\skills\vibe-coding-workflow"
Copy-Item "$src\CLAUDE.md" .
Copy-Item "$src\templates" .\templates -Recurse
Copy-Item "$src\memory" .\memory -Recurse
Copy-Item "$src\.claude" .\.claude -Recurse
New-Item specs -ItemType Directory
```

**收尾清单**（SKILL.md Startup Checklist）：
1. 填写 `tech-stack.md`（模板见 `templates/tech-stack-template.md`）
2. 初始化 `memory/project-context.md`（项目名 + 技术栈）
3. 初始化 `memory/agent-activity-log.md`、`memory/file-index.md`
4. `git init`：main + develop 分支
5. 让 Planner 产出第一个 `module-001` 的 plan

**或更省事**：在新项目直接对主会话说 **"用 vibe-coding-workflow 模式初始化这个项目"**——技能是全局挂载的，主会话会自动执行上述清单。

### 第 3 层：行为复用（不需要"继承 session"）

本 session 特有的行为其实全部**跟着规范走、不跟 session 走**：

| 行为 | 来源 |
|---|---|
| 主会话作为 Planner 侦察 → 写 plan → 写 Workflow JS（确定性控制流） | 规范 §9 + 编排文档 |
| 每 2-5 分钟监控 Agent transcript、超时介入 | 编排文档 §5.0 |
| 每模块完成一次 git 提交 + 推送 | 规范 §8 |
| 经验沉淀（模型坑/环境坑/决策）进 `memory/` | 规范 §10 |

只要项目落地了副本 + 新 session 打开，这些行为自动具备。

---

## 3. 触发词（不要调技能）

| 你想做什么 | 正确说法 |
|---|---|
| 继续推进 | "继续下一个模块" |
| 新需求 | "规划 module-XXX：<需求>" |
| 具体优化 | "做 XX 优化 / 重构 / 排查 bug" |
| 初始化新项目 | "用 vibe-coding-workflow 模式初始化这个项目" |

> 为什么不要调技能：`SKILL.md` 明确它只负责**初始化 / 加入已有项目**，完整规范在项目 `CLAUDE.md`，编排在 `.claude/workflows/vibe-coding-loop.md`。调技能 = 读说明书；执行 = 主会话内化后写 Workflow JS。已落地项目里，直接下指令最精准。

---

## 4. 重试上限可申请调整

默认参数（编排文档 §9.1）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `max_developer_retry` | 3 | Developer 自修复重试次数 |
| `max_reviewer_rounds` | 3 | Review 不通过最大轮次 |
| `max_tester_retry` | 3 | Test 不通过最大重试次数 |
| `module_code_limit` | 200 | 单模块代码行数上限 |
| `unit_test_coverage` | 80 | 单元测试覆盖率下限（%） |
| `integration_test_coverage` | 60 | 集成测试覆盖率下限（%） |

**调整方式（二选一）**：
1. **单模块**：在 `plan.md` 中声明理由，放宽该模块上限
2. **全局**：项目根 `.claude/config.json` 覆盖默认值：
   ```json
   { "max_reviewer_rounds": 8, "module_code_limit": 300 }
   ```

> 案例：module-028 曾以 8 轮充分迭代，说明上限可按需放宽——在 plan 里写明理由即可，**"3 次"不是硬约束**。

---

## 5. 记忆库维护（本项目踩过的真实教训）

**规范 vs 现状**：
- 规范（CLAUDE.md §10）：所有 Agent 在阶段交接时读写 `memory/project-context.md`
- 实际情况（2026-08-02 诊断）：三个记忆文件全部停更在早期

| 文件 | 停更状态 |
|---|---|
| `memory/file-index.md` | 只到 module-001 / 2026-07-29 |
| `memory/project-context.md` | 只到 module-016 / 2026-07-30 |
| `memory/agent-activity-log.md` | 只有 2026-07-29 一条 |

**根因**：规范存在但**执行断裂**——Agent 没在阶段边界更新记忆库。
**修复方向**：把"记忆库更新"写进各 Agent 的退出条件与验收标准，强制检查；file-index 由 Planner 定期重扫补全。

---

## 6. 常见坑（对照 SKILL.md Common Mistakes）

- **Planner 写代码**：Planner 只产出 plan + acceptance-criteria，不碰源码
- **Reviewer 只读 git diff**：必须读完整文件内容
- **跳过模板**：plan / changelog / review / test 文档必须用 `templates/` 模板，禁止自造格式
- **并行开发模块**：一次只跑一个模块，不并发
- **忽略共享记忆库**：阶段开始必读、结束必写 `project-context.md`

---

## 7. 附录：本项目落地现状（作为范本）

- `CLAUDE.md`：项目规范（已按本仓库技术栈定制）
- `.claude/agents/`：4 角色定义
- `memory/`：project-context / agent-activity-log / file-index
- `specs/module-001~019/`：每模块 plan + acceptance-criteria + changelog + review-report + test-report
- `templates/`：8 个模板
- `tech-stack.md`：技术栈配置

> 注意：本项目 `memory/` 已停更（见 §5），作为范本时请**以规范为准，不要照抄停更状态**。
