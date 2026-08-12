"""
Rerank 重排服务 — 本地 Cross-Encoder 精排
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  HybridRetriever (Top N) → [Reranker] Cross-Encoder 逐对评分 → Top K

为什么使用 bge-reranker-v2-m3（module-030）？
  module-018 曾切换为 Qwen3-Reranker-0.6B（生成式模型），但 CPU 每对约 6s
  （自回归生成慢），top-20 重排需 120s，真实链路被阻塞。
  现改用 BAAI/bge-reranker-v2-m3（分类式 CrossEncoder，实测约 515ms/对，
  快约 12 倍）：
  - sentence-transformers CrossEncoder 原生支持，predict 传 (query, doc)
    裸 pair 即可，无需 chat template 适配
  - 分类式打分（sigmoid），分数接近 1.0 时排序仍正确，区分度低是已知特性，
    校准留待后续（不阻塞）
  - 权衡：首次加载 2.17GB 入内存较慢（预热后复用实例）

缺权重策略（决策，module-018 保留）：
  本地模型目录缺少权重文件时**明确报错**（抛 RerankerException），
  不回退 HuggingFace 在线加载。让问题可见而非静默降级。
"""
import asyncio
import logging
import os
import threading
from typing import Optional

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

# 本地模型路径（必须完整：含 model.safetensors / pytorch_model.bin）
# module-050 目录细分后本文件位于 rag/retrieval/ 下，需三级 dirname 才回到
# ai_service/ 根（对齐 embeddings.py:27-32 同款修法）；二级 dirname 会落在
# rag/ 下解析出 rag/models/... 导致模型缺失——module-053 曾致向量通道全断，
# 本模块（module-054）修复重排通道同款回归。
_LOCAL_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "bge-reranker-v2-m3",
)
# 权重文件名候选（safetensors 优先，兼容 pytorch bin）
_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
_DEFAULT_MODEL = _LOCAL_MODEL_DIR
# 重排内容截断阈值（性能修复）：CrossEncoder 按 batch 内最长序列填充，
# 知识库父块可达数万字符（无 ## 标题的文档整篇入库），fp32 CPU 下近满长
# 上下文使单次 rerank 从 ~0.5s 飙到 ~200s（实测 2 pair 201s）。重排只需
# 判断相关度，截断阈值越小整体越快，代价是丢失文档中后段的匹配信号
# （对已检索候选的重排影响小）。
# 选数依据（2026-08-09 九档拐点扫描，6 pair，本地 bge-reranker-v2-m3，
# 见 eval/benchmark_rerank.py --sweep 与 ADR-0004）：
#   2000 字符: 45.4s（7.57s/pair）  相关分数 0.977~0.999
#   1000 字符: 19.7s（3.28s/pair）  相关分数 0.983~1.000
#   500 字符:   8.9s（1.48s/pair）  相关分数 0.867~0.999
#   250 字符:   5.0s（0.83s/pair）  相关分数 0.724~0.999  ← 采纳
#   200 字符:   4.2s（0.70s/pair）  相关分数 0.700~0.999  （与 250 同档安全）
#   150 字符:   3.5s（0.58s/pair）  相关分数 0.388~0.999  ← 分数拐点（弱相关跌破 0.4）
#   100 字符:   2.6s（0.44s/pair）  相关分数 0.103~0.998
#    75 字符:   2.3s（0.38s/pair）  相关分数 0.079~0.992  （主文档开始掉至 0.858）
#    50 字符:   2.0s（0.34s/pair）  相关分数 0.001~0.992  （主文档崩溃至 0.157）
# 结论：250→200 分数/排序均稳定（差 ≤0.003、6/6 一致），拐点在 150；
# 250 相对 500 提速 44%、相对 2000 提速 89%，是"分数无损 + 排序稳定"
# 的安全值；更小档位省时有限（<0.7s/pair 后边际收益趋零）不值得冒险。
_MAX_PAIR_CHARS = 250


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

    使用 bge-reranker-v2-m3（本地，分类式 CrossEncoder）逐对计算
    (query, doc_content) 的相关性分数，返回按相关性降序的结果。

    CrossEncoder 比 Bi-Encoder（向量检索）精度更高，因为它让 query 和 doc
    做完整的交叉注意力计算。但速度慢，所以只对 Top N 做精排。

    缺权重策略：本地目录必须包含权重文件（model.safetensors / pytorch_model.bin），
    缺失时抛 RerankerException 明确报错，不回退 HuggingFace 在线加载。
    """

    def __init__(self, model_name: str = ""):
        self._model_name = model_name or _DEFAULT_MODEL
        self._model: Optional[CrossEncoder] = None
        # 单 CrossEncoder 实例访问串行化：to_thread 在真线程执行，模型推理非线程安全
        self._lock = threading.Lock()

    def _validate_model_dir(self):
        """校验本地模型目录完整性

        要求：
        1. 目录存在（否则提示下载）
        2. 包含权重文件（model.safetensors 或 pytorch_model.bin）

        缺任一条件即抛 RerankerException，明确报错而非静默降级。
        """
        if not os.path.isdir(self._model_name):
            raise RerankerException(
                f"重排模型目录不存在: {self._model_name}，请先下载 bge-reranker-v2-m3"
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

    def _predict_sync(self, pairs: list[tuple[str, str]]) -> list[float]:
        """同步执行重排打分（由 to_thread 调用）

        与 embeddings.py 的 module-027 模式一致：lazy_load + predict 均为同步
        CPU 密集调用，直接放在 async 函数里会阻塞事件循环；锁保证单实例访问
        完全串行（模型推理非线程安全）。
        """
        with self._lock:
            self._lazy_load()
            return self._model.predict(pairs)

    async def rerank(self, query: str, documents: list[dict], top_k: int = 5) -> list[dict]:
        """执行 CrossEncoder 重排

        将 query 与每个文档的 content 拼为 (query, doc) 裸 pair，
        用 CrossEncoder 模型逐对打分，按分数降序返回 top_k 条。

        bge-reranker-v2-m3 是分类式标准 CrossEncoder，predict 直接接受
        (query, doc) 裸 pair（不同于 Qwen3 生成式模型需要的 chat message 适配，
        已移除）。
        """
        if not documents:
            return []

        try:
            # 截断超长文档内容（性能修复）：CrossEncoder 按 batch 最长序列填充，
            # 超长父块（数千~数万字符）会把单次 rerank 拖到 ~200s。重排只需
            # 判断相关度，截断到 _MAX_PAIR_CHARS=250（module-044 九档实测：
            # 6 pair 耗时 5.0s vs 500 的 8.9s，提速 44%；拐点在 150，见头部注释）。
            pairs = [
                (query, (d.get("content") or "")[:_MAX_PAIR_CHARS])
                for d in documents
            ]

            # 批量预测相关性分数：CPU 密集推理挪到线程池（to_thread），
            # 避免阻塞事件循环导致 rerank 期间整个服务无响应
            scores = await asyncio.to_thread(self._predict_sync, pairs)

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
