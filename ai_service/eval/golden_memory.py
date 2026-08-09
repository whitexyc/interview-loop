"""
Golden 记忆提取评测 — extract_facts P/R/F1 + eval_runs 版本化回归（module-046 WP3）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.golden_memory                    # LLM 提取 + P/R/F1 + 落库
    python -m eval.golden_memory --fixture          # 关键词启发式（不依赖 LLM/DB）
    python -m eval.golden_memory --no-save          # 纯跑分，不写 eval_runs

指标定义:
    Precision  预测事实中与标注匹配的比例（含"不应提取"样本：空标注却被预测 → FP，
               防过度提取——宁可少提取也不编造）
    Recall     标注事实中被预测召回的比例（漏提取量化）
    F1         精确率与召回率的调和平均

标注集:
    内嵌 MEMORY_GOLDEN_DATASET（≥20 条）：{dialogue: 多轮对话文本, facts: [应提取
    事实], keywords: [fixture 关键词]}。含 facts=[] 的"不应提取"样本防过度提取
    （一次性问答/寒暄/通用知识——不是用户记忆，提取器应返回空）。

提取器契约:
    run_eval(extractor=None, dataset=None) — extractor 为 async callable
    (item) -> list[str]（预测事实列表）。默认走 extract_facts 公共入口
    （rag.memory_extractor.extract_facts，签名 query/answer/history，由
    dialogue 末轮 user/assistant 映射）；--fixture 走关键词启发式。

版本化回归:
    每次运行记录 eval_runs 表（eval_type='memory_extraction'，git_commit +
    rag_config 快照 + scores/per_question），对齐 eval/golden_retrieval.py
    的落库模式。

降级策略:
    - 单条提取异常 → 跳过并记录错误，其余继续
    - extract_facts 内部失败返回 []（本身降级），不影响整体运行
    - 数据库不可用 → 分数记录失败打印警告，评估仍完成
"""
import argparse
import asyncio
import logging
import re
import sys

from eval.golden_retrieval import get_git_commit, load_rag_config, save_eval_run
from rag.memory_extractor import extract_facts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("golden_memory")

