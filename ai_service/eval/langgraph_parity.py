"""
LangGraph 复刻等价性 + 转正对比脚本（module-091 / 阶段 E）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.langgraph_parity --mode fixture                  # WP-A 等价性（零 LLM/DB，秒级）
    python -m eval.langgraph_parity --mode real --sample 12 --pass-k 1  # WP-B 真实对比（交替执行）

两条被比对环路（同一评测集 eval/agent_tasks.json 36 条，同 --sample 子集）:
    hand      = agent/react.py::react_loop（手写 while 循环，生产主路径）
    langgraph = agent/langgraph_react.py::langgraph_react_loop（StateGraph 实验端点）

WP-A（fixture，确定性零 LLM）：假 LLM 按 item["expected_tools"] 逐次回放工具
计划、假工具返回固定文本（复用 066 的 _FixtureClient / _fixture_registry），
两侧各跑一遍后逐条比对四维：
    ① 工具名序列 actual_names 逐字相同 ② tool_count 相同 ③ 最终 answer 相同
    ④ 判定器四规则 coverage / no_extra / args_ok / pass 相同
不一致条目**逐条列出 id + 两侧序列**（AC-2，不允许静默通过）。

WP-B（real）：同子集同 pass_k，两条环路**交替执行**（hand, langgraph 逐任务
交替，AC-7）摊平供应商限流时段影响；三层指标复用 066 纯函数（compute_scores /
_sum_usage / _percentile）；两次 save_agent_eval_run 落库，config_snapshot 附
{"loop": ..., "module": "091"}（JSONB 列，零新表零 ALTER）。任务运行异常记入
fail_reason 并在报告中列出，禁止静默重跑掩盖（AC-12）。

红线：本脚本只读生产代码；fixture 的 mock 仅替换 LLM 客户端（不 patch 生产
行为），agent/ src/ main.py 零 diff。
"""
import argparse
import asyncio
import logging
import random
import time
from unittest import mock

from src import observability
from src.config import settings
from agent.react import ReactContext, _build_messages, react_loop
from agent.langgraph_react import langgraph_react_loop
from eval import agent_tasks as at

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("langgraph_parity")

LOOP_HAND = "hand"
LOOP_LANGGRAPH = "langgraph"

# fixture 假 LLM 补丁点：两个模块各自 import LLMFactory，patch 目标字符串不同
#（AC-6 要求不得混用；注：两处解析到同一个 llm.client.LLMFactory 类对象，
# 见 parity-report §环境——单测仍按字符串断言，防未来任一模块改为本地工厂）
_LLM_PATCH = {
    LOOP_HAND: "agent.react.LLMFactory.get_client",
    LOOP_LANGGRAPH: "agent.langgraph_react.LLMFactory.get_client",
}
_LOOP_FN = {LOOP_HAND: react_loop, LOOP_LANGGRAPH: langgraph_react_loop}

# 评测匿名身份（memory 只读不写，测后按 066 先例清理）
EVAL_IDENTITY = "eval-091-anon"


# ==================== WP-A：fixture 等价性 ====================


def _fixture_plan(item: dict) -> list:
    """fixture 工具计划：expected_tools 逐次回放（参数取 args_schema 必填占位）

    Args:
        item: 任务条目

    Returns:
        [(工具名, args dict), ...]
    """
    return [(name, at._args_for(name)) for name in item["expected_tools"]]


def _fixture_answer(item: dict, is_last: bool) -> str:
    """fixture 答案（确定性）：末轮=answer_points 拼接，中间轮=占位文本

    Args:
        item: 任务条目
        is_last: 是否多轮任务的最后一轮

    Returns:
        答案文本
    """
    return "、".join(item["answer_points"]) + "。" if is_last else "（fixture 中间轮回答）"


async def run_round(loop: str, ctx: ReactContext, item: dict,
                    is_last: bool, real: bool) -> list:
    """单轮运行一条环路，产出事件列表

    Args:
        loop: LOOP_HAND 或 LOOP_LANGGRAPH
        ctx: 本轮 ReactContext
        item: 任务条目（fixture 计划来源）
        is_last: 是否最后一轮（fixture 答案仅末轮含全部 answer_points）
        real: True=真实 LLM + 真实工具；False=fixture 假 LLM + 假工具

    Returns:
        事件列表（token / tool_call / tool_result / done）
    """
    fn = _LOOP_FN[loop]
    messages = _build_messages(ctx)
    budget = settings.max_agent_tools
    if real:
        return [evt async for evt in fn(ctx, messages, budget)]
    client = at._FixtureClient(_fixture_plan(item), _fixture_answer(item, is_last))
    with mock.patch(_LLM_PATCH[loop], return_value=client):
        return [evt async for evt in fn(ctx, messages, budget,
                                        tools=at._fixture_registry())]


