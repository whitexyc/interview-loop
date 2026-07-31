"""
文本嵌入服务

使用 ModelScope 云端 Embedding API（OpenAI 兼容接口）计算 embedding。
本地无需下载模型，bge-m3 输出 1024 维向量。
"""
import logging
import os
import numpy as np
from typing import Optional

from openai import AsyncOpenAI

from src.config import settings

logger = logging.getLogger(__name__)


class EmbeddingException(Exception):
    """嵌入服务异常"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


class EmbeddingService:
    """文本嵌入服务（ModelScope 云端 API，异步）"""

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or settings.embedding_model
        self._client: Optional[AsyncOpenAI] = None
        self._dim = 1024  # bge-m3 固定 1024 维

    def _lazy_load(self):
        if self._client is None:
            api_key = settings.embedding_api_key or settings.modelscope_api_key
            base_url = settings.embedding_base_url or settings.modelscope_base_url
            if not api_key:
                raise EmbeddingException("EMBEDDING_API_KEY / MODELSCOPE_API_KEY 未配置")
            if not base_url:
                raise EmbeddingException("EMBEDDING_BASE_URL 未配置")
            logger.info("初始化嵌入客户端: model=%s, base_url=%s", self._model_name, base_url)
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=60,
            )

    @staticmethod
    def _normalize(embedding: list[float]) -> list[float]:
        """L2 归一化，与本地模型 normalize_embeddings=True 保持一致"""
        arr = np.asarray(embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 1e-9:
            arr = arr / norm
        return arr.tolist()

    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingException("嵌入文本不能为空")
        self._lazy_load()
        try:
            resp = await self._client.embeddings.create(
                model=self._model_name,
                input=text,
                encoding_format="float",
            )
            return self._normalize(resp.data[0].embedding)
        except Exception as e:
            logger.error("Embedding 调用失败: %s", e)
            raise EmbeddingException("嵌入服务暂不可用", cause=e)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._lazy_load()
        valid = [t for t in texts if t and t.strip()]
        if not valid:
            return []
        try:
            resp = await self._client.embeddings.create(
                model=self._model_name,
                input=valid,
                encoding_format="float",
            )
            # API 按输入顺序返回，取前 len(valid) 条
            embs = [self._normalize(d.embedding) for d in resp.data[: len(valid)]]
            return embs
        except Exception as e:
            logger.error("Embedding 批量调用失败: %s", e)
            raise EmbeddingException("嵌入服务暂不可用", cause=e)


# 全局单例
embedding_service = EmbeddingService()
