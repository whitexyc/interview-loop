"""
module-093 WP-C 对拍任务集 — 3 个固定长对话剧本 × 18 轮连续追问
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

设计（plan §2 WP-C）：
  - 3 个固定剧本（线程池 / RAG / MySQL 索引），每个剧本 1 条初始提问 +
    18 轮连续追问，模拟真实"深挖"长对话（历史随轮次累积，触发压缩）。
  - 每轮带 answer_points（2-3 个关键技术词），复用 066 判定器口径
    （outcome_pass 的子串命中判定，expected_tools=[] 时退化为纯要点命中）。
  - 剧本固定入 git（可复现）：对拍三臂（off / clearing / clearing+compaction）
    逐臂跑同一剧本，臂间唯一差异 = ctx_mode（D4 公平）。

文件约束（plan §5）：ctx_tasks.py + ctx_parity.py 合计 AST ≤ 350（数据脚本
放宽），无网络/无模型依赖的纯数据 + 轻量加载器。
"""
from pathlib import Path

CTX_TASKS_PATH = Path(__file__).resolve().parent / "ctx_tasks.json"

# 3 个固定剧本（入 git 可复现）：initial = 首条 user 提问；
# rounds = 18 条连续追问，每条 q + answer_points（要点关键词子串判定用）。
CTX_SCRIPTS: list[dict] = [
    {
        "id": "G1-threadpool-deepdive",
        "topic": "Java 线程池工作原理深挖",
        "initial": "请详细讲解 Java 线程池的核心工作原理，从提交任务到执行的完整流程",
        "rounds": [
            {"q": "核心线程数和最大线程数有什么区别？",
             "answer_points": ["corePoolSize", "maximumPoolSize"]},
            {"q": "任务队列有哪些类型，分别适合什么场景？",
             "answer_points": ["LinkedBlockingQueue", "SynchronousQueue"]},
            {"q": "线程池的拒绝策略有哪几种？",
             "answer_points": ["AbortPolicy", "CallerRunsPolicy", "DiscardPolicy"]},
            {"q": "keepAliveTime 的作用是什么？",
             "answer_points": ["keepAliveTime", "非核心线程"]},
            {"q": "execute 和 submit 方法有什么区别？",
             "answer_points": ["execute", "submit", "Future"]},
            {"q": "线程池是如何创建线程的？",
             "answer_points": ["ThreadFactory"]},
            {"q": "饱和状态下 CallerRunsPolicy 怎么工作？",
             "answer_points": ["CallerRunsPolicy", "调用者线程"]},
            {"q": "如何监控线程池的运行状态？",
             "answer_points": ["getActiveCount", "getCompletedTaskCount"]},
            {"q": "FixedThreadPool 有什么隐患？",
             "answer_points": ["FixedThreadPool", "无界队列", "OOM"]},
            {"q": "为什么不建议用 Executors 创建线程池？",
             "answer_points": ["Executors", "OOM", "资源耗尽"]},
            {"q": "如何合理配置线程池大小？",
             "answer_points": ["CPU 密集型", "IO 密集型"]},
            {"q": "prestartCoreThread 有什么用？",
             "answer_points": ["prestartCoreThread", "预热"]},
            {"q": "线程池里的线程执行任务抛异常了会怎么样？",
             "answer_points": ["afterExecute", "线程终止"]},
            {"q": "allowCoreThreadTimeOut 是什么含义？",
             "answer_points": ["allowCoreThreadTimeOut", "核心线程回收"]},
            {"q": "任务执行超时怎么处理？",
             "answer_points": ["Future", "get", "超时"]},
            {"q": "如何优雅关闭线程池？",
             "answer_points": ["shutdown", "shutdownNow"]},
            {"q": "shutdown 和 shutdownNow 的区别？",
             "answer_points": ["shutdown", "shutdownNow", "中断"]},
            {"q": "如何排查线程池任务堆积问题？",
             "answer_points": ["任务堆积", "队列长度", "活跃线程"]},
        ],
    },
    {
        "id": "G2-rag-deepdive",
        "topic": "RAG 检索增强生成原理深挖",
        "initial": "请详细讲解 RAG（检索增强生成）的核心原理与典型架构",
        "rounds": [
            {"q": "RAG 的基本流程分哪几步？",
             "answer_points": ["检索", "增强", "生成"]},
            {"q": "文档切分有哪些策略？",
             "answer_points": ["固定长度", "语义切分", "重叠"]},
            {"q": "稠密向量和稀疏向量检索有什么区别？",
             "answer_points": ["稠密向量", "稀疏向量", "语义"]},
            {"q": "embedding 模型怎么选？",
             "answer_points": ["embedding", "句向量", "余弦相似度"]},
            {"q": "向量数据库的作用是什么？",
             "answer_points": ["向量数据库", "ANN", "相似度检索"]},
            {"q": "重排序（rerank）有什么用？",
             "answer_points": ["rerank", "重排序", "精排"]},
            {"q": "混合检索是什么？",
             "answer_points": ["混合检索", "BM25", "向量"]},
            {"q": "查询改写（query rewriting）有什么价值？",
             "answer_points": ["查询改写", "召回率"]},
            {"q": "上下文窗口超限怎么处理？",
             "answer_points": ["上下文窗口", "截断", "压缩"]},
            {"q": "如何评估 RAG 效果？",
             "answer_points": ["RAGAS", "faithfulness", "相关性"]},
            {"q": "RAG 有哪些典型失败模式？",
             "answer_points": ["幻觉", "检索缺失", "上下文污染"]},
            {"q": "如何让检索更精准？",
             "answer_points": ["元数据过滤", "HyDE"]},
            {"q": "多轮对话下 RAG 如何保持上下文？",
             "answer_points": ["多轮", "历史压缩"]},
            {"q": "大模型如何融合检索到的内容？",
             "answer_points": ["prompt", "上下文拼接", "引用"]},
            {"q": "小模型能做 RAG 吗？",
             "answer_points": ["小模型", "检索增强"]},
            {"q": "企业知识库 RAG 有哪些挑战？",
             "answer_points": ["权限", "时效性", "更新"]},
            {"q": "GraphRAG 是什么？",
             "answer_points": ["GraphRAG", "知识图谱", "实体"]},
            {"q": "RAG 和微调怎么选？",
             "answer_points": ["RAG", "微调", "知识更新"]},
        ],
    },
    {
        "id": "G3-mysql-index-deepdive",
        "topic": "MySQL 索引与查询优化深挖",
        "initial": "请详细讲解 MySQL 索引的工作原理与查询优化实战",
        "rounds": [
            {"q": "聚簇索引和非聚簇索引有什么区别？",
             "answer_points": ["聚簇索引", "非聚簇索引", "B+树"]},
            {"q": "为什么用 B+ 树而不是 B 树？",
             "answer_points": ["B+树", "叶子节点", "范围查询"]},
            {"q": "什么是回表？",
             "answer_points": ["回表", "二级索引", "主键"]},
            {"q": "什么是覆盖索引？",
             "answer_points": ["覆盖索引", "减少回表"]},
            {"q": "最左前缀原则是什么？",
             "answer_points": ["最左前缀", "联合索引"]},
            {"q": "索引为什么会失效？",
             "answer_points": ["索引失效", "函数", "隐式转换"]},
            {"q": "怎么看 SQL 执行计划？",
             "answer_points": ["EXPLAIN", "type", "rows"]},
            {"q": "慢查询怎么排查？",
             "answer_points": ["慢查询日志", "索引", "全表扫描"]},
            {"q": "联合索引的顺序怎么排？",
             "answer_points": ["联合索引", "区分度", "最左前缀"]},
            {"q": "什么是索引下推？",
             "answer_points": ["索引下推", "ICP", "过滤"]},
            {"q": "事务隔离级别有哪些？",
             "answer_points": ["读已提交", "可重复读", "串行化"]},
            {"q": "什么是幻读，怎么解决？",
             "answer_points": ["幻读", "间隙锁", "MVCC"]},
            {"q": "MVCC 是怎么实现的？",
             "answer_points": ["MVCC", "undo log", "版本链"]},
            {"q": "死锁怎么排查？",
             "answer_points": ["死锁", "等待图", "锁"]},
            {"q": "主从复制的原理是什么？",
             "answer_points": ["binlog", "主从复制", "relay log"]},
            {"q": "什么是 buffer pool？",
             "answer_points": ["buffer pool", "缓冲池", "页"]},
            {"q": "大表加字段会锁表吗？",
             "answer_points": ["DDL", "Online DDL", "锁"]},
            {"q": "怎么设计高性能索引？",
             "answer_points": ["高区分度", "覆盖索引", "避免冗余"]},
        ],
    },
]


