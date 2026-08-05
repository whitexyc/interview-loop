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

### 2026-08-05（module-032 JWT 登录体系）| 模块 | 角色 | 摘要 |
|------|------|------|
| module-032 | Planner | 记忆架构讨论（三层：长期/短期/会话，参考 llm-push/19-Agent记忆管理.md）→ 用户定 3 模块方案（032 JWT登录 / 033 长期记忆 / 034 短期+会话）；plan.md + acceptance-criteria.md（跨栈契约：JWT HS256 + 共享 secret + 匿名降级 IP）；三记忆文件更新 |
| module-032 | Developer(backend) | Workflow 并行派发：users 表 V032 + UserEntity/Repository + JwtUtil(HS256) + AuthService(BCrypt) + AuthController(register/login/me) + AuthInterceptor + application.yml/pom；mvn 37/0（新 17）；changelog-backend.md |
| module-032 | Developer(frontend) | LoginPage + AuthContext(localStorage) + api/client.ts(统一附 Bearer) + AppLayout 登录入口 + 3 service 复用；vitest 17 新过 + build ✓；changelog-frontend.md |
| module-032 | Developer(python) | src/identity.py(parse_jwt/resolve_identity) + 中间件注入 user_id + memory source→memory:\<identity\>: + engine 身份化；pytest 215/0（新 20）；changelog-python.md |
| module-032 | Reviewer | 三栈全量审查：跨栈契约专项核对（HS256 payload / APP_JWT_SECRET=PW_JWT_SECRET 按值对齐 / CommonResult.msg vs message / memory:\<identity\>: / 匿名降级 IP）；安全审查（BCrypt、secret 不进仓库、LIKE 注入双保险、日志无敏感）；独立复现 mvn 37/0 ✓ + vitest 17 ✓ + pytest identity/memory 49 ✓ + frontend build ✓；结论：⚠️ 有条件通过（契约/安全无阻塞；建议项见 review-report.md）|
| module-032 | Tester | 三栈回归全过（mvn 37/0、pytest 215/0、vitest 31+3 基线）+ 真实 E2E：**发现核心跨栈缺陷**——Java `signWith(key)` 对 64 字节 secret 自动签 HS512，Python 仅验 HS256 → token 被拒、记忆不按 user_id 隔离（B 召回 A 记忆）。结论 ❌ 不通过，验收 32/40 |
| module-032 | Developer(team-lead 修复) | 修复 JwtUtil 显式 `signWith(key, Jwts.SIG.HS256)` + 64 字节密钥回归测试（shouldSignHS256WithLongSecret）；mvn 38/0。重跑真实 E2E：token alg=HS256、A 记忆 memory:3:、B 召回 0（隔离成功）、匿名降级零回归 → **复验通过 40/40**。E2E 测试数据已清理 |

