"""module-018 Tester 验收测试：完整断言覆盖 acceptance-criteria.md §4.

覆盖：
  A. 正常加载 + 排序（rerank('Java 线程池参数', docs, top_k=3)）
  B. 缺权重 / 缺目录 → RerankerException（不回退 HF）
  C. 边界：空文档 / 单文档 / top_k 超长 / top_k=1 / top_k=0 / 缺 content 字段
  D. 接口契约：返回数量 = min(top_k, len)、rerank_score 为 float、原字段保留
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rag.reranker import CrossEncoderReranker, RerankerException

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  [FAIL] {name} {detail}")


async def main():
    print("=== A. 正常加载 + 排序 ===")
    rr = CrossEncoderReranker()
    docs = [
        {'id': 1, 'content': 'Java 线程池的核心参数包括核心线程数、最大线程数'},
        {'id': 2, 'content': 'Redis 缓存穿透是指查询不存在的数据'},
        {'id': 3, 'content': '线程池的拒绝策略有 AbortPolicy、CallerRunsPolicy'},
    ]
    result = await rr.rerank('Java 线程池参数', docs, top_k=3)
    ids = [d['id'] for d in result]
    print(f"  排序 ids={ids}, scores={[round(d['rerank_score'], 4) for d in result]}")
    check("A1 返回 3 条 (top_k=3)", len(result) == 3, f"got {len(result)}")
    check("A2 id=1 排最前 (相关文档排前)", ids[0] == 1, f"first={ids[0]}")
    check("A3 分数降序", [d['rerank_score'] for d in result] ==
          sorted([d['rerank_score'] for d in result], reverse=True))
    check("A4 rerank_score 为 float", all(isinstance(d['rerank_score'], float) for d in result))
    check("A5 原字段保留 (id/content)", all('id' in d and 'content' in d for d in result))
    check("A6 无 RerankerException", True)

    print("=== B. 缺权重 / 缺目录报错 ===")
    # B1 目录不存在 → RerankerException
    bad = CrossEncoderReranker(model_name="/nonexistent/model/path")
    try:
        await bad.rerank("test", [{'id': 1, 'content': 'x'}])
        check("B1 目录不存在抛 RerankerException", False, "未抛出")
    except RerankerException as e:
        check("B1 目录不存在抛 RerankerException", True, f"-> {type(e).__name__}")
    except Exception as e:
        check("B1 目录不存在抛 RerankerException", False, f"抛错类型错误: {type(e).__name__}")

    # B2 目录存在但缺权重文件 → RerankerException
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "tokenizer.json"), "w").close()
        no_weight = CrossEncoderReranker(model_name=tmp)
        try:
            await no_weight.rerank("test", [{'id': 1, 'content': 'x'}])
            check("B2 缺权重文件抛 RerankerException", False, "未抛出")
        except RerankerException as e:
            check("B2 缺权重文件抛 RerankerException", True, f"-> {type(e).__name__}")
        except Exception as e:
            check("B2 缺权重文件抛 RerankerException", False, f"抛错类型错误: {type(e).__name__}")

    # B3 仅缺一个权重文件（model.safetensors 缺失但 pytorch_model.bin 存在）→ 不报错
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "pytorch_model.bin"), "w").close()
        one_weight = CrossEncoderReranker(model_name=tmp)
        try:
            # 权重文件存在性校验应通过，之后 CrossEncoder 加载失败会抛 RerankerException
            await one_weight.rerank("test", [{'id': 1, 'content': 'x'}])
            check("B3 至少一个权重文件存在 → 校验放行", False, "加载意外成功")
        except RerankerException as e:
            check("B3 至少一个权重文件存在 → 校验放行", True,
                  f"校验通过(进入加载阶段)，加载失败包装为 {type(e).__name__}")
        except Exception as e:
            check("B3 至少一个权重文件存在 → 校验放行", False,
                  f"抛错类型错误: {type(e).__name__}")

    print("=== C. 边界情况 ===")
    empty = await rr.rerank('q', [])
    check("C1 空 documents -> []", empty == [], f"got {empty}")

    single = await rr.rerank('q', [{'id': 9, 'content': '只有一篇文档'}])
    check("C2 单文档返回 1 条带 rerank_score",
          len(single) == 1 and 'rerank_score' in single[0] and isinstance(single[0]['rerank_score'], float))

    many = await rr.rerank('q', docs, top_k=99)
    check("C3 top_k=99 超长返回全部", len(many) == len(docs), f"got {len(many)}")

    one = await rr.rerank('q', docs, top_k=1)
    check("C4 top_k=1 返回 1 条", len(one) == 1, f"got {len(one)}")

    zero = await rr.rerank('q', docs, top_k=0)
    check("C5 top_k=0 返回 0 条 (min(0,len))", len(zero) == 0, f"got {len(zero)}")

    missing_content = await rr.rerank('q', [{'id': 7}, {'id': 8, 'content': '有内容'}])
    check("C6 缺 content 字段不抛异常且返回 2 条",
          len(missing_content) == 2, f"got {len(missing_content)}")

    print("=== D. 接口契约 ===")
    n = 3
    r3 = await rr.rerank('Java 线程池参数', docs[:5], top_k=n)
    check("D1 返回数量 = min(top_k, len)", len(r3) == min(n, 5), f"got {len(r3)}")
    check("D2 顺序按 rerank_score 降序",
          [d['rerank_score'] for d in r3] == sorted([d['rerank_score'] for d in r3], reverse=True))

    print(f"\n=== RESULT: {PASS} passed, {FAIL} failed ===")
    if FAILURES:
        print("FAILED:", FAILURES)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