def load_ctx_scripts() -> list[dict]:
    """返回固定对拍剧本集（内存常量，结构自检）

    校验：恰 3 个剧本、每剧本 18 轮、每轮含非空 q 与 1-3 个 answer_points。

    Returns:
        CTX_SCRIPTS 副本（调用方随意 mutate）

    Raises:
        ValueError: 结构非法（剧本数/轮数/字段）
    """
    if len(CTX_SCRIPTS) != 3:
        raise ValueError(f"需 3 个剧本，当前 {len(CTX_SCRIPTS)}")
    for s in CTX_SCRIPTS:
        if len(s.get("rounds") or []) != 18:
            raise ValueError(f"剧本 {s.get('id')} 需 18 轮，当前 {len(s.get('rounds') or [])}")
        for i, r in enumerate(s["rounds"]):
            pts = r.get("answer_points") or []
            if not r.get("q") or not (1 <= len(pts) <= 3) or not all(pts):
                raise ValueError(f"剧本 {s.get('id')} 第 {i} 轮结构非法: {r}")
    return [dict(s) for s in CTX_SCRIPTS]


def flatten_rounds(scripts: list[dict]) -> list[dict]:
    """展平为逐轮判定条目（复用 066 outcome_pass 口径）

    每条目 id = {script_id}#r{n}；expected_tools=[]（深挖对话工具覆盖不计入
    质量，考核纯要点命中）；answer_points 透传；附 meta 供落库。

    Args:
        scripts: load_ctx_scripts() 结果

    Returns:
        逐轮条目列表（含 meta: script_id / round_idx / is_initial）
    """
    out: list[dict] = []
    for s in scripts:
        out.append({
            "id": f"{s['id']}#r0", "task": s["initial"], "expected_tools": [],
            "answer_points": [], "meta": {"script_id": s["id"], "round_idx": 0,
                                          "is_initial": True}})
        for i, r in enumerate(s["rounds"], start=1):
            out.append({
                "id": f"{s['id']}#r{i}", "task": r["q"], "expected_tools": [],
                "answer_points": list(r["answer_points"]),
                "meta": {"script_id": s["id"], "round_idx": i,
                         "is_initial": False}})
    return out
