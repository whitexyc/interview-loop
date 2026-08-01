"""
长期记忆服务 — 跨会话记忆沉淀（module-023）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

系统无长期记忆（只有 Redis 短期缓存 + 内存 IP 会话，重启丢失）。
本模块提供跨会话记忆：复用 documents 表（source='memory:<ip>:' 区分），
无新表，复用分块（chunker）/向量化（本地 bge-m3）/检索（hybrid_retriever）全链路。

- save(content, ip): 分块 → 向量化 → 写 documents（父块无向量 + 子块含向量）
- recall(query, ip): hybrid_retriever 限定 source 过滤，只查本 IP 记忆，返回 Top-K

隔离设计：
- 记忆检索 source_pattern='memory:<ip>:%'，只查该 IP 的记忆文档；
  source 以尾冒号分隔 IP 与内容（'memory:<ip>:'），避免前缀重叠 IP
  （如 1.1.1.1 与 1.1.1.10）经 LIKE 交叉泄漏记忆
- ip 必须通过 IPv4 格式校验（_normalize_ip，空/非法降级 'unknown'），
  且 pattern 构造处对 LIKE 元字符转义（_escape_like），双保险杜绝
  通配符注入（如 ip="%" 构造 'memory:%:%' 匹配全部记忆）绕过按 IP 隔离
- 普通知识库检索默认排除 'memory:%' 前缀（见 retriever._source_condition），
  保证记忆不污染知识库检索结果
"""
import hashlib
import logging
import re
from datetime import date

from sqlalchemy import func, select

from src.database import async_session_factory
from rag.models import Document
from rag.chunker import chunker
from rag.embeddings import embedding_service
from rag.retriever import hybrid_retriever
from rag.text_tokenizer import tokenize

logger = logging.getLogger(__name__)

# 记忆 source 前缀：source='memory:<ip>:' 区分记忆与知识库文档（尾冒号为 IP 与内容的分隔符）
MEMORY_SOURCE_PREFIX = "memory:"
DEFAULT_IP = "unknown"
# IPv4 格式校验（review #1）：仅数字与点组成，天然不含 LIKE 元字符，
# 校验通过即可保证 ip 无法向 source_pattern 注入通配符绕过按 IP 隔离
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _normalize_ip(ip: str) -> str:
    """规范化并校验 IP 标识（review #1 安全加固）

    - 空白 → 'unknown'
    - 非 IPv4（含 LIKE 通配符 '%'/'_'、反斜杠等）→ 'unknown'（防御性降级，
      任何客户端可控 ip 都无法借 source_pattern 匹配到其他 IP 的记忆）
    - 合法 IPv4 → 原样返回

    Args:
        ip: 客户端传入的 IP 标识

    Returns:
        规范化后的 IP（仅数字与点或 'unknown'）
    """
    ip = (ip or "").strip()
    if not ip:
        return DEFAULT_IP
    if _IPV4_RE.match(ip) is None:
        return DEFAULT_IP
    return ip


