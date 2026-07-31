# RAG 知识库系统完整流程文档

> 本文件基于 ai_service 全部源码逐文件梳理（main.py / engine.py / retriever.py / reranker.py / chunker.py / embeddings.py / models.py / graph_store.py / graph_extractor.py / reflector.py / router.py / client.py / config.py / cache.py / ratelimit.py / schemas.py / state.py / graph.py）。
>
> 目的：作为后续优化工作的基准文档——每一处细节分支、降级、超时、配置均已穷尽。

---

## 1. 系统总览

### 1.1 架构分层

```
用户
  │  HTTP
  ▼
React 前端 (Vite → localhost:3000)
  │  代理转发
  ├─ /api/*  → Spring Boot (8080) — 简历 CRUD / 会话 / 熔断降级(仅配置，未实现调用)
  └─ /ai/*   → Python FastAPI (8000) — RAG 全部逻辑
                 │
                 ├─ PostgreSQL 16 (pgvector + Apache AGE + Flyway)
                 ├─ Redis (查询缓存)
                 ├─ ModelScope 云端 API (LLM 降级链 + bge-m3 嵌入)
                 └─ 本地模型 (bge-reranker-v2-m3 CrossEncoder 重排)
```

### 1.2 两条主链路

| 链路 | 入口 | 特点 |
|------|------|------|
| **chat 同步** | `POST /ai/rag/chat` | 手写循环，一次返回完整回答 + sources |
| **stream 流式** | `POST /ai/rag/chat/stream` | SSE 推送每步 `step` 事件 + 逐 token `token` 事件 |

另有两条辅助链路：
- **纯检索** `POST /ai/rag/search`（知识库搜索面板用，不生成回答）
- **LangGraph 编排** `rag/graph.py`（备选实现，未被 HTTP 端点直接调用，仅保留参考）

### 1.3 核心参数速览

| 参数 | 值 | 位置 |
|------|-----|------|
| 向量维度 | 1024 (bge-m3) | config + models.py |
| 子块大小 | 300 字符 / 重叠 50 | chunker.py |
| 混合检索 alpha | 0.3 (FTS 权重) | retriever.py |
| Rerank Top-K | 5 | graph.py |
| 检索反思循环 | 最多 3 轮 | engine.py |
| Redis TTL | 300 秒 | cache.py |
| IP 限流 | 20 次/60 秒 | ratelimit.py |
| LLM 降级链 | qwen → zhipu → deepseek | client.py |

---

## 2. 请求入口与限流（main.py）

### 2.1 HTTP 中间件顺序

```
CORS → rate_limit_middleware → 路由
```

### 2.2 端点清单

| 方法 | 路径 | 功能 | 限流 |
|------|------|------|------|
| GET | /ai/health | 健康检查 | 跳过 |
| GET | /ai/config | 返回配置（无密钥） | 有 |
| GET | /ai/chat/sessions | IP 会话列表 | 有 |
| GET | /ai/chat/sessions/{ip}/messages | IP 会话消息 | 有 |
| POST | /ai/rag/search | 知识库检索 | 有 |
| POST | /ai/rag/chat | 同步问答 | 有 |
| POST | /ai/rag/chat/stream | 流式问答 (SSE) | 有 |
| POST | /ai/rag/documents | 添加文档 | 有 |
| POST | /ai/rag/documents/upload | 上传 PDF | 有 |
| GET | /ai/documents | 文档列表（分页） | 有 |
| DELETE | /ai/documents/{doc_id} | 删除文档 | 有 |

### 2.3 IP 限流（滑动窗口）

- **算法**：内存 dict `{ip: [timestamp...]}`，滑动窗口剔除过期记录
- **阈值**：20 次 / 60 秒（ratelimit.py 常量，非配置项）
- **X-Forwarded-For**：取第一个 IP（最接近客户端）
- **分支**：
  - 超限 → 返回 **429** + `Retry-After` 头 + `retry_after` 秒数
  - 未超限 → 记录本次请求时间戳，放行
- **注意**：多实例部署时内存 dict 不共享 → 需换 Redis sorted set

### 2.4 会话保存（chat 同步链路）

`POST /ai/rag/chat` 处理后：
- **分支 A**：`message` 为 `casual_chat` / `realtime_not_implemented` → **不保存**会话
- **分支 B**：其他（knowledge 路径）且 answer 非空 → 追加 `{user, assistant}` 到 `IP_SESSION_MESSAGES[ip]`
- **上限**：`MAX_MESSAGES_PER_IP = 50`，超出裁剪最旧（`records[-50:]`）
- 会话是**内存态**（重启丢失），与后端 conversations/messages 表（Spring Boot 持久化）是两套体系

