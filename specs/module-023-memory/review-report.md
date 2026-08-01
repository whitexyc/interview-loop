# 审查报告 — Module-023: 长期记忆（跨会话记忆沉淀）

## 1. 审查结论

- 结论: **通过**（v3 修复已覆盖前两轮全部问题；本轮新发现问题均为低严重度建议，不阻塞进入测试阶段）
- 审查时间: 2026-08-01
- 审查人: Reviewer
- 审查耗时: 约 40 分钟
- 审查轮次: 第 3 轮（针对 Developer v3 修复后的复审）

## 2. 问题列表

### 2.1 阻塞问题（必须修复才能通过）

无。v2/v3 两轮阻塞与高风险问题均已修复并实测验证：

- **#1 阻塞·LIKE 通配符注入**（第 2 轮阻塞项）：已修复。`_normalize_ip`（IPv4 正则校验 `^\d{1,3}(\.\d{1,3}){3}$`，空/非 IPv4 含 `%`/`_`/`\` 一律降级 `unknown`）+ `_escape_like`（转义 LIKE 元字符）双保险。`ip="%"`/`"_"`/`"\\"` 均降级为 `unknown` 桶，无法构造 `memory:%:%` 跨 IP 读取。`re.match` 配合 `^...$` 全匹配 + 先 `.strip()`，无尾换行绕过。save 写 source、recall 构造 pattern、_next_title 计数统一走规范化。回归测试 `test_recall_ip_wildcard_cannot_bypass` / `test_save_ip_wildcard_normalized_to_unknown` / `test_escape_like_escapes_metacharacters` 全部通过。✅
- **#2 中·prompt 字节回归声明不实**：已修复。`_GENERATE_PROMPT` 仅将占位符 `{history_section}` 改名为 `{sections}` 并保留其后换行，空 sections 时与旧版逐字节一致（`test_empty_sections_byte_identical_to_old` 通过）；changelog 措辞已更正。✅
- **#4 中·_next_title 全局计数**：已修复。计数限定本 IP（`source LIKE 'memory:<ip>:%'`）+ 当日（`date(created_at)`）过滤，序号不再跨日期/IP 累计；更新 + 新增回归测试通过。✅
- **#5 低·recall 在意图分支前**：已修复。realtime 意图提前返回，`_recall_memory` 移至其后；闲聊/知识库路径仍召回记忆（`test_chat_realtime_skips_memory_recall` / `test_chat_casual_still_recalls_memory` 通过）。✅
- **#7 低·list_documents 列出记忆**：已修复。分组子查询排除 `source IS NULL OR source NOT LIKE 'memory:%'`（`test_list_documents_excludes_memory_source` 通过）。✅
- **#3 chat_stream / #6 message 键**：已记录处置（计划范围决策 / 维持既有风格），可接受。

### 2.2 建议改进（不阻塞但建议修复）

| # | 文件 | 行号 | 问题描述 | 严重级别 | 修复建议 |
|---|------|------|----------|----------|----------|
| 1 | ai_service/main.py | L341-366（memory_save / memory_recall） | 记忆端点信任请求体 `ip`，与 chat 召回用的 `request.state.client_ip`（中间件检测的真实 IP）来源不一致：任何人可伪造任意 IPv4 读写该桶（按"声明标识"隔离，非真实来源隔离），且前端若传的 ip 与中间件检测值不同，save 的记忆将无法被 chat 召回（集成失效风险）。计划 §3.3 即定义为 body 字段，属设计限制；个人站可接受 | 低 | 后续统一从 `request.state.client_ip` 取 IP（与 `/ai/rag/chat` 一致），消除伪造面与召回失效风险；或前端接入时保证 save/recall/chat 三处 ip 同源 |
| 2 | ai_service/rag/memory.py | L43-65（_normalize_ip） | 仅接受 IPv4；IPv6 真实客户端（本机 `::1`、`fe80::*`）全部降级 `unknown` 桶，隔离粒度坍缩为单桶（安全无虞，隔离变粗） | 低 | 若未来需支持 IPv6 客户端，可将 `_normalize_ip` 扩展为接受冒号十六进制形式的 IPv6 并继续走 LIKE 转义；当前个人站可接受 |
| 3 | ai_service/rag/memory.py | L233-260（_next_title） | 计数非原子（count 后 insert），并发同 IP+当日 save 可能产生重复标题序号；仅影响标题美观，不影响数据正确性 | 低 | 若在意标题唯一性，可将标题改为 DB id 派生或在事务内锁定；当前可接受 |
| 4 | ai_service/main.py L209-335 / ai_service/agent/reflector.py L196-240 | chat_stream 未接入记忆注入（plan §3.4 范围决定，已记录） | 真实前端链路 `/ai/rag/chat/stream` 暂不注入记忆，用户经流式端点看不到记忆沉淀效果 | 低 | Tester 验收「场景 3 记忆注入回答」限定非流式 `/ai/rag/chat`；流式接入列入后续模块 backlog |
| 5 | ai_service/（memory.py 299 行 + main/engine/retriever/reflector/schemas 增量） | 新增代码量约 540 行（不含测试），超出 plan 约 300 行预估 | plan.md 已注明"需调整上限"，属规划内偏差，如实记录 | 低 | 后续模块拆分的代码量估算应更贴近实际 |
| 6 | ai_service/rag/engine.py | L134-249（chat） | chat 方法约 116 行，超过方法 ≤50 行限制；v3 之前已超长，本模块增长约 19 行 | 低 | 后续拆分意图/闲聊/知识库子路径（如独立 `_chat_casual` / `_chat_knowledge` 私有方法） |
| 7 | ai_service/main.py | L352、L366（错误响应键） | 错误响应用 `message` 键而非 CLAUDE.md §5 名义 `msg`；与 main.py 既有端点（upload_document 等）风格一致 | 说明 | 统一 `msg` 键列入后续全文件清理（changelog #6 已记录） |

