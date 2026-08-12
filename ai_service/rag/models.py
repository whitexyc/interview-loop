"""
RAG 知识库文档 ORM 模型
"""
import logging

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from pgvector.sqlalchemy import Vector


logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """统一 ORM 基类"""


class Document(Base):
    """文档模型 — 存储知识库文档及其向量嵌入"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="文档 ID")
    title = Column(String(512), nullable=False, default="", comment="文档标题")
    content = Column(Text, nullable=False, comment="文档内容")
    source = Column(String(256), nullable=False, default="", comment="来源标识")
    page_num = Column(Integer, nullable=True, comment="页码")
    # 使用 meta 避免与 SQLAlchemy 保留属性 metadata 冲突
    meta = Column("metadata", JSONB, nullable=False, default=dict, comment="元数据")
    content_hash = Column(String(64), nullable=True, index=True, comment="内容 SHA256 哈希（去重用）")
    embedding = Column(Vector(1024), nullable=True, comment="向量嵌入")
    parent_id = Column(Integer, ForeignKey("documents.id"),
                       nullable=True, index=True,
                       comment="父块 ID（NULL=父块/根块，非NULL=子块指向其父块）")
    search_tokens = Column(Text, nullable=True,
                           comment="jieba分词后的空格连接文本（中文FTS检索用，仅子块写入）")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    # module-046 记忆进化：仅短期层使用（last_mentioned_at 提及刷新 / mention_count
    # 召回加权 + 升级阈值）。存量行字段为 NULL/0 时按 created_at 衰减、count=0 加权
    #（零迁移 fail-open，不写迁移脚本）
    last_mentioned_at = Column(
        DateTime(timezone=True), nullable=True, comment="最近提及时间（module-046 仅短期层使用）"
    )
    mention_count = Column(
        Integer, nullable=False, default=0, comment="提及次数（module-046 仅短期层使用）"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} title={self.title!r} source={self.source!r}>"

    def to_dict(self) -> dict:
        """转为可序列化字典"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "page_num": self.page_num,
            "metadata": self.meta,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Feedback(Base):
    """用户反馈模型 — 层 4 分类器（intent/充分性）再训练数据源（module-048）

    👍👎 反馈飞轮：前端对每条 AI 回复点赞/点踩（可选评论），落 feedback 表
    累积标注数据。feedback 与 documents 表无关（独立新表），message_id 先
    落前端消息 ID，飞轮回填脚本再按需关联 query/answer（本模块不建外键）。
    """

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="反馈 ID")
    message_id = Column(Integer, nullable=False, index=True,
                        comment="关联的消息 ID（飞轮回填用）")
    rating = Column(Integer, nullable=False, comment="评分：1=赞，-1=踩")
    comment = Column(Text, nullable=True, comment="补充评论（可选，≤500）")
    identity = Column(String(256), nullable=False, default="",
                      comment="反馈者身份（user_id 优先，client_ip 兜底）")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:
        return (f"<Feedback id={self.id} message_id={self.message_id} "
                f"rating={self.rating}>")


class RequestLog(Base):
    """请求观测日志 — 线上可观测性（module-058 WP-C）

    trace_id 贯穿日志与落库；timings/usage 为 JSONB（阶段耗时按毫秒、
    token 用量按供应商），支撑"单问题成本分布 / P50-P95 延迟"聚合查询。
    identity 对齐 048 口径（user_id 优先，client_ip 兜底）；建表走
    init_db 自愈幂等 DDL（src/database.py REQUEST_LOGS_DDL），
    落库失败 fail-open 不阻塞主链路。
    """

    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="日志 ID")
    trace_id = Column(String(64), nullable=False, index=True, comment="请求追踪 ID")
    identity = Column(String(256), nullable=False, default="",
                      comment="请求身份（user_id 优先，client_ip 兜底）")
    endpoint = Column(String(128), nullable=False, default="",
                      comment="端点（chat/chat_stream/agent/agent-lg）")
    intent = Column(String(64), nullable=False, default="",
                      comment="意图（knowledge/casual_chat/realtime/agent）")
    timings = Column(JSONB, nullable=False, default=dict, comment="各阶段耗时（毫秒）")
    usage = Column(JSONB, nullable=False, default=dict, comment="token 用量（按供应商）")
    cache_hits = Column(Integer, nullable=False, default=0, comment="检索缓存命中次数")
    cache_misses = Column(Integer, nullable=False, default=0, comment="检索缓存未命中次数")
    error = Column(Boolean, nullable=False, default=False, comment="请求错误标记")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:
        return f"<RequestLog id={self.id} trace_id={self.trace_id!r}>"