### 2026-08-05（module-033 长期记忆自动写入）| 模块 | 角色 | 摘要 |
|------|------|------|
| module-033 | Planner | 长期记忆自动写入方案（对话结束异步 LLM 提取 + 语义去重>0.95 + 动态K召回 + 格式化注入 + fire-and-forget）；plan.md + acceptance-criteria.md（38 项）；三记忆文件更新 |
| module-033 | Developer | [CODE] 实现：memory_extractor.py（extract_facts LLM 提取 + importance>=0.6 过滤 + 失败/超时降级[]）+ memory.py（save dedup=True 语义去重 cosine>0.95→更新旧父块追加合并、条数不涨 / recall 动态K 0.85/0.75/宁缺毋滥 / format_memory_line '[长期记忆 - 日期]：内容' / _expand_to_parents 增 created_at）+ engine.py（_persist_memory fire-and-forget + _schedule_persist + chat knowledge 路径异步触发 + _recall_memory 新格式）+ main.py（chat_stream accumulate token 后 schedule_stream_persist，casual/realtime 跳过）+ config.py（阈值可配置）；changelog.md；技能：test-driven-development / systematic-debugging（test_empty_answer_skips_extract 失败归因 → 补 _persist_memory 空答案守卫）；pytest 254/0（215 基线 + 新 39） |
| module-033 | Reviewer | [REVIEW] 全量审查：契约核对（source 格式 / save-recall 签名兼容 / 匿名降级 / fire-and-forget 不阻塞 / 提取只对 knowledge 路径）；安全（去重只查本身份 LIKE 转义+校验双保险 / 提取失败降级不影响对话 / 嵌入 L2 归一化验证点积=cosine）；独立复现 test_memory_extractor 39/0 + 全量 pytest 254/0 + identity 20/0 + py_compile OK；验收 38 项中 32 项经代码/单测核验 ✅、2 项 E2E 留 Tester、4 项文档 ✅。结论：⚠️ 有条件通过（无阻塞；6 项非阻塞建议：①动态K阈值作用于 min-max 相对分而非绝对相似度（retriever._normalize 跨查询不可比），真实语义与 19-Agent记忆管理 参考设计有偏差 ②去重合并后不重建子块向量，新事实检索可能 miss ③chat 路径 _recall_memory top_k=3 使 K=5 档不可达 ④新生产代码约 438 行略超 plan 400 预算 ⑤agent 端点未接自动写入 ⑥worktree 既有 application.yml 硬编码 JWT 默认值提示）；review-report.md 已产出；技能：understand-diff / verification-before-completion / requesting-code-review |
| module-033 | team-lead | [FIX] 安全阻塞：application.yml `jwt.secret` 硬编码默认密钥（${APP_JWT_SECRET:64位hex}）→ 移除默认值恢复 ${APP_JWT_SECRET} fail-fast（Reviewer 阻塞 #1：env 缺失时回退公开密钥可伪造 token）。注：Reviewer 审查时打印 .env PW_JWT_SECRET 到 transcript（凭证泄露警告），建议用户轮换该值 |