---

## 3. 意图路由（agent/router.py）

### 3.1 主流程

```
classify(query)
  ├─ query 空/纯空白 → {intent: knowledge, confidence: 0.0}（保守）
  ├─ LLM.generate(分类 prompt) → 解析 JSON
  └─ 任何异常 → {intent: knowledge, confidence: 0.0}（保守）
```

### 3.2 LLM 分类 prompt

- 三类：`knowledge`（需检索）/ `casual_chat`（闲聊）/ `realtime`（实时数据）
- 要求 LLM 返回 JSON：`{"intent", "confidence", "reason"}`

### 3.3 JSON 解析 `_parse_response`（多级回退）

1. `response.find("{")` → `rfind("}")` 提取 JSON 块
2. `json.loads` 解析
3. **intent 值校验**：不在 `(knowledge, casual_chat, realtime)` 内 → 强制 `knowledge`
4. 解析失败/异常 → `{intent: knowledge, confidence: 0.0}`

**降级哲学**：任何不确定都走 `knowledge`（宁可多检索，不要漏检）。

### 3.4 路由分支（调用方）

| intent | 行为 |
|--------|------|
| casual_chat | 直接 LLM 多轮 chat，返回 `message="casual_chat"` |
| realtime | 返回"正在开发中"，`message="realtime_not_implemented"` |
| knowledge | 进入检索+反思循环 |

---

## 4. LLM 多供应商降级链（llm/client.py + src/config.py）

### 4.1 供应商适配层

统一接口 `LLMClient`（抽象基类）：
- `generate(prompt)` → 单轮生成
- `chat(messages)` → 多轮对话
- `generate_stream(prompt)` → 流式生成（异步生成器）

客户端实现：
| 类 | 供应商 | 底层 | 说明 |
|----|--------|------|------|
| `ClaudeClient` | Anthropic | ChatAnthropic | 需 CLAUDE_API_KEY |
| `DeepSeekClient` | DeepSeek 官方 | ChatOpenAI | 独立 API |
| `QwenClient` | ModelScope | ChatOpenAI | `_ModelScopeBaseClient` 子类 |
| `ZhipuClient` | ModelScope | ChatOpenAI | `_ModelScopeBaseClient` 子类 |
| `ModelScopeClient` | ModelScope | ChatOpenAI | 兼容旧配置 |
| `FallbackClient` | 降级链 | 逐个尝试 | 见 4.3 |

### 4.2 异常包装

所有客户端方法：
- `LLMException(provider, message, cause)` 统一异常
- 构造时校验 API Key：缺失 → 立即抛 `LLMException`

### 4.3 FallbackClient 降级链（核心）

**默认链**：`qwen → zhipu → deepseek`（config.py `fallback_chain`，env `PW_FALLBACK_CHAIN`）

```
generate(prompt):
  for provider in chain:
    try:
      client = LLMFactory.get_client(provider)
      return await client.generate(prompt)   # 成功即返回
    except Exception as e:
      log warning → 尝试下一个
  raise 最后一个异常（或"降级链全部失败"）
```

- **generate / chat / generate_stream** 三个方法都有独立降级
- **generate_stream 细节**：`async for chunk` 正常 yield；流式中间异常 → 整个供应商失败，换下一个**重新开始流**
- `LLMFactory._instances` 缓存实例，`clear_cache()` 可重置（当前无运行时切换场景）

### 4.4 工厂解析

```
get_client(provider=None):
  provider = provider or settings.llm_provider   # 默认 "fallback"
  支持: claude | deepseek | modelscope | qwen | zhipu | fallback
  fallback → 解析 fallback_chain 逗号分隔 → FallbackClient
  未知 provider → ValueError
```

### 4.5 配置项（config.py）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| PW_LLM_PROVIDER | `fallback` | 默认供应商 |
| PW_FALLBACK_CHAIN | `qwen,zhipu,deepseek` | 降级链 |
| PW_CLAUDE_API_KEY / PW_CLAUDE_MODEL | — / `claude-sonnet-5-20251001` | Claude |
| PW_DEEPSEEK_API_KEY / _MODEL / _BASE_URL | — / `deepseek-chat` / `https://api.deepseek.com/v1` | DeepSeek |
| PW_MODELSCOPE_API_KEY / _BASE_URL | — / `https://api-inference.modelscope.cn/v1` | ModelScope 共用 |
| PW_QWEN_MODEL | `Qwen/Qwen3.5-35B-A3B` | Qwen |
| PW_ZHIPU_MODEL | `ZhipuAI/GLM-5.2` | GLM |

