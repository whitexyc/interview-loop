# Review Report — Module-005: Agentic RAG 知识库核心

> Reviewer: Claude (reviewer-001) | Date: 2026-07-30 | Version: v1

## 审查范围

| 文件 | 路径 | 行数 |
|------|------|------|
| Document ORM | `ai_service/rag/models.py` | 48 |
| 嵌入服务 | `ai_service/rag/embeddings.py` | 121 |
| 混合检索器 | `ai_service/rag/retriever.py` | 214 |
| Rerank 重排 | `ai_service/rag/reranker.py` | 72 |
| RAG 引擎 | `ai_service/rag/engine.py` | 132 |
| 意图路由 | `ai_service/agent/router.py` | 85 |
| 自我反思 | `ai_service/agent/reflector.py` | 117 |
| LLM 适配器 | `ai_service/llm/client.py` | 123 |
| Schemas | `ai_service/rag/schemas.py` | 26 |
| Config | `ai_service/src/config.py` | 46 |
| Database | `ai_service/src/database.py` | 39 |
| 入口 | `ai_service/main.py` | 80 |

---

## 1. 摘要

整体架构清晰，分层合理：`rag/` 负责检索链路，`agent/` 负责智能决策（路由、反思），`llm/` 统一 LLM 调用。代码风格一致，snake_case、类型注解、日志覆盖均有。发现 **2 个 Critical 问题** 会在运行时直接触发错误，**4 个 High 问题** 涉及性能和安全，以及若干中低优先级改进项。

---

## 2. Critical 问题（必须修复）

### C1. `reflector.py` — provider `"modelscope"` 不被 LLMFactory 支持（运行时崩溃）

**文件**: `ai_service/agent/reflector.py:46`

```python
self._provider = provider or "modelscope"  # 默认用 ModelScope 的 V4-Pro
```

但 `ai_service/llm/client.py:115-116` 中 `LLMFactory.get_client()` 仅支持 `"claude"` 和 `"deepseek"`：

```python
if provider == "claude":
    cls._instances[provider] = ClaudeClient()
elif provider == "deepseek":
    cls._instances[provider] = DeepSeekClient()
else:
    raise ValueError(f"不支持的 LLM 供应商: {provider}")
```

**影响**: 每次调用 `reflector.check_sufficiency()` 或 `reflector.generate_answer()` 都会抛出 `ValueError`，RAG chat 链路在反思步骤直接崩溃。

**修复**: 在 `LLMFactory` 中新增 `"modelscope"` 分支，使用 DeepSeekClient 以 ModelScope base_url 初始化；或改为 `provider or "deepseek"`，并在 factory 中为 modelscope 注册别名。

---

### C2. `router.py` — Prompt 中的分类名拼写错误导致意图识别失效

**文件**: `ai_service/agent/router.py:25`

Prompt 中写的管道值列表为 `knowledge|causal_chat|realtime`，但第 70 行的校验列表是 `("knowledge", "casual_chat", "realtime")`。

`causal_chat` vs `casual_chat` — LLM 会遵循 prompt 中的规范返回 `"causal_chat"`，随后被校验逻辑拒绝，fallback 为 `"knowledge"`。闲聊类查询会被错误路由到知识库检索。

**修复**: 将 prompt 第 25 行的 `causal_chat` 改为 `casual_chat`。

---

## 3. High 问题（强烈建议修复）

### H1. `llm/client.py` — 同步 `generate()`/`chat()` 阻塞 FastAPI 事件循环

**文件**: `ai_service/llm/client.py:53-68`, `ai_service/llm/client.py:84-99`

`LLMClient.generate()` 和 `LLMClient.chat()` 都是 synchronous 方法，内部调用 LangChain 的 `self._llm.invoke()`（同步 HTTP 调用）。但它们在 async 上下文中被调用（`engine.chat()` 是 async，`router.classify()` 是 async，`reflector.check_sufficiency()` 是 async）。

在 FastAPI 的单一事件循环线程中，同步阻塞 I/O 会卡住整个服务，导致并发能力降为 1。

**修复**: 改用 LangChain 的 async API (`self._llm.ainvoke()`)，并将 `LLMClient` 的 `generate()` 和 `chat()` 改为 async 方法。调用方需加 `await`。或使用 `asyncio.to_thread()` 将同步调用放到线程池。

---

### H2. `llm/client.py` — `chat()` 类型注解与实际调用不匹配

**文件**: `ai_service/llm/client.py:36`

```python
def chat(self, messages: list[BaseMessage]) -> str:
```

但调用方 (`engine.py:62-66`) 传入的是 `list[dict]`：

