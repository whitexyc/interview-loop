"""
意图识别路由 (Router Agent) — RAG 链路第一关
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  用户 Query → [Router Agent] 分类
                  ├─ knowledge  ──→ 知识库检索路径（主力路径）
                  ├─ casual_chat ──→ 直接 LLM 回答（跳过检索）
                  └─ realtime    ──→ 🔜 实时数据（未实现）

为什么需要意图路由？
  如果没有路由，每个问题都会走"检索→反思→生成"全链路。
  对于"你好"这种闲聊，检索知识库不仅浪费算力，还可能返回无关内容
  污染 LLM 的上下文。路由让系统只在必要时进行检索。

设计决策：
  LLM-as-Classifier：用 LLM 做分类而不是传统 ML 分类器。
  原因是：
  1. 传统分类器需要标注数据训练，维护成本高
  2. LLM zero-shot 即可分类，且能给出推理理由
  3. 新增类别无需重新训练，只需修改 prompt

  保守策略：当 LLM 分类失败或超时时，默认返回 "knowledge" 意图。
  宁可多检索一次，也不要漏检。这是"安全优先"的设计。
"""
import json
import logging
from typing import Optional

from llm.client import LLMFactory

logger = logging.getLogger(__name__)

# 意图分类的 prompt 模板
# 设计要点：
# 1. 要求 LLM 只返回 JSON，纯文本会破坏下游解析
# 2. 给出 3 个明确的类别定义，每个带具体例子
# 3. 要求返回 confidence 分数，便于下游做阈值判断
# 4. 要求返回 reason，便于调试和审计
_PROMPT_TEMPLATE = """你是一个问题分类器。判断用户问题的意图，只返回 JSON。

类别定义：
- knowledge: 询问知识库中的信息、文档内容、专业知识等（需要检索）
- casual_chat: 日常聊天、问候、寒暄等（不需要检索）
- realtime: 查询实时数据、当前时间、天气等（需要实时数据源）

用户问题: {query}

返回格式（只返回 JSON，不要其他文字）:
{{"intent": "knowledge|casual_chat|realtime", "confidence": 0.0-1.0, "reason": "简短原因"}}"""


class RouterAgent:
    """意图识别路由器

    使用 LLM 对用户问题进行 zero-shot 分类。
    实例化时可指定 provider，默认使用 settings.llm_provider。
    """

    def __init__(self, provider: Optional[str] = None):
        self._provider = provider  # None = 用默认 provider

    async def classify(self, query: str) -> dict:
        """判断问题意图

        内部使用 LLM.generate() 发送 prompt 给 LLM，让 LLM 返回 JSON。
        使用 generate（单轮）而不是 chat（多轮），因为分类不需要上下文。

        Args:
            query: 用户问题

        Returns:
            {"intent": str, "confidence": float, "reason": str}
            异常时默认返回 knowledge（保守策略）
        """
        if not query or not query.strip():
            return {"intent": "knowledge", "confidence": 0.0, "reason": "空查询，默认走知识库"}

        try:
            client = LLMFactory.get_client(self._provider)
            prompt = _PROMPT_TEMPLATE.format(query=query.strip())
            response = await client.generate(prompt)
            result = self._parse_response(response)
            logger.info("意图识别: query=%s, intent=%s, confidence=%.2f",
                        query[:50], result.get("intent"), result.get("confidence", 0))
            return result
        except Exception as e:
            # 任何异常都保守地返回 knowledge
            logger.warning("意图识别失败，默认走知识库: %s", e)
            return {"intent": "knowledge", "confidence": 0.0, "reason": f"LLM 分类失败，保守路由: {e}"}

    @staticmethod
    def _parse_response(response: str) -> dict:
        """解析 LLM 返回的 JSON

        LLM 可能返回带 markdown 包裹的 JSON（```json...```），
        也可能返回纯 JSON。这里先提取 {} 块再解析。

        为什么不用 json.loads 直接解析？
        因为 LLM 有时会在 JSON 前后加多余文字（如"好的，这是分类结果:"），
        直接解析会失败。提取 JSON 块的方式更鲁棒。
        """
        try:
            # 尝试提取 JSON 块：找到第一个 { 和最后一个 }
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                json_str = response[start:end + 1]
                result = json.loads(json_str)
                intent = result.get("intent", "knowledge")
                # 校验 intent 值是否合法，防止 LLM 胡编乱造
                if intent not in ("knowledge", "casual_chat", "realtime"):
                    intent = "knowledge"
                return {
                    "intent": intent,
                    "confidence": float(result.get("confidence", 0.5)),
                    "reason": result.get("reason", ""),
                }
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning("解析 LLM 响应失败: %s", e)

        return {"intent": "knowledge", "confidence": 0.0, "reason": "解析失败，默认走知识库"}


# 全局单例
router_agent = RouterAgent()
