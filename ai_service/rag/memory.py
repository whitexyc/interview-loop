"""
长期记忆服务 — 跨会话记忆沉淀（module-023 / module-032 身份化）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

系统无长期记忆（只有 Redis 短期缓存 + 内存 IP 会话，重启丢失）。
本模块提供跨会话记忆：复用 documents 表（source='memory:<identity>:' 区分），
无新表，复用分块（chunker）/向量化（本地 bge-m3）/检索（hybrid_retriever）全链路。

- save(content, identity): 分块 → 向量化 → 写 documents（父块无向量 + 子块含向量）
- recall(query, identity): hybrid_retriever 限定 source 过滤，只查该身份的
  记忆，返回 Top-K

身份（module-032）：
- identity = user_id（JWT.sub）优先，否则 client_ip（匿名降级，零回归）
- 用户登录后记忆按 user_id 隔离（跨设备/跨会话）；匿名访客仍按 client_ip 隔离

隔离设计：
- 记忆检索 source_pattern='memory:<identity>:%'，只查该身份的记忆文档；
  source 以尾冒号分隔身份与内容（'memory:<identity>:'），避免前缀重叠
  （如 1.1.1.1 与 1.1.1.10）经 LIKE 交叉泄漏记忆
- identity 必须通过规范化校验（_normalize_identity，空/含 LIKE 元字符降级
  'unknown'），且 pattern 构造处对 LIKE 元字符转义（_escape_like），双保险
  杜绝通配符注入（如 identity="%" 构造 'memory:%:%' 匹配全部记忆）绕过隔离
- 普通知识库检索默认排除 'memory:%' 前缀（见 retriever._source_condition），
  保证记忆不污染知识库检索结果
"""
import hashlib
import logging
import re
from datetime import date

from sqlalchemy import func, select

from src.config import settings
from src.database import async_session_factory
from rag.models import Document
from rag.chunker import chunker
from rag.embeddings import embedding_service
from rag.retriever import hybrid_retriever
from rag.text_tokenizer import tokenize

logger = logging.getLogger(__name__)

# 记忆 source 前缀：source='memory:<identity>:' 区分记忆与知识库文档
#（尾冒号为身份与内容的分隔符；identity = user_id 优先，否则 client_ip）
MEMORY_SOURCE_PREFIX = "memory:"
DEFAULT_IDENTITY = "unknown"
# identity 中禁止出现的 LIKE 元字符（review #1 双保险：拒绝 + 转义）。
# user_id 由 JWT 下发（服务端签发，可信）；client_ip 由中间件从 X-Forwarded-For
# 提取。两者均可含任意字符串，故统一按 LIKE 元字符校验 + 转义，杜绝注入。
_LIKE_META_RE = re.compile(r"[%_\\]")


def _normalize_identity(identity: str) -> str:
    """规范化并校验身份标识（user_id 或 client_ip）（review #1 安全加固）

    - 空白 → 'unknown'
    - 含 LIKE 通配符 '%'/'_'、反斜杠等 → 'unknown'（防御性降级，
      任何客户端可控 identity 都无法借 source_pattern 匹配到其他用户的记忆）
    - 其余（合法 IPv4 或 JWT 下发的 user_id）→ 原样返回

    Args:
        identity: 身份标识（user_id 优先，否则 client_ip）

    Returns:
        规范化后的 identity 或 'unknown'
    """
    identity = (identity or "").strip()
    if not identity:
        return DEFAULT_IDENTITY
    if _LIKE_META_RE.search(identity):
        return DEFAULT_IDENTITY
    return identity