## 3. 验收标准核对

| 验收项 | 对应代码 | 状态 | 备注 |
|--------|----------|------|------|
| 保存记忆入库 | memory.py save（L91-140）→ documents source='memory:<ip>:' | ✅ 通过 | test_save_writes_documents_with_memory_source 通过 |
| 检索记忆 | memory.py recall（L202-231）source_pattern 过滤 | ✅ 通过 | test_recall_passes_source_pattern_and_expands_to_parent 通过 |
| 记忆向量化 | _insert_children 写 1024 维 embedding + search_tokens | ✅ 通过 | 子块带向量，父块无向量 |
| 按 IP 隔离 | source='memory:<ip>:' + recall 'memory:<ip>:%' | ✅ 通过 | 前缀重叠 + 通配符注入回归测试通过 |
| 无记忆时零回归 | engine._recall_memory 返回空串，sections="" 字节一致 | ✅ 通过 | test_no_memories_returns_empty + byte_identical 通过 |
| 空 content 保存返回错误 | save 抛 ValueError → 端点 code 1 | ✅ 通过 | |
| 空 ip 默认 'unknown' | _normalize_ip 降级 | ✅ 通过 | |
| 无匹配记忆返回空列表 | recall 返回 [] | ✅ 通过 | |
| 检索 query 为空返回空 | recall 首行判空返回 [] | ✅ 通过 | |
| embedding 不可用返回错误码不崩 | save 抛 RuntimeError → 端点 code 2，事务回滚 | ✅ 通过 | test_save_embedding_failure_raises 通过 |
| 检索失败返回空记忆回答照常 | recall 捕获异常返回 []，engine 降级 | ✅ 通过 | |
| 数据库不可用返回错误 | save 异常 → code 2 | ✅ 通过 | |
| POST /ai/memory/save 请求 {content, ip} | schemas.MemorySaveRequest | ✅ 通过 | |
| 返回 {code, data:{id, status}} | save 端点返回 data{id,title,status} | ✅ 通过 | |
| POST /ai/memory/recall 请求 {query, ip} | schemas.MemoryRecallRequest | ✅ 通过 | |
| 返回 {code, data:{memories:[{content, score}]}} | recall 端点 | ✅ 通过 | |
| memories 按 score 降序 | _expand_to_parents sorted(reverse=True) | ✅ 通过 | test_recall_dedup_same_parent_take_highest_score 通过 |
| documents 表 source='memory:<ip>' | save source=f"memory:{ip}:" | ✅ 通过 | 尾冒号分隔，IP 前缀重叠不泄漏 |
| 记忆文档有 embedding（1024 维） | embedding_service.embed_documents | ✅ 通过 | |
| 检索只查记忆（source 过滤）不污染知识库检索 | retriever._source_condition 双向过滤 | ✅ 通过 | test_default_excludes_memory_prefix 通过 |
| 所有 public 方法有 Docstring | save/recall/_next_title/_expand_to_parents 等 | ✅ 通过 | |
| 记忆注入逻辑有行内注释 | engine._recall_memory + 注入处注释 | ✅ 通过 | |
| 函数/变量 snake_case | 全部符合 | ✅ 通过 | |
| 单个方法 ≤ 50 行 | save=50 行（含 docstring，贴线），其余均达标 | ✅ 通过 | engine.chat 为既有超长（见 2.2 #6） |
| 本模块新增代码 ≤ 300 行 | 实际约 540 行（不含测试） | ⚠️ 说明 | plan.md 已注明"需调整上限"（见 2.2 #5） |
| Python 语法通过 | py_compile 全部 OK | ✅ 通过 | 实测 |
| 无未使用 import | 检查无新增未使用 import | ✅ 通过 | |
| MemoryService save/recall 单测 | test_memory.py 27 例 | ✅ 通过 | 实测 `pytest tests/test_memory.py` 27 passed |
| source 过滤逻辑单测 | TestSourceFilter 4 例 | ✅ 通过 | |
| `pytest tests/ -x` 无新增失败 | 81 passed / 2 failed（既有 test_engine async 用例缺 pytest-asyncio） | ✅ 通过 | 实测确认 2 个失败均为既有环境问题，非本模块回归 |
| chat 无记忆时行为不变 | 空 sections 字节一致测试 | ✅ 通过 | |

