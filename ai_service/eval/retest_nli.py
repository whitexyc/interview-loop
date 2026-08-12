"""
mDeBERTa 矛盾判别复测脚本（module-054 / ADR-0010 P1-③ 复测，实施前置放行门槛）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.retest_nli                      # 真实复测：矛盾样本 + 真实检索对 → kappa
    python -m eval.retest_nli --gen-real 24        # 生成真实检索候选对（LLM 答案 + DB 检索片段）
    python -m eval.retest_nli --no-save            # 不写 eval_runs
    python -m eval.retest_nli --limit 20           # 只评估前 20 条（冒烟）

复测口径（对齐 ADR-0010 "kappa 复测计划"四项）:
    1. 矛盾构造样本集 ≥30 条（本模块构造 32 条 + 正例对照 16 + neutral 8，
       eval/contradiction_dataset.json）——验证矛盾判别能力。
    2. claim 用真实答案句子（LLM 生成，非问题代答句；--gen-real 生成后人工
       标注 verdict，落 eval/real_retrieval_pairs.json）。
    3. 文档用 DB 真实检索片段（golden 112 题 hybrid 检索 top 片段）。
    4. 门槛：复测 kappa（三分类）≥ 0.7 通过（放行替换 mDeBERTa）；
       未达则降级评估（双轨：NLI 只做矛盾扫描），如实标注不伪造。

指标:
    Cohen's kappa（三分类 entailment/neutral/contradiction + 二值 entailment-vs-rest
    两口径，sklearn cohen_kappa_score）。kappa 校正随机一致（三分类基线 33%）。

降级:
    - mDeBERTa 模型缺失 → 明确报错（_require_model 同款），不静默通过
    - 单条打分异常 → 跳过记录，其余继续
    - 数据库不可用 → --gen-real 失败该条记 unavailable，评估仍完成
    - LLM 不可用 → --gen-real 如实标注 claim="[LLM_UNAVAILABLE]" 并声明口径

诚实边界:
    1. 矛盾样本为人工构造（非真实用户对话），方向性验证；标注一致性经
       Reviewer 抽查，非多人独立标注。
    2. 真实检索对 claim=LLM 生成答案句子（真实链路），doc=真实检索片段；
       人工标注 verdict 由 Developer 完成 + Reviewer 抽查。
    3. mDeBERTa 多语言训练，中文是泛化表现；输入截断 512 token（同 module-052）。
    4. 复测 kappa < 0.7 → 结论=降级双轨（NLI 只做矛盾扫描），不硬推放行。
"""
import argparse
import asyncio
import json
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"

from sklearn.metrics import cohen_kappa_score

from eval.contradiction_dataset import (DATASET_PATH, VERDICTS,
                                        load_contradiction_dataset)
from eval.compare_nli_models import (MDEBERTA_DIR, _require_model, binarize,
                                     load_mdeberta, mdeberta_score,
                                     model_metrics, print_metrics_table)

REAL_PAIRS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "real_retrieval_pairs.json")
REAL_CANDIDATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "real_retrieval_candidates.json")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden.json")

GATE_KAPPA = 0.7


def load_real_pairs(path: str = REAL_PAIRS_PATH) -> list[dict]:
    """加载真实检索对（part="real_retrieval"）；文件不存在返回 []"""
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    samples = payload["samples"] if isinstance(payload, dict) else payload
    for item in samples:
        for key in ("question", "claim", "doc", "verdict"):
            if not item.get(key, ""):
                raise ValueError(f"真实检索对缺 {key}: {item.get('question', '')[:30]}")
        if item["verdict"] not in VERDICTS:
            raise ValueError(f"verdict 须为 {VERDICTS}: {item.get('question', '')[:30]}")
    return samples