**注意**：`llm_provider` 显式设为单供应商时绕过降级链（单点）。改 `PW_FALLBACK_CHAIN` 可重排降级顺序。

---

## 5. 混合检索（rag/retriever.py + rag/embeddings.py）

### 5.1 链路位置

```
query → [EmbeddingService 云端 bge-m3 向量化]
      → [HybridRetriever] ── PG FTS (BM25 风格) ──┐
      │                     └─ pgvector 余弦相似度 ─┤
      → [min-max 归一化 + alpha 加权融合] ──┘
      → [Reranker] TopN 精排
```

### 5.2 EmbeddingService（云端，embeddings.py）

- **模型**：`OllmOne/bge-m3-GGUF`（ModelScope），1024 维
- **base_url**：`https://ms-ens-*.api-inference.modelscope.cn/v1`（专属 endpoint）
- **API Key**：优先 `PW_EMBEDDING_API_KEY`，回退 `PW_MODELSCOPE_API_KEY`
- **归一化**：返回向量做 L2 归一化（与 pgvector 余弦匹配）
- **接口**：
  - `embed_text(text)` → 单条
  - `embed_documents(texts)` → 批量（按输入顺序取前 len(valid) 条）
- **异常**：空文本抛异常；API 调用失败 → `EmbeddingException`
- **分支**：`_lazy_load` 惰性初始化客户端；首次调用建连

### 5.3 HybridRetriever.retrieve 主流程

```
retrieve(query, top_k, session=None):
  query 空 → RetrievalException
  query_embedding = embed_text(query)     # 失败 → RetrievalException
  fetch_k = top_k * 2                     # 2 倍召回
  session 有 → 复用；无 → 自动创建
```

### 5.4 双通道并行 + 降级

```python
fts_task, vector_task = _fts_search, _vector_search
asyncio.gather(..., return_exceptions=True)
```

分支处理：
- FTS 异常 → warning + `fts_results=[]`（降级为仅向量）
- 向量异常 → warning + `vector_results=[]`（降级为仅 FTS）
- 两路都空 → 返回 `[]`

### 5.5 FTS 检索（BM25 风格）

```sql
SELECT ..., ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) AS score
FROM documents
WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
  AND parent_id IS NOT NULL
ORDER BY score DESC LIMIT :limit
```

- **`simple` 配置**：不做词干化；中文按字分词（不理想，靠向量通道弥补；后续可换 zhparser）
- **过滤条件**：`parent_id IS NOT NULL`（只检索子块，父块无向量）

### 5.6 向量检索（pgvector 余弦）

```sql
SELECT ..., 1 - (embedding <=> :query_embedding) AS score
FROM documents
WHERE embedding IS NOT NULL AND parent_id IS NOT NULL
ORDER BY embedding <=> :query_embedding ASC LIMIT :limit
```

- `<=>` 余弦距离 → `1 - 距离` 转相似度
- `embedding IS NOT NULL` 过滤未向量化文档

### 5.7 分数归一化 `_normalize`

- **min-max 归一化到 [0,1]**（保持序关系，跨查询不可比）
- `score_range < 1e-9`（全同分/单条）→ 全部置 1.0

### 5.8 合并 + alpha 加权融合

- 按 doc id 合并双通道结果
- `hybrid_score = alpha * fts_score + (1-alpha) * vector_score`
- 排序取 top_k 返回
- 单文档同时命中两路时，两个分数都贡献

### 5.9 配置

| 项 | 值 | 位置 |
|----|-----|------|
| PW_HYBRID_SEARCH_ALPHA | 0.3 | config.py |
| fetch 倍数 | top_k * 2 | retriever.py 硬编码 |

---

## 6. 重排（rag/reranker.py）

### 6.1 模型

- `BAAI/bge-reranker-v2-m3`（本地 CrossEncoder，xlm-roberta，hidden 1024）
- 模型目录 `ai_service/models/bge-reranker-v2-m3/`
- ⚠️ **注意**：该目录当前**只有 tokenizer 无权重文件**（约 1GB 缺失）→ 运行时可能触发从 HuggingFace 下载或加载失败
- `_DEFAULT_MODEL`：本地目录存在则用本地路径，否则回退官方模型名

### 6.2 流程

```
rerank(query, documents, top_k=5):
  documents 空 → []
  _lazy_load() 加载 CrossEncoder
  pairs = [(query, doc.content) for doc]     # 逐对拼接
  scores = model.predict(pairs)              # CPU 批量推理
  附加 rerank_score → 按分降序 → 返回 top_k
```

### 6.3 异常

- 加载或推理失败 → `RerankerException`（上层 catch 后**使用原始排序**）
- 每对约 30-50ms CPU 推理，5 条约几百 ms

