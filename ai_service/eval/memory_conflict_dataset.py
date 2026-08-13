"""
记忆冲突 NLI 评测（module-061 / ADR-0007 P1 评测闭环，先度量用数据决定启用）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.memory_conflict_dataset                  # 真实 mDeBERTa baseline
    python -m eval.memory_conflict_dataset --fixture        # 关键词启发式（确定性，不依赖模型）
    python -m eval.memory_conflict_dataset --no-save        # 纯跑分不写 eval_runs
    python -m eval.memory_conflict_dataset --limit 10       # 冒烟（前 N 条）

评测口径（记忆级场景，比 claim_vs_doc 更聚焦——短句偏好/事件级）：
    样本 = (premise 旧记忆, hypothesis 新事实)，人工标注三分类 verdict：
      entailment      新事实与旧记忆一致（同义/被蕴含）
      neutral         新事实与旧记忆无关（不同主题）
      contradiction   新事实与旧记忆冲突（改口/迁移/过时/升级换代）
    达标线（建议值）：contradiction Recall≥0.8 且 Precision≥0.8 —— 写路径
    冲突消解只在判定矛盾时标 SUPERSEDED，漏判（Recall 低）=旧记忆仍拼接共存
    （无害降级），误判（Precision 低）=正常记忆被标过期（有害）——Precision
    是更硬的约束，故双门槛同等 ≥0.8。

指标:
    accuracy_3class（三分类，参考）+ contradiction P/R/F1（micro，主指标）。

降级:
    - 真实模式模型缺失 → 明确报错（require_nli_model 同款），不静默通过
    - 单条推理异常 → 跳过记录并打印，其余继续
    - 数据库不可用 → eval_runs 落库失败打印警告，评估仍完成（--no-save 跳过）

诚实边界:
    1. 记忆冲突样本为人工构造（非真实用户改口数据），方向性验证；标注由
       Developer 完成，非多人独立标注。
    2. mDeBERTa 多语言训练，中文是泛化表现；输入截断 512 token。
    3. 本批为记忆级场景（短句/偏好/事件级），与历史 claim_vs_doc 矛盾判别
       （module-054/057 kappa<0.7）口径不同——是否更聚焦以数据说话。
    4. 达标才启用（PW_MEMORY_CONFLICT 默认 false）；不达标如实标注"未达门槛"。
"""
import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

VERDICTS = ("entailment", "neutral", "contradiction")
GATE_CONTRADICTION_RECALL = 0.8
GATE_CONTRADICTION_PRECISION = 0.8

