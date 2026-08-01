# 功能规格说明书 — Module-027: 嵌入并发修复 + backlog 收敛

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-027 |
| 模块名称 | 嵌入并发修复 + backlog 收敛 |
| 版本号 | 0.27.0-module-027 |
| 优先级 | P1 |
| 预估代码量 | ≤ 150 行 |
| 创建日期 | 2026-08-02 |
| 最后更新 | 2026-08-02 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-026 环境观察 + backlog 确认
- 原始描述：本地 bge-m3 嵌入模型（单 Llama 实例）被 `asyncio.to_thread` 并发调用时，llama-cpp 底层非线程安全 → GGML_ASSERT 崩溃（module-026 Tester 记录）。

### 2.2 用户故事

```
作为 RAG 系统开发者
我想要 本地嵌入模型并发安全
以便 高并发下不会 GGML_ASSERT 崩溃，检索稳定
```

### 2.3 验收场景（BDD 格式）

```
场景 1：并发嵌入安全
  假设 多个请求并发调用 embed_text
  当 同时嵌入
  那么 不崩溃，结果正确

场景 2：批量嵌入安全
  假设 并发调用 embed_documents
  当 同时批量嵌入
  那么 不崩溃，各批次结果正确

场景 3：空 query 防护（module-022 遗留）
  假设 传入空 query
  当 _retrieve 处理
  那么 不生成缓存 key，安全返回
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | embed_text / embed_documents 接口不变 |
| 并发 | 多线程安全（llama-cpp 非线程安全需串行化） |
| 性能 | 锁开销低（嵌入是 I/O 密集，锁竞争可接受） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/embeddings.py` | 修改 | 加互斥锁串行化 Llama 访问 |

### 3.2 业务逻辑说明

#### 核心流程（embeddings.py 改造）

```
问题: _embed_sync / _embed_documents_sync 直接调用 self._model.create_embedding
      被 asyncio.to_thread 并发调用 → llama-cpp 非线程安全 → GGML_ASSERT 崩溃

方案: threading.Lock 互斥锁
  1. __init__ 加 self._lock = threading.Lock()
  2. _embed_sync 和 _embed_documents_sync 内：
     with self._lock:
         resp = self._model.create_embedding(...)
  3. 锁只保护模型调用（Llama 实例），归一化在锁外（无状态）

说明:
  - threading.Lock 而非 asyncio.Lock：因为 to_thread 在真线程中执行
  - 锁粒度是整个模型调用（create_embedding），保证单实例串行
  - 批量嵌入内部循环也需持锁（连续调用同一实例）
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| threading.Lock | to_thread 是真线程，asyncio.Lock 无法跨线程 |
| 锁覆盖整个模型调用 | 单 Llama 实例完全串行，杜绝并发访问 |
| 归一化在锁外 | 无状态操作，不持锁减少竞争 |
| 空 query 防护 | _retrieve 入口对空 query 提前返回（module-022 遗留） |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 锁获取失败 | Exception | 由 EmbeddingException 包装（现有） |
| 嵌入崩溃 | GGML_ASSERT | 锁后不再发生；若仍发生记 ERROR |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 并发嵌入安全测试
python -c "
import asyncio
from rag.embeddings import embedding_service
async def test():
    # 并发 16 路 embed_text
    tasks = [embedding_service.embed_text(f'测试文本{i}') for i in range(16)]
    results = await asyncio.gather(*tasks)
    assert all(len(r) == 1024 for r in results)
    print(f'16 路并发嵌入成功: {len(results)} 条, 均 {len(results[0])} 维')
asyncio.run(test())"

# 2. 批量并发
python -c "
import asyncio
from rag.embeddings import embedding_service
async def test():
    tasks = [embedding_service.embed_documents([f'doc{i}-a', f'doc{i}-b']) for i in range(8)]
    results = await asyncio.gather(*tasks)
    print(f'8 路并发批量成功: {len(results)} 批')
asyncio.run(test())"

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
16 路并发嵌入成功: 16 条, 均 1024 维
8 路并发批量成功: 8 批
===== 0 failed, N passed =====
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 仍 GGML_ASSERT | 锁未覆盖全部调用 | 检查所有 create_embedding 调用是否持锁 |
| 死锁 | 锁嵌套 | 检查锁范围（只包模型调用） |
| 并发慢 | 锁竞争 | 确认是否必要（嵌入本身 I/O 密集） |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-020 | 本地 bge-m3 GGUF | ✅ |

### 5.2 下游依赖

无（独立修复）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 锁串行化损失并发 | 嵌入吞吐降 | 中 | 嵌入单请求毫秒级，可接受；必要时可多实例 |
| 锁范围过宽 | 不必要竞争 | 低 | 只包模型调用，归一化在外 |

### 6.2 技术注意事项

- [x] threading.Lock 而非 asyncio.Lock（to_thread 真线程）
- [x] 锁覆盖批量内部循环
- [x] 归一化在锁外

### 6.3 开发建议

- 优先实现锁 + 并发测试
- 顺带处理空 query 防护（module-022 遗留）

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-02 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-02 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
