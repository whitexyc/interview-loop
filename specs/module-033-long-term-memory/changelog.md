# 变更日志 — Module-033: 长期记忆自动写入

## 变更概述

对话结束后自动从 (query, answer, history) 提取值得长期记住的事实沉淀为长期记忆：
新增 LLM 事实提取器（extract_facts，importance 过滤 + 失败降级）；save 写入前语义去重
（与本身份现有记忆嵌入 cosine>0.95 视为重复 → 更新旧父块而非新增，库内条数不涨）；
recall 动态 K 召回（候选平均相似度 >0.85→5 / 0.75-0.85→3 / <0.75→1，宁缺毋滥）；
召回记忆格式化注入 '[长期记忆 - 日期]：内容'；chat / chat_stream 在 knowledge 路径
生成答案后以 fire-and-forget（asyncio.create_task）异步触发写入，不阻塞响应；
闲聊/实时路径跳过。全量单测 254 通过（215 基线 + 新增 39），0 失败。

## 文件变更列表

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/rag/memory_extractor.py | 新增 | 对话→值得记住事实的 LLM 提取器（结构化 JSON + importance 过滤 + 失败/超时降级 []） |
| ai_service/tests/test_memory_extractor.py | 新增 | 提取器/去重/动态K/格式化/触发链路 39 项单测 |
| ai_service/src/config.py | 修改 | 记忆阈值配置（去重 0.95 / 动态K 0.85/0.75 / importance 0.6 / 最大K 5） |
| ai_service/rag/memory.py | 修改 | save 语义去重（dedup=True）；recall 动态 K；_expand_to_parents 增加 created_at；新增 format_memory_line / _find_duplicate / _merge_duplicate / _dynamic_k |
| ai_service/rag/engine.py | 修改 | 新增 _persist_memory / _schedule_persist；_recall_memory 格式化注入新格式；chat knowledge 路径触发 |
| ai_service/main.py | 修改 | chat_stream 生成后异步触发（accumulate token 拼答案）；新增 schedule_stream_persist |
| ai_service/tests/test_memory.py | 修改 | recall 断言补 created_at 字段（契约新增字段） |
| ai_service/tests/test_stream_memory.py | 修改 | mock 后台 _persist_memory（避免真实 LLM 提取） |

## 关键设计说明

### 设计决策 1: 语义去重 = 更新旧父块（追加合并），而非新增行
- 决策: save(dedup=True) 写入前 `_find_duplicate` 查询本身份现有记忆子块嵌入，
  与新事实嵌入（均已 L2 归一化，cosine=点积）逐一比对，最高相似度 >
  settings.memory_dedup_threshold(0.95) → `_merge_duplicate` 把新内容追加到既有父块
  content，返回 status="updated"，不新增任何行（库内条数不涨）。
- 原因: 与 llm-push/19-Agent记忆管理 参考方案一致；去重检索/嵌入/更新任何异常
  都降级为正常新增（不阻塞，零回归）。手动 save 默认也去重（统一防重复事实堆积）。

### 设计决策 2: 动态 K 召回（宁缺毋滥）
- 决策: recall 先取 top_k=5 候选，按候选平均 hybrid_score 动态调整最终召回条数
  （>0.85→5 / 0.75-0.85→3 / <0.75→1）；空候选直接返回空列表。条数上限受
  settings.memory_max_recall 控制。
- 原因: 候选质量越高说明与 query 越相关，多召回几条；越低只保留最相关一条，
  避免低质量记忆稀释生成 prompt。阈值可配置（acceptance §2.2）。

### 设计决策 3: 格式化注入 '[长期记忆 - 日期]：内容'
- 决策: recall 每条结果新增 created_at（'YYYY-MM-DD'，取自父块创建时间），
  memory.py 的 `format_memory_line` 生成 '[长期记忆 - 日期]：内容'（无 created_at
  省略日期）；engine._recall_memory 拼接注入 prompt。recall 返回结构保持 list[dict]
  不变（跨模块契约），仅新增 created_at 字段。
- 原因: 带日期前缀帮助模型区分历史记忆与当前对话；无日期时优雅省略（acceptance §1.4）。

### 设计决策 4: fire-and-forget 异步不阻塞响应
- 决策: chat 在 knowledge 两个 return 点（无结果直接 LLM / 正常生成）调
  `_schedule_persist` → asyncio.create_task 后台执行 `_persist_memory`（不 await）；
  chat_stream 在 SSE done 前 accumulate token 拼出完整答案后触发。
  `_persist_memory` 内部全量 try/except，提取失败/超时 → 空 facts 不写、单条 save
  失败仅日志降级，绝不抛回响应。casual_chat / realtime 在分支提前返回不触发。
- 原因: 记忆写入是后台动作，不应增加对话延迟（acceptance §1.5 / §2.4 非功能需求）。

### 设计决策 5: 提取只对 knowledge 路径
- 决策: 触发条件 = intent==knowledge 且 answer 非空；闲聊/实时不提取。
- 原因: 省 LLM 成本、避免把一次性闲聊沉淀为"长期记忆"垃圾（plan §3.3）。

## 验证命令

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 新增单测 | `python -m pytest tests/test_memory_extractor.py -q` | 39 passed |
| 记忆/身份/流式回归 | `python -m pytest tests/test_memory.py tests/test_identity.py tests/test_stream_memory.py -q` | 54 passed |
| 全量回归 | `python -m pytest tests/ -q` | 254 passed / 0 failed（215 基线 + 39 新增） |
| 编译检查 | `python -m py_compile src/config.py rag/memory.py rag/memory_extractor.py rag/engine.py main.py` | OK |

## 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-05 | 初始实现（提取器/去重/动态K/格式化/异步接入 + 39 单测） | Developer |