# 记忆冲突标注集：{scenario, premise 旧记忆, hypothesis 新事实, verdict}
# 前 20 条为 contradiction（改口 10 + 迁移 4 + 过时 3 + 升级冲突 3），
# 后 10 条为正例/中性（entailment 5 + neutral 5）——防止 Recall 虚高与过度标矛盾。
MEMORY_CONFLICT_DATASET: list[dict] = [
    # ---- 改口类（10）：用户改变偏好/习惯，旧说法与最新说法互斥 ----
    {"scenario": "改口", "premise": "用户喜欢喝美式咖啡，每天早上都要来一杯",
     "hypothesis": "用户现在讨厌咖啡了，改喝茶", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户偏好用 Python 写代码",
     "hypothesis": "用户现在主要用 Java 写后端代码", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户喜欢简洁的回答风格",
     "hypothesis": "用户觉得回答太短没细节，希望更详细", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户不喜欢吃辣",
     "hypothesis": "用户最近迷上了麻辣火锅", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户习惯晚睡，凌晨一点才睡",
     "hypothesis": "用户改作息了，现在晚上十一点就睡", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户使用 VS Code 写代码",
     "hypothesis": "用户换成了 IntelliJ IDEA", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户目前在 A 公司工作",
     "hypothesis": "用户已经离职去了 B 公司", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户面试方向是 JVM 和并发",
     "hypothesis": "用户改投算法方向了", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户每天工作八小时",
     "hypothesis": "用户现在每天只工作四小时", "verdict": "contradiction"},
    {"scenario": "改口", "premise": "用户习惯用网名称呼自己",
     "hypothesis": "用户让大家叫他的全名", "verdict": "contradiction"},
    # ---- 迁移类（4）：技术栈/部署/存储切换，旧状态被新状态取代 ----
    {"scenario": "迁移", "premise": "用户的数据库用的是 MySQL",
     "hypothesis": "用户把数据库换成了 PostgreSQL", "verdict": "contradiction"},
    {"scenario": "迁移", "premise": "用户主要使用 Maven 构建项目",
     "hypothesis": "用户项目改用了 Gradle 构建", "verdict": "contradiction"},
    {"scenario": "迁移", "premise": "用户用 Redis 做缓存",
     "hypothesis": "用户缓存换成了本地 Caffeine", "verdict": "contradiction"},
    {"scenario": "迁移", "premise": "用户使用 Docker 部署服务",
     "hypothesis": "用户部署改成了 K8s 集群", "verdict": "contradiction"},
    # ---- 过时类（3）：旧版本被新版本取代 ----
    {"scenario": "过时", "premise": "用户在使用 Spring Boot 2.x",
     "hypothesis": "用户已经升级到 Spring Boot 3.x", "verdict": "contradiction"},
    {"scenario": "过时", "premise": "用户用 Java 8 开发",
     "hypothesis": "用户项目迁移到了 Java 21", "verdict": "contradiction"},
    {"scenario": "过时", "premise": "用户的 Node 版本是 16",
     "hypothesis": "用户升级到了 Node 20", "verdict": "contradiction"},
    # ---- 升级冲突类（3）：短期层新事实 vs 长期层旧记忆 ----
    {"scenario": "升级冲突", "premise": "用户长期记忆：喜欢的语言是 Go",
     "hypothesis": "短期新事实：用户现在主要写 Rust", "verdict": "contradiction"},
    {"scenario": "升级冲突", "premise": "长期记忆：用户计划学习 Kafka",
     "hypothesis": "短期新事实：用户放弃 Kafka 改学 Pulsar", "verdict": "contradiction"},
    {"scenario": "升级冲突", "premise": "长期记忆：用户常用技术栈是 Spring 全家桶",
     "hypothesis": "短期新事实：用户转型做前端 React", "verdict": "contradiction"},
    # ---- 正例（5）：新事实与旧记忆一致（entailment，防过度标矛盾）----
    {"scenario": "正例", "premise": "用户喜欢喝美式咖啡",
     "hypothesis": "用户喜欢咖啡", "verdict": "entailment"},
    {"scenario": "正例", "premise": "用户是 Java 后端开发",
     "hypothesis": "用户主要做后端开发", "verdict": "entailment"},
    {"scenario": "正例", "premise": "用户住在北京",
     "hypothesis": "用户现在还是住在北京", "verdict": "entailment"},
    {"scenario": "正例", "premise": "用户每周四做技术分享",
     "hypothesis": "用户的分享日定在周四", "verdict": "entailment"},
    {"scenario": "正例", "premise": "用户用 VS Code",
     "hypothesis": "用户使用 Visual Studio Code 写代码", "verdict": "entailment"},
    # ---- 中性（5）：新事实与旧记忆无关（neutral，防"不同主题也算矛盾"）----
    {"scenario": "中性", "premise": "用户喜欢喝咖啡",
     "hypothesis": "用户养了一只猫", "verdict": "neutral"},
    {"scenario": "中性", "premise": "用户在准备大厂面试",
     "hypothesis": "用户最近在学做饭", "verdict": "neutral"},
    {"scenario": "中性", "premise": "用户偏好中文回答",
     "hypothesis": "用户本周要去成都出差", "verdict": "neutral"},
    {"scenario": "中性", "premise": "用户习惯早上阅读技术文章",
     "hypothesis": "用户的手机是华为的", "verdict": "neutral"},
    {"scenario": "中性", "premise": "用户通过 B 站学习技术",
     "hypothesis": "用户喜欢跑步锻炼", "verdict": "neutral"},
]


def load_memory_conflict_dataset() -> list[dict]:
    """加载并校验标注集结构

    Raises:
        ValueError: 样本 < 20、缺 premise/hypothesis/verdict、verdict 非法、
                    contradiction < 15、缺 entailment/neutral 对照
    """
    data = MEMORY_CONFLICT_DATASET
    if len(data) < 20:
        raise ValueError(f"记忆冲突标注集过小：需 ≥ 20 条，当前 {len(data)}")
    for item in data:
        for key in ("premise", "hypothesis", "verdict"):
            if not str(item.get(key) or "").strip():
                raise ValueError(f"样本缺 {key}: {item}")
        if item["verdict"] not in VERDICTS:
            raise ValueError(f"verdict 须为 {VERDICTS}: {item.get('premise', '')[:30]}")
    contradictions = sum(1 for i in data if i["verdict"] == "contradiction")
    if contradictions < 15:
        raise ValueError(f"contradiction 样本需 ≥ 15 条，当前 {contradictions}")
    if not any(i["verdict"] == "entailment" for i in data):
        raise ValueError("缺少正例对照（entailment）样本")
    if not any(i["verdict"] == "neutral" for i in data):
        raise ValueError("缺少中性对照（neutral）样本")
    return data


# ──────────────────────────────────────────────────────────────
# 指标（纯函数，可单测）
# ──────────────────────────────────────────────────────────────

