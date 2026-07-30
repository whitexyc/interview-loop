"""Schema 模型单元测试"""
from rag.schemas import SearchRequest, SearchResponse, ChatRequest, ChatResponse


def test_search_request_defaults():
    r = SearchRequest(query="test")
    assert r.query == "test"
    assert r.top_k == 5


def test_search_response():
    r = SearchResponse(results=[{"id": 1}], message="ok")
    assert len(r.results) == 1
    assert r.message == "ok"


def test_chat_request_with_history():
    r = ChatRequest(query="你好", history=[{"role": "user", "content": "hi"}])
    assert len(r.history) == 1


def test_chat_response():
    r = ChatResponse(answer="回答", sources=[{"id": 1}])
    assert r.answer == "回答"
    assert len(r.sources) == 1