def gen_real_pairs(num: int = 24) -> None:
    """生成真实检索候选对：LLM 生成答案句子（claim）+ DB hybrid 检索片段（doc）

    只生成候选（无 verdict），人工标注后写入 real_retrieval_pairs.json。
    """
    from rag.retrieval.retriever import hybrid_retriever
    from llm.client import LLMFactory

    if not os.path.isfile(GOLDEN_PATH):
        raise FileNotFoundError(f"golden.json 缺失: {GOLDEN_PATH}")
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        golden = json.load(f)

    # 确定性抽样：跨类别取题（黄金 112 题按步长抽，保证类别多样）
    stride = max(1, len(golden) // num)
    picked = golden[::stride][:num]

    async def _one(item: dict) -> dict:
        q = item["question"]
        # 1) DB 真实检索片段（hybrid，本地 bge-m3 + pgvector）
        try:
            docs = await asyncio.wait_for(
                hybrid_retriever.retrieve(q, top_k=2), timeout=20,
            )
        except Exception as e:
            return {"question": q, "claim": "", "doc": f"[RETRIEVE_UNAVAILABLE: {e}]",
                    "doc_title": "", "category": item.get("category", "")}
        if not docs:
            return {"question": q, "claim": "", "doc": "[NO_DOCS]",
                    "doc_title": "", "category": item.get("category", "")}
        doc = docs[0]
        # 2) LLM 生成真实答案句子（deepseek 降级链）
        try:
            client = LLMFactory.get_client()
            answer = await asyncio.wait_for(
                client.generate(f"请用 1-2 句话直接回答（不要引用、不要补充与问题无关的内容）：{q}"),
                timeout=30,
            )
            claim = (answer or "").strip()
            if not claim:
                claim = "[EMPTY_ANSWER]"
        except Exception as e:
            claim = f"[LLM_UNAVAILABLE: {type(e).__name__}]"
        return {
            "question": q,
            "claim": claim,
            "doc": (doc.get("content") or "")[:700],
            "doc_title": doc.get("title", ""),
            "category": item.get("category", ""),
        }

    async def _gen_all():
        return await asyncio.gather(*[_one(i) for i in picked])

    candidates = asyncio.run(_gen_all())
    with open(REAL_CANDIDATES_PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": {"num": len(candidates), "note": "候选对，待人工标注 verdict"},
                   "samples": candidates}, f, ensure_ascii=False, indent=2)
    print(f"候选对已生成: {REAL_CANDIDATES_PATH}（{len(candidates)} 条，"
          f"请人工标注 verdict 后写入 {REAL_PAIRS_PATH}）")
    n_unavail = sum(1 for c in candidates if "UNAVAILABLE" in c["claim"] or "NO_DOCS" in c["doc"])
    if n_unavail:
        print(f"环境不可用标注: {n_unavail} 条（LLM/检索不可用，如实声明）")


