# 功能规格说明书 — Module-028: Agent 工具化（ToolRegistry + ReAct 循环）

> 本文件由 **Planner** 输出，作为模块开发的唯一权威规格文档。
> Developer 严格按本文件编码，Reviewer 和 Tester 按本文件验收。

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-028 |
| 模块名称 | Agent 工具化（ToolRegistry + ReAct 循环） |
| 版本号 | 0.28.0-module-028 |
| 优先级 | P2 |
| 预估代码量 | ≤ 400 行（含 ToolRegistry + ReAct + 端点 + SSE，需调整上限） |
| 创建日期 | 2026-08-02 |
| 最后更新 | 2026-08-02 |
| 负责人 | Planner: 规划执行, Developer: 待分配 |

> **代码量调整理由**：含 ToolRegistry（~80 行）、ReAct 循环（~120 行）、LLMClient 工具接口（~60 行）、新端点 + SSE 轨迹（~100 行）、测试（~80 行）。合计约 400 行，申请调整上限。

---

## 2. 需求描述

### 2.1 需求来源

- 来源类型：发散路线图 P2 + 用户确认
- 原始描述：把固定流水线（意图路由→检索→反思→生成）升级为 Agentic ReAct 循环——LLM 自己决定调用什么工具、以什么顺序，直到可回答。用户已确认：并存新端点、SSE 工具轨迹、工具调用预算可配置（总次数上限）、开发流程突破 3 轮重试。

### 2.2 用户故事

```
作为 RAG 系统用户
我想要 Agent 能自己决定怎么检索（图密集先查图、精确关键词先查 FTS）
以便 比固定流水线更聪明地找到答案
```

### 2.3 验收场景（BDD 格式）

```
场景 1：LLM 工具调用
  假设 用户提问
  当 走 Agent 端点
  那么 LLM 能输出 tool_call 并正确执行

场景 2：ReAct 循环
  假设 一次检索不够
  当 Agent 判断需要更多
  那么 自动调下一个工具，直到可回答或达预算上限

场景 3：工具预算
  假设 预算上限 N
  当 循环执行
  那么 总工具调用次数 ≤ N

场景 4：SSE 工具轨迹
  假设 流式调用 Agent 端点
  当 每次工具调用
  那么 前端收到 tool_call/tool_result 事件
```

### 2.4 非功能需求

| 类别 | 要求 |
|------|------|
| 并存 | 新端点 /ai/rag/chat/agent，现有 /ai/rag/chat 不变 |
| 预算 | 工具总调用次数可配置（默认 3-4，开发可调大） |
| 降级 | 工具失败返回空，LLM 判断继续或放弃 |

---

## 3. 技术方案

### 3.1 涉及文件

| 文件路径 | 操作类型 | 说明 |
|----------|----------|------|
| `ai_service/llm/client.py` | 修改 | LLMClient 新增工具调用方法 |
| `ai_service/agent/tool_registry.py` | 新增 | ToolRegistry 注册/解析工具 |
| `ai_service/agent/react.py` | 新增 | ReAct 循环编排 |
| `ai_service/main.py` | 修改 | 新增 /ai/rag/chat/agent 端点（SSE） |
| `ai_service/src/config.py` | 修改 | 工具预算配置项 |

### 3.2 业务逻辑说明

#### 核心流程

```
1. ToolRegistry（tool_registry.py）:
   注册工具: 把现成方法包装成带 name/description/args_schema 的工具
   内置工具: search_knowledge / search_fts / search_vector / search_graph /
            extract_entities / recall_memory / generate_answer

2. LLMClient 工具接口（client.py）:
   新增 chat_with_tools(messages, tools) -> {content, tool_calls}
   - DeepSeek/Qwen/Zhipu 都用 ChatOpenAI.bind_tools()
   - 返回 tool_calls 列表（name + args）

3. ReAct 循环（react.py）:
   while 未回答 and 工具调用数 < budget:
     LLM 调用（含已收集的工具结果作为上下文）
     if tool_calls:
       逐个执行工具 → 结果追加到消息
       yield tool_call/tool_result 事件
       工具数 +1
     else:
       LLM 直接输出答案 → 结束
   budget 耗尽 → 用已收集 docs 兜底生成

4. 端点（main.py）:
   POST /ai/rag/chat/agent → SSE
   event: tool_call / tool_result / token / done
```

