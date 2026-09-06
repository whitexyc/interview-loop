# 常见环境问题排查（environment-troubleshooting）

> 本节是 CLAUDE.md §14 环境预检与 §15 附录的落地载体：沉淀实战环境坑为速查表，主规范只保留入口指针。
> **症状共性**：以下问题都伪装成"代码/API 故障"，单靠 Agent 归因易误判方向——排查时应**先验证环境，再怀疑代码**。

## 问题速查表（症状 → 根因 → 修复 → 预防）

| # | 症状 | 根因 | 修复 | 预防 |
|---|------|------|------|------|
| ① | **全部子代理返回 400** | `CLAUDE_CODE_SUBAGENT_MODEL` 指向错误/不可用模型 | 在 `.claude/settings.json` 的 `env` 块覆盖为可用模型；启动 1 个最小子代理冒烟验证，应正常返回而非 400 | §14 启动清单强制预检；每个模块启动前按 §2.0 复核 |
| ② | **auto 模式命令被拦**（`cannot determine safety`） | 权限分类器（LLM）临时不可用 | 配置静态 `allow` 白名单兜底：`PowerShell(git*,python*,pip*,uv*)` + `Write(*.md,*.py)`；重试该 Agent | settings.json 基线 `allow` 白名单预检；介入后 `[UNBLOCKED]` 记录 |
| ③ | **async 测试用例未收集/静默跳过** | 缺 `pytest-asyncio` 等插件，测试收集阶段被跳过 | 补依赖后重跑；把 collection warning / 被跳过用例视为**失败**，禁止记为通过 | 平台工具链预检确认插件就绪；Tester §2.2 收集完整性规则 |
| ④ | **Windows 原生依赖编译失败** | pip sdist 深路径（如 llama-cpp）、uv 缺编译器、长路径限制 | 用预编译 wheel 或换 pip/uv；开启 `LongPathsEnabled` | 仅技术栈含原生依赖且宿主为 Windows 时适用；tech-stack 记录已知坑 |
| ⑤ | **单测全绿但真实环境失败** | mock 掩盖真实缺陷（DB/外部依赖未真实交互） | 强制真实 DB 冒烟：启动真实服务跑通核心链路（读+写），禁用 mock/内存库 | Tester 强制前置：acceptance-criteria §4.5 冒烟验收项 |

## 处置流程

1. **先归因，再修复**：测试失败先按 tester.md §2「环境性失败归因」分类——环境性失败修环境/补齐 mock 后重跑（不消耗业务重试、不阻塞），真实回归才通知 Developer。
2. **被动介入兜底**：Agent 卡住/超时由工作流 §5.0 定时检查（调度方每 2-5 分钟）介入处置，每次介入在 `agent-activity-log.md` 追加 `[UNBLOCKED]`。
3. **复用现成技能，不重复造轮子**：
   - `update-config` 技能 → 配置 `settings.json` 的 `env` 块（模型覆盖）与权限 `allow` 白名单
   - `fewer-permission-prompts` 技能 → 扫描 transcript 生成项目级权限 allowlist，减少拦截
   - `systematic-debugging` 技能 → 环境问题之外的根因排查

> **生效方式**：本节为新增指引，主规范只做入口指针——CLAUDE.md §14 预检、§15 附录索引、SKILL.md Quick Reference。
