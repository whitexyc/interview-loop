# 功能规格说明书 — Module-022: 检索缓存修复

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-022 |
| 模块名称 | 检索缓存修复（key 参数化 + 失效策略） |
| 版本号 | 0.22.0-module-022 |
| 优先级 | P0 |
| 预估代码量 | ≤ 200 行 |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：发散路线图 P0 + 用户确认
- 原始描述：检索缓存存在两个正确性缺陷：① cache_key 只含 query hash，不含 top_k/min_score/history，不同参数复用错误结果；② 文档增删后缓存不失效，脏缓存持续返回旧数据。

### 2.2 用户故事

```
作为 RAG 系统开发者
我想要 缓存 key 纳入检索参数、文档变更后缓存失效
以便 检索结果可复现、不污染评估，脏缓存不导致错误结果
```

### 2.3 验收场景（BDD 格式）

```
场景 1：不同参数不同缓存
  假设 同一 query 用不同 top_k 检索
  当 两次调用 _retrieve
  那么 不互相污染（key 含 top_k）

场景 2：新增文档后缓存失效
  假设 检索某 query 并缓存
  当 add_document 新增文档
  那么 再次检索同 query 返回新结果（旧缓存已失效）

场景 3：删除文档后缓存失效
  假设 检索某 query 并缓存
  当 delete_document 删除文档
  那么 再次检索同 query 不返回已删文档
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | cache.get/set 接口不变 |
| 失效效率 | 按前缀失效（SCAN + DEL），不阻塞 |
| 不回归 | 缓存命中仍加速（TTL 保留） |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/src/cache.py` | 修改 | 新增 `delete_by_prefix(prefix)` |
| `ai_service/rag/engine.py` | 修改 | cache_key 纳入参数 + add/delete 失效 |
| `ai_service/main.py` | 修改 | delete_document 端点失效缓存 |

### 3.2 数据库变更

无表结构变更。

### 3.3 业务逻辑说明

#### 核心流程

```
1. cache.py 新增 delete_by_prefix(prefix):
   - 用 Redis SCAN 匹配前缀（避免 KEYS 阻塞）
   - 逐个 DEL 匹配的 key
   - 失败降级（不影响检索）

2. engine._retrieve cache_key 改造:
   旧: rag:retrieve:{hash(query)[:12]}
   新: rag:retrieve:{hash(query + top_k + min_score)[:16]}
   - 纳入 top_k、min_score（history 可选，当前 _retrieve 无 history 参数）

3. add_document 失效:
   - 文档成功入库后，调用 cache.delete_by_prefix("rag:retrieve:")
   - 清空所有检索缓存（简单粗暴但正确；文档变更影响所有查询）

4. delete_document 失效（main.py）:
   - 删除成功后，同样 delete_by_prefix("rag:retrieve:")
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| key 纳入 top_k/min_score | 不同参数不同缓存，避免错误复用 |
| 文档变更全量失效 | 简单正确（文档增删影响所有查询的候选集） |
| SCAN 而非 KEYS | 避免大 key 空间下 KEYS 阻塞 Redis |
| 失效失败降级 | 缓存是优化层，失效失败不影响检索正确性（只影响新鲜度） |

### 3.4 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| SCAN 失败 | Exception | 记录 warning，降级（缓存不失效） |
| Redis 不可用 | Exception | delete_by_prefix 返回 False，不抛 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. delete_by_prefix 测试
python -c "
import asyncio
from src.cache import cache
async def test():
    await cache.set('rag:retrieve:test1', [{'id':1}])
    await cache.set('rag:retrieve:test2', [{'id':2}])
    ok = await cache.delete_by_prefix('rag:retrieve:')
    print('delete_by_prefix:', ok)
    v1 = await cache.get('rag:retrieve:test1')
    v2 = await cache.get('rag:retrieve:test2')
    print('清除后:', v1, v2)
asyncio.run(test())"

# 2. 不同 top_k 不同缓存（检查 key）
# 3. 新增文档后缓存失效
```

### 4.2 预期输出

```
delete_by_prefix: True
清除后: None None
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 缓存不失效 | Redis 不可用 / SCAN 失败 | 检查日志 warning |
| key 冲突 | hash 碰撞 | 16 位 hash 足够 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-015: Redis Cache | cache.get/set | ✅ |
| module-005: RAG 核心 | _retrieve | ✅ |

### 5.2 下游依赖

无（独立正确性修复）。

### 5.3 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| Redis | 缓存 | 不可用时降级（现有行为） |

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| SCAN 性能 | 大 key 空间慢 | 低 | 用 SCAN cursor 分批 |
| 全量失效频繁 | 缓存命中率下降 | 低 | 文档变更不频繁 |

### 6.2 技术注意事项

- [x] cache.get/set 接口保持不变（兼容现有调用）
- [x] delete_by_prefix 用 SCAN 而非 KEYS
- [x] 文档变更全量失效（简单正确）
- [ ] Redis SCAN 需 async 实现

### 6.3 开发建议

- 优先实现 delete_by_prefix + cache_key 改造
- 再挂接 add/delete 失效

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
