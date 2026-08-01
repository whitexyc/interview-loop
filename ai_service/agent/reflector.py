"""
自我反思与纠错 (Self-Reflection) — RAG 链路质量控制
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  Rerank (Top 5) → [Reflector.check_sufficiency] 检查是否充分
                       ├─ 充分 → [Reflector.generate_answer] 生成答案
                       └─ 不充分 → 改写 Query → 二次检索 → 合并文档 → 生成答案

为什么需要自我反思？
  这是 Agentic RAG 的核心特性。传统 RAG 是"检索一次就回答"，
  如果检索结果不相关，答案就错了。自我反思让 LLM 自己检查
  检索结果是否足够回答用户问题，不够就改写 query 再试一次。

  这是"Self-RAG" (https://arxiv.org/abs/2310.11511) 思想的具体实现。
  虽然不是完整的 Self-RAG（没有训练专门的 reflection token），
  但通过 prompt engineering 实现了类似的效果。

设计决策：
  1. 反思和生成使用同一 LLM 实例（ModelScope DeepSeek-V4-Pro）。
     反思任务不需要专门的"评估模型"，通用 LLM 通过 prompt 即可胜任。

  2. 反思 prompt 要求返回结构化 JSON，而不是自由文本。
     便于下游程序化判断（if sufficient → generate else 二次检索）。

  3. 二次检索的结果与原始结果合并（而不是替换）。
     因为改写后的 query 可能丢失部分原始意图，保留原始结果做互补。

  4. 生成 prompt 包含历史对话（history 参数），支持多轮追问。
     这是后来加的特性，最初 generate_answer 只接受当前 query。
"""
import json
import logging
from typing import AsyncGenerator, Optional

from llm.client import LLMFactory

logger = logging.getLogger(__name__)

# 反思 prompt：判断检索结果是否充分
# 要求 LLM 输出 JSON，包含 sufficient（是否充分）和 rewritten_query（改写后的查询）。
# 如果不充分，rewritten_query 会被用于二次检索。
_CHECK_PROMPT = """你是一个严格的答案质量检查员，倾向于使用已有文档。
只有在现有文档完全无法回答问题时才判定不充分。

用户问题: {query}

检索到的文档摘要:
{docs_summary}

规则（严格遵守）：
1. 如果文档内容与问题部分相关、间接相关、或能提供部分信息 → sufficient=true
2. 即使文档没有直接给出答案，但只要包含相关的背景知识 → sufficient=true
3. 只有文档内容与问题完全无关（完全不沾边）才 → sufficient=false
4. 默认倾向 sufficient=true，宁可使用不完美的文档也不要空跑二次检索

如果文档信息充分，返回: {{"sufficient": true, "reason": "..."}}
如果文档信息不充分，返回: {{"sufficient": false, "reason": "...", "rewritten_query": "改写的搜索关键词"}}

只返回 JSON，不要其他文字。"""

# 生成 prompt：基于检索文档生成回答
# 要求 LLM 用 [1][2] 格式标注引用来源，这是 RAG 答案"可溯源"的关键。
# sections（= 历史对话段 + 记忆段）是可选的，由 generate_answer 方法根据
# 传入的 history / memory 参数填充；两者均为空时 sections 为空串，
# 模板保留 {sections} 后的换行（对齐旧版 {history_section}\n 结构），
# 故空 sections 时 prompt 与旧版逐字节一致（零回归，review #2 实测验证）。
_GENERATE_PROMPT = """你是一个知识库问答助手。基于检索到的文档回答用户问题。

要求：
1. 引用文档原文进行回答，用 [1][2] 标注引用来源
2. 如果文档信息不足以回答问题，如实告知
3. 回答后附带引用文档列表

{sections}
用户问题: {query}

检索到的文档:
{docs_detail}

回答："""