#### 关键设计决策

| 决策 | 说明 |
|------|------|
| 工具总次数预算 | 不是单工具次数，是循环总上限（防空转烧钱） |
| 预算可配置 | config 加 max_agent_tools，开发/测试可调大 |
| 并存新端点 | 现有链路零风险，可 A/B 对比 |
| 工具失败返回空 | LLM 判断继续或放弃（沿用降级哲学） |
| 工具结果作上下文 | 每次工具结果追加到 messages，LLM 能看到历史 |

### 3.3 异常处理

| 异常场景 | 异常类型 | 处理方式 |
|----------|----------|----------|
| 工具执行失败 | Exception | 返回空结果，LLM 判断继续/放弃 |
| LLM 调用失败 | LLMException | 降级链切下一个供应商 |
| 预算耗尽 | — | 用已收集 docs 兜底生成 |
| 循环死锁 | — | 预算上限天然防死循环 |

---

## 4. 验收标准

> 详细验收标准见同目录下的 `acceptance-criteria.md`

### 4.1 可运行的验证命令

```bash
cd ai_service
# 1. ToolRegistry 注册测试
python -c "
from agent.tool_registry import registry
tools = registry.list_tools()
print('已注册工具:', [t.name for t in tools])"

# 2. ReAct 循环测试
python -c "
import asyncio
from agent.react import react_agent
async def test():
    result = await react_agent('Java线程池核心参数', budget=4)
    print('答案:', result['answer'][:100])
    print('工具调用次数:', result['tool_count'])
asyncio.run(test())"

# 3. 回归
python -m pytest ai_service/tests/ -x
```

### 4.2 预期输出

```
已注册工具: ['search_knowledge', 'search_fts', 'search_vector', 'search_graph', 'extract_entities', 'recall_memory', 'generate_answer']
工具调用次数: ≤ 4
===== 0 failed, N passed =====
```

### 4.3 失败诊断方法

| 失败现象 | 可能原因 | 排查步骤 |
|----------|----------|----------|
| LLM 不调工具 | bind_tools 未生效 | 检查 chat_with_tools |
| 工具调用超过预算 | 预算逻辑未生效 | 检查 react.py 计数 |
| 死循环 | 预算=0 或未检查 | 确认 budget > 0 |

---

## 5. 依赖关系

### 5.1 上游依赖

| 依赖模块 | 依赖内容 | 状态 |
|----------|----------|------|
| module-005 | 检索/图/记忆方法（工具来源） | ✅ |
| module-026 | LLMClient 温度/降级链 | ✅ |
| — | DeepSeek/Qwen/Zhipu function calling（已验证） | ✅ |

### 5.2 下游依赖

| 被依赖模块 | 提供内容 | 状态 |
|------------|----------|------|
| 降级链动态调序 | 前端调整供应商顺序 | 📋 后续 |
| LangGraph 接入 | ReAct 用 LangGraph 编排 | 📋 后续 |

---

## 6. 风险点与注意事项

### 6.1 已知风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| LLM 工具调用不稳定 | 偶尔不调或乱调 | 中 | 预算兜底 + 降级为直接回答 |
| 延迟增加 | 每轮工具调用耗时 | 中 | 预算限制 + 缓存 |

### 6.2 技术注意事项

- [x] 工具总次数预算（非单工具）
- [x] 三家供应商 function calling 已验证可用
- [x] 预算可配置（开发调大）
- [x] 工具结果作上下文（LLM 能看到历史）

### 6.3 开发建议

- 优先 ToolRegistry + LLMClient 工具接口（基础）
- 再 ReAct 循环（核心）
- 最后端点 + SSE 轨迹（展示）

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
| Reviewer | Reviewer | ✅ 通过 | 2026-08-02 | 审查通过，放行进入 Tester 阶段 |
| Tester | Tester | ✅ 通过 | 2026-08-02 | 验收通过 44/44，见 test-report.md |

---

> **下一步**：Developer 根据本规格说明书开始编码实现。
> **开发流程注**：本模块允许突破 3 轮重试上限，直到系统完善（用户确认）。
