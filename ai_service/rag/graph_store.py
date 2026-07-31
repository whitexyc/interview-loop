"""
Apache AGE 知识图谱存储 — Graph RAG 图操作层

在整个 RAG 链路中的位置：
  文档入库 → [GraphExtractor] 提取实体/关系 → [GraphStore] 写入 AGE
  用户查询 → [GraphExtractor] 提取查询实体 → [GraphStore.search_related] 图遍历 → 文档

依赖：
  - PostgreSQL 已安装 Apache AGE 扩展（本地 PG 自带）
  - 图名 knowledge_graph
  - 节点 == Entity(name, type, doc_ids)
  - 边 == RELATED_TO（统一关系类型）

设计决策：
  1. 为什么用 MERGE 而非 CREATE？
     MERGE 是幂等的，重复执行不会重复创建节点/边。
     适合 add_document 多次调用和初始化场景。

  2. 为什么 doc_ids 存为 JSON 数组字符串？
     AGE 不支持直接的数组类型存储。JSON 字符串可被
     SQL 解析和追加，且与 Python list 互相转换方便。

  3. 为什么 search_related 用两步查询（Cypher → SQL）？
     AGE Cypher 可以找到相关实体和它们的 doc_ids，但
     返回完整文档内容需要 JOIN PostgreSQL 的 documents 表。
     两步查询是 AGE + PG 混合模型的标准做法。

  4. 为什么不用 bindparams？
     asyncpg 在 $$...$$ dollar-quoting 内的 `:param` 不会被识别为参数绑定，
     因此使用 Python f-string + 字符转义（Cypher 级别）注入参数值。
     $$...$$ 本身已经提供 PostgreSQL 级别的 SQL 注入防护——f-string 只影响 Cypher
     表达式内部的字符串字面量，不涉及外层 SQL AST。
"""
import asyncio
import json
import logging
from typing import Optional

from sqlalchemy import text, select

from src.database import async_session_factory
from rag.models import Document

logger = logging.getLogger(__name__)

GRAPH_NAME = "knowledge_graph"


def _escape(val: str) -> str:
    """转义 Cypher 字符串字面量中的特殊字符

    替换规则：
      ' → \\'  （单引号）
      } → \\}  （大括号，用于 Cypher 属性语法）
      \\  → \\\\\\  （反斜杠）
    """
    return val.replace("\\", "\\\\").replace("'", "\\'").replace("}", "\\}")