def contradiction_metrics(human3: list[str], pred3: list[str]) -> dict:
    """contradiction P/R/F1（micro 口径）+ 三分类 accuracy

    tp = 预测 contradiction 且人工 contradiction；fp = 预测 contradiction 但
    人工非 contradiction（正常记忆被误标过期——Precision 是更硬的约束）；
    fn = 人工 contradiction 但预测非（漏判——无害降级为拼接共存）。

    Args:
        human3: 人工三分类标注列表
        pred3: 模型预测三分类列表

    Returns:
        {"accuracy_3class", "precision", "recall", "f1", "tp", "fp", "fn"}
    """
    tp = fp = fn = 0
    ok = 0
    for h, p in zip(human3, pred3):
        if h == p:
            ok += 1
        if h == "contradiction" and p == "contradiction":
            tp += 1
        elif p == "contradiction" and h != "contradiction":
            fp += 1
        elif h == "contradiction" and p != "contradiction":
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "accuracy_3class": round(ok / len(human3), 4) if human3 else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
    }


# ──────────────────────────────────────────────────────────────
# 判定器
# ──────────────────────────────────────────────────────────────

def fixture_judge(premise: str, hypothesis: str) -> str:
    """fixture 关键词启发式判定（确定性，不依赖模型，仅演示评测管线）

    冲突信号词（换成/改成/搬到/升级/讨厌/改投/迷上/辞职/搬去 等）在
    hypothesis 中且与 premise 同主题（共享非空词）→ contradiction；
    无冲突词 → neutral（保守，不判 entailment）。不代表真实判别能力。
    """
    _CONFLICT_WORDS = ("换成", "改成", "改成了", "搬到", "搬去", "换成了",
                       "升级到", "讨厌", "改投", "迷上", "辞职", "现在", "已经",
                       "改学", "转型", "改作息")
    if any(w in hypothesis for w in _CONFLICT_WORDS):
        return "contradiction"
    return "neutral"


async def real_judge(premise: str, hypothesis: str) -> str:
    """真实 mDeBERTa 判定（复用生产封装 rag.memory.nli_judge 单一来源）"""
    from rag.memory.nli_judge import nli_judge
    result = await nli_judge.predict(premise, hypothesis)
    if result is None:
        raise RuntimeError("NLI 不可用（None）")
    return result


async def clf_judge(premise: str, hypothesis: str) -> str:
    """module-062 WP4 分类模型判定（bge-m3+LR 二分类 → 三分类口径）

    二分类输出 contradiction / non_conflict → 映射三分类：contradiction 保持，
    non_conflict 归入 neutral（非矛盾；entailment 的 3 类准确率会偏低，但
    contradiction P/R/F1 主指标不受影响——达标线只看 Precision）。不可用 → 抛错。
    """
    from rag.memory.memory_conflict_clf import memory_conflict_clf
    loaded = await memory_conflict_clf.load()
    if not loaded:
        raise RuntimeError("memory_conflict_clf 模型缺失/加载失败（先跑 train_memory_conflict_clf.py）")
    verdict = await memory_conflict_clf.predict(premise, hypothesis)
    if verdict is None:
        raise RuntimeError("CLF 判定不可用（None）")
    return verdict if verdict == "contradiction" else "neutral"


# ──────────────────────────────────────────────────────────────
# 运行
# ──────────────────────────────────────────────────────────────

async def run_eval(judge=None, dataset=None, limit: int | None = None) -> tuple:
    """执行一次记忆冲突评估

    Args:
        judge: 判定器 async callable (premise, hypothesis) -> verdict
        dataset: 标注样本列表；默认 load_memory_conflict_dataset()
        limit: 只评估前 N 条（冒烟）

    Returns:
        (scores, per_question, skipped)
    """
    items = dataset if dataset is not None else load_memory_conflict_dataset()
    if limit:
        items = items[:limit]
    judge = judge if judge is not None else real_judge
    human3 = [i["verdict"] for i in items]
    pred3: list[str] = []
    per_question: list[dict] = []
    skipped: list[dict] = []

    for i, item in enumerate(items):
        try:
            pred = await judge(item["premise"], item["hypothesis"])
            if pred not in VERDICTS:
                raise ValueError(f"判定器返回非法 verdict: {pred}")
        except Exception as e:
            logger.error("[%d/%d] NLI 判定失败: %s — %s",
                         i + 1, len(items), item["premise"][:30], e)
            skipped.append({"premise": item["premise"][:40], "reason": f"error: {e}"})
            pred3.append("neutral")  # 失败样本按 neutral 计数（不污染 contradiction 统计）
            per_question.append({
                "premise": item["premise"][:40], "hypothesis": item["hypothesis"][:40],
                "label": item["verdict"], "predicted": "neutral", "skipped": True,
            })
            continue
        pred3.append(pred)
        per_question.append({
            "premise": item["premise"][:40], "hypothesis": item["hypothesis"][:40],
            "label": item["verdict"], "predicted": pred, "skipped": False,
        })

    scores = contradiction_metrics(human3, pred3)
    scores["dataset_size"] = len(items)
    scores["evaluated"] = len([q for q in per_question if not q["skipped"]])
    scores["skipped"] = len(skipped)
    return scores, per_question, skipped


