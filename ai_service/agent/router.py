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

L2 前置校验（module-043 / ADR-0003 修订版）：
  LLM 低置信（intent≠knowledge 且 confidence<0.5）时，用**确定性信号**确认
  是否涉及知识库——与 LLM 完全无关（同源复核已否决，红线：确认路径零 LLM）：
    ① FTS 术语命中：jieba 分词 query → documents.search_tokens 倒排匹配
       （复用 module-020 中文 FTS 通道），命中 ≥1 知识库专有术语 → 确认
    ② 图谱实体命中：图谱 Entity 名称出现在 query 中 → 确认（Cypher 拉实体
       名后 Python 子串匹配，全程无 LLM——不走 graph_extractor，其依赖 LLM）
    ③ 规则表：明确闲聊/实时特征词（"几点""天气""你是谁"），命中 → 保持原判
       （否决确认信号，防止"现在""天气"等常见词在知识库文档中的巧合命中误转）
  任何异常 → 保守 knowledge（宁多检不漏检）。

L4 分类器（module-043 / ADR-0003）：
  bge-m3 冻结特征 + 逻辑回归头（intent_classifier.py）可插拔注入
  （构造器注入 / 配置开关惰性加载），默认仍用 LLM；模型缺失/加载/推理失败
  一律回退 LLM 分类，零影响。
