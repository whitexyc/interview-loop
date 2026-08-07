"""
RAG 知识库引擎 — 核心编排层
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置（最上层编排器）：
  用户 Query
    → [Router Agent] 意图分类 ─── 闲聊 ──→ 直接 LLM 回答
    │                               ├─ 实时 ──→ 🔜 module-006
    │                               └─ 知识库 ──→ [HybridRetriever] BM25+向量
    │                                              → [Reranker] Top20→Top5
    │                                              → [Reflector] 反思→改写→二次检索
    │                                              → [LLM] 生成答案+引用溯源
    └──────────────────────────────────────────────────────────────→ ChatResponse

设计思路：
  本文件是 RAG 链路的"总导演"，不实现具体算法，而是把各个独立模块
  （检索、重排、反思、生成）按正确顺序串联起来。每个步骤失败时都有
  降级策略（fallback），保证系统的鲁棒性。
"""
import asyncio
import hashlib
import logging

from sqlalchemy import select

from src.config import settings
from src.database import async_session_factory
from llm.client import LLMFactory
from src.cache import cache
from rag.schemas import SearchRequest, SearchResponse, ChatRequest, ChatResponse, ChatSteps
from rag.models import Document
from rag.embeddings import embedding_service
from rag.text_tokenizer import tokenize
from rag.retriever import hybrid_retriever
from rag.reranker import reranker
from rag.chunker import chunker
from agent.router import router_agent
from agent.reflector import reflector
from rag.graph_store import graph_store
from rag.graph_extractor import graph_extractor
from rag.memory import memory_service, format_memory_line
from rag.memory_extractor import extract_facts
from rag.session_memory import session_memory_service

logger = logging.getLogger(__name__)

# HyDE (Hypothetical Document Embeddings) 提示词
# LLM 先根据用户问题生成一段假设性回答，然后用这个假设回答的语义向量
# 代替原始问题去做检索。因为假设回答模仿了知识库文档的语言风格，
# 所以能更精准地匹配到相关文档。
_HYDE_PROMPT = """你是一个知识库助手。根据用户问题，写一段2-3句话的假设性回答。
这段回答不是给用户看的，而是用来在知识库中检索相关文档。
请模仿知识库文档的语言风格来写。

用户问题: {query}

假设回答（2-3句话）:"""


def _retrieve_cache_key(query: str, top_k: int, min_score: float) -> str:
    """生成检索缓存键：query + top_k + min_score 共同决定

    检索结果依赖 top_k/min_score，不同参数若复用同一 key 会返回
    错误结果，故 hash 输入必须纳入这两个参数。前缀保持
    "rag:retrieve:" 不变，供 cache.delete_by_prefix 前缀失效。
    16 位十六进制 = 64 bits，碰撞概率足够低。

    Args:
        query: 用户查询
        top_k: 每次检索的候选数
        min_score: 低分过滤阈值

    Returns:
        形如 "rag:retrieve:<sha256 前 16 位>" 的缓存键
    """
    digest = hashlib.sha256((query + str(top_k) + str(min_score)).encode()).hexdigest()
    return f"rag:retrieve:{digest[:16]}"


# ── 检索延迟优化（module-024）配置常量 ──
_RETRIEVE_BUDGET_SECONDS = 30.0  # 整链路检索总预算（秒），超预算用已收集 docs 提前结束
_MIN_DOCS_SKIP_REFLECT = 3       # round 0 已收集文档数达到该值，跳过反思与后续轮次
_HYDE_CACHE_TTL = 300            # HyDE 缓存 TTL（秒），与检索结果缓存一致


def _hyde_cache_key(query: str) -> str:
    """生成 HyDE 缓存键：仅由 query 决定，与检索结果缓存 key 独立

    前缀 "rag:hyde:" 与检索缓存 "rag:retrieve:" 不同，互不污染；
    HyDE 结果只依赖 query（与 top_k/min_score 无关），故 key 不含参数。

    用 sha256 而非 Python 内置 hash()：内置 hash 受 PYTHONHASHSEED
    影响跨进程不稳定，Redis 缓存跨进程共享时会永远 miss。
    12 位十六进制 = 48 bits，碰撞概率足够低。

    Args:
        query: 用户查询

    Returns:
        形如 "rag:hyde:<sha256 前 12 位>" 的缓存键
    """
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
    return f"rag:hyde:{digest[:12]}"


