# 代码审查报告 — Module-033: 长期记忆自动写入

> 本文件由 **Reviewer** 输出，作为模块进入测试阶段的质量门禁结论。
> 依据 `review-checklist.md` 逐项核验；阻塞问题不通过，非阻塞问题记录为技术债务。

## 审查元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-033 |
| 审查日期 | 2026-08-06 |
| 审查人 | m33-reviewer |
| 提交人 | m33-dev（Developer） |
| 审查轮次 | 第 1 轮 |
| 关联 plan.md | `specs/module-033-long-term-memory/plan.md` |
| 关联 acceptance-criteria.md | `specs/module-033-long-term-memory/acceptance-criteria.md` |
| 审查分支 | worktree-m8-knowledge-panel |

---

## 一、审查范围

完整阅读变更文件（非仅 diff）：

| 文件 | 变更类型 | 结论 |
|------|----------|------|
| `ai_service/rag/memory_extractor.py` | 新增（148 行） | ✅ 已读，契约符合 plan §3.2 功能1 |
| `ai_service/rag/memory.py` | 修改（+191/-10） | ✅ 已读，去重/动态K/格式化符合 plan §3.2 功能2/3 |
| `ai_service/rag/engine.py` | 修改（+63/-3） | ✅ 已读，fire-and-forget 接入符合 plan §3.2 功能4 |
| `ai_service/main.py` | 修改（+29） | ✅ 已读，chat_stream 触发符合 plan §3.2 功能4 |
| `ai_service/src/config.py` | 修改（+7） | ✅ 已读，阈值配置符合 plan §3.2 |
| `ai_service/tests/test_memory_extractor.py` | 新增（540 行，39 用例） | ✅ 已读，覆盖验收 §1.1-1.5 |
| `ai_service/tests/test_memory.py` | 修改（+10） | ✅ 已读，recall 断言补 created_at 契约字段 |
| `ai_service/tests/test_stream_memory.py` | 修改（+4） | ✅ 已读，mock 后台 _persist_memory |

---

## 二、独立复现记录（Reviewer 亲跑）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 新增单测 | `python -m pytest tests/test_memory_extractor.py -q` | ✅ **39 passed** |
| 记忆/身份/流式回归 | `python -m pytest tests/test_memory.py tests/test_identity.py tests/test_stream_memory.py -q` | ✅ **54 passed** |
| 全量回归 | `python -m pytest tests/ -q` | ✅ **254 passed / 0 failed**（215 基线 + 39 新增，与 changelog 一致；3 个既有 Redis setex 弃用 warning，与 module-033 无关） |
| 身份回归 | `python -m pytest tests/test_identity.py -q` | ✅ **20 passed**（含在 54 组中） |
| 编译检查 | `python -m py_compile src/config.py rag/memory.py rag/memory_extractor.py rag/engine.py main.py` | ✅ **OK** |

> 说明：Reviewer 第二轮独立复现（2026-08-06，Python 3.11.15 / pytest 9.1.1），结果与 Developer 报告及首轮审查完全一致。首次 collect 显示 255，随后复跑为 254（当时 Developer 仍在写入测试文件，属瞬态）；最终收集数=通过数=254，完全自洽。

---

## 三、契约核对

