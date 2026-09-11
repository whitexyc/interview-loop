"""
上下文压缩接线冒烟（module-093 / WP-B 集成，AC-14/AC-16）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用假 LLM 客户端确定性验证：
  - react_loop 与 langgraph_react_loop 均在 chat_with_tools 前调用 compress_view
  - 超阈时传给 LLM 的是含占位符/摘要的「视图副本」，本地 messages 保持完整（D1）
  - 触发时记 ctx_compress span（AC-16）
全 hermetic（零 DB 零网络）。
"""
import json

import pytest

from agent.react import ReactContext, _build_messages, react_loop
from agent.langgraph_react import langgraph_react_loop
from agent.tool_registry import ToolRegistry


def _stub_registry():
    reg = ToolRegistry()

    async def _stub(ctx, args):
        return "短工具结果"

    reg.register("search_knowledge", "检索",
                 {"type": "object", "properties": {}}, _stub, group=["retrieval"])
    return reg


def _fake_client(seen):
    class _Fake:
        def __init__(self):
            self.calls = 0

        async def chat_with_tools(self, messages, tools):
            seen.append(messages)
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [{"id": "x1", "name": "search_knowledge",
                                    "args": {}}],
                    "message": {"role": "assistant", "content": "",
                                "tool_calls": [{"id": "x1", "type": "function",
                                                "function": {"name": "search_knowledge",
                                                             "arguments": "{}"}}]},
                }
            return {"content": "最终答案", "tool_calls": [],
                    "message": {"role": "assistant", "content": "最终答案"}}

        async def chat(self, messages):
            return "最终答案"

    return _Fake()


def _long_history(rounds: int):
    """构造长 history（每轮 user→assistant(tool_calls)→长 tool 结果）"""
    hist = []
    for i in range(rounds):
        hist.append({"role": "user", "content": f"问题{i}"})
        hist.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "search_knowledge", "arguments": "{}"}},
        ]})
        hist.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": "长工具结果" * 400})
    return hist


@pytest.mark.asyncio
async def test_react_loop_compress_view_is_copy(monkeypatch):
    from src import tracing
    from src.config import settings

    monkeypatch.setattr(settings, "ctx_compress_enabled", True)
    monkeypatch.setattr(settings, "ctx_token_threshold", 1500)
    monkeypatch.setattr(settings, "ctx_keep_recent", 3)

    spans = []
    orig = tracing.record_span

    def _rec(name, kind, decision="", status="ok", duration_ms=0):
        if name == "ctx_compress":
            spans.append(decision)
        return orig(name, kind, decision=decision, status=status, duration_ms=duration_ms)

    monkeypatch.setattr(tracing, "record_span", _rec)

    seen = []
    fake = _fake_client(seen)
    monkeypatch.setattr("agent.react.LLMFactory.get_client", lambda: fake)

    history = _long_history(8)
    ctx = ReactContext("当前问题", identity="eval", history=history)
    messages = _build_messages(ctx)
    answer = ""
    async for evt in react_loop(ctx, messages, budget=5, tools=_stub_registry()):
        if evt["type"] == "done":
            answer = evt.get("answer", "")
    assert "最终答案" in answer
    # 传给 LLM 的首轮视图含 clearing 占位符
    assert any("[tool result cleared:" in m.get("content", "")
               for m in seen[0] if m.get("role") == "tool")
    # 本地 messages 保持完整（无占位符，D1）
    assert not any("[tool result cleared:" in m.get("content", "")
                    for m in messages if m.get("role") == "tool")
    # 触发 ctx_compress span（AC-16）
    assert spans and json.loads(spans[0])["triggered"] is True


@pytest.mark.asyncio
async def test_langgraph_loop_compress_view_is_copy(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "ctx_compress_enabled", True)
    monkeypatch.setattr(settings, "ctx_token_threshold", 1500)
    monkeypatch.setattr(settings, "ctx_keep_recent", 3)

    seen = []
    fake = _fake_client(seen)
    monkeypatch.setattr("agent.langgraph_react.LLMFactory.get_client", lambda: fake)

    history = _long_history(8)
    ctx = ReactContext("当前问题", identity="eval", history=history)
    answer = ""
    async for evt in langgraph_react_loop(ctx, _build_messages(ctx), budget=5,
                                           tools=_stub_registry()):
        if evt["type"] == "done":
            answer = evt.get("answer", "")
    assert "最终答案" in answer
    assert any("[tool result cleared:" in m.get("content", "")
               for m in seen[0] if m.get("role") == "tool")
    assert not any("[tool result cleared:" in m.get("content", "")
                   for m in _build_messages(ctx) if m.get("role") == "tool")
