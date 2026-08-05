"""
流式记忆接入单测（module-025）

验证 chat_stream 在 Step 5 生成前调用 rag_engine._recall_memory，
并把结果传给 reflector.generate_answer_stream(memory=...)：
- 有记忆：memory 参数包含召回文本
- 无记忆 / 召回失败（返回空串）：memory 为空串，SSE 照常（零回归）
- client_ip 从 request.state 透传（X-Forwarded-For → _recall_memory 入参）
- casual_chat 路径提前返回，不触发记忆召回（记忆注入仅生成步骤）

用 httpx ASGITransport 直连 app 端点，mock 检索/反思/生成链路，
不依赖真实数据库 / Redis / LLM（与 test_memory.py 同款 mock 模式）。
同步用例内 asyncio.run 执行，不依赖 pytest-asyncio（规避既有环境问题）。
"""
import asyncio
import json
from unittest import mock

import httpx

import main
from agent import reflector as _reflector  # noqa: F401  确保 patch 目标类已导入
from agent import router as _router  # noqa: F401
from rag import engine as _engine  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


def _parse_sse(body: bytes) -> list[dict]:
    """把 SSE 响应体解析成事件列表 [{event, data}, ...]"""
    events = []
    for block in body.decode("utf-8").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        evt = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                evt["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                evt["data"] = line[len("data: "):]
        if evt:
            events.append(evt)
    return events


def _doc(doc_id: int = 1) -> dict:
    return {
        "id": doc_id,
        "title": "测试文档",
        "content": "这是一段测试内容，用于检索与生成。",
        "source": "test",
        "hybrid_score": 0.95,
    }


class _GenCapture:
    """捕获 generate_answer_stream 的调用参数，并用假 token 流式产出"""

    def __init__(self, tokens: list[str] = None):
        self.calls: list[dict] = []
        self.tokens = tokens or ["好", "的"]

    def make_gen(self):
        async def fake_generate_answer_stream(query, documents, history=None, memory=""):
            self.calls.append({
                "query": query,
                "documents": documents,
                "history": history,
                "memory": memory,
            })
            for tok in self.tokens:
                yield tok
        return fake_generate_answer_stream


class _FakeLLM:
    """casual_chat 路径用的假 LLM 客户端（generate_stream 产出 token）"""

    def __init__(self):
        async def generate_stream(prompt):
            yield "你好"
        self.generate_stream = generate_stream


def _hit_stream(gen_capture, memory_text="", recall_calls=None, classify_intent="knowledge",
                xff="9.9.9.9"):
    """发起一次 chat_stream 请求（mock 全链路），返回 (sse_events, status_code)

    附带收集 _recall_memory 的调用参数到 recall_calls（由调用方传入列表）。
    """
    events = []
    status = 0
    async def run():
        nonlocal status
        with mock.patch("agent.router.router_agent.classify",
                        new=mock.AsyncMock(return_value={"intent": classify_intent})):
            with mock.patch("rag.engine.rag_engine._retrieve",
                            new=mock.AsyncMock(return_value=[_doc()])):
                with mock.patch("rag.engine.rag_engine._rerank",
                                new=mock.AsyncMock(side_effect=lambda q, docs: docs)):
                    with mock.patch("rag.engine.rag_engine._recall_memory",
                                    new=mock.AsyncMock(return_value=memory_text)) as recall:
                        with mock.patch("agent.reflector.reflector.check_sufficiency",
                                        new=mock.AsyncMock(
                                            return_value={"sufficient": True, "reason": ""})):
                            with mock.patch("agent.reflector.reflector.generate_answer_stream",
                                            new=gen_capture.make_gen()):
                                with mock.patch("rag.engine.rag_engine._resolve_session_history",
                                                new=mock.AsyncMock(
                                                    side_effect=lambda identity, h: h)):
                                    with mock.patch("rag.engine.rag_engine._schedule_session_persist",
                                                    new=mock.MagicMock()):
                                        transport = httpx.ASGITransport(
                                            app=main.app, raise_app_exceptions=True)
                                        async with httpx.AsyncClient(
                                                transport=transport, base_url="http://test") as client:
                                            resp = await client.post(
                                                "/ai/rag/chat/stream",
                                                headers={"X-Forwarded-For": xff} if xff else {},
                                                json={"query": "回答风格", "history": []},
                                            )
                                        events.extend(_parse_sse(resp.content))
                                        status = resp.status_code
        if recall_calls is not None:
            recall_calls.extend(recall.call_args_list)
    # module-033：mock 后台记忆自动写入（fire-and-forget 任务），避免真实 LLM 提取
    with mock.patch("rag.engine.rag_engine._persist_memory", new=mock.AsyncMock()):
        _run(run())
    return events, status


class TestChatStreamMemoryInjection:
    """module-025: chat_stream 流式记忆注入"""

    def test_memory_injected_when_recalled(self):
        """有记忆：召回文本传给 generate_answer_stream(memory=...)，SSE 正常"""
        gen = _GenCapture()
        memory_text = "历史记忆:\n- 用户偏好简洁回答"
        events, status = _hit_stream(gen, memory_text=memory_text)
        assert status == 200
        assert gen.calls, "generate_answer_stream 应被调用"
        assert gen.calls[0]["memory"] == memory_text
        assert gen.calls[0]["query"] == "回答风格"
        # SSE 事件格式不变：step/token/done 完整
        assert [e["event"] for e in events] == ["step", "step", "step", "step", "token", "token", "done"]

    def test_empty_memory_zero_regression(self):
        """无记忆：memory 为空串，生成照常（零回归）"""
        gen = _GenCapture()
        events, status = _hit_stream(gen, memory_text="")
        assert status == 200
        assert gen.calls[0]["memory"] == ""
        assert [e["event"] for e in events][-1] == "done"

    def test_recall_failure_contract_returns_empty(self):
        """召回失败：engine 契约返回空串，流式照常（failure→空串→零回归）"""
        gen = _GenCapture()
        events, status = _hit_stream(gen, memory_text="")
        assert status == 200
        assert gen.calls[0]["memory"] == ""

    def test_client_ip_passed_to_recall(self):
        """client_ip 从 request.state 透传：X-Forwarded-For → _recall_memory 入参"""
        gen = _GenCapture()
        recall_calls = []
        _hit_stream(gen, memory_text="m", recall_calls=recall_calls, xff="10.0.0.8")
        assert recall_calls, "_recall_memory 应被调用"
        args, kwargs = recall_calls[0]
        assert args[1] == "10.0.0.8"  # (query, client_ip)

    def test_casual_chat_skips_memory_recall(self):
        """casual_chat 提前返回：不触发记忆召回（记忆注入仅生成步骤）"""
        gen = _GenCapture()
        recall_calls = []
        with mock.patch("llm.client.LLMFactory.get_client") as gc:
            gc.return_value = _FakeLLM()
            _hit_stream(gen, memory_text="不应被召回", recall_calls=recall_calls,
                        classify_intent="casual_chat")
        assert recall_calls == [], "casual_chat 不应触发记忆召回"
