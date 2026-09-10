# CLAUDE.md — Vibe Coding Workflow · 本项目适配版

> 常驻规范（Claude Code 自动加载）。只放铁律与指针，细节不在此重复。
> 渐进披露（L0/L1/L2，入场顺序见 skill 的 `SKILL.md`）：**无触发不读**，全量加载会导致上下文腐化。
>
> **本文件是 skill 模板（`~/.skills-manager/skills/vibe-coding-workflow/CLAUDE.md`）的项目适配版。**
> 原版 §2 引用的 `docs/rules/`、`docs/reference/`、`templates/`、`contexts/`、`docs/adr/`
> 在本项目**均不存在**，故按需索引只保留本项目真实存在的路径——**不照搬悬空引用**。
> 铁律条数与 skill 的 `SKILL.md` 规则表保持同步（14 条）。

## 0. 铁律（违反 = 阶段不通过，无需提醒）

| # | 铁律 | 验证方式 | 违反后果 |
|---|------|----------|----------|
| 1 | 编码前先产出 plan.md + acceptance-criteria.md；Planner 绝不写代码（**轻量模式豁免**：小改可直接执行，须留 changelog + 记忆行） | 查文件 | 阶段不通过 |
| 2 | 一次一个 module-XXX；新增生产代码 ≤200 AST | `ast` 复算 | 阶段不通过 |
| 3 | 方法 ≤50 行、类 ≤500 行；超限拆分或 plan.md 说明 | 静态分析 | Review 驳回 |
| 4 | public/导出方法必须有 Docstring；魔法数字命名常量 | pylint / 人工核 | Review 驳回 |
| 5 | 严禁空 catch / 吞异常；业务异常统一封装 | 正则扫描 | Review 驳回 |
| 6 | 严禁跨层/反向/循环依赖；Entity 不暴露到 Controller（DTO） | import 检查 | Review 驳回 |
| 7 | API 统一 `{code, msg, data, timestamp, request_id}` | 接口测试 | Test 驳回 |
| 8 | INFO 日志（入参摘要 + 耗时）；异常含 request_id；禁打敏感信息 | 日志扫描 | Review 驳回 |
| 9 | 禁 SQL 拼接（参数化）；禁硬编码密钥/明文密码 | semgrep / gitleaks | Review 驳回 |
| 10 | 架构变更走 ADR：发现者写 → Planner 审批 → 更新索引（本项目 ADR 在 `specs/adr/`） | 核对 | 不算完成 |
| 11 | 入场先读记忆三件套，阶段退出前必写 | 记忆核对 | 阶段不通过 |
| 12 | 交接前自跑 lint + 测试**并贴输出**；交付文档用固定模板 | 内容校验 | 不算完成 |
| 13 | 脚本类工具纯内置模块 + 头部用途注释（用法/退出码/环境变量） | 代码检查 | 不算完成 |
| 14 | 闸门/审计类脚本须配套可机械断言的夹具用例 | 夹具矩阵 | 不算完成 |

## 1. 角色与环路（指针）

| 角色 | 一句话职责 | 定义文件 |
|------|-----------|----------|
| Planner | 需求拆解 → plan.md + acceptance-criteria.md；维护 project-context 待办 | `.claude/agents/planner.md` |
| Developer | 按 plan 实现 → 代码 + changelog.md；自修 ≤3 轮 | `.claude/agents/developer.md` |
| Reviewer | **读全文件**审查（非仅 diff）→ review-report.md，每条附 `文件:行号` | `.claude/agents/reviewer.md` |
| Tester | 全量回归 + 新测试 → test-report.md | `.claude/agents/tester.md` |

- 调度模型：编排者（主会话）派发四个角色为子 agent，**每个角色的产出文件即阶段完成信号**（plan.md / changelog.md / review-report.md / test-report.md）
- 闭环流程、超时、回退 → `.claude/workflows/vibe-coding-loop.md`
- 派发提示词模板 → `.claude/workflows/agent-prompts-template.md`
- 复杂模块可派多个同类角色实例，须在 plan.md 声明

## 2. 按需索引（无触发不读）

