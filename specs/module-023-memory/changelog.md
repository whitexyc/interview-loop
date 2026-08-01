# 变更日志 — Module-023: 长期记忆（跨会话记忆沉淀）

## 变更概述

系统此前无长期记忆（仅 Redis 短期缓存 + 内存 IP 会话，重启丢失）。本模块新增跨会话记忆：
复用 documents 表（`source='memory:<ip>:'` 区分，无新表）与既有分块/向量化/混合检索全链路，
提供保存（`POST /ai/memory/save`）与检索（`POST /ai/memory/recall`）两个 API，
并在 `chat` 生成前按 IP 召回相关记忆拼入生成 prompt（"历史记忆: ..."），
无记忆时行为完全不变（零回归）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/memory.py | 新增 | MemoryService：save（分块+向量化+入库）/ recall（source 过滤检索） |
| ai_service/tests/test_memory.py | 新增 | 单元测试 17 例（save/recall/IP 隔离/source 过滤/零回归前提） |
| ai_service/rag/retriever.py | 修改 | 新增可选 `source_pattern` 参数；默认排除 `memory:%`（防记忆污染知识库检索） |
| ai_service/rag/engine.py | 修改 | chat 生成前 `_recall_memory` 召回记忆注入 prompt（无记忆零回归） |
| ai_service/agent/reflector.py | 修改 | `_GENERATE_PROMPT` 新增 `{memory_section}`；generate_answer 系列加可选 memory 参数 |
| ai_service/rag/schemas.py | 修改 | 新增 MemorySaveRequest / MemoryRecallRequest |
| ai_service/main.py | 修改 | 新增 /ai/memory/save、/ai/memory/recall；chat 端点透传 client_ip |

**v3 追加变更**（Reviewer 第二轮问题修复）：

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/memory.py | 修改 | 新增 `_normalize_ip`（IPv4 校验）+ `_escape_like`（LIKE 转义）；save/recall/_next_title 统一 IP 规范化（#1）；_next_title 计数限定本 IP+当日（#4） |
| ai_service/agent/reflector.py | 修改 | `_GENERATE_PROMPT` 恢复 `{sections}` 后换行，空 sections 时与旧版逐字节一致（#2） |
| ai_service/rag/engine.py | 修改 | realtime 意图提前返回，`_recall_memory` 移至其后（#5） |
| ai_service/main.py | 修改 | list_documents 分组子查询排除 `source NOT LIKE 'memory:%'`（#7） |
| ai_service/tests/test_memory.py | 修改 | 新增 8 个回归测试（#1/#2/#4/#5/#7） |

> 说明：retriever.py / reflector.py 不在 plan §3.1 文件列表中，但为满足 plan §3.4
> 「复用 hybrid_retriever（限定 source 过滤）」与「拼入生成 prompt」所必需的使能改动，
> 均为向后兼容（新参数默认值不改变既有行为）。

**v4 追加变更**（Tester 测试反馈修复）：

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/memory.py | 修改 | save 改传 `date.today()`（date 对象）；`_next_title` 参数类型 `str` → `date`（SQLAlchemy 绑定 DATE，修复真实 save 崩溃） |
| ai_service/tests/test_memory.py | 修改 | 更新 2 个 `_next_title` 用例传 `date` 对象；新增 2 个回归测试（save 传 date 对象 / 绑定参数为 DATE 类型） |

## 关键设计说明

### 设计决策 1: 复用 documents 表，source='memory:<ip>:' 隔离
- 决策：无新表，记忆复用 documents 表；`source='memory:<ip>:'` 区分记忆与知识库文档；标题 `记忆-<日期>-<序号>`
- 原因：直接复用 chunker / embedding_service / hybrid_retriever 全链路，避免重复实现存储与检索

### 设计决策 2: source 过滤双方向（防记忆污染知识库检索）
- 决策：① recall 用 `source_pattern='memory:<ip>:%'` 只查本 IP 记忆；
  ② 普通知识库检索（source_pattern=None）默认附加 `source NOT LIKE 'memory:%'`（retriever._source_condition）
- 原因：满足验收「检索只查记忆（source 过滤），不污染知识库检索」——
  记忆必须按 IP 隔离，同时知识库检索结果不得混入记忆文档；
  source 以尾冒号分隔 IP 与内容，LIKE 前缀匹配不会交叉命中前缀重叠的其他 IP

### 设计决策 3: 生成前注入 + 零回归
- 决策：chat 意图识别后调用 `memory_service.recall(query, client_ip)`（超时 5s）；
  命中记忆以「历史记忆: ...」拼入生成 prompt（闲聊/无结果兜底/知识库生成三路径）；
  召回失败/无记忆时 memory_text=""，prompt 与之前完全一致
