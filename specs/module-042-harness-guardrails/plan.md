# 功能规格说明书 — Module-042: Agent Harness 围栏

> Planner | 2026-08-08

---

## 1. 模块元信息

| 字段 | 内容 |
|------|------|
| 模块编号 | module-042 |
| 模块名称 | Harness 围栏 — Agent 安全边界 |
| 版本号 | 0.42.0-module-042 |
| 优先级 | P1（Agent 路径缺防护——工具无超时、输入无校验、输出无截断） |
| 预估代码量 | ≤ 150 行 |

---

## 2. 需求

### 2.1 现状缺口

| 能力 | 非 Agent 路径 (engine.chat) | Agent 路径 (react_loop) |
|------|---------------------------|------------------------|
| 工具超时 | ✅ retrieve 有 asyncio.wait_for(30s) | ❌ 每个工具调用无超时 |
| 输入校验 | ❌ 无 query/history 长度限制 | ❌ 同 |
| 输出截断 | ❌ 无 | ❌ 无 |

### 2.2 目标

三项低成本高收益防护：
1. Agent 每个工具调加 15s 超时 → 卡住不阻塞整个 loop
2. ChatRequest 输入校验 → query ≤ 2000 字符，history ≤ 20 条
3. LLM 答案输出截断 → 防止异常超长输出撑爆 SSE

### 2.3 验收场景

```
场景 1：工具超时自动终止
  假设 Agent 调 search_graph 耗时 >15s
  那么 工具返回"（超时）"→ LLM 继续下一轮/兜底 → 不阻塞

场景 2：超长输入拒绝
  假设 query > 2000 字符
  那么 返回 422 错误 "query 过长（最大 2000 字符）"

场景 3：history 条数限制
  假设 history 含 25 条消息
  那么 只取最近 20 条 + 返回 422

场景 4：答案截断不丢引用
  假设 LLM 生成 15000 字符答案
  那么 截断到 10000 字符 + 保留完整 sources
```

---

## 3. 技术方案

### 3.1 涉及文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `ai_service/agent/tool_registry.py` | 修改 | AgentTool.run() 加 asyncio.wait_for(15s) 超时 |
| `ai_service/rag/schemas.py` | 修改 | ChatRequest 加 Pydantic validator：query max_length=2000 |
| `ai_service/main.py` | 修改 | 端点入口 history 截断 + 答案长度保护 |

### 3.2 核心逻辑

#### 1) AgentTool.run 超时

```python
async def run(self, args: dict, ctx) -> str:
    try:
        return await asyncio.wait_for(self.func(ctx, args), timeout=15)
    except asyncio.TimeoutError:
        logger.warning("工具 %s 超时 (15s)", self.name)
        return f"（工具 {self.name} 执行超时）"
    except Exception as e:
        logger.warning("工具 %s 失败: %s", self.name, e)
        return ""
```

#### 2) ChatRequest 校验

```python
class ChatRequest(BaseModel):
    query: str = Field(..., max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=20)
```

#### 3) 答案截断

main.py 在返回 ChatResponse 前：
```python
MAX_ANSWER_LEN = 10000
if len(answer) > MAX_ANSWER_LEN:
    answer = answer[:MAX_ANSWER_LEN] + "\n\n[答案过长，已截断]"
```

### 3.3 降级

| 场景 | 处理 |
|------|------|
| 工具超时 | 返回提示文本，LLM 决定下一步 |
| 输入超限 | HTTP 422 + 明确错误消息 |
| 答案截断 | 保留 sources，末尾加截断提示 |

---

## 4. 依赖

- module-028 (AgentTool.run / ReactContext)
- module-004 (Reflector)
- 上游无新增依赖
