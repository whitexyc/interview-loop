"""
Golden Sufficiency 评测脚本 — 充分性判断 Accuracy/P/R/F1 + 混淆矩阵 + 版本化回归（module-044 层 0）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.golden_sufficiency                 # 真实模式：reflector.check_sufficiency 判每条样本 + 落库
    python -m eval.golden_sufficiency --fixture       # fixture 模式：启发式判断器，不依赖 LLM/DB（管线演示）
    python -m eval.golden_sufficiency --no-save       # 纯跑分，不写 eval_runs

指标定义（对齐 ADR-0005 层 0）:
    Accuracy      全部样本判对比例
    Precision     该类预测中判对比例
    Recall        该类真实样本中被抓回比例
    F1            精确率与召回率的调和平均
    Confusion Matrix  行=真实充分性，列=预测充分性
    **重点看 insufficient 类的 Recall**：漏判"不充分"（把不充分判成充分）会导致
    基于无关文档硬答，最致命——报告里单独大字标出。

数据集:
    内嵌 SUFFICIENCY_DATASET：问题借 golden 集真实题目（eval/golden.json），
    注入代表性文档（相关文档/不相关文档），人工标注充分/不充分两类，共 12 条
    （充分 6 + 不充分 6）；每条 2 篇文档——兼容层 1 数量闸门（文档数 < 2 →
    直接判不充分，零 LLM），确保真实模式测到 LLM 判断而非被数量闸门短路。
    fixture 模式不依赖 DB 检索与 LLM。

版本化回归:
    每次运行记录 eval_runs 表（eval_type='sufficiency'，git_commit + rag_config
    快照 + scores/per_question），对齐 eval/golden_retrieval.py 的落库模式。
    改 check_sufficiency（层 1-3）后跑分对比，量化充分性判断误判率变化。

降级策略:
    - 单条判断失败 → 跳过并记录错误，其余继续
    - 数据库不可用 → 分数记录失败打印警告，评估仍完成
    - reflector.check_sufficiency 内部失败默认充分（现有降级哲学，不误杀）
"""
import argparse
import asyncio
import logging
import sys

from agent.reflector import reflector
from eval.golden_retrieval import get_git_commit, load_rag_config, save_eval_run
from eval.golden_intent import compute_confusion_matrix

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("golden_sufficiency")

SUFFICIENCY_CLASSES = ("sufficient", "insufficient")

