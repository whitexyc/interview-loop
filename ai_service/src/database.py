"""
数据库连接管理
异步 SQLAlchemy + asyncpg + pgvector
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from .config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# feedback 表 DDL（module-048 反馈飞轮）：与 eval_runs 同款模式——
# 独立建表脚本 + 启动 init_db 自愈建表（CREATE TABLE IF NOT EXISTS，幂等）
FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS feedback (
    id           BIGSERIAL    PRIMARY KEY,
    message_id   INTEGER      NOT NULL,
    rating       INTEGER      NOT NULL,
    comment      TEXT,
    identity     VARCHAR(256) NOT NULL DEFAULT '',
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE feedback IS '用户反馈表（👍👎，层 4 分类器再训练数据源）';
COMMENT ON COLUMN feedback.message_id IS '关联的消息 ID（飞轮回填用）';
COMMENT ON COLUMN feedback.rating IS '评分：1=赞，-1=踩';
COMMENT ON COLUMN feedback.comment IS '补充评论（可选，≤500）';
COMMENT ON COLUMN feedback.identity IS '反馈者身份（user_id 优先，client_ip 兜底）';
"""


async def ensure_feedback_table() -> None:
    """幂等创建 feedback 表（数据库不可用时抛异常，由调用方处理）

    DDL 含多条语句（CREATE TABLE + COMMENT），asyncpg 不允许单条
    prepared statement 执行多条命令，因此按 ';' 拆分逐条执行。
    """
    statements = [s.strip() for s in FEEDBACK_DDL.split(";") if s.strip()]
    async with async_session_factory() as session:
        for stmt in statements:
            await session.execute(text(stmt))
        await session.commit()


async def init_db():
    """初始化数据库：启用 pgvector 扩展 + 自愈建 feedback 表"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("pgvector extension 已就绪")
    await ensure_feedback_table()
    logger.info("feedback 表已就绪（module-048）")


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