def gate_passed(scores: dict) -> bool:
    """达标线判定：contradiction Recall≥0.8 且 Precision≥0.8"""
    return (scores.get("recall", 0.0) >= GATE_CONTRADICTION_RECALL
            and scores.get("precision", 0.0) >= GATE_CONTRADICTION_PRECISION)


async def record_eval_run(scores: dict, per_question: list[dict]) -> tuple[str, int]:
    """版本化落库 eval_runs（eval_type='memory_conflict'）"""
    from eval.golden_retrieval import get_git_commit, load_rag_config, save_eval_run
    commit = get_git_commit()
    config_snapshot = await load_rag_config()
    saved_id = await save_eval_run(
        eval_type="memory_conflict",
        git_commit=commit,
        config_snapshot=config_snapshot,
        scores={**scores,
                "gate_contradiction_recall": GATE_CONTRADICTION_RECALL,
                "gate_contradiction_precision": GATE_CONTRADICTION_PRECISION,
                "gate_passed": gate_passed(scores)},
        per_question=per_question,
    )
    return commit, saved_id


def print_report(scores: dict, per_question: list[dict], skipped: list[dict],
                 saved_id: int, commit: str, fixture: bool = False) -> None:
    print("\n" + "=" * 60)
    print("Memory Conflict NLI Eval" + ("  [fixture 模式：关键词启发式，非真实指标]" if fixture else ""))
    print("=" * 60)
    print(f"Dataset: {scores['dataset_size']} | Evaluated: {scores['evaluated']} "
          f"| Skipped: {scores['skipped']}")
    print(f"Accuracy(3类): {scores['accuracy_3class']:.4f}")
    print(f"Contradiction Precision: {scores['precision']:.4f}   "
          f"(tp={scores['tp']}, fp={scores['fp']})")
    print(f"Contradiction Recall:    {scores['recall']:.4f}   (fn={scores['fn']})")
    print(f"Contradiction F1:        {scores['f1']:.4f}")
    passed = gate_passed(scores)
    print("-" * 60)
    print(f"达标线: contradiction Recall≥{GATE_CONTRADICTION_RECALL} 且 "
          f"Precision≥{GATE_CONTRADICTION_PRECISION}  "
          f"→ {'✅ 达标' if passed else '❌ 未达门槛（默认关，不预设成功）'}")
    if per_question:
        print("Per-Item (first 12):")
        for q in per_question[:12]:
            tag = "SKIP" if q["skipped"] else ("ok " if q["label"] == q["predicted"] else "MIS")
            print(f"  [{tag}] 人工={q['label']:<13} 预测={q['predicted']:<13} {q['premise'][:30]}")
    if skipped:
        print(f"Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  [{s['reason'][:30]}] {s['premise'][:44]}")
    print("=" * 60)
    if saved_id:
        print(f"Saved to eval_runs (id={saved_id}, commit={commit[:8]})")
    else:
        print("Not saved to eval_runs")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="记忆冲突 NLI 评测：mDeBERTa/分类模型 contradiction P/R/F1 + 达标判定")
    parser.add_argument("--fixture", action="store_true",
                        help="fixture 模式：关键词启发式（确定性，不依赖模型），仅演示管线")
    parser.add_argument("--judge", choices=["nli", "clf"], default="nli",
                        help="判定器：nli（module-061 mDeBERTa，默认）/ clf（module-062 bge-m3+LR 分类模型）")
    parser.add_argument("--no-save", action="store_true", help="不记录 eval_runs 表")
    parser.add_argument("--limit", type=int, default=None, help="只评估前 N 条（冒烟）")
    args = parser.parse_args()

    load_memory_conflict_dataset()
    if args.fixture:
        async def _fixture(p: str, h: str) -> str:
            return fixture_judge(p, h)
        judge = _fixture
    elif args.judge == "clf":
        judge = clf_judge
    else:
        judge = real_judge

    scores, per_question, skipped = await run_eval(judge=judge, limit=args.limit)

    saved_id = 0
    commit = ""
    if not args.no_save:
        try:
            commit, saved_id = await record_eval_run(scores, per_question)
        except Exception as e:
            logger.warning("eval_runs 落库失败（不中断）: %s", e)
    print_report(scores, per_question, skipped, saved_id, commit, fixture=args.fixture)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