### 6.4 调用分支

| 场景 | 行为 |
|------|------|
| docs 为空 | 直接返回 [] |
| 重排异常 | 上层 catch → 保留检索原始顺序（engine._rerank / search 均有此分支） |

---

## 7. 反思与改写（agent/reflector.py）

### 7.1 反思 prompt

- 要求 LLM 返回 JSON：`{"sufficient": bool, "reason": str, "rewritten_query": str}`
- **倾向充分**：文档部分相关/间接相关 → sufficient=true；只有完全无关才 false
- 只传前 5 条文档摘要（各 200 字符）避免超上下文

### 7.2 check_sufficiency 分支

```
documents 空 → {sufficient: False, rewritten_query: query}   # 无文档 → 判定不充分
LLM.generate → _parse_check 解析
  解析成功 → 返回 parsed
  异常 → warning + {sufficient: True}（默认充分，防死循环）
```

### 7.3 _parse_check JSON 解析

- 提取 `{}` 块 → json.loads
- `sufficient = bool(result.get("sufficient", True))`（缺省 true）
- 不充分时附带 `rewritten_query`
- 解析失败 → `{sufficient: True}`

### 7.4 generate_answer / generate_answer_stream

- **history 处理**：取最近 6 条消息拼成 `历史对话:` 段
- **docs_detail**：每条带 `[N]` 引用编号 + title + source + content
- 空文档 → 直接返回"抱歉，未检索到相关信息。"
- 生成失败 → 返回"抱歉，回答生成时遇到问题，请稍后重试。"
- 流式版本：`async for token in client.generate_stream(prompt)` yield

### 7.5 Provider 选择（重要）

- `Reflector.__init__(provider=None)` → `self._provider = provider or "deepseek"`
- **固定用 DeepSeek**（注释说明 ModelScope 有 moderation 过滤问题；但注意降级链配置后此默认是硬编码 deepseek，而非 fallback）— **优化点：可改为走 fallback 链**

### 7.6 全局单例

`reflector = Reflector()` — 模块级单例

---

## 8. Graph RAG（rag/graph_store.py + rag/graph_extractor.py）

### 8.1 架构

```
文档入库 → [GraphExtractor.extract_from_document] 两步 LLM 提取实体/关系
        → [GraphStore] 写入 AGE 图 knowledge_graph
查询时  → [GraphExtractor.extract_from_query] 提取实体名
        → [GraphStore.search_related] 图遍历 → 关联文档
```

### 8.2 GraphStore 操作

| 方法 | 说明 | 分支 |
|------|------|------|
| ensure_graph | 建图（幂等） | 检查 ag_graph 表存在性 → 不存在才 create_graph；异常 → False |
| upsert_entity | 写实体节点 | **见 8.3** |
| upsert_relation | 写 RELATED_TO 边 | plain MERGE 幂等 |
| search_related | 图搜索 | 见 8.4 |

### 8.3 upsert_entity 关键实现（已修复）

**背景**：Apache AGE 1.6.0 **不支持** `MERGE ... ON CREATE/MATCH SET` 子句（语法错误）。

当前两步实现：
1. `MATCH (e:Entity {name, type}) RETURN e.name` → 检查存在
2. 不存在 → `CREATE`，`doc_ids: ['87']`（agtype 数组）
   已存在 → `MATCH ... WHERE NOT '87' IN e.doc_ids SET e.doc_ids = e.doc_ids || ['87']`

**doc_ids 存储格式**：agtype 数组（`["87","88"]`），`json.loads` 可直接解析 → 与 search_related 兼容

**分支**：
- 写入失败 → warning + return False（不抛出）
- 数组已含 doc_id → WHERE 不匹配，跳过追加（幂等）

### 8.4 search_related 图搜索

```
entities 空 → []
Cypher: MATCH (e:Entity) WHERE e.name IN [...]
        OPTIONAL MATCH (e)-[:RELATED_TO]->(related)
        RETURN COALESCE(related.doc_ids, e.doc_ids) LIMIT top_k*2
→ 解析 doc_ids 集合（json.loads）
→ 查 documents 表（parent_id IS NULL）→ 拼接 hybrid_score=0.6（固定值）
→ 异常 → warning + []（降级）
```

**注意**：`hybrid_score` 硬编码 0.6（**优化点**：无真实分数，图结果排序位置固定）

### 8.5 GraphExtractor 实体提取

**extract_from_document**（两步 LLM）：
1. 截断文档到 2000 字符 → `_ENTITY_PROMPT` 提取实体 JSON
2. entities 为空 → 直接返回空（不提取关系）
3. 实体名列表 → `_RELATION_PROMPT`（文档再截断到 1000 字符）提取关系
4. 任一异常 → warning + 返回空结构