async def run_side(loop: str, item: dict, k: int, real: bool) -> dict:
    """一条任务 × 一条环路的一次运行（多轮按 task 数组逐轮推进）

    Args:
        loop: LOOP_HAND 或 LOOP_LANGGRAPH
        item: 任务条目
        k: 第 k 次独立尝试（同时进入 trace_id，供 grounding 读回）
        real: True=真实模式（真实 LLM/工具/DB + grounding）；False=fixture

    Returns:
        逐任务明细 dict（判定器四规则 + actual_names + tokens + fail_reason）
    """
    trace_id = f"eval-{item['id']}-{loop}-{k}"
    observability.init_request(trace_id)
    rounds = item["task"] if isinstance(item["task"], list) else [item["task"]]
    calls: list[dict] = []
    answer = ""
    error = None
    t0 = time.perf_counter()
    try:
        history: list[dict] = []
        for q in rounds:
            ctx = ReactContext(q, identity=EVAL_IDENTITY, history=history)
            for evt in await run_round(loop, ctx, item, q == rounds[-1], real):
                if evt["type"] == "tool_call":
                    calls.append({"name": evt["name"], "args": evt["args"]})
                elif evt["type"] == "done":
                    answer = evt.get("answer", "") or ""
            history.append({"role": "user", "content": q})
            if answer:
                history.append({"role": "assistant", "content": answer})
    except Exception as e:  # 单任务失败不中断其余（AC-12：记 fail_reason，不重跑）
        error = f"{type(e).__name__}: {e}"
        logger.error("[%s/%s] 任务运行失败: %s", item["id"], loop, error)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    tokens = at._sum_usage(observability.get_request_stats().get("usage", {}))
    grounding = None if not real else await at._load_grounding(trace_id)
    return at._build_task_result(item, calls, answer, duration_ms, tokens,
                                 grounding, error)


def compare_pair(item: dict, hand: dict, lg: dict) -> dict:
    """两条环路逐任务四维比对（确定性，不用 LLM 判答案好坏）

    Args:
        item: 任务条目
        hand: 手写侧 run_side 结果
        lg: LangGraph 侧 run_side 结果

    Returns:
        {"task_id", "equal", "diffs", "hand", "langgraph"}；diffs 空=等价
    """
    diffs = []
    if hand["actual_names"] != lg["actual_names"]:
        diffs.append(f"工具序列 hand={hand['actual_names']} langgraph={lg['actual_names']}")
    if hand["tool_count"] != lg["tool_count"]:
        diffs.append(f"工具次数 hand={hand['tool_count']} langgraph={lg['tool_count']}")
    if hand["answer"] != lg["answer"]:
        diffs.append(f"答案 hand={hand['answer']!r} langgraph={lg['answer']!r}")
    for field in ("coverage", "no_extra", "args_ok", "pass"):
        if hand[field] != lg[field]:
            diffs.append(f"{field} hand={hand[field]} langgraph={lg[field]}")
    return {"task_id": item["id"], "equal": not diffs, "diffs": diffs,
            "hand": hand, "langgraph": lg}


def equivalence_rate(pairs: list) -> float:
    """等价率 = 等价条数 / 总条数（4 位小数）

    Args:
        pairs: compare_pair 结果列表

    Returns:
        等价率（空列表 → 0.0）
    """
    if not pairs:
        return 0.0
    return round(sum(1 for p in pairs if p["equal"]) / len(pairs), 4)


async def run_equivalence(tasks: list) -> list:
    """WP-A：全任务集 fixture 等价性比对（零 LLM 零 DB）

    Args:
        tasks: 任务列表

    Returns:
        逐条比对结果 list
    """
    pairs = []
    for i, item in enumerate(tasks):
        hand = await run_side(LOOP_HAND, item, 1, real=False)
        lg = await run_side(LOOP_LANGGRAPH, item, 1, real=False)
        pairs.append(compare_pair(item, hand, lg))
        logger.info("[%d/%d] %s equal=%s", i + 1, len(tasks),
                    item["id"], pairs[-1]["equal"])
    return pairs


