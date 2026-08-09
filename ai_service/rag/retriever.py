"""
混合检索器 — 召回层核心
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  Query → [EmbeddingService] 向量化
           → [HybridRetriever] ─→ PG 全文检索 (BM25 风格)
           │                      └→ pgvector 向量检索 (cosine)
           → [Score Fusion] Min-Max 归一化 + alpha 加权融合
           → [Reranker] TopN 精排

为什么需要混合检索？
  纯粹的向量检索（语义搜索）对"概念匹配"很好，比如搜"JVM内存管理"
  能找到"G1 GC Region分区"。但对"精确关键词"（如"G1 GC"）反而可能
  不如传统 BM25。混合检索结合了两者优势：
  - FTS（BM25）：精确匹配关键词，对专有名词、代码片段效果好
  - 向量：语义相似度，对同义词、概念性查询效果好
  - 两者互补，大幅提高召回率

alpha 参数的设计选择：
  alpha=0.3 意味着 30% 权重给 FTS，70% 给向量。
  这是因为在我们的场景中（后端知识库问答），语义理解比关键词匹配更重要。
  可以通过配置文件（PW_HYBRID_SEARCH_ALPHA）调整。
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import async_session_factory
from rag.embeddings import EmbeddingService, embedding_service as default_embedding_service
from rag.text_tokenizer import tokenize

logger = logging.getLogger(__name__)


class RetrievalException(Exception):
    """检索异常

    包装底层异常（数据库连接失败、embedding API 超时等），
    避免上层捕获到原始异常细节（防止敏感信息泄漏）。
    """

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


# 检索模式（module-019 消融评估用）：
#   hybrid       组合检索（FTS + 向量融合），默认值，行为与之前完全一致
#   vector_only  仅向量检索（pgvector）
#   fts_only     仅全文检索（PG FTS / BM25 风格）
#   graph_only   仅图检索（Graph RAG，LLM 提取实体 → 图遍历）
VALID_MODES = ("hybrid", "vector_only", "fts_only", "graph_only")


class HybridRetriever:
    """混合检索器

    同时执行 PG 全文检索和向量语义检索，对结果归一化后按加权得分融合输出。
    全文检索权重 alpha 可在初始化时指定（默认 0.3）。

    线程安全：本类不持有数据库连接，每次 retrieve 都新建或接受外部 session。
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        alpha: float = 0.3,
    ):
        self._embedding_service = embedding_service or default_embedding_service
        self._alpha = alpha  # FTS 权重，向量权重为 1-alpha

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        session: Optional[AsyncSession] = None,
        mode: str = "hybrid",
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """执行混合检索（支持按通道消融）

        hybrid 模式：query 向量化 → 并行 FTS+向量 → min-max 归一化 → alpha 融合。
        消融模式（fts_only/vector_only/graph_only）委托 _dispatch_mode 分派。

        Args:
            query: 用户查询
            top_k: 返回结果数量
            session: 数据库会话（可选）
            mode: 检索模式，见 VALID_MODES，默认 hybrid 与之前完全一致
            source_pattern: source LIKE 过滤（module-023 记忆检索 'memory:<ip>:%'）；
                为空默认排除 'memory:%'（防记忆污染知识库检索）；None 与之前一致

        Returns:
            检索结果列表（含 fts_score / vector_score / hybrid_score）

        Raises:
            RetrievalException: 检索失败时抛出
            ValueError: mode 不在 VALID_MODES 中
        """
        if not query or not query.strip():
            raise RetrievalException("检索查询不能为空")
        if mode not in VALID_MODES:
            raise ValueError(f"非法检索模式: {mode}，可选: {VALID_MODES}")

        # 消融模式（fts_only/vector_only/graph_only）：单通道检索，互不影响
        if mode != "hybrid":
            return await self._dispatch_mode(query, top_k, session, mode, source_pattern)

        # hybrid 模式（原逻辑，零回归）：向量化 → 并行检索 → 归一化融合
        try:
            query_embedding = await self._embedding_service.embed_text(query)
        except Exception as e:
            raise RetrievalException("查询向量化失败", cause=e)

        # 扩大召回，取 2 倍候选给 rerank 更大提升空间
        fetch_k = top_k * 2

        # session 可选：传入则共享串行，不传则 _execute 内为两路各建独立 session
        # 并行（module-026 并发修复，session 由 _execute 内部按需创建）
        return await self._execute(query, query_embedding, fetch_k, top_k, session, source_pattern)

    async def _dispatch_mode(
        self,
        query: str,
        top_k: int,
        session: Optional[AsyncSession],
        mode: str,
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """消融模式分派：fts_only / vector_only / graph_only 单通道检索

        retrieve() 的非 hybrid 分支统一委托到本方法，互不影响：
        - fts_only：只跑全文检索（不依赖 embedding）
        - vector_only：只跑向量检索（需先向量化，失败抛 RetrievalException）
        - graph_only：图遍历返回关联文档，失败降级为空

        Args:
            query: 用户查询
            top_k: 返回结果数量
            session: 数据库会话（可选，不传则自动创建）
            mode: 消融模式（调用方已校验在 VALID_MODES 且非 hybrid）
            source_pattern: source LIKE 过滤模式（透传给单通道检索）

        Returns:
            单通道检索结果列表；通道失败降级返回空列表

        Raises:
            RetrievalException: vector_only 向量化失败时抛出
        """
        if mode == "fts_only":
            return await self._retrieve_single_channel(
                query, None, top_k, session, channel="fts", source_pattern=source_pattern,
            )
        if mode == "vector_only":
            # 向量通道必须先向量化（embedding API 不可用时抛 RetrievalException）
            try:
                query_embedding = await self._embedding_service.embed_text(query)
            except Exception as e:
                raise RetrievalException("查询向量化失败", cause=e)
            return await self._retrieve_single_channel(
                query, query_embedding, top_k, session, channel="vector",
                source_pattern=source_pattern,
            )
        return await self._retrieve_graph_only(query, top_k)

    async def _retrieve_single_channel(
        self,
        query: str,
        query_embedding: Optional[list[float]],
        top_k: int,
        session: Optional[AsyncSession],
        channel: str,
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """单通道检索（vector_only / fts_only）

        与 hybrid 的 _execute 不同：不做跨通道归一化与融合，
        直接按通道原始分数排序取 top_k（_fts_search / _vector_search
        已在 SQL 层按分数倒序返回）。

        Args:
            query: 用户查询
            query_embedding: 查询向量（channel="vector" 时必填）
            top_k: 返回结果数量
            session: 数据库会话（可选）
            channel: "fts" 或 "vector"
            source_pattern: source LIKE 过滤模式（透传给单通道 SQL）

        Returns:
            检索结果列表；单通道失败时降级返回空列表（不影响其他通道）
        """
        fetch_k = top_k * 2

        async def _run(sess: AsyncSession) -> list[dict]:
            try:
                if channel == "vector":
                    return await self._vector_search(
                        query_embedding, fetch_k, sess, source_pattern,
                    )
                return await self._fts_search(query, fetch_k, sess, source_pattern)
            except Exception as e:
                logger.warning("%s 检索失败，降级返回空: %s", channel, e)
                return []

        if session is not None:
            return (await _run(session))[:top_k]
        async with async_session_factory() as sess:
            return (await _run(sess))[:top_k]

    async def _retrieve_graph_only(self, query: str, top_k: int) -> list[dict]:
        """图检索（graph_only）——仅 Graph RAG 通道

        复用 engine._retrieve 的图路径：
        LLM 从查询提取实体 → graph_store.search_related 图遍历返回关联文档。
        任一步失败或超时都降级返回空（评估时该通道记 0 分，不影响其他通道）。

        Args:
            query: 用户查询
            top_k: 返回最大文档数

        Returns:
            关联文档列表；失败返回空列表
        """
        try:
            from rag.graph_extractor import graph_extractor
            from rag.graph_store import graph_store

            entities = await asyncio.wait_for(
                graph_extractor.extract_from_query(query), timeout=10
            )
            if not entities:
                return []
            results = await asyncio.wait_for(
                graph_store.search_related(entities, top_k=top_k), timeout=15
            )
            return list(results) if results else []
        except asyncio.TimeoutError:
            logger.warning("图检索超时，降级返回空: query=%s", query[:40])
            return []
        except Exception as e:
            logger.warning("图检索失败，降级返回空: %s", e)
            return []

    async def _execute(
        self,
        query: str,
        query_embedding: list[float],
        fetch_k: int,
        top_k: int,
        session: Optional[AsyncSession] = None,
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """执行检索主逻辑（module-026 并发修复）

        并发竞态背景：asyncpg 单连接禁止并发操作。旧实现用 gather 在同一个
        session（同一连接）上并行跑 FTS + 向量，冷缓存时偶发
        "concurrent operations are not permitted"，导致结果不稳定（0 vs 2 篇）。

        修复方案（独立 session）：
          - 未传外部 session（默认路径）：为 FTS / 向量各开独立 session
            （各占独立连接），仍用 gather 并行执行，保留并行性能且互不冲突
          - 传了外部 session（兼容路径）：共享 session 上串行执行两路，
            保证事务可见性与连接安全（asyncpg 禁止单连接并发）
          - 独立 session 创建失败：降级为单共享 session 串行执行
          - 两路均单路降级：一路失败不影响另一路

        Args:
            query: 用户查询
            query_embedding: 查询向量
            fetch_k: 召回候选数（top_k 的 2 倍）
            top_k: 最终返回数
            session: 外部数据库会话（可选，不传则两路各建独立 session）
            source_pattern: source LIKE 过滤（透传两路 SQL）

        Returns:
            融合排序后的检索结果列表（含 fts_score / vector_score / hybrid_score）
        """
        # Step 2: 并行执行 FTS 和向量检索
        # 用 asyncio.gather 同时查询两个通道，性能提升约 2x。
        # return_exceptions=True：一路失败不影响另一路。
        if session is not None:
            # 外部 session：共享连接上串行执行（asyncpg 单连接禁止并发）
            fts_results, vector_results = await self._search_serial(
                query, query_embedding, fetch_k, session, source_pattern,
            )
        else:
            # 默认路径：FTS / 向量各开独立 session（module-026 并发修复）
            try:
                async with async_session_factory() as fts_sess, async_session_factory() as vec_sess:
                    fts_task = self._fts_search(query, fetch_k, fts_sess, source_pattern)
                    vector_task = self._vector_search(query_embedding, fetch_k, vec_sess, source_pattern)
                    fts_results, vector_results = await asyncio.gather(
                        fts_task, vector_task, return_exceptions=True,
                    )
            except Exception as e:
                # 独立 session 创建失败 → 降级为单共享 session 串行
                logger.warning("独立 session 创建失败，降级为共享 session 串行: %s", e)
                async with async_session_factory() as shared_sess:
                    fts_results, vector_results = await self._search_serial(
                        query, query_embedding, fetch_k, shared_sess, source_pattern,
                    )

        # 处理异常：某一路失败时降级为单路
        # 这是 graceful degradation 的设计——即使全文索引坏了，
        # 向量检索仍能工作，反之亦然。
        if isinstance(fts_results, Exception):
            logger.warning("全文检索失败，降级为仅向量检索: %s", fts_results)
            fts_results = []
        if isinstance(vector_results, Exception):
            logger.warning("向量检索失败，降级为仅全文检索: %s", vector_results)
            vector_results = []

        if not fts_results and not vector_results:
            return []

        # module-043 L3 后置校验数据：归一化前保存向量通道原始绝对余弦。
        # pgvector 的 score = 1 - (embedding <=> query) = 绝对语义相似度；
        # _normalize 会原地覆盖 score（min-max 相对分，跨查询不可比），
        # 故先存档到 abs_cosine（module-037 同名字段口径，
        # 下游 d.get("abs_cosine", 0.0) 读取）。仅 FTS 命中的文档无该字段，
        # 由 L3 侧按 0.0 处理（无语义匹配证据 → 保守标记）。
        for r in vector_results:
            r["abs_cosine"] = r.get("score", 0.0)

        # Step 3: 分数归一化
        # FTS 的 ts_rank 分数和向量检索的 cosine 距离不在同一个量纲。
        # 直接加权平均没有意义，所以先各自归一化到 [0, 1]。
        # 为什么用 min-max 而不是 z-score？因为我们只关心相对排序，
        # 不关心绝对分数，min-max 保持序关系不变。
        fts_normalized = self._normalize(fts_results, "score")
        vec_normalized = self._normalize(vector_results, "score")

        # Step 4: 按文档 ID 合并
        # 如果一个文档同时被 FTS 和向量检索命中，它的 hybrid_score
        # 会同时包含两个通道的贡献。
        merged: dict[int, dict] = {}
        for doc in fts_normalized:
            doc_id = doc["id"]
            merged[doc_id] = doc
            merged[doc_id]["fts_score"] = doc["score"]
            merged[doc_id]["vector_score"] = 0.0

        for doc in vec_normalized:
            doc_id = doc["id"]
            if doc_id in merged:
                merged[doc_id]["vector_score"] = doc["score"]
                # module-045 WP1: 双命中透传 abs_cosine（原始绝对余弦）。
                # vec_normalized 的 doc 源自 vector_results，已在上方存档
                # abs_cosine（module-043）；fts-only 文档保持无该字段，
                # 由下游按 0.0 保守处理（d.get("abs_cosine", 0.0)）。
                merged[doc_id]["abs_cosine"] = doc["abs_cosine"]
            else:
                doc["fts_score"] = 0.0
                doc["vector_score"] = doc["score"]
                merged[doc_id] = doc

        # Step 5: 计算混合分数
        for doc_id, doc in merged.items():
            doc["hybrid_score"] = (
                self._alpha * doc.get("fts_score", 0.0)
                + (1.0 - self._alpha) * doc.get("vector_score", 0.0)
            )

        # Step 6: 排序取 top_k，返回给上层（reranker 或直接输出）
        results = sorted(merged.values(), key=lambda x: x["hybrid_score"], reverse=True)
        return results[:top_k]

    async def _search_serial(
        self,
        query: str,
        query_embedding: list[float],
        fetch_k: int,
        session: AsyncSession,
        source_pattern: Optional[str] = None,
    ) -> tuple[list[dict], list[dict]]:
        """共享 session 上串行执行 FTS + 向量两路检索（module-026）

        外部传入 session（或独立 session 创建失败降级）时使用：
        同一连接上 asyncpg 不允许并发操作，只能串行；单路失败各自捕获
        降级为空，保持与并行路径一致的"一路失败不影响另一路"语义。

        Args:
            query: 用户查询
            query_embedding: 查询向量
            fetch_k: 召回候选数
            session: 共享数据库会话
            source_pattern: source LIKE 过滤（透传两路 SQL）

        Returns:
            (fts_results, vector_results)，失败路为空列表
        """
        try:
            fts_results = await self._fts_search(query, fetch_k, session, source_pattern)
        except Exception as e:
            logger.warning("全文检索失败，降级为仅向量检索: %s", e)
            fts_results = []
        try:
            vector_results = await self._vector_search(query_embedding, fetch_k, session, source_pattern)
        except Exception as e:
            logger.warning("向量检索失败，降级为仅全文检索: %s", e)
            vector_results = []
        return fts_results, vector_results

    async def _fts_search(
        self, query: str, fetch_k: int, session: AsyncSession,
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """PG 全文检索（BM25 风格，中文 jieba 预分词）

        使用 PostgreSQL 内建的全文搜索：
        - to_tsvector('simple', search_tokens): 把入库时 jieba 分词后的
          空格连接文本拆成 lexeme（中文词元，module-020）
        - plainto_tsquery('simple', query): 把分词后的用户查询转成 tsquery
        - @@ 操作符: 匹配词元
        - ts_rank: 计算 TF/IDF 风格的匹配分数

        Module-020 复活中文 FTS 的关键：
          旧逻辑查 content 列，'simple' 配置对连续中文文本按整个字符串作为
          单个 lexeme（如 'Java线程池核心参数'），多字查询必然空召回
          （module-019 基线 Hit@5=0）。现在：
          1. 入库侧已将子块内容 jieba 分词写入 search_tokens（空格连接）
          2. 查询侧同样 jieba 分词（与入库侧一致），plainto_tsquery 对
             空格分隔的词元逐词匹配
          3. WHERE search_tokens IS NOT NULL 过滤未分词/分词失败文档
             只查 search_tokens 不查 content，避免旧未分词文档干扰
        """
        # 查询侧分词与入库侧一致（都用 jieba）；分词后为空（空串/纯标点）则无匹配
        tokenized_query = tokenize(query)
        if not tokenized_query:
            logger.debug("FTS 检索: query 分词后为空，返回空列表")
            return []
        sql = text(f"""
            SELECT
                id, title, content, source, page_num, metadata, created_at, parent_id,
                ts_rank(to_tsvector('simple', search_tokens),
                        plainto_tsquery('simple', :query)) AS score
            FROM documents
            WHERE to_tsvector('simple', search_tokens) @@ plainto_tsquery('simple', :query)
              AND search_tokens IS NOT NULL
              AND parent_id IS NOT NULL
              {self._source_condition(source_pattern)}
            ORDER BY score DESC
            LIMIT :limit
        """)
        params: dict = {"query": tokenized_query, "limit": fetch_k}
        if source_pattern is not None:
            params["source_pattern"] = source_pattern
        rows = await session.execute(sql, params)
        results = []
        for row in rows.mappings():
            d = dict(row)
            d["score"] = float(d["score"]) if d["score"] is not None else 0.0
            results.append(d)
        logger.debug("FTS 检索: query=%s, results=%d", query, len(results))
        return results

    async def _vector_search(
        self, query_embedding: list[float], fetch_k: int, session: AsyncSession,
        source_pattern: Optional[str] = None,
    ) -> list[dict]:
        """pgvector 向量检索（余弦相似度）

        使用 pgvector 扩展的 <=> 操作符计算余弦距离：
        - 距离 = 0：向量完全一致（语义完全相同）
        - 距离 = 1：完全不相关
        - 返回时用 `1 - 距离` 转为"相似度分数"

        为什么用 cosine 而不是 L2 或内积？
        因为我们的 embedding 做了 L2 归一化（normalize_embeddings=True），
        此时 cosine ≈ 内积，且对向量模长不敏感，更适合文本语义匹配。

        注意：embedding IS NOT NULL 条件过滤掉未向量化的文档。
        """
        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"
        sql = text(f"""
            SELECT
                id, title, content, source, page_num, metadata, created_at, parent_id,
                1 - (embedding <=> :query_embedding) AS score
            FROM documents
            WHERE embedding IS NOT NULL
              AND parent_id IS NOT NULL
              {self._source_condition(source_pattern)}
            ORDER BY embedding <=> :query_embedding ASC
            LIMIT :limit
        """)
        params: dict = {"query_embedding": embedding_str, "limit": fetch_k}
        if source_pattern is not None:
            params["source_pattern"] = source_pattern
        rows = await session.execute(sql, params)
        results = []
        for row in rows.mappings():
            d = dict(row)
            d["score"] = float(d["score"]) if d["score"] is not None else 0.0
            results.append(d)
        logger.debug("向量检索: results=%d", len(results))
        return results

    @staticmethod
    def _source_condition(source_pattern: Optional[str]) -> str:
        """构造 source 过滤 SQL 片段（module-023 记忆隔离）

        - source_pattern 非空（记忆检索）：source LIKE :source_pattern，
          只查该 IP 的记忆文档，避免知识库文档污染记忆结果
        - source_pattern 为空（普通知识库检索）：排除 'memory:%' 前缀，
          保证记忆文档不会出现在知识库检索结果中

        Args:
            source_pattern: source LIKE 模式（None 表示普通知识库检索）

        Returns:
            拼入 WHERE 的 SQL 片段
        """
        if source_pattern is not None:
            return "AND source LIKE :source_pattern"
        return "AND (source IS NULL OR source NOT LIKE 'memory:%')"

    @staticmethod
    def _normalize(results: list[dict], score_key: str) -> list[dict]:
        """Min-Max 归一化分数到 [0, 1]

        用 min-max 而非 z-score 的理由：
        - z-score 适合正态分布数据，但检索分数分布不确定
        - min-max 保持序关系（排序不变），只是把数值映射到 [0,1]
        - 如果所有分数都相同（极端情况：单条结果），返回全 1.0

        注意：这是"soft"归一化，因为每次只归一化当前结果集，
        不是全局归一化。跨查询的分数不可比，但同一次查询内的排序正确。
        """
        if not results:
            return results

        scores = [r.get(score_key, 0.0) for r in results]
        min_s = min(scores)
        max_s = max(scores)
        score_range = max_s - min_s

        if score_range < 1e-9:
            # 分数完全相同的情况（比如单条结果、或所有文档分数一致）
            for r in results:
                r[score_key] = 1.0
        else:
            for r in results:
                r[score_key] = (r.get(score_key, 0.0) - min_s) / score_range

        return results


# 全局单例
hybrid_retriever = HybridRetriever()
