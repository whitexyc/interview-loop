"""
Golden Factcheck 评测脚本 — HHEM 专职裁判 vs 人工标注 Cohen's kappa（ADR-0010 P1-④，module-051）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.golden.golden_factcheck                # 真实模式：HHEM 判 50 条 + 落库
    python -m eval.golden.golden_factcheck --fixture      # fixture 模式：关键词启发式，不依赖模型
    python -m eval.golden.golden_factcheck --no-save      # 纯跑分，不写 eval_runs

指标定义（ADR-0010 P1-④：kappa > 0.7 才信这个裁判，一致性≠正确性）:
    Cohen's kappa（三态）    supported/inferred/unsupported 直接算（sklearn union labels）
    Cohen's kappa（二值）    supported-vs-rest（human: label=="supported"；predicted:
                           max_score ≥ 阈值high 映射 supported——与生产三态映射同口径）
    Accuracy                三态精确一致率（辅助参考，不是验收门槛）

数据集:
    build_factcheck_dataset() 共 50 条：
    - supported 20 条：SUFFICIENCY_DATASET 充分样本取前 20（文档能回答问题，
      claim=问题，label 继承 module-044 人工充分性标注——代理度量，与 module-050 同口径）
    - unsupported 20 条：SUFFICIENCY_DATASET 不充分样本取前 20（文档完全不沾边）
    - inferred 10 条：人工构造——文档只部分覆盖问题（相关但不完整，典型中分区间）

判定口径（与生产 verify_answer 完全一致）:
    每 claim 对每篇文档 HHEM 打分 → max_score 映射三态（阈值读配置
    settings.verify_hhem_threshold_high=0.7 / low=0.3，module-051 经验值，标注集可校准）。

版本化回归:
    eval_runs 落库 eval_type='factcheck'（git_commit + rag_config 快照 +
    scores/per_question），对齐 eval/golden_retrieval.py 落库模式。

降级策略:
    - HHEM 不可用（模型缺失/加载失败/推理异常）→ 该条记 skipped（reason=model_unavailable），
      评估仍完成并输出已评估条目的 kappa（如实标注，不伪造数字）
    - 单条判定异常 → 跳过并记录错误，其余继续
    - 数据库不可用 → 分数记录失败打印警告，评估仍完成

诚实边界:
    - HHEM 为英文训练数据，中文输入属跨语言泛化（module-050 实测 Accuracy 0.77
      是最好可用裁判）；绝对分数偏低，kappa 看相对一致性。
    - supported/unsupported 的 label 是"文档能否回答问题"的代理标注（继承
      module-044 人工标注），inferred 为本次人工构造——量级小（50 条），
      kappa 门槛是方向性验证而非最终结论。
"""
import argparse
import asyncio
import logging
import sys

from sklearn.metrics import cohen_kappa_score

from eval.golden.golden_retrieval import get_git_commit, load_rag_config, save_eval_run
from eval.golden.golden_sufficiency import SUFFICIENCY_DATASET
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("golden_factcheck")

FACTCHECK_CLASSES = ("supported", "inferred", "unsupported")

