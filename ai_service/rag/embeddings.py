"""
文本嵌入服务

使用 HuggingFace sentence-transformers 本地计算 embedding，无需外部 API。
"""
import logging
import os
import ssl
import numpy as np
from typing import Optional

# Windows SSL 证书修复：优先使用 certifi 提供的 CA bundle
# （sentence-transformers 下载模型时默认 SSL 验签在 Windows 上可能失败）
try:
    import certifi
    _SSL_CA_BUNDLE = certifi.where()
except ImportError:
    _SSL_CA_BUNDLE = None

if _SSL_CA_BUNDLE and os.path.exists(_SSL_CA_BUNDLE):
    os.environ.setdefault("SSL_CERT_FILE", _SSL_CA_BUNDLE)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _SSL_CA_BUNDLE)

logger = logging.getLogger(__name__)


class EmbeddingException(Exception):
    """嵌入服务异常"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


# 本地模型路径（优先使用已下载的本地缓存）
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "models", "sentence-transformers_all-MiniLM-L6-v2",
)


class EmbeddingService:
    """文本嵌入服务（本地 sentence-transformers）"""

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or _LOCAL_MODEL_DIR
        self._model = None
        self._dim = 384

    def _lazy_load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info("加载 embedding 模型: %s", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                self._dim = self._model.get_embedding_dimension()
                logger.info("embedding 模型就绪, dim=%d", self._dim)
            except ImportError:
                raise EmbeddingException("sentence-transformers 未安装，请执行: pip install sentence-transformers")

    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingException("嵌入文本不能为空")
        self._lazy_load()
        emb = self._model.encode(text, normalize_embeddings=True)
        return emb.tolist()

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._lazy_load()
        valid = [t for t in texts if t and t.strip()]
        if not valid:
            return []
        embs = self._model.encode(valid, normalize_embeddings=True)
        return [e.tolist() for e in embs]


# 全局单例
embedding_service = EmbeddingService()
