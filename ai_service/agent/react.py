"""
Agent ReAct 循环 — 工具编排核心（module-028）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

把固定流水线（意图路由→检索→反思→生成）升级为 Agentic ReAct 循环：
LLM 自己决定调用什么工具、以什么顺序，直到信息足够直接回答，或达到
工具总调用次数预算。

核心流程：
  while 未回答 and 工具调用数 < budget:
    LLM 调用（含已收集工具结果作上下文）
    if tool_calls:
      逐个执行 → 结果追加到消息 → 工具数 +1
    else:
      LLM 直接输出答案 → 结束
  budget 耗尽 → 用已收集 docs 兜底生成（reflector.generate_answer）

设计要点：
  1. react_loop 是异步生成器，逐事件产出（tool_call/tool_result/token/done），
     react_agent（非流式，供测试/调用）与 main.py 的 SSE 端点共用同一核心，
     避免逻辑重复。
  2. 工具结果作为上下文追加到 messages（OpenAI dict 格式：assistant 消息带
     原样 tool_calls + reasoning_content，后接逐条 tool 结果消息），
     LLM 每一轮都能看到历史工具结果。
  3. 工具总次数预算（非单工具次数）防空转烧钱；预算=0 时 LLM 不带工具直接回答。
  4. 消息用 OpenAI dict 格式；assistant 消息保留 reasoning_content
     （deepseek thinking 模式回传要求）并只含实际执行的 tool_calls，
     避免预算截断时出现无对应 tool 结果的孤立声明。
"""
import json
import logging
from typing import AsyncGenerator, Optional

from src.config import settings
from llm.client import LLMFactory
from agent.reflector import reflector
from agent.tool_registry import ToolRegistry, registry

logger = logging.getLogger(__name__)

# ReAct 系统提示词：指导 LLM 自主决定工具调用顺序
_SYSTEM_PROMPT = """你是张三个人网站的 Agentic RAG 问答助手。用户的问题需要检索知识库来回答，
你可以通过 function calling 调用工具，自主决定调用哪些工具、以什么顺序，直到信息足够回答问题。

可用工具：
- search_knowledge: 混合检索（关键词 + 语义向量），推荐首选
- search_fts: 精确关键词全文检索（适合专有名词、代码、精确术语）
- search_vector: 语义向量检索（适合概念性、同义表述查询）
- search_graph: 知识图谱检索（实体关系图遍历）
- extract_entities: 从查询/文本中提取技术实体
- recall_memory: 召回该用户的跨会话长期记忆
- generate_answer: 基于已检索到的全部文档生成带引用标注的最终答案

使用规则：
1. 优先用 search_knowledge 做一次检索；结果不足时再换 search_fts / search_vector /
   search_graph，或改用更精确的查询词重试
2. 检索工具会自动累积已检索文档；信息足够后调用 generate_answer 生成带引用答案，
   或直接输出最终答案
3. 工具返回空结果不代表出错，可能是知识库无相关内容，请判断是继续检索还是如实告知用户
4. 用中文回答，严格基于检索到的文档内容，禁止编造"""


class ReactContext:
    """ReAct 循环的会话上下文（每请求独立，多会话并发安全）

    Attributes:
        query: 用户当前问题
        client_ip: 用户 IP 标识（记忆按 IP 隔离）
        history: 历史对话列表 [{"role", "content"}, ...]
        docs: 检索工具累积的文档（按 doc id 去重）
        memory: recall_memory 工具召回的记忆文本（供 generate_answer 使用）
    """

    def __init__(self, query: str, client_ip: str = "unknown",
                 history: Optional[list[dict]] = None):
        self.query = query
        self.client_ip = client_ip
        self.history = history or []
        self.docs: list[dict] = []
        self._seen_ids: set = set()
        self.memory = ""

    def add_docs(self, docs: list[dict]) -> None:
        """按 doc id 去重累积检索文档（供 generate_answer / 兜底生成使用）"""
        for d in docs or []:
            did = d.get("id")
            if did is not None and did not in self._seen_ids:
                self.docs.append(d)
                self._seen_ids.add(did)


def _build_messages(ctx: ReactContext) -> list:
    """构造 ReAct 会话消息（OpenAI dict 格式）：system + history + 当前问题"""
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    messages.extend(ctx.history or [])
    messages.append({"role": "user", "content": ctx.query})
    return messages


def _assistant_message(response: dict, executed_ids: set) -> dict:
    """构造 assistant 工具调用消息（保留 reasoning_content + 原样 tool_calls）

    DeepSeek thinking 模式要求把 reasoning_content 原样回传（否则 400），
    tool_calls 用模型原始 arguments 字符串（不重新序列化，保持格式一致）。
    只保留本轮实际执行的 tool_calls（预算截断时避免出现无对应 tool 结果）。
    """
    raw = response.get("message") or {}
    msg = {"role": "assistant", "content": raw.get("content") or ""}
    reasoning = raw.get("reasoning_content")
    if reasoning:
        msg["reasoning_content"] = reasoning
    calls = [c for c in (raw.get("tool_calls") or []) if c.get("id") in executed_ids]
    if calls:
        msg["tool_calls"] = calls
    return msg


