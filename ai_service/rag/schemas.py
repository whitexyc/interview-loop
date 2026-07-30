"""
RAG 知识库请求/响应模型
"""
from pydantic import BaseModel
from typing import Optional


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchResponse(BaseModel):
    results: list[dict] = []
    message: str = ""


class ChatRequest(BaseModel):
    query: str
    history: list[dict] = []


class ChatSteps(BaseModel):
    """RAG 中间步骤数据，供前端管线面板展示

    每个步骤包含：
    - timing_ms: 该步骤耗时（毫秒）
    - intent: 意图识别结果（label, confidence）
    - retrieval: 检索结果统计（count, top_score, documents_preview, relevance）
    - rerank: 重排前后数量
    - reflection: 反思结果（sufficient, query_rewritten, rewritten_query）
    """
    intent: dict = {}         # {"label": str, "confidence": float, "timing_ms": int}
    retrieval: dict = {}      # {"count": int, "top_score": float, "timing_ms": int,
                              #  "documents_preview": [{"title": str, "snippet": str, "score": float}],
                              #  "relevance": {"qualified": int, "total": int, "min_score": float}}
    rerank: dict = {}         # {"before": int, "after": int, "timing_ms": int}
    reflection: dict = {}     # {"sufficient": bool, "query_rewritten": bool, "timing_ms": int}


class ChatResponse(BaseModel):
    answer: str = ""
    sources: list[dict] = []
    message: str = ""
    steps: Optional[ChatSteps] = None