| 触发场景 | 文件 |
|----------|------|
| 记忆读写规则 / 热区约束 | `memory/project-context.md` §顶部说明 + `.claude/agents/*.md` §记忆纪律 |
| 追溯历史阶段结论 | `memory/agent-activity-log.md` |
| 定位文件 / 模块产物 | `memory/file-index.md` |
| 已有违纪记录（避坑） | `memory/violations.md` |
| 已沉淀的直觉/经验 | `memory/instincts.md` |
| 架构决策依据 | `specs/adr/`（本项目 ADR 目录，非 `docs/adr/`） |
| 具体模块的 plan/AC/报告 | `specs/module-XXX-<name>/` |
| LLM 供应商接入事实（端点/鉴权/配额） | `specs/llm-providers.md` |
| 评测设计与口径（grader/pass@k/分阶段遥测） | `specs/module-066*`、`specs/module-092-parity-telemetry/` |
| 提交 / 分支 / 版本规范 | `.claude/workflows/vibe-coding-loop.md` §6 |
| 环境报错 / 权限拦截 / Windows 怪癖 | skill 的 `environment-troubleshooting.md`（`~/.skills-manager/skills/vibe-coding-workflow/`） |
| 术语/概念对照（面试口径） | `CONTEXT.md` |
| 角色阶段模式上下文 | `.claude/agents/<role>.md` 内嵌（本项目未拆 `contexts/`） |

> ⚠️ 本项目的 `docs/` 目录**不属于工作流规范**（内容是面试材料与项目资料），且 `docs/` 已被 `.gitignore` 忽略、不入库。

## 3. 共享记忆（强制读 / 写）

- `memory/project-context.md` — 项目状态（待办/进行中/已完成/ADR 索引）**热区，有尺寸约束**
- `memory/file-index.md` — 文件索引（每模块 1 行 + 入口文件）
- `memory/agent-activity-log.md` — 活动日志（每模块每阶段 1 行，单行 ≤200 字符）
- `memory/violations.md` — 违纪与勘误记录
- `memory/instincts.md` — 沉淀的经验直觉

**入场先读，阶段退出前必写**；交接消息须列出更新的文件，否则下一阶段无法开始。

## 4. 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Spring Boot 3.2 + MyBatis-Plus + Java 17 |
| AI 层 | FastAPI + LangChain + 自研 ReAct/LangGraph 双环路 + pgvector |
| 前端 | React 18 + TypeScript + Vite + Ant Design |
| 数据 | PostgreSQL（pgvector / Apache AGE）+ Redis |
| 向量/重排 | bge-m3（本地 GGUF）+ bge-reranker（本地离线） |
| LLM 供应商 | OpenCode Go（glm-5.3-flash，当前跑批） / ModelScope 系 / 降级链见 `.env` |
| 部署 | Docker Compose |

**栈变更须更新本表 + 补 ADR。**

## 5. 本项目特有约定（适配增量，原版模板未含）

### 5.1 模块红线（每模块 plan 必须显式声明）
历史惯例：**`ai_service/agent/`、`ai_service/src/`、`ai_service/main.py` 零 diff**。
例外的 provider 接入类改动须在 plan/AC/changelog **三处显式申报**性质（纯增量 / 是否改变默认行为）。

### 5.2 文档与编码禁忌（已踩过的坑）
- **写中文文件一律用 Edit/Write 工具或 Python（`encoding='utf-8'`）——禁止 bash heredoc**（会双重编码乱码，2026-09-07 与 09-10 各踩一次）
- **查多字节内容用 Read/Python，别用 `cut -c`**（按字节截断造成"乱码"假象，曾误报一次）
- **长任务输出不要接管道**（`| tail`）—— 会缓冲到进程结束，看起来像卡死；改用重定向到文件
- Git Bash 的 `/tmp` 映射到 `D:\tmp`；临时脚本写项目内路径

### 5.3 基线与口径
- **全量回归基线每日刷新**，以最近一次实测为准（2026-09-10 为 **1825 passed / 0 failed / 3 skipped**）；写文档引用基线前先复跑确认，**不要沿用旧值**
- Python 解释器：`ai_service/.venv/Scripts/python.exe`（**不要用系统 python**，缺依赖）
- 跑批类供应商凭据走 **shell 环境变量**，不改 `.env`（091 验收先例）

### 5.4 评测模块额外约定
- 评测代码只读生产代码，**拦截全在 eval 层**（`mock.patch` 包装且原行为先执行/透传）
- 评测数据清理用**时间窗口径**（`AND created_at >= '<评测日>'`）——不带时间窗会误删历史评测数据
- 大体积评测产物不入 git（如 `eval_io_traces/`）

### 5.5 不立 module 的事项
基础设施类改动（如 LLM 供应商接入）**不占 module 编号**，登记到累积台账 `specs/llm-providers.md`（用户 2026-09-10 明确要求）。

### 5.6 诚实性硬约束
- 严禁虚假信息：写入 README/简历前必须交叉验证真实代码/DB/git
- 实测数据以脚本 + 落库 + 配置快照 + commit 为证据链，拒绝无证明估算
- **对自研/自己结论不利的事实照实写**；失败不掩盖、不重跑挑数据