async def react_agent(
    query: str,
    history: Optional[list[dict]] = None,
    client_ip: str = "unknown",
    budget: Optional[int] = None,
    tools: Optional[ToolRegistry] = None,
) -> dict:
    """ReAct 循环（非流式）：自主调用工具直到可回答或达预算上限

    Args:
        query: 用户问题
        history: 历史对话列表
        client_ip: 用户 IP 标识（记忆隔离）
        budget: 工具总调用次数上限，None 用 settings.max_agent_tools
        tools: 工具注册表，默认全局 registry

    Returns:
        {"answer": str, "tool_count": int,
         "tool_trace": [{"name", "args", "result"}, ...]}
    """
    ctx = ReactContext(query, client_ip, history)
    budget = int(budget) if budget is not None else settings.max_agent_tools
    answer = ""
    tool_count = 0
    tool_trace: list[dict] = []

    async for evt in react_loop(ctx, _build_messages(ctx), budget, tools):
        t = evt["type"]
        if t == "tool_call":
            tool_count = evt["tool_count"]
            tool_trace.append({"name": evt["name"], "args": evt["args"]})
        elif t == "tool_result":
            if tool_trace:
                tool_trace[-1]["result"] = evt["result"][:200]
        elif t == "done":
            answer = evt.get("answer", "")
            tool_count = evt.get("tool_count", tool_count)
            break

    return {"answer": answer, "tool_count": tool_count, "tool_trace": tool_trace}


async def react_loop(
    ctx: ReactContext,
    messages: list,
    budget: int,
    tools: Optional[ToolRegistry] = None,
) -> AsyncGenerator[dict, None]:
    """ReAct 循环核心（异步生成器，逐事件产出，供 react_agent 与 SSE 端点复用）

    Args:
        ctx: 会话上下文（检索工具累积 docs 到 ctx）
        messages: 会话消息（system + history + 当前问题，会追加工具结果）
        budget: 工具总调用次数上限（≥0）
        tools: 工具注册表，默认全局 registry

    Yields 事件:
      {"type": "tool_call",   "name": str, "args": dict, "tool_count": int}
      {"type": "tool_result", "name": str, "args": dict, "result": str,
       "tool_count": int}
      {"type": "token", "content": str}             # 推理/回答文本片段
      {"type": "done", "answer": str, "tool_count": int}

    Raises:
        LLMException: 降级链所有供应商均失败（LLM 调用层面）
    """
    tools = tools or registry
    client = LLMFactory.get_client()
    budget = int(budget or 0)
    tool_count = 0

    # 预算=0：不调用工具，LLM 直接回答（验收 §1.2「预算=0：直接生成」）
    if budget <= 0:
        answer = await client.chat(messages)
        yield {"type": "done", "answer": answer, "tool_count": 0}
        return

    while tool_count < budget:
        response = await client.chat_with_tools(messages, tools.to_llm_schemas())
        tool_calls = response.get("tool_calls", []) or []
        content = response.get("content", "") or ""

        # 无 tool_call：LLM 认为信息足够，直接输出答案
        if not tool_calls:
            if content:
                yield {"type": "token", "content": content}
            yield {"type": "done", "answer": content, "tool_count": tool_count}
            return

        # 本轮 LLM 的推理文本（非最终答案），透传给前端观察进度
        if content:
            yield {"type": "token", "content": content}

        # 预算内本轮可执行的工具数（预算截断时只执行前 N 个）
        allowed = tool_calls[: max(0, budget - tool_count)]
        if not allowed:
            break  # 预算已满，无可用额度 → 兜底生成

        # 先追加 assistant 消息（保留 reasoning_content + 仅含实际执行的 tool_calls），
        # 再逐个执行并追加 tool 结果消息（OpenAI 要求 assistant 在前、tool 结果在后）
        executed_ids = {tc.get("id", "") for tc in allowed}
        messages.append(_assistant_message(response, executed_ids))

        for tc in allowed:
            name = tc.get("name", "")
            args = tc.get("args") or {}
            if isinstance(args, str):  # 防御：个别供应商返回未解析的 JSON 字符串
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
            tool = tools.get(name)
            tool_count += 1
            yield {"type": "tool_call", "name": name, "args": args,
                   "tool_count": tool_count}
            # 工具失败时 AgentTool.run 内部返回空结果，LLM 判断继续/放弃
            result = "" if tool is None else await tool.run(args, ctx)
            yield {"type": "tool_result", "name": name, "args": args,
                   "result": result, "tool_count": tool_count}
            # 工具结果追加到消息历史（LLM 下一轮能看到）
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "content": result})

    # 预算耗尽：用已收集 docs 兜底生成
    logger.warning("工具预算耗尽 (budget=%d)，用 %d 篇已收集文档兜底生成",
                   budget, len(ctx.docs))
    answer = await reflector.generate_answer(
        ctx.query, ctx.docs, history=ctx.history, memory=ctx.memory,
    )
    if answer:
        yield {"type": "token", "content": answer}
    yield {"type": "done", "answer": answer, "tool_count": tool_count}
