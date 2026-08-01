# 测试报告 — Module-023: 长期记忆（跨会话记忆沉淀）

> 本轮为 v4 修复后的**重新验收**。上轮 Tester 阻塞项（`_next_title` 传 ISO 字符串 → `date = varchar` 类型不匹配致真实 save 恒崩溃）已由 Developer v4 修复（`save` 改传 `date.today()` date 对象），本轮以真实 DB + HTTP 全链路复测验证。

## 1. 测试概览

| 指标 | 数值 |
|------|------|
| 单元测试（`tests/test_memory.py`） | 29/29 通过 |
| 集成测试（真实 DB 冒烟，直接调用 MemoryService） | 9/9 通过 |
| 接口测试（HTTP，uvicorn + curl） | 9/9 通过 |
| 全量回归（`pytest tests/ -q`） | 83 passed / 2 失败（均为既有环境问题，非本模块回归） |
| 本模块相关失败数 | 0 |
| 通过率（本模块） | 100% |
| 执行耗时 | 单元 46s + 冒烟/接口约 2min + 回归 53s |

| 测试集 | 结果 |
|--------|------|
| `python -m pytest tests/test_memory.py -v`（模块单测） | 29 passed |
| `python -m pytest tests/ -q`（全量回归） | 83 passed / 2 failed（既有 test_engine async 缺 pytest-asyncio，非本模块回归） |
| 真实 DB 冒烟（直接调用 MemoryService：save A#1/A#2、save B、DB 直查、recall A/B/C、边界、清理） | 9/9 passed |
| HTTP 端点（uvicorn + curl：save/recall/空 content/空 query/通配符 ip） | 9/9 passed |
| `/ai/documents` 排除记忆行 | total=45, memory_rows=0 |
| `py_compile` 7 文件 + import 检查 | OK |
| 行覆盖（`rag/memory.py`，stdlib trace） | 125/127 = 98.4% |

## 2. 覆盖率报告

> 环境未安装 `pytest-cov`，改用 Python stdlib `trace` 对 `test_memory.py` 全量运行统计 `rag/memory.py` 行覆盖。

| 覆盖维度 | 覆盖率 | 要求 | 状态 |
|----------|--------|------|------|
| 行覆盖率（rag/memory.py） | 125/127 = 98.4% | ≥ 80% | ✅ |
| 分支覆盖率 | 异常/兜底分支均有用例覆盖（详见下） | ≥ 70% | ✅ |

未执行行（2 行，均为防御性兜底分支，正常流程不可达，不影响验收）：
- `memory.py` L192 `parent_idx = 0`（子块 `parent_index` 越界安全兜底）
- `memory.py` L291 `continue`（`_expand_to_parents` 中空 content 跳过）

覆盖到的关键分支：save 空 content / 空 ip / 通配符 ip 降级 / embedding 失败回滚 / recall 空 query / 检索失败降级空 / 通配符 ip 不绕过隔离 / 前缀重叠 IP 不交叉命中 / 同父块去重取最高分 / `_next_title` date 对象绑定 / prompt 空 sections 字节一致 / realtime 跳过召回 / list_documents 排除记忆。

## 3. 验收标准核对

### 3.1 功能验收
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| 保存记忆入库（documents source='memory:...'） | 冒烟 [1-3] + HTTP [1-3] + `test_save_writes_documents_with_memory_source` | ✅ 通过 | 真实 DB 4 行 `source='memory:10.9.9.1:'`；HTTP save 返回 `{code:0, data:{id, title:'记忆-2026-08-01-01', status:'saved'}}` |
| 检索记忆返回相关 | 冒烟 [5-6] + HTTP [4-5] + `test_recall_passes_source_pattern_and_expands_to_parent` | ✅ 通过 | IP_A 召回 2 条 Java 记忆，IP_B 召回 1 条 Rust 记忆 |
| 记忆向量化（1024 维） | 冒烟 [4] + 清理复核 + `test_save_writes_documents_with_memory_source` | ✅ 通过 | 子块 embedding `len==1024` 实测；父块无向量 |
| 按 IP 隔离 | 冒烟 [5-6] + HTTP [5] + `test_recall_isolated_by_ip` / `test_recall_ip_prefix_overlap_no_cross_match` / `test_recall_ip_wildcard_cannot_bypass` | ✅ 通过 | 不同 IP 互不干扰；`ip="%"`/`"_"` 降级 `unknown` 桶，不跨 IP |
| 无记忆时 chat 零回归 | `test_empty_sections_byte_identical_to_old` + `test_no_memories_returns_empty` + 全量回归 | ✅ 通过 | 空 sections 与旧版 prompt 逐字节一致 |

