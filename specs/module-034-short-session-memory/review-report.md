# 代码审查报告 — Module-034: 短期记忆 + 会话记忆

> 本文件由 **Reviewer（m34-reviewer）** 在代码审查阶段输出，供 Developer 修复、Tester 验收参考。
> 本轮为 Round 1 综合结论：**❌ 不通过（1 项阻塞问题）**。
> 说明：Round 1 早前版本曾以「⚠️ 有条件通过」签署并将会话持久化双重调度列为"应修建议"；
> 本轮 Reviewer 独立复现 + 连接池/唯一约束分析确认该问题为**确定性重复落库**（非低概率竞态），
> 升级为阻塞项，结论改为不通过。其余契约/安全/架构核对全部通过，修复预期为一行级改动。

> **✅ 阻塞修复（team-lead，2026-08-06）**：Reviewer 阻塞 #1（双重调度）已修复——
> `ai_service/main.py` L333 删除重复的 `rag_engine._schedule_session_persist(...)` 调用，
> 只保留 `engine.chat` 内部（no-docs L254 / docs L268 两 return 点）的自包含调度。
> 全量回归 **278 passed / 0 failed** 通过（无回归）。待 Tester 真实 E2E 复验每轮会话
> 不再重复落库（预期每轮 2 行 user+assistant，而非 4 行）。

---

## 审查元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-034 |
| 模块名称 | 短期记忆 + 会话记忆 |
| 审查日期 | 2026-08-06 |
| 审查人 | Reviewer（m34-reviewer，Teammate 模式） |
| 提交人 | Developer（m34-dev） |
| 审查轮次 | 第 1 轮（结论升级） |
| 关联 plan.md | `specs/module-034-short-session-memory/plan.md` |
| 关联分支 | worktree-m8-knowledge-panel |

---

## 一、审查范围（完整阅读，非仅 diff）

| 文件 | 变更类型 | 核对要点 |
|------|----------|----------|
| `ai_service/rag/memory.py` | 修改 | 三层 source 分层（`_memory_source`/`_layer_pattern`）；长期检索由 `:%` 改精确匹配（零回归论证）；`save_short`/`recall_short`（动态 K + TTL 惰性过滤）；`format_memory_line` label 参数 |
| `ai_service/rag/session_memory.py` | 新增 | `save_session_messages`（content_hash 幂等 + 上限滚动）/ `get_session_messages`（隔离恢复） |
| `ai_service/rag/engine.py` | 修改 | `_recall_memory` 长/短合并注入；`_persist_memory` 同批 facts 沉淀长+短；`_resolve_session_history`；`_schedule_session_persist`/`_persist_session` |
| `ai_service/main.py` | 修改 | chat / chat_stream 会话持久化接入 + Step 5 会话恢复 + IP_SESSION_MESSAGES 降级兜底缓存 |
| `ai_service/src/config.py` | 修改 | `memory_short_ttl_days`/`memory_session_max_messages`/`memory_session_history_limit` |
| `ai_service/tests/test_session_memory.py` | 新增 | 11 用例 |
| `ai_service/tests/test_memory.py` | 修改 | long pattern 断言改精确匹配；+13 short 用例 |
| `ai_service/tests/test_identity.py` | 修改 | `_recall_memory` 身份透传补 recall_short |
| `ai_service/tests/test_memory_extractor.py` | 修改 | 补 save_short/recall_short mock；stream helper 补会话恢复/持久化 mock |
| `ai_service/tests/test_stream_memory.py` | 修改 | stream helper 补 `_resolve_session_history`/`_schedule_session_persist` mock |

---

## 二、契约核对（按 plan §3.5）