# 充分性标注集：问题借 golden 集真实题目，文档为代表性内容（相关/不相关），
# 人工标注充分性。keywords 为问题核心术语，供 fixture 启发式判断器使用。
SUFFICIENCY_DATASET: list[dict] = [
    # ---- 充分（相关文档能回答问题，6 条）----
    {
        "question": "什么是G1垃圾收集器？它的核心创新是什么？",
        "documents": [{
            "title": "1-G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11",
            "content": "G1（Garbage First）垃圾收集器是 JDK 9 之后的默认垃圾收集器。"
                       "核心设计是把堆划分为大小相等的 Region 区域，每个 Region 可独立扮演 Eden、"
                       "Survivor 或 Old 角色，实现增量回收。G1 的核心创新：1）Region 分区 + "
                       "Remembered Set 使回收粒度降到区域级，停顿时间可预测；2）回收价值优先，"
                       "优先回收垃圾最多的 Region；3）并发标记 + SATB 写屏障与用户线程并发执行；"
                       "4）复制式回收避免 CMS 的碎片问题。MixedGC 在并发标记完成后同时回收"
                       "年轻代与高收益的老年代 Region。",
        }, {
            "title": "1-G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11 > 板块3 > 调优参数",
            "content": "G1 常用调优参数：-XX:MaxGCPauseMillis=200 设定停顿目标；"
                       "-XX:G1HeapRegionSize=8m 指定 Region 大小；"
                       "-XX:InitiatingHeapOccupancyPercent=45 控制并发标记触发阈值。"
                       "调优经验：大对象（Humongous）直接分配在连续 Region，频繁分配会提前触发"
                       "并发标记；RSet 占用约 5%-10% 堆空间，Region 越小 RSet 越精细但开销越大。",
        }],
        "sufficient": True,
        "keywords": ["G1", "Region", "MixedGC"],
        "category": "java_gc",
    },
    {
        "question": "Kafka的ISR机制是如何保证消息可靠性的？",
        "documents": [{
            "title": "5-Kafka消息可靠性与高吞吐设计_2026-07-15",
            "content": "Kafka 可靠性核心是 ISR（In-Sync Replicas）机制：每个 Partition 有多个副本，"
                       "Leader 负责读写，Follower 拉取同步，超过 replica.lag.time.max.ms 未同步即被踢出 ISR。"
                       "生产者端 acks=all 配合 min.insync.replicas=2 保证 ISR 中至少一个副本确认；"
                       "消费端手动提交 offset 防丢消息。高吞吐依赖顺序写、页缓存与零拷贝。",
        }, {
            "title": "5-Kafka消息可靠性与高吞吐设计_2026-07-15 > 板块2 > 生产端配置",
            "content": "生产端可靠性配置：acks=0 发完即走可能丢消息；acks=1 Leader 写入即确认，"
                       "Leader 宕机可能丢；acks=all 要求 ISR 所有副本写入，配合 min.insync.replicas=2 "
                       "与 retries 重试参数，实现不丢消息。幂等性（enable.idempotence=true）配合"
                       "事务机制进一步防止重复写入。",
        }],
        "sufficient": True,
        "keywords": ["ISR", "副本", "acks"],
        "category": "kafka",
    },
    {
        "question": "AQS (AbstractQueuedSynchronizer) 的工作原理是什么？ReentrantLock如何基于AQS实现？",
        "documents": [{
            "title": "15-AQS抽象队列同步器与ReentrantLock实现原理_2026-07-26",
            "content": "AQS 是 Java 并发包基石，核心是 volatile int state 字段 + CLH 变体 FIFO 等待队列。"
                       "state 表示同步状态，ReentrantLock 中表示重入次数；获取失败的线程封装为 Node "
                       "入队，通过自旋 + park 阻塞，前驱释放后唤醒后继。ReentrantLock 非公平锁先 CAS "
                       "抢锁再排队，公平锁严格 FIFO；释放时 state 减到 0 唤醒队首。AQS 支持独占"
                       "（acquire/release）与共享（acquireShared/releaseShared）两种模式。",
        }, {
            "title": "15-AQS抽象队列同步器与ReentrantLock实现原理_2026-07-26 > 板块2 > Condition与实战",
            "content": "ReentrantLock 通过 newCondition() 创建多个条件队列，await() 释放锁并等待、"
                       "signal() 唤醒等待线程，典型场景是 ArrayBlockingQueue 的 notEmpty/notFull "
                       "两个 Condition。lockInterruptibly() 支持响应中断，tryLock(timeout) 支持限时"
                       "抢锁——这是 synchronized 不具备的能力。",
        }],
        "sufficient": True,
        "keywords": ["AQS", "ReentrantLock", "state"],
        "category": "java_concurrency",
    },
    {
        "question": "volatile关键字的作用和实现原理是什么？",
        "documents": [{
            "title": "16-volatile与Java内存模型JMM_2026-07-27",
            "content": "volatile 是 Java 提供的轻量级同步机制，两大作用：1）可见性——写 volatile 变量"
                       "会插入 StoreStore/StoreLoad 内存屏障，强制刷新到主内存，读时从主内存读取，"
                       "避免线程工作内存缓存导致的值过期；2）有序性——禁止指令重排序，防止单例"
                       "双重检查锁中对象未初始化完成即被发布。volatile 不保证原子性，复合操作"
                       "（如 i++）仍需 synchronized 或原子类。",
        }, {
            "title": "16-volatile与Java内存模型JMM_2026-07-27 > 板块2 > 双检锁示例",
            "content": "双重检查锁（Double-Checked Locking）单例：外层判空避免无谓加锁，内层"
                       "synchronized 保证只实例化一次，instance 字段声明为 volatile 防止指令重排"
                       "导致返回未完成初始化的对象。这是 volatile 有序性语义的经典应用场景。",
        }],
        "sufficient": True,
        "keywords": ["volatile", "可见性", "内存屏障"],
        "category": "java_concurrency",
    },
    {
        "question": "Redis的持久化方式RDB和AOF有什么区别？如何选择？",
        "documents": [{
            "title": "10-Redis持久化机制_2026-07-20",
            "content": "Redis 两种持久化：RDB 定时生成全量快照（fork 子进程写临时文件），恢复快但可能"
                       "丢最后一次快照后的数据；AOF 追加写命令日志，默认 everysec 每秒 fsync，"
                       "最多丢 1 秒数据，文件会不断增大需 AOF 重写压缩。选择：能接受少量丢数据、"
                       "看重恢复速度用 RDB；数据安全要求高用 AOF；生产一般 RDB + AOF 组合。",
        }, {
            "title": "10-Redis持久化机制_2026-07-20 > 板块2 > 混合持久化",
            "content": "Redis 4.0 引入混合持久化：AOF 重写时把历史数据以 RDB 格式写入 AOF 文件头部，"
                       "后续增量用命令追加——兼顾 RDB 的恢复速度与 AOF 的数据安全，是生产环境的"
                       "推荐配置（aof-use-rdb-preamble yes）。",
        }],
        "sufficient": True,
        "keywords": ["RDB", "AOF", "持久化"],
        "category": "comprehensive",
    },
    {
        "question": "synchronized的底层实现原理是什么？锁升级过程是怎样的？",
        "documents": [{
            "title": "12-HashMap与ConcurrentHashMap底层原理_2026-07-23",
            "content": "synchronized 底层基于对象头 Mark Word + Monitor 监视器锁。锁升级路径："
                       "无锁 → 偏向锁（单线程重入，CAS 记录线程 ID）→ 轻量级锁（竞争时自旋 CAS "
                       "抢锁）→ 重量级锁（阻塞挂起，依赖操作系统互斥量）。JDK 6 之后的优化使"
                       "无竞争场景开销极低。锁升级是单向不可逆的，避免频繁竞争可减少升级到重量级锁。",
        }, {
            "title": "12-HashMap与ConcurrentHashMap底层原理_2026-07-23 > 板块3 > 锁对比",
            "content": "synchronized 与 ReentrantLock 对比：synchronized 由 JVM 管理锁升级，写法简单"
                       "自动释放；ReentrantLock 支持可中断、限时、公平性与多 Condition，灵活但需"
                       "手动释放。无竞争时两者性能接近，有竞争时 AQS 表现更可预测。",
        }],
        "sufficient": True,
        "keywords": ["synchronized", "Monitor", "锁升级"],
        "category": "java_concurrency",
    },
    # ---- 不充分（文档无法回答问题，6 条）----
    {
        "question": "什么是G1垃圾收集器？它的核心创新是什么？",
        "documents": [{
            "title": "5-Kafka消息可靠性与高吞吐设计_2026-07-15",
            "content": "Kafka 可靠性核心是 ISR（In-Sync Replicas）机制：每个 Partition 有多个副本，"
                       "Leader 负责读写，Follower 拉取同步，超过 replica.lag.time.max.ms 未同步即被"
                       "踢出 ISR。生产者端 acks=all 配合 min.insync.replicas=2 保证确认；消费端手动"
                       "提交 offset 防丢消息。",
        }, {
            "title": "7-Netty高性能IO与Reactor线程模型_2026-07-17",
            "content": "Netty 基于 Reactor 线程模型：Boss 线程负责 accept 连接并注册到 Worker 线程，"
                       "Worker 线程处理读写事件。零拷贝通过堆外内存与 CompositeByteBuf 实现，"
                       "避免多次内存拷贝，是高吞吐网络编程的基础设施。",
        }],
        "sufficient": False,
        "keywords": ["G1", "Region", "MixedGC"],
        "category": "java_gc",
        "note": "完全不沾边：问 G1 却检索到 Kafka/Netty 文档",
    },
    {
        "question": "ZGC的特点和适用场景是什么？",
        "documents": [{
            "title": "1-G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11",
            "content": "G1（Garbage First）垃圾收集器是 JDK 9 之后的默认垃圾收集器。核心设计是把堆"
                       "划分为大小相等的 Region 区域，每个 Region 可独立扮演 Eden、Survivor 或 Old "
                       "角色。G1 的核心创新：Region 分区 + Remembered Set、回收价值优先、"
                       "并发标记 + SATB 写屏障。MixedGC 在并发标记完成后回收年轻代与高收益 Region。",
        }, {
            "title": "1-G1垃圾收集器的Region分区机制与MixedGC全流程_2026-07-11 > 板块3 > 调优参数",
            "content": "G1 常用调优参数：-XX:MaxGCPauseMillis=200、-XX:G1HeapRegionSize=8m、"
                       "-XX:InitiatingHeapOccupancyPercent=45。调优经验：大对象分配在连续 Region，"
                       "频繁分配会提前触发并发标记；RSet 占用约 5%-10% 堆空间。",
        }],
        "sufficient": False,
        "keywords": ["ZGC", "适用场景"],
        "category": "java_gc",
        "note": "主题错位：文档全篇讲 G1，不含 ZGC 任何内容",
    },
    {
        "question": "Kafka的零拷贝(Zero-Copy)技术是如何实现的？",
        "documents": [{
            "title": "15-AQS抽象队列同步器与ReentrantLock实现原理_2026-07-26",
            "content": "AQS 是 Java 并发包基石，核心是 volatile int state 字段 + CLH 变体 FIFO 等待"
                       "队列。state 表示同步状态；获取失败的线程封装为 Node 入队，通过自旋 + park "
                       "阻塞。ReentrantLock 非公平锁先 CAS 抢锁再排队，公平锁严格 FIFO。",
        }, {
            "title": "16-volatile与Java内存模型JMM_2026-07-27",
            "content": "volatile 是 Java 提供的轻量级同步机制：可见性——写 volatile 变量插入内存屏障"
                       "强制刷新主内存；有序性——禁止指令重排序。volatile 不保证原子性，复合操作"
                       "仍需 synchronized 或原子类。",
        }],
        "sufficient": False,
        "keywords": ["零拷贝", "Zero-Copy"],
        "category": "kafka",
        "note": "完全不沾边：问 Kafka 零拷贝却检索到 AQS/volatile 文档",
    },
    {
        "question": "什么是CAP定理？在分布式系统设计中如何权衡？",
        "documents": [{
            "title": "10-Redis持久化机制_2026-07-20",
            "content": "Redis 两种持久化：RDB 定时生成全量快照（fork 子进程写临时文件），恢复快但"
                       "可能丢最后一次快照后的数据；AOF 追加写命令日志，默认 everysec 每秒 fsync。",
        }, {
            "title": "6-Java线程池ThreadPoolExecutor核心参数与工作原理_2026-07-16",
            "content": "ThreadPoolExecutor 核心参数：corePoolSize、maximumPoolSize、workQueue、"
                       "keepAliveTime、threadFactory、handler。任务提交先复用核心线程，队列满后"
                       "扩容到最大线程数，仍满则走拒绝策略。",
        }],
        "sufficient": False,
        "keywords": ["CAP"],
        "category": "comprehensive",
        "note": "完全不沾边：问 CAP 定理却检索到 Redis/线程池文档",
    },
    {
        "question": "CompletableFuture和Future有什么区别？如何使用CompletableFuture进行异步编排？",
        "documents": [{
            "title": "16-volatile与Java内存模型JMM_2026-07-27",
            "content": "volatile 是 Java 提供的轻量级同步机制，两大作用：1）可见性——写 volatile "
                       "变量插入内存屏障强制刷新主内存；2）有序性——禁止指令重排序。volatile "
                       "不保证原子性，复合操作仍需 synchronized 或原子类。",
        }, {
            "title": "16-volatile与Java内存模型JMM_2026-07-27 > 板块2 > 双检锁示例",
            "content": "双重检查锁（Double-Checked Locking）单例：外层判空避免无谓加锁，内层"
                       "synchronized 保证只实例化一次，instance 字段声明为 volatile 防止指令重排。",
        }],
        "sufficient": False,
        "keywords": ["CompletableFuture", "Future"],
        "category": "java_concurrency",
        "note": "主题错位：文档讲 volatile，不含 Future 任何内容",
    },
    {
        "question": "synchronized的底层实现原理是什么？锁升级过程是怎样的？",
        "documents": [{
            "title": "5-Kafka消息可靠性与高吞吐设计_2026-07-15",
            "content": "Kafka 可靠性核心是 ISR（In-Sync Replicas）机制：每个 Partition 有多个副本，"
                       "Leader 负责读写，Follower 拉取同步，超过 replica.lag.time.max.ms 未同步即被"
                       "踢出 ISR。生产者端 acks=all 配合 min.insync.replicas=2 保证确认。",
        }, {
            "title": "7-KVCache与注意力优化_2026-07-17",
            "content": "KV Cache 是 LLM 推理优化：自回归生成时缓存历史 token 的 K/V 向量，避免每步"
                       "重复计算，显存换算力的经典手段。配合 PagedAttention 减少显存碎片。",
        }],
        "sufficient": False,
        "keywords": ["synchronized", "锁升级"],
        "category": "java_concurrency",
        "note": "完全不沾边：问 synchronized 却检索到 Kafka/KV Cache 文档",
    },
]


