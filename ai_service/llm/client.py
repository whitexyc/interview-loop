"""
LLM 多供应商适配层 — RAG 链路的推理引擎
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  RAG 链路中所有需要 LLM 推理的地方都经过这个适配层：
    - Router Agent: 意图分类
    - Reflector: 反思检查 + 答案生成
    - Casual Chat: 直接闲聊

  本文件不直接参与 RAG 流水线编排，但为流水线中的多个环节提供"大脑"。

设计决策：
  1. 为什么用 LangChain？
     因为 LangChain 提供了统一的 ChatModel 接口，切换供应商只需
     换一个类（ChatAnthropic → ChatOpenAI），不用改调用代码。
     如果没有 LangChain，我们需要为每个供应商写一个 HTTP 客户端。

  2. 为什么用工厂模式？
     RAG 链路中有多处调用 LLM（路由、反思、生成），如果每个地方都
     自己实例化客户端，配置变更时（如切换供应商）需要改多处代码。
     工厂模式集中管理 LLM 实例，配置变更只需改一处。

  3. 为什么全异步（async/await）？
     LLM API 调用是 I/O 密集型操作，同步调用会阻塞事件循环。
     异步化让服务器在等待 API 响应时能处理其他请求，提高吞吐量。

  4. 为什么用实例缓存（_instances dict）？
     LLM 客户端初始化可能涉及网络连接（如 websocket），
     重复创建销毁浪费资源。缓存复用同一个客户端实例。
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from src.config import settings

logger = logging.getLogger(__name__)


class LLMException(Exception):
    """LLM 调用异常

    包装供应商特定的异常信息，统一异常接口。
    provider 字段告诉调用方是哪个供应商出了问题。
    cause 字段保留原始异常链，方便排查问题。
    """

    def __init__(self, provider: str, message: str, cause: Optional[Exception] = None):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
        self.__cause__ = cause


class LLMClient(ABC):
    """LLM 客户端抽象基类（异步）

    定义 generate（单轮文本生成）、chat（多轮对话）和 generate_stream（流式生成）三个接口。
    所有供应商客户端都必须实现这些方法。

    generate vs chat 的区别：
    - generate: 接收字符串 prompt，返回字符串（内部转成单轮 messages）
    - chat: 接收 messages 列表，支持多轮对话（system/user/assistant）

    generate_stream vs generate 的区别：
    - generate_stream: 异步生成器，逐 token 产出文本片段
    - generate: 等待完整响应后一次性返回
    """

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """单轮文本生成"""
        ...

    @abstractmethod
    async def chat(self, messages: list[dict]) -> str:
        """多轮对话"""
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        """流式文本生成，逐 token 产出

        Args:
            prompt: 输入文本

        Yields:
            文本片段，每次 yield 一个或几个 token
        """
        ...
        if False:  # pragma: no cover 让生成器成为真正的 async generator
            yield ""


class ClaudeClient(LLMClient):
    """Claude API 客户端（异步）

    通过 LangChain 的 ChatAnthropic 封装调用 Claude API。
    用于需要 Claude 推理能力的高质量生成场景。
    """

    def __init__(self):
        if not settings.claude_api_key:
            raise LLMException("claude", "CLAUDE_API_KEY 未配置")
        self._llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.claude_api_key,
            temperature=0.7,  # 0.7 在创造性和确定性之间平衡
            timeout=120,      # RAG 全链路多次 LLM 调用，设 120s 避免过早超时
        )

    async def generate(self, prompt: str) -> str:
        logger.info("Claude generate, model=%s, prompt_len=%d", settings.claude_model, len(prompt))
        try:
            # ainvoke 是 LangChain 的异步调用方法
            response = await self._llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            logger.error("Claude 调用失败: %s", e)
            raise LLMException("claude", "Claude 服务暂不可用", cause=e)

    async def chat(self, messages: list[dict]) -> str:
        try:
            response = await self._llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("Claude chat 失败: %s", e)
            raise LLMException("claude", "Claude 对话服务暂不可用", cause=e)

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        logger.info("Claude stream, model=%s", settings.claude_model)
        try:
            # 使用 astream_events 替代 astream，获得更精细的 token 级别事件
            async for event in self._llm.astream_events(prompt, version="v1"):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield chunk.content
        except Exception as e:
            logger.error("Claude 流式调用失败: %s", e)
            raise LLMException("claude", "Claude 流式服务暂不可用", cause=e)


class DeepSeekClient(LLMClient):
    """DeepSeek API 客户端（兼容 OpenAI SDK，异步）

    DeepSeek 的 API 兼容 OpenAI 格式，所以用 LangChain 的 ChatOpenAI 封装。
    这是项目的默认 LLM 供应商。
    """

    def __init__(self):
        if not settings.deepseek_api_key:
            raise LLMException("deepseek", "DEEPSEEK_API_KEY 未配置")
        self._llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.7,
            timeout=120,   # RAG 全链路多次 LLM 调用，设 120s 避免过早超时
        )

    async def generate(self, prompt: str) -> str:
        logger.info("DeepSeek generate, model=%s, prompt_len=%d", settings.deepseek_model, len(prompt))
        try:
            response = await self._llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            logger.error("DeepSeek 调用失败: %s", e)
            raise LLMException("deepseek", "DeepSeek 服务暂不可用", cause=e)

    async def chat(self, messages: list[dict]) -> str:
        try:
            response = await self._llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("DeepSeek chat 失败: %s", e)
            raise LLMException("deepseek", "DeepSeek 对话服务暂不可用", cause=e)

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        logger.info("DeepSeek stream, model=%s", settings.deepseek_model)
        try:
            async for chunk in self._llm.astream(prompt):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("DeepSeek 流式调用失败: %s", e)
            raise LLMException("deepseek", "DeepSeek 流式服务暂不可用", cause=e)


class ModelScopeClient(LLMClient):
    """ModelScope API 客户端（兼容 OpenAI SDK，异步）

    也是通过 ChatOpenAI 封装，但指向 ModelScope 的 API 端点。
    用于反射和生成等对模型质量要求较高的环节。
    """

    def __init__(self):
        if not settings.modelscope_api_key:
            raise LLMException("modelscope", "MODELSCOPE_API_KEY 未配置")
        self._llm = ChatOpenAI(
            model=settings.modelscope_model,
            api_key=settings.modelscope_api_key,
            base_url=settings.modelscope_base_url,
            temperature=0.7,
            timeout=120,   # RAG 全链路多次 LLM 调用，设 120s 避免过早超时
        )

    async def generate(self, prompt: str) -> str:
        logger.info("ModelScope generate, model=%s", settings.modelscope_model)
        try:
            response = await self._llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            logger.error("ModelScope 调用失败: %s", e)
            raise LLMException("modelscope", "ModelScope 服务暂不可用", cause=e)

    async def chat(self, messages: list[dict]) -> str:
        try:
            response = await self._llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.error("ModelScope chat 失败: %s", e)
            raise LLMException("modelscope", "ModelScope 对话服务暂不可用", cause=e)

    async def generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        logger.info("ModelScope stream, model=%s", settings.modelscope_model)
        try:
            async for chunk in self._llm.astream(prompt):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("ModelScope 流式调用失败: %s", e)
            raise LLMException("modelscope", "ModelScope 流式服务暂不可用", cause=e)


class LLMFactory:
    """LLM 客户端工厂，根据配置返回对应实例

    工厂模式的好处：
    1. 调用方不需要知道具体客户端类的存在
    2. 实例缓存（_instances）避免重复创建
    3. 切换供应商只需改配置文件中的 llm_provider

    使用示例：
        client = LLMFactory.get_client()           # 默认供应商
        client = LLMFactory.get_client("modelscope")  # 指定供应商
    """

    _instances: dict[str, LLMClient] = {}

    @classmethod
    def get_client(cls, provider: Optional[str] = None) -> LLMClient:
        """获取 LLM 客户端实例

        实例化后缓存，后续调用直接返回缓存的实例。
        如果调用方没有指定 provider，使用配置文件中的默认供应商。
        """
        provider = provider or settings.llm_provider
        if provider not in cls._instances:
            if provider == "claude":
                cls._instances[provider] = ClaudeClient()
            elif provider == "deepseek":
                cls._instances[provider] = DeepSeekClient()
            elif provider == "modelscope":
                cls._instances[provider] = ModelScopeClient()
            else:
                raise ValueError(f"不支持的 LLM 供应商: {provider}")
        return cls._instances[provider]

    @classmethod
    def clear_cache(cls):
        """清理客户端缓存

        在切换供应商时调用（比如用户在管理后台换了 API 配置）。
        目前没有运行时切换的场景，但保留这个接口供后续使用。
        """
        cls._instances.clear()