class RAGEngine:
    """RAG 检索与问答引擎

    职责：串联整个 RAG 流水线。
    注意：本类不持有状态，所有请求都是独立的（无状态设计），
    方便横向扩展和测试。
    """

    async def search(self, request: SearchRequest) -> SearchResponse:
        """知识库检索：混合检索 → Rerank

        纯检索路径（不生成回答），供前端知识库搜索面板使用。
        搜索链路较短，只做召回+排序，不做 LLM 生成。
        """
        logger.info("RAG search: query=%s, top_k=%d", request.query, request.top_k)

        try:
            # 限制 top_k 范围，防止恶意请求打爆数据库
            top_k = max(1, min(request.top_k, 50))

            # 先取 2 倍数量，给 rerank 留出裁剪空间
            # 因为 rerank 比 embedding 更准，但速度慢，所以先粗筛再精排
            results = await hybrid_retriever.retrieve(
                request.query, top_k=top_k * 2 if top_k > 1 else top_k,
            )

            # 有足够候选时才做 rerank，否则直接返回
            if results and top_k < len(results):
                try:
                    results = await reranker.rerank(request.query, results, top_k=top_k)
                except Exception as e:
                    logger.warning("Rerank 失败，使用原始排序: %s", e)
            elif not results:
                return SearchResponse(results=[], message="未检索到相关内容")

            # 父块映射：子块命中 → 父块返回（完整 section 语义）
            results = await self._expand_to_parents(results)

            # 格式化输出：限制 content 长度，避免前端渲染大量文本
            output = []
            for doc in results:
                output.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:500],
                    "source": doc.get("source", ""),
                    "score": round(
                        doc.get("hybrid_score", doc.get("rerank_score", 0.0)), 4
                    ),
                })

            return SearchResponse(results=output, message="ok")
        except Exception as e:
            logger.error("检索失败: %s", e, exc_info=True)
            return SearchResponse(results=[], message="检索服务暂不可用")

    async def chat(self, request: ChatRequest, identity: str = "unknown") -> ChatResponse:
        """RAG 问答：意图路由 → 检索+反思循环（最多 3 轮）→ 生成

        手写循环替代 LangGraph（更直观的流程控制）：
        1. 意图识别 → 闲聊/实时走快捷路径
        2. 检索+反思循环（最多 3 轮）：
           - 每轮检索 → rerank → 去重 → 反思检查
           - 不充分则改写 query 继续
           - 充分或达到上限则结束
        3. 用收集到的所有文档生成答案 + 引用溯源

        长期记忆（module-023）：意图识别后调用 memory.recall(query, identity)，
        命中记忆以"历史记忆: ..."拼入生成 prompt；无记忆/召回失败时不注入，
        行为与之前完全一致（零回归）。

        Args:
            request: 聊天请求
            identity: 请求身份标识（user_id 优先，否则 client_ip；用于按身份隔离检索长期记忆）
        """
        logger.info("RAG chat: query=%s, history=%d", request.query, len(request.history))

        try:
            # ========== 1. 意图识别 ==========
            intent_result = await router_agent.classify(request.query)
            intent = intent_result.get("intent", "knowledge")
            intent_labels = {"knowledge": "知识库", "casual_chat": "闲聊", "realtime": "实时数据"}

            # 实时数据路径：直接返回，不召回记忆（review #5，避免无谓的 5s 召回延迟）
            if intent == "realtime":
                return ChatResponse(answer="实时数据查询功能正在开发中，请稍后再试。",
                    sources=[], message="realtime_not_implemented")

            # ========== 1.5 长期记忆召回（module-023；闲聊/知识库路径，失败降级为空） ==========
            memory_text = await self._recall_memory(request.query, identity)

            # 闲聊路径
            if intent == "casual_chat":
                client = LLMFactory.get_client()
                system_prompt = "你是张三个人网站的 AI 助手，友好地回答用户的问题。"
                if memory_text:
                    system_prompt += f"\n\n{memory_text}"
                answer = await client.chat([
                    {"role": "system", "content": system_prompt},
                    *request.history,
                    {"role": "user", "content": request.query},
                ])
                return ChatResponse(answer=answer, sources=[], message="casual_chat")

            # ========== 2. 检索+反思循环（最多 3 轮） ==========
            current_query = request.query
            all_docs: list[dict] = []
            seen_ids: set[int] = set()

            for round_num in range(3):
                docs = await asyncio.wait_for(
                    hybrid_retriever.retrieve(current_query, top_k=20),
                    timeout=15,
                )
                docs = await reranker.rerank(current_query, docs, top_k=5)
                for d in docs:
                    doc_id = d.get("id")
                    if doc_id and doc_id not in seen_ids:
                        all_docs.append(d)
                        seen_ids.add(doc_id)

                if round_num < 2:
                    check = await asyncio.wait_for(
                        reflector.check_sufficiency(current_query, docs),
                        timeout=10,
                    )
                    if check.get("sufficient", True):
                        break
                    rewritten = check.get("rewritten_query", "")
                    if rewritten and rewritten != current_query:
                        current_query = rewritten
                    else:
                        break

            docs = all_docs

            # 父块映射：子块命中 → 父块返回（完整 section 语义）
            docs = await self._expand_to_parents(docs)

            # ========== 3. 降级：无结果时直接 LLM ==========
            if not docs:
                client = LLMFactory.get_client()
                prompt = f"用户问：{request.query}\n\n知识库暂无相关信息，请如实告知用户。"
                if memory_text:
                    prompt = f"{memory_text}\n\n{prompt}"
                answer = await client.generate(prompt)
                self._schedule_persist(request, answer, identity)
                # module-034：knowledge 路径异步持久化会话轮次（不阻塞响应）
                self._schedule_session_persist(identity, request.query, answer)
                return ChatResponse(answer=answer, sources=[], message="ok")

            # ========== 4. 生成答案 + 引用溯源 ==========
            # module-034：会话恢复优先持久化（刷新/换设备不丢）；无持久化会话
            # 时回退当前请求 history（零回归）
            effective_history = await self._resolve_session_history(identity, request.history)
            answer = await reflector.generate_answer(
                request.query, docs, history=effective_history, memory=memory_text,
            )
            # module-039：证据链验证——逐句检查答案是否被检索文档支持
            verified = await reflector.verify_answer(answer, docs)
            # module-033：knowledge 路径生成答案后异步触发长期记忆自动写入
            #（fire-and-forget，不阻塞响应；casual_chat/realtime 已在分支提前返回）
            self._schedule_persist(request, answer, identity)
            # module-034：异步持久化会话轮次（不阻塞响应）
            self._schedule_session_persist(identity, request.query, answer)

            sources = []
            for i, doc in enumerate(docs[:5]):
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:300],
                    "source": doc.get("source", ""),
                    "ref_index": i + 1,
                })

            return ChatResponse(answer=answer, sources=sources, verified_claims=verified, message="ok")

        except Exception as e:
            logger.error("RAG chat 失败: %s", e, exc_info=True)
            return ChatResponse(
                answer="抱歉，我暂时无法回答这个问题，请稍后重试。",
                sources=[],
                verified_claims=None,
                message="internal_error" if not settings.debug else f"error: {e}",
            )

    async def _recall_memory(self, query: str, identity: str, top_k: int = 5) -> str:
        """召回长期记忆 + 短期记忆并格式化为生成 prompt 片段

        module-023/033：长期记忆（"历史记忆"段，'[长期记忆 - YYYY-MM-DD]：内容'）。
        module-034：短期记忆（"最近上下文"段，'[短期记忆 - YYYY-MM-DD]：内容'），
        两段均按身份隔离检索（memory_service.recall / recall_short）。长期在前、
        短期在后，帮助模型区分"持久偏好"与"最近上下文"；任一召回失败/为空 →
        跳过对应段；两者皆空 → 返回 ""。失败/超时/无记忆时返回空串，生成 prompt
        不包含记忆段，与无记忆时行为完全一致（零回归）。

        Args:
            query: 用户当前问题
            identity: 请求身份标识（user_id 优先，否则 client_ip）
            top_k: 最多召回记忆条数（长/短各最多 top_k 条）

        Returns:
            "历史记忆:\n[长期记忆 - 日期]：内容...\n\n最近上下文:\n[短期记忆 - 日期]：内容..."
            格式字符串；无记忆/失败返回 ""
        """
        if not identity:
            return ""
        long_text = ""
        try:
            memories = await asyncio.wait_for(
                memory_service.recall(query, identity, top_k=top_k),
                timeout=5,
            )
            if memories:
                long_text = "历史记忆:\n" + "\n".join(format_memory_line(m) for m in memories)
        except Exception as e:
            logger.warning("长期记忆召回失败，跳过注入: %s", e)
        short_text = ""
        try:
            short_memories = await asyncio.wait_for(
                memory_service.recall_short(query, identity, top_k=top_k),
                timeout=5,
            )
            if short_memories:
                short_text = "最近上下文:\n" + "\n".join(
                    format_memory_line(m, label="短期记忆") for m in short_memories)
        except Exception as e:
            logger.warning("短期记忆召回失败，跳过注入: %s", e)
        sections = [s for s in (long_text, short_text) if s]
        return "\n\n".join(sections)

    def _schedule_persist(self, request: ChatRequest, answer: str, identity: str) -> None:
        """knowledge 路径生成答案后异步触发长期记忆写入（fire-and-forget）

        intent=knowledge 且 answer 非空才触发；casual_chat / realtime 已在
        前置分支提前返回，不会走到本方法（闲聊/实时不提取）。asyncio.create_task
        只调度不 await，写入后台进行不阻塞响应；后台任务异常全部在
        _persist_memory 内降级捕获，绝不抛回响应（零回归）。

        Args:
            request: 聊天请求（含 query / history）
            answer: 生成的答案文本
            identity: 请求身份（user_id 优先，否则 client_ip）
        """
        if identity and answer and answer.strip():
            asyncio.create_task(
                self._persist_memory(request.query, answer, identity, request.history)
            )

    async def _persist_memory(self, query: str, answer: str, identity: str,
                              history: list[dict] | None = None) -> None:
        """对话结束后异步提取并写入长期 + 短期记忆（module-033/034，失败降级）

        内部流程：extract_facts(query, answer, history) → 逐条
        memory_service.save(content, identity, dedup=True)（长期，语义去重）+
        memory_service.save_short(content, identity, dedup=True)（短期，TTL 7 天）。
        提取失败/超时返回空 facts → 不写任何记忆；单条 save/save_short 失败仅
        日志降级，不影响其余事实与对话响应。

        Args:
            query: 用户问题
            answer: 助手回答（非空才提取）
            identity: 请求身份（user_id 优先，否则 client_ip）
            history: 最近对话历史（可选）
        """
        if not answer or not answer.strip():
            return  # 空答案不提取（防御：调用方已按 answer 非空触发）
        try:
            facts = await extract_facts(query, answer, history or [])
        except Exception as e:
            logger.warning("长期记忆提取失败，跳过写入: %s", e)
            return
        if not facts:
            return
        long_saved = 0
        short_saved = 0
        for fact in facts:
            # 长期记忆：持久偏好（无 TTL，module-033）
            try:
                await memory_service.save(fact["content"], identity, dedup=True)
                long_saved += 1
            except Exception as e:
                logger.warning("长期记忆写入失败（降级）: %s", e)
            # 短期记忆：最近主题/会话摘要（TTL 7 天，module-034）
            try:
                await memory_service.save_short(fact["content"], identity, dedup=True)
                short_saved += 1
            except Exception as e:
                logger.warning("短期记忆写入失败（降级）: %s", e)
        logger.info("长期记忆自动写入完成: identity=%s, facts=%d, saved=%d",
                    identity, len(facts), long_saved)
        logger.info("短期记忆自动写入完成: identity=%s, facts=%d, saved=%d",
                    identity, len(facts), short_saved)

    async def _resolve_session_history(self, identity: str,
                                       request_history: list[dict]) -> list[dict]:
        """会话恢复：优先持久化会话历史，无则用当前请求 history（零回归）

        module-034：get_session_messages 恢复最近会话（按身份隔离）；持久化会话
        存在 → 用它作生成历史（刷新/换设备不丢）；否则回退当前请求 history（与
        module-034 之前行为完全一致）。恢复失败/超时/身份为空 → 回退当前请求。

        Args:
            identity: 请求身份（user_id 优先，否则 client_ip）
            request_history: 当前请求携带的历史

        Returns:
            用于生成的有效历史列表（持久化会话优先）
        """
        if not identity:
            return request_history or []
        try:
            persisted = await asyncio.wait_for(
                session_memory_service.get_session_messages(
                    identity, limit=settings.memory_session_history_limit),
                timeout=3,
            )
        except Exception as e:
            logger.warning("会话恢复失败，使用当前请求 history: %s", e)
            persisted = []
        if persisted:
            return persisted
        return request_history or []

    def _schedule_session_persist(self, identity: str, query: str, answer: str) -> None:
        """knowledge 路径生成答案后异步持久化会话轮次（fire-and-forget）

        module-034：save_session_messages 写入 source='memory:<identity>:session:'，
        供刷新/换设备恢复。asyncio.create_task 只调度不 await，写入后台进行不
        阻塞响应；后台任务异常全部在 _persist_session 内降级捕获，绝不抛回响应
        （零回归）。

        Args:
            identity: 请求身份（user_id 优先，否则 client_ip）
            query: 用户问题
            answer: 助手回答（非空才持久化）
        """
        if identity and query and answer and answer.strip():
            asyncio.create_task(self._persist_session(query, answer, identity))

    async def _persist_session(self, query: str, answer: str, identity: str) -> None:
        """会话轮次持久化（写入用户问题 + 助手回答各一条，失败降级）

        Args:
            query: 用户问题
            answer: 助手回答
            identity: 请求身份（user_id 优先，否则 client_ip）
        """
        try:
            await session_memory_service.save_session_messages(identity, [
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ])
        except Exception as e:
            logger.warning("会话持久化失败（降级，不影响对话）: %s", e)

    async def _hyde_expand(self, query: str) -> str:
        """使用 LLM 生成假设性回答作为检索查询（module-024 起带 Redis 缓存）

        HyDE (Hypothetical Document Embeddings) 策略：
        用户查询通常简短，而知识库文档是长文本段落。
        让 LLM 先生成一段假设回答，模仿文档的语言风格和篇幅，
        用这个假设回答的向量去检索，能显著提升召回率。

        module-024 缓存：
        1. 先查 HyDE 缓存（key=rag:hyde:<sha256(query)[:12]>），命中直接复用
        2. 未命中 → LLM 生成 → 写入缓存（TTL 300s）
        3. 失败/超时 → 降级返回原始 query（原有行为不变）
        Redis 不可用时 cache.get/set 内部降级返回 None/False，不阻塞主链路。

        Args:
            query: 用户原始查询

        Returns:
            假设性回答文本；失败或超时时降级返回原始 query
        """
        hyde_key = _hyde_cache_key(query)

        # 缓存命中直接返回，避免同一 query 重复调用 LLM
        cached = await cache.get(hyde_key)
        if cached is not None:
            logger.info("HyDE 缓存命中: key=%s, query=%s", hyde_key, query[:50])
            return cached

        prompt = _HYDE_PROMPT.format(query=query)
        try:
            client = LLMFactory.get_client()
            answer = await asyncio.wait_for(
                client.generate(prompt),
                timeout=10,
            )
            logger.info("HyDE 扩展完成: query=%s, hyde_len=%d", query[:50], len(answer))
            answer = answer or query
            # 仅在真实生成（非降级值）时写入缓存，避免缓存退化结果
            if answer != query:
                await cache.set(hyde_key, answer, ttl=_HYDE_CACHE_TTL)
            return answer
        except asyncio.TimeoutError:
            logger.warning("HyDE 扩展超时 (10s)，降级使用原始 query: %s", query[:50])
            return query
        except Exception as e:
            logger.warning("HyDE 扩展失败，降级使用原始 query: %s", e)
            return query

    async def _retrieve(self, query: str, top_k: int = 30, min_score: float = 0.6) -> list[dict]:
        """多次检索 + 反思改写（最多 3 轮），供流式端点复用

        流程：
        1. 初始检索（取 top_k 个候选）
        2. 反思：检查文档是否足够回答用户问题
        3. 如果不够，改写 query 再次检索（最多额外 2 次）
        4. 每次结果合并后去重（按 doc id）
        5. 最后过滤 min_score 以下的低分结果

        module-024 延迟优化：
        - round 0 向量/图检索用 gather(return_exceptions=True)，单路失败降级
          为另一路（两路都失败返回空，不整链路崩溃）
        - HyDE 扩展带 Redis 缓存（_hyde_expand 内实现），重复 query 不重复调 LLM
        - 整链路预算 _RETRIEVE_BUDGET_SECONDS：每轮循环检查，超预算用已收集 docs 提前结束
        - round 0 已收集 ≥_MIN_DOCS_SKIP_REFLECT 篇文档时跳过反思与后续轮次（提前终止强化）

        参数:
            query: 初始查询
            top_k: 每次检索的候选数
            min_score: 低分过滤阈值
        """
        from agent.reflector import reflector

        # ── 空 query 防护（module-022 遗留，module-027 收敛） ──
        # 在缓存检查之前提前返回：空 query 不生成缓存 key、不调 HyDE/
        # 检索/反思（空串的 sha256 key 无意义且纯浪费资源）。
        if not query or not query.strip():
            logger.warning("检索 query 为空，返回空结果")
            return []

        # ── Redis 缓存检查 ──
        # key 纳入 top_k/min_score：不同参数生成不同 key，避免错误复用缓存
        cache_key = _retrieve_cache_key(query, top_k, min_score)
        cached = await cache.get(cache_key)
        if cached is not None:
            logger.info("检索缓存命中: key=%s, docs=%d", cache_key, len(cached))
            return cached

        # ── 整链路预算（module-024） ──
        # deadline 在 HyDE/循环前设定：HyDE 生成、实体提取、多轮检索全部
        # 计入 30s 总预算。每轮循环开头检查，超预算即用已收集 docs 提前
        # 结束（不再发起新一轮检索），保证最坏时延有上限。
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _RETRIEVE_BUDGET_SECONDS

        all_docs: list[dict] = []
        existing_ids: set[int] = set()
        current_query = query

        # HyDE 查询扩展：首轮用假设回答检索（语义更接近文档），后续轮次用反射改写查询
        hyde_query = await self._hyde_expand(query)

        for round_num in range(3):  # 最多 3 轮
            # 超预算检查：到点不再发起新一轮检索，用已收集 docs 进入生成
            if loop.time() >= deadline:
                logger.warning("检索超预算 (%.0fs)，使用已收集 %d 篇文档提前结束",
                               _RETRIEVE_BUDGET_SECONDS, len(all_docs))
                break

            search_text = hyde_query if round_num == 0 else current_query

            # Round 0: 并行向量检索 + 图搜索
            if round_num == 0:
                # 实体提取失败时 graph_extractor 内部降级返回空列表
                query_entities = await graph_extractor.extract_from_query(query)
                vector_task = asyncio.wait_for(
                    hybrid_retriever.retrieve(search_text, top_k=top_k),
                    timeout=15,
                )
                graph_task = asyncio.wait_for(
                    graph_store.search_related(query_entities, top_k=top_k),
                    timeout=15,
                )
                vector_docs, graph_docs = await asyncio.gather(
                    vector_task, graph_task, return_exceptions=True,
                )
                # 单路失败降级为另一路（与混合检索降级哲学一致）：
                # 向量超时/失败 → 仅图结果；图超时/失败 → 仅向量结果；
                # 两路都失败 → 空列表，不整链路崩溃
                if isinstance(vector_docs, Exception):
                    logger.warning("round 0 向量检索失败，降级为仅图结果: %s", vector_docs)
                    vector_docs = []
                if isinstance(graph_docs, Exception):
                    logger.warning("round 0 图检索失败，降级为仅向量结果: %s", graph_docs)
                    graph_docs = []
                # 合并：向量结果优先，图结果追加去重
                docs = list(vector_docs) if vector_docs else []
                for gd in (graph_docs or []):
                    if gd.get("id") and gd["id"] not in {d.get("id") for d in docs}:
                        docs.append(gd)
            else:
                try:
                    docs = await asyncio.wait_for(
                        hybrid_retriever.retrieve(search_text, top_k=top_k),
                        timeout=15,
                    )
                except asyncio.TimeoutError:
                    logger.warning("第 %d 轮检索超时 (15s)", round_num + 1)
                    break
                except Exception as e:
                    logger.warning("第 %d 轮检索失败: %s", round_num + 1, e)
                    break

            # 合并本轮结果，去重
            for d in docs:
                doc_id = d.get("id")
                if doc_id and doc_id not in existing_ids:
                    all_docs.append(d)
                    existing_ids.add(doc_id)

            # 提前终止强化（module-024）：round 0 已收集 ≥3 篇文档即跳过
            # 反思与后续轮次。阈值保守，减少一次 LLM 反思调用且不过度牺牲召回。
            if round_num == 0 and len(all_docs) >= _MIN_DOCS_SKIP_REFLECT:
                logger.info("round 0 已收集 %d 篇文档，跳过反思与后续轮次", len(all_docs))
                break

            # 前两轮尝试反思改写，最后一轮直接结束
            if round_num < 2:
                try:
                    # 反思检查始终使用原始 query（非 HyDE 查询）
                    check = await asyncio.wait_for(
                        reflector.check_sufficiency(query, docs),
                        timeout=10,
                    )
                    if check.get("sufficient", True):
                        break  # 充分则提前结束
                    rewritten = check.get("rewritten_query", current_query)
                    if not rewritten or rewritten == current_query:
                        break
                    current_query = rewritten
                    logger.info("检索改写第 %d 次: %s", round_num + 1, rewritten)
                except asyncio.TimeoutError:
                    logger.warning("反思检查超时 (10s)，终止检索")
                    break
                except Exception as e:
                    logger.warning("反思检查失败，终止检索: %s", e)
                    break
            else:
                break

        # 父块映射：子块命中 → 父块返回（后续 rerank 基于父块）
        docs = await self._expand_to_parents(all_docs) if all_docs else []

        # 低分过滤
        docs = [
            d for d in docs
            if d.get("hybrid_score", d.get("score", 0)) >= min_score
        ] if docs else []

        # ── Redis 缓存写入 ──
        if docs:
            await cache.set(cache_key, docs, ttl=300)
            logger.info("检索结果已缓存: key=%s, docs=%d", cache_key, len(docs))

        return docs

    async def _rerank(self, query: str, docs: list[dict]) -> list[dict]:
        """仅重排（供流式端点复用）"""
        if not docs:
            return docs
        try:
            docs = await reranker.rerank(query, docs, top_k=5)
        except Exception as e:
            logger.warning("重排失败，使用原始排序: %s", e)
        return docs

    async def _expand_to_parents(self, child_docs: list[dict]) -> list[dict]:
        """将子块检索结果映射回父块，去重后按最佳分数排序

        为什么需要父块映射？
          检索命中的是子块（~300字符），但返回给用户/LLM 的应该是
          语义完整的父块（完整 section）。同一父块的多个子块可能同时命中，
          此时去重并取最佳子块的 hybrid_score 作为父块的分数。

        Args:
            child_docs: 子块检索结果列表，每项必须包含 parent_id 字段

        Returns:
            去重父块列表，字段包含 id, title, content, source, hybrid_score
            按 hybrid_score 降序排列
        """
        if not child_docs:
            return []

        # 旧格式文档（parent_id=NULL，无 M17 父子块结构）直接通过
        # 子块文档（parent_id=NOT NULL）映射到父块，去重后取最佳分数
        output: list[dict] = []
        parent_scores: dict[int, float] = {}
        for doc in child_docs:
            pid = doc.get("parent_id")
            if pid is None:
                # 旧格式：文档自身就是完整内容，直接通过
                output.append(doc)
            else:
                # 新格式：收集 parent_id，待会统一查父块
                score = doc.get("hybrid_score", doc.get("score", 0.0))
                if pid not in parent_scores or score > parent_scores[pid]:
                    parent_scores[pid] = score

        if not parent_scores:
            return output  # 没有子块需要展开，直接返回旧格式文档

        # 批量查询父块
        async with async_session_factory() as session:
            result = await session.execute(
                select(Document).where(Document.id.in_(list(parent_scores.keys())))
            )
            parents = result.scalars().all()

        # 输出 = 旧格式文档 + 父块文档
        for p in parents:
            output.append({
                "id": p.id,
                "title": p.title,
                "content": p.content,
                "source": p.source,
                "hybrid_score": parent_scores.get(p.id, 0.0),
            })

        # 按 ID 去重 + 按分数降序
        seen: set[int] = set()
        unique_output: list[dict] = []
        for d in output:
            did = d.get("id")
            if did is not None and did not in seen:
                seen.add(did)
                unique_output.append(d)
        unique_output.sort(key=lambda x: x.get("hybrid_score", 0.0), reverse=True)
        logger.debug("_expand_to_parents: child_docs=%d → parent-mapped=%d",
                      len(child_docs), len(unique_output))
        return unique_output

    async def add_document(self, title: str, content: str, source: str = "") -> dict:
        """添加文档：分块 → 向量化 → 落库

        流程：
        1. 计算内容 SHA256，检测是否重复
        2. 按 Markdown 标题分块
        3. 逐块向量化
        4. 批量写入 PostgreSQL

        为什么先向量化再落库？
          因为 embedding 计算可能失败（如模型加载异常），先算再写可以避免
          写入无 embedding 的"残缺"记录，保证数据一致性。

        Args:
            title: 文档标题
            content: 文档内容（不能为空）
            source: 来源标识（可选）

        Returns:
            {"id": int, "title": str, "chunks": int, "duplicate": bool}

        Raises:
            ValueError: title 或 content 为空
            RuntimeError: 向量化或入库失败
        """
        if not title or not title.strip():
            raise ValueError("文档标题不能为空")
        if not content or not content.strip():
            raise ValueError("文档内容不能为空")

        logger.info("add_document: title=%s, content_len=%d, source=%s", title, len(content), source)

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        async with async_session_factory() as session:
            # 检测重复：标题完全匹配 或 内容哈希匹配
            existing = await session.execute(
                select(Document).where(
                    (Document.title == title.strip()) | (Document.content_hash == content_hash)
                ).limit(1)
            )
            dup = existing.scalar_one_or_none()
            if dup:
                logger.info("检测到重复文档: id=%d, title=%s, reason=%s",
                            dup.id, dup.title,
                            "标题匹配" if dup.title == title.strip() else "内容哈希匹配")
                return {"id": dup.id, "title": dup.title, "chunks": 0, "duplicate": True}

            # 1. 两级分块：父块（section）+ 子块（~300 字符）
            chunk_result = chunker.chunk(content, source=source)
            parents = chunk_result.get("parents", [])
            children = chunk_result.get("children", [])

            # 无父块兜底：整文档为单一父块，子块=父块内容
            if not parents:
                parents = [{"title": title, "content": content}]
                children = [{"title": title, "content": content, "parent_index": 0}]

            try:
                # 2. 插入父块（无向量，供子块引用）
                parent_objs = []
                for p in parents:
                    parent_title = f"{title} > {p['title']}" if p.get("title") and p["title"] != title else title
                    doc = Document(
                        title=parent_title,
                        content=p["content"],
                        source=source,
                        embedding=None,
                        parent_id=None,
                        content_hash=hashlib.sha256(p["content"].encode("utf-8")).hexdigest(),
                    )
                    session.add(doc)
                    parent_objs.append(doc)

                # flush 获取父块 DB ID（不提交，保持事务原子性）
                await session.flush()

                # 3. 子块向量化
                child_texts = [c["content"] for c in children]
                embeddings = await embedding_service.embed_documents(child_texts)

                # 4. 插入子块（含向量 + parent_id 外键）
                for i, (child, emb) in enumerate(zip(children, embeddings)):
                    parent_idx = child.get("parent_index", 0)
                    if parent_idx >= len(parent_objs):
                        parent_idx = 0  # 安全兜底
                    parent = parent_objs[parent_idx]

                    child_title = f"{title} > {child.get('title', '')}" if child.get("title") else title
                    doc = Document(
                        title=child_title,
                        content=child["content"],
                        source=source,
                        embedding=emb,
                        parent_id=parent.id,
                        content_hash=hashlib.sha256(child["content"].encode("utf-8")).hexdigest(),
                        search_tokens=tokenize(child["content"]),
                    )
                    session.add(doc)

                # 5. 原子提交（父块 + 子块一起落库）
                await session.commit()

                logger.info("文档入库成功: title=%s, parents=%d, children=%d",
                            title, len(parent_objs), len(children))

                # ── 检索缓存失效：文档变更影响所有查询的候选集，全量清空 ──
                # 缓存是优化层，失效失败降级（delete_by_prefix 内部 catch，返回 False）
                await cache.delete_by_prefix("rag:retrieve:")

                # ── 知识图谱实体提取（异步，失败不影响入库） ──
                try:
                    await graph_store.ensure_graph()
                    extraction = await graph_extractor.extract_from_document(content)
                    entities = extraction.get("entities", [])
                    relations = extraction.get("relations", [])
                    parent_id = parent_objs[0].id if parent_objs else None

                    for ent in entities:
                        name = ent.get("name", "").strip()
                        ent_type = ent.get("type", "concept")
                        if name and parent_id:
                            await graph_store.upsert_entity(name, ent_type, int(parent_id))

                    for rel in relations:
                        src = rel.get("source", "").strip()
                        tgt = rel.get("target", "").strip()
                        if src and tgt:
                            await graph_store.upsert_relation(src, tgt)

                    logger.info("Graph: extracted %d entities, %d relations",
                                len(entities), len(relations))
                except Exception as e:
                    logger.warning("Graph 提取/写入失败，跳过: %s", e)

                return {
                    "id": parent_objs[0].id,
                    "title": title,
                    "chunks": len(parent_objs) + len(children),
                    "duplicate": False,
                }
            except Exception as e:
                await session.rollback()
                logger.error("文档入库失败: %s", e)
                raise RuntimeError("文档入库失败") from e


# 全局单例 — 整个应用共享一个 RAGEngine 实例
# 为什么用单例？RAGEngine 本身是无状态的，不需要创建多个实例。
# 所有状态（LLM 客户端、embedding 模型）由子模块自行管理。
rag_engine = RAGEngine()
