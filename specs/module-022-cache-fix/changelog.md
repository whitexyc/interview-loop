# 变更日志 — Module-022: 检索缓存修复

## 变更概述
修复检索缓存两个正确性缺陷：① cache_key 只含 query hash 不含检索参数，不同 top_k/min_score 复用错误结果；② 文档增删后缓存不失效，脏缓存持续返回旧数据。改动集中在缓存 key 参数化、Redis 前缀失效（SCAN + DEL）、add/delete 后全量失效三处，cache.get/set 接口保持不变，失效失败降级不影响检索正确性。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| ai_service/src/cache.py | 修改 | 新增 `delete_by_prefix(prefix) -> bool`（SCAN 分批 + DEL，失败降级返回 False）；模块 docstring 设计注记同步更新为 16 位 hash |
| ai_service/rag/engine.py | 修改 | 提取纯函数 `_retrieve_cache_key()`（hash 纳入 top_k + min_score，16 位）；`_retrieve` 改用新 key；`add_document` 入库成功后全量失效 |
| ai_service/main.py | 修改 | `delete_document` 成功后全量失效（新增 `src.cache` import） |
| ai_service/tests/test_cache.py | 新增 | cache_key 参数化单测 + 真实 Redis delete_by_prefix 集成测试 + add/delete 失效接线测试（8 用例） |

## 关键设计说明

### 设计决策 1: cache_key 纳入 top_k/min_score（参数化）
- 决策: `rag:retrieve:{sha256(query + str(top_k) + str(min_score))[:16]}`，替换旧格式 `{sha256(query)[:12]}`
- 原因: 检索结果依赖 top_k（候选数）与 min_score（低分阈值），不同参数必须生成不同 key，否则复用错误结果污染评估与用户体验。前缀 `rag:retrieve:` 保持不变以兼容前缀失效
- 实现: 提取为模块级纯函数 `_retrieve_cache_key`，便于单元测试（不依赖 DB/LLM 端到端链路）

### 设计决策 2: 文档变更全量失效（简单正确）
- 决策: `add_document`/`delete_document` 数据变更成功后调用 `cache.delete_by_prefix("rag:retrieve:")` 清空全部检索缓存
- 原因: 任何文档增删都会改变所有查询的候选集，按前缀全清最简单且正确；文档变更频率低，缓存命中率影响可忽略

### 设计决策 3: SCAN 而非 KEYS
- 决策: `delete_by_prefix` 用 Redis `SCAN cursor` 分批（count=100）+ `DEL` 逐个删除，游标归零结束
- 原因: 避免大 key 空间下 `KEYS *` 阻塞 Redis 主线程

### 设计决策 4: 失效失败降级
- 决策: `delete_by_prefix` 所有异常 catch，记录 warning 并返回 False，不抛出；Redis 不可用时短路返回 False
- 原因: 缓存是可选的优化层，失效失败只影响新鲜度（最坏返回旧缓存），不影响检索正确性；与 cache.get/set 既有降级模式一致

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| 语法检查 | `python -m py_compile src/cache.py rag/engine.py main.py tests/test_cache.py` | 无输出，退出码 0 |
| cache_key 单测 | `python -m pytest tests/test_cache.py -q` | `8 passed` |
| delete_by_prefix（plan 验收脚本） | `python -c "..."`（plan.md §4.1） | `delete_by_prefix: True` / `清除后: None None` |
| cache_key 参数化（plan 验收脚本） | `python -c "..."`（acceptance §4.4） | `cache_key 参数化 OK` |
| 全量回归 | `python -m pytest tests/ -q` | `54 passed, 2 failed`（2 个失败为 test_engine.py 既有 async 用例缺 pytest-asyncio，module-018 已记录的技术债务，非本次回归） |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始实现：cache_key 参数化 + delete_by_prefix + add/delete 失效 + 测试 | Developer |