# 记忆提取标注集：{dialogue: 多轮对话, facts: [应提取事实], keywords: [fixture 关键词]}
# 前 22 条为"应提取"（facts 非空），后 6 条为"不应提取"（facts=[]，防过度提取）。
MEMORY_GOLDEN_DATASET: list[dict] = [
    # ---- 应提取（用户偏好/职业事实/任务状态/明确"记住"）----
    {"dialogue": "用户: 我比较喜欢简洁的回答，不要太啰嗦\n助手: 好的，我会尽量保持回答简洁。",
     "facts": ["用户偏好简洁的回答风格"], "keywords": ["简洁"]},
    {"dialogue": "用户: 我在一家公司做 Java 后端开发，已经三年了\n助手: 三年 Java 后端经验，了解了。",
     "facts": ["用户是 Java 后端开发，有三年经验"], "keywords": ["Java"]},
    {"dialogue": "用户: 我平时主要用 Spring Boot 和 Redis 这套技术栈\n助手: Spring Boot + Redis，很主流的组合。",
     "facts": ["用户常用技术栈是 Spring Boot 和 Redis"], "keywords": ["Spring Boot"]},
    {"dialogue": "用户: 我最近在准备大厂面试，主要是 JVM 和分布式方向\n助手: 祝你面试顺利！可以随时问我相关知识。",
     "facts": ["用户正在准备大厂面试，方向是 JVM 和分布式"], "keywords": ["大厂面试"]},
    {"dialogue": "用户: 我在做 Agentic RAG 个人知识库问答系统\n助手: 这个项目很有意思，是 Agent 加 RAG 的组合。",
     "facts": ["用户在开发 Agentic RAG 个人知识库问答系统"], "keywords": ["Agentic RAG"]},
    {"dialogue": "用户: 我的简历已经更新完了，最近在投递\n助手: 好的，简历更新完毕，开始投递阶段。",
     "facts": ["用户简历已更新完成，正在投递"], "keywords": ["简历"]},
    {"dialogue": "用户: 这周末我计划系统地学一下 Kafka\n助手: 周末学 Kafka，需要资料可以找我。",
     "facts": ["用户计划这周末学习 Kafka"], "keywords": ["Kafka"]},
    {"dialogue": "用户: 请记住，我喜欢喝美式咖啡，不加糖\n助手: 记住了，美式咖啡不加糖。",
     "facts": ["用户喜欢喝美式咖啡且不加糖"], "keywords": ["美式咖啡"]},
    {"dialogue": "用户: 请记住我的偏好，回答时用中文就行\n助手: 好的，以后用中文回答。",
     "facts": ["用户偏好中文回答"], "keywords": ["中文"]},
    {"dialogue": "用户: 我每天都会写代码到晚上十点\n助手: 很自律的作息，晚上十点收工。",
     "facts": ["用户每天写代码到晚上十点"], "keywords": ["晚上十点"]},
    {"dialogue": "用户: 我在 8 人的技术团队里负责检索模块\n助手: 8 人团队负责检索模块，明白了。",
     "facts": ["用户所在团队 8 人，负责检索模块"], "keywords": ["检索模块"]},
    {"dialogue": "用户: 答应你的事我会做到，明天给你面试复盘文档\n助手: 期待你的复盘文档。",
     "facts": ["用户承诺明天提供面试复盘文档"], "keywords": ["复盘文档"]},
    {"dialogue": "用户: 我业余喜欢摄影，周末常去扫街\n助手: 摄影是个很好的爱好。",
     "facts": ["用户业余爱好摄影"], "keywords": ["摄影"]},
    {"dialogue": "用户: 我准备明年往架构师方向发展\n助手: 架构师方向，很好的职业规划。",
     "facts": ["用户计划明年向架构师方向发展"], "keywords": ["架构师"]},
    {"dialogue": "用户: 我不太喜欢被人叫全名，叫网名就行\n助手: 好的，以后称呼你的网名。",
     "facts": ["用户偏好被称呼网名而非全名"], "keywords": ["网名"]},
    {"dialogue": "用户: 我写代码习惯用 VS Code\n助手: VS Code 是个好选择。",
     "facts": ["用户编程工具偏好 VS Code"], "keywords": ["VS Code"]},
    {"dialogue": "用户: 我平时早上会先看一小时技术文章再开工\n助手: 早上阅读技术文章，很好的习惯。",
     "facts": ["用户习惯早上阅读一小时技术文章"], "keywords": ["技术文章"]},
    {"dialogue": "用户: 我准备系统学一遍 Redis 源码，作为下一阶段目标\n助手: Redis 源码学习是个硬骨头，加油。",
     "facts": ["用户下一阶段目标系统学习 Redis 源码"], "keywords": ["Redis 源码"]},
    {"dialogue": "用户: 我通过知乎和 B 站学习技术比较多\n助手: 知乎和 B 站确实是好的学习渠道。",
     "facts": ["用户主要通过知乎和 B 站学习技术"], "keywords": ["知乎"]},
    {"dialogue": "用户: 我正在跟进一个开源项目，主要贡献文档和测试\n助手: 开源贡献文档和测试很有价值。",
     "facts": ["用户正在参与开源项目，贡献文档和测试"], "keywords": ["开源"]},
    {"dialogue": "用户: 请记住，我面试方向偏中间件，尤其消息队列\n助手: 记住了，中间件方向，主攻消息队列。",
     "facts": ["用户面试方向偏中间件尤其是消息队列"], "keywords": ["消息队列"]},
    {"dialogue": "用户: 我的习惯是每周四做技术分享\n助手: 每周四技术分享，很有节奏。",
     "facts": ["用户每周四做技术分享"], "keywords": ["每周四"]},
    # ---- 不应提取（facts=[]：一次性问答/寒暄/通用知识——不是用户记忆）----
    {"dialogue": "用户: G1 垃圾收集器是什么？\n助手: G1 是 JDK9+ 默认的垃圾收集器，基于 Region 分区……",
     "facts": [], "keywords": []},
    {"dialogue": "用户: 你好呀\n助手: 你好！有什么可以帮你的吗？",
     "facts": [], "keywords": []},
    {"dialogue": "用户: 现在几点了？\n助手: 抱歉，我无法获取实时时间。",
     "facts": [], "keywords": []},
    {"dialogue": "用户: HashMap 和 ConcurrentHashMap 有什么区别？\n助手: HashMap 线程不安全，ConcurrentHashMap 用分段锁/红黑树……",
     "facts": [], "keywords": []},
    {"dialogue": "用户: 帮我搜一下 Nacos 的配置中心用法\n助手: Nacos 配置中心支持动态刷新，用法如下……",
     "facts": [], "keywords": []},
    {"dialogue": "用户: 谢谢你的帮助，再见！\n助手: 不客气，随时找我。",
     "facts": [], "keywords": []},
]


