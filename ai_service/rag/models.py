"""
RAG 知识库文档 ORM 模型
"""
import logging

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
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
