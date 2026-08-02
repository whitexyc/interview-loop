# 功能规格说明书 — Module-030: 重排性能优化 + LangGraph 实验端点

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-030 |
| 模块名称 | 重排性能优化 + LangGraph 实验端点 |
| 版本号 | 0.30.0-module-030 |
| 优先级 | P2 |
| 预估代码量 | ≤ 300 行 |
| 创建日期 | 2026-08-02 |
| 最后更新 | 2026-08-02 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：module-028 环境观察 + 用户确认（3+4 合并）
- 原始描述：
  ① 重排性能：Qwen3-Reranker（生成式模型）CPU 每对 6 秒，top-20 需 120 秒，真实链路被阻塞。换 bge-reranker-v2-m3（分类式，快 12 倍）。
  ② LangGraph：现有 ReAct 是手写 while 循环。新增 LangGraph 实验端点（并存），坐实技术栈、零回归风险。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 ① 重排快速（不再等几分钟）
      ② Agent 编排有 LangGraph 实现（技术栈坐实）
以便 问答响应可接受、架构技术栈完整
```

### 2.3 验收场景（BDD 格式）

```
场景 1：重排加速
  假设 5 个 pair 重排
  当 用 bge-reranker-v2-m3
  那么 耗时 < 3 秒（对比 Qwen3 30 秒）

场景 2：重排排序有效
  假设 相关和不相关文档混合
  当 重排
  那么 相关文档排前（分数可饱和但排序正确）

场景 3：LangGraph 端点
  假设 调用 /ai/rag/chat/agent-lg
  当 流式
  那么 正常回答（工具调用链路工作）
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 兼容 | 现有 reranker 接口不变（rerank(query, docs, top_k)） |
| 并存 | LangGraph 实验端点不动现有 /ai/rag/chat/agent |
| 回归 | 现有链路零回归 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/rag/reranker.py` | 修改 | 模型路径 → bge-reranker-v2-m3（分类式） |
| `ai_service/rag/graph.py` | 修改 | 已有 LangGraph 编排层，补充 ReAct 节点 |
| `ai_service/agent/langgraph_react.py` | 新增 | LangGraph 版 ReAct 循环 |
| `ai_service/main.py` | 修改 | 新增 /ai/rag/chat/agent-lg 端点 |
| `ai_service/rag_metadata_tables.sql` | 修改 | reranker_model 更新 |

### 3.2 业务逻辑说明

#### 功能 1：重排模型切换（bge-reranker-v2-m3）

```
问题: Qwen3-Reranker 生成式模型 CPU 每对 6s（自回归生成慢）
方案: 换 bge-reranker-v2-m3（分类式 CrossEncoder，实测 515ms/对，快 12 倍）

改动:
  1. reranker.py _LOCAL_MODEL_DIR → models/bge-reranker-v2-m3
  2. 加载: CrossEncoder(model_dir)（分类式，无需 chat template 适配）
  3. predict 传 (query, doc) 裸 pair（bge 是标准 CrossEncoder）
  4. 保留缺权重校验（module-018 设计）
  5. rag_config.reranker_model 更新

注意:
  - bge 分数接近 1.0（sigmoid 饱和），排序仍正确，区分度低是已知特性
  - 移除 Qwen3 的 chat template 适配代码（不再需要）
```

#### 功能 2：LangGraph 实验端点（并存）

```
背景: 现有 ReAct 是手写 while 循环（react.py，工作正常）
方案: 新增 LangGraph 版 ReAct（并存，不动手写循环）

改动:
  1. langgraph_react.py: 用 StateGraph 编排 ReAct
     - node llm_call: 调 chat_with_tools
     - node execute_tools: 执行工具 + 结果追加
     - 条件路由: 有 tool_call → execute_tools；无 → END
     - 预算检查: 工具数 < budget 才继续
  2. main.py: 新增 POST /ai/rag/chat/agent-lg（SSE）
  3. 复用现有 ToolRegistry + ReactContext（不重复实现）

注意:
  - LangGraph 版本与手写版本行为对齐（预算/工具/上下文）
  - 不动现有 react.py（并存，零回归）
  - 这是实验端点，非生产主路径
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| bge-reranker 替换 Qwen3 | 分类式快 12 倍，根治性能问题 |
| LangGraph 并存 | 零回归，坐实技术栈 |
| 复用 ToolRegistry/Context | 不重复实现工具逻辑 |
| bge 分数饱和不阻塞 | 排序正确即可，校准后续做 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| bge-reranker 缺权重 | RerankerException | 明确报错（保留 module-018 设计） |
| LangGraph 端点失败 | Exception | 返回 error SSE 事件 |
| 预算耗尽 | — | 用已收集 docs 兜底 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. 重排性能
python -c "
import time, asyncio, sys
sys.path.insert(0, '.')
from rag.reranker import reranker
async def test():
    docs = [{'id': i, 'content': f'Java线程池参数测试内容第{i}段'} for i in range(5)]
    t0 = time.time()
    r = await reranker.rerank('Java线程池', docs, top_k=3)
    print(f'耗时: {time.time()-t0:.1f}s')
    print('排序:', [d['id'] for d in r])
asyncio.run(test())"

# 2. LangGraph 端点
curl -X POST http://localhost:8000/ai/rag/chat/agent-lg \
  -H "Content-Type: application/json" -d '{"query":"Java线程池核心参数"}'

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
耗时: < 3s
排序: [相关文档在前]
SSE 正常（tool_call/token/done）
===== 0 failed, N passed =====
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| 重排慢 | 仍用 Qwen3 | 检查模型路径 |
| bge 加载失败 | 缺权重 | 检查 model.safetensors |
| LangGraph 端点报错 | 图构建问题 | 检查 langgraph_react.py |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-018 | reranker 结构 | ✅ |
| module-028 | ToolRegistry + ReactContext | ✅ |
| — | bge-reranker-v2-m3 权重（已下载 2.17GB） | ✅ |

### 5.2 下游依赖

无（独立优化）。

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| bge 分数饱和 | 区分度低 | 高 | 排序仍正确，不阻塞；后续校准 |
| LangGraph 版本行为偏差 | 与手写不一致 | 中 | 复用 ToolRegistry/Context，测试对齐 |

### 6.2 技术注意事项

- [x] bge-reranker-v2-m3 权重已下载（2.17GB）
- [x] 移除 Qwen3 chat template 适配（bge 不需要）
- [x] LangGraph 并存（不动 react.py）
- [x] 复用 ToolRegistry/Context

### 6.3 开发建议

- 优先重排切换（性能根治），验证 12 倍提升
- 再 LangGraph 实验端点（并存）

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