def load_memory_golden() -> list[dict]:
    """加载记忆提取标注集，校验结构

    Returns:
        样本列表，每项含 dialogue（多轮对话文本）/ facts（应提取事实列表）

    Raises:
        ValueError: 样本 < 20、dialogue 为空、facts 非字符串列表、
                   或缺少"不应提取"（facts=[]）样本
    """
    data = MEMORY_GOLDEN_DATASET
    if len(data) < 20:
        raise ValueError(f"记忆提取标注集过小：需 ≥ 20 条，当前 {len(data)}")
    for item in data:
        dialogue = str(item.get("dialogue") or "").strip()
        if not dialogue:
            raise ValueError(f"标注集存在空 dialogue: {item}")
        facts = item.get("facts")
        if not isinstance(facts, list) or not all(
            isinstance(f, str) and f.strip() for f in facts
        ):
            raise ValueError(f"facts 须为字符串列表: {dialogue[:30]}")
    if not any(not d["facts"] for d in data):
        raise ValueError("标注集缺少'不应提取'样本（facts=[]），无法防过度提取评测")
    return data


def _parse_dialogue(dialogue: str) -> list[dict]:
    """把多轮对话文本解析为 {"role", "content"} 轮次列表（无效行跳过）

    Args:
        dialogue: "用户: ...\n助手: ..." 多行文本

    Returns:
        轮次列表；无有效轮次返回 []
    """
    turns = []
    for line in (dialogue or "").splitlines():
        line = line.strip()
        if line.startswith("用户:"):
            turns.append({"role": "user", "content": line[len("用户:"):].strip()})
        elif line.startswith("助手:"):
            turns.append({"role": "assistant", "content": line[len("助手:"):].strip()})
    return [t for t in turns if t["content"]]


def _dialogue_to_extract_inputs(dialogue: str):
    """dialogue 多轮文本 → (query, answer, history)（对齐 extract_facts 公共入口）

    取最后一个 user 轮为 query、其后最近一个 assistant 轮为 answer、
    query 之前轮次为 history。无 assistant 回答（对话未完成）→ 返回 None
    （extract_facts 空 answer 恒返回 []，样本无意义 → 跳过）。

    Args:
        dialogue: 多轮对话文本

    Returns:
        (query, answer, history) 三元组；无法映射返回 None
    """
    turns = _parse_dialogue(dialogue)
    user_idx = [i for i, t in enumerate(turns) if t["role"] == "user"]
    if not user_idx:
        return None
    last_user = user_idx[-1]
    answer = ""
    for i in range(last_user + 1, len(turns)):
        if turns[i]["role"] == "assistant":
            answer = turns[i]["content"]
            break
    if not answer:
        return None
    history = turns[:last_user]
    return turns[last_user]["content"], answer, history