- 原因：记忆作为额外上下文，不影响无记忆路径（零回归）；异常时降级为空，不阻塞问答

### 设计决策 4: 简单总结优先（不自动总结会话）
- 决策：只提供手动 save 接口（内容由前端/会话结束提供），不做自动会话总结
- 原因：plan §3.4 明确「简单总结优先」，避免引入 LLM 总结复杂度与质量不确定性

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 单元测试 | `python -m pytest tests/test_memory.py -v` | 19 passed |
| 全量回归 | `python -m pytest tests/ -q` | 2 failed（既有 test_engine async 用例，缺 pytest-asyncio）/ 73 passed，无新增失败 |
| 导入检查 | `python -c "import rag.memory, rag.engine, rag.retriever, rag.schemas, agent.reflector, main"` | 无异常 |
| 编译检查 | `python -m py_compile rag/memory.py rag/retriever.py rag/engine.py rag/schemas.py agent/reflector.py main.py tests/test_memory.py` | OK |
| 真实 DB 冒烟 | `python _tmp_memory_smoke.py`（save A → recall A 命中 / recall B 空 → 知识库检索无 memory source → 清理） | save 标题 记忆-2026-08-01-01/02、source='memory:<ip>' 4 行、embedding 1024 维、IP 隔离 ✅、清理后 0 残留 |
| 接口验证 | `curl -X POST http://localhost:8000/ai/memory/save -H "Content-Type: application/json" -d '{"content":"用户偏好简洁回答","ip":"192.168.1.1"}'` | `{"code":0,"data":{"id":N,"title":"记忆-...","status":"saved"}}` |
| 接口验证 | `curl -X POST http://localhost:8000/ai/memory/recall -H "Content-Type: application/json" -d '{"query":"回答风格","ip":"192.168.1.1"}'` | `{"code":0,"data":{"memories":[...]}}` |
| 单元测试（v3） | `python -m pytest tests/test_memory.py -v` | 27 passed |
| 全量回归（v3） | `python -m pytest tests/ -q` | 81 passed / 2 failed（既有 test_engine async 用例缺 pytest-asyncio，非本模块回归） |
| 通配符注入回归（v3） | `python -m pytest tests/test_memory.py -k "wildcard or escape_like" -v` | 3 passed |
| prompt 零回归验证（v3） | `python -m pytest tests/test_memory.py -k "byte_identical" -v` | 1 passed |
| 单元测试（v4） | `python -m pytest tests/test_memory.py -v` | 29 passed（新增 2 个回归测试） |
| 全量回归（v4） | `python -m pytest tests/ -q` | 83 passed / 2 failed（既有 test_engine async 用例缺 pytest-asyncio，非本模块回归） |
| 真实 DB 冒烟（v4） | `python _tmp_smoke.py`（save→recall 命中→IP 隔离→序号递增→清理，验证后已删除） | save `{code:0, data:{id, title:'记忆-2026-08-01-01', status:'saved'}}`；recall 命中；另一 IP 空；第 2 条 save 标题 -02；清理后 0 残留 ✅ |

## 修复记录 (v3: Reviewer 第二轮问题修复)

针对 `review-report.md` 第二轮问题清单逐项处理：