| 契约 | 结论 | 说明 |
|------|------|------|
| 三层 source 互不混淆 | ✅ | 长期 `memory:<id>:` / 短期 `memory:<id>:short:` / 会话 `memory:<id>:session:`。`_layer_pattern` 无通配符（LIKE 等值），`_memory_source` 尾冒号收尾；`recall`/`recall_short`/`_find_duplicate`/`_next_title` 均按层精确匹配，互不误命中 |
| 长期记忆零回归 | ✅ | 既有长期数据 source 恒为精确 `memory:<id>:`，`LIKE 'memory:<id>:'` 无通配 = 等值，与旧 `:%` 行为对存量一致；全量 254 基线通过证实 |
| memory.save/recall 签名兼容 | ✅ | `save`/`recall` 公共签名不变；新增 `save_short`/`recall_short` 独立方法；`format_memory_line` 新增 `label="长期记忆"` 默认参数（module-033 调用不变） |
| chat/stream 端点签名不变 | ✅ | 端点签名/返回格式零变更；会话恢复在端点函数体内部完成 |
| 匿名降级不变 | ✅ | identity = user_id 优先否则 client_ip；`_normalize_identity` 通配符→'unknown' 不变 |
| 会话持久化不阻塞响应 | ✅ | `_schedule_session_persist` fire-and-forget（`asyncio.create_task` 不 await）；异常在 `_persist_session`/`save_session_messages` 内降级捕获 |
| 短期写入不阻塞 | ✅ | `_persist_memory` 内 `save`/`save_short` 单条异常日志降级，不影响响应 |
| 会话复用 documents 合理 | ✅ | 会话文档无 embedding/无 search_tokens/parent_id=None → 向量（embedding IS NOT NULL）、FTS（search_tokens IS NOT NULL）、普通知识库（NOT LIKE 'memory:%'）三通道均排除；仅等值 source + id 排序恢复 |

---

## 三、独立复现（Reviewer 实测，勿只信 Developer 报告）

| 验证项 | 命令 | 结果 |
|--------|------|------|
| 新增单测（会话 + 短期分层） | `python -m pytest tests/test_session_memory.py tests/test_memory.py -q` | ✅ **53 passed** in 45.29s |
| 全量回归 | `python -m pytest tests/ -q` | ✅ **278 passed / 0 failed / 3 warnings**（3 个 Redis setex 弃用 warning，既有非本模块） |
| 身份回归 | `python -m pytest tests/test_identity.py -q` | ✅ **20 passed** in 52.63s |
| 编译检查 | `python -m py_compile src/config.py rag/memory.py rag/session_memory.py rag/engine.py main.py` | ✅ **OK** |
| 阻塞问题实证 | mock `_schedule_session_persist` 计数，跑单次 knowledge chat | **schedule_session_persist = 2，schedule_persist = 1**（确认双重调度） |

Developer 自测口径（278/0）与 Reviewer 独立复现完全一致。

---

## 四、发现的问题

### 🔴 阻塞问题（1 项，必须修复后再验收）

| 序号 | 严重程度 | 问题描述 | 所在文件 | 修复建议 |
|------|----------|----------|----------|----------|
| 1 | 🔴 阻塞 | **`/ai/rag/chat` 每次 knowledge 请求对会话持久化重复调度两次，每轮对话会话消息确定性重复落库**。`engine.chat` 在 no-docs 分支（L254）与 docs 分支（L268）各调一次 `self._schedule_session_persist(...)`，`main.py` chat（L333）又调一次（内容相同）。两个 fire-and-forget 任务并发执行 `save_session_messages` 的 check-then-insert：两任务各自独立 session（`src/database.py` 连接池 `pool_size=5, max_overflow=10`，必然拿到不同连接并发），SELECT content_hash 均在对方 COMMIT 之前完成 → 两任务都读到空哈希集 → 双双 INSERT。**`content_hash` 列仅 `index=True` 无唯一约束**（models.py L28），DB 层无兜底 → **每轮 user+assistant 各写 2 条（4 行/轮）**。后果：`get_session_messages` 恢复的历史每轮重复、`_resolve_session_history` 注入 LLM 的上下文每轮重复（回答质量劣化）、50 条上限实际减半为 25 轮。现有单测全部 mock 掉 `_schedule_session_persist`，故未覆盖此路径。 | `ai_service/main.py:333`（冗余）+ `ai_service/rag/engine.py:254,268` | **删除 `main.py` chat 的 `rag_engine._schedule_session_persist(...)`（L333）**——`engine.chat` 两 knowledge 分支已覆盖，main.py 调用不增加任何覆盖（其 `result.message` 守卫与 engine 内部 knowledge 路径一致；仅 internal_error 分支差异：engine 不调度而 main.py 会，删后错误响应不再持久化"抱歉"文案，语义更合理）。或反向保留 main.py、删除 engine.chat 两处。**关键是只保留一个调度点**。 |

