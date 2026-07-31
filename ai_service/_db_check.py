"""module-018 Tester: 只读校验 rag_config.reranker_model 数据库实际值"""
import asyncio
from sqlalchemy import text
from src.database import engine


async def main():
    try:
        async with engine.connect() as conn:
            r = await conn.execute(
                text("SELECT config_key, config_value FROM rag_config WHERE config_key = 'reranker_model'")
            )
            row = r.fetchone()
            print("DB rag_config row:", row)
            if row and row[1] == "Qwen/Qwen3-Reranker-0.6B":
                print("RESULT: SYNCED")
            else:
                print("RESULT: NOT-SYNCED")
    except Exception as e:
        print("DB query failed:", type(e).__name__, str(e)[:300])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
