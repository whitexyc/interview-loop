"""module-018 Tester: 检索链路（retriever + rerank）整体集成回归。

直接调用 rag_engine.search()（等同 tests/test_engine.py 的 async 用例，
因缺 pytest-asyncio 插件无法在 pytest 下运行，此处手动跑）。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rag.schemas import SearchRequest
from rag.engine import rag_engine


async def main():
    print("=== 集成: rag_engine.search('Java 线程池') ===")
    r = SearchRequest(query="Java 线程池", top_k=5)
    try:
        result = await rag_engine.search(r)
        print("message:", result.message)
        print("results count:", len(result.results))
        for d in result.results[:5]:
            print(f"  id={d.get('id')} score={d.get('score')} title={str(d.get('title'))[:40]}")
        # 无异常即视为通过（message='ok' 或检索结果为空时 message 为 '未检索到相关内容'）
        if result.message == "检索服务暂不可用":
            print("RESULT: FAIL (检索服务异常)")
            return 1
        print("RESULT: PASS")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("RESULT: FAIL (异常)", type(e).__name__, str(e)[:200])
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