1. **问题 #1（阻塞）LIKE 通配符注入绕过按 IP 隔离 → 已修复**
   - 根因：`source_pattern=f"memory:{ip}:%"` 直接拼接客户端可控 `ip`，未校验格式；
     `ip="%"` → `memory:%:%` 匹配全部记忆 source，可跨 IP 读取所有用户记忆；`ip="_"` 同理
   - 修复（双保险）：① `_normalize_ip(ip)`：IPv4 正则 `^\d{1,3}(\.\d{1,3}){3}$` 校验，
     空白/非 IPv4（含 `%`/`_`/`\`）一律降级 `unknown`；② `_escape_like(s)`：构造 pattern
     前转义 LIKE 元字符。save 写 source、recall 构造 pattern、_next_title 计数统一走规范化
   - 新增回归测试：`test_recall_ip_wildcard_cannot_bypass`、
     `test_save_ip_wildcard_normalized_to_unknown`、`test_escape_like_escapes_metacharacters`

2. **问题 #2（中）changelog「逐字节一致」声明不实 → 已修复**
   - 根因：v2 将 `{history_section}\n{memory_section}` 合并为单行 `{sections}` 时，
     去掉了旧版 history_section 行自带的空行；空 sections 时新旧 prompt 差一个空行
   - 修复：`_GENERATE_PROMPT` 恢复 `{sections}` 后的换行（`{sections}\n用户问题: {query}`），
     空 sections 时与旧版**逐字节一致**（`列表\n\n\n用户问题`，2 空行，实测验证）
   - 新增回归测试：`test_empty_sections_byte_identical_to_old`

3. **问题 #3（中）chat_stream 未接入记忆注入 → 计划范围决策，不改代码**
   - 与 plan §3.4 仅 `engine.chat` 范围一致；`generate_answer_stream` 的 `memory`
     参数已预留默认空串。接入前 **Tester 限定验收「场景 3 记忆注入回答」范围为
     非流式端点 `/ai/rag/chat`**；真实前端链路（流式）接入列入后续模块 backlog

4. **问题 #4（低）_next_title 全局计数 → 已修复**
   - 根因：计数 `source LIKE 'memory:%' AND parent_id IS NULL` 不按日期/IP 过滤，
     序号跨日期累计
   - 修复：计数改为本 IP（`source LIKE 'memory:<ip>:%'`）+ 当日
     （`date(created_at)=当日`）过滤，`_next_title(day, ip)`
   - 更新/新增回归测试：`test_counts_memory_parents_by_source_not_title`（加 IP/日期断言）、
     `test_next_title_scoped_to_ip_not_global`

5. **问题 #5（低）记忆召回在意图分支前执行 → 已修复**
   - 根因：`_recall_memory` 置于 if/else 意图分支之前，realtime 意图结果被丢弃，
     最坏增加 5s 延迟
   - 修复：engine.chat 中 realtime 意图提前返回，`_recall_memory` 移至其后再执行
     （闲聊/知识库路径仍召回记忆，行为不变）
   - 新增回归测试：`test_chat_realtime_skips_memory_recall`、
     `test_chat_casual_still_recalls_memory`

6. **问题 #6（低）错误响应用 message 键 → 维持现状（本次不阻塞）**
   - 与 main.py 既有端点（upload_document 等）风格一致；统一 `msg` 键列入后续全文件清理

7. **问题 #7（低）list_documents 列出记忆文档 → 已修复（本模块引入的回归）**
   - 根因：本模块复用 documents 表存记忆（source='memory:%'），既有 `/ai/documents`
     列表无 source 过滤，记忆行污染知识库管理面板
   - 修复：list_documents 分组子查询排除
     `source IS NULL OR source NOT LIKE 'memory:%'`（与 retriever._source_condition 同款条件）
   - 新增回归测试：`test_list_documents_excludes_memory_source`

## 修复记录 (v4: Tester 测试反馈修复)

针对 `test-report.md` 失败详情逐项处理：

1. **问题 #1（阻塞）真实 save 路径崩溃（date = character varying）→ 已修复**
   - 根因：v3 修复 #4「_next_title 按 IP+当日计数」引入回归——`save` 调用
     `_next_title(date.today().isoformat(), ip)` 传**字符串**日期，查询
     `func.date(Document.created_at) == day` 经 asyncpg 绑定为 `$2::VARCHAR`，
     PostgreSQL 无 `date = character varying` 运算符 → 任何真实 save 抛
     `ProgrammingError`，被 save 捕获转 `RuntimeError` → 端点恒返回
     `{code:2, message:'记忆保存失败'}`，记忆永远无法入库。
     单测全部 mock 了 session（`_FakeSession` 断言编译后 SQL 字符串，字面量
     `'2026-08-01'` 被 PG 隐式转 date），故 27 例全绿；真实 asyncpg 绑定参数
     显式带类型才暴露。
   - 修复（最小改动）：`save` 改传 `date.today()`（`datetime.date` 对象），
     SQLAlchemy 绑定为 DATE；`_next_title` 参数类型契约 `str` → `date`
     （docstring 注明不可传 ISO 字符串）。`f"记忆-{day}-"` 对 date 对象格式化
     仍为 `记忆-YYYY-MM-DD-NN`，标题格式不变。
   - 新增回归测试（2 例，见 test_memory.py `TestNextTitle`）：
     - `test_save_passes_date_object_to_next_title`：断言 save 传给
       `_next_title` 的第一个参数是 `datetime.date` 实例（非 str）
     - `test_next_title_binds_date_not_string`：断言 `_next_title` 编译后
       绑定参数含 `date` 类型值（改回 ISO 字符串将断言失败）
   - 真实 DB 验证：`python _tmp_repro.py` / `_tmp_smoke.py` —— save →
     `{code:0, data:{id, title, status:'saved'}}`，recall 命中、IP 隔离、
     当日序号递增（-01 → -02），清理后 0 残留。脚本验证后已删除。

2. **问题 #2（中）chat_stream 未接入记忆注入 → 计划范围决策，不改代码**
   - 与 plan §3.4 将注入范围限定 `engine.chat` 一致（非流式端点生效）；
     `generate_answer_stream` 的 `memory` 参数已预留默认空串。
   - 处置：真实前端链路走流式端点，接入 `_recall_memory` 列入后续模块
     backlog；接入前验收「场景 3 记忆注入回答」限定非流式 `/ai/rag/chat`。

3. **问题 #3（低）记忆端点错误响应用 `message` 键 → 维持现状（本次不阻塞）**
   - 与 main.py 既有端点（upload_document 等）风格一致；统一 `msg` 键列入
     后续全文件清理（changelog #6 已记录）。

## 修复记录 (v2: Reviewer 问题修复)

针对 `review-report.md` 问题清单逐项修复：

1. **问题 #1（高）按 IP 隔离前缀 LIKE 泄漏 → 已修复**
   - `save` 的 source 增加尾冒号分隔符：`source = f"memory:{ip}:"`
   - `recall` 匹配模式同步改为 `f"memory:{ip}:%"`（`memory.py` L70 / L145）
   - 效果：`LIKE 'memory:192.168.1.1:%'` 不再匹配 `memory:192.168.1.10:...`，
     前缀重叠 IP（如 `192.168.1.1` vs `192.168.1.10`）不再交叉泄漏记忆
   - 新增回归测试 `test_recall_ip_prefix_overlap_no_cross_match`（startswith 镜像 SQL LIKE）

2. **问题 #2（中）save 方法超 50 行 → 已修复**
   - `save` 拆分出私有方法 `_insert_parents`（28 行）与 `_insert_children`（~30 行），
     `save` 仅编排事务与回滚（48 行含 docstring）
   - 行为不变：父块 flush 取 ID → 子块向量化 + 写入 → 整体 commit/rollback

3. **问题 #3（低）prompt 空白回归 → 已修复（严格零回归）**
   - `_GENERATE_PROMPT` 将 `{history_section}\n{memory_section}` 合并为单行 `{sections}`
   - `generate_answer` / `generate_answer_stream` 改为 `sections = history_section + memory_section`
   - 已验证：history 与 memory 均为空时，prompt 与旧版**逐字节一致**（`列表\n\n用户问题`，无多余空行）

4. **问题 #4（低）chat_stream 未接入记忆注入 → 计划范围决策，不改代码**
   - 与 plan §3.4 明确 `engine.chat` 范围一致；`generate_answer_stream` 的 `memory` 参数已预留默认空串
   - 后续模块可在 `chat_stream` 接入 `_recall_memory`；真实前端链路（流式）暂不验收「记忆注入回答」

5. **问题 #5（低）_next_title 计数依赖标题格式 → 已修复**
   - 计数条件由 `title LIKE '记忆-<日期>-%'` 改为 `source LIKE 'memory:%' AND parent_id IS NULL`，
     记忆内容含 markdown 标题（父块标题为标题文本）时不再漏计，避免序号重复/跳号
   - 新增回归测试 `test_counts_memory_parents_by_source_not_title`

6. **问题 #6（低）错误响应用 message 键 → 文件既有风格，不改代码**
   - 与 main.py 既有端点（upload_document 等）保持一致；统一 `msg` 键列入后续全文件清理

> 兼容性说明：source 格式由 `memory:<ip>` 改为 `memory:<ip>:`。冒烟数据已清理、
> 无真实存量记忆文档，故无数据迁移需求；如未来存在旧格式行，recall 新模式不会命中，
> 但仅影响存量记忆（不影响知识库检索，`source NOT LIKE 'memory:%'` 排除逻辑不变）。

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现 | Developer |
| v2 | 2026-08-01 | 修复 #1 IP 隔离前缀泄漏（source 尾冒号）；#2 save 拆分方法；#3 prompt 严格零回归；#5 _next_title 按 source 计数；新增 2 个回归测试 | Developer |
| v3 | 2026-08-01 | 修复 #1 通配符注入（IP 校验+LIKE 转义双保险）；#2 prompt 恢复字节零回归；#4 _next_title 本 IP+当日计数；#5 realtime 跳过记忆召回；#7 列表排除记忆文档；#3/#6 记录处置；新增 8 个回归测试 | Developer |
| v4 | 2026-08-01 | 修复 Tester 阻塞 #1：`_next_title` 当日参数 date=varchar 类型不匹配致真实 save 崩溃（save 改传 `date.today()` date 对象）；新增 2 个回归测试 + 真实 DB 冒烟验证；Tester #2（chat_stream 记忆注入）/#3（message 键）维持范围/风格记录处置 | Developer |