# 人工构造的 inferred 样例（10 条）：文档只部分覆盖问题——相关但不完整，
# 典型落在三态映射的中分区间（0.3-0.7）。keywords 供 fixture 启发式使用。
INFERRED_SAMPLES: list[dict] = [
    {
        "question": "G1 垃圾收集器的调优参数怎么设置？",
        "documents": [{
            "title": "1-G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11",
            "content": "G1（Garbage First）垃圾收集器把堆划分为大小相等的 Region 区域，"
                       "每个 Region 可独立扮演 Eden、Survivor 或 Old 角色，通过 "
                       "Remembered Set 实现增量回收，停顿时间可预测。",
        }],
        "label": "inferred",
        "keywords": ["G1", "调优参数"],
        "category": "java_gc",
        "note": "文档讲 G1 机制但无任何调优参数",
    },
    {
        "question": "Kafka 生产者端怎么配置才能保证消息不丢失？",
        "documents": [{
            "title": "5-Kafka消息可靠性与高吞吐设计_2026-07-15",
            "content": "Kafka 可靠性核心是 ISR（In-Sync Replicas）机制：每个 Partition 有"
                       "多个副本，Leader 负责读写，Follower 拉取同步，超过"
                       "replica.lag.time.max.ms 未同步即被踢出 ISR。",
        }],
        "label": "inferred",
        "keywords": ["Kafka", "acks"],
        "category": "kafka",
        "note": "文档讲副本同步机制，无生产者端 acks 配置",
    },
    {
        "question": "线程池的四种拒绝策略分别是什么？",
        "documents": [{
            "title": "6-Java线程池ThreadPoolExecutor核心参数与工作原理_2026-07-16",
            "content": "ThreadPoolExecutor 六大核心参数：corePoolSize（核心线程数）、"
                       "maximumPoolSize（最大线程数）、workQueue（任务队列）、"
                       "keepAliveTime（空闲存活时间）、threadFactory（线程工厂）、"
                       "handler（拒绝策略）。",
        }],
        "label": "inferred",
        "keywords": ["ThreadPoolExecutor", "拒绝策略"],
        "category": "java_concurrency",
        "note": "文档只列出 handler 参数名，未展开四种拒绝策略",
    },
    {
        "question": "联合索引的最左前缀原则是什么？",
        "documents": [{
            "title": "8-MySQL索引原理与B+树_2026-07-18",
            "content": "InnoDB 使用 B+树索引：非叶子节点只存键值（扇出大，3 层可容纳"
                       "千万级数据），叶子节点存数据并按序串联，主键索引叶子存整行"
                       "（聚簇），二级索引叶子存主键值需回表。",
        }],
        "label": "inferred",
        "keywords": ["B+树", "最左前缀"],
        "category": "mysql",
        "note": "文档讲 B+树结构，无联合索引匹配规则",
    },
    {
        "question": "Redis 哨兵触发故障转移的流程是怎样的？",
        "documents": [{
            "title": "14-Redis高可用架构：主从+哨兵_2026-07-25",
            "content": "Redis 哨兵（Sentinel）独立进程监控主从节点，通过心跳（PING）"
                       "判断节点存活，主节点客观下线需多数哨兵同意。",
        }],
        "label": "inferred",
        "keywords": ["哨兵", "故障转移"],
        "category": "redis",
        "note": "文档讲监控与下线判定，无选举新主与切换流程",
    },
    {
        "question": "Spring AOP 的代理失效场景有哪些？",
        "documents": [{
            "title": "19-SpringAOP原理与动态代理_2026-07-30",
            "content": "Spring AOP 基于动态代理：有接口用 JDK 动态代理（Proxy + "
                       "InvocationHandler），无接口用 CGLIB（字节码生成子类），切面"
                       "织入发生在 BeanPostProcessor 阶段，代理对象替换原 Bean。",
        }],
        "label": "inferred",
        "keywords": ["AOP", "代理失效"],
        "category": "spring",
        "note": "文档讲代理实现原理，无失效场景列举",
    },
    {
        "question": "Netty 是怎么解决粘包问题的？",
        "documents": [{
            "title": "7-Netty高性能IO与Reactor线程模型_2026-07-17",
            "content": "Netty 采用主从 Reactor 线程模型：Boss 线程负责 accept 新连接并"
                       "注册到 Worker 线程组，Worker 线程处理该连接的读写事件，通过 "
                       "ChannelPipeline 逐 handler 处理。",
        }],
        "label": "inferred",
        "keywords": ["Netty", "粘包"],
        "category": "netty",
        "note": "文档讲线程模型，无编解码与粘包拆包方案",
    },
    {
        "question": "JWT 的刷新机制是怎么设计的？",
        "documents": [{
            "title": "22-JWT认证机制详解_2026-08-02",
            "content": "JWT 认证流程：用户登录后服务端签发 JWT（Header.Payload.Signature "
                       "三段，Base64Url 编码），客户端后续请求携带 Authorization: "
                       "Bearer <token>，服务端验签通过即信任载荷，天然无状态。",
        }],
        "label": "inferred",
        "keywords": ["JWT", "刷新"],
        "category": "auth",
        "note": "文档讲认证流程，无 refresh token 轮换机制",
    },
    {
        "question": "CAS 的 ABA 问题是怎么产生的？",
        "documents": [{
            "title": "41-CAS与原子操作原理_2026-08-21",
            "content": "CAS（Compare And Swap）是 CPU 原子指令：比较内存值与期望值，"
                       "相等则替换为新值，全程由 cmpxchg 指令保证原子性，Java 中 "
                       "Unsafe/VarHandle 提供，AtomicInteger 依赖 CAS 循环实现。",
        }],
        "label": "inferred",
        "keywords": ["CAS", "ABA"],
        "category": "java_concurrency",
        "note": "文档讲 CAS 原理，无 ABA 问题分析",
    },
    {
        "question": "HashMap 的扩容时机是怎么决定的？",
        "documents": [{
            "title": "12-HashMap与ConcurrentHashMap底层原理_2026-07-23",
            "content": "HashMap 底层是数组 + 链表 + 红黑树：key 经 hashCode 扰动后定位"
                       "数组槽位，冲突时链式挂载，链表长度超 8 且数组容量 ≥64 时树化"
                       "为红黑树，查找 O(log n)。",
        }],
        "label": "inferred",
        "keywords": ["HashMap", "扩容"],
        "category": "java_collection",
        "note": "文档讲结构与树化，无容量阈值与扩容流程",
    },
]