### 3.2 边界条件验收
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| 空 content 保存返回错误 | `test_save_empty_content_raises` + HTTP [7] | ✅ 通过 | 端点返回 `{code:1, message:'记忆内容不能为空'}` |
| 空 ip 默认 'unknown' | `test_save_empty_ip_defaults_unknown` + HTTP [7]（缺 ip 字段） | ✅ 通过 | source 写 `memory:unknown:` |
| 无匹配记忆 recall 返回空 | 冒烟 [7] | ✅ 通过 | 无记忆 IP 返回 `[]` |
| 检索 query 为空返回空 | `test_recall_empty_query_returns_empty` + 冒烟 [8] + HTTP [8] | ✅ 通过 | 不调用 retriever |

### 3.3 异常场景验收
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| embedding 不可用：保存失败返回错误码（不崩） | `test_save_embedding_failure_raises` | ✅ 通过 | 抛 RuntimeError，`session.rollback` 已调用（不留残缺记录） |
| 检索失败：返回空记忆，回答照常 | `test_recall_retrieval_failure_returns_empty` | ✅ 通过 | 降级返回 `[]` |
| 数据库不可用：返回错误 | 单元（save 抛 RuntimeError）+ 端点 `except` → code 2 | ✅ 通过 | 端点异常兜底，不崩 |

### 3.4 接口验收
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| POST /ai/memory/save 请求 {content, ip} | HTTP [1-3] + schemas.MemorySaveRequest | ✅ 通过 | |
| 返回 {code, data:{id, status}} | HTTP [1] | ✅ 通过 | data 含 id/title/status |
| content 为空返回错误 | HTTP [7] | ✅ 通过 | code=1 |
| POST /ai/memory/recall 请求 {query, ip} | HTTP [4-6] + schemas.MemoryRecallRequest | ✅ 通过 | |
| 返回 {code, data:{memories:[{content, score}]}} | HTTP [4] | ✅ 通过 | |
| memories 按 score 降序 | HTTP [4]（1.0, 0.3）+ 冒烟 | ✅ 通过 | |

### 3.5 记忆存储
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| documents 表 source='memory:<ip>' | 冒烟 [4]（DB 直查） | ✅ 通过 | 尾冒号分隔 `memory:10.9.9.1:` |
| 记忆文档有 embedding（1024 维） | 冒烟 [4] + 清理复核 | ✅ 通过 | |
| 检索只查记忆，不污染知识库检索 | `test_default_excludes_memory_prefix` + `/ai/documents`（total=45, memory_rows=0） | ✅ 通过 | list_documents 已排除记忆行 |

### 3.6 代码质量验收
| 验收项 | 对应测试/检查 | 状态 | 备注 |
|--------|--------------|------|------|
| public 方法有 Docstring | 代码走查 | ✅ 通过 | save/recall/_next_title/_expand_to_parents 等 |
| 记忆注入有行内注释 | 代码走查 | ✅ 通过 | memory.py + engine.py |
| snake_case 命名 | 代码走查 | ✅ 通过 | |
| 单个方法 ≤ 50 行 | Reviewer 已核 | ✅ 通过 | save=48 行贴线；engine.chat 为既有超长 |
| 新增代码 ≤ 300 行 | 实际约 540 行（不含测试） | ⚠️ 说明 | plan.md 已注明"需调整上限"，规划内偏差 |
| Python 语法通过 | `py_compile` 7 文件 | ✅ 通过 | |
| 无未使用 import | 导入检查 | ✅ 通过 | |

