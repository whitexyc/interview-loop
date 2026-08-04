# Agent 活动日志索引

> 日志文件按 Agent 角色 + 日期存储于 `memory/logs/<role>/YYYY-MM-DD.md`
> 维护规则：Agent 完成有意义动作后，在对应角色当日日志追加记录。

## 日志文件索引

| 日期 | 角色 | 文件路径 | 主要活动摘要 |
|------|------|----------|-------------|
| 2026-07-29 | Planner | [planner/2026-07-29.md](logs/planner/2026-07-29.md) | 项目初始化、技术栈配置、模块规划 |

## 阶段汇总（2026-07-29 ~ 2026-08-02，模块 001-030）

> 各模块详细产出见 `specs/module-0XX-*/`（plan/acceptance/changelog/review-report/test-report）。

### 基础期（module-001 ~ 017，07-29 ~ 07-31）
- 项目脚手架、简历数据/API/前端、AI 层基础、RAG 核心、Chat UI、知识库面板、会话持久化、RAG UI、RAGAS、HyDE、Redis 缓存、Graph RAG、父子分块。

### 优化期（module-018 ~ 030，08-01 ~ 08-02）
| 日期 | 模块 | 角色 | 摘要 |
|------|------|------|------|
| 08-01 | module-018 | 全角色 | Rerank 修复（Qwen3-Reranker）→ 评审/测试通过 |
| 08-01 | module-019 | 全角色 | 评估闭环（golden 集 + Hit@k/MRR + 版本化） |
| 08-01 | module-020 | 全角色 | 中文 FTS（jieba）+ 本地嵌入（bge-m3 GGUF） |
| 08-01 | module-021 | 全角色 | 图分数归一化 |
| 08-01 | module-022 | 全角色 | 检索缓存修复（key 参数化 + 失效） |
| 08-01 | module-023 | 全角色 | 长期记忆（测试发现 date 类型 bug → 修复） |
| 08-01 | module-024 | 全角色 | 检索延迟优化（预算 + HyDE 缓存） |
| 08-01 | module-025 | 全角色 | 流式记忆接入 |
| 08-01 | module-026 | 全角色 | 检索并发修复 + Reflector 低温度 |
| 08-02 | module-027 | 全角色 | 嵌入并发修复 + backlog 收敛 |
| 08-02 | module-028 | 全角色 | Agent 工具化（ToolRegistry + ReAct，8 轮充分迭代） |
| 08-02 | module-029 | 全角色 | 前端增强（工具轨迹 + 降级链动态调序） |
| 08-02 | module-030 | 全角色 | 重排优化（bge）+ LangGraph 实验端点 |

### 2026-08-04（module-030 修复 + module-031 知识库重建）
| 模块 | 角色 | 摘要 |
|------|------|------|
| module-030 修复 | Developer | 实机诊断：库里 45 篇全为旧版"整篇 1 父+1 子"大块（平均 2.1 万字符）→ rerank 200-641s + 同步阻塞事件循环冻结服务；reranker 截断 500 字符 + to_thread 修复；降级链恢复 deepseek 优先（提交 78fc9a0） |
| module-031 | Planner | 分块规则讨论 → 用户拍板 Option C（## + ### + 父块 4000 上限 + 子块 300）；plan.md / acceptance-criteria.md |
| module-031 | Developer | chunker Option C 实现 + tests 8/8；reindex_knowledge_base.py（幂等/--dry-run/--no-graph/--skip-import）；全量重建 58 文件 → 1136 父 / 6370 子，父块 >4000 = 0 |
| module-031 | Reviewer | 审查发现 cleanup_orphans `r.t` bug（SQLAlchemy 2.0.19 Row 具名属性陷阱）→ 修复 + --skip-import 恢复模式；review-report.md |
| module-031 | Tester | 单测 8/8 + graph_store 12/12；全量回归 **195 passed / 0 failed**（含 async 债务修复）；库内统计达标；图谱 1423 实体；E2E G1/Redis 检索质量恢复；test-report.md |

### 2026-08-02 收尾
- Planner（主会话）：记忆库同步（file-index/activity-log 补齐）、backlog 记录（重排分数校准、记忆库维护）