def build_factcheck_dataset() -> list[dict]:
    """构造 50 条 factcheck 标注（supported 20 + unsupported 20 + inferred 10）

    构造规则（代理度量，诚实边界见模块 docstring）：
    - supported/unsupported 继承 SUFFICIENCY_DATASET 的人工充分性标注（文档能否
      回答问题），确定性取前 20 条——与 module-050 对比脚本同口径
    - inferred 为人工构造的"部分覆盖"样例（INFERRED_SAMPLES）

    Returns:
        样本列表，每项含 question / documents / label（三态）/ keywords / category
    """
    items = []
    sufficient = [i for i in SUFFICIENCY_DATASET if i["sufficient"]]
    insufficient = [i for i in SUFFICIENCY_DATASET if not i["sufficient"]]
    for item in sufficient[:20]:
        items.append({
            "question": item["question"],
            "documents": item["documents"],
            "label": "supported",
            "keywords": item["keywords"],
            "category": item["category"],
        })
    for item in insufficient[:20]:
        items.append({
            "question": item["question"],
            "documents": item["documents"],
            "label": "unsupported",
            "keywords": item["keywords"],
            "category": item["category"],
        })
    items.extend(INFERRED_SAMPLES)
    return items


def load_factcheck_dataset() -> list[dict]:
    """加载 factcheck 标注集，校验结构

    Returns:
        样本列表，每项含 question / documents / label（三态）

    Raises:
        ValueError: 样本 < 50、question 为空、documents 为空、label 非三态、三类不齐全
    """
    data = build_factcheck_dataset()
    if len(data) < 50:
        raise ValueError(f"factcheck 评测集过小：需 ≥ 50 条，当前 {len(data)}")
    for item in data:
        if not item.get("question", "").strip():
            raise ValueError(f"factcheck 评测集存在空 question: {item}")
        if not item.get("documents"):
            raise ValueError(f"factcheck 评测集存在空 documents: {item.get('question', '')[:30]}")
        if item.get("label") not in FACTCHECK_CLASSES:
            raise ValueError(f"label 须为 {FACTCHECK_CLASSES}: {item.get('question', '')[:30]}")
    counts = {c: sum(1 for i in data if i["label"] == c) for c in FACTCHECK_CLASSES}
    if not all(counts.values()):
        raise ValueError(f"factcheck 评测集缺少类别（三态须都有）: {counts}")
    return data


def heuristic_judge(question: str, documents: list[dict], keywords: list[str]) -> str:
    """fixture 启发式判断器：关键词命中数映射三态（确定性，不依赖 LLM/模型）

    命中 ≥2 个核心术语 → supported（文档覆盖充分）；恰好 1 个 → inferred（部分覆盖）；
    0 个 → unsupported（完全不沾边）。仅用于 fixture 模式演示评测管线，
    不代表真实判断能力。
    """
    if not documents:
        return "unsupported"
    text = "".join(d.get("content", "") for d in documents)
    hits = sum(1 for kw in keywords if kw in text)
    if hits >= 2:
        return "supported"
    if hits == 1:
        return "inferred"
    return "unsupported"


async def judge_factcheck(question: str, documents: list[dict]) -> tuple[str, float]:
    """真实模式：HHEM 逐文档打分 → max 分映射三态（与生产 verify_answer 同口径）

    Args:
        question: claim 文本（本题集 claim=问题）
        documents: 检索文档列表

    Returns:
        (verdict, max_score)；HHEM 不可用 → (None, None)（上层记 skipped，不中断）
    """
    from rag.retrieval.factcheck_judge import hhem_judge

    doc_texts = [d.get("content", "") for d in documents]
    scores = await hhem_judge.predict(doc_texts, [question] * len(doc_texts))
    if scores is None:
        return None, None
    max_score = max(scores)
    high = settings.verify_hhem_threshold_high
    low = settings.verify_hhem_threshold_low
    if max_score >= high:
        return "supported", float(max_score)
    if max_score >= low:
        return "inferred", float(max_score)
    return "unsupported", float(max_score)


