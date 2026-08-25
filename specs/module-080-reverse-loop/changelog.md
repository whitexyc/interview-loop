# 变更日志 — Module-080: 反向闭环（低分题→待学笔记→自动抓取优先级）

## 变更概述
实现 ADR-0019 最后一个验收项「反向闭环」：低分题（feedback rating=-1）沉淀为待学笔记（documents 表 weak_topic:<identity>: 前缀），提取主题关键词，动态提升匹配源的抓取优先级，形成"面试发现弱点→知识库补强"闭环。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/memory/weak_topics.py` | 新增 | 待学笔记核心模块：save_weak_topic / recall_weak_topics / extract_keywords |
| `ai_service/src/database.py` | 修改 | source_configs 表新增 priority 列（幂等 ALTER）+ init_db 挂接 |
| `ai_service/rag/crawl/crawler.py` | 修改 | _load_sources_from_db 返回 priority + _prioritize_sources 动态加权 + run_crawl 入口排序 |
| `ai_service/main.py` | 修改 | 新增 POST /ai/weak-topics/ingest + GET /ai/weak-topics 端点 + crawl sources 支持 priority |
| `ai_service/rag/schemas.py` | 修改 | 新增 WeakTopicIngestRequest 请求体 |
| `ai_service/src/config.py` | 修改 | 新增 weak_topic_priority_boost 配置项（默认 10） |
| `ai_service/rag/memory/__init__.py` | 修改 | re-export weak_topics 模块 |
| `ai_service/tests/memory/test_weak_topics.py` | 新增 | 待学笔记单元测试（15 项） |
| `ai_service/tests/crawl/test_crawl_priority.py` | 新增 | 抓取优先级单元测试（7 项） |

## 关键设计说明

### 设计决策 1: 待学笔记存储选型
- **决策**: 复用 documents 表，source 前缀 `weak_topic:<identity>:`（对齐 memory:<identity>: 三层分层模式）
- **原因**: 零新表，复用已有分块/嵌入/检索/去重全链路，与现有记忆体系同架构

### 设计决策 2: 优先级计算方式
- **决策**: 动态内存态计算（不写回 DB），run_crawl 入口扫描待学笔记关键词 → 子串匹配 url_pattern/name → 动态提升 priority
- **原因**: 每次抓取实时计算，无需维护同步任务；不写回 DB 避免并发问题

### 设计决策 3: 关键词匹配策略
- **决策**: 简单子串匹配（`in` 操作），关键词取待学笔记 title 字段（小写化）
- **原因**: 首版实现简单可靠；后续可升级为 embedding 余弦匹配

### 设计决策 4: 去重机制
- **决策**: 同 identity + 同 topic 不重复新增（更新 context 追加）
- **原因**: 避免重复记录堆积；用户多次录入同一主题时合并上下文

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 编译检查 | `python -m py_compile rag/memory/weak_topics.py` | 无报错 |
| 编译检查 | `python -m py_compile src/database.py` | 无报错 |
| 编译检查 | `python -m py_compile rag/crawl/crawler.py` | 无报错 |
| 编译检查 | `python -m py_compile main.py` | 无报错 |
| 编译检查 | `python -m py_compile src/config.py` | 无报错 |
| 编译检查 | `python -m py_compile rag/schemas.py` | 无报错 |
| 待学笔记测试 | `pytest tests/memory/test_weak_topics.py -q` | 15 passed |
| 抓取优先级测试 | `pytest tests/crawl/test_crawl_priority.py -q` | 7 passed |
| 全量回归 | `pytest tests/ -q` | 1449 passed / 4 failed（基线）/ 3 skipped |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-26 | 初始实现（Developer） | Developer |
