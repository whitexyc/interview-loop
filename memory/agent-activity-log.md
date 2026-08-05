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

### 2026-08-05（module-032 JWT 登录体系）
| 模块 | 角色 | 摘要 |
|------|------|------|
| module-032 | Planner | 记忆架构讨论（三层：长期/短期/会话，参考 llm-push/19-Agent记忆管理.md）→ 用户定 3 模块方案（032 JWT登录 / 033 长期记忆 / 034 短期+会话）；plan.md + acceptance-criteria.md（跨栈契约：JWT HS256 + 共享 secret + 匿名降级 IP）；三记忆文件更新 |
| module-032 | Developer(backend) | Workflow 并行派发：users 表 V032 + UserEntity/Repository + JwtUtil(HS256) + AuthService(BCrypt) + AuthController(register/login/me) + AuthInterceptor + application.yml/pom；mvn 37/0（新 17）；changelog-backend.md |
| module-032 | Developer(frontend) | LoginPage + AuthContext(localStorage) + api/client.ts(统一附 Bearer) + AppLayout 登录入口 + 3 service 复用；vitest 17 新过 + build ✓；changelog-frontend.md |
| module-032 | Developer(python) | src/identity.py(parse_jwt/resolve_identity) + 中间件注入 user_id + memory source→memory:\<identity\>: + engine 身份化；pytest 215/0（新 20）；changelog-python.md |
| module-032 | Reviewer | 三栈全量审查：跨栈契约专项核对（HS256 payload / APP_JWT_SECRET=PW_JWT_SECRET 按值对齐 / CommonResult.msg vs message / memory:\<identity\>: / 匿名降级 IP）；安全审查（BCrypt、secret 不进仓库、LIKE 注入双保险、日志无敏感）；独立复现 mvn 37/0 ✓ + vitest 17 ✓ + pytest identity/memory 49 ✓ + frontend build ✓；结论：⚠️ 有条件通过（契约/安全无阻塞；建议项见 review-report.md）|
| module-032 | Tester | 三栈回归全过（mvn 37/0、pytest 215/0、vitest 31+3 基线）+ 真实 E2E：**发现核心跨栈缺陷**——Java `signWith(key)` 对 64 字节 secret 自动签 HS512，Python 仅验 HS256 → token 被拒、记忆不按 user_id 隔离（B 召回 A 记忆）。结论 ❌ 不通过，验收 32/40 |
| module-032 | Developer(team-lead 修复) | 修复 JwtUtil 显式 `signWith(key, Jwts.SIG.HS256)` + 64 字节密钥回归测试（shouldSignHS256WithLongSecret）；mvn 38/0。重跑真实 E2E：token alg=HS256、A 记忆 memory:3:、B 召回 0（隔离成功）、匿名降级零回归 → **复验通过 40/40**。E2E 测试数据已清理 |
| module-032 | Tester | **真实 E2E 验收发现核心缺陷：不通过**。① 三栈回归全过：mvn 37/0、pytest 215/0、vitest 31 pass + 3 既有 ChatPage 基线失败（git log 确认 ChatPage.test.tsx 未被 module-032 触碰）；② 真实双服务 E2E（Java:8080 APP_JWT_SECRET 与 PW_JWT_SECRET 同值 + AI:8000 hermes venv uvicorn + 真实 PG）：注册/登录/me/重复用户名/匿名降级全过；③ **缺陷**：Java JwtUtil 对 64 字节 secret 经 jjwt 0.12.6 自动签 **HS512**（token header 解码实证），Python parse_jwt 仅接受 HS256 → pyjwt `InvalidAlgorithmError` 拒绝 → 带 token 保存记忆 source=memory:127.0.0.1:（应为 memory:1:）、B 登录召回 A 的记忆（跨用户隔离失败）；④ 根因：单测密钥 40 字节恰好 HS256 掩盖问题，生产 64 字节才触发；Reviewer 复现仅跑单测未做真实握手；⑤ 修复方向：Java 显式 `signWith(key, Jwts.SIG.HS256)` 或对齐 Python；⑥ 验收 40 项：32 通过 / 8 失败（1.3 两项 + 1.4 一项 + 2.1 算法契约 + 4.3 两项 E2E + 5.3 文档同步 2 项留收尾）；test-report.md 已产出。**环境坑**：PowerShell `Get-Content` 注入 ETS 属性致登录 500（脚本问题非模块缺陷）|

### 2026-08-02 收尾
- Planner（主会话）：记忆库同步（file-index/activity-log 补齐）、backlog 记录（重排分数校准、记忆库维护）