def load_sufficiency_dataset() -> list[dict]:
    """加载充分性标注集，校验结构

    Returns:
        样本列表，每项含 question / documents / sufficient（可含 keywords/category/note）

    Raises:
        ValueError: 样本 < 10、question 为空、documents 为空、sufficient 非 bool、两类不齐全
    """
    data = SUFFICIENCY_DATASET
    if len(data) < 10:
        raise ValueError(f"充分性评测集过小：需 ≥ 10 条，当前 {len(data)}")
    for item in data:
        if not item.get("question", "").strip():
            raise ValueError(f"充分性评测集存在空 question: {item}")
        if not item.get("documents"):
            raise ValueError(f"充分性评测集存在空 documents: {item.get('question', '')[:30]}")
        if not isinstance(item.get("sufficient"), bool):
            raise ValueError(f"sufficient 须为 bool: {item.get('question', '')[:30]}")
    counts = {s: sum(1 for i in data if i["sufficient"] == s) for s in (True, False)}
    if not all(counts.values()):
        raise ValueError(f"充分性评测集缺少类别（充分/不充分须都有）: {counts}")
    return data


def heuristic_judge(query: str, documents: list[dict], keywords: list[str]) -> bool:
    """fixture 启发式判断器：关键词命中判定充分性（确定性，不依赖 LLM/DB）

    问题核心术语（keywords）任一出现在文档内容中 → 充分；否则不充分。
    仅用于 fixture 模式演示评测管线，不代表真实判断能力。

    Args:
        query: 用户问题
        documents: 检索文档列表
        keywords: 该问题核心术语（样本标注字段）

    Returns:
        True=充分 / False=不充分
    """
    if not documents:
        return False
    text = "".join(d.get("content", "") for d in documents)
    return any(kw in text for kw in keywords)