```python
answer = client.chat([
    {"role": "system", "content": "..."},
    *request.history,
    {"role": "user", "content": request.query},
])
```

虽然 LangChain 的 `invoke()` 运行时接受 dict，但类型注解承诺 `BaseMessage` 却接收 `dict`，是类型不一致。且 `ChatRequest.history` 定义为 `list[dict]`（`schemas.py:19`），整个链路都是 dict。

**修复**: 将参数类型改为 `list[dict]`，或使用 `HumanMessage`/`SystemMessage` 构造消息。

---

### H3. `reranker.py` — `httpx.AsyncClient` 未关闭（资源泄漏）

**文件**: `ai_service/rag/reranker.py:32`

```python
self._client = AsyncClient(timeout=30)
```

全局单例 `reranker = ModelScopeReranker()` 创建的 `AsyncClient` 在进程生命周期内不会被关闭，会导致连接池中的 TCP 连接泄漏。

**修复**: 改为惰性初始化（每次调用创建并使用 `async with`），或实现 `close()` 方法并在 app shutdown 时调用。

---

### H4. `engine.py` — 错误信息暴露给用户

**文件**: `ai_service/rag/engine.py:123-126`

```python
return ChatResponse(
    answer="抱歉，我暂时无法回答这个问题，请稍后重试。",
    sources=[],
    message=f"error: {e}",  # 暴露内部异常细节
)
```

`message` 字段直接拼接异常信息，可能泄露内部路径、API endpoint 等敏感信息。

**修复**: 在生产环境隐藏具体错误，只返回通用错误码：

```python
message="internal_error" if not settings.debug else f"error: {e}"
```

---

## 4. Medium 问题（建议修复）

### M1. 缺少 `/ai/rag/documents` API 端点

**文件**: 计划 `plan.md:73` 要求但 `main.py` 未实现

计划中的 `/ai/rag/documents` POST 端点（文档入库接口）缺失，这意味着无法向知识库添加文档，RAG 链路缺少"写入"入口。

### M2. `retriever.py` — `import asyncio` 位置不当

**文件**: `ai_service/rag/retriever.py:95`

`import asyncio` 写在 `_execute()` 方法内部。应移至文件顶部。

### M3. `engine.py` — 二次检索后未重新检查充分性

**文件**: `ai_service/rag/engine.py:96-103`

第一次反思判定"不充分"后改写 Query 进行二次检索，但二次检索的结果直接追加到文档列表后调用 `generate_answer`，未再次检查充分性（见验收标准："二次检索仍不充分时如实告知"）。

**修复**: 二次检索后可再次调用 `reflector.check_sufficiency()`，或使用重试计数器限制最大检索轮次。

### M4. `llm/client.py` — `temperature=0.7` 硬编码

**文件**: `ai_service/llm/client.py:50, 81`

所有 LLM 调用的 temperature 固定为 0.7。但意图分类和反思检查属于结构化输出任务，应使用更低 temperature（如 0.0-0.2），而闲聊回答适合 0.7-1.0。

**修复**: 在 `get_client()` 或 `generate()` 中支持传入 temperature 参数。

### M5. `config.py` — 数据库密码硬编码为默认值

**文件**: `ai_service/src/config.py:15`

```python
database_url: str = "postgresql+asyncpg://postgres:postgres123@localhost:5432/personal_website"
```

密码出现在代码中。虽为默认值且环境变量可覆盖，但建议移除默认凭据，或在 `.env.example` 中占位，启动时检查并报错。

### M6. `embeddings.py` — embedding_model 默认值与 ModelScope 不匹配

**文件**: `ai_service/src/config.py:37`

```python
embedding_model: str = "text-embedding-v3"
```

这是 OpenAI 的模型名。但 embeddings.py 的默认 base_url 指向 ModelScope，而 ModelScope 上没有这个模型。实际在 ModelScope 应使用类似 `bge-m3` 或 `bge-large-zh-v1.5` 的模型。

**修复**: 将默认模型改为 ModelScope 上实际可用的 embedding 模型名。

---

## 5. Low 问题（可选修复）

### L1. `retriever.py` — `_normalize()` 就地修改入参并返回

`_normalize()` 方法一边修改 `results` 列表中每个 dict 的 `score` 字段，一边返回同一个列表。行为正确但语义混乱——调用方看到返回值可能误以为是副本。建议要么纯 in-place（返回 None），要么纯 copy（返回新列表）。

### L2. `embeddings.py` — 全局单例在 import 时强制初始化

`embedding_service = EmbeddingService()` 在模块导入时即执行，若 API key 未配置，整个应用启动失败。建议延迟到首次调用时初始化（lazy singleton）。

### L3. `models.py` — `to_dict()` 不返回 `embedding` 字段