def kappa_metrics(human: list[str], predicted: list[str]) -> dict:
    """三态 + 二值两种口径的 Cohen's kappa + 三态精确一致率（纯函数）

    - 三态：supported/inferred/unsupported 直接算（sklearn 对两序列取标签并集）
    - 二值：supported-vs-rest——human: label=="supported"；predicted: 三态预测中的
      supported 位（与生产阈值同口径，不另设 0.5 阈值）

    Args:
        human: 人工标注标签列表（与 predicted 等长）
        predicted: HHEM 判定标签列表

    Returns:
        {"kappa_three_state": float, "kappa_binary_supported_vs_rest": float,
         "accuracy": float}
        空输入（全部跳过）→ 全 0.0（sklearn 空数组会抛 ValueError，不中断评估）
    """
    if not human or not predicted:
        return {"kappa_three_state": 0.0, "kappa_binary_supported_vs_rest": 0.0,
                "accuracy": 0.0}
    kappa3 = cohen_kappa_score(human, predicted)
    human_bin = [1 if l == "supported" else 0 for l in human]
    pred_bin = [1 if p == "supported" else 0 for p in predicted]
    kappa2 = cohen_kappa_score(human_bin, pred_bin)
    agree = (sum(1 for h, p in zip(human, predicted) if h == p)
             / len(human) if human else 0.0)
    return {
        "kappa_three_state": round(float(kappa3), 4),
        "kappa_binary_supported_vs_rest": round(float(kappa2), 4),
        "accuracy": round(float(agree), 4),
    }


async def run_eval(judge=None, dataset=None) -> tuple[dict, list[dict], list[dict]]:
    """执行一次 factcheck 评估

    Args:
        judge: 判断协程 (question, documents) -> (verdict, max_score)；
               默认 judge_factcheck（真实模式，HHEM）
        dataset: 评测样本列表；默认 build_factcheck_dataset()

    Returns:
        (scores, per_question, skipped)
        - scores: kappa 三态/二值 + accuracy + 类别分布 + 阈值快照
        - per_question: 每条明细（label/predicted/correct/max_score/category）
        - skipped: 判定失败或模型不可用的样本记录
    """
    items = dataset if dataset is not None else build_factcheck_dataset()
    judge_fn = judge if judge is not None else judge_factcheck
    per_question: list[dict] = []
    skipped: list[dict] = []

    for i, item in enumerate(items):
        question = item["question"]
        label = item["label"]
        try:
            verdict, max_score = await judge_fn(question, item["documents"])
        except Exception as e:
            logger.error("[%d/%d] factcheck 判定失败: %s — %s", i + 1, len(items),
                         question[:40], e)
            skipped.append({"question": question, "label": label,
                            "reason": f"error: {e}"})
            continue
        if verdict is None:
            skipped.append({"question": question, "label": label,
                            "reason": "model_unavailable"})
            continue
        per_question.append({
            "question": question,
            "label": label,
            "predicted": verdict,
            "correct": verdict == label,
            "max_score": round(float(max_score), 4) if max_score is not None else None,
            "category": item.get("category", ""),
        })

    kappa = kappa_metrics([q["label"] for q in per_question],
                          [q["predicted"] for q in per_question])
    scores = {
        "dataset_size": len(items),
        "evaluated": len(per_question),
        "skipped": len(skipped),
        **kappa,
        "class_distribution": {
            c: sum(1 for q in per_question if q["label"] == c)
            for c in FACTCHECK_CLASSES
        },
        "thresholds": {
            "high": settings.verify_hhem_threshold_high,
            "low": settings.verify_hhem_threshold_low,
        },
    }
    return scores, per_question, skipped


async def record_eval_run(scores: dict, per_question: list[dict]) -> tuple[str, int]:
    """版本化落库：git_commit + rag_config 快照 + eval_type='factcheck'

    Returns:
        (commit, saved_id)；落库失败 saved_id=0（save_eval_run 内部已捕获并警告）
    """
    commit = get_git_commit()
    config_snapshot = await load_rag_config()
    saved_id = await save_eval_run(
        eval_type="factcheck",
        git_commit=commit,
        config_snapshot=config_snapshot,
        scores=scores,
        per_question=per_question,
    )
    return commit, saved_id


