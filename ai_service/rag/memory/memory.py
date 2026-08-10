"""
长期记忆服务 — 跨会话记忆沉淀（module-023 / module-032 身份化 / module-034 分层 / module-035 分数口径）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

系统无长期记忆（只有 Redis 短期缓存 + 内存 IP 会话，重启丢失）。
本模块提供跨会话记忆：复用 documents 表（source='memory:<identity>:' 区分），
无新表，复用分块（chunker）/向量化（本地 bge-m3）/检索（hybrid_retriever）全链路。

- save(content, identity): 长期记忆，分块 → 向量化 → 写 documents（父块无向量 + 子块含向量）
- save_short(content, identity): 短期记忆（source='memory:<identity>:short:'，去重命中刷新提及）
- recall(query, identity): 长期记忆检索（source 精确匹配，动态 K）
- recall_short(query, identity): 短期记忆检索（动态 K + module-046 进化：衰减/加权/升级）

module-035 分数口径（相对分 vs 绝对分）：
  - 动态 K / 低分过滤 / 去重统一用**绝对 embedding 余弦**（候选子块 embedding 存库已 L2
    归一化，点积=cosine；query 经 embed_text 归一化）——相对分（min-max hybrid_score）
    跨查询不可比，套绝对阈值语义失真（旧动态 K 恒 K=1 的根因，详见
    specs/module-035-score-calibration/score-issues.md）
  - query 嵌入失败 → 降级用原 hybrid_score（不回退失败）

module-034 三层 source 分层：
  - 长期 memory:<identity>:
  - 短期 memory:<identity>:short:
  - 会话 memory:<identity>:session:（见 session_memory.py）
  各层检索 source_pattern 精确匹配（_layer_pattern），互不混淆；既有长期数据
  source 恒为精确 'memory:<identity>:'，长期检索由旧 ':%' 通配改为精确匹配后
  行为一致（零回归），且不再误命中 short/session 层。

身份（module-032）：
- identity = user_id（JWT.sub）优先，否则 client_ip（匿名降级，零回归）
- 用户登录后记忆按 user_id 隔离（跨设备/跨会话）；匿名访客仍按 client_ip 隔离

隔离设计：
- 记忆检索 source_pattern 精确匹配（_layer_pattern，如 'memory:<identity>:' /
  'memory:<identity>:short:'），只查该身份同层记忆文档；
  source 以尾冒号分隔身份与内容（'memory:<identity>:'），避免前缀重叠
  （如 1.1.1.1 与 1.1.1.10）经 LIKE 交叉泄漏记忆
- identity 必须通过规范化校验（_normalize_identity，空/含 LIKE 元字符降级
  'unknown'），且 pattern 构造处对 LIKE 元字符转义（_escape_like），双保险
  杜绝通配符注入（如 identity="%" 构造 'memory:%:%' 匹配全部记忆）绕过隔离
- 普通知识库检索默认排除 'memory:%' 前缀（见 retriever._source_condition），
  保证记忆不污染知识库检索结果
"""
import asyncio
import hashlib
import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy import delete, func, select, update

from src.config import settings
from src.database import async_session_factory
from rag.models import Document
from rag.retrieval.chunker import chunker
from rag.retrieval.embeddings import embedding_service
from rag.retrieval.retriever import hybrid_retriever
from rag.retrieval.text_tokenizer import tokenize

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


def _memory_source(identity: str, layer: str = "") -> str:
    """构造记忆 source（module-034 三层 source 分层）

    - 长期: memory:<identity>:          （module-023/032/033，格式不变）
    - 短期: memory:<identity>:short:    （本次新增）
    - 会话: memory:<identity>:session:  （本次新增，见 session_memory.py）

    source 以尾冒号分隔身份与内容（'memory:<identity>:'），避免前缀重叠
    身份（如 1.1.1.1 与 1.1.1.10）经 LIKE 交叉泄漏记忆。

    Args:
        identity: 已规范化的身份标识（user_id 优先，否则 client_ip）
        layer: 层标识（""=长期 / "short"=短期 / "session"=会话）

    Returns:
        对应 source 字符串（尾冒号收尾）
    """
    return f"{MEMORY_SOURCE_PREFIX}{identity}:" + (f"{layer}:" if layer else "")