def _escape_like(s: str) -> str:
    """转义 SQL LIKE 模式元字符（\\、%、_）（review #1 双保险）

    在 _normalize_identity 校验之外再做一层转义，即使未来校验规则被放宽，
    注入到 LIKE pattern 的 identity 也不会被当作通配符。

    Args:
        s: 已规范化的身份标识（user_id 或 client_ip）

    Returns:
        转义后可用于 LIKE pattern 的字符串
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def format_memory_line(memory: dict) -> str:
    """格式化单条召回记忆为 '[长期记忆 - YYYY-MM-DD]：内容'（module-033）

    带日期前缀帮助生成模型区分记忆与当前对话；无 created_at（或解析失败）
    时省略日期，仅保留 '[长期记忆]：内容'。格式化逻辑放本模块，由
    engine._recall_memory 拼接注入 prompt。

    Args:
        memory: 召回记忆 dict，含 content；created_at 可选（'YYYY-MM-DD' 或 None）

    Returns:
        形如 "[长期记忆 - 2026-08-05]：用户偏好简洁回答" 的格式化字符串
    """
    content = memory.get("content") or ""
    created_at = memory.get("created_at")
    prefix = f"[长期记忆 - {created_at}]" if created_at else "[长期记忆]"
    return f"{prefix}：{content}"


def _date_str(value) -> str | None:
    """把 datetime/日期字符串规范化为 'YYYY-MM-DD'；无法解析返回 None

    Args:
        value: datetime 对象、字符串或 None

    Returns:
        'YYYY-MM-DD' 字符串；None/无法解析时返回 None
    """
    if value is None:
        return None
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    s = str(value)
    return s[:10] if len(s) >= 10 else None


class MemoryService:
    """长期记忆服务（跨会话记忆沉淀）

    职责：
    - save: 保存一条记忆到 documents（source='memory:<identity>:'）
    - recall: 检索与身份相关的历史记忆（source 过滤，按身份隔离）
    """

    async def save(self, content: str, identity: str = DEFAULT_IDENTITY,
                   dedup: bool = True) -> dict:
        """保存一条长期记忆

        流程（dedup=True 默认，module-033）：
          1. 语义去重：与本身份现有记忆嵌入 cosine 相似度最高值 > 阈值
             （settings.memory_dedup_threshold=0.95）→ 视为重复 → 更新既有
             父块（追加内容）并返回 status="updated"（不新增行，库内条数不涨）
          2. 未命中重复 → 分块（复用 chunker）→ 写父块 → 子块向量化 + 写子块
             （细节拆分到 _insert_parents / _insert_children）；embedding 失败时
             整体 rollback，不会留下无向量的"残缺"记忆记录
        去重检索/嵌入失败 → 降级为正常新增（不阻塞，与"去重失败降级"约定一致）。

        Args:
            content: 记忆内容（不能为空）
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            dedup: 写入前是否语义去重（默认 True；手动 save 也去重，统一防堆积）

        Returns:
            {"id": int, "title": str, "status": "saved"} 或 {"status": "updated"}

        Raises:
            ValueError: content 为空
            RuntimeError: 向量化或入库失败
        """
        if not content or not content.strip():
            raise ValueError("记忆内容不能为空")
        # 规范化 + 校验身份：空/含 LIKE 通配符一律降级为 'unknown'，
        # 防止通配符注入绕过按身份隔离（review #1）
        identity = _normalize_identity(identity)
        # source 带尾冒号分隔符：'memory:<identity>:'，配合 recall 的
        # 'memory:<identity>:%' LIKE 匹配，避免前缀重叠身份（如 192.168.1.1
        # 与 192.168.1.10）交叉泄漏记忆
        source = f"{MEMORY_SOURCE_PREFIX}{identity}:"

        # module-033 语义去重：写入前查重，命中重复则更新旧记忆而非新增。
        # 任何去重异常降级为正常新增（不阻塞，零回归）
        if dedup:
            try:
                duplicate = await self._find_duplicate(content, identity)
                if duplicate is not None:
                    merged = await self._merge_duplicate(duplicate, content)
                    if merged is not None:
                        return merged
            except Exception as e:
                logger.warning("记忆去重失败，按新增处理: %s", e)

        # 当日参数传 date 对象而非 ISO 字符串：字符串经 asyncpg 绑定为 VARCHAR，
        # PG 无 date=varchar 运算符 → 真实 save 崩溃（tester 阻塞 #1 回归）
        title = await self._next_title(date.today(), identity)

        # 分块：短内容无 ## 标题 → parents 为空 → 兜底单父块
        chunk_result = chunker.chunk(content, source=source)
        parents = chunk_result.get("parents", [])
        children = chunk_result.get("children", [])
        if not parents:
            parents = [{"title": title, "content": content}]
            children = [{"title": title, "content": content, "parent_index": 0}]

        async with async_session_factory() as session:
            try:
                # 1. 插入父块（无向量，供子块引用），flush 获取 DB ID
                parent_objs = await self._insert_parents(session, parents, title, source)
                # 2. 子块向量化 + 插入（embedding 失败则整体 rollback，不留残缺记录）
                await self._insert_children(session, children, parent_objs, title, source)
                await session.commit()
                logger.info("记忆保存成功: title=%s, source=%s, chunks=%d",
                            title, source, len(parent_objs) + len(children))
                return {"id": parent_objs[0].id, "title": title, "status": "saved"}
            except Exception as e:
                await session.rollback()
                logger.error("记忆保存失败: %s", e)
                raise RuntimeError("记忆保存失败") from e

    async def _find_duplicate(self, content: str, identity: str):
        """语义去重：与本身份现有记忆嵌入 cosine 最高相似度 > 阈值 → 返回重复记忆

        流程：
          1. 新事实向量化（失败 → None，视为无重复，不阻塞）
          2. 查本身份现有记忆子块（source='memory:<identity>:%' 且带向量）
          3. 嵌入已 L2 归一化，cosine 相似度 = 点积；逐条计算取最高
          4. 最高相似度 > settings.memory_dedup_threshold → 返回该子块

        任何异常降级返回 None（视为无重复 → 正常新增）。

        Args:
            content: 新记忆内容
            identity: 已规范化的身份标识（user_id 优先，否则 client_ip）

        Returns:
            命中重复时返回最佳匹配子块 Document（含 parent_id）；否则 None
        """
        try:
            new_emb = await embedding_service.embed_text(content)
        except Exception as e:
            logger.warning("去重向量化失败，视为无重复: %s", e)
            return None
        safe_identity = _escape_like(identity)
        pattern = f"{MEMORY_SOURCE_PREFIX}{safe_identity}:%"
        try:
            async with async_session_factory() as session:
                rows = await session.execute(
                    select(Document).where(
                        Document.source.like(pattern),
                        Document.embedding.isnot(None),
                        Document.parent_id.isnot(None),
                    )
                )
                existing = rows.scalars().all()
        except Exception as e:
            logger.warning("去重检索失败，视为无重复: %s", e)
            return None

        best = None
        best_sim = 0.0
        for doc in existing:
            emb = doc.embedding
            if not emb:
                continue
            sim = sum(a * b for a, b in zip(new_emb, emb))
            if sim > best_sim:
                best_sim = sim
                best = doc
        if best is not None and best_sim > settings.memory_dedup_threshold:
            logger.info("记忆去重命中: identity=%s, sim=%.3f, id=%d",
                        identity, best_sim, best.id)
            return best
        return None

    async def _merge_duplicate(self, duplicate, content: str) -> dict | None:
        """语义重复记忆：更新既有父块（追加内容）而非新增，返回 status='updated'

        不新增任何行（库内条数不涨）；把新内容追加到既有父块 content，
        父块 id/title 保持不变，召回仍按既有子块向量命中映射回父块。
        父块缺失/更新失败 → 返回 None（由调用方 save 兜底为正常新增）。

        Args:
            duplicate: _find_duplicate 命中的子块 Document（含 parent_id）
            content: 新记忆内容

        Returns:
            {"id": int, "title": str, "status": "updated"}；失败返回 None
        """
        parent_id = duplicate.parent_id or duplicate.id
        try:
            async with async_session_factory() as session:
                parent = await session.get(Document, parent_id)
                if parent is None:
                    logger.warning("去重命中但父块不存在(id=%d)，按新增处理", parent_id)
                    return None
                if content not in parent.content:
                    parent.content = f"{parent.content}\n{content}"
                await session.commit()
                logger.info("记忆去重更新旧记忆: id=%d, title=%s", parent.id, parent.title)
                return {"id": parent.id, "title": parent.title, "status": "updated"}
        except Exception as e:
            logger.warning("记忆去重更新失败，按新增处理: %s", e)
            return None

    async def _insert_parents(
        self, session, parents: list[dict], title: str, source: str,
    ) -> list[Document]:
        """插入父块（无向量，供子块引用）并 flush 获取 DB ID

        Args:
            session: 数据库会话（事务由调用方 save 持有）
            parents: 父块列表，每项 {"title": str, "content": str}
            title: 记忆标题（父块无标题时兜底）
            source: 记忆 source 标识（'memory:<identity>:'）

        Returns:
            已 flush 的父块 Document 列表（含 id，供子块引用）
        """
        parent_objs = []
        for p in parents:
            doc = Document(
                title=p.get("title") or title,
                content=p["content"],
                source=source,
                embedding=None,
                parent_id=None,
                content_hash=hashlib.sha256(p["content"].encode("utf-8")).hexdigest(),
            )
            session.add(doc)
            parent_objs.append(doc)
        await session.flush()
        return parent_objs

    async def _insert_children(
        self, session, children: list[dict], parent_objs: list[Document],
        title: str, source: str,
    ) -> None:
        """向量化子块并插入（含向量 + search_tokens + parent_id）

        Args:
            session: 数据库会话（事务由调用方 save 持有）
            children: 子块列表，每项 {"title", "content", "parent_index"}
            parent_objs: 已 flush 的父块对象列表（子块引用其 id）
            title: 记忆标题（子块无标题时兜底）
            source: 记忆 source 标识（'memory:<identity>:'）
        """
        child_texts = [c["content"] for c in children]
        embeddings = await embedding_service.embed_documents(child_texts)

        for i, (child, emb) in enumerate(zip(children, embeddings)):
            parent_idx = child.get("parent_index", 0)
            if parent_idx >= len(parent_objs):
                parent_idx = 0  # 安全兜底
            parent = parent_objs[parent_idx]
            session.add(Document(
                title=child.get("title") or title,
                content=child["content"],
                source=source,
                embedding=emb,
                parent_id=parent.id,
                content_hash=hashlib.sha256(child["content"].encode("utf-8")).hexdigest(),
                search_tokens=tokenize(child["content"]),
            ))

    async def recall(
        self, query: str, identity: str = DEFAULT_IDENTITY, top_k: int = 5,
    ) -> list[dict]:
        """检索与 query 相关的长期记忆（按身份隔离；动态 K 召回，module-033）

        复用 hybrid_retriever（source_pattern 限定 'memory:<identity>:%'），
        检索命中的子块再映射回父块，返回完整记忆内容（同父块去重取最高分）。

        module-033 动态 K：先取 top_k 个候选，按候选平均相似度动态调整最终
        召回条数（均值>0.85→5 / 0.75-0.85→3 / <0.75→1，宁缺毋滥）——候选
        质量越高多召回几条，越低只保留最相关一条。每条结果新增 created_at
        （'YYYY-MM-DD' 或 None），供 '[长期记忆 - 日期]：内容' 格式化注入。

        Args:
            query: 检索查询
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            top_k: 动态 K 的最大候选数（默认 5，同时是动态 K 的条数上限）

        Returns:
            [{"content": str, "score": float, "title": str, "created_at": str|None}, ...]
            按 score 降序；query 为空或检索失败时返回空列表
        """
        if not query or not query.strip():
            return []
        # 规范化 + 校验身份，并对 LIKE 元字符转义（双保险，review #1）：
        # 客户端传 identity="%" 或 "_" 时不会构造出 'memory:%:%' 匹配全部记忆
        safe_identity = _escape_like(_normalize_identity(identity))
        try:
            docs = await hybrid_retriever.retrieve(
                query, top_k=top_k, source_pattern=f"{MEMORY_SOURCE_PREFIX}{safe_identity}:%",
            )
        except Exception as e:
            logger.warning("记忆检索失败，返回空记忆: %s", e)
            return []
        if not docs:
            return []
        # module-033 动态 K：按候选平均相似度调整召回条数（宁缺毋滥）
        avg_score = sum(
            d.get("hybrid_score", d.get("score", 0.0)) for d in docs
        ) / len(docs)
        dynamic_k = self._dynamic_k(avg_score)
        memories = await self._expand_to_parents(docs)
        return memories[:dynamic_k]

    @staticmethod
    def _dynamic_k(avg_score: float) -> int:
        """按候选平均相似度动态调整召回 K（module-033，宁缺毋滥）

        Args:
            avg_score: 检索候选的平均相似度（0-1）

        Returns:
            召回条数：>0.85 → 5；0.75-0.85 → 3；<0.75 → 1
        """
        if avg_score > settings.memory_recall_high_threshold:
            return settings.memory_max_recall
        if avg_score >= settings.memory_recall_mid_threshold:
            return 3
        return 1

    async def _next_title(self, day: date, identity: str) -> str:
        """生成标题 '记忆-<日期>-<序号>'（序号=本身份当日已存记忆父块数+1）

        只统计父块（parent_id IS NULL），并按「本身份 + 当日」过滤：
        - source LIKE 'memory:<identity>:%'（身份规范化 + 转义，review #1）
        - created_at 落在当日（避免序号跨日期累计，review #4）
        不依赖标题格式：记忆内容含 markdown 标题时父块标题为标题文本
        （非 '记忆-<日期>-NN'），若按标题统计会漏计导致序号重复/跳号。

        Args:
            day: 日期（datetime.date 对象，SQLAlchemy 绑定为 DATE；不可传
                ISO 字符串，否则 asyncpg 绑定为 VARCHAR，PG 无 date=varchar
                运算符导致真实查询崩溃 — tester 阻塞 #1）
            identity: 已规范化的身份标识（空/非法已由调用方降级为 'unknown'）
        """
        prefix = f"记忆-{day}-"
        safe_identity = _escape_like(identity)
        pattern = f"{MEMORY_SOURCE_PREFIX}{safe_identity}:%"
        async with async_session_factory() as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(Document)
                    .where(
                        Document.source.like(pattern),
                        Document.parent_id.is_(None),
                        func.date(Document.created_at) == day,
                    )
                )
            ).scalar() or 0
        return f"{prefix}{count + 1:02d}"

    async def _expand_to_parents(self, child_docs: list[dict]) -> list[dict]:
        """子块命中 → 父块内容（完整记忆），同父块去重取最高分

        module-033：每条结果新增 created_at（'YYYY-MM-DD' 或 None），
        取自父块创建时间（子块无父块时回退子块自身的 created_at），
        供 '[长期记忆 - 日期]：内容' 格式化注入。

        Args:
            child_docs: 检索命中的子块列表

        Returns:
            [{"content": str, "score": float, "title": str, "created_at": str|None}, ...]
            按 score 降序
        """
        if not child_docs:
            return []
        parent_ids = {d.get("parent_id") for d in child_docs if d.get("parent_id")}
        parents = {}
        if parent_ids:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(Document).where(Document.id.in_(parent_ids))
                )
                parents = {p.id: p for p in result.scalars().all()}

        best: dict[str, dict] = {}
        for d in child_docs:
            p = parents.get(d.get("parent_id"))
            content = p.content if p else d.get("content", "")
            if not content:
                continue
            score = d.get("hybrid_score", d.get("score", 0.0))
            if content not in best or score > best[content]["score"]:
                created_at = _date_str(p.created_at) if p else _date_str(d.get("created_at"))
                best[content] = {
                    "content": content,
                    "score": round(score, 4),
                    "title": p.title if p else d.get("title", ""),
                    "created_at": created_at,
                }
        return sorted(best.values(), key=lambda m: m["score"], reverse=True)


# 全局单例 — 整个应用共享一个 MemoryService 实例（无状态）
memory_service = MemoryService()
