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

### 2026-08-02 收尾
- Planner（主会话）：记忆库同步（file-index/activity-log 补齐）、backlog 记录（重排分数校准、记忆库维护）