def _escape_like(s: str) -> str:
    """转义 SQL LIKE 模式元字符（\\、%、_）（review #1 双保险）

    在 _normalize_ip 校验之外再做一层转义，即使未来校验规则被放宽，
    注入到 LIKE pattern 的 ip 也不会被当作通配符。

    Args:
        s: 已规范化的 IP（仅数字与点）

    Returns:
        转义后可用于 LIKE pattern 的字符串
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemoryService:
    """长期记忆服务（跨会话记忆沉淀）

    职责：
    - save: 保存一条记忆到 documents（source='memory:<ip>:'）
    - recall: 检索与本 IP 相关的历史记忆（source 过滤，按 IP 隔离）
    """

    async def save(self, content: str, ip: str = DEFAULT_IP) -> dict:
        """保存一条长期记忆

        流程：分块（复用 chunker）→ 写父块 → 子块向量化 + 写子块（细节拆分到
        _insert_parents / _insert_children）；embedding 失败时整体 rollback，
        不会留下无向量的"残缺"记忆记录。

        Args:
            content: 记忆内容（不能为空）
            ip: 用户 IP 标识（空/空白则默认 'unknown'）

        Returns:
            {"id": int, "title": str, "status": "saved"}

        Raises:
            ValueError: content 为空
            RuntimeError: 向量化或入库失败
        """
        if not content or not content.strip():
            raise ValueError("记忆内容不能为空")
        # 规范化 + 校验 IP：空/非 IPv4（含 LIKE 通配符）一律降级为 'unknown'，
        # 防止通配符注入绕过按 IP 隔离（review #1）
        ip = _normalize_ip(ip)
        # source 带尾冒号分隔符：'memory:<ip>:'，配合 recall 的 'memory:<ip>:%
        # LIKE 匹配，避免前缀重叠 IP（如 192.168.1.1 与 192.168.1.10）交叉泄漏记忆
        source = f"{MEMORY_SOURCE_PREFIX}{ip}:"
        # 当日参数传 date 对象而非 ISO 字符串：字符串经 asyncpg 绑定为 VARCHAR，
        # PG 无 date=varchar 运算符 → 真实 save 崩溃（tester 阻塞 #1 回归）
        title = await self._next_title(date.today(), ip)

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

    async def _insert_parents(
        self, session, parents: list[dict], title: str, source: str,
    ) -> list[Document]:
        """插入父块（无向量，供子块引用）并 flush 获取 DB ID

        Args:
            session: 数据库会话（事务由调用方 save 持有）
            parents: 父块列表，每项 {"title": str, "content": str}
            title: 记忆标题（父块无标题时兜底）
            source: 记忆 source 标识（'memory:<ip>:'）

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
            source: 记忆 source 标识（'memory:<ip>:'）
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
        self, query: str, ip: str = DEFAULT_IP, top_k: int = 5,
    ) -> list[dict]:
        """检索与 query 相关的长期记忆（按 IP 隔离）

        复用 hybrid_retriever（source_pattern 限定 'memory:<ip>:%'），
        检索命中的子块再映射回父块，返回完整记忆内容（同父块去重取最高分）。

        Args:
            query: 检索查询
            ip: 用户 IP 标识（空/空白则默认 'unknown'）
            top_k: 返回最大记忆条数

        Returns:
            [{"content": str, "score": float, "title": str}, ...]
            按 score 降序；query 为空或检索失败时返回空列表
        """
        if not query or not query.strip():
            return []
        # 规范化 + 校验 IP，并对 LIKE 元字符转义（双保险，review #1）：
        # 客户端传 ip="%" 或 "_" 时不会构造出 'memory:%:%' 匹配全部记忆
        safe_ip = _escape_like(_normalize_ip(ip))
        try:
            docs = await hybrid_retriever.retrieve(
                query, top_k=top_k, source_pattern=f"{MEMORY_SOURCE_PREFIX}{safe_ip}:%",
            )
        except Exception as e:
            logger.warning("记忆检索失败，返回空记忆: %s", e)
            return []
        return await self._expand_to_parents(docs)

    async def _next_title(self, day: date, ip: str) -> str:
        """生成标题 '记忆-<日期>-<序号>'（序号=本 IP 当日已存记忆父块数+1）

        只统计父块（parent_id IS NULL），并按「本 IP + 当日」过滤：
        - source LIKE 'memory:<ip>:%'（IP 规范化 + 转义，review #1）
        - created_at 落在当日（避免序号跨日期累计，review #4）
        不依赖标题格式：记忆内容含 markdown 标题时父块标题为标题文本
        （非 '记忆-<日期>-NN'），若按标题统计会漏计导致序号重复/跳号。

        Args:
            day: 日期（datetime.date 对象，SQLAlchemy 绑定为 DATE；不可传
                ISO 字符串，否则 asyncpg 绑定为 VARCHAR，PG 无 date=varchar
                运算符导致真实查询崩溃 — tester 阻塞 #1）
            ip: 已规范化的用户 IP（空/非法已由调用方降级为 'unknown'）
        """
        prefix = f"记忆-{day}-"
        safe_ip = _escape_like(ip)
        pattern = f"{MEMORY_SOURCE_PREFIX}{safe_ip}:%"
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

        Args:
            child_docs: 检索命中的子块列表

        Returns:
            [{"content": str, "score": float, "title": str}, ...] 按 score 降序
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
                best[content] = {
                    "content": content,
                    "score": round(score, 4),
                    "title": p.title if p else d.get("title", ""),
                }
        return sorted(best.values(), key=lambda m: m["score"], reverse=True)


# 全局单例 — 整个应用共享一个 MemoryService 实例（无状态）
memory_service = MemoryService()