**extract_from_query**：
- `_QUERY_ENTITY_PROMPT` 要求 LLM 返回逗号分隔实体名（非 JSON）
- 解析：按逗号拆分 → strip → 过滤单字符 → 取前 10 个
- 失败 → []

### 8.6 文档入库时的图更新（engine.add_document 尾部）

```
try:
  ensure_graph()
  extract_from_document(content)
  for 每个实体: upsert_entity(name, type, parent_id)
  for 每个关系: upsert_relation(src, tgt)
except Exception: warning + 跳过（不影响入库结果）
```

**分支**：Graph 更新失败不影响文档入库成功返回

---

## 9. 分块与入库（rag/chunker.py + engine.add_document）

### 9.1 父子两级分块 MarkdownChunker

**第一级**（父块）：`MarkdownHeaderTextSplitter` 按 `##` 标题分割
- metadata 保留 `{"section": "标题"}` → title = `" > ".join(title_parts)`
- `min_chars=50`：父块内容 < 50 字符 → 过滤

**第二级**（子块）：`RecursiveCharacterTextSplitter`
- `chunk_size=300`，`chunk_overlap=50`
- separators：`["\n\n", "\n", "。", ".", " ", ""]`

**边界分支**：
- 空文本 → `{parents: [], children: []}`
- 无 `##` 标题或全被过滤 → 返回空 → **engine 兜底**：整文档为单一父块 + 子块=父块内容

### 9.2 add_document 入库流程

```
校验 title/content 非空（否则 ValueError）
content_hash = SHA256(content)
检测重复: title 完全匹配 OR content_hash 匹配 → return {duplicate: True, id: 已有id}
  （注意：已存在的父块标题通常被拼成 "title > section"，可能与新 title 不匹配 → 主要靠 hash 去重）

分块 → parents / children
（无父块 → 兜底单父块单子块）

事务内:
  1. 插入父块（embedding=None, parent_id=NULL）
  2. flush 获取父块 DB ID
  3. embedding_service.embed_documents(child_texts)   # 批量向量化（可能失败 → 回滚）
  4. 插入子块（embedding + parent_id）
  5. commit（原子）
  异常 → rollback + RuntimeError("文档入库失败")
```

**注意**：embedding 失败会回滚父块（事务原子性，不产生残缺记录）

### 9.3 元数据统计表（新建）

**rag_config**（key-value，10 条初始配置）：
| config_key | value | 说明 |
|------------|-------|------|
| embedding_model | OllmOne/bge-m3-GGUF | 嵌入模型 |
| embedding_dim | 1024 | 向量维度 |
| chunk_size | 300 | 子块字符数 |
| chunk_overlap | 50 | 重叠 |
| min_chars | 50 | 父块最小字符 |
| reranker_model | BAAI/bge-reranker-v2-m3 | 重排模型 |
| rerank_top_k | 5 | 精排保留 |
| hybrid_search_alpha | 0.3 | 混合权重 |
| graph_name | knowledge_graph | 图名 |
| llm_provider | fallback | 降级链 |

**document_chunk_stats**（每父块文档一行）：
- document_id / title / source / parent_count / child_count / embedding_dim / chunk_size / chunk_overlap / created_at
- UNIQUE(document_id)，`ON CONFLICT DO UPDATE child_count`

---

## 10. 缓存（src/cache.py）

### 10.1 设计

- 只缓存 `_retrieve()` 的检索结果（流式链路），**chat 同步链路不缓存**
- key：`rag:retrieve:{SHA256(query)[:12]}`
- TTL：300 秒
- **懒连接**：首次 get/set 时连接，失败标记 `_connected=False`

### 10.2 分支（全部静默降级）

| 操作 | 分支 |
|------|------|
| get | Redis 不可用/连接失败 → None（正常走检索） |
| get | key 不存在 → None |
| set | Redis 不可用 → False（不抛异常） |
| 任何异常 | catch + `_connected=False` + 释放连接 + 降级 |

### 10.3 失效模式

- 缓存 key 只含 query hash，**不含 top_k** → 不同 top_k 可能复用错误结果（**优化点**）
- 文档更新后缓存不主动失效（TTL 兜底）

---

## 11. 端到端时序：chat 同步链路（engine.chat）