async def judge_sufficiency(query: str, documents: list[dict]) -> bool:
    """真实模式：调用 reflector.check_sufficiency 判断充分性

    返回结构兼容 check_sufficiency 契约（sufficient/reason/rewritten_query）；
    失败降级由 reflector 内部兜底（默认充分，防死循环）。

    Args:
        query: 用户问题
        documents: 检索文档列表

    Returns:
        True=充分 / False=不充分
    """
    result = await reflector.check_sufficiency(query, documents)
    return bool(result.get("sufficient", True))


def extract_sufficiency_label(item: dict) -> bool:
    """取样本标注标签（bool），统一数据访问"""
    return item["sufficient"]


def label_str(sufficient: bool) -> str:
    """bool 标签 → 语义字符串（混淆矩阵/报告用）"""
    return "sufficient" if sufficient else "insufficient"


async def run_eval(judge=None, dataset=None) -> tuple[dict, list[dict], list[dict]]:
    """执行一次充分性评估

    Args:
        judge: 判断协程 (query, documents) -> bool 充分性；默认走 reflector（真实模式）
        dataset: 评测样本列表；默认 load_sufficiency_dataset()

    Returns:
        (scores, per_question, skipped)
        - scores: accuracy + 混淆矩阵 + per-class 指标 + 统计（含 insufficient_recall 重点项）
        - per_question: 每题明细（label/predicted/correct）
        - skipped: 判断失败的样本记录
    """
    items = dataset if dataset is not None else load_sufficiency_dataset()
    judge_fn = judge if judge is not None else judge_sufficiency
    per_question: list[dict] = []
    skipped: list[dict] = []

    for i, item in enumerate(items):
        question = item["question"]
        documents = item["documents"]
        label = extract_sufficiency_label(item)
        try:
            predicted = await judge_fn(question, documents)
        except Exception as e:
            logger.error("[%d/%d] 充分性判断失败: %s — %s", i + 1, len(items), question[:40], e)
            skipped.append({"question": question, "label": label, "reason": f"error: {e}"})
            continue
        per_question.append({
            "question": question,
            "label": label,
            "predicted": bool(predicted),
            "correct": bool(predicted) == label,
            "category": item.get("category", ""),
        })

    conf = compute_confusion_matrix(
        [label_str(q["label"]) for q in per_question],
        [label_str(q["predicted"]) for q in per_question],
    )
    # 重点项：不充分类的 Recall（漏判"不充分"→ 基于无关文档硬答，最致命）
    insufficient_recall = conf["per_class"].get("insufficient", {}).get("recall", 0.0)
    scores = {
        "dataset_size": len(items),
        "evaluated": len(per_question),
        "skipped": len(skipped),
        "accuracy": conf["accuracy"],
        "confusion_matrix": conf["matrix"],
        "per_class": conf["per_class"],
        "classes": conf["classes"],
        "insufficient_recall": insufficient_recall,
    }
    return scores, per_question, skipped


