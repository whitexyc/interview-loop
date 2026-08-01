# 功能规格说明书 — Module-021: 图分数归一化

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-021 |
| 模块名称 | 图分数归一化（graph_score 真实相关度） |
| 版本号 | 0.21.0-module-021 |
| 优先级 | P1 |
| 预估代码量 | ≤ 200 行 |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：发散路线图 P1 + 用户确认
- 原始描述：`graph_store.search_related` 返回的文档 `hybrid_score` **硬编码 0.6**，图结果之间无真实区分度。三通道融合时图结果永远固定分，导致排序失真。

### 2.2 用户故事

```
作为 RAG 系统开发者
我想要 图检索结果有真实相关度分数（命中实体数归一化）
以便 图结果与向量/FTS 结果可比，三通道融合更准确
```

### 2.3 验收场景（BDD 格式）

```
场景 1：图结果带真实分数
  假设 查询命中多个图实体
  当 search_related 返回
  那么 每篇文档的 hybrid_score 反映其命中实体数（归一化到 [0,1]）

场景 2：分数有区分度
  假设 两篇文档命中不同数量的实体
  当 比较分数
  那么 命中实体多的文档分数更高

场景 3：评估基线保持
  假设 运行 golden_retrieval --mode graph_only
  当 计算指标
  那么 Hit@5 不下降（当前 0.50 基线）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容性 | 返回格式不变（list[dict] 含 id/title/content/hybrid_score） |
| 可解释 | graph_score 反映真实相关度（实体命中数） |
| 不回归 | graph_only Hit@5 保持 ≥ 0.50 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/graph_store.py` | 修改 | search_related 计算真实 graph_score |
| `ai_service/rag/retriever.py` | 修改 | graph_only 模式分数归一化（如需要） |

### 3.2 数据库变更

无表结构变更（图数据在 AGE 中，分数在查询时计算）。

### 3.3 业务逻辑说明

#### 核心流程（graph_store.search_related 改造）

```
1. Cypher 查询增强：返回每个 doc 的命中实体数
   当前: RETURN DISTINCT COALESCE(related.doc_ids, e.doc_ids) AS doc_ids
   新:   匹配起点实体 e（查询实体命中）和相关实体 related，
         用 UNWIND doc_ids 统计每个 doc 被多少个实体引用

2. 计算 graph_score:
   对每篇 doc，统计其在查询实体及其一跳邻居中被引用的次数
   graph_score = 命中实体数（整数）

3. 归一化（在 Python 层）:
   min-max 归一化到 [0,1]（复用 retriever._normalize 的范式）
   若所有 doc 命中数相同 → 全部 0.6（保底，与现有一致）

4. 输出:
   hybrid_score = 归一化后的 graph_score
   按 graph_score 降序，取 top_k
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 命中实体数作为相关度 | 被越多实体引用的文档，与查询越相关（可解释） |
| min-max 归一化 | 与向量/FTS 通道分数同量纲（[0,1]） |
| 全同分保底 0.6 | 单结果/全同分时避免全 0（与现有行为一致） |
| 排序用原始计数 | 归一化只改分数值，排序用真实命中数 |

### 3.4 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| Cypher 查询失败 | Exception | 降级返回空（现有行为） |
| 无实体命中 | — | 返回空列表 |
| 单篇结果 | — | 分数 0.6（保底） |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 图检索分数测试
python -c "
import asyncio
from rag.graph_store import graph_store
async def test():
    docs = await graph_store.search_related(['Java', '线程池'], top_k=5)
    for d in docs:
        print(d['id'], d['hybrid_score'], d['title'][:40])
    # 验证分数在 [0,1] 且有区分度
asyncio.run(test())"

# 2. graph_only 评估
python -m eval.golden_retrieval --mode graph_only

# 3. hybrid 评估（确认融合不退化）
python -m eval.golden_retrieval --mode hybrid
```

### 4.2 预期输出

```
# 分数测试：分数在 [0,1]，命中实体多的排前
id=91 0.87 6-Java线程池ThreadPoolExecutor核心参数与工作原理
id=75 0.53 ...

# graph_only 评估：Hit@5 ≥ 0.50（基线）
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 分数全 0.6 | 命中实体数统计失败 | 检查 Cypher 是否返回命中数 |
| graph_only 下降 | 排序逻辑变化 | 检查是否按真实计数排序 |
| AGE 查询慢 | UNWIND 大数组 | 确认 LIMIT top_k*2 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-016: Graph RAG | AGE 图数据（实体+关系） | ✅ |
| module-019 | graph_only Hit@5=0.50 基线 | ✅ |

### 5.2 下游依赖

| 被依赖模块 | 提供内容 | 状态 |
|------------|----------|------|
| 混合检索增强 | 图结果真实分数融合 | 📋 |

### 5.3 外部依赖

无（本地 AGE）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| Cypher 复杂化 | 查询变慢/出错 | 中 | 用 UNWIND + 计数，测试验证 |
| 归一化影响融合 | hybrid 分数变化 | 中 | 用评估基线对比 |

### 6.2 技术注意事项

- [x] AGE 支持 UNWIND / 数组操作（agtype）
- [x] 分数归一化在 Python 层（复用 retriever._normalize 范式）
- [x] 排序用真实命中数，归一化只改分数值
- [ ] 需验证 AGE 的 UNWIND 语法可用

### 6.3 开发建议

- 优先实现 Cypher 返回命中数，验证 AGE 语法
- 再实现归一化 + 排序
- 用 graph_only 评估对比基线

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