## 4. 架构评估

- 分层正确性: **通过**。memory.py 独立为服务层，main.py 仅挂端点，engine 编排注入，schemas 定义模型；无跨层调用。
- 依赖方向: **正确**。engine → memory_service → hybrid_retriever/embedding/chunker；无反向依赖。
- DTO 约束: **通过**。请求/响应走 pydantic 模型与 dict，未泄漏 ORM Entity 到端点返回。
- 新增依赖: **无**。全部复用既有 chunker/embedding/hybrid_retriever，无 plan.md 未定义的新依赖。

## 5. 安全评估

- [x] SQL 注入防护: **通过**。source_pattern 走绑定参数（`LIKE :source_pattern`），无字符串拼接注入；LIKE 元字符经 `_normalize_ip` + `_escape_like` 双保险转义，PG LIKE 默认反斜杠转义语义正确。
- [x] 通配符注入（IP 隔离绕过）: **通过**。`ip="%"`/`"_"`/`"\\"` 降级 `unknown`，回归测试覆盖（第 2 轮阻塞项已闭环）。
- [x] 记忆污染知识库检索: **通过**。`_source_condition(None)` 默认排除 `memory:%`（保留前缀，既有文档无此来源，零回归）；graph 通道不受影响（记忆 save 不写图）。
- [x] 敏感信息日志处理: **通过**。仅记录 title/source/chunks，未记录记忆全文。
- 说明: 按 IP 隔离本质是"按声明标识"隔离（body ip 可伪造），属计划设计限制，非本模块代码缺陷；个人站场景可接受（见 2.2 #1）。

## 6. 架构决策记录（ADR）

- 本次审查是否产生 ADR: 否（无新依赖、无与 plan 不同的架构决策；changelog 中的范围决策均已记录在案）

## 7. 审查检查清单

- [x] 命名符合规范（snake_case）
- [x] 接口返回统一格式（与 main.py 既有端点一致 `{code, message, data}`；`msg` 统一清理列入 backlog）
- [x] Controller / Service / Repository 分层正确
- [x] 无跨层调用或反向依赖
- [x] 异常处理无空 catch
- [x] 关键操作有日志记录（save/recall 均记 logger）
- [x] 敏感信息处理正确
- [x] 代码长度在限制内（本模块新增方法均 ≤ 50 行；engine.chat 为既有超长）
- [x] API 端点命名 kebab-case（/ai/memory/save、/ai/memory/recall 单路径段）
- [x] 安全性检查通过（LIKE 注入、SQL 参数化、source 隔离双向过滤）

## 8. 审查验证记录（实测）

| 验证项 | 命令 | 实测结果 |
|--------|------|----------|
| 本模块单测 | `python -m pytest tests/test_memory.py -q` | 27 passed（51.7s） |
| 全量回归 | `python -m pytest tests/ -q` | 81 passed / 2 failed（test_engine async 缺 pytest-asyncio，既有问题非本模块回归） |
| 编译检查 | `python -m py_compile rag/memory.py rag/retriever.py rag/engine.py rag/schemas.py agent/reflector.py main.py tests/test_memory.py` | OK |
| 导入检查 | `python -c "import rag.memory, rag.engine, rag.retriever, rag.schemas, agent.reflector, main"` | import OK |

> 待 Tester 关注：真实 DB 冒烟（save A → recall A 命中 / recall B 空）、`/ai/memory/save`、`/ai/memory/recall` 接口验证、场景 3 记忆注入限定非流式 `/ai/rag/chat`。

## 9. 审查人自检

- [x] 已读取 changelog.md / plan.md / acceptance-criteria.md / project-context.md
- [x] 已阅读全部变更文件完整内容（memory.py / main.py / engine.py / schemas.py / retriever.py / reflector.py / test_memory.py / models.py）
- [x] 实测 `pytest tests/test_memory.py` → 27 passed；全量 81 passed / 2 failed（既有环境问题）；py_compile + import 通过
- [x] 每个问题标注文件 + 行号 + 具体修复建议
- [x] 验收标准逐项核对
- [x] 架构分层 / 依赖 / 安全 / 依赖审计完成

---

> **下一步**：通过 — 通知 Tester 进入测试阶段；Tester 验收「场景 3 记忆注入回答」时限定非流式 `/ai/rag/chat`。
