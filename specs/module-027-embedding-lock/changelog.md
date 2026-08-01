# 变更日志 — Module-027: 嵌入并发修复 + backlog 收敛

## 变更概述
修复本地 bge-m3 嵌入（单 Llama 实例）被 `asyncio.to_thread` 并发调用时 llama-cpp 底层非线程安全导致的 GGML_ASSERT 崩溃（module-026 环境观察）。在 `embeddings.py` 引入 `threading.Lock` 串行化模型访问，并收敛 module-022 遗留的空 query 防护（`engine._retrieve` 入口提前返回）。

## 文件变更列表
| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/embeddings.py` | 修改 | `__init__` 加 `threading.Lock`；`_embed_sync` / `_embed_documents_sync` 用锁包住 `_lazy_load` + `create_embedding`；归一化移出锁 |
| `ai_service/rag/engine.py` | 修改 | `_retrieve` 入口空 query 提前返回（不生成缓存 key、不调 HyDE/检索/反思） |
| `ai_service/tests/test_embedding_concurrency.py` | 新增 | 并发 + 边界 + 空 query 防护单测（6 用例） |

## 关键设计说明

### 设计决策 1: threading.Lock 而非 asyncio.Lock
- 决策: `__init__` 加 `self._lock = threading.Lock()`，同步嵌入函数内 `with self._lock:` 包住模型调用
- 原因: `asyncio.to_thread` 在**真线程**中执行同步函数，asyncio.Lock 无法跨线程互斥；threading.Lock 对同一进程所有线程互斥，保证单 Llama 实例访问完全串行，杜绝 GGML_ASSERT 崩溃

### 设计决策 2: 锁同时覆盖 _lazy_load + 模型调用
- 决策: `with` 块内先 `self._lazy_load()` 再 `self._model.create_embedding(...)`
- 原因: `_lazy_load` 本身有"双加载"竞态（两个线程同时看到 `_model is None` 会重复加载 Llama 实例、互相覆盖）；把整个模型访问路径放进锁内才真正串行

### 设计决策 3: 归一化在锁外
- 决策: 单条 `_normalize` 在 `with` 之后；批量先锁内收集原始向量、锁外统一归一化
- 原因: L2 归一化是无状态 numpy 操作，不涉及模型状态，持锁只增加竞争、降低吞吐

### 设计决策 4: 批量内部循环整批持锁
- 决策: `_embed_documents_sync` 整个循环（列表推导）在 `with` 块内
- 原因: 批量连续调用同一 Llama 实例，若循环内放锁会让他线程插队、仍构成并发访问；整批持锁保证该批次对模型访问完全串行

### 设计决策 5: 空 query 防护
- 决策: `engine._retrieve` 入口（Redis 缓存检查之前）对空/空白 query 提前返回 `[]`
- 原因: module-022 遗留——空串的 sha256 cache key 无意义，提前返回避免生成缓存 key、避免无谓的 HyDE / 检索 / 反思调用

## 验证命令
| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| py_compile | `python -c "py_compile..."`（3 个变更文件） | py_compile OK |
| 新增单测 | `cd ai_service && python -m pytest tests/test_embedding_concurrency.py -v` | 6 passed |
| 全量回归 | `cd ai_service && python -m pytest tests/ -q` | 120 passed，2 个既有 async 技术债务失败（test_engine.py 缺 pytest-asyncio，module-018 已记录，非本次回归） |
| 真实 16 路并发 embed_text | `python -c "..."`（plan §4.1） | `16 路并发嵌入成功: 16 条, 均 1024 维`，不崩 |
| 真实 8 路并发 embed_documents | `python -c "..."`（plan §4.1） | `8 路并发批量成功: 8 批, 每批 2 条, 均 1024 维`，不崩 |

## 变更记录
| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始实现（threading.Lock + 空 query 防护 + 单测） | Developer |