def print_equivalence(pairs: list) -> None:
    """打印等价性逐条表 + 不一致明细（不静默通过）

    Args:
        pairs: compare_pair 结果列表

    Returns:
        None（打印到 stdout）
    """
    print("\n" + "=" * 64)
    print("LangGraph Parity — fixture 等价性（零 LLM，确定性）")
    print("=" * 64)
    for p in pairs:
        flag = "OK  " if p["equal"] else "DIFF"
        print(f"  {flag} {p['task_id']:<8} hand={p['hand']['actual_names']}"
              f" lg={p['langgraph']['actual_names']}"
              f" pass={p['hand']['pass']}/{p['langgraph']['pass']}")
    diffs = [p for p in pairs if not p["equal"]]
    rate = equivalence_rate(pairs)
    print("-" * 64)
    print(f"等价率: {rate:.4f}  ({len(pairs) - len(diffs)}/{len(pairs)})")
    if diffs:
        print(f"不一致条目（{len(diffs)} 个，逐条归因，不静默通过）:")
        for p in diffs:
            print(f"  {p['task_id']}:")
            for d in p["diffs"]:
                print(f"      - {d}")
    else:
        print("不一致条目：无（全部四维逐字等价）")
    print("=" * 64 + "\n")


# ==================== WP-B：真实模式对比 ====================


async def run_real(tasks: list, pass_k: int) -> dict:
    """WP-B：两条环路交替执行（hand, langgraph 逐任务交替，AC-7 摊平限流时段）

    Args:
        tasks: 任务列表
        pass_k: 每任务独立尝试次数（k 次全成功才算 pass）

    Returns:
        {loop: per_question list}
    """
    out = {LOOP_HAND: [], LOOP_LANGGRAPH: []}
    for i, item in enumerate(tasks):
        for loop in (LOOP_HAND, LOOP_LANGGRAPH):
            runs = [await run_side(loop, item, k, real=True)
                    for k in range(1, pass_k + 1)]
            first = dict(runs[0])
            first["pass"] = all(r["pass"] for r in runs)  # pass^k 口径
            out[loop].append(first)
            logger.info("[%d/%d] %s %-9s pass=%s tools=%s", i + 1, len(tasks),
                        item["id"], loop, first["pass"], first["actual_names"])
    return out


def score_run(loop: str, per_question: list, pass_k: int,
              dataset_size: int) -> dict:
    """聚合单条环路的三层指标（复用 066 compute_scores 纯函数）

    Args:
        loop: LOOP_HAND 或 LOOP_LANGGRAPH
        per_question: 逐任务明细
        pass_k: 尝试次数
        dataset_size: 任务集规模

    Returns:
        scores dict（含 loop/module/tokens_total 供报告对账）
    """
    scores = at.compute_scores(per_question)
    scores.update({
        "loop": loop,
        "module": "091",
        "pass_k": pass_k,
        "dataset_size": dataset_size,
        "tokens_total": sum(t.get("tokens") or 0 for t in per_question),
        "tool_steps_total": sum(t["tool_count"] for t in per_question),
    })
    return scores


def build_config_snapshot(base: dict, loop: str) -> dict:
    """构造 config_snapshot：rag_config 快照 + 环路标识（AC-9 落库区分用）

    Args:
        base: load_rag_config() 产出的配置快照
        loop: LOOP_HAND 或 LOOP_LANGGRAPH

    Returns:
        附加 {"loop", "module"} 后的快照 dict（JSONB 列，零新表零 ALTER）
    """
    snapshot = dict(base or {})
    snapshot.update({"loop": loop, "module": "091"})
    return snapshot