def _layer_pattern(safe_identity: str, layer: str = "") -> str:
    """构造某层记忆的精确 source 匹配模式（无通配符，LIKE 等值匹配）

    三层 source 均以 '<身份>:' 为前缀，若长期层沿用旧 'memory:<id>:%' 通配
    模式会把 short/session 层记忆一并命中（跨层污染）。改为精确匹配后：
      - 长期 'memory:<id>:'       只命中长期父块/子块
      - 短期 'memory:<id>:short:' 只命中短期
    既有长期数据 source 恒为精确 'memory:<id>:'，精确匹配行为与旧 ':%' 一致
    （零回归），只是不再误命中新增的 short/session 层。

    Args:
        safe_identity: 已规范化 + 转义的身份标识
        layer: 层标识（""=长期 / "short"=短期 / "session"=会话）

    Returns:
        形如 'memory:<id>:short:' 的精确匹配模式
    """
    return f"{MEMORY_SOURCE_PREFIX}{safe_identity}:" + (f"{layer}:" if layer else "")


def format_memory_line(memory: dict, label: str = "长期记忆") -> str:
    """格式化单条召回记忆为 '[<label> - YYYY-MM-DD]：内容'（module-033/034）

    带日期前缀帮助生成模型区分记忆与当前对话；无 created_at（或解析失败）
    时省略日期，仅保留 '[<label>]：内容'。格式化逻辑放本模块，由
    engine._recall_memory 拼接注入 prompt。

    module-034：label 参数区分长/短期注入段（长期 '[长期记忆...]' 注入"历史
    记忆"段；短期 '[短期记忆...]' 注入"最近上下文"段）。默认 '长期记忆'
    保持既有调用（module-033）行为不变。

    Args:
        memory: 召回记忆 dict，含 content；created_at 可选（'YYYY-MM-DD' 或 None）
        label: 记忆类型标签（默认 '长期记忆'；短期调用传 '短期记忆'）

    Returns:
        形如 "[长期记忆 - 2026-08-05]：用户偏好简洁回答" 的格式化字符串
    """
    content = memory.get("content") or ""
    created_at = memory.get("created_at")
    prefix = f"[{label} - {created_at}]" if created_at else f"[{label}]"
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
    """长期/短期记忆服务（跨会话记忆沉淀）

    职责：
    - save: 保存一条长期记忆到 documents（source='memory:<identity>:'，module-023/033）
    - save_short: 保存一条短期记忆（source='memory:<identity>:short:'，module-034/046）
    - recall: 检索与身份相关的长期记忆（source 精确过滤，按身份隔离）
    - recall_short: 检索与身份相关的短期记忆（动态 K + 进化：衰减/加权/升级，module-034/046）

    module-034 三层 source 分层（长期/短期/会话）：
      - 长期 memory:<identity>:
      - 短期 memory:<identity>:short:
      - 会话 memory:<identity>:session:（见 session_memory.py）
    各层 source_pattern 精确匹配（_layer_pattern），互不混淆；既有长期数据
    source 恒为精确 'memory:<identity>:'，长期检索由 ':%' 改精确匹配后行为
    一致（零回归），只是不再误命中 short/session 层。
    """

    async def save(self, content: str, identity: str = DEFAULT_IDENTITY,
                   dedup: bool = True) -> dict:
        """保存一条长期记忆（签名兼容 module-023/033）

        委托 _save（layer=''）执行分块/去重/入库；语义去重仅在长期层内查重。

        Args:
            content: 记忆内容（不能为空）
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            dedup: 写入前是否语义去重（默认 True）

        Returns:
            {"id": int, "title": str, "status": "saved"} 或 {"status": "updated"}

        Raises:
            ValueError: content 为空
            RuntimeError: 向量化或入库失败
        """
        return await self._save(content, identity, layer="", dedup=dedup)

    async def save_short(self, content: str, identity: str = DEFAULT_IDENTITY,
                         dedup: bool = True) -> dict:
        """保存一条短期记忆（source='memory:<identity>:short:'，module-034）

        复用 _save 的分块/嵌入/入库全链路；语义去重仅在短期层内
        （_find_duplicate layer='short'），与长期记忆互不混淆。短期记忆带
        created_at；去重命中（status="updated"）时刷新 last_mentioned_at +
        mention_count+1（module-046 写入侧提及强化）。过期处理由 recall_short
        的进化逻辑负责（硬上限 + 平滑衰减，替代旧 7 天一刀切 TTL）。

        Args:
            content: 短期记忆内容（不能为空）
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            dedup: 写入前是否语义去重（默认 True）

        Returns:
            {"id": int, "title": str, "status": "saved"} 或 {"status": "updated"}

        Raises:
            ValueError: content 为空
            RuntimeError: 向量化或入库失败
        """
        return await self._save(content, identity, layer="short", dedup=dedup)

    async def _save(self, content: str, identity: str, layer: str,
                    dedup: bool = True) -> dict:
        """保存一条记忆（长期/短期共用，module-034 重构）

        流程（dedup=True 默认，module-033）：
          1. 语义去重：与本身份同层现有记忆嵌入 cosine 相似度最高值 > 阈值
             （settings.memory_dedup_threshold=0.85，module-035 校准）→ 视为重复 → 更新既有
             父块（追加内容）并返回 status="updated"（不新增行，库内条数不涨）
          2. 未命中重复 → 分块（复用 chunker）→ 写父块 → 子块向量化 + 写子块
             （细节拆分到 _insert_parents / _insert_children）；embedding 失败时
             整体 rollback，不会留下无向量的"残缺"记忆记录
        去重检索/嵌入失败 → 降级为正常新增（不阻塞，与"去重失败降级"约定一致）。

        Args:
            content: 记忆内容（不能为空）
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            layer: 层标识（""=长期 / "short"=短期）
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
        # source 带尾冒号分隔符：'memory:<identity>:' / 'memory:<identity>:short:'，
        # 配合 recall / recall_short 的精确 source_pattern 匹配，避免前缀重叠身份
        #（如 192.168.1.1 与 192.168.1.10）交叉泄漏记忆
        source = _memory_source(identity, layer)

        # module-033 语义去重：写入前查同层现有记忆（_find_duplicate layer 隔离），
        # 命中重复则更新旧记忆而非新增。任何去重异常降级为正常新增（不阻塞，零回归）
        if dedup:
            try:
                duplicate = await self._find_duplicate(content, identity, layer=layer)
                if duplicate is not None:
                    merged = await self._merge_duplicate(duplicate, content, layer=layer)
                    if merged is not None:
                        return merged
            except Exception as e:
                logger.warning("记忆去重失败，按新增处理: %s", e)

        # 当日参数传 date 对象而非 ISO 字符串：字符串经 asyncpg 绑定为 VARCHAR，
        # PG 无 date=varchar 运算符 → 真实 save 崩溃（tester 阻塞 #1 回归）
        title = await self._next_title(date.today(), identity, layer=layer)

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

    async def _find_duplicate(self, content: str, identity: str, layer: str = ""):
        """语义去重：与本身份同层现有记忆嵌入 cosine 最高相似度 > 阈值 → 返回重复记忆

        流程：
          1. 新事实向量化（失败 → None，视为无重复，不阻塞）
          2. 查本身份同层现有记忆子块（source 精确匹配 _layer_pattern 且带向量）
          3. 嵌入已 L2 归一化，cosine 相似度 = 点积；逐条计算取最高
          4. 最高相似度 > settings.memory_dedup_threshold → 返回该子块

        module-034：layer 限定去重范围（""=长期 / "short"=短期），同层内查重，
        长/短记忆互不混淆；session 层无向量不参与去重。任何异常降级返回 None
        （视为无重复 → 正常新增）。

        Args:
            content: 新记忆内容
            identity: 已规范化的身份标识（user_id 优先，否则 client_ip）
            layer: 层标识（""=长期 / "short"=短期）

        Returns:
            命中重复时返回最佳匹配子块 Document（含 parent_id）；否则 None
        """
        try:
            new_emb = await embedding_service.embed_text(content)
        except Exception as e:
            logger.warning("去重向量化失败，视为无重复: %s", e)
            return None
        safe_identity = _escape_like(identity)
        pattern = _layer_pattern(safe_identity, layer)
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

    async def _merge_duplicate(self, duplicate, content: str, layer: str = "") -> dict | None:
        """语义重复记忆：更新既有父块（追加内容）而非新增，返回 status='updated'

        不新增任何行（库内条数不涨）；把新内容追加到既有父块 content，
        父块 id/title 保持不变，召回仍按既有子块向量命中映射回父块。
        父块缺失/更新失败 → 返回 None（由调用方 save 兜底为正常新增）。

        module-046：短期层（layer='short'）去重命中 = 再次提及 → 写入侧提及
        刷新（mention_count+1 + last_mentioned_at=now）；长期层（layer=''）
        行为不变（进化只作用于短期层）。存量行 mention_count 为 NULL 时
        视为 0 再 +1（零迁移 fail-open）。

        Args:
            duplicate: _find_duplicate 命中的子块 Document（含 parent_id）
            content: 新记忆内容
            layer: 层标识（""=长期 / "short"=短期）

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
                if layer == "short":
                    parent.mention_count = (parent.mention_count or 0) + 1
                    parent.last_mentioned_at = datetime.now(timezone.utc)
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
        """检索与 query 相关的长期记忆（按身份隔离；动态 K 召回，module-033/035）

        复用 hybrid_retriever（source_pattern 精确匹配 'memory:<identity>:'，
        module-034 后不再用 ':%' 通配，避免命中 short/session 层），
        检索命中的子块再映射回父块，返回完整记忆内容（同父块去重取最高分）。

        module-035 动态 K（绝对余弦口径）：query 嵌入 + 候选子块 embedding
        （存库已 L2 归一化，点积=cosine）算每条绝对余弦；绝对余弦 <
        memory_recall_min_score（默认 0.4）的候选丢弃（防"本批相对高但绝对烂"
        注入）；按平均绝对余弦动态调整召回条数（>0.85→5 / 0.75-0.85→3 /
        <0.75→1，宁缺毋滥）。query 嵌入失败 → 降级用原 hybrid_score（不回退
        失败）。每条结果新增 created_at（'YYYY-MM-DD' 或 None），供
        '[长期记忆 - 日期]：内容' 格式化注入。

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
        # module-034：长期层 source 精确匹配（_layer_pattern），不再用 ':%' 通配，
        # 避免命中新增的 short/session 层（既有长期数据 source 恒为精确值，零回归）
        try:
            docs = await hybrid_retriever.retrieve(
                query, top_k=top_k, source_pattern=_layer_pattern(safe_identity),
            )
        except Exception as e:
            logger.warning("记忆检索失败，返回空记忆: %s", e)
            return []
        if not docs:
            return []
        # module-035 动态 K：绝对余弦口径（低分过滤 + 按绝对余弦降序 + 均值判定）
        avg_score = await self._absolute_cosine_avg(query, docs)
        dynamic_k = self._dynamic_k(avg_score)
        memories = await self._expand_to_parents(docs)
        return memories[:dynamic_k]

    async def recall_short(
        self, query: str, identity: str = DEFAULT_IDENTITY, top_k: int = 5,
    ) -> list[dict]:
        """检索与 query 相关的短期记忆（module-034：按身份隔离；动态 K + module-046 进化）

        复用 hybrid_retriever（source_pattern 精确匹配 'memory:<identity>:short:'，
        只查短期层，与长期/会话互不混淆），命中子块映射回父块（_expand_to_parents）。

        动态 K：与长期 recall 一致（module-035 绝对余弦口径——候选平均绝对余弦
        >0.85→5 / 0.75-0.85→3 / <0.75→1，宁缺毋滥；低分过滤 + 嵌入失败降级同 recall）。
        module-046 进化（替代 module-034 的 7 天一刀切 TTL，见 _evolve_recall）：
          ① 硬上限：参考时间（last_mentioned_at or created_at）超 memory_short_max_days
             （默认 30 天）→ 不参与召回
          ② 平滑衰减 + 提及加权：最终分 = 语义分 × 0.5**(age/half_life) × (1 + α×mention_count)
          ③ 召回命中刷新提及（fire-and-forget）
          ④ 短期→长期升级（mention_count ≥ 阈值 且 最近提及在窗口内；幂等）
        兼容性：存量短期记忆无 last_mentioned_at/mention_count（NULL/0）→ 按
        created_at 衰减、count=0 加权（零迁移 fail-open）；两者皆无 → 保留原样。

        Args:
            query: 检索查询
            identity: 身份标识（user_id 优先，否则 client_ip；空/空白则默认 'unknown'）
            top_k: 动态 K 的最大候选数（默认 5，同时是动态 K 的条数上限）

        Returns:
            [{"content": str, "score": float, "title": str, "created_at": str|None}, ...]
            按 score 降序；query 为空、无候选或检索失败时返回空列表
        """
        if not query or not query.strip():
            return []
        safe_identity = _escape_like(_normalize_identity(identity))
        try:
            docs = await hybrid_retriever.retrieve(
                query, top_k=top_k, source_pattern=_layer_pattern(safe_identity, "short"),
            )
        except Exception as e:
            logger.warning("短期记忆检索失败，返回空记忆: %s", e)
            return []
        if not docs:
            return []
        # module-035 动态 K：绝对余弦口径（低分过滤 + 按绝对余弦降序 + 均值判定）
        avg_score = await self._absolute_cosine_avg(query, docs)
        dynamic_k = self._dynamic_k(avg_score)
        memories = await self._expand_to_parents(docs)
        if not memories:
            return []
        # module-046：短期记忆进化（硬上限/衰减/加权/提及刷新/升级）
        memories = await self._evolve_recall(memories, docs, identity)
        return memories[:dynamic_k]

    async def _evolve_recall(
        self, memories: list[dict], child_docs: list[dict], identity: str,
    ) -> list[dict]:
        """module-046 短期记忆进化：硬上限 + 平滑衰减 + 提及加权 + 升级（替代一刀切 TTL）

        流程（plan 3.2 召回侧）：
          ① 硬上限：参考时间（last_mentioned_at or created_at）超
             settings.memory_short_max_days（默认 30 天）→ 不参与召回
          ② 平滑衰减 + 提及加权：age_days = now - 参考时间；
             decay = 0.5**(age_days/half_life)（半衰期默认 3 天）；
             最终分 = 语义分 × decay × (1 + α×mention_count)（α 默认 0.2）
          ③ 提及刷新：召回命中 = 再次提及 → fire-and-forget 更新
             last_mentioned_at=now + mention_count+1（不阻塞召回；**仅刷新通过
             硬上限过滤的项**——超硬上限不参与召回也不刷新，避免"检索一次即复活"）
          ④ 升级检测：mention_count ≥ settings.memory_promote_mentions 且最近提及在
             settings.memory_promote_window_days 内 → _promote_memory（幂等）
          ⑤ 重排：最终分与原始语义分排序可能不一致 → 按新 score 降序重排
             （plan 场景 1 加权排前 / 场景 2 衰减排后；stable 排序，同分保持
             语义分先后），由调用方按此顺序截断 dynamic_k

        兼容性（零迁移 fail-open）：无 last_mentioned_at/mention_count 的存量行
        （NULL）→ 按 created_at 衰减、count=0 加权；参考时间缺失 → 保留原样；
        参考文档加载失败/异常 → 返回原 memories（plan 3.3：异常走原逻辑不抛）。

        Args:
            memories: _expand_to_parents 输出的父块记忆列表（原地改 score）
            child_docs: 检索命中的短期子块列表（含 id / parent_id）
            identity: 已规范化的身份标识（供升级写入长期 source）

        Returns:
            过滤 + 加权后的记忆列表（按新 score 降序重排，调用方按此截断 dynamic_k）
        """
        try:
            ref_ids = {d.get("parent_id") for d in child_docs if d.get("parent_id")}
            ref_ids |= {d.get("id") for d in child_docs
                        if not d.get("parent_id") and d.get("id")}
            if not ref_ids:
                return memories
            async with async_session_factory() as session:
                rows = await session.execute(
                    select(Document).where(Document.id.in_(ref_ids))
                )
                refs = {d.id: d for d in rows.scalars().all()}
        except Exception as e:
            logger.warning("短期记忆进化失败，走原逻辑: %s", e)
            return memories

        by_content: dict[str, Document] = {}
        for d in refs.values():
            if d.content and d.content not in by_content:
                by_content[d.content] = d

        now = datetime.now(timezone.utc)
        result: list[dict] = []
        to_promote: list[Document] = []
        refreshed_ids: list[int] = []  # 仅收集通过硬上限过滤（参与召回）的参考文档
        for m in memories:
            doc = by_content.get(m.get("content"))
            if doc is None:
                result.append(m)  # 参考文档缺失 → 保留原样（fail-open）
                continue
            # ① 硬上限 + ② 衰减：参考时间 = last_mentioned_at or created_at
            ref = doc.last_mentioned_at or doc.created_at
            age_days = 0.0
            if ref is not None:
                if ref.tzinfo is None:
                    ref = ref.replace(tzinfo=timezone.utc)  # 存量 naive 按 UTC 解释
                age_days = (now - ref).total_seconds() / 86400.0
                if age_days > settings.memory_short_max_days:
                    continue  # 超硬上限：不参与召回（也不刷新提及，避免"检索一次即复活"）
            count = doc.mention_count or 0
            half_life = settings.memory_short_half_life or 3.0
            if half_life <= 0:
                half_life = 3.0  # 配置防御：半衰期非正数回退默认
            decay = 0.5 ** (age_days / half_life)
            m["score"] = round(
                m["score"] * decay * (1 + settings.memory_mention_boost_alpha * count), 4,
            )
            result.append(m)
            refreshed_ids.append(doc.id)  # 通过硬上限 → 参与召回 → 提及刷新
            # ④ 升级检测：count ≥ 阈值 且 最近提及在窗口内
            if count >= settings.memory_promote_mentions:
                last_ref = doc.last_mentioned_at or doc.created_at
                if last_ref is not None:
                    if last_ref.tzinfo is None:
                        last_ref = last_ref.replace(tzinfo=timezone.utc)
                    if (now - last_ref).total_seconds() <= settings.memory_promote_window_days * 86400.0:
                        to_promote.append(doc)

        # ③ 提及刷新（fire-and-forget，不阻塞召回；只刷新通过硬上限过滤的项，
        #    超硬上限的记忆不"复活"；刷新任务内部降级）
        if refreshed_ids:
            asyncio.create_task(self._refresh_mentions(refreshed_ids))
        # ④ 升级执行（幂等；异常已在 _promote_memory 内降级）
        for doc in to_promote:
            await self._promote_memory(identity, doc)
        # ⑤ 重排：衰减+加权后的最终分与原始语义分排序可能不一致，按新 score
        #    降序（stable：同分保持语义分先后）——新分数驱动召回排序与截取
        result.sort(key=lambda m: m["score"], reverse=True)
        return result

    async def _refresh_mentions(self, doc_ids: list[int]) -> None:
        """召回命中刷新提及（fire-and-forget）：last_mentioned_at=now + mention_count+1

        只更新参考文档（短期父块或旧格式单文档）本身；存量行 mention_count 为
        NULL 时视为 0 再 +1（coalesce，零迁移 fail-open）。失败仅日志降级，
        不影响召回结果。

        Args:
            doc_ids: 召回命中的参考文档 id 列表
        """
        if not doc_ids:
            return
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(Document)
                    .where(Document.id.in_(doc_ids))
                    .values(
                        last_mentioned_at=datetime.now(timezone.utc),
                        mention_count=func.coalesce(Document.mention_count, 0) + 1,
                    )
                )
                await session.commit()
        except Exception as e:
            logger.warning("短期记忆提及刷新失败（降级）: %s", e)

    async def _promote_memory(self, identity: str, doc: Document) -> None:
        """短期→长期升级：复制到长期层 + 删除短期副本（幂等，plan 3.3 异常降级）

        复制：父块（无向量）+ 子块（含向量）→ source 改为长期 'memory:<identity>:'
        （长期/短期隔离由 source 前缀 + _layer_pattern 精确匹配保证）。
        幂等：长期层已存在同 content_hash 的父块（历史升级/长期层已写入同内容）
        → 不重复复制，仅清理残留短期副本。content_hash 缺失（存量脏行）时跳过
        幂等检查（极端边角，容忍重复）。
        旧格式单文档（parent_id=None 且无子块，自身即完整记忆）→ 整体复制
        （保留向量，parent_id=None）。
        复制在删除之前执行：复制失败 → 短期副本保留（不丢数据）。

        Args:
            identity: 已规范化的身份标识
            doc: 待升级的短期参考文档（父块或旧格式单文档）
        """
        if doc.parent_id is not None:
            logger.warning("升级跳过：参考文档为子块（id=%d），仅父块参与升级", doc.id)
            return
        try:
            async with async_session_factory() as session:
                # 子块（父块模式下复制子块；旧格式单文档无子块）
                rows = await session.execute(
                    select(Document).where(Document.parent_id == doc.id)
                )
                children = rows.scalars().all()
                # 幂等检查：长期层是否已有同 content_hash 的父块
                hashes = [h for h in [doc.content_hash] + [c.content_hash for c in children] if h]
                dup = None
                if hashes:
                    dup = (await session.execute(
                        select(Document.id).where(
                            Document.source.like(_layer_pattern(_escape_like(identity))),
                            Document.parent_id.is_(None),
                            Document.content_hash.in_(hashes),
                        ).limit(1)
                    )).scalar()
                if dup is None:
                    # 复制到长期层（先复制后删除：复制失败不丢短期数据）
                    long_source = _memory_source(identity)
                    if children:
                        new_parent = Document(
                            title=doc.title, content=doc.content, source=long_source,
                            embedding=None, parent_id=None, content_hash=doc.content_hash,
                        )
                        session.add(new_parent)
                        await session.flush()
                        for c in children:
                            session.add(Document(
                                title=c.title, content=c.content, source=long_source,
                                embedding=c.embedding, parent_id=new_parent.id,
                                content_hash=c.content_hash, search_tokens=c.search_tokens,
                            ))
                    else:
                        # 旧格式单文档：整体复制（保留向量）
                        session.add(Document(
                            title=doc.title, content=doc.content, source=long_source,
                            embedding=doc.embedding, parent_id=None,
                            content_hash=doc.content_hash, search_tokens=doc.search_tokens,
                        ))
                    logger.info("短期记忆升级长期: identity=%s, source=%s, content=%.20s",
                                identity, long_source, doc.content[:20])
                else:
                    logger.info("短期记忆升级跳过（长期层已存在）: identity=%s, dup_id=%d",
                                identity, dup)
                # 删除短期副本（父块 + 子块；已升级时同样清理残留副本）
                del_ids = [doc.id] + [c.id for c in children]
                if del_ids:
                    await session.execute(delete(Document).where(Document.id.in_(del_ids)))
                await session.commit()
        except Exception as e:
            logger.warning("短期→长期升级失败（降级，不影响召回）: %s", e)

    @staticmethod
    def _dynamic_k(avg_score: float) -> int:
        """按候选平均相似度动态调整召回 K（module-033 阈值 / module-035 绝对余弦口径）

        Args:
            avg_score: 检索候选的平均相似度（module-035 起为绝对余弦均值，0-1）

        Returns:
            召回条数：>0.85 → 5；0.75-0.85 → 3；<0.75 → 1
        """
        if avg_score > settings.memory_recall_high_threshold:
            return settings.memory_max_recall
        if avg_score >= settings.memory_recall_mid_threshold:
            return 3
        return 1

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """向量余弦相似度（module-035 绝对余弦口径）

        候选子块 embedding 存库时已 L2 归一化（module-033），query embedding 由
        embedding_service.embed_text 归一化，故点积即余弦。维度不一致（历史脏
        数据）或任一为空时返回 0.0（视为不相似，宁缺毋滥）。

        Args:
            a: 向量 A（query embedding）
            b: 向量 B（候选 embedding）

        Returns:
            [0, 1] 余弦相似度
        """
        if not a or not b or len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))

    async def _child_embeddings(self, child_docs: list[dict]) -> dict[int, list[float]]:
        """批量读取候选子块的存储 embedding（module-035 绝对余弦用）

        子块 embedding 存库时已 L2 归一化（module-033），读取后可直接
        dot(query_emb, doc_emb) 作为绝对余弦。按候选子块 id 做 IN 查询
        （只查这批候选，避免全表扫描）。

        Args:
            child_docs: 检索命中的子块候选列表（含 id）

        Returns:
            {子块 id: embedding 向量}；读取失败返回空 dict（由调用方降级）
        """
        ids = {d.get("id") for d in child_docs if d.get("id")}
        if not ids:
            return {}
        try:
            async with async_session_factory() as session:
                rows = await session.execute(
                    select(Document.id, Document.embedding).where(Document.id.in_(ids))
                )
                return {row.id: row.embedding for row in rows.all()}
        except Exception as e:
            logger.warning("候选子块 embedding 读取失败，降级 hybrid_score: %s", e)
            return {}

    async def _absolute_cosine_avg(self, query: str, docs: list[dict]) -> float:
        """module-035 动态 K 绝对余弦口径（低分过滤 + 绝对余弦排序 + 均值）

        对每条候选计算绝对余弦 = dot(query_emb, doc_emb)（候选子块 embedding
        存库已 L2 归一化，点积=cosine），绝对余弦 < memory_recall_min_score 的
        候选丢弃（防"本批相对高但绝对烂"的记忆注入），剩余候选按绝对余弦降序
        排序，返回平均绝对余弦供 _dynamic_k 判定档位。

        query 嵌入失败或候选 embedding 读取失败 → 降级返回原 hybrid_score 均值
        （相对分，跨查询不可比但保留既有排序行为；不回退失败）。

        Args:
            query: 检索查询
            docs: 检索命中的子块候选列表（原地修改：注入 abs_cosine / 低分过滤 / 排序）

        Returns:
            平均相似度（绝对余弦均值；降级时为 hybrid_score 均值）
        """
        query_emb = None
        try:
            query_emb = await embedding_service.embed_text(query)
        except Exception as e:
            logger.warning("记忆绝对余弦失败（query 嵌入），降级 hybrid_score: %s", e)
        emb_by_id: dict[int, list[float]] = {}
        if query_emb is not None:
            emb_by_id = await self._child_embeddings(docs)
        if query_emb is not None and emb_by_id:
            for d in docs:
                emb = emb_by_id.get(d.get("id"))
                if emb:
                    d["abs_cosine"] = self._cosine(query_emb, emb)
            # 低分过滤：绝对余弦 < memory_recall_min_score 的候选丢弃
            docs[:] = [
                d for d in docs
                if d.get("abs_cosine", 0.0) >= settings.memory_recall_min_score
            ]
            if not docs:
                return 0.0
            docs.sort(key=lambda d: d.get("abs_cosine", 0.0), reverse=True)
            return sum(d.get("abs_cosine", 0.0) for d in docs) / len(docs)
        return sum(
            d.get("hybrid_score", d.get("score", 0.0)) for d in docs
        ) / len(docs)

    async def _next_title(self, day: date, identity: str, layer: str = "") -> str:
        """生成标题 '记忆-<日期>-<序号>'（序号=本身份同层当日已存记忆父块数+1）

        只统计父块（parent_id IS NULL），并按「本身份同层 + 当日」过滤：
        - source 精确匹配 _layer_pattern(identity, layer)（module-034：长期/短期
          各自独立计数，互不混用）
        - created_at 落在当日（避免序号跨日期累计，review #4）
        不依赖标题格式：记忆内容含 markdown 标题时父块标题为标题文本
        （非 '记忆-<日期>-NN'），若按标题统计会漏计导致序号重复/跳号。

        Args:
            day: 日期（datetime.date 对象，SQLAlchemy 绑定为 DATE；不可传
                ISO 字符串，否则 asyncpg 绑定为 VARCHAR，PG 无 date=varchar
                运算符导致真实查询崩溃 — tester 阻塞 #1）
            identity: 已规范化的身份标识（空/非法已由调用方降级为 'unknown'）
            layer: 层标识（""=长期 / "short"=短期）
        """
        prefix = f"记忆-{day}-"
        safe_identity = _escape_like(identity)
        pattern = _layer_pattern(safe_identity, layer)
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
            # module-035：优先用绝对余弦（abs_cosine）；嵌入失败降级路径仍用 hybrid_score
            score = d.get("abs_cosine", d.get("hybrid_score", d.get("score", 0.0)))
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