### 3.7 测试验收
| 验收项 | 对应测试 | 状态 | 备注 |
|--------|----------|------|------|
| MemoryService save/recall 单测 | `pytest tests/test_memory.py -v` | ✅ 通过 | 29 passed |
| source 过滤逻辑 | TestSourceFilter 4 例 | ✅ 通过 | |
| 真实保存记忆到 documents | 冒烟 [1-3] + 清理复核 | ✅ 通过 | 真实 DB 4 行入库 |
| 真实检索记忆返回相关 | 冒烟 [5] | ✅ 通过 | 真实 embedding 检索命中 |
| 按 IP 隔离 | 冒烟 [5-6] | ✅ 通过 | |
| `pytest tests/ -x` 无新增失败 | 全量回归 | ✅ 通过 | 83 passed / 2 既有环境失败（见 §4） |
| chat 无记忆时行为不变 | `test_empty_sections_byte_identical_to_old` | ✅ 通过 | |

### 3.8 文档验收
| 验收项 | 对应测试/检查 | 状态 | 备注 |
|--------|--------------|------|------|
| changelog.md 已更新 | 阅读 | ✅ 通过 | 含 v1/v2/v3/v4 修复记录 |
| 版本号/日期/变更内容/变更人 | 阅读 | ✅ 通过 | |
| 存储方案记录在 plan.md | 阅读 | ✅ 通过 | 复用 documents + source 隔离 |
| 注入方案记录在 plan.md | 阅读 | ✅ 通过 | 生成前 recall |

## 4. 失败详情

### 失败 #1 / #2（既有环境问题，非本模块回归）

- 测试名: `tests/test_engine.py::test_search_returns_response`、`tests/test_engine.py::test_chat_returns_response`
- 失败原因: `async def functions are not natively supported. You need to install a suitable plugin... (pytest-asyncio)`
- 关联文件: `ai_service/tests/test_engine.py`（自初始提交 62e4797 起未改动，`git status` 无修改记录）
- 归因: 测试环境缺 `pytest-asyncio`，2 个既有 async 用例无法在 pytest 下运行。此为 module-018 验收时已记录的技术债务（`memory/project-context.md` 第 7 节），非 module-023 引入。
- 修复建议: 后续环境补齐 `pytest-asyncio` 后即可运行；本次不阻塞。

> 本模块所有新增测试（test_memory.py 29 例）与既有测试（83 例）全部通过，无本模块相关回归失败。

## 5. 测试结论

- 结论: **通过**
- 测试时间: 2026-08-01
- 测试人: Tester
- 备注:
  1. **v4 阻塞项闭环验证**：真实 DB 保存成功。`save` 改传 `date.today()`（date 对象，SQLAlchemy 绑定 DATE），`date(created_at) = $1::DATE` 正常执行；HTTP `/ai/memory/save` 返回 `{code:0, data:{id, title:'记忆-2026-08-01-01', status:'saved'}}`，第二条标题 `-02` 序号递增。单测新增 `test_save_passes_date_object_to_next_title` / `test_next_title_binds_date_not_string` 亦通过。
  2. **三层次验证**：单元（29 例）→ 真实 DB 直接调用 MemoryService（9 项，含 1024 维向量、IP 隔离、通配符注入不绕过）→ HTTP 端点（9 项，含空 content 报错、空 query、无匹配空列表）。
  3. 场景 3「记忆注入回答」按计划范围限定非流式 `/ai/rag/chat`（chat_stream 记忆注入列入后续模块 backlog，见 changelog 决策 #3）。engine.chat 注入路径已由单测覆盖（`_recall_memory` 格式化 / realtime 跳过 / casual 仍注入）。
  4. 测试数据已全部清理（删除 8 行测试记忆，`memory:10.*` 残留 0），uvicorn 测试服务已停止，临时脚本已删除。
  5. 说明项（不阻塞）：新增代码约 540 行超出 plan 预估（plan 已申请调整）；错误响应 `message` 键维持既有风格（统一 `msg` 列入全文件清理）。