"""
import json
import logging
from typing import Optional

from llm.client import LLMFactory
from src.config import settings

logger = logging.getLogger(__name__)

# ── L2 前置校验配置（module-043 / ADR-0003 修订版） ──
# 触发条件：intent≠knowledge 且 LLM 低置信（单向信任：LLM 自报绝对值不可信，
# 但低置信是有效的"不放心"信号）。
_L2_CONFIDENCE_THRESHOLD = 0.5

# 规则表：明确闲聊/实时特征词，命中任一 → 保持原判（不修正为 knowledge）。
# 只收录几乎不可能出现在知识库问题中的词——"时间/温度"等词会误伤
# "停顿时间模型""温度监控"类知识库问题，不收录。
_RULE_TABLE = (
    # 实时：时间类（"几点" 无歧义，不会出现在知识库问题中）
    "几点", "几点了", "几点钟", "现在几点", "几号", "今天几号", "星期几",
    "今天星期", "周几", "今天周",
    # 实时：天气类
    "天气", "气温", "下雨", "下雪", "晴天", "阴天", "台风", "刮风",
    # 闲聊：身份/问候/寒暄
    # module-045 WP2a: 移除"你能做什么/你会什么"——golden 边界样本
    # "你能做什么？这个系统能帮我解决什么问题？" 标注 knowledge（问系统能力
    # 而非闲聊），规则表命中会否决 FTS/图谱确认信号（rule_veto），误伤边界样本
    "你是谁", "你叫什么", "你多大了", "介绍一下你自己",
    "你好", "您好", "嗨", "哈喽", "hello", "hi ", "在吗", "在不在", "再见", "拜拜",
    "谢谢", "感谢", "晚安", "早安", "辛苦了", "哈哈", "嗯嗯", "好的好的",
)

# 高频功能词/代词/疑问词：不计入 FTS 术语命中。"什么""怎么""区别"等词在
# 知识库文档中广泛存在，命中无判别力；只保留有专有术语特征的词参与确认。
_FUNCTION_STOPWORDS = frozenset((
    "什么", "怎么", "为什么", "哪些", "哪个", "如何", "请问", "知道", "可以",
    "是不是", "区别", "关系", "原理", "作用", "特点", "介绍", "了解", "解释",
    "说下", "讲讲", "情况", "时候", "什么时候", "然后", "这个", "那个", "这样",
    "那样", "我们", "你们", "他们", "咱们", "自己", "现在", "东西", "回事",
    "究竟", "到底", "为什么", "是", "的", "了", "吗", "呢", "吧", "啊", "呀",
    "哦", "喔", "嗯", "哈", "喂", "你", "我", "他", "她", "它", "您", "有",
    "没", "在", "和", "与", "及", "就", "都", "也", "很", "太",
))

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

    使用 LLM 对用户问题进行 zero-shot 分类（L4 分类器启用时替换决策主体）。
    实例化时可指定 provider，默认使用 settings.llm_provider。
    module-043：可注入 L4 意图分类器（intent_classifier，bge-m3+逻辑回归），
    默认仍用 LLM；LLM 低置信结果走 L2 确定性信号确认（见模块 docstring）。
    """

    def __init__(self, provider: Optional[str] = None,
                 intent_classifier: Optional[object] = None):
        self._provider = provider  # None = 用默认 provider
        # L4 可插拔分类器：显式注入优先（测试/定制）；None 时若配置开关开启
        # 则惰性加载一次，失败回退 LLM（零影响）
        self._intent_classifier = intent_classifier
        self._classifier_tried = intent_classifier is not None

    async def _get_classifier(self):
        """L4 分类器获取：注入优先；未注入且开关开启 → 惰性加载一次

        Returns:
            可用的分类器（有 predict_proba(query) -> dict[str, float]），
            不可用返回 None（回退 LLM 分类）
        """
        if self._intent_classifier is None and not self._classifier_tried:
            self._classifier_tried = True
            if settings.intent_classifier_enabled:
                try:
                    from agent.intent_classifier import IntentClassifier
                    clf = IntentClassifier()
                    if await clf.load():
                        self._intent_classifier = clf
                        logger.info("L4 意图分类器已加载: %s", clf.model_path)
                except Exception as e:
                    logger.warning("L4 分类器加载失败，回退 LLM 分类: %s", e)
        return self._intent_classifier

    async def classify(self, query: str) -> dict:
        """判断问题意图

        内部使用 LLM.generate() 发送 prompt 给 LLM，让 LLM 返回 JSON。
        使用 generate（单轮）而不是 chat（多轮），因为分类不需要上下文。
        module-043 增强：
          - L4 分类器可用时用它替换 LLM 决策主体（校准概率，无 LLM 调用）
          - LLM 低置信（intent≠knowledge 且 confidence<0.5）时走 L2 确定性
            信号确认（FTS 术语/图谱实体/规则表），命中 → 修正为 knowledge

        Args:
            query: 用户问题

        Returns:
            {"intent": str, "confidence": float, "reason": str}
            异常时默认返回 knowledge（保守策略）
        """
        if not query or not query.strip():
            return {"intent": "knowledge", "confidence": 0.0, "reason": "空查询，默认走知识库"}

        # ── L4 分类器路径（module-043）：可插拔注入，失败回退 LLM ──
        classifier = await self._get_classifier()
        if classifier is not None:
            try:
                probs = await classifier.predict_proba(query.strip())
                intent = max(probs, key=probs.get)
                # module-045 WP2d: L4 分类器返回的 intent 过白名单——非法值
                # 归 knowledge（与 LLM 路径 _parse_response 口径一致，防模型
                # 类别外漂移导致路由落入未知分支）
                if intent not in ("knowledge", "casual_chat", "realtime"):
                    intent = "knowledge"
                confidence = probs[intent]
                logger.info("意图识别(L4): query=%s, intent=%s, confidence=%.2f",
                            query[:50], intent, confidence)
                return {"intent": intent, "confidence": round(confidence, 4),
                        "reason": f"L4 classifier {probs}"}
            except Exception as e:
                logger.warning("L4 分类器推理失败，回退 LLM 分类: %s", e)

        try:
            client = LLMFactory.get_client(self._provider)
            prompt = _PROMPT_TEMPLATE.format(query=query.strip())
            response = await client.generate(prompt)
            result = self._parse_response(response)

            # ── L2 前置校验（module-043 / ADR-0003 修订版） ──
            # 触发：intent≠knowledge 且 LLM 低置信（confidence<0.5）。确认动作
            # 是确定性信号（_deterministic_confirm），与 LLM 完全无关。
            # confidence 缺失（降级/外部 mock 结果）时不触发：无"低置信"信号
            # 即无"不放心"依据，保持原判（零回归）。
            confidence = result.get("confidence")
            if (result.get("intent") != "knowledge"
                    and confidence is not None and confidence < _L2_CONFIDENCE_THRESHOLD):
                confirmed, signal = await self._deterministic_confirm(query.strip())
                if confirmed:
                    logger.info("L2 信号确认(%s)，intent 修正为 knowledge: query=%s",
                                signal, query[:50])
                    original_reason = result.get("reason", "")
                    result["intent"] = "knowledge"
                    result["reason"] = f"L2 信号确认({signal})，宁多检不漏检" + (
                        f" | 原判: {original_reason}" if original_reason else "")
                else:
                    logger.info("L2 无确认信号(%s)，保持原判 %s: query=%s",
                                signal, result.get("intent"), query[:50])
            logger.info("意图识别: query=%s, intent=%s, confidence=%.2f",
                        query[:50], result.get("intent"), result.get("confidence", 0))
            return result
        except Exception as e:
            # 任何异常都保守地返回 knowledge
            logger.warning("意图识别失败，默认走知识库: %s", e)
            return {"intent": "knowledge", "confidence": 0.0, "reason": f"LLM 分类失败，保守路由: {e}"}

    # ── L2 确定性信号确认（module-043 / ADR-0003 修订版，红线：零 LLM） ──

    async def _deterministic_confirm(self, query: str) -> tuple[bool, str]:
        """L2 确定性信号确认 — 与 LLM 完全无关（确认路径零 LLM 调用）

        信号（按优先级，FTS/图谱任一命中即确认；规则表命中保持原判）：
          ① FTS 术语命中（_fts_term_hit）→ confirmed
          ② 图谱实体命中（_graph_entity_hit）→ confirmed
          ③ 规则表（_rule_hits）→ 保持原判（否决 FTS/图谱的巧合命中）
        任何异常 → 保守 knowledge（宁多检不漏检，AC 场景 4）。

        Args:
            query: 用户问题原文

        Returns:
            (confirmed, signal)
            - confirmed=True → 修正为 knowledge
            - signal: fts_term / graph_entity / rule_veto / no_signal /
                      error_conservative（可观测：写入日志与 reason）
        """
        try:
            fts_hit = await self._fts_term_hit(query)
            graph_hit = await self._graph_entity_hit(query) if not fts_hit else False
            if self._rule_hits(query):
                # 规则表：明确闲聊/实时特征词 → 保持原判
                return False, "rule_veto"
            if fts_hit:
                return True, "fts_term"
            if graph_hit:
                return True, "graph_entity"
            return False, "no_signal"
        except Exception as e:
            # 信号查询失败 → 保守 knowledge（宁多检不漏检）
            logger.warning("L2 确定性信号确认异常，保守 knowledge: %s", e)
            return True, "error_conservative"

    @staticmethod
    def _kb_terms(query: str) -> list[str]:
        """从 query 提取用于 FTS 术语命中的词元（过滤功能词/单字）

        只保留长度 ≥2 且不在 _FUNCTION_STOPWORDS 中的 jieba 词元——
        "什么""区别"等词在知识库文档中广泛存在，命中无判别力。

        Args:
            query: 用户问题

        Returns:
            候选术语列表；纯闲聊（如"你好呀"）可能为空
        """
        from rag.text_tokenizer import tokenize
        return [
            tok for tok in tokenize(query).split()
            if len(tok) >= 2 and tok not in _FUNCTION_STOPWORDS
        ]

    async def _fts_term_hit(self, query: str) -> bool:
        """① FTS 术语命中：任一知识库专有术语出现在倒排索引（search_tokens）

        复用 module-020 中文 FTS 通道的匹配语义：jieba 预分词写入的
        search_tokens 经 to_tsvector('simple') 切分，plainto_tsquery 单术语
        @@ 匹配（大小写不敏感，'GC' 与 'gc' 等价）。只查知识库文档
        （排除 memory:% 记忆文档）。逐术语短回路查询，命中即返。

        Args:
            query: 用户问题

        Returns:
            命中 ≥1 知识库专有术语 → True
        """
        terms = self._kb_terms(query)
        if not terms:
            return False
        from sqlalchemy import text
        from src.database import async_session_factory
        async with async_session_factory() as session:
            for term in terms:
                row = await session.execute(text("""
                    SELECT 1 FROM documents
                    WHERE search_tokens IS NOT NULL
                      AND parent_id IS NOT NULL
                      AND (source IS NULL OR source NOT LIKE 'memory:%')
                      AND to_tsvector('simple', search_tokens)
                          @@ plainto_tsquery('simple', :term)
                    LIMIT 1
                """), {"term": term})
                if row.scalar_one_or_none() is not None:
                    logger.info("L2 FTS 术语命中: term=%s, query=%s", term, query[:50])
                    return True
        return False

    async def _graph_entity_hit(self, query: str) -> bool:
        """② 图谱实体命中：图谱 Entity 名称（≥2 字符）出现在 query 中

        确定性实现（红线：不调 LLM）：Cypher 拉取实体名列表 → Python 子串
        匹配。不走 graph_extractor——其 extract_from_query 依赖 LLM，确认
        路径禁用。实体名是知识库专有名词（如 GC/G1/JVM），子串匹配即可。

        Args:
            query: 用户问题

        Returns:
            query 包含任一实体名 → True；图谱不可用抛异常（由调用方保守降级）
        """
        import json
        from sqlalchemy import text
        from src.database import async_session_factory
        from rag.graph_store import GRAPH_NAME
        async with async_session_factory() as session:
            await session.execute(text("LOAD 'age'"))
            await session.execute(text('SET search_path = ag_catalog, "$user", public'))
            rows = (await session.execute(text(f"""
                SELECT * FROM cypher('{GRAPH_NAME}', $$
                    MATCH (e:Entity) RETURN e.name LIMIT 200
                $$) AS (name agtype)
            """))).fetchall()
        for row in rows:
            if row[0] is None:
                continue
            try:
                name = json.loads(str(row[0]))
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(name, str) and len(name) >= 2 and name in query:
                logger.info("L2 图谱实体命中: entity=%s, query=%s", name, query[:50])
                return True
        return False

    @staticmethod
    def _rule_hits(query: str) -> bool:
        """③ 规则表命中：明确闲聊/实时特征词出现在 query 中 → 保持原判

        Args:
            query: 用户问题

        Returns:
            query 含任一规则词 → True
        """
        q = query.lower()
        return any(word.lower() in q for word in _RULE_TABLE)

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