```
POST /ai/rag/chat
  → rate_limit_middleware (429 或放行 + 记录 IP)
  → rag_engine.chat(request)

  ├─ 1. 意图识别
  │    router_agent.classify(query)
  │    ├─ casual_chat → LLM.chat(系统提示+history+query) → ChatResponse(message="casual_chat") [不保存会话]
  │    ├─ realtime   → ChatResponse("正在开发中", message="realtime_not_implemented") [不保存会话]
  │    └─ knowledge  → 继续 ↓

  ├─ 2. 检索+反思循环（最多 3 轮）
  │    for round in 0..2:
  │      docs = wait_for(retrieve(current_query, top_k=20), 15s)   # 超时抛异常
  │      docs = rerank(current_query, docs, top_k=5)                # 异常 → 原始排序
  │      去重合并到 all_docs (seen_ids)
  │      if round < 2:
  │        check = wait_for(reflector.check_sufficiency, 10s)      # 超时 → 外层异常
  │        sufficient → break
  │        rewritten 非空且≠current → current_query=rewritten 继续
  │        else → break
  │    第 3 轮后循环自然结束
  │    注：第 2 步任何 wait_for 超时/异常 → 跳到外层 except → "抱歉，我暂时无法回答"

  ├─ 3. 父块映射 _expand_to_parents(all_docs)
  │    parent_id 为 NULL（旧格式）→ 直接通过
  │    parent_id 非空 → 收集 → 查父块 → 用子块最高分作为父块分数 → 去重降序

  ├─ 4. 降级：docs 为空
  │    LLM.generate("知识库暂无相关信息，请如实告知用户")
  │    → ChatResponse(answer, sources=[], message="ok")

  ├─ 5. 生成答案
  │    reflector.generate_answer(query, docs, history)
  │    失败 → "抱歉，回答生成时遇到问题"
  │    sources = 前 5 篇 docs，ref_index 1..5

  └─ 6. 保存会话（message != casual/realtime 且 answer 非空）

  全局异常 → ChatResponse("抱歉，我暂时无法回答这个问题", message="internal_error" 或 f"error:{e}" 当 debug)
```

---

## 12. 端到端时序：stream 流式链路（chat_stream）

```
POST /ai/rag/chat/stream → StreamingResponse(SSE)

event_stream():
  Step1 意图识别:
    classify → yield step {intent}
    ├─ casual_chat → LLM.generate_stream(系统提示) → token 事件 → done → return
    └─ knowledge → continue

  Step2 检索:
    docs = rag_engine._retrieve(query, top_k=20)
      ├─ Redis 缓存命中 → 直接返回缓存 docs
      ├─ HyDE: _hyde_expand(query)   # LLM 生成假设回答, 10s 超时→原 query, 异常→原 query
      ├─ Round0: 并行 [vector retrieve + graph search] + extract_from_query
      │   graph_extractor 失败 → [] （图通道静默降级）
      ├─ Round1/2: 仅向量检索（15s 超时/异常 → break）
      ├─ 反思: check_sufficiency 用原始 query（10s 超时/异常 → break）
      ├─ 父块映射 → 低分过滤(>=min_score=0.6)
      └─ 写缓存 (docs 非空时, TTL 300)
    yield step {retrieval} (count, relevant>=0.3, previews 前5)
    docs 空 → LLM.generate_stream("知识库暂无相关信息") → token → done → return

  Step3 Rerank:
    docs = _rerank(query, docs)   # 异常 → 原始排序
    yield step {rerank} (before/after)

  Step4 反思:
    check = reflector.check_sufficiency(query, docs)
    yield step {reflection} (sufficient/reason/rewritten_query)

  Step5 流式生成:
    reflector.generate_answer_stream(query, docs, history) → token 事件逐字

  Step6 引用:
    sources = 前5篇 → done 事件 {sources}

  全局异常 → error 事件 {message: "服务暂时不可用"}
```

### 12.1 _retrieve 完整分支树

```
_retrieve(query, top_k=30, min_score=0.6):
  缓存命中 → return cached
  hyde_query = _hyde_expand(query)
  all_docs=[], existing_ids=set, current_query=query
  for round 0..2:
    search_text = hyde_query (round 0) else current_query
    round 0:
      entities = extract_from_query(query)         # 失败 → []
      [vector_task (15s wait_for), graph_task] 并行 gather
        - vector 超时 → gather 抛 TimeoutError → 外层异常 → 整体失败
        - vector 异常 → gather 抛 → 整体失败
        - graph 异常 → search_related 内部降级返回 []
      合并: 向量优先 + 图结果追加去重
    round 1/2:
      retrieve 15s wait_for
      超时 → break; 异常 → break
    合并去重
    if round < 2:
      check = wait_for(reflector.check_sufficiency(query, docs), 10s)
        - 超时 → break
        - 异常 → break
        - sufficient → break
        - rewritten 空/相同 → break
        - 否则 current_query = rewritten
  docs = _expand_to_parents(all_docs)
  低分过滤 (>= min_score)
  缓存写入 (非空时)
  return docs
```

