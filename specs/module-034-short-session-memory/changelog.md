# 变更日志 — Module-034: 短期记忆 + 会话记忆

## 变更概述

补齐三层记忆架构的短期（最近上下文，TTL 7 天）与会话（历史持久化）两层：

1. **source 三层分层** — 长期 `memory:<identity>:`（不变）/ 短期 `memory:<identity>:short:` /
   会话 `memory:<identity>:session:`。长期检索/去重/标题计数由旧 `memory:<id>:%` 通配改为
   **精确匹配**（`_layer_pattern`），避免命中新增的 short/session 层（既有长期数据 source
   恒为精确值，行为一致零回归，仅不再误命中）。
2. **短期记忆** — `save_short`（复用分块/嵌入/入库，语义去重仅 short 层内查重）；
   `recall_short`（source 精确匹配 + 动态 K + **TTL 惰性过滤**：created_at 超
   `memory_short_ttl_days`=7 天的记忆召回时过滤，无 created_at fail-open 保留）。
3. **会话记忆** — 新增 `session_memory.py`：`save_session_messages`（每消息一条写
   `memory:<identity>:session:`，content_hash 幂等去重，超 `memory_session_max_messages`=50
   滚动删除最旧）；`get_session_messages`（id 升序恢复最近会话）。生成时**优先持久化会话**
   （刷新/换设备不丢），无则用当前请求 history（零回归）。
4. **注入分层** — `_recall_memory` 合并长/短两段：长期"历史记忆"段 + 短期"最近上下文"段，
   格式 `[短期记忆 - 日期]：内容`（`format_memory_line` 新增 label 参数，默认不变）。
5. **接入** — `_persist_memory` 对话结束后同批 facts 沉淀长期 + 短期（fire-and-forget，
   复用 module-033 extract_facts）；chat / chat_stream 在 knowledge 路径异步持久化会话轮次；
   IP_SESSION_MESSAGES 保留为内存兜底缓存。

全量单测 **278 passed / 0 failed**（254 基线 + 24 新增：test_session_memory 11 + test_memory
short 13）。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/session_memory.py | 新增 | 会话记忆持久化（source=`memory:<identity>:session:`，content_hash 幂等 + 上限滚动 + 按身份隔离恢复） |
| ai_service/tests/test_session_memory.py | 新增 | 会话保存/恢复/隔离/上限滚动/幂等 11 项单测 |
| ai_service/src/config.py | 修改 | 新增 memory_short_ttl_days / memory_session_max_messages / memory_session_history_limit |
| ai_service/rag/memory.py | 修改 | 三层 source 分层（_memory_source / _layer_pattern）；长期精确匹配（零回归）；save_short / recall_short（动态 K + TTL 过滤）；format_memory_line label 参数 |
| ai_service/rag/engine.py | 修改 | _recall_memory 合并长/短注入段；_persist_memory 沉淀长期+短期；_resolve_session_history / _schedule_session_persist / _persist_session |
| ai_service/main.py | 修改 | chat / chat_stream 会话持久化接入；chat_stream Step 5 会话恢复；IP_SESSION_MESSAGES 降级为兜底缓存 |
| ai_service/tests/test_memory.py | 修改 | 长期 source_pattern 断言改精确匹配；新增 TestSourceLayering / TestSaveShort / TestRecallShort（含 TTL） |
| ai_service/tests/test_identity.py | 修改 | _recall_memory 身份透传断言补 recall_short |
| ai_service/tests/test_memory_extractor.py | 修改 | _persist_memory/_recall_memory 测试补 save_short/recall_short mock；stream helper 补会话恢复/持久化 mock |
| ai_service/tests/test_stream_memory.py | 修改 | stream helper 补会话恢复/持久化 mock |

## 关键设计说明

### 设计决策 1: 三层 source 精确匹配（长期层由 `:%` 改精确，零回归）
- 决策: 长期 `memory:<id>:` / 短期 `memory:<id>:short:` / 会话 `memory:<id>:session:`。
  长期检索 `recall`/`_find_duplicate`/`_next_title` 的 pattern 由旧 `memory:<id>:%` 改为
  **精确匹配** `memory:<id>:`（`_layer_pattern`）。短/会话 source 均以 `<id>:` 为前缀，
  旧 `:%` 通配会跨层误命中，必须收敛。
- 原因: 既有长期数据 source 恒为精确 `memory:<id>:`，LIKE 无通配 = 等值，精确匹配与旧行为
  完全一致（零回归）；只排除新增层。测试断言同步更新为精确模式。

### 设计决策 2: 短期 TTL 惰性过滤（召回时，不删行）
- 决策: `recall_short` 按 `memory_short_ttl_days`(7 天) 过滤 created_at 早于 cutoff 的记忆；
  无 created_at 的记录 fail-open 保留（无法判断年龄不误删）。不实现定时删除（与长期记忆
  无清理同哲学，plan §3.2 "可选惰性清理"）。
- 原因: 召回过滤是最低成本、无阻塞的过期方式；`'YYYY-MM-DD'` 零填充字典序 = 时间序，直接
  字符串比较。

### 设计决策 3: 会话记忆复用 documents（无新表）+ 幂等 + 上限滚动
- 决策: 每消息一条 Document（无 embedding，仅 source 等值查询 + id 排序恢复）；
  content_hash 幂等去重（重复保存不堆积）；超 `memory_session_max_messages`(50) 按 id 升序
  滚动删除最旧。`get_session_messages` 恢复最近 `memory_session_history_limit`(20) 条。
- 原因: 无新表，与长期记忆同源复用；上限控制防止 documents 表膨胀（plan 风险 #1）。

### 设计决策 4: 会话恢复优先持久化（history 优先持久化，无则当前请求零回归）
- 决策: 生成前 `_resolve_session_history` 先查持久化会话（按 identity），有 → 用它作 history
  （刷新/换设备不丢）；无/失败 → 回退 `request.history`（零回归）。仅注入生成，不改
  `_schedule_persist` 的提取 history（降低耦合）。
- 原因: 每次对话轮次已持久化，持久化历史是完整上下文；回退路径与 module-034 之前行为一致。

### 设计决策 5: 短期摘要复用 extract_facts（不另写 prompt）
- 决策: `_persist_memory` 提取 facts 后同批沉淀长期（save）+ 短期（save_short）；触发点仍是
  既有 `_schedule_persist`（chat）与 `schedule_stream_persist`（chat_stream），main.py 无需
  另接短期生成。
- 原因: 复用 module-033 提取/去重/动态K（plan §3.5 "复用不重复实现"）；facts 即"最近主题/
  结论"，短期层去重防膨胀、TTL 控制过期。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 新增单测 | `python -m pytest tests/test_session_memory.py -q` | 11 passed |
| 记忆分层回归 | `python -m pytest tests/test_memory.py -q` | passed（含 short 新增） |
| 身份回归 | `python -m pytest tests/test_identity.py -q` | 20 passed |
| 提取/流式回归 | `python -m pytest tests/test_memory_extractor.py tests/test_stream_memory.py -q` | 44 passed |
| 全量回归 | `python -m pytest tests/ -q` | **278 passed / 0 failed**（254 基线 + 24 新增） |
| 编译检查 | `python -m py_compile src/config.py rag/memory.py rag/session_memory.py rag/engine.py main.py` | OK |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-06 | 初始实现（三层分层/短期 save+recall+TTL/会话持久化/长短期合并注入 + 24 单测） | Developer(m34-dev) |
