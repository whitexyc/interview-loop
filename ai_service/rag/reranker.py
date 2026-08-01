"""
Rerank 重排服务 — 本地 Cross-Encoder 精排
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  HybridRetriever (Top N) → [Reranker] Cross-Encoder 逐对评分 → Top K

为什么切换为 Qwen3-Reranker-0.6B（module-018）？
  之前使用 BAAI/bge-reranker-v2-m3，但本地目录缺少权重文件（仅 tokenizer），
  导致 CrossEncoder 加载失败 → 上层静默降级为原始排序，重排从未真正生效。

  现改用 Qwen3-Reranker-0.6B（本地，ModelScope 下载）：
  - sentence-transformers 5.6.1 原生支持，predict 接口直接可用
  - 0.6B 参数，CPU 推理每对约 50-100ms，无外部 API 依赖
  - 权衡：首次加载 1.1GB 入内存较慢（预热后复用实例）

缺权重策略（决策）：
  本地模型目录缺少权重文件时**明确报错**（抛 RerankerException），
  不回退 HuggingFace 在线加载。让问题可见而非静默降级。
"""
import logging
import os
from typing import Optional

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# 本地模型路径（必须完整：含 model.safetensors / pytorch_model.bin）
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "models", "Qwen3-Reranker-0.6B",
)
# 权重文件名候选（safetensors 优先，兼容 pytorch bin）
_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
_DEFAULT_MODEL = _LOCAL_MODEL_DIR


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

    使用 Qwen3-Reranker-0.6B（本地）逐对计算 (query, doc_content) 的相关性分数，
    返回按相关性降序的结果。

    CrossEncoder 比 Bi-Encoder（向量检索）精度更高，因为它让 query 和 doc
    做完整的交叉注意力计算。但速度慢，所以只对 Top N 做精排。

    缺权重策略：本地目录必须包含权重文件（model.safetensors / pytorch_model.bin），
    缺失时抛 RerankerException 明确报错，不回退 HuggingFace 在线加载。
    """

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or _DEFAULT_MODEL
        self._model: Optional[CrossEncoder] = None

    def _validate_model_dir(self):
        """校验本地模型目录完整性

        要求：
        1. 目录存在（否则提示下载）
        2. 包含权重文件（model.safetensors 或 pytorch_model.bin）

        缺任一条件即抛 RerankerException，明确报错而非静默降级。
        """
        if not os.path.isdir(self._model_name):
            raise RerankerException(
                f"重排模型目录不存在: {self._model_name}，请先下载 Qwen3-Reranker-0.6B"
            )
        missing = [f for f in _WEIGHT_FILES if not os.path.isfile(os.path.join(self._model_name, f))]
        if len(missing) == len(_WEIGHT_FILES):
            raise RerankerException(
                f"重排模型缺少权重文件: {self._model_name}（需包含 {_WEIGHT_FILES[0]} 或 {_WEIGHT_FILES[1]}）"
            )

    def _lazy_load(self):
        if self._model is None:
            # 缺权重校验：目录不存在或缺权重文件时明确报错
            self._validate_model_dir()
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

            # Qwen3-Reranker 是生成式重排模型（Qwen3ForCausalLM），
            # 需要 chat 消息格式：query+document 拼进 user 消息，并追加 assistant 生成提示，
            # 使最后 token 位置的 logits 可用于 yes/no 相关性打分。
            # 注意：不能传 (query, doc) 裸 pair——本地 chat template 不认识
            # sentence-transformers 的 "query"/"document" 角色，会渲染成空串（0 token）。
            messages = [
                [{"role": "user", "content": f"{query}\n{d.get('content', '')}"}]
                for d in documents
            ]

            # 批量预测相关性分数（CPU 推理）
            scores = self._model.predict(
                messages,
                processing_kwargs={"chat_template": {"add_generation_prompt": True}},
            )

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