---

## 13. 全部降级路径汇总表

| # | 触发点 | 触发条件 | 降级行为 |
|---|--------|----------|----------|
| 1 | 意图路由 | LLM 分类失败/解析失败/空查询 | 保守走 knowledge |
| 2 | 意图路由 | intent 值非法 | 强制 knowledge |
| 3 | LLM Fallback | 某供应商调用失败 | 切下一个供应商 |
| 4 | LLM 构造 | API Key 缺失 | 抛 LLMException → 外层 catch |
| 5 | 混合检索 | FTS 失败 | 仅向量检索 |
| 6 | 混合检索 | 向量检索失败 | 仅 FTS |
| 7 | 混合检索 | 两路都失败 | 返回 [] |
| 8 | 向量化 query | embed_text 失败 | RetrievalException → 上层 catch |
| 9 | Rerank | 重排异常 | 使用原始排序 |
| 10 | 反思 | LLM 检查异常 | 默认 sufficient=True |
| 11 | 反思解析 | JSON 解析失败 | 默认 sufficient=True |
| 12 | 反思 | 文档为空 | 判定不充分 + rewritten=原query |
| 13 | 生成 | 文档为空 | 直接 LLM"暂无相关信息" |
| 14 | 生成 | LLM 失败 | "回答生成时遇到问题" |
| 15 | Graph 图搜索 | AGE 不可用 | 返回 []（不影响向量检索） |
| 16 | Graph 实体提取 | LLM 失败 | 返回空 |
| 17 | Graph 写库 | 写入失败 | warning + 跳过 |
| 18 | 文档入库 | embedding 失败 | rollback + RuntimeError |
| 19 | Redis 缓存 | 连接失败/读写失败 | 静默降级，正常检索 |
| 20 | HyDE | LLM 超时/失败 | 用原始 query |
| 21 | _retrieve 检索 | 15s 超时 | break 提前结束 |
| 22 | _retrieve 反思 | 10s 超时/异常 | break 提前结束 |
| 23 | _retrieve 低分 | 分数 < 0.6 | 过滤丢弃 |
| 24 | chat 全局异常 | 任何未捕获异常 | "抱歉，我暂时无法回答" |
| 25 | stream 全局异常 | 任何未捕获异常 | error SSE 事件 |
| 26 | PDF 上传 | 非 PDF | code=1 |
| 27 | PDF 上传 | 空文件 | code=2 |
| 28 | PDF 上传 | PyMuPDF 缺失 | code=3 |
| 29 | PDF 上传 | 解析异常 | code=3 |
| 30 | IP 限流 | 超 20 次/60s | 429 + Retry-After |

---

## 14. 全部超时点汇总表

| # | 位置 | 超时值 | 超时行为 |
|---|------|--------|----------|
| 1 | chat 检索 | 15s | 抛异常 → 全局 except |
| 2 | chat 反思 | 10s | 抛异常 → 全局 except |
| 3 | stream 向量检索 (round 0) | 15s | gather 抛 → 全局 error 事件 |
| 4 | stream 二次检索 (round 1/2) | 15s | break 提前结束检索 |
| 5 | stream 反思 | 10s | break 提前结束 |
| 6 | HyDE | 10s | 用原始 query |
| 7 | LLM 客户端 | 120s (ChatOpenAI/ChatAnthropic timeout) | 抛异常 → 降级链/外层 |
| 8 | Redis 连接 | 3s socket_connect + 3s socket | 缓存不可用 |
| 9 | 嵌入客户端 | 60s (AsyncOpenAI timeout) | 抛 EmbeddingException |
| 10 | Spring 转发 (配置) | connect 5s / read 30s | 未实现实际调用 |

---

## 15. 配置参数总表

### 15.1 环境变量（config.py，前缀 PW_）

| 变量 | 默认值 | 用途 |
|------|--------|------|
| PW_DATABASE_URL | postgresql+asyncpg://postgres:postgres123@localhost:5432/personal_website | 数据库 |
| PW_REDIS_URL | redis://localhost:6379/0 | Redis |
| PW_LLM_PROVIDER | fallback | 默认 LLM 供应商 |
| PW_FALLBACK_CHAIN | qwen,zhipu,deepseek | 降级链 |
| PW_CLAUDE_API_KEY / PW_CLAUDE_MODEL | — / claude-sonnet-5-20251001 | Claude |
| PW_DEEPSEEK_API_KEY / _MODEL / _BASE_URL | — / deepseek-chat / api.deepseek.com/v1 | DeepSeek |
| PW_MODELSCOPE_API_KEY / _BASE_URL | — / api-inference.modelscope.cn/v1 | ModelScope |
| PW_QWEN_MODEL | Qwen/Qwen3.5-35B-A3B | Qwen |
| PW_ZHIPU_MODEL | ZhipuAI/GLM-5.2 | GLM |
| PW_EMBEDDING_API_KEY / _BASE_URL / _MODEL | — / — / OllmOne/bge-m3-GGUF | 云端嵌入 |
| PW_HYBRID_SEARCH_ALPHA | 0.3 | 混合检索 FTS 权重 |
| PW_DEBUG | False | 调试模式（影响错误透出） |

