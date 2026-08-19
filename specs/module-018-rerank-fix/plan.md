# 功能规格说明书 — Module-018: Rerank 重排修复（切换 Qwen3-Reranker）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-018 |
| 模块名称 | Rerank 重排修复（切换 Qwen3-Reranker） |
| 版本号 | 0.18.0-module-018 |
| 优先级 | P0 |
| 预估代码量 | ≤ 200 行 |
| 创建日期 | 2026-08-01 |
| 最后更新 | 2026-08-01 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：代码审查发现 + 用户确认
- 原始描述：重排模型 bge-reranker-v2-m3 本地目录缺少权重文件，导致 CrossEncoder 加载失败，重排从未真正生效（静默降级为原始排序）。用户已下载 Qwen3-Reranker-0.6B 模型，要求切换为本地模型。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 重排真正生效（用 Qwen3-Reranker-0.6B）
以便 检索结果按真实相关性排序，而不是依赖混合检索的原始顺序
```

### 2.3 验收场景（BDD 格式）

```
场景 1：加载 Qwen3-Reranker 本地模型
  假设 模型文件存在于 models/Qwen3-Reranker-0.6B/（含 model.safetensors）
  当 初始化 CrossEncoderReranker 并调用 rerank()
  那么 模型加载成功，返回带 rerank_score 的排序结果

场景 2：本地模型缺失权重时明确报错
  假设 模型目录存在但无权重文件（model.safetensors / pytorch_model.bin）
  当 初始化并调用 rerank()
  那么 抛出 RerankerException（而非静默降级），日志记录明确原因

场景 3：rerank 排序有效
  假设 传入 query 和多个 docs
  当 调用 rerank()
  那么 返回按 rerank_score 降序的 top_k 条，且排序与输入不同（相关性高的靠前）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 响应时间 | 每对推理 ≤ 200ms（CPU 推理，0.6B 模型） |
| 并发量 | 单请求内 top 20 对，无并发压力 |
| 可用性 | 模型加载失败时明确报错（不静默降级） |
| 安全级别 | 本地模型，无外部 API 调用 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/reranker.py` | 修改 | 模型路径指向 Qwen3-Reranker + 缺权重明确报错 |
| `ai_service/.env` | 修改 | 更新 reranker 相关配置（如需要） |
| `ai_service/rag_metadata_tables.sql` | 修改 | rag_config.reranker_model 默认值更新 |
| `ai_service/create_metadata_tables.py` | 修改 | INITIAL_CONFIG 中 reranker_model 更新 |
| `ai_service/backfill_graph.py` | 不动 | — |

### 3.2 数据库变更

无新增表。`rag_config` 表已有 `reranker_model` 行，需 UPDATE 值：

```sql
UPDATE rag_config SET config_value = 'Qwen/Qwen3-Reranker-0.6B', updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'reranker_model';
```

### 3.3 业务逻辑说明

#### 核心流程（reranker.py 修改点）

```
1. _LOCAL_MODEL_DIR 指向 models/Qwen3-Reranker-0.6B
2. _DEFAULT_MODEL 逻辑：
   a. 若本地目录存在 → 用本地路径
   b. 若本地目录不存在 → 不自动回退 HuggingFace，抛 RerankerException 明确报错
      （决策：用户要求"直接本地，不回退"）
3. _lazy_load() 增加权重文件存在性校验：
   - 检查 model.safetensors 或 pytorch_model.bin 是否存在
   - 缺失 → 抛 RerankerException("模型权重文件缺失: <path>")