def print_real(results: dict, scores: dict) -> None:
    """打印真实模式对比表 + 运行期失败清单（不掩盖）

    Args:
        results: {loop: per_question list}
        scores: {loop: scores dict}

    Returns:
        None（打印到 stdout）
    """
    print("\n" + "=" * 64)
    print("LangGraph Parity — real 模式对比（单次采样，非置信区间）")
    print("=" * 64)
    print(f"{'指标':<16}{'hand':>22}{'langgraph':>22}")
    print("-" * 64)
    rows = (("pass^1", "pass_1"), ("工具正确率", "tool_correct_rate"),
            ("平均步数", "avg_tool_count"), ("平均 token", "avg_tokens"),
            ("tokens 总量", "tokens_total"), ("P50 ms", "p50_ms"),
            ("P95 ms", "p95_ms"), ("Grounding", "grounding"))
    for label, key in rows:
        a = scores[LOOP_HAND].get(key)
        b = scores[LOOP_LANGGRAPH].get(key)
        fa = f"{a:.4f}" if isinstance(a, float) else str(a)
        fb = f"{b:.4f}" if isinstance(b, float) else str(b)
        print(f"{label:<16}{fa:>22}{fb:>22}")
    print("-" * 64)
    for loop in (LOOP_HAND, LOOP_LANGGRAPH):
        failed = [t for t in results[loop] if t.get("fail_reason")]
        if failed:
            print(f"[{loop}] 运行期失败 {len(failed)} 条（如实列出，不重跑掩盖）:")
            for t in failed:
                print(f"    {t['task_id']}: {t['fail_reason']}")
    print("=" * 64 + "\n")


# ==================== CLI ====================


async def main() -> None:
    """CLI 入口：fixture 等价性 / real 真实对比

    Args:
        None（参数经 argparse 读取：--mode/--sample/--pass-k/--limit/--no-save）

    Returns:
        None
    """
    parser = argparse.ArgumentParser(
        description="LangGraph 复刻等价性 + 转正对比（module-091）")
    parser.add_argument("--mode", choices=["fixture", "real"], default="fixture",
                        help="fixture=零 LLM 等价性；real=真实模式对比")
    parser.add_argument("--sample", type=int, default=12,
                        help="抽样条数（0=全量；固定种子 42 可复现）")
    parser.add_argument("--pass-k", type=int, default=1,
                        help="每任务独立尝试次数，k 次全成功才算过")
    parser.add_argument("--limit", type=int, default=0, help="冒烟：只跑前 N 条")
    parser.add_argument("--no-save", action="store_true",
                        help="real 模式不落 agent_eval_runs")
    args = parser.parse_args()

    pass_k = max(1, int(args.pass_k or 1))
    # fixture 零成本且 AC-1 要求全量 36 条 → 强制忽略 --sample；real 默认 12
    if args.mode == "fixture":
        args.sample = 0
    tasks = at.load_agent_tasks()  # 先校验任务集（结构非法立即报错退出）
    if args.limit:
        tasks = tasks[:max(0, args.limit)]
    if args.sample:
        tasks = random.Random(42).sample(tasks, min(args.sample, len(tasks)))
        tasks.sort(key=lambda t: t["id"])
    logger.info("任务集 %d 条（mode=%s pass_k=%d）", len(tasks), args.mode, pass_k)

    if args.mode == "fixture":
        settings.tool_call_logs_enabled = False  # fixture 零 DB：不落 tool_call_logs
        print_equivalence(await run_equivalence(tasks))
        return

    try:  # real 模式依赖 tool_call_logs（grounding 数据来源）：脚本独立运行
        from src.database import ensure_tool_call_logs_table
        await ensure_tool_call_logs_table()
    except Exception as e:
        logger.warning("tool_call_logs 建表失败（grounding 将标 None）: %s", e)

    results = await run_real(tasks, pass_k)
    scores = {loop: score_run(loop, results[loop], pass_k, len(tasks))
              for loop in (LOOP_HAND, LOOP_LANGGRAPH)}
    print_real(results, scores)

    if args.no_save:
        print("[--no-save] 跳过 agent_eval_runs 落库")
    else:
        from eval.golden.golden_retrieval import get_git_commit, load_rag_config
        commit = get_git_commit()
        for loop in (LOOP_HAND, LOOP_LANGGRAPH):
            snapshot = build_config_snapshot(await load_rag_config(), loop)
            run_id = await at.save_agent_eval_run(commit, snapshot, scores[loop],
                                                  results[loop])
            print(f"Saved agent_eval_runs id={run_id} loop={loop} commit={commit[:8]}")
    await at._cleanup_eval_memory()  # 测后清理评测身份记忆残留（066 先例，防御性）


if __name__ == "__main__":
    asyncio.run(main())