class GraphStore:
    """Apache AGE 知识图谱存储

    职责：
    1. ensure_graph() — 幂等创建图
    2. upsert_entity() — 创建/更新实体节点，追加 doc_ids
    3. upsert_relation() — 创建 RELATED_TO 边
    4. search_related() — 从实体出发图遍历，返回关联文档

    所有操作均 try/except 包裹，失败时静默降级（日志 warning）。
    """

    async def ensure_graph(self) -> bool:
        """确保 AGE 图和扩展已就绪（幂等）

        创建流程：
          1. CREATE EXTENSION age（首次）
          2. LOAD 'age'（每次会话）
          3. 检查图是否已存在 → 不存在才 create_graph

        注意：
          - 不再吞异常：create_graph 失败必须记录，避免"图没建出来但系统
            假装成功"的静默降级（之前导致 Graph RAG 长期无数据）。
          - 只忽略一种情况：图已存在（查询 ag_graph 表确认）。

        Returns:
            True 如果就绪，False 如果创建失败
        """
        try:
            async with async_session_factory() as session:
                await session.execute(text("CREATE EXTENSION IF NOT EXISTS age"))
                await session.execute(text("LOAD 'age'"))
                await session.execute(text(
                    "SET search_path = ag_catalog, \"$user\", public"
                ))

                # 检查图是否已存在（避免 create_graph 抛"已存在"异常）
                exists = await session.execute(text(
                    "SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name LIMIT 1"
                ), {"name": GRAPH_NAME})
                if exists.scalar_one_or_none() is None:
                    await session.execute(text(
                        f"SELECT create_graph('{_escape(GRAPH_NAME)}')"
                    ))
                    logger.info("AGE 图已创建: %s", GRAPH_NAME)
                else:
                    logger.info("AGE 图已存在: %s", GRAPH_NAME)

                await session.commit()
                return True
        except Exception as e:
            logger.warning("AGE 图初始化失败: %s", e)
            return False

    async def upsert_entity(self, name: str, entity_type: str, doc_id: int) -> bool:
        """创建或更新实体节点，追加关联文档 ID

        实现说明（重要）：
          Apache AGE 1.6.0 的 openCypher 方言不支持 MERGE 的
          ON CREATE SET / ON MATCH SET 子句（语法错误），所以拆成两步：
            1. 先 MATCH 检查节点是否存在
            2. 不存在 → CREATE（doc_ids 初始为数组 ['doc_id']）
               已存在 → WHERE NOT doc_id IN e.doc_ids + SET 数组追加
          doc_ids 存为 agtype 数组，与 search_related 的 json.loads 解析兼容。

        Args:
            name: 实体名称
            entity_type: 实体类型（如 "concept", "technology"）
            doc_id: 关联的文档 ID

        Returns:
            True 如果成功，False 如果失败
        """
        try:
            safe_name = _escape(name)
            safe_type = _escape(entity_type)
            doc_id_str = str(doc_id)

            async with async_session_factory() as session:
                await session.execute(text("LOAD 'age'"))
                await session.execute(text(
                    "SET search_path = ag_catalog, \"$user\", public"
                ))

                # Step 1: 检查实体是否已存在
                exists = await session.execute(text(f"""
                    SELECT * FROM cypher('{GRAPH_NAME}', $$
                        MATCH (e:Entity {{name: '{safe_name}', type: '{safe_type}'}})
                        RETURN e.name
                    $$) AS (name agtype)
                """))
                if exists.fetchone() is None:
                    # Step 2a: 不存在 → 创建，doc_ids 初始为单元素数组
                    query = text(f"""
                        SELECT * FROM cypher('{GRAPH_NAME}', $$
                            CREATE (e:Entity {{name: '{safe_name}', type: '{safe_type}',
                                              doc_ids: ['{doc_id_str}']}})
                            RETURN e.name
                        $$) AS (name agtype)
                    """)
                    await session.execute(query)
                else:
                    # Step 2b: 已存在 → 若 doc_id 不在数组内则追加
                    query = text(f"""
                        SELECT * FROM cypher('{GRAPH_NAME}', $$
                            MATCH (e:Entity {{name: '{safe_name}', type: '{safe_type}'}})
                            WHERE NOT '{doc_id_str}' IN e.doc_ids
                            SET e.doc_ids = e.doc_ids || ['{doc_id_str}']
                            RETURN e.name
                        $$) AS (name agtype)
                    """)
                    await session.execute(query)

                await session.commit()
                return True
        except Exception as e:
            logger.warning("实体写入失败 [%s]: %s", name[:30], e)
            return False

    async def upsert_relation(self, source: str, target: str) -> bool:
        """创建源实体到目标实体的 RELATED_TO 边（幂等）

        Args:
            source: 源实体名称
            target: 目标实体名称

        Returns:
            True 如果成功，False 如果失败
        """
        try:
            safe_src = _escape(source)
            safe_tgt = _escape(target)

            async with async_session_factory() as session:
                await session.execute(text("LOAD 'age'"))
                await session.execute(text(
                    "SET search_path = ag_catalog, \"$user\", public"
                ))
                query = text(f"""
                    SELECT * FROM cypher('{GRAPH_NAME}', $$
                        MATCH (a:Entity {{name: '{safe_src}'}})
                        MATCH (b:Entity {{name: '{safe_tgt}'}})
                        MERGE (a)-[r:RELATED_TO]->(b)
                        RETURN r
                    $$) AS (r agtype)
                """)
                await session.execute(query)
                await session.commit()
                return True
        except Exception as e:
            logger.warning("关系写入失败 [%s → %s]: %s", source[:20], target[:20], e)
            return False

    async def search_related(self, entities: list[str], top_k: int = 10) -> list[dict]:
        """从查询实体出发图遍历，返回关联文档

        Args:
            entities: 查询中提取的实体名称列表
            top_k: 返回的最大文档数

        Returns:
            文档列表（与 vector_retrieval 兼容格式），失败返回空列表
        """
        if not entities:
            return []

        try:
            async with async_session_factory() as session:
                await session.execute(text("LOAD 'age'"))
                await session.execute(text(
                    "SET search_path = ag_catalog, \"$user\", public"
                ))
                # 构建 Cypher 兼容的列表字符串 ["a","b","c"]
                safe_entities = ",".join(f"'{_escape(e)}'" for e in entities)
                entity_str = f"[{safe_entities}]"

                query = text(f"""
                    SELECT * FROM cypher('{GRAPH_NAME}', $$
                        MATCH (e:Entity)
                        WHERE e.name IN {entity_str}
                        OPTIONAL MATCH (e)-[:RELATED_TO]->(related:Entity)
                        RETURN DISTINCT COALESCE(related.doc_ids::TEXT, e.doc_ids::TEXT) AS doc_ids
                        LIMIT {top_k * 2}
                    $$) AS (doc_ids agtype)
                """)
                result = await session.execute(query)
                rows = result.fetchall()

            doc_ids: set[int] = set()
            for row in rows:
                try:
                    raw = str(row[0])
                    ids = json.loads(raw) if raw else []
                    if isinstance(ids, list):
                        for did in ids:
                            if isinstance(did, int) or (isinstance(did, str) and did.isdigit()):
                                doc_ids.add(int(did))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

            if not doc_ids:
                return []

            async with async_session_factory() as session:
                result = await session.execute(
                    select(Document)
                    .where(Document.id.in_(list(doc_ids)))
                    .where(Document.parent_id.is_(None))
                    .limit(top_k)
                )
                docs = result.scalars().all()

            output = []
            for d in docs:
                output.append({
                    "id": d.id,
                    "title": d.title,
                    "content": d.content,
                    "source": d.source,
                    "hybrid_score": 0.6,
                    "parent_id": None,
                })

            logger.info("图搜索完成: entities=%d, docs=%d", len(entities), len(output))
            return output
        except Exception as e:
            logger.warning("图搜索失败，降级返回空: %s", e)
            return []


# 全局单例
graph_store = GraphStore()