| 契约项 | 要求（plan §3.5 / acceptance §2） | 实现 | 结论 |
|--------|----------------------------------|------|------|
| source 格式 | `memory:<identity>:`（user_id 优先，否则 client_ip） | save 构造 `f"memory:{identity}:"`；recall 用 `memory:<identity>:%` LIKE | ✅ |
| save 签名 | 兼容，新增可选参数 | `save(content, identity, dedup=True)`，现有调用方（main.py memory_save）不变 | ✅ |
| recall 签名 | 兼容 | `recall(query, identity, top_k=5)` 签名不变，仅结果新增 created_at 字段（additive） | ✅ |
| 匿名降级 | 无 token → client_ip 隔离，零回归 | resolve_identity → user_id 优先否则 client_ip（取不到 unknown）；_normalize_identity 兜底 | ✅ |
| fire-and-forget | 不阻塞响应 | engine._schedule_persist / main.schedule_stream_persist 均 asyncio.create_task 不 await | ✅ |
| 提取只对 knowledge 路径 | 闲聊/实时不提取 | engine.chat 中 casual_chat/realtime 分支提前 return；schedule_stream_persist 显式 guard `intent=="knowledge"` | ✅ |
| 去重只查本身份记忆 | LIKE 注入防护保留 | `_find_duplicate` 用 `_escape_like(_normalize_identity(identity))` 构造 `memory:<id>:%`；`_normalize_identity` 拒绝 `%`/`_`/`\` + `_escape_like` 转义双保险 | ✅ |
| 提取失败降级不影响对话 | 失败返回 [] | extract_facts 全量 try/except（超时 10s 兜底）→ []；_persist_memory 再包一层 | ✅ |

**嵌入归一化验证**：embeddings.py `_normalize`（L109-115）对 bge-m3 输出做 L2 归一化，故 `_find_duplicate` 的 `sum(a*b)` 点积即 cosine 相似度，0.95 阈值语义成立。✅

---

## 四、安全检查

| 项 | 结论 |
|----|------|
| 去重检索身份隔离 | ✅ source LIKE 带 `_escape_like` 转义 + `_normalize_identity` 校验，identity="%" 无法构造 `memory:%:%` 跨身份匹配 |
| 检索范围限定子块+向量 | ✅ `parent_id.isnot(None)` + `embedding.isnot(None)`，只比对本身份已向量化子块 |
| 提取/写入异常 | ✅ 全部降级捕获，不抛回响应 |
| 日志敏感信息 | ✅ 提取日志只记 query[:40] 前缀，不记 answer 全文；记忆内容不入日志 |
| 依赖审计 | ✅ 无新增第三方依赖（复用 LLMFactory / embedding_service） |

---

## 五、架构检查

| 项 | 结论 |
|----|------|
| 分层 | ✅ Controller(main) → Service(engine) → memory_service/extract_facts → retriever/embedding；无跨层/反向调用 |
| 依赖方向 | ✅ 单向；engine 依赖 memory、extract_facts；memory 不依赖 engine |
| 模块拆分 | ✅ memory_extractor.py 独立（148 行）；memory.py/engine.py 增量修改内聚 |
| 配置 | ✅ src/config.py 集中 5 项阈值（importance 0.6 / dedup 0.95 / 动态K 0.85/0.75 / max 5），env_prefix PW_ |

---

## 六、验收标准逐项核对

### 1. 功能验收（16 项）

| 验收项 | 实现 | 验证用例 | 结论 |
|--------|------|----------|------|
| 1.1 对话→提取事实 | extract_facts LLM 结构化 JSON | test_extracts_and_filters_facts | ✅ |
| 1.1 importance 过滤 | <0.6 或空 content 丢弃 | test_importance_at_threshold_kept / test_empty_content_dropped / test_non_numeric_importance_dropped | ✅ |
| 1.1 提取失败降级 | 异常/超时返回 [] | test_llm_failure_returns_empty / test_llm_timeout_returns_empty / test_empty_answer_no_llm_call | ✅ |
| 1.1 输出 JSON 结构 | {"facts":[{"content","importance"}]} | _parse_json 多级回退（含 markdown fence） | ✅ |
| 1.2 相似>0.95 视为重复 | _find_duplicate 点积>0.95 → _merge_duplicate 更新旧父块 | test_high_cosine_returns_duplicate / test_duplicate_merges_into_parent_no_new_rows | ✅ |
| 1.2 不同事实正常新增 | 未命中重复 → 正常新增 | test_low_cosine_returns_none / test_no_duplicate_normal_new_insert | ✅ |
| 1.2 去重失败降级 | 检索/嵌入异常 → 正常新增 | test_embedding_failure_returns_none / test_db_failure_returns_none / test_dedup_failure_degrades_to_new_insert | ✅ |
| 1.3 均值>0.85→K=5 | _dynamic_k 返回 memory_max_recall=5 | test_high_quality_recalls_five / test_dynamic_k_thresholds | ✅ |
| 1.3 0.75-0.85→K=3 | 边界含 0.75/0.85 | test_mid_quality_recalls_three | ✅ |
| 1.3 <0.75→K=1 | 宁缺毋滥 | test_low_quality_recalls_one | ✅ |
| 1.3 空候选 | recall 直接返回 [] | test_empty_candidates_returns_empty | ✅ |
| 1.4 "[长期记忆 - 日期]：内容" | format_memory_line + engine._recall_memory | test_format_line_with_date / test_recall_memory_formats_with_date | ✅ |
| 1.4 无日期省略 | created_at None → "[长期记忆]" | test_format_line_without_date | ✅ |
| 1.5 chat 结束异步提取 | engine.chat knowledge 路径 _schedule_persist | test_knowledge_triggers_background_persist | ✅ |
| 1.5 闲聊不提取 | casual_chat 提前 return | test_casual_chat_skips_persist | ✅ |
| 1.5 实时不提取 | realtime 提前 return + guard | test_realtime_skips_persist / test_realtime_skips_persist(stream) | ✅ |

### 2. 接口验收（5 项）

| 验收项 | 结论 |
|--------|------|
| save/recall 签名兼容 | ✅（dedup 可选参数，默认 True） |
| 手动 POST /ai/memory/save 行为不变（+去重） | ✅（端点未改；save 默认去重） |
| chat/stream 端点签名不变 | ✅ |
| source `memory:<identity>:` 不变 | ✅ |
| 阈值可配置 | ✅（config.py 5 项） |

### 3. 代码质量验收（5 项）

| 验收项 | 结论 |
|--------|------|
| public 方法 Docstring | ✅（save/recall/extract_facts/_find_duplicate/_merge_duplicate/format_memory_line/_dynamic_k 均有） |
| Python snake_case | ✅ |
| 单方法 ≤ 50 行 | ⚠️ save() 约 73 行、_find_duplicate 约 55 行（含 docstring/注释；save 主体为 module-023 既有，本模块增量约 10 行） |
| 模块生产代码 ≤ 400 行（plan 声明调整） | ⚠️ 新增生产代码约 438 行（extractor 148 + memory.py +191 + engine +63 + main +29 + config +7），略超 plan 400 行预算（约 10%），多为 docstring/日志 |
| py_compile + 无未使用 import | ✅（亲跑通过；各文件 import 均被使用） |

### 4. 测试验收（8 项）

| 验收项 | 结论 |
|--------|------|
| test_memory_extractor.py 提取/过滤/降级/JSON | ✅ 39 用例 |
| memory 去重（>0.95 更新/不同新增/失败降级） | ✅ |
| 动态 K 三档 + 空候选 | ✅ |
| 格式化注入 | ✅ |
| 全量 215 基线 + 新增 / 0 失败 | ✅ **254 passed / 0 failed** |
| 身份回归 | ✅ 20 passed |
| E2E 登录→提取→去重不膨胀 | ⏳ Tester 执行 |
| 匿名 client_ip 隔离 | ⏳ Tester 执行 |

### 5. 文档验收（4 项）

| 验收项 | 结论 |
|--------|------|
| changelog.md 已更新 | ✅（v1，含版本/日期/变更/变更人 + 5 条设计决策 + 验证命令） |
| 方案记录在 plan.md §3 | ✅（Planner 已写） |
| project-context.md 更新 | ✅（module-033 行 + 迭代状态） |
| agent-activity-log.md 更新（PLAN/CODE/REVIEW/TEST） | ✅（PLAN/CODE 已由 Planner/Developer 写；本报告追加 REVIEW） |

---

## 七、发现的问题

### 阻塞问题（🔴）

| 序号 | 严重程度 | 问题描述 | 所在文件 | 行号 | 修复建议 |
|------|----------|----------|----------|------|----------|
| 1 | 🔴 提交前必须处理（非 module-033 逻辑缺陷） | application.yml 硬编码 JWT secret 默认值（详见下方非阻塞表 #6） | `backend/src/main/resources/application.yml` | L25 | 提交前恢复 `${APP_JWT_SECRET}` fail-fast；module-033 产品代码本身无阻塞项 |

### 非阻塞问题 / 建议（🟡）

| 序号 | 严重程度 | 问题描述 | 所在文件 | 行号 | 修复建议 |
|------|----------|----------|----------|------|----------|
| 1 | 🟡 建议 | **动态 K 阈值作用于 min-max 相对分数，而非绝对相似度**。hybrid_score 是检索候选集内 min-max 归一化（retriever._normalize 自身注释明确"跨查询分数不可比"），每次查询 top-1 恒≈1.0，avg 反映的是候选分数**散布**而非绝对相关性。参考方案 19-Agent记忆管理 的 0.85/0.75 阈值本意是绝对相似度。典型后果：5 条普遍弱相关但分数接近的记忆 → avg 偏高 → K=3/5（应 K=1，宁缺毋滥失效）；单条强相关记忆 → 恒 K=1（上限 5 仅当有多条）。单测 mock 原始 hybrid_score 通过，但真实语义与文档设计有偏差 | `ai_service/rag/memory.py` recall L394-399 / `ai_service/rag/retriever.py` _normalize L509-534 | L397 | 二选一：(a) 用候选原始 vector cosine（绝对相似度）替代 min-max hybrid_score 计算 avg；(b) 在 plan/changelog 明示动态 K 基于相对分数，并重标阈值。建议 Tester 在真实 E2E 中观察实际召回条数 |
| 2 | 🟡 建议 | **去重合并后不重建子块向量**。_merge_duplicate 仅把新内容追加到父块 content，不新增/更新子块 embedding。合并后的事实只有在既有子块被检索命中时才随父块内容返回；针对新事实的后续检索可能 miss。去重条数不涨（验收达成），但检索质量有损 | `ai_service/rag/memory.py` _merge_duplicate L267-295 | L289 | 合并后可将合并内容重嵌入为一个新子块（parent_id 指向原父块），或至少在 docstring/plan 记录该取舍 |
| 3 | 🟡 建议 | **chat 路径 _recall_memory 用 top_k=3，动态 K 的 K=5 档在 chat 生成路径不可达**。engine._recall_memory 默认 top_k=3 透传给 recall，故聊天气泡最多注入 3 条记忆（K=5 仅 /ai/memory/recall API 用默认 top_k=5 时可达）。不影响验收（recall 直接测 K=5），但 plan 场景4 的"高质量召回 5 条"在 chat 实际不生效 | `ai_service/rag/engine.py` _recall_memory L282/L305 | L282 | 若意图是 chat 也吃 K=5，把 _recall_memory 默认 top_k 提到 5 |
| 4 | 🟡 建议 | 新增生产代码约 438 行，略超 plan 声明调整的 400 行预算（约 10%）。多为 docstring/防御日志，功能性增量可控 | `ai_service/rag/*` | — | 后续模块注意预算；本次可接受 |
| 5 | 🟡 观察 | `/ai/rag/chat/agent` 与 `/ai/rag/chat/agent-lg` 端点未接入自动记忆写入。plan 仅要求 chat/chat_stream，符合范围；但 ReAct 对话不沉淀记忆，若后续要做可复用 _persist_memory | `ai_service/main.py` chat_agent L482-538 | — | 记录为 backlog，非本次缺陷 |
| 6 | 🔴 提交前必须处理（非 module-033 逻辑缺陷） | **`backend/src/main/resources/application.yml` 把 JWT secret 改为 `${APP_JWT_SECRET:<64位hex硬编码>}`（带默认值回退）**。此为工作树既有改动（非 module-033 Python 侧 diff 范围，changelog 未声明），但硬编码默认密钥一旦在 env 缺失时生效即成为公开签名密钥 → 可伪造任意 user 的 token，直接击穿 module-032 的认证与记忆隔离，且违背 module-032「缺失时 fail-fast 启动失败」设计（见 project-context.md 关键技术决策）。Reviewer 第二轮已独立确认该行存在于当前工作树 | `backend/src/main/resources/application.yml` | L25 | **提交前移除默认值，恢复 `${APP_JWT_SECRET}` fail-fast**；本地开发缺 secret 时走 `.env`/`application-local.yml`，不入仓库 |
| 7 | 🟡 观察 | 工作树含 2 个未跟踪操作文件 `.claude/config.json`（max_*_retry=60）与 `module-033-loop.js`（vibe-coding 循环驱动脚本），非 module-033 产品代码。若随模块提交需确认有意为之，否则应加 .gitignore | `module-033-loop.js` / `.claude/config.json` | — | team-lead 提交时确认这两个文件是否纳入版本控制 |

### 非阻塞技术债务汇总

| 债务 | 建议版本 |
|------|----------|
| 动态 K 阈值语义（min-max 相对分 vs 绝对相似度）与参考设计偏差 | 随 Tester E2E 观察后再定 |
| 去重合并不重建子块向量，新事实检索质量有损 | 后续记忆模块（module-034） |
| chat 路径动态 K 上限被 top_k=3 截断 | 后续记忆模块 |

### 需记录的 ADR

- [ ] 否。动态 K 阈值语义偏差属实现口径问题，不构成架构决策变更；如采纳"绝对相似度"口径可补记录。

---

## 八、审查结论

- [ ] ✅ **通过** — 所有检查项通过
- [x] ⚠️ **有条件通过** — module-033 产品代码无阻塞缺陷；存在 1 项提交前必办（🔴 application.yml 硬编码 JWT secret，见问题 #6）+ 6 项建议/观察（重点：#1 动态 K 阈值语义），记录技术债务，可进入测试阶段（提交前须先处理 #6）
- [ ] ❌ 不通过

**结论说明**：契约、安全、架构、回归全部达标；新增 39 单测 + 全量 254/0 亲跑通过；验收 38 项中 32 项经代码/单测核验通过、2 项（E2E）留给 Tester、4 项文档类核验通过。module-033 产品代码无阻塞缺陷。**唯一须在提交前处理项**：工作树内 `backend/src/main/resources/application.yml` 硬编码 JWT secret 默认值（🔴，非 module-033 逻辑，属模块提交前的密钥卫生问题，详见问题 #6），team-lead 提交前须移除该默认值恢复 fail-fast。动态 K 的 min-max 相对分数语义与参考设计（绝对相似度阈值）存在偏差，建议 Tester 在真实 E2E 中重点观察实际召回条数分布。

### 审查人签名

- 审查人：m33-reviewer
- 日期：2026-08-06
- 结论：⚠️ 有条件通过