async def _extract_with_llm(item: dict) -> list[str]:
    """LLM 模式提取器：调用 extract_facts 公共入口，返回预测事实 content 列表

    extract_facts(query, answer, history) 为公共接口（rag.memory_extractor），
    dialogue 经 _dialogue_to_extract_inputs 映射；提取失败 extract_facts 内部
    降级返回 []（不影响整体运行）。

    Args:
        item: 标注样本（dialogue）

    Returns:
        预测事实 content 列表（可能为空）
    """
    inputs = _dialogue_to_extract_inputs(item.get("dialogue") or "")
    if inputs is None:
        return []
    query, answer, history = inputs
    facts = await extract_facts(query, answer, history)
    return [f.get("content", "") for f in facts if f.get("content", "").strip()]


def fixture_extract(item: dict) -> list[str]:
    """fixture 关键词启发式提取（确定性，不依赖 LLM/DB）

    返回对话文本中含任一标注关键词的句子（按 。！？ 切句）。无关键词 → 空列表
    （"不应提取"样本在 fixture 下同样不提取）。仅用于演示评测管线，不代表
    真实提取能力。

    Args:
        item: 标注样本（dialogue / keywords）

    Returns:
        命中关键词的句子列表
    """
    keywords = [k for k in (item.get("keywords") or []) if k]
    if not keywords:
        return []
    text = item.get("dialogue") or ""
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if s.strip()]
    return [s for s in sentences if any(k in s for k in keywords)]


def _norm_fact(s: str) -> str:
    """事实归一化：去空白/常见标点 + 小写（匹配容忍措辞差异）"""
    return re.sub(r"[\s，。！？、；：\"\"''（）()【】《》~～]+", "", s or "").lower()


def _fact_match(pred: str, gold: str) -> bool:
    """预测事实与标注事实是否匹配：归一化后互相包含（任一方向）"""
    np_, ng = _norm_fact(pred), _norm_fact(gold)
    return bool(np_ and ng) and (ng in np_ or np_ in ng)


def _match_sample(predicted: list[str], golden: list[str]) -> tuple[int, int, int]:
    """单样本匹配（贪心：每条标注至多匹配一条预测）→ (tp, fp, fn)

    Args:
        predicted: 提取器预测事实列表
        golden: 标注事实列表

    Returns:
        (tp, fp, fn)：tp=预测且标注命中；fp=预测但标注未命中（含"不应提取"
        样本被预测——过度提取）；fn=标注但未被预测（漏提取）
    """
    used = [False] * len(golden)
    tp = 0
    for p in predicted:
        hit = False
        for i, g in enumerate(golden):
            if not used[i] and _fact_match(p, g):
                used[i] = True
                hit = True
                break
        if hit:
            tp += 1
    fp = len(predicted) - tp
    fn = sum(1 for u in used if not u)
    return tp, fp, fn


def compute_prf(rows: list[dict]) -> dict:
    """汇总多样本 tp/fp/fn → Precision / Recall / F1（micro 口径）

    Args:
        rows: 每样本 {"tp", "fp", "fn"} 列表

    Returns:
        {"precision", "recall", "f1", "tp", "fp", "fn"}；无样本/分母为 0 → 0.0
    """
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
    }


async def run_eval(extractor=None, dataset=None) -> tuple[dict, list[dict], list[dict]]:
    """执行一次记忆提取评估

    Args:
        extractor: 提取器 async callable (item) -> list[str]；默认走
            extract_facts 公共入口（_extract_with_llm）
        dataset: 标注样本列表；默认 load_memory_golden()

    Returns:
        (scores, per_question, skipped)
        - scores: P/R/F1 + tp/fp/fn + 过度提取样本数 + 统计
        - per_question: 每样本明细（golden/predicted/tp/fp/fn/over_extraction）
        - skipped: 提取异常跳过的样本记录
    """
    items = dataset if dataset is not None else load_memory_golden()
    extract = extractor if extractor is not None else _extract_with_llm
    per_question: list[dict] = []
    skipped: list[dict] = []

    for i, item in enumerate(items):
        try:
            predicted = await extract(item)
        except Exception as e:
            logger.error("[%d/%d] 记忆提取失败: %s — %s",
                         i + 1, len(items), (item.get("dialogue") or "")[:30], e)
            skipped.append({
                "dialogue": (item.get("dialogue") or "")[:40],
                "reason": f"error: {e}",
            })
            continue
        golden = [g for g in (item.get("facts") or []) if g]
        tp, fp, fn = _match_sample(predicted, golden)
        per_question.append({
            "dialogue": (item.get("dialogue") or "")[:40],
            "golden": golden,
            "predicted": predicted,
            "tp": tp, "fp": fp, "fn": fn,
            "over_extraction": bool(predicted) and not golden,
        })

    prf = compute_prf(per_question)
    scores = {
        "dataset_size": len(items),
        "evaluated": len(per_question),
        "skipped": len(skipped),
        "over_extraction_count": sum(1 for q in per_question if q["over_extraction"]),
        **prf,
    }
    return scores, per_question, skipped


