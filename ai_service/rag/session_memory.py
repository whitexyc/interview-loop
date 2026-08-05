"""
会话记忆服务 — 会话历史持久化（module-034）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

复用 documents 表（source='memory:<identity>:session:'，无新表），
把对话历史按轮次持久化，供刷新/换设备恢复；不参与向量检索（无 embedding，
仅按 source 等值查询 + id 排序恢复）。与内存态 IP_SESSION_MESSAGES 的关系：
持久化为主（生成时优先恢复持久化会话），内存态降级为兜底缓存（/ai/chat/sessions
端点等即时读取）。

- save_session_messages(identity, messages): 写入会话消息（每消息一条，按 identity
  隔离；content_hash 去重幂等；超上限滚动删除最旧）
- get_session_messages(identity, limit): 恢复最近会话（id 升序，最近 limit 条）

身份（module-032）：identity = user_id 优先，否则 client_ip（匿名降级，零回归）。
source 尾冒号分隔身份与内容（'memory:<identity>:session:'），配合身份规范化
（_normalize_identity）杜绝通配符注入绕过按身份隔离。
"""
import hashlib
import logging

from sqlalchemy import delete, func, select

from src.config import settings
from src.database import async_session_factory
from rag.models import Document
from rag.memory import MEMORY_SOURCE_PREFIX, _normalize_identity

logger = logging.getLogger(__name__)

# 会话层标识：source = 'memory:<identity>:session:'
SESSION_LAYER = "session"


def _session_source(identity: str) -> str:
    """构造会话记忆 source：'memory:<identity>:session:'

    Args:
        identity: 已规范化的身份标识（user_id 优先，否则 client_ip）

    Returns:
        会话记忆 source 字符串
    """
    return f"{MEMORY_SOURCE_PREFIX}{identity}:{SESSION_LAYER}:"


class SessionMemoryService:
    """会话记忆服务（module-034，会话历史持久化）

    职责：
    - save_session_messages: 写入会话消息（按身份隔离 + content_hash 幂等 + 超限滚动）
    - get_session_messages: 恢复最近会话（供生成 history，刷新/换设备不丢）
    """

    async def save_session_messages(
        self, identity: str, messages: list[dict],
    ) -> int:
        """保存会话消息到持久化（source='memory:<identity>:session:'）

        每消息写一条 Document（无 embedding，仅有序恢复）；按身份隔离。
        content_hash 去重：完全重复内容幂等跳过（重复保存不堆积）。写入后按
        settings.memory_session_max_messages（默认 50）控制上限，超限滚动删除
        最旧消息。任何单步失败降级日志，不影响对话响应。

        Args:
            identity: 身份标识（user_id 优先，否则 client_ip）
            messages: 会话消息列表 [{"role": "user"|"assistant", "content": str}, ...]

        Returns:
            新写入的消息条数
        """
        if not messages:
            return 0
        identity = _normalize_identity(identity)
        source = _session_source(identity)
        new_count = 0
        async with async_session_factory() as session:
            # 查现有 content_hash，完全重复跳过（幂等，防重复保存堆积）
            existing_hashes = set()
            try:
                rows = await session.execute(
                    select(Document.content_hash).where(Document.source == source)
                )
                existing_hashes = {r[0] for r in rows.all() if r[0]}
            except Exception as e:
                logger.warning("会话去重检索失败，忽略幂等: %s", e)
            for msg in messages:
                role = str(msg.get("role") or "").strip()
                content = str(msg.get("content") or "").strip()
                if not content:
                    continue
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if digest in existing_hashes:
                    continue
                session.add(Document(
                    title=f"session:{role}" if role else "session",
                    content=content,
                    source=source,
                    embedding=None,
                    parent_id=None,
                    content_hash=digest,
                ))
                existing_hashes.add(digest)
                new_count += 1
            if new_count:
                try:
                    await session.commit()
                except Exception as e:
                    logger.error("会话持久化提交失败: %s", e)
                    raise
            # 上限控制（超限滚动删除最旧）；失败降级不影响已保存
            try:
                await self._trim(session, source)
            except Exception as e:
                logger.warning("会话上限清理失败（降级）: %s", e)
        logger.info("会话持久化: identity=%s, new=%d", identity, new_count)
        return new_count

    async def _trim(self, session, source: str) -> None:
        """会话上限控制：超出 settings.memory_session_max_messages 删除最旧消息

        按 id 升序取超限条数删除（id 单调递增即时间序），保持每 identity
        会话条数有界，防止 documents 表无限增长。

        Args:
            session: 数据库会话（事务由调用方 save_session_messages 持有）
            source: 会话记忆 source（'memory:<identity>:session:'）
        """
        max_msgs = max(settings.memory_session_max_messages, 1)
        count = (
            await session.execute(
                select(func.count()).select_from(Document)
                .where(Document.source == source)
            )
        ).scalar() or 0
        excess = count - max_msgs
        if excess <= 0:
            return
        rows = await session.execute(
            select(Document.id)
            .where(Document.source == source)
            .order_by(Document.id.asc())
            .limit(excess)
        )
        ids = [r[0] for r in rows.all()]
        if ids:
            await session.execute(delete(Document).where(Document.id.in_(ids)))
            await session.commit()
            logger.info("会话上限清理: source=%s, deleted=%d", source, len(ids))

    async def get_session_messages(
        self, identity: str, limit: int | None = None,
    ) -> list[dict]:
        """恢复最近会话消息（module-034，按身份隔离）

        查询 source='memory:<identity>:session:' 的全部消息，按 id 升序
        （时间序）取最近 limit 条。无记录返回空列表（调用方降级用当前请求
        history，零回归）。

        Args:
            identity: 身份标识（user_id 优先，否则 client_ip）
            limit: 返回条数（默认 settings.memory_session_history_limit）

        Returns:
            [{"role": "user"|"assistant", "content": str}, ...]（时间升序，最近 limit 条）
        """
        if limit is None:
            limit = settings.memory_session_history_limit
        identity = _normalize_identity(identity)
        source = _session_source(identity)
        try:
            async with async_session_factory() as session:
                rows = await session.execute(
                    select(Document)
                    .where(Document.source == source)
                    .order_by(Document.id.asc())
                )
                docs = rows.scalars().all()
        except Exception as e:
            logger.warning("会话恢复失败，返回空: %s", e)
            return []
        if not docs:
            return []
        recent = docs[-max(limit, 1):]
        out: list[dict] = []
        for doc in recent:
            content = (doc.content or "").strip()
            if not content:
                continue
            role = "user"
            if doc.title and doc.title.startswith("session:"):
                role = doc.title[len("session:"):].strip()
            if role not in ("user", "assistant"):
                role = "user"
            out.append({"role": role, "content": content})
        return out


# 全局单例 — 整个应用共享一个 SessionMemoryService 实例（无状态）
session_memory_service = SessionMemoryService()