### 🟡 建议（非阻塞，记录技术债务）

| 序号 | 严重程度 | 问题描述 | 所在文件 | 修复建议 |
|------|----------|----------|----------|----------|
| 2 | 🟡 建议 | **短期去重合并不刷新 created_at**：`_merge_duplicate` 只追加父块 content，不更新 created_at；7 天前创建的短期记忆今日被近义事实合并后，recall_short 的 TTL 过滤仍按原始日期判为过期 → 近期内容不可见 | `ai_service/rag/memory.py:379-407` | 合并时同步刷新 created_at（或基于最近更新时间判断 TTL） |
| 3 | 🟡 建议 | **短期记忆行物理不清理**：TTL 仅召回过滤（惰性），`memory:<id>:short:` 行在 documents 表无限累积；配合去重阈值 0.95（module-033 实测同义改写 cosine≈0.88 不触发），短期层可能堆积近似重复事实 | `ai_service/rag/memory.py` | 后续加周期性清理（按 TTL 删行）或下调 `memory_dedup_threshold`≈0.85（module-033 Tester 建议），记 backlog |
| 4 | 🟡 建议 | **会话 content_hash 仅含 content 不含 role**：user/assistant 同文本（如均"你好"）哈希碰撞导致助手条被跳过；用户完全重复提问也被"幂等"跳过丢失真实轮次 | `ai_service/rag/session_memory.py:92` | hash 纳入 `role + content` |
| 5 | 🟡 建议 | **持久化会话可能丢弃更新鲜的 request.history**：`_resolve_session_history` 只要持久化非空就采用持久化、忽略 request.history；上一轮生成失败（异常路径不调度持久化）时下一轮持久化缺该轮而 request.history 有 → 上下文丢失 | `ai_service/rag/engine.py:398-426` | 可比较两者取更新者，或异常路径也补一次持久化 |
| 6 | 🟡 建议 | **`save_session_messages`（63 行）与 `memory._save`（74 行）超「单方法 ≤ 50 行」约定**（与既往模块同口径宽容处理） | `session_memory.py:55-117` / `memory.py:246-319` | 拆小方法；非阻塞 |
| 7 | 🟢 低 | **`_resolve_session_history` 为生成路径新增至多 3s 查库延迟**（wait_for 3s）；超时降级返回空走 request.history，机制正确 | `ai_service/rag/engine.py` | 可接受；会话量大后可加 Redis 缓存兜底 |
| 8 | 🟢 低 | **TTL cutoff 用本地 `date.today()` 而 created_at 为 PG UTC**（module-033 已记录 8h 时区差）→ 晚间本地写入的短期记忆可能提前约 1 天过期。环境既有，非本模块回归 | `ai_service/rag/memory.py:556` | 记 backlog，改 UTC 基准 |
| 9 | 🟢 低 | `retriever._source_condition` docstring 仍写"记忆检索 'memory:\<ip\>:%'"（retriever.py 未随本模块改），实际已精确匹配 | `ai_service/rag/retriever.py` | 同步注释 |

---