async def record_eval_run(scores: dict, per_question: list[dict]) -> tuple[str, int]:
    """版本化落库：git_commit + rag_config 快照 + eval_type='memory_extraction'

    Args:
        scores: 整体指标 dict
        per_question: 每样本明细 list

    Returns:
        (commit, saved_id)；落库失败 saved_id=0（save_eval_run 内部已捕获并警告）
    """
    commit = get_git_commit()
    config_snapshot = await load_rag_config()
    saved_id = await save_eval_run(
        eval_type="memory_extraction",
        git_commit=commit,
        config_snapshot=config_snapshot,
        scores=scores,
        per_question=per_question,
    )
    return commit, saved_id


def print_report(scores: dict, per_question: list[dict], skipped: list[dict],
                 saved_id: int, commit: str, fixture: bool = False) -> None:
    """打印评估报告到控制台"""
    print("\n" + "=" * 60)
    print("Golden Memory Extraction Eval" + ("  [fixture 模式：关键词启发式，非真实指标]" if fixture else ""))
    print("=" * 60)
    print(f"Dataset: {scores['dataset_size']} items | Evaluated: {scores['evaluated']} | Skipped: {scores['skipped']}")
    print(f"Over-extraction samples: {scores['over_extraction_count']} (空标注被预测 = 过度提取)")
    print("-" * 60)
    print(f"Precision: {scores['precision']:.4f}   (tp={scores['tp']}, fp={scores['fp']})")
    print(f"Recall:    {scores['recall']:.4f}   (tp={scores['tp']}, fn={scores['fn']})")
    print(f"F1:        {scores['f1']:.4f}")
    print("-" * 60)
    if per_question:
        print("Per-Item (first 12):")
        for q in per_question[:12]:
            tag = "OVER" if q["over_extraction"] else "ok  "
            print(f"  [{tag}] tp={q['tp']} fp={q['fp']} fn={q['fn']} | {q['dialogue'][:38]}")
    if skipped:
        print("-" * 60)
        print(f"Skipped ({len(skipped)}):")
        for s in skipped:
            print(f"  [{s['reason'][:30]}] {s['dialogue'][:44]}")
    print("=" * 60)
    if saved_id:
        print(f"Saved to eval_runs (id={saved_id}, commit={commit[:8]})")
    else:
        print("Not saved to eval_runs")
    print()


async def main() -> None:
    """评测脚本入口"""
    parser = argparse.ArgumentParser(
        description="Golden 记忆提取评测：extract_facts P/R/F1 + 版本化回归")
    parser.add_argument("--fixture", action="store_true",
                        help="fixture 模式：关键词启发式提取（确定性，不依赖 LLM/DB），仅演示管线")
    parser.add_argument("--no-save", action="store_true", help="不记录 eval_runs 表")
    args = parser.parse_args()

    load_memory_golden()
    if args.fixture:
        async def _fixture_extract(item: dict) -> list[str]:
            return fixture_extract(item)
        scores, per_question, skipped = await run_eval(extractor=_fixture_extract)
        fixture = True
    else:
        scores, per_question, skipped = await run_eval()
        fixture = False

    saved_id = 0
    commit = ""
    if not args.no_save:
        commit, saved_id = await record_eval_run(scores, per_question)
    print_report(scores, per_question, skipped, saved_id, commit, fixture=fixture)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