def print_report(scores: dict, per_question: list[dict], skipped: list[dict],
                 saved_id: int, commit: str, fixture: bool) -> None:
    """打印评估报告到控制台：kappa 两种口径 + 类别分布 + 误判明细 + 门槛判定"""
    print("\n" + "=" * 60)
    print("Golden Factcheck Eval" + ("  [fixture 模式：启发式判断器，非真实指标]" if fixture else ""))
    print("=" * 60)
    print(f"Dataset: {scores['dataset_size']} | Evaluated: {scores['evaluated']} | "
          f"Skipped: {scores['skipped']}")
    print(f"Thresholds: high={scores['thresholds']['high']} low={scores['thresholds']['low']}")
    print("-" * 60)
    k3 = scores["kappa_three_state"]
    k2 = scores["kappa_binary_supported_vs_rest"]
    print(f"Cohen's kappa (三态): {k3:.4f}")
    print(f"Cohen's kappa (二值 supported-vs-rest): {k2:.4f}")
    print(f"Accuracy (三态精确一致): {scores['accuracy']:.4f}")
    gate = 0.7
    if fixture:
        # fixture 模式：启发式判断器产出非真实指标，不做达标/未达判定
        print(f"==> [fixture] 三态 kappa {k3:.4f}（启发式，非真实指标），"
              f"不构成 ADR-0010 P1-④ 门槛判定")
    elif scores["evaluated"] < scores["dataset_size"]:
        print(f"==> 门槛判定: 有 {scores['skipped']} 条未评估（模型不可用/失败），"
              f"kappa 基于 {scores['evaluated']} 条，如实标注")
    elif k3 >= gate:
        print(f"==> 门槛判定: 三态 kappa {k3:.4f} >= {gate} 达标（ADR-0010 P1-④）")
    else:
        print(f"==> 门槛判定: 三态 kappa {k3:.4f} < {gate} 未达门槛，如实标注"
              f"（阈值/标注集可校准，不伪造数字）")
    print("-" * 60)
    print("Class distribution (human labels):")
    for cls in FACTCHECK_CLASSES:
        n = scores["class_distribution"].get(cls, 0)
        ok = sum(1 for q in per_question if q["label"] == cls and q["correct"])
        print(f"  {cls:<12} n={n:<3} 判对 {ok}/{max(n, 1)}")
    mis = [q for q in per_question if not q["correct"]]
    if mis:
        print("-" * 60)
        print(f"Misclassified ({len(mis)}):")
        for q in mis:
            score_txt = f"{q['max_score']:.3f}" if q.get("max_score") is not None else "n/a"
            print(f"  label={q['label']:<12} -> {q['predicted']:<12} "
                  f"score={score_txt} | {q['question'][:40]}")
    if skipped:
        print("-" * 60)
        print(f"Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  [{s['reason'][:30]}] {s['question'][:50]}")
    print("=" * 60)
    if saved_id:
        print(f"Saved to eval_runs (id={saved_id}, commit={commit[:8]})")
    else:
        print("Not saved to eval_runs")
    print()


async def main() -> None:
    """评测脚本入口"""
    parser = argparse.ArgumentParser(
        description="Golden factcheck 评测：HHEM 裁判 vs 人工标注 kappa（三态+二值）+ 版本化回归")
    parser.add_argument("--fixture", action="store_true",
                        help="fixture 模式：关键词启发式判断器（确定性，不依赖模型/DB），仅演示管线")
    parser.add_argument("--no-save", action="store_true", help="不记录 eval_runs 表")
    args = parser.parse_args()

    load_factcheck_dataset()

    if args.fixture:
        samples = build_factcheck_dataset()

        async def _fixture_judge(question, documents):
            item = next(i for i in samples if i["question"] == question)
            return heuristic_judge(question, documents, item["keywords"]), None
        judge = _fixture_judge
    else:
        judge = None  # 默认走 HHEM（真实模式）

    scores, per_question, skipped = await run_eval(judge=judge)

    saved_id = 0
    commit = ""
    if not args.no_save:
        commit, saved_id = await record_eval_run(scores, per_question)
    print_report(scores, per_question, skipped, saved_id, commit, fixture=args.fixture)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