### 2026-08-06（module-033 收尾 + module-034 规划）
| 模块 | 角色 | 摘要 |
|------|------|------|
| module-033 | Tester | [TEST] **验收通过（40/40，4 项附条件非阻塞）**。① 全量回归 **254 passed / 0 failed**（215 基线 + 39 新增，3 个既有 Redis setex 弃用 warning 与模块无关）；② 新增单测 **39/39**（test_memory_extractor.py：提取/importance 过滤/失败降级/JSON 结构/去重（>0.95 更新、不同新增、失败降级）/动态K 三档+空候选/格式化注入/触发链路 chat+chat_stream）；③ 身份回归 20/20、memory+identity+stream 54/54、py_compile 5 文件 OK；④ **半真实 E2E**（真实 PG + 真实本地 bge-m3 + 真实 DeepSeek HTTP 200）：`_persist_memory` 自动写入链路真实跑通（extract_facts 返回事实 → save 落库 → recall 召回 → 格式化注入）、匿名 client_ip 两身份（9.9.9.9/8.8.8.8）隔离 PASS（含自动写入路径）、去重机制（identical content cosine 1.0→updated）✅；⑤ **Reviewer 关注项复核**：#1 动态K 真实 min-max 相对分 avg 恒<0.75 → 恒 K=1（K=5/3 档实际不可达，确认语义偏差）、#2 去重合并无脏数据/崩溃（子块向量不重建是已知取舍）、#3 chat 路径 top_k=3 截断 K=5 档（无逻辑错误）；⑥ **去重阈值校准观察**：真实 bge-m3 同义改写 cosine≈0.88<0.95 不触发去重（完全一致 1.0 触发），LLM 提取措辞不稳定 → 「二次同义对话→不膨胀」在措辞变化时不成立；机制正确属阈值校准问题，建议 module-034 下调阈值（约 0.85）或改绝对相似度口径；⑦ 时区观察：created_at 为 PG UTC（08-05）vs 标题本地日期（08-06），同天差 8 小时（环境既有非模块缺陷）；⑧ 验收项核对发现原统计 38 实际复选框 40（17/5/6/8/4），按实际 40 签署并修正统计表。test-report.md 已产出；技能：verification-before-completion / systematic-debugging（观察归因） / test-driven-development |
| module-034 | Planner | 短期记忆+会话记忆方案（source 三层分层 long/short/session + 短期 TTL 7天 + 会话摘要异步生成 + 会话持久化复用 documents + IP_SESSION_MESSAGES 升级）；plan.md + acceptance-criteria.md（34 项）；三记忆文件更新 |
| module-034 | Developer | [CODE] 实现：memory.py（三层 source 分层 `_memory_source`/`_layer_pattern`，长期检索由 `memory:<id>:%` 改**精确匹配**防跨层误命中（零回归）+ `save_short`/`recall_short`（动态K + TTL 7天过滤）+ `format_memory_line` label 参数）+ session_memory.py（`save_session_messages` content_hash 幂等 + 每 identity 上限滚动 / `get_session_messages` 隔离恢复）+ engine.py（`_recall_memory` 长/短合并注入"最近上下文"段 / `_persist_memory` 同批 facts 沉淀长+短 / `_resolve_session_history` 优先持久化会话 / `_schedule_session_persist`）+ main.py（chat/chat_stream 会话持久化接入 + Step 5 会话恢复 + IP_SESSION_MESSAGES 降级兜底缓存）+ config.py（memory_short_ttl_days / session max+history limit）；changelog.md；技能：test-driven-development / systematic-debugging（fake session 按语句类型路由修正）；pytest **278/0**（254 基线 + 新 24） |
| module-034 | Reviewer | [REVIEW] **结论：❌ 不通过（1 项阻塞）**。全量审查：① 契约核对全过（三层 source 精确匹配互不混淆 / save-recall 签名兼容 / chat-stream 端点签名不变 / 匿名降级不变 / fire-and-forget 不阻塞 / 会话复用 documents 不泄漏进检索）；② 安全全过（LIKE 注入双保险保留、TTL fail-open 合理、日志无敏感）；③ 独立复现与 Developer 一致：新单测 53/0 + 全量 **278/0** + 身份 20/0 + py_compile OK；④ **阻塞项**：`/ai/rag/chat` 每轮 knowledge 请求会话持久化**双重调度**（engine.chat L254/L268 + main.py L333），mock 计数实证 schedule_session_persist=2；两 fire-and-forget 任务独立 session（连接池 pool_size=5 并发）check-then-insert 均读旧态，`content_hash` 无唯一约束 → 每轮会话消息确定性重复落库（4 行/轮）、恢复历史每轮重复、50 上限减半；修复：删除 main.py L333 冗余调度（或删 engine.chat 两处，二选一，只留一个调度点）；⑤ 9 项非阻塞建议（短期去重合并不刷新 created_at、content_hash 仅 content 不含 role、TTL 惰性物理不清理、_save/save_session_messages 超 50 行、持久化会话可能丢弃更新鲜 request.history、3s 会话恢复延迟、UTC/本地时区差、retriever docstring 过期、agent 端点未接会话/短期记忆）；⑥ 验收按实际复选框 36 项核对：32 项代码/单测核验通过 + 3 项真实 E2E 留 Tester + 1 项代码长度附条件。report：`specs/module-034-short-session-memory/review-report.md`；技能：verification-before-completion / requesting-code-review（原则应用，完整阅读全部变更文件 + 独立复现 + 阻塞实证，未显式调用 Skill 工具） |
| module-034 | team-lead | [FIX] Reviewer 阻塞 #1（双重调度）修复：`main.py` L333 删除重复的 `rag_engine._schedule_session_persist(...)`，只保留 `engine.chat` 内部（no-docs L254 / docs L268）自包含调度。全量回归 **278 passed / 0 failed** 通过（无回归）。已通知 Tester 真实 E2E 复验每轮会话不再重复落库（预期 2 行/轮而非 4 行） |
| module-034 | Reviewer | [REVIEW]（⚠️ **前次结论已被下一行升级取代**——阻塞项：/ai/rag/chat 双重调度会话持久化→确定性重复落库，见下行）全量审查：契约核对（三层 source 精确匹配 / 长期 `:%`→精确等值零回归 / save-recall 签名兼容 / 匿名降级 / 会话持久化 fire-and-forget 不阻塞 / 长短期注入段区分）；安全（三层按本身份隔离：长/短 `_layer_pattern` 精确 LIKE + 双保险转义，会话等值查询 / TTL 惰性过滤 fail-open / 日志无敏感）；架构（session_memory 复用 documents 无新表、依赖方向无循环、会话文档无向量不参与 FTS/向量/图检索）；独立复现 py_compile OK + test_session_memory 11/0 + test_memory 42/0（+13 short）+ test_identity 20/0 + extractor/stream 44/0 + 全量 **278/0**（与 Developer 自测一致）；验收 34 项中 31 项代码/单测核验 ✅、3 项真实 E2E 留 Tester（另发现 acceptance 汇总表接口类记 3 实际 4 项，按实际核对）。结论：⚠️ **有条件通过**（无阻塞；应修建议 #1 `/ai/rag/chat` 双重 `_schedule_session_persist`——engine.chat L254/268 + main.py L333 对同一轮两次调度，content_hash 幂等存在 TOCTOU 竞态可致会话重复轮次，建议 Tester E2E 前删一处；非阻塞 #2 短期行物理不清理 + 0.95 去重阈值近似重复累积 #3 持久化会话偏好可能丢更新鲜 request.history #4 save_session_messages 63 行超 50 #5 会话恢复 +3s 延迟 #6 TTL 时区差）。review-report.md 已产出；技能：understand-anything:understand-diff / verification-before-completion / requesting-code-review |
| module-034 | Tester | [TEST] **验收通过（36/36）**。① 全量回归 **278 passed / 0 failed**（254 基线 + 24 新增，3 个既有 Redis setex 弃用 warning 与模块无关）；② 新增单测 **24/24**（test_session_memory.py 11：保存 source/幂等 hash 去重/上限滚动/隔离恢复/失败返回空 + test_memory.py short 13：三层 source 精确匹配/短期去重 layer 隔离/TTL 过滤）；③ 身份回归 20/20、memory+extractor 81、stream 5、py_compile 5 文件 OK；④ **真实 E2E**（Tester 启动 Java 8081 + AI 8001 + 真实 PG/Redis/bge-m3/DeepSeek，结束已停）：注册/登录（user 10/11）、带 token knowledge 对话 → 日志 `extract_facts → save 长期 + save 短期`（memory:10:short: 落库）、recall_short 真实召回 1 条、匿名双 IP（203.0.113.71/72）隔离 PASS（ip1 session+short 落库、ip2 无）、`_resolve_session_history` 持久化优先 + 空/失败回退 request.history 单元级核验、长短期双段注入（历史记忆+最近上下文）核验；⑤ **Reviewer 阻塞 #1（双重调度）复现 + 修复复验**：首跑 AI 服务为修复前代码 → 真实复现 4 行/轮重复落库（duplicated_contents c=2）；team-lead 已修复 main.py（删除 L333 冗余调度）→ Tester 用**修复后代码重跑** → **2 行/轮、duplicated_contents=[]**（PASS）；⑥ 摘要失败降级真实验证（uid=11 extract_facts facts=0 不落库）；⑦ 测试数据已清理（user 10/11、ip 71/72/90 全部删除，残留校验 0）。test-report.md + acceptance-criteria.md（36/36 签署）已产出；技能：verification-before-completion / systematic-debugging（双重调度复现归因） / test-driven-development |
| module-033 | Tester(补跑) | [TEST] **真实 HTTP 端点 E2E 复验通过**（首轮服务未启动，补跑启动双服务：Java 8081 `APP_JWT_SECRET` 与 ai_service/.env `PW_JWT_SECRET` 同值注入未打印 + AI 8001 uvicorn 真实 PG/Redis/bge-m3/DeepSeek）。① 注册/登录 HS256 通过（user_id=8，token header 解码 alg=HS256）；② 带 token 保存记忆落库 source=`memory:8:`；③ 完全一致内容二次保存 **status=updated**（id 不变、parents 数不涨=3）→ >0.95 去重机制真实验证；同义改写 cosine≈0.88<0.95 按设计新增（阈值校准观察）；④ 登录 knowledge 对话（query 含偏好）→ 日志 `extract_facts facts=1 → save → 长期记忆自动写入完成 identity=8`，落库 memory:8:（自动提取链路真实 HTTP 跑通）；⑤ 闲聊/实时不提取（日志确认不触发 _persist_memory）；⑥ 无 token chat XFF=7.7.7.7 → 自动落库 memory:7.7.7.7:（匿名 client_ip 隔离真实验证），user 8 记忆不受影响；匿名 recall 仅返回本身份记忆、user 8 带 token recall 仅返回 user 8 记忆（无跨身份泄漏）；⑦ recall 返回 created_at + `[长期记忆 - 日期]：内容` 格式化注入；⑧ 测试数据已清理（memory:8:/memory:7.7.7.7: 共 12 行删除，残留校验 parents=0）。test-report.md §6.6 增补真实 E2E；技能：verification-before-completion / systematic-debugging（阈值观察归因） |
| module-033 | Tester | [TEST] **验收通过（40/40，4 项附条件非阻塞）**。① 全量回归 **254 passed / 0 failed**（215 基线 + 39 新增，3 个既有 Redis setex 弃用 warning 与模块无关）；② 新增单测 **39/39**（test_memory_extractor.py：提取/importance 过滤/失败降级/JSON 结构/去重（>0.95 更新、不同新增、失败降级）/动态K 三档+空候选/格式化注入/触发链路 chat+chat_stream）；③ 身份回归 20/20、memory+identity+stream 54/54、py_compile 5 文件 OK；④ **半真实 E2E**（真实 PG + 真实本地 bge-m3 + 真实 DeepSeek HTTP 200）：`_persist_memory` 自动写入链路真实跑通（extract_facts 返回事实 → save 落库 → recall 召回 → 格式化注入）、匿名 client_ip 两身份（9.9.9.9/8.8.8.8）隔离 PASS（含自动写入路径）、去重机制（identical content cosine 1.0→updated）✅；⑤ **Reviewer 关注项复核**：#1 动态K 真实 min-max 相对分 avg 恒<0.75 → 恒 K=1（K=5/3 档实际不可达，确认语义偏差）、#2 去重合并无脏数据/崩溃（子块向量不重建是已知取舍）、#3 chat 路径 top_k=3 截断 K=5 档（无逻辑错误）；⑥ **去重阈值校准观察**：真实 bge-m3 同义改写 cosine≈0.88<0.95 不触发去重（完全一致 1.0 触发），LLM 提取措辞不稳定 → 「二次同义对话→不膨胀」在措辞变化时不成立；机制正确属阈值校准问题，建议 module-034 下调阈值（约 0.85）或改绝对相似度口径；⑦ 时区观察：created_at 为 PG UTC（08-05）vs 标题本地日期（08-06），同天差 8 小时（环境既有非模块缺陷）；⑧ 验收项核对发现原统计 38 实际复选框 40（17/5/6/8/4），按实际 40 签署并修正统计表。test-report.md 已产出；技能：verification-before-completion / systematic-debugging（观察归因） / test-driven-development |
| module-032 | Tester | **真实 E2E 验收发现核心缺陷：不通过**。① 三栈回归全过：mvn 37/0、pytest 215/0、vitest 31 pass + 3 既有 ChatPage 基线失败（git log 确认 ChatPage.test.tsx 未被 module-032 触碰）；② 真实双服务 E2E（Java:8080 APP_JWT_SECRET 与 PW_JWT_SECRET 同值 + AI:8000 hermes venv uvicorn + 真实 PG）：注册/登录/me/重复用户名/匿名降级全过；③ **缺陷**：Java JwtUtil 对 64 字节 secret 经 jjwt 0.12.6 自动签 **HS512**（token header 解码实证），Python parse_jwt 仅接受 HS256 → pyjwt `InvalidAlgorithmError` 拒绝 → 带 token 保存记忆 source=memory:127.0.0.1:（应为 memory:1:）、B 登录召回 A 的记忆（跨用户隔离失败）；④ 根因：单测密钥 40 字节恰好 HS256 掩盖问题，生产 64 字节才触发；Reviewer 复现仅跑单测未做真实握手；⑤ 修复方向：Java 显式 `signWith(key, Jwts.SIG.HS256)` 或对齐 Python；⑥ 验收 40 项：32 通过 / 8 失败（1.3 两项 + 1.4 一项 + 2.1 算法契约 + 4.3 两项 E2E + 5.3 文档同步 2 项留收尾）；test-report.md 已产出。**环境坑**：PowerShell `Get-Content` 注入 ETS 属性致登录 500（脚本问题非模块缺陷）|

### 2026-08-02 收尾
- Planner（主会话）：记忆库同步（file-index/activity-log 补齐）、backlog 记录（重排分数校准、记忆库维护）