async def record_eval_run(scores: dict, per_question: list[dict]) -> tuple[str, int]:
    """版本化落库：git_commit + rag_config 快照 + eval_type='sufficiency'

    Args:
        scores: 整体指标 dict
        per_question: 每题明细 list

    Returns:
        (commit, saved_id)；落库失败 saved_id=0（save_eval_run 内部已捕获并警告）
    """
    commit = get_git_commit()
    config_snapshot = await load_rag_config()
    saved_id = await save_eval_run(
        eval_type="sufficiency",
        git_commit=commit,
        config_snapshot=config_snapshot,
        scores=scores,
        per_question=per_question,
    )
    return commit, saved_id


def print_report(scores: dict, per_question: list[dict], skipped: list[dict],
                 saved_id: int, commit: str, fixture: bool) -> None:
    """打印评估报告到控制台：混淆矩阵 + per-class 指标 + 误判明细

    重点标出 insufficient Recall（漏判"不充分"最致命）。
    """
    classes = scores["classes"]
    print("\n" + "=" * 60)
    print("Golden Sufficiency Eval" + ("  [fixture 模式：启发式判断器，非真实指标]" if fixture else ""))
    print("=" * 60)
    print(f"Dataset: {scores['dataset_size']} samples | Evaluated: {scores['evaluated']} | Skipped: {scores['skipped']}")
    print("-" * 60)
    print(f"Accuracy: {scores['accuracy']:.4f}")
    print(f"==> 重点: insufficient Recall = {scores['insufficient_recall']:.4f} "
          f"（漏判'不充分' → 基于无关文档硬答，最致命）")
    print("-" * 60)
    print("Confusion Matrix (row=label, col=predicted):")
    print(f"{'':<14}" + "".join(f"{c[:10]:>14}" for c in classes))
    for label in classes:
        row = scores["confusion_matrix"][label]
        print(f"{label:<14}" + "".join(f"{row[pred]:>14}" for pred in classes))
    print("-" * 60)
    print("Per-Class Precision/Recall/F1:")
    for cls in classes:
        pc = scores["per_class"][cls]
        print(f"  {cls:<14} precision={pc['precision']:.4f} recall={pc['recall']:.4f} "
              f"f1={pc['f1']:.4f} support={pc['support']}")
    mis = [q for q in per_question if not q["correct"]]
    if mis:
        print("-" * 60)
        print(f"Misclassified ({len(mis)}):")
        for q in mis:
            print(f"  label={'sufficient' if q['label'] else 'insufficient':<14} "
                  f"-> {'sufficient' if q['predicted'] else 'insufficient':<14} | {q['question'][:40]}")
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
    parser = argparse.ArgumentParser(description="Golden sufficiency 评测：充分性判断混淆矩阵 + 版本化回归")
    parser.add_argument("--fixture", action="store_true",
                        help="fixture 模式：启发式判断器（确定性，不依赖 LLM/DB），仅演示管线")
    parser.add_argument("--no-save", action="store_true", help="不记录 eval_runs 表")
    args = parser.parse_args()

    load_sufficiency_dataset()

    if args.fixture:
        async def _fixture_judge(query, documents):
            item = next(i for i in SUFFICIENCY_DATASET if i["question"] == query)
            return heuristic_judge(query, documents, item["keywords"])
        judge = _fixture_judge
    else:
        judge = None  # 默认走 reflector（真实模式）

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