def run_retest(limit: int | None = None, save: bool = True) -> None:
    """真实复测：矛盾样本 + 真实检索对 → mDeBERTa 打分 → kappa 两口径 + 门槛判定"""
    _require_model(MDEBERTA_DIR, [
        "config.json", "model.safetensors", "tokenizer.json",
        "tokenizer_config.json", "special_tokens_map.json", "spm.model",
    ])
    load_mdeberta()
    id2label = _mdeberta_label_map()

    constructed = load_contradiction_dataset()
    real_pairs = load_real_pairs()
    all_samples = constructed + real_pairs
    if limit:
        all_samples = all_samples[:limit]

    docs = [s["doc"] for s in all_samples]
    claims = [s["claim"] for s in all_samples]
    human3 = [s["verdict"] for s in all_samples]

    labels, _ = mdeberta_score(docs, claims)
    pred3 = [str(id2label[int(i)]) for i in labels]

    # 总体指标 + 分部分指标
    from collections import Counter
    dist = Counter(human3)
    print(f"== 数据: {len(all_samples)} 对（entailment {dist['entailment']} / "
          f"neutral {dist['neutral']} / contradiction {dist['contradiction']}）")
    print(f"   ├─ 人工构造样本: {len(constructed)} 条")
    print(f"   └─ 真实检索样本: {len(real_pairs)} 条"
          + ("（LLM 答案句子 + DB 检索片段）" if real_pairs else "（无，本次未提供）"))

    overall = model_metrics(human3, pred3)
    print("\n-- 指标（kappa 三分类 + 二值两口径）--")
    print_metrics_table("总体", overall)
    if real_pairs:
        n = len(constructed)
        constructed_metrics = model_metrics(human3[:n], pred3[:n])
        real_metrics = model_metrics(human3[n:], pred3[n:])
        print_metrics_table("  人工构造", constructed_metrics)
        print_metrics_table("  真实检索", real_metrics)

    # 混淆矩阵
    classes = ["entailment", "neutral", "contradiction"]
    print("\n-- 混淆矩阵（行=人工, 列=mDeBERTa）--")
    print(f"{'':<14}" + "".join(f"{c:>14}" for c in classes))
    for r in classes:
        row = [sum(1 for hr, pr in zip(human3, pred3) if hr == r and pr == c)
               for c in classes]
        print(f"{r:<14}" + "".join(f"{n:>14}" for n in row))

    # 误判明细（前 10 条）
    mis = [i for i in range(len(human3)) if human3[i] != pred3[i]]
    if mis:
        print(f"\n-- 误判 {len(mis)} 条（前 10 条）--")
        for i in mis[:10]:
            s = all_samples[i]
            print(f"  [{i}] 人工={human3[i]} 预测={pred3[i]} ({s.get('contradiction_type', '?')})")
            print(f"      claim: {s['claim'][:60]}")
            print(f"      doc:   {s['doc'][:60]}")

    # 门槛判定（ADR-0010 P1-③ 放行条件）
    print("\n" + "=" * 60)
    k3 = overall["kappa_3class"]
    print(f"复测 kappa(三分类) = {k3:.4f}  门槛 = {GATE_KAPPA}")
    if k3 >= GATE_KAPPA:
        print(f"==> 结论: kappa {k3:.4f} >= {GATE_KAPPA} 达标 —— 放行替换 "
              f"（mDeBERTa 作为逐句裁判三态来源，实施另行模块）")
    else:
        print(f"==> 结论: kappa {k3:.4f} < {GATE_KAPPA} 未达门槛，如实标注 —— "
              f"降级双轨：NLI 只做矛盾扫描（不替换 HHEM 主裁判）")
    print("=" * 60)

    if save:
        _save_eval_run(overall, human3, pred3, constructed, real_pairs)


def _mdeberta_label_map() -> dict:
    from eval.compare_nli_models import _mdeberta
    return _mdeberta["id2label"]


def _save_eval_run(metrics: dict, human3: list, pred3: list,
                   constructed: list, real_pairs: list) -> None:
    """版本化落库 eval_runs（eval_type='nli_retest'）；失败仅警告不中断

    注意：load_rag_config + save_eval_run 须在同一个事件循环内执行——
    asyncpg 连接池不可跨 asyncio.run() 复用（Windows ProactorEventLoop 既有约束）。
    """
    try:
        from eval.golden_retrieval import get_git_commit, load_rag_config, save_eval_run
        import asyncio

        per_question = [
            {"question": s["question"], "label": h, "predicted": p,
             "correct": h == p, "part": s.get("part", "constructed")}
            for s, h, p in zip(constructed + real_pairs, human3, pred3)
        ]

        async def _record():
            config_snapshot = await load_rag_config()
            return await save_eval_run(
                eval_type="nli_retest", git_commit=get_git_commit(),
                config_snapshot=config_snapshot,
                scores={**metrics, "gate_kappa": GATE_KAPPA,
                        "constructed_n": len(constructed), "real_n": len(real_pairs)},
                per_question=per_question,
            )

        saved_id = asyncio.run(_record())
        print(f"已落库 eval_runs (id={saved_id}, eval_type='nli_retest')")
    except Exception as e:
        print(f"eval_runs 落库失败（不中断）: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="mDeBERTa 矛盾判别复测（ADR-0010 P1-③）")
    parser.add_argument("--gen-real", type=int, metavar="N", default=0,
                        help="生成 N 条真实检索候选对（LLM 答案 + DB 检索片段）")
    parser.add_argument("--no-save", action="store_true", help="不记录 eval_runs")
    parser.add_argument("--limit", type=int, default=None, help="只评估前 N 条（冒烟）")
    args = parser.parse_args()

    if args.gen_real:
        gen_real_pairs(args.gen_real)
        return
    run_retest(limit=args.limit, save=not args.no_save)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