4. CrossEncoder 加载失败 → 抛 RerankerException（不再被上层静默吞掉）
```

#### 关键业务规则

| 序号 | 规则描述 | 实现位置 |
|------|----------|----------|
| 1 | 本地模型目录优先 | reranker.py `_LOCAL_MODEL_DIR` |
| 2 | 缺权重必须明确报错，不回退 HF | reranker.py `_lazy_load` |
| 3 | 加载/推理失败抛 RerankerException | reranker.py 异常处理 |
| 4 | 正常路径仍返回 top_k 精排结果 | reranker.py `rerank` |

#### 变更点（对比现状）

| 现状 | 目标 |
|------|------|
| `_LOCAL_MODEL_DIR = models/bge-reranker-v2-m3` | `models/Qwen3-Reranker-0.6B` |
| `_DEFAULT_MODEL` 缺目录回退 HF | 缺目录抛异常 |
| 缺权重时静默失败 | 缺权重明确报错 |

### 3.4 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 本地目录不存在 | RerankerException | 抛出，明确提示模型未下载 |
| 权重文件缺失 | RerankerException | 抛出，明确提示缺失文件路径 |
| CrossEncoder 加载失败 | RerankerException | 包装原始异常抛出 |
| predict 推理失败 | RerankerException | 包装原始异常抛出 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
# 1. 加载测试（Python）
cd ai_service
python -c "
import asyncio
from rag.reranker import reranker
async def test():
    docs = [
        {'id': 1, 'content': 'Java 线程池的核心参数包括核心线程数、最大线程数'},
        {'id': 2, 'content': 'Redis 缓存穿透是指查询不存在的数据'},
        {'id': 3, 'content': '线程池的拒绝策略有 AbortPolicy、CallerRunsPolicy'},
    ]
    result = await reranker.rerank('Java 线程池参数', docs, top_k=3)
    for d in result:
        print(d['id'], d.get('rerank_score'))
    print('OK')
asyncio.run(test())
"

# 2. 缺权重报错测试（临时把模型目录改名验证，或 mock）
# 3. rag_config 更新确认
psql -U postgres -d personal_website -c "SELECT config_key, config_value FROM rag_config WHERE config_key='reranker_model';"
```

### 4.2 预期输出

```
# 加载测试预期
1 1.xx  （id=1 Java线程池 得分最高）
3 0.xx  （id=3 相关）
2 0.xx  （id=2 不相关 得分最低）
OK

# rag_config 预期
 reranker_model | Qwen/Qwen3-Reranker-0.6B
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| RerankerException: 模型权重文件缺失 | 模型未下载或目录不完整 | 检查 models/Qwen3-Reranker-0.6B/model.safetensors |
| 加载慢 | 1.1GB 模型首次载入内存 | 属正常，预热后可复用实例 |
| OOM | 0.6B 模型内存占用 | 确认机器内存 ≥ 4GB |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-005: Agentic RAG 核心 | retriever.py 检索结果格式 | ✅ 已完成 |
| — | sentence-transformers 5.6.1（已装） | ✅ |
| — | Qwen3-Reranker-0.6B 模型（已下载） | ✅ |

### 5.2 下游依赖

| 被依赖模块 | 提供内容 | 状态 |
|------------|----------|------|
| module-019+ | Rerank 真分数作为后续 Graph 归一化/评估闭环的基础 | 📋 待开发 |

### 5.3 外部依赖

| 外部服务 | 用途 | 可用性要求 |
|----------|------|------------|
| 无（本地模型） | — | — |

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 0.6B 模型 CPU 推理慢 | 中（每对 ~100ms） | 中 | 只对 top 20 精排，可接受 |
| 首次加载慢 | 低 | 高 | 预热机制（main.py lifespan 已预热） |
| 模型加载内存占用 | 中 | 中 | 确认机器内存 ≥ 4GB |

### 6.2 技术注意事项

- [x] 注意：模型已下载至 `ai_service/models/Qwen3-Reranker-0.6B/`（1.14GB）
- [x] 注意：`.gitignore` 已排除 models 目录（不会提交模型）
- [x] 注意：sentence-transformers 5.6.1 原生支持 Qwen3-Reranker
- [ ] 注意：config.json 的 model_type 需在测试时确认（不影响加载）

### 6.3 开发建议

- 优先实现核心路径（模型路径 + 缺权重报错）
- rerank_score 用于后续 Graph 归一化（阶段 3），保持字段名不变
- 修改后跑一次真实检索确认排序变化

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