class Reflector:
    """自我反思与 Query 改写

    职责：
    1. check_sufficiency: 检查检索结果是否充分，不充分时生成改写 query
    2. generate_answer: 基于检索文档 + 对话历史生成最终回答

    注意：这两个方法都调用 LLM，但用的是 generate（单轮生成）而非 chat。
    因为虽然逻辑上它需要"理解上下文"，但底层实现是拼接 prompt 而不是
    传 messages 数组。这是有意的设计选择，让 prompt 的组装更可控。
    """

    def __init__(self, provider: Optional[str] = None):
        # 默认用 modelscope 作为反思/生成模型
        # 为什么不用默认 LLM provider（deepseek）？
        # 因为反思任务对模型能力要求更高（需要推理能力），
        # ModelScope 上的 DeepSeek-V4-Pro 比 DeepSeek Flash 更强。
        self._provider = provider or "deepseek"  # ModelScope API 有 moderation 过滤问题，改用 DeepSeek

    async def check_sufficiency(self, query: str, documents: list[dict]) -> dict:
        """检查检索结果是否充分

        如果 LLM 判断检索结果不够回答问题，会返回一个 rewritten_query，
        这个 query 会被 engine.py 用于二次检索。

        Args:
            query: 原始查询
            documents: 检索到的文档列表

        Returns:
            充分时: {"sufficient": true, "reason": "..."}
            不充分时: {"sufficient": false, "reason": "...", "rewritten_query": "改写后的查询"}
        """
        if not documents:
            return {"sufficient": False, "reason": "未检索到任何文档",
                     "rewritten_query": query}

        try:
            # 只传前 5 个文档摘要给 LLM 检查，避免超出上下文窗口
            docs_summary = "\n".join(
                f"- [{i + 1}] {d.get('title', '')}: {d.get('content', '')[:200]}"
                for i, d in enumerate(documents[:5])
            )
            client = LLMFactory.get_client(self._provider)
            prompt = _CHECK_PROMPT.format(query=query, docs_summary=docs_summary)
            response = await client.generate(prompt)
            result = self._parse_check(response)
            logger.info("反思结果: sufficient=%s, rewritten=%s",
                        result.get("sufficient"),
                        result.get("rewritten_query", "无"))
            return result
        except Exception as e:
            # 反思失败时默认"充分"，避免反复重试导致无限循环
            logger.warning("反思检查失败，默认充分: %s", e)
            return {"sufficient": True, "reason": f"反思检查异常，默认通过: {e}"}

    async def generate_answer(
        self,
        query: str,
        documents: list[dict],
        history: Optional[list[dict]] = None,
        memory: str = "",
    ) -> str:
        """基于文档生成带引用的回答

        支持传入对话历史（history），保证多轮对话的上下文连贯性。
        例如用户先问"G1 GC的核心创新是什么"，再问"它和CMS有什么区别"，
        第二问的 prompt 中会包含第一问的对话记录，LLM 能理解"它"的指代。

        memory（module-023）：跨会话长期记忆片段，命中时以"历史记忆: ..."
        拼入生成 prompt；为空时不生成记忆段，行为与之前完全一致（零回归）。

        Args:
            query: 用户当前问题
            documents: 检索到的文档列表
            history: 历史对话列表，每项 {"role": str, "content": str}
            memory: 长期记忆文本片段（无记忆时为空字符串）
        """
        if not documents:
            return "抱歉，未检索到相关信息。"

        try:
            # 构造历史对话上下文
            # 只取最近 6 条消息（约 3 组问答），避免 prompt 过长
            history_section = ""
            if history:
                lines = []
                for msg in history:
                    role = "用户" if msg.get("role") == "user" else "AI助手"
                    lines.append(f"{role}: {msg.get('content', '')}")
                if lines:
                    history_section = "历史对话:\n" + "\n".join(lines[-6:]) + "\n"

            # 组装文档详情，每条带 [N] 引用编号
            docs_detail = "\n\n".join(
                f"[{i + 1}] {d.get('title', '')}\n来源: {d.get('source', '')}\n内容: {d.get('content', '')}"
                for i, d in enumerate(documents)
            )
            client = LLMFactory.get_client(self._provider)
            # 合并历史段与记忆段：两者为空时 sections=""，prompt 与旧版逐字节一致
            sections = history_section + (f"{memory}\n" if memory else "")
            prompt = _GENERATE_PROMPT.format(
                query=query,
                docs_detail=docs_detail,
                sections=sections,
            )
            response = await client.generate(prompt)
            return response
        except Exception as e:
            logger.error("答案生成失败: %s", e)
            return "抱歉，回答生成时遇到问题，请稍后重试。"

    async def generate_answer_stream(
        self,
        query: str,
        documents: list[dict],
        history: Optional[list[dict]] = None,
        memory: str = "",
    ) -> AsyncGenerator[str, None]:
        """流式生成答案，逐 token 产出

        与 generate_answer 逻辑相同，但使用 astream 替代 ainvoke。
        前置步骤（检索、反思）已完成，只流式传输 LLM 生成部分。
        memory（module-023）默认空串，不改变流式路径原有行为（零回归）。
        """
        if not documents:
            yield "抱歉，未检索到相关信息。"
            return

        try:
            history_section = ""
            if history:
                lines = []
                for msg in history:
                    role = "用户" if msg.get("role") == "user" else "AI助手"
                    lines.append(f"{role}: {msg.get('content', '')}")
                if lines:
                    history_section = "历史对话:\n" + "\n".join(lines[-6:]) + "\n"

            docs_detail = "\n\n".join(
                f"[{i + 1}] {d.get('title', '')}\n来源: {d.get('source', '')}\n内容: {d.get('content', '')}"
                for i, d in enumerate(documents)
            )

            client = LLMFactory.get_client(self._provider)
            # 合并历史段与记忆段：两者为空时 sections=""，prompt 与旧版逐字节一致
            sections = history_section + (f"{memory}\n" if memory else "")
            prompt = _GENERATE_PROMPT.format(
                query=query,
                docs_detail=docs_detail,
                sections=sections,
            )
            async for token in client.generate_stream(prompt):
                yield token
        except Exception as e:
            logger.error("流式答案生成失败: %s", e)
            yield "抱歉，回答生成时遇到问题，请稍后重试。"

    @staticmethod
    def _parse_check(response: str) -> dict:
        """解析 LLM 返回的检查结果 JSON

        与 router.py 的 _parse_response 类似，处理 LLM 输出中的
        非 JSON 杂质（markdown 包裹、多余文字等）。
        """
        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                result = json.loads(response[start:end + 1])
                sufficient = bool(result.get("sufficient", True))
                output = {"sufficient": sufficient, "reason": result.get("reason", "")}
                if not sufficient:
                    output["rewritten_query"] = result.get("rewritten_query", "")
                return output
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("解析反思结果失败: %s", e)
        return {"sufficient": True, "reason": "解析失败，默认充分"}


# 全局单例
reflector = Reflector()
