"""
Rerank 重排服务 — 本地 Cross-Encoder 精排
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  HybridRetriever (Top N) → [Reranker] Cross-Encoder 逐对评分 → Top K

为什么切换为本地模型？
  之前使用 ModelScope API rerank，但 API 频繁失败导致回退到分数排序。
  改用本地 sentence-transformers CrossEncoder 模型（BAAI/bge-reranker-v2-m3），
  推理在本地 CPU 完成，无需网络请求，延迟可预测。

  权衡：
  - 优点：无外部依赖、无 API 费用、低延迟（CPU 上每对约 30-50ms）
  - 缺点：首次加载需下载模型（~1GB）、CPU 推理比 GPU 慢
"""
import logging
import os
from typing import Optional

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# 本地模型路径（优先使用已下载的本地缓存）
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "models", "bge-reranker-v2-m3",
)
_DEFAULT_MODEL = _LOCAL_MODEL_DIR if os.path.isdir(_LOCAL_MODEL_DIR) else "BAAI/bge-reranker-v2-m3"


class RerankerException(Exception):
    """重排异常"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


class Reranker:
    """重排器抽象基类"""

    async def rerank(self, query: str, documents: list[dict], top_k: int = 5) -> list[dict]:
        """对检索结果重排，返回按相关性降序的 top_k 条"""
        ...


class CrossEncoderReranker(Reranker):
    """本地 CrossEncoder 重排器

    使用 BAAI/bge-reranker-v2-m3 多语言 Cross-Encoder 模型。
    逐对计算 (query, doc_content) 的相关性分数，返回按相关性降序的结果。

    CrossEncoder 比 Bi-Encoder（向量检索）精度更高，因为它让 query 和 doc
    做完整的交叉注意力计算。但速度慢，所以只对 Top N 做精排。
    """

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or _DEFAULT_MODEL
        self._model: Optional[CrossEncoder] = None

    def _lazy_load(self):
        if self._model is None:
            logger.info("加载 reranker 模型: %s", self._model_name)
            self._model = CrossEncoder(self._model_name)
            logger.info("reranker 模型就绪")

    async def rerank(self, query: str, documents: list[dict], top_k: int = 5) -> list[dict]:
        """执行 CrossEncoder 重排

        将 query 与每个文档的 content 拼接为 (query, doc) 对，
        用 CrossEncoder 模型逐对打分，按分数降序返回 top_k 条。
        """
        if not documents:
            return []

        try:
            self._lazy_load()

            # 构造 (query, doc) 对
            pairs = [(query, d.get("content", "")) for d in documents]

            # 批量预测相关性分数（CPU 推理）
            scores = self._model.predict(pairs)

            # 将分数附加到文档上，按分数降序排列
            ranked = []
            for doc, score in zip(documents, scores):
                doc["rerank_score"] = float(score)
                ranked.append(doc)

            ranked.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
            logger.info("Rerank 完成: %d → %d", len(documents), len(ranked[:top_k]))
            return ranked[:top_k]

        except Exception as e:
            logger.error("Rerank 失败: %s", e)
            raise RerankerException("重排服务暂时不可用", cause=e)


# 全局单例
reranker = CrossEncoderReranker()
