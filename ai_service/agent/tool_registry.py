"""
Agent 工具注册表 — ToolRegistry（module-028）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

把固定 RAG 流水线升级为 Agentic ReAct 循环的第一步：把现有检索/图/记忆/生成
方法包装成带 name/description/args_schema 的工具，供 LLM 通过 function calling
自主调度。

设计要点：
  1. 注册表无状态（只存工具定义），执行时通过 AgentTool.run(args, ctx)
     注入会话上下文 ctx（query/identity/history/累积 docs/记忆），
     故全局单例 registry 可被多会话并发复用，无共享可变状态。
  2. 工具失败由 AgentTool.run 统一捕获返回空串（降级哲学），
     LLM 自行判断是继续检索还是如实告知用户。
  3. 内置 10 个工具：
     search_knowledge / search_fts / search_vector / search_graph /
     extract_entities / recall_memory / generate_answer / verify_answer /
     re_search / note_to_self
"""
import json
import logging
from typing import Callable, Optional

from rag.engine import rag_engine
from rag.retriever import hybrid_retriever
from rag.graph_store import graph_store
from rag.graph_extractor import graph_extractor
from agent.reflector import reflector

logger = logging.getLogger(__name__)


class AgentTool:
    """单个 Agent 工具

    Attributes:
        name: 工具名（LLM 通过该名调用）
        description: 工具用途描述（指导 LLM 何时使用）
        args_schema: JSON Schema（OpenAI function parameters 格式）
        func: 执行函数，签名 async def func(ctx, args) -> str
    """

    def __init__(self, name: str, description: str, args_schema: dict,
                 func: Callable):
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.func = func

    async def run(self, args: dict, ctx) -> str:
        """执行工具；失败返回空结果，LLM 判断继续/放弃（module-028 降级哲学）

        Args:
            args: LLM 传入的工具参数（已由 args_schema 描述）
            ctx: ReAct 循环的会话上下文（见 react.ReactContext）

        Returns:
            工具结果文本；执行失败返回 ""
        """
        try:
            return await self.func(ctx, args)
        except Exception as e:
            logger.warning("工具 %s 执行失败，返回空: %s", self.name, e)
            return ""

    def to_openai_schema(self) -> dict:
        """转成 OpenAI function calling 的 tool schema（ChatOpenAI.bind_tools 用）"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema,
            },
        }


class ToolRegistry:
    """工具注册表：注册 / 查询 / 序列化

    注册表只保存工具定义（name/description/args_schema/func），
    不持有任何请求级状态；执行时经 run(args, ctx) 注入会话上下文，
    因此全局单例可跨请求复用（并发安全）。
    """

    def __init__(self):
        self._tools: dict[str, AgentTool] = {}

    def register(self, name: str, description: str, args_schema: dict,
                 func: Callable) -> "ToolRegistry":
        """注册一个工具（同名覆盖，便于测试替换）"""
        self._tools[name] = AgentTool(name, description, args_schema, func)
        return self

    def get(self, name: str) -> Optional[AgentTool]:
        """按名字取工具，未注册返回 None"""
        return self._tools.get(name)

    def list_tools(self) -> list[AgentTool]:
        """返回全部已注册工具（注册序）"""
        return list(self._tools.values())

    def list_tool_names(self) -> list[str]:
        """返回全部工具名"""
        return [t.name for t in self._tools.values()]

    def to_llm_schemas(self) -> list[dict]:
        """序列化为 OpenAI function calling 的 tool schema 列表"""
        return [t.to_openai_schema() for t in self._tools.values()]


# ─── 检索结果格式化 ───


def _format_docs(docs: list[dict], limit: int = 5) -> str:
    """把检索结果格式化为 LLM 可读文本（标题 + 分数 + 内容截断）

    Args:
        docs: 检索结果列表（含 id/title/content/hybrid_score 等）
        limit: 最多展示条数

    Returns:
        格式化文本；无结果返回 "（无检索结果）"
    """
    if not docs:
        return "（无检索结果）"
    parts = []
    for i, d in enumerate(docs[:limit], start=1):
        score = round(float(d.get("hybrid_score", d.get("score", 0.0))), 3)
        content = (d.get("content") or "")[:400]
        parts.append(f"[{i}] {d.get('title', '')} (score={score})\n{content}")
    if len(docs) > limit:
        parts.append(f"……共 {len(docs)} 条结果，已展示前 {limit} 条")
    return "\n\n".join(parts)


# ─── 内置工具实现（func 签名: async def (ctx, args) -> str） ───


async def _search_knowledge(ctx, args: dict) -> str:
    """混合检索：FTS 关键词 + 向量语义融合，默认首选"""
    query = args.get("query") or ctx.query
    top_k = int(args.get("top_k", 5))
    docs = await hybrid_retriever.retrieve(query, top_k=top_k, mode="hybrid")
    ctx.add_docs(docs)
    return _format_docs(docs)


async def _search_fts(ctx, args: dict) -> str:
    """仅全文检索：精确关键词匹配（专有名词/代码/精确术语）"""
    query = args.get("query") or ctx.query
    top_k = int(args.get("top_k", 5))
    docs = await hybrid_retriever.retrieve(query, top_k=top_k, mode="fts_only")
    ctx.add_docs(docs)
    return _format_docs(docs)


async def _search_vector(ctx, args: dict) -> str:
    """仅向量检索：语义相似度匹配（概念性/同义表述查询）"""
    query = args.get("query") or ctx.query
    top_k = int(args.get("top_k", 5))
    docs = await hybrid_retriever.retrieve(query, top_k=top_k, mode="vector_only")
    ctx.add_docs(docs)
    return _format_docs(docs)


async def _search_graph(ctx, args: dict) -> str:
    """知识图谱检索：提取实体 → 沿实体关系图遍历返回关联文档"""
    query = args.get("query") or ctx.query
    top_k = int(args.get("top_k", 5))
    entities = await graph_extractor.extract_from_query(query)
    if not entities:
        return "（图检索：未提取到实体）"
    docs = await graph_store.search_related(entities, top_k=top_k)
    ctx.add_docs(docs)
    return _format_docs(docs)


async def _extract_entities(ctx, args: dict) -> str:
    """从查询/文本提取技术实体名称列表（JSON）"""
    query = args.get("query") or ctx.query
    entities = await graph_extractor.extract_from_query(query)
    return json.dumps({"entities": entities}, ensure_ascii=False)


async def _recall_memory(ctx, args: dict) -> str:
    """召回该用户的跨会话长期记忆（按身份隔离；无记忆返回提示）"""
    query = args.get("query") or ctx.query
    top_k = int(args.get("top_k", 3))
    text = await rag_engine._recall_memory(query, ctx.identity, top_k=top_k)
    if text:
        ctx.memory = text  # 供 generate_answer 工具拼入生成 prompt
    return text or "（无相关历史记忆）"


async def _generate_answer(ctx, args: dict) -> str:
    """基于本次已累积检索到的文档生成带引用标注的最终答案"""
    if not ctx.docs:
        return "（尚未检索到文档，请先调用 search_knowledge 等检索工具）"
    query = args.get("query") or ctx.query
    return await reflector.generate_answer(
        query, ctx.docs, history=ctx.history, memory=ctx.memory,
        scratchpad=ctx.scratchpad,
    )


async def _verify_answer(ctx, args: dict) -> str:
    """逐句验证已生成答案是否被检索文档支持，标注可信度（module-039）"""
    answer = args.get("answer")
    if not answer:
        return "（未提供答案文本，无法验证）"
    if not ctx.docs:
        return "（无检索文档，无法验证答案可信度；请先检索）"
    result = await reflector.verify_answer(answer, ctx.docs)
    if not result.get("claims"):
        return "（验证失败，无法判定答案可信度）"
    lines = []
    for c in result["claims"]:
        verdict_icon = {"supported": "✓", "inferred": "~", "unsupported": "✗"}.get(
            c.get("verdict", ""), "?"
        )
        lines.append(f"[{verdict_icon}] {c.get('verdict')}: {c.get('claim')} (证据: {c.get('evidence')})")
    lines.append(f"\n整体置信度: {result.get('overall_confidence', 0):.0%}")
    lines.append(f"supported={result.get('supported', 0)} inferred={result.get('inferred', 0)} unsupported={result.get('unsupported', 0)}")
    return "\n".join(lines)


async def _re_search(ctx, args: dict) -> str:
    """检索不足 → 改写 query 重检 → 新结果累积到 ctx.docs（module-040）

    流程：
      1. check_sufficiency 判断当前 ctx.docs 是否充分
      2. 不充分 → 用 rewritten_query 重新混合检索
      3. 新结果按 id 去重累积到 ctx.docs

    降级：
      - 无 ctx.docs → 提示先检索
      - check_sufficiency 返回充分 → 提示无需重检
      - 改写后仍无结果 → 提示知识库无相关内容
      - check_sufficiency 自身失败（LLM 异常）→ reflector 内部默认充分
    """
    if not ctx.docs:
        return "（尚未检索到文档，请先调用 search_knowledge 等检索工具）"
    query = args.get("query") or ctx.query
    result = await reflector.check_sufficiency(query, ctx.docs)
    if result.get("sufficient"):
        return "（当前检索结果已充分，无需重检）"
    rewritten = result.get("rewritten_query", query)
    docs = await hybrid_retriever.retrieve(rewritten, top_k=5, mode="hybrid")
    ctx.add_docs(docs)
    if not docs:
        return f"改写查询 '{rewritten}' 后仍无结果，知识库可能无相关内容"
    return f"改写查询 '{rewritten}' → 检索到 {len(docs)} 篇文档：\n" + _format_docs(docs)


async def _note_to_self(ctx, args: dict) -> str:
    """记录中间发现或推理结论到工作笔记（module-041）"""
    note = args.get("note", "")
    if not note or not note.strip():
        return "（未提供笔记内容）"
    note = note.strip()[:500]  # 截断过长笔记
    ctx.add_note(note)
    return f"已记录笔记 ({len(ctx.scratchpad)}): {note[:200]}"


# ─── 内置工具注册 ───

_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "检索关键词（缺省用原始问题）"},
        "top_k": {"type": "integer", "description": "返回数量，默认 5"},
    },
    "required": ["query"],
}

_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "要提取实体的文本"}},
    "required": ["query"],
}

_MEMORY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "记忆检索查询"},
        "top_k": {"type": "integer", "description": "返回条数，默认 3"},
    },
    "required": ["query"],
}

_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "要回答的问题"}},
    "required": ["query"],
}

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "原始用户问题"},
        "answer": {"type": "string", "description": "待验证的答案文本（通常由 generate_answer 产出）"},
    },
    "required": ["answer"],
}

_RE_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "原始用户问题，缺省用 ctx.query"},
    },
}

_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string", "description": "要记录的笔记内容"},
    },
    "required": ["note"],
}


def register_builtin_tools(reg: Optional[ToolRegistry] = None) -> ToolRegistry:
    """注册 10 个内置工具到注册表（默认全局 registry）

    Args:
        reg: 目标注册表（测试可传入独立实例），None 用全局 registry

    Returns:
        注册完成后的注册表
    """
    reg = reg or registry
    reg.register(
        "search_knowledge",
        "混合检索：同时使用全文关键词与语义向量在知识库中检索相关文档，默认首选。",
        _SEARCH_SCHEMA, _search_knowledge,
    )
    reg.register(
        "search_fts",
        "全文检索：按精确关键词匹配知识库文档（适合专有名词、代码、精确术语）。",
        _SEARCH_SCHEMA, _search_fts,
    )
    reg.register(
        "search_vector",
        "向量检索：按语义相似度检索知识库文档（适合概念性、同义表述查询）。",
        _SEARCH_SCHEMA, _search_vector,
    )
    reg.register(
        "search_graph",
        "知识图谱检索：从查询中提取实体，沿实体关系图遍历返回关联文档。",
        _SEARCH_SCHEMA, _search_graph,
    )
    reg.register(
        "extract_entities",
        "从查询/文本中提取技术实体名称列表（返回 JSON）。",
        _ENTITY_SCHEMA, _extract_entities,
    )
    reg.register(
        "recall_memory",
        "召回该用户的跨会话长期记忆（历史问答沉淀，按用户隔离）。",
        _MEMORY_SCHEMA, _recall_memory,
    )
    reg.register(
        "generate_answer",
        "基于本次已检索到的全部文档生成带引用标注的最终答案。",
        _ANSWER_SCHEMA, _generate_answer,
    )
    reg.register(
        "verify_answer",
        "逐句验证已生成的答案是否被检索文档支持，标注每句的可信度（supported/inferred/unsupported），返回置信度。",
        _VERIFY_SCHEMA, _verify_answer,
    )
    reg.register(
        "re_search",
        "检索不足时自动改写查询重检：检查已有文档是否充分，不充分则用改写后的查询重新混合检索，新结果累积到已有文档。",
        _RE_SEARCH_SCHEMA, _re_search,
    )
    reg.register(
        "note_to_self",
        "记录中间发现或推理结论到工作笔记（草稿纸），后续轮次可参考。",
        _NOTE_SCHEMA, _note_to_self,
    )
    return reg


# 全局单例 — 无状态定义容器，多会话并发安全
registry = ToolRegistry()
register_builtin_tools()