这是合理的选择（向量通常不序列化），但缺少注释说明原因。

### L4. `schemas.py` — `SearchResponse.results: list[dict]` 类型过宽

`list[dict]` 丢失了文档结构信息。建议定义一个 `SearchResultItem` pydantic model，包含 `id`, `title`, `content`, `source`, `score` 等字段。

### L5. `reranker.py` — fallback 依赖 `hybrid_score` 字段

如果 reranker 的输入文档不是来自 `HybridRetriever`（来自其他检索源），则 `hybrid_score` 不存在，fallback 排序无效。

### L6. `engine.py` — 多处裸 dict key 访问无保护

如 `doc.get("id")`, `doc.get("title")` 等使用了 `.get()` 安全访问，但部分分数计算使用 `doc.get("hybrid_score", doc.get("rerank_score", 0.0))`，逻辑嵌套较深，可读性差。

---

## 6. 验收标准覆盖度

| 验收项 | 状态 | 说明 |
|--------|------|------|
| 文档向量化 | Partial | embedding 服务实现，但 `/ai/rag/documents` 端点缺失 |
| 混合检索 (BM25+向量) | Pass | `HybridRetriever` 完整实现，含归一化和加权融合 |
| Rerank Top20→Top5 | Pass | `ModelScopeReranker` 实现，含 fallback |
| 意图路由 (3分类) | Bug | Prompt 拼写错误导致分类失效 (C2) |
| 自我反思+改写Query | Bug | `reflector` provider 配置错误导致崩溃 (C1) |
| 引用溯源 | Pass | ChatResponse 包含 sources 数组 |
| `/ai/rag/chat` 完整链路 | Fail | C1 导致运行时崩溃，H1 导致性能问题 |
| 知识库为空友好提示 | Pass | `engine.py:82-85` 已处理 |
| 闲聊不走检索 | Pass | `engine.py:60-67` 已处理 |
| 二次检索不充分告知 | Partial | 二次检索后未再检查充分性 (M3) |

---

## 7. 代码质量汇总

| 维度 | 评分 | 说明 |
|------|------|------|
| snake_case | Good | 全局一致 |
| async/await | Warning | LLM 调用层是同步的 (H1) |
| 类型注解 | Good | 参数和返回值均有注解，仅 schemas 偏宽 |
| 异常处理 | Good | 各层均有自定义异常，降级和 fallback 完善 |
| 日志 | Good | 关键路径均有 info/debug/error 日志 |

## 8. 架构评价

```
main.py (FastAPI)
  └── rag/engine.py (RAGEngine)         ← 编排层
        ├── agent/router.py (Router)     ← 决策层
        ├── rag/retriever.py (Retriever) ← 检索层
        │     └── rag/embeddings.py
        ├── rag/reranker.py (Reranker)   ← 精排层
        ├── agent/reflector.py           ← 决策层
        └── llm/client.py (LLMFactory)   ← 适配层
```

分层清晰，`rag/` 专注检索、`agent/` 专注决策、`llm/` 专注适配。唯一不足是 `reflector` 既承担"判断充分性"又承担"生成回答"，可考虑将生成职责拆分到独立的 Generator 模块。

## 9. 安全性

- API Key 通过环境变量读取：Pass（`config.py` 使用 `pydantic-settings`，prefix `PW_`）
- 数据库密码默认为明文：Medium risk（M5）
- 错误信息暴露：High risk（H4）
- CORS 配置 `allow_origins=["*"]`：根据使用场景评估（个人网站可接受，企业级需收紧）

## 10. 修复优先级

| 优先级 | 编号 | 问题 | 预估工时 |
|--------|------|------|----------|
| P0 | C1 | reflector provider "modelscope" 不被支持 | 5min |
| P0 | C2 | router prompt 中 casual_chat 拼写错误 | 1min |
| P1 | H1 | sync LLM 调用阻塞事件循环 | 30min |
| P1 | H3 | AsyncClient 资源泄漏 | 10min |
| P1 | H4 | 错误信息暴露 | 5min |
| P2 | H2 | chat() 类型注解不匹配 | 5min |
| P2 | M3 | 二次检索不检查充分性 | 15min |
| P3 | M1 | 缺少 documents 端点 | 30min (新任务) |
| P3 | M2-M6 | 其他 Medium 问题 | 30min |
| P4 | L1-L6 | Low 问题 | 可选 |

---

## 11. 总结

代码质量整体良好，模块职责清晰。两个 Critical 问题是配置层面的 bug（不是逻辑错误），修复成本极低。核心顾虑是 H1（事件循环阻塞）——在并发场景下这是硬伤，必须在生产部署前解决。
