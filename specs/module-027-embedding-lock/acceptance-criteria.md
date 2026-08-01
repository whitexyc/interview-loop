# 验收标准 — Module-027: 嵌入并发修复 + backlog 收敛

> 本文件由 **Planner** 在输出开发计划时同步编写，由 **Tester** 在测试阶段执行验收。
> 所有检查项使用 `- [ ]` 复选框格式，验收时勾选。

---

## 验收元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-027 |
| 模块名称 | 嵌入并发修复 + backlog 收敛 |
| 关联 plan.md | `specs/module-027-embedding-lock/plan.md` |
| 验收日期 | 2026-08-02 |
| 验收人 | Tester |
| 验收版本 | 0.27.0-module-027 |

---

## 1. 功能验收

### 1.1 核心功能验收

- [x] 📋 并发嵌入安全 — 验证方式：16 路并发 embed_text 不崩溃，结果正确
- [x] 📋 并发批量安全 — 验证方式：8 路并发 embed_documents 不崩溃
- [x] 📋 锁覆盖模型调用 — 验证方式：所有 create_embedding 调用持锁
- [x] 📋 归一化在锁外 — 验证方式：锁只包模型调用（性能）

### 1.2 边界条件验收

- [x] 🔲 空文本嵌入：抛 EmbeddingException
- [x] 🔲 空列表批量：返回空列表
- [x] 🔲 空 query 防护（module-022 遗留）：_retrieve 空 query 不生成缓存 key

### 1.3 异常场景验收

- [x] ⚡ 模型调用失败：锁释放正常（with 语句）
- [x] ⚡ 并发下崩溃：不再 GGML_ASSERT

---

## 2. 接口验收

### 2.1 嵌入接口

- [x] 📦 `embed_text(text) -> list[float]` 签名不变
- [x] 📦 `embed_documents(texts) -> list[list[float]]` 签名不变
- [x] 📦 返回维度仍 1024

### 2.2 并发

- [x] 📦 threading.Lock 正确使用（非 asyncio.Lock）
- [x] 📦 批量内部循环持锁

---

## 3. 代码质量验收

### 3.1 注释覆盖率

- [x] 💻 锁逻辑有行内注释（说明为何 threading.Lock）

### 3.2 命名规范

- [x] 💻 变量符合 snake_case

### 3.3 代码长度

- [x] 💻 单个方法 ≤ 50 行
- [x] 💻 本模块新增代码 ≤ 150 行

### 3.4 编译检查

- [x] 💻 Python 语法通过
- [x] 💻 无未使用 import

---

## 4. 测试验收

### 4.1 单元测试

- [x] 🧪 并发嵌入测试（16 路）
- [x] 🧪 并发批量测试（8 路）
- [x] 🧪 空输入边界

### 4.2 集成测试

- [x] 🧪 真实模型并发嵌入
- [x] 🧪 空 query 防护

### 4.3 回归测试

- [x] 🧪 `python -m pytest ai_service/tests/ -x` 无新增失败
- [x] 🧪 检索链路无回归

### 4.4 测试命令

```bash
cd ai_service
# 并发嵌入
python -c "
import asyncio
from rag.embeddings import embedding_service
async def test():
    tasks = [embedding_service.embed_text(f'测试文本{i}') for i in range(16)]
    results = await asyncio.gather(*tasks)
    assert all(len(r) == 1024 for r in results)
    print(f'16 路并发嵌入成功: {len(results)} 条')
asyncio.run(test())"

# 回归
python -m pytest ai_service/tests/ -x
```

**预期输出**：
```
16 路并发嵌入成功: 16 条
===== 0 failed, N passed =====
```

---

## 5. 文档验收

### 5.1 变更记录

- [x] 📝 changelog.md 已更新
- [x] 📝 包含版本号/日期/变更内容/变更人

### 5.2 设计说明

- [x] 📝 锁方案（threading.Lock）记录在 plan.md

---

## 验收执行结果

### 分项统计

| 验收类别 | 总项数 | 通过 | 失败 | 未执行 |
|----------|--------|------|------|--------|
| 功能验收 | 9 | 9 | 0 | 0 |
| 接口验收 | 5 | 5 | 0 | 0 |
| 代码质量验收 | 6 | 6 | 0 | 0 |
| 测试验收 | 7 | 7 | 0 | 0 |
| 文档验收 | 3 | 3 | 0 | 0 |
| **合计** | **30** | **30** | **0** | **0** |

### 失败详情

| 序号 | 类别 | 失败项 | 失败原因 | 建议修复方式 |
|------|------|--------|----------|--------------|
| — | — | 无失败项 | — | — |

> 注：全量回归 2 个失败用例为既有 async 技术债务（`tests/test_engine.py` 缺 pytest-asyncio，
> module-018 已记录），与 module-027 无关，不计入本模块失败项。

### 验收结论

- 审查人: Reviewer
- 测试人: Tester
- 验收时间: 2026-08-02
- 结论:
  - [x] ✅ **通过**
  - [ ] ❌ **不通过**
  - [ ] ⚠️ **有条件通过**
- 备注: 本模块新增单测 6/6 通过；真实 bge-m3 模型 16 路并发 embed_text / 8 路并发 embed_documents 均不崩溃、结果 1024 维；空 query 防护真实引擎验证 0 次缓存调用；全量回归 120 passed / 2 既有 async 技术债务失败（无新增失败）。详细见 `test-report.md`。

---

> **下一步**：
> - 通过：更新 `memory/project-context.md`，模块标记 ✅
> - 不通过：通知 Developer 修复后重新验收