## 五、安全检查核对

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 三层按本身份隔离 | ✅ | 长期/短期检索用 `_layer_pattern` 精确 LIKE（无通配符）+ `_normalize_identity` + `_escape_like` 双保险；会话层用 `Document.source == source` 等值查询（非 LIKE），注入面更小 |
| LIKE 注入防护保留 | ✅ | `_normalize_identity` 拒绝 `%`/`_`/`\` → 'unknown'；`_escape_like` 转义双保险仍在；session 等值查询无通配符注入可能 |
| TTL 惰性过滤 fail-open 合理 | ✅ | `recall_short` 按 created_at 过滤早于 cutoff 的记录；无 created_at fail-open 保留（无法判断年龄不误删）。新写短期记忆均带 created_at（DB server_default），无日期仅存于理论/遗留数据 |
| 会话 content_hash 幂等 | ⚠️ | 顺序重放幂等正确（有单测）；**并发下无唯一约束兜底失效**（阻塞项 #1 根因之一） |
| 日志无敏感信息 | ✅ | 日志仅 identity + 条数 + source，不含消息/答案内容 |
| 会话文档不泄漏进检索 | ✅ | 无 embedding/无 search_tokens/parent_id=None → 向量、FTS、知识库三通道均排除 |

---

## 六、架构检查核对

| 检查项 | 结论 | 说明 |
|--------|------|------|
| 分层 | ✅ | session_memory.py 为服务层（复用 memory.py 既有 Repository 风格）；engine 编排；main 接线 |
| 依赖方向 | ✅ | session_memory → memory（`_normalize_identity`/`MEMORY_SOURCE_PREFIX`）；memory 不依赖 session_memory；engine 依赖二者；无循环 |
| 会话复用 documents 合理性 | ✅ | 无新表；会话文档无向量不参与检索，仅等值 source + id 排序恢复；content_hash 幂等 + 上限滚动防膨胀，符合 plan 风险缓解 |
| source 精确匹配 vs `:%` 回归风险 | ✅ | test_memory.py 6 处断言已同步更新为精确模式（4 处 recall pattern + `_next_title` 2 处）；retriever `_source_condition` 测试传任意字符串仅测 SQL 片段生成，不受影响 |
| 模块拆分 | ✅ | 新增/变更集中在 memory/session_memory/engine/main/config，职责单一 |

---

## 七、验收标准核对（acceptance-criteria.md，按实际复选框统计 36 项）

> 注：acceptance-criteria.md 汇总表标"34 项（14/3/5/8/4）"，实际复选框为 36 项
> （接口 4：§2.1 三项 + §2.2 一项；代码质量 6：§3.1-§3.4 共 6 复选框）。按实际复选框签署
> （与 module-033 统计差异处理同款口径）。

| 类别 | 总项 | 代码/单测核验 | 留 Tester | 附条件 |
|------|------|------|------|------|
| 功能验收 | 14 | 14 | 0 | 0 |
| 接口验收 | 4 | 4 | 0 | 0 |
| 代码质量验收 | 6 | 5 | 0 | 1（单方法 ≤50：2 处超限，建议 #6） |
| 测试验收 | 8 | 5（单测+回归+身份） | 3（§4.3 真实 E2E） | 0 |
| 文档验收 | 4 | 4 | 0 | 0 |
| **合计** | **36** | **32** | **3** | **1** |

- 功能 14/14：save_short source ✅、会话摘要生成（extract_facts 同批沉淀 short）✅、短期去重（layer='short'）✅、摘要失败降级 ✅；recall_short 动态K+TTL ✅、注入段区分（"历史记忆" vs "最近上下文"）✅、TTL 过滤 ✅、空短期 ✅；会话保存/恢复/隔离/无持久化兜底 ✅；三前缀并存 ✅、长期零回归（278/0）✅
- 接口 4/4：save/recall 签名兼容 ✅、chat/stream 端点签名不变 ✅、source 格式不变（新增后缀）✅、TTL/会话上限可配置 ✅
- 代码质量：Docstring ✅、snake_case ✅、py_compile ✅、无未使用 import ✅；单方法 ≤50 有 2 处超限（宽容）；模块生产代码约 390-500 行，接近 plan 声明调整的 450 行预算
- 测试 5/8（单测 11+13+39、回归 278/0、身份 20/0）+ 3 项真实 E2E 留 Tester
- 文档 4/4：changelog.md ✅、plan.md §3 ✅、project-context.md ✅、agent-activity-log.md ✅

> ⚠️ 注意：阻塞项 #1 影响功能验收 §1.3「会话保存」的生产质量——功能存在、顺序幂等单测通过，但
> 生产路径每轮重复落库。修复后 Tester 真实 E2E 时应核验「一轮对话 → 会话库恰好 2 行
> （user+assistant 各 1）」作为回归点。

---

## 审查总结

### 审查结论

- [ ] ✅ 通过
- [ ] ⚠️ 有条件通过
- [x] ❌ **不通过** — 1 项阻塞问题（§四 #1 会话持久化双重调度 → 每轮确定性重复落库），修复后请 Developer 重新提交审查（Round 2）

### 需记录的 ADR

- [x] 无（三层 source 分层 / 会话复用 documents 均为既有架构自然延伸，无新架构决策）

### 审查人签名

- 审查人：m34-reviewer
- 日期：2026-08-06
- 结论：❌ 不通过（1 项阻塞：main.py/engine.py 会话持久化双重调度，修复预期一行级）
