"""module-093 OpenCode Zen provider 接入单元测试

覆盖（全部 mock，不打真实网络）：
- opencode 进入 LLMFactory 白名单 + validate_chain 接受
- OpenCodeClient 构造参数（model / base_url / api_key / timeout）
- 免费层必需的 X-Session-Id 头注入（实例级 UUID，非空且合法）
- (provider, temperature) 缓存隔离 → 不同实例不同 session id
- 未配置 key 时 fail-fast（LLMException，provider="opencode"）
- content=None 时返回空串（推理型免费模型 max_tokens 被推理耗尽的实测行为，
  空串兜底避免调用方 len(None) 崩溃）
- _provider_label → "opencode"（module-058 usage 按供应商归桶）
- chat_with_tools 走 ChatOpenAI 底层 create 路径并正确解析 tool_calls

实现说明：用例内 clear_cache 隔离 LLMFactory 类级实例缓存（对齐
test_reflector_temperature.py 模式）；同步用例内 asyncio.run 执行。
"""
import asyncio
import uuid
from unittest import mock

import pytest

from llm.client import LLMFactory, LLMException, OpenCodeClient


@pytest.fixture
def opencode_env():
    """假 key + 清空实例缓存；用例结束再清一次（避免跨用例污染）"""
    LLMFactory.clear_cache()
    with mock.patch("llm.client.settings.opencode_api_key", "fake-key"):
        yield
    LLMFactory.clear_cache()


class TestOpenCodeRegistration:
    """工厂注册与降级链白名单"""

    def test_in_supported_providers(self):
        assert "opencode" in LLMFactory.SUPPORTED_PROVIDERS

    def test_validate_chain_accepts_opencode(self):
        assert LLMFactory.validate_chain(["opencode", "qwen"]) == ["opencode", "qwen"]

    def test_get_client_returns_opencode_client(self, opencode_env):
        # 钉住 model/base_url，避免 .env 覆盖导致用例非 hermetic
        with mock.patch("llm.client.settings.opencode_model", "deepseek-v4-flash-free"), \
                mock.patch("llm.client.settings.opencode_base_url",
                           "https://opencode.ai/zen/v1"), \
                mock.patch("llm.client.ChatOpenAI") as m:
            c = LLMFactory.get_client("opencode")
        assert isinstance(c, OpenCodeClient)
        kwargs = m.call_args.kwargs
        assert kwargs["model"] == "deepseek-v4-flash-free"
        assert kwargs["base_url"] == "https://opencode.ai/zen/v1"
        assert kwargs["api_key"] == "fake-key"
        assert kwargs["timeout"] == 180                       # 网关抖动大，比 deepseek 放宽
        assert kwargs["temperature"] == 0.7                   # 默认温度

    def test_cache_isolated_by_temperature(self, opencode_env):
        with mock.patch("llm.client.ChatOpenAI"):
            low = LLMFactory.get_client("opencode", temperature=0.1)
            low_again = LLMFactory.get_client("opencode", temperature=0.1)
            default = LLMFactory.get_client("opencode")
        assert low is low_again                 # 同 (provider, temperature) 复用
        assert low is not default               # 不同温度不同实例
        assert low._session_id != default._session_id   # 实例级 session 各自独立


class TestSessionHeader:
    """免费层 X-Session-Id 头注入（module-093 实测：不带此头报 MissingSessionID）"""

    def test_header_injected_as_valid_uuid(self, opencode_env):
        with mock.patch("llm.client.ChatOpenAI") as m:
            c = LLMFactory.get_client("opencode")
        headers = m.call_args.kwargs["default_headers"]
        assert set(headers) == {"X-Session-Id"}
        # 合法 UUID（uuid.UUID 解析失败会抛 ValueError → 用例失败）
        assert str(uuid.UUID(headers["X-Session-Id"])) == headers["X-Session-Id"]
        assert headers["X-Session-Id"] == c._session_id

    def test_each_instance_gets_distinct_session_id(self, opencode_env):
        a = OpenCodeClient()
        b = OpenCodeClient()
        assert a._session_id != b._session_id


class TestFailFast:
    """配置缺失与异常行为"""

    def test_missing_api_key_raises(self):
        LLMFactory.clear_cache()
        try:
            with mock.patch("llm.client.settings.opencode_api_key", ""):
                with pytest.raises(LLMException) as ei:
                    LLMFactory.get_client("opencode")
            assert ei.value.provider == "opencode"
            assert "OPENCODE_API_KEY" in str(ei.value)
        finally:
            LLMFactory.clear_cache()

    def test_chat_none_content_returns_empty_string(self, opencode_env):
        """推理型免费模型 max_tokens 被推理耗尽时 content 为 None → 空串兜底"""
        c = OpenCodeClient()
        resp = mock.MagicMock()
        resp.content = None
        c._llm = mock.MagicMock()
        c._llm.ainvoke = mock.AsyncMock(return_value=resp)
        with mock.patch("llm.client._record_usage"):
            out = asyncio.run(c.chat([{"role": "user", "content": "hi"}]))
        assert out == ""

    def test_provider_label_is_opencode(self):
        c = OpenCodeClient.__new__(OpenCodeClient)   # 绕过 __init__ 免配 key
        assert c._provider_label() == "opencode"


class TestChatWithTools:
    """工具调用走 ChatOpenAI 底层 create 路径（基类默认实现）"""

    def test_parses_tool_calls_and_labels_usage(self, opencode_env):
        c = LLMFactory.get_client("opencode")   # 真实 ChatOpenAI 实例（不发起请求）

        raw = mock.MagicMock()
        raw.choices[0].message.content = ""
        tc = mock.MagicMock()
        tc.id = "call-1"
        tc.function.name = "search_notes"
        tc.function.arguments = '{"query": "RRF"}'
        raw.choices[0].message.tool_calls = [tc]

        create = mock.AsyncMock(return_value=raw)
        # async_client 是 pydantic Field（类属性不可 patch），直接实例级替换
        c._llm.async_client = mock.MagicMock()
        c._llm.async_client.create = create
        with mock.patch("llm.client._record_usage") as rec:
            out = asyncio.run(c.chat_with_tools(
                [{"role": "user", "content": "搜 RRF"}],
                [{"type": "function", "function": {"name": "search_notes"}}],
            ))

        assert out["tool_calls"] == [
            {"id": "call-1", "name": "search_notes", "args": {"query": "RRF"}},
        ]
        assert out["message"]["tool_calls"][0]["function"]["arguments"] == '{"query": "RRF"}'
        rec.assert_called_once()
        assert rec.call_args.args[0] == "opencode"   # usage 归桶到 opencode（非 "llm"）
        assert create.call_args.kwargs["model"] == c._llm.model_name
