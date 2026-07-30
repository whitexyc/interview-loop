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
import hashlib
import logging

from sqlalchemy import select

from src.config import settings
from src.database import async_session_factory
from rag.schemas import SearchRequest, SearchResponse, ChatRequest, ChatResponse, ChatSteps
from rag.models import Document
from rag.embeddings import embedding_service
from rag.retriever import hybrid_retriever
from rag.reranker import reranker
from rag.chunker import chunker
from agent.router import router_agent
from agent.reflector import reflector

logger = logging.getLogger(__name__)


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
                results = await reranker.rerank(request.query, results, top_k=top_k)
            elif not results:
                return SearchResponse(results=[], message="未检索到相关内容")

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

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """RAG 问答：意图路由 → 检索+反思循环（最多 3 轮）→ 生成

        手写循环替代 LangGraph（更直观的流程控制）：
        1. 意图识别 → 闲聊/实时走快捷路径
        2. 检索+反思循环（最多 3 轮）：
           - 每轮检索 → rerank → 去重 → 反思检查
           - 不充分则改写 query 继续
           - 充分或达到上限则结束
        3. 用收集到的所有文档生成答案 + 引用溯源
        """
        logger.info("RAG chat: query=%s, history=%d", request.query, len(request.history))

        try:
            # ========== 1. 意图识别 ==========
            intent_result = await router_agent.classify(request.query)
            intent = intent_result.get("intent", "knowledge")
            intent_labels = {"knowledge": "知识库", "casual_chat": "闲聊", "realtime": "实时数据"}

            # 闲聊路径
            if intent == "casual_chat":
                client = LLMFactory.get_client()
                answer = await client.chat([
                    {"role": "system", "content": "你是张三个人网站的 AI 助手，友好地回答用户的问题。"},
                    *request.history,
                    {"role": "user", "content": request.query},
                ])
                return ChatResponse(answer=answer, sources=[], message="casual_chat")

            # 实时数据路径
            if intent == "realtime":
                return ChatResponse(answer="实时数据查询功能正在开发中，请稍后再试。",
                    sources=[], message="realtime_not_implemented")

            # ========== 2. 检索+反思循环（最多 3 轮） ==========
            current_query = request.query
            all_docs: list[dict] = []
            seen_ids: set[int] = set()

            for round_num in range(3):
                docs = await hybrid_retriever.retrieve(current_query, top_k=20)
                docs = await reranker.rerank(current_query, docs, top_k=5)
                for d in docs:
                    doc_id = d.get("id")
                    if doc_id and doc_id not in seen_ids:
                        all_docs.append(d)
                        seen_ids.add(doc_id)

                if round_num < 2:
                    check = await reflector.check_sufficiency(current_query, docs)
                    if check.get("sufficient", True):
                        break
                    rewritten = check.get("rewritten_query", "")
                    if rewritten and rewritten != current_query:
                        current_query = rewritten
                    else:
                        break

            docs = all_docs

            # ========== 3. 降级：无结果时直接 LLM ==========
            if not docs:
                client = LLMFactory.get_client()
                answer = await client.generate(
                    f"用户问：{request.query}\n\n知识库暂无相关信息，请如实告知用户。"
                )
                return ChatResponse(answer=answer, sources=[], message="ok")

            # ========== 4. 生成答案 + 引用溯源 ==========
            answer = await reflector.generate_answer(
                request.query, docs, history=request.history,
            )

            sources = []
            for i, doc in enumerate(docs[:5]):
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:300],
                    "source": doc.get("source", ""),
                    "ref_index": i + 1,
                })

            return ChatResponse(answer=answer, sources=sources, message="ok")

        except Exception as e:
            logger.error("RAG chat 失败: %s", e, exc_info=True)
            return ChatResponse(
                answer="抱歉，我暂时无法回答这个问题，请稍后重试。",
                sources=[],
                message="internal_error" if not settings.debug else f"error: {e}",
            )

    async def _retrieve(self, query: str, top_k: int = 30, min_score: float = 0.6) -> list[dict]:
        """多次检索 + 反思改写（最多 3 轮），供流式端点复用

        流程：
        1. 初始检索（取 top_k 个候选）
        2. 反思：检查文档是否足够回答用户问题
        3. 如果不够，改写 query 再次检索（最多额外 2 次）
        4. 每次结果合并后去重（按 doc id）
        5. 最后过滤 min_score 以下的低分结果

        参数:
            query: 初始查询
            top_k: 每次检索的候选数
            min_score: 低分过滤阈值
        """
        from agent.reflector import reflector

        all_docs: list[dict] = []
        existing_ids: set[int] = set()
        current_query = query

        for round_num in range(3):  # 最多 3 轮
            try:
                docs = await hybrid_retriever.retrieve(current_query, top_k=top_k)
            except Exception as e:
                logger.warning("第 %d 轮检索失败: %s", round_num + 1, e)
                break

            # 合并本轮结果，去重
            for d in docs:
                doc_id = d.get("id")
                if doc_id and doc_id not in existing_ids:
                    all_docs.append(d)
                    existing_ids.add(doc_id)

            # 前两轮尝试反思改写，最后一轮直接结束
            if round_num < 2:
                try:
                    check = await reflector.check_sufficiency(current_query, docs)
                    if check.get("sufficient", True):
                        break  # 充分则提前结束
                    rewritten = check.get("rewritten_query", current_query)
                    if not rewritten or rewritten == current_query:
                        break
                    current_query = rewritten
                    logger.info("检索改写第 %d 次: %s", round_num + 1, rewritten)
                except Exception as e:
                    logger.warning("反思检查失败，终止检索: %s", e)
                    break
            else:
                break

        # 低分过滤
        docs = [
            d for d in all_docs
            if d.get("hybrid_score", d.get("score", 0)) >= min_score
        ] if all_docs else []

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

            # 1. 按 Markdown 标题分块
            chunks = chunker.chunk(content, source=source)
            if not chunks:
                # 没有标题时，整篇作为一个块
                chunks = [{"title": title, "content": content}]

            # 2. 逐块向量化
            texts = [c["content"] for c in chunks]
            try:
                embeddings = await embedding_service.embed_documents(texts)
            except Exception as e:
                logger.error("文档向量化失败: %s", e)
                raise RuntimeError("文档向量化失败，请稍后重试") from e

            # 3. 批量落库
            inserted_ids = []
            try:
                for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                    chunk_title = f"{title} > {chunk['title']}" if chunk["title"] and chunk["title"] != title else title
                    # 只有第一个块保留原始 source，后续块附加页码标记
                    chunk_source = source if i == 0 else f"{source}#chunk{i + 1}"
                    doc = Document(
                        title=chunk_title,
                        content=chunk["content"],
                        source=chunk_source,
                        embedding=emb,
                        content_hash=hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest(),
                    )
                    session.add(doc)
                    inserted_ids.append(doc)

                await session.commit()
                for doc in inserted_ids:
                    await session.refresh(doc)

                logger.info("文档入库成功: title=%s, chunks=%d, ids=%s",
                            title, len(inserted_ids), [d.id for d in inserted_ids])
                return {
                    "id": inserted_ids[0].id,
                    "title": title,
                    "chunks": len(inserted_ids),
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
