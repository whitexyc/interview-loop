# 功能规格说明书 — Module-026: 并发修复 + Reflector 改造

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-026 |
| 模块名称 | 检索并发修复 + Reflector 改造（低温度 + 走降级链） |
| 版本号 | 0.26.0-module-026 |
| 优先级 | P1 |
| 预估代码量 | ≤ 200 行 |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-024 环境观察 + 用户 backlog 确认
- 原始描述：
  ① 检索并发竞态：`retriever._execute` 在单 asyncpg 连接上并发跑 FTS+向量，偶发 `concurrent operations are not permitted`，冷缓存结果不稳定（0 vs 2 篇）。
  ② Reflector 改造：反思用硬编码 deepseek（temperature=0.7 与生成同温，JSON 稳定性欠佳）+ 不走降级链（单点）。

### 2.2 用户故事

```
作为 RAG 系统开发者
我想要 ① 检索结果稳定（并发竞态消除）
      ② 反思温度更低（JSON 稳定）且走降级链（消除单点）
以便 检索可复现、反思可靠、LLM 故障可降级
```

### 2.3 验收场景（BDD 格式）

```
场景 1：并发竞态消除
  假设 冷缓存混合检索
  当 FTS 和向量并行执行
  那么 不再报 concurrent operations（结果稳定）

场景 2：反思低温度
  假设 反思检查
  当 LLM 生成判断
  那么 用 temperature=0.1（JSON 更稳定）

场景 3：Reflector 走降级链
  假设 deepseek 不可用
  当 Reflector 调用
  那么 降级到 qwen/zhipu（不单点）

场景 4：生成保持 0.7
  假设 生成回答
  当 LLM 生成
  那么 temperature 仍为 0.7（创造性不变）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | _execute / Reflector 接口不变 |
| 并行性能 | 独立 session 保留并行（不串行化） |
| 零回归 | 检索质量/生成行为不下降 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/retriever.py` | 修改 | _execute 两路独立 session |
| `ai_service/llm/client.py` | 修改 | LLMFactory 支持低温度创建（或新增方法） |
| `ai_service/agent/reflector.py` | 修改 | 反思用低温度客户端 + 走降级链 |

### 3.2 业务逻辑说明

#### 并发修复（retriever._execute）

```
问题: gather 在单 session 上并发跑 FTS + 向量 → asyncpg 单连接 concurrent ops 限制

方案 A（独立 session）:
  fts_task = self._fts_search(query, fetch_k, session_a)      # 独立连接
  vector_task = self._vector_search(query_embedding, fetch_k, session_b)  # 独立连接
  gather(fts_task, vector_task, return_exceptions=True)
  - 保留并行性能
  - 每路独立连接，避免并发冲突

实现: _execute 内部为两路各建 session（或用 async_session_factory 各开）
     保留传入 session 的兼容（外部 session 时串行或用其子连接）
```

#### Reflector 改造

```
1. 低温度反思:
   现状: Reflector 用 DeepSeekClient（temperature=0.7）
   新:  反思用 temperature=0.1 的 DeepSeek 客户端
   - LLMFactory 新增支持: get_client(provider, temperature=0.1)
   - 或新增 get_reflection_client() 返回低温度 DeepSeek 实例

2. 消除硬编码 deepseek:
   现状: self._provider = provider or "deepseek"（硬编码，不走降级链）
   新:   self._provider = provider or "fallback"（走降级链 deepseek→qwen→zhipu）
   - 降级链第一个是 deepseek（默认优先），行为基本不变
   - deepseek 挂时自动降级 qwen/zhipu（消除单点）
   - 但反思要求低温度：需确保 fallback 链各供应商也用低温度
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 并发用独立 session | 保留并行性能，避免串行化损失 |
| 反思温度 0.1 | 结构化 JSON 任务需确定性 |
| Reflector 走 fallback | 降级链 deepseek 优先，消除单点 |
| 低温度贯穿降级链 | fallback 各供应商反思都用 0.1 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 独立 session 创建失败 | Exception | 降级为共用原 session（串行） |
| 低温度客户端构造失败 | Exception | 回退默认温度 |
| 降级链全失败 | LLMException | Reflector 现有 fallback（sufficient=true） |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 并发检索稳定性测试（多次冷缓存检索，结果一致）
python -c "
import asyncio
from rag.retriever import hybrid_retriever
async def test():
    for i in range(5):
        docs = await hybrid_retriever.retrieve('Java线程池', top_k=3)
        print(f'第{i+1}次: {len(docs)} 篇')
asyncio.run(test())"

# 2. Reflector 温度验证
python -c "
from agent.reflector import reflector
print('provider:', reflector._provider)
from llm.client import LLMFactory
client = LLMFactory.get_client(reflector._provider)
print('温度:', client._llm.temperature)"

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
# 并发: 5 次结果一致（不出现 0 篇偶发）
第1次: 3 篇
第2次: 3 篇
...（稳定）

# Reflector: provider=fallback, 温度=0.1

# 回归: 0 failed
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 并发仍报错 | session 未真正隔离 | 检查 _execute 两路 session |
| 温度未变 | 客户端未用低温度 | 检查 LLMFactory 低温度创建 |
| Reflector 仍硬编码 | provider 未改 | 检查 reflector._provider |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-005 | retriever / reflector | ✅ |
| module-018 | LLM 降级链 | ✅ |

### 5.2 下游依赖

无（独立修复）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 独立 session 连接数翻倍 | 连接池压力 | 低 | 池默认 5，够用 |
| 反思低温度影响改写 | rewritten 变保守 | 低 | 0.1 仍允许推理 |

### 6.2 技术注意事项

- [x] 并发保留并行（不串行化）
- [x] 反思低温度仅影响反思，生成仍 0.7
- [x] Reflector 走 fallback 链（deepseek 优先）
- [ ] 需验证 LLMFactory 低温度创建不影响其他调用方

### 6.3 开发建议

- 优先并发修复（正确性），再 Reflector 改造
- 低温度客户端做成 LLMFactory 的选项，不影响默认

---

## 7. 变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| v1 | 2026-08-01 | 初始版本 | Planner |

---

## 8. 审批记录

| 角色 | 姓名 | 审批结果 | 日期 | 备注 |
|------|------|----------|------|------|
| Planner | 规划执行 | ✅ 通过 | 2026-08-01 | |
| Reviewer | | ⏳ 待审查 | | |
| Tester | | ⏳ 待测试 | | |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
