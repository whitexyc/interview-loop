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

logger = logging.getLogger(__name__)


class RetrievalException(Exception):
    """检索异常

    包装底层异常（数据库连接失败、embedding API 超时等），
    避免上层捕获到原始异常细节（防止敏感信息泄漏）。
    """

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


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
    ) -> list[dict]:
        """执行混合检索

        流程：
        1. 将 query 转为向量
        2. 并行执行 FTS 和向量检索（各取 top_k * 2 以扩大召回）
        3. 对两路分数做 min-max 归一化
        4. 按 alpha 加权融合，返回 top_k 结果

        Args:
            query: 用户查询
            top_k: 返回结果数量
            session: 数据库会话（可选，不传则自动创建）

        Returns:
            检索结果列表，每项包含文档字段及 fts_score / vector_score / hybrid_score

        Raises:
            RetrievalException: 检索失败时抛出
        """
        if not query or not query.strip():
            raise RetrievalException("检索查询不能为空")

        # Step 1: 查询向量化
        # 先用 embedding 模型把自然语言 query 转成向量。
        # 为什么先向量化？因为需要它同时用于向量检索和后续的 score fusion。
        try:
            query_embedding = await self._embedding_service.embed_text(query)
        except Exception as e:
            raise RetrievalException("查询向量化失败", cause=e)

        # 扩大召回以覆盖更多候选
        # 取的候选越多，rerank 阶段的提升空间越大；
        # 但越多也意味着数据库查询越慢。这里取 2 倍是经验值。
        fetch_k = top_k * 2

        if session is not None:
            return await self._execute(query, query_embedding, fetch_k, top_k, session)
        else:
            async with async_session_factory() as sess:
                return await self._execute(query, query_embedding, fetch_k, top_k, sess)

    async def _execute(
        self,
        query: str,
        query_embedding: list[float],
        fetch_k: int,
        top_k: int,
        session: AsyncSession,
    ) -> list[dict]:
        """执行检索主逻辑"""
        # Step 2: 并行执行 FTS 和向量检索
        # 用 asyncio.gather 同时查询两个通道，性能提升约 2x。
        # return_exceptions=True：一路失败不影响另一路。
        fts_task = self._fts_search(query, fetch_k, session)
        vector_task = self._vector_search(query_embedding, fetch_k, session)

        fts_results, vector_results = await asyncio.gather(
            fts_task, vector_task,
            return_exceptions=True,
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

    async def _fts_search(self, query: str, fetch_k: int, session: AsyncSession) -> list[dict]:
        """PG 全文检索（BM25 风格）

        使用 PostgreSQL 内建的全文搜索：
        - to_tsvector('simple', content): 把文档内容拆成 lexeme（词元）
        - plainto_tsquery('simple', query): 把用户查询转成 tsquery
        - @@ 操作符: 匹配词元
        - ts_rank: 计算 TF/IDF 风格的匹配分数

        为什么用 'simple' 配置？
        因为文档内容是中文 + 英文混合（技术笔记），'simple' 不做词干化，
        直接按空格和标点分词。对于中文文档，每个汉字被视为独立 lexeme，
        这并不理想，但 vector 检索弥补了中文语义匹配。
        如果后续需要更好的中文 FTS，可以切换到 zhparser 扩展。
        """
        sql = text("""
            SELECT
                id, title, content, source, page_num, metadata, created_at,
                ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) AS score
            FROM documents
            WHERE to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)
        rows = await session.execute(sql, {"query": query, "limit": fetch_k})
        results = []
        for row in rows.mappings():
            d = dict(row)
            d["score"] = float(d["score"]) if d["score"] is not None else 0.0
            results.append(d)
        logger.debug("FTS 检索: query=%s, results=%d", query, len(results))
        return results

    async def _vector_search(self, query_embedding: list[float], fetch_k: int, session: AsyncSession) -> list[dict]:
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
        sql = text("""
            SELECT
                id, title, content, source, page_num, metadata, created_at,
                1 - (embedding <=> :query_embedding) AS score
            FROM documents
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> :query_embedding ASC
            LIMIT :limit
        """)
        rows = await session.execute(sql, {"query_embedding": embedding_str, "limit": fetch_k})
        results = []
        for row in rows.mappings():
            d = dict(row)
            d["score"] = float(d["score"]) if d["score"] is not None else 0.0
            results.append(d)
        logger.debug("向量检索: results=%d", len(results))
        return results

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
