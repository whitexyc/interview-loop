"""
文本嵌入服务

使用本地 bge-m3 GGUF 模型（llama-cpp-python）计算 embedding。
无需外部 API，bge-m3 输出 1024 维向量。

为何从云端切换到本地（module-020）：
  云端 ModelScope embedding API 频繁 502，导致向量检索通道不可用。
  改用本地 GGUF（Q8 量化，605MB）+ llama-cpp-python，零外部依赖。

模型加载约束（Qwen3-Reranker 同款生成式适配的经验延伸）：
  - llama-cpp Llama(embedding=True, pooling_type=2) → CLS pooling，1024 维
  - 输出未 L2 归一化，需 _normalize()（与云端 API 行为保持一致）
"""
import asyncio
import logging
import os
import numpy as np
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)

# 本地 GGUF 模型路径
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "models", "bge-m3-gguf", "bge-m3-q8_0.gguf",
)
# 权重文件名（校验完整性）
_WEIGHT_FILES = ("bge-m3-q8_0.gguf",)


class EmbeddingException(Exception):
    """嵌入服务异常"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.__cause__ = cause


class EmbeddingService:
    """文本嵌入服务（本地 bge-m3 GGUF，异步包装）"""

    def __init__(self, model_path: str = ""):
        self._model_path = model_path or _LOCAL_MODEL_DIR
        self._model = None
        self._dim = 1024  # bge-m3 固定 1024 维

    def _validate_model_file(self):
        """校验本地模型文件完整性

        要求模型文件存在且非空（0 字节文件会加载失败但被掩盖）。
        缺文件时明确抛 EmbeddingException。
        """
        if not os.path.isfile(self._model_path):
            raise EmbeddingException(
                f"嵌入模型文件不存在: {self._model_path}，请先下载 bge-m3-q8_0.gguf"
            )
        size = os.path.getsize(self._model_path)
        if size == 0:
            raise EmbeddingException(f"嵌入模型文件为空(0字节): {self._model_path}")

    def _lazy_load(self):
        if self._model is None:
            self._validate_model_file()
            logger.info("加载本地嵌入模型: %s", self._model_path)
            from llama_cpp import Llama
            self._model = Llama(
                model_path=self._model_path,
                embedding=True,
                n_ctx=8192,
                pooling_type=2,  # CLS pooling（BGE 系列推荐）
                verbose=False,
            )
            logger.info("嵌入模型就绪, dim=%d", self._dim)

    def _embed_sync(self, text: str) -> list[float]:
        """同步嵌入单条文本（由 to_thread 调用）"""
        self._lazy_load()
        resp = self._model.create_embedding(text)
        return self._normalize(resp["data"][0]["embedding"])

    def _embed_documents_sync(self, texts: list[str]) -> list[list[float]]:
        """同步批量嵌入（由 to_thread 调用）"""
        self._lazy_load()
        result = []
        for text in texts:
            resp = self._model.create_embedding(text)
            result.append(self._normalize(resp["data"][0]["embedding"]))
        return result

    @staticmethod
    def _normalize(embedding: list[float]) -> list[float]:
        """L2 归一化，与云端 normalize_embeddings=True 保持一致"""
        arr = np.asarray(embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 1e-9:
            arr = arr / norm
        return arr.tolist()

    async def embed_text(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingException("嵌入文本不能为空")
        try:
            # llama-cpp 是同步库，用 to_thread 避免阻塞事件循环
            return await asyncio.to_thread(self._embed_sync, text)
        except Exception as e:
            logger.error("Embedding 调用失败: %s", e)
            raise EmbeddingException("嵌入服务暂不可用", cause=e)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        valid = [t for t in texts if t and t.strip()]
        if not valid:
            return []
        try:
            return await asyncio.to_thread(self._embed_documents_sync, valid)
        except Exception as e:
            logger.error("Embedding 批量调用失败: %s", e)
            raise EmbeddingException("嵌入服务暂不可用", cause=e)


# 全局单例
embedding_service = EmbeddingService()