### 15.2 代码常量

| 常量 | 值 | 位置 |
|------|-----|------|
| chunk_size / chunk_overlap / min_chars | 300 / 50 / 50 | chunker.py |
| fetch_k 倍数 | top_k * 2 | retriever.py |
| chat 检索循环 | range(3) | engine.py |
| chat top_k | 20 | engine.py |
| stream _retrieve top_k | 20 | main.py |
| _retrieve min_score | 0.6 | engine.py |
| stream MIN_SCORE (相关) | 0.3 | main.py |
| Rerank top_k | 5 | 多处 |
| Redis TTL | 300s | cache.py |
| 限流阈值 | 20次/60s | ratelimit.py |
| MAX_MESSAGES_PER_IP | 50 | main.py |
| Graph RELEVANCE_THRESHOLD | 0.5 | graph.py |
| Graph FILTER_THRESHOLD | 0.6 | graph.py |
| Graph RETRIEVE_TOP_K | 30 | graph.py |
| Graph RERANK_TOP_K | 5 | graph.py |
| 反思 history 截断 | 最近 6 条 | reflector.py |
| 实体提取截断 | 2000 / 1000 字符 | graph_extractor.py |

---

## 16. 优化建议清单

### P0（正确性 / 明显缺陷）

1. **Reflector 固定用 deepseek**，不走 fallback 链 → 改 `provider or "fallback"` 或继承默认，避免单点
2. **Reranker 本地模型缺权重文件**（`models/bge-reranker-v2-m3/` 无 safetensors）→ 补权重或确认运行时下载
3. **检索缓存 key 不含 top_k** → key 加 top_k，避免不同参数复用错误结果
4. **图搜索 hybrid_score 硬编码 0.6** → 可考虑融合真实相关度或调整排序权重

### P1（健壮性）

5. **chat 同步链路无 Redis 缓存**（只有 stream 的 _retrieve 有）→ 两链路缓存策略不一致，可统一
6. **内存态 IP 会话/限流** 多实例不共享 → 换 Redis
7. **中文 FTS 用 simple 配置**分词差 → 评估 zhparser / jieba FTS
8. **`settings.local.json` 损坏**（转义乱码）→ 修复或删除，避免 Claude Code 配置加载异常
9. **流式链路 round 0 的向量检索超时是致命的**（无内部降级）→ 与 round 1/2 一致降级为 break

### P2（性能 / 体验）

10. **反思 + HyDE + 检索**每轮多次 LLM 串行调用，延迟高 → 引入并行 / 超时缩短 / 提前终止策略
11. **父块映射每请求多次 DB 查询**（engine 用循环内查）→ 批量 IN 一次取回
12. **`document_chunk_stats` 与入库流程未联动**（目前是手动脚本填充）→ 在 add_document 提交后自动 upsert
13. **降级链日志**只记 warning 无统计 → 加供应商调用计数/成功率指标
14. **图实体提取的 doc_ids 用字符串数组** → 可考虑 AGE 原生 int[] 或类型化 agtype

### P3（配置化）

15. 大量魔法数字（top_k、min_score、阈值）硬编码 → 提升到 config / rag_config 表
16. **限流阈值、Rerank top_k、反思轮数** → 从 rag_config 表动态读取
17. **PDF 上传大小限制**未设 → 增加文件大小校验

---

## 附录：模型与文件位置

| 项 | 位置 | 说明 |
|----|------|------|
| 嵌入模型 | 云端 ModelScope | OllmOne/bge-m3-GGUF，1024 维 |
| 重排模型 | `ai_service/models/bge-reranker-v2-m3/` | 缺权重（见 P0-2） |
| 旧嵌入模型残留 | `ai_service/models/sentence-transformers_all-MiniLM-L6-v2/` | 已不用（384 维） |
| 元数据表 SQL | `ai_service/rag_metadata_tables.sql` | rag_config + document_chunk_stats |
| 建表脚本 | `ai_service/create_metadata_tables.py` | 可重复执行 |
| Graph 补跑脚本 | `ai_service/backfill_graph.py` | 历史文档实体提取 |
