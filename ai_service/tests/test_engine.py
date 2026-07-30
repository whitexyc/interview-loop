"""RAG 引擎骨架单元测试"""
from rag.schemas import SearchRequest, ChatRequest
from rag.engine import rag_engine


async def test_search_returns_response():
    r = SearchRequest(query="测试")
    result = await rag_engine.search(r)
    assert result.message is not None


async def test_chat_returns_response():
    r = ChatRequest(query="你好")
    result = await rag_engine.chat(r)
    assert result.answer is not None
    assert isinstance(result.sources, list)
