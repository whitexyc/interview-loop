"""
LangGraph 对比评测深化 — 多轮采样 + 分阶段遥测 + 冷启动（module-092）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    python -m eval.parity_telemetry --mode real --repeat 3          # 正式 3 轮
    python -m eval.parity_telemetry --mode real --repeat 1 --sample 2 --limit 2 --no-save

在 091（eval/langgraph_parity.py，单次采样对比，结论=维持自研）基础上的数据深化：

WP-A 多轮采样：--repeat N（默认 3）。抽样集合固定（091 同款种子 42 抽样，
    跨轮可比），轮间顺序重洗（seed=1000+i，防顺序效应）；每指标聚合
    mean±std/min/max + 逐轮明细；每轮两条 save_agent_eval_run，
    config_snapshot 注入 {"repeat","repeat_of","module":"092"}（JSONB，零新表）。

WP-B 分阶段遥测（ADR-0020 StateGraph 开销归因钥匙）：
    LLM 轮次 = timing proxy 包装 client（patch 环路 LLMFactory.get_client →
        代理逐次计时）+ mock.patch("llm.client._record_usage") 包装原函数捕获
        逐次 (label, prompt, completion)——chat_with_tools 返回体不含 usage，
        _record_usage 是逐次 token 的唯一干净入口，全在 eval 层零生产 diff。
        proxy 计时 chat/chat_with_tools/generate，并按"是否在工具执行窗口内"
        分桶：工具内调用（如 generate_answer 工具内部的生成、re_search 内部的
        图抽取）其耗时已包含在 tool_call_logs 工具时长中，单独归桶防止与工具
        段双重计数；环路级调用（ReAct 推理轮次 + 预算耗尽兜底生成）计入 LLM 段。
        工具窗口判定 = _tool_guard 包装 execute_tool_with_log（两环路各自模块
        引用都 patch；不能按栈帧判定——工具超时 wait_for 新建 Task 会切断帧链）。
    工具执行 = tool_call_logs 按 trace_id 读回，按 tool_name 分组；
    编排开销 = 总 duration_ms − ΣLLM − Σ工具（残差定义）→ 两环路差值即
        StateGraph 调度开销归因。闭合校验 = ΣLLM+Σ工具 是否溢出总时长窗口
        （残差 <0 即闭合失败，逐条如实列出）。

WP-C 冷启动：①独立子进程分别计时 import agent.react 与
    agent.langgraph_react（后者含模块级 build_react_graph 编译），差值=框架
    编译冷启动；②每轮第 1 条任务记 cold、其余 warm，cold/warm 中位比值 ×
    2 环路；公平性声明见报告（本地模型加载 bge-m3/reranker 为两环路共同
    成本不计入差异；LLM 首次握手同为一次）。

红线：本脚本只读生产代码；拦截全部在 eval 层（mock.patch 包装且原行为先
执行/透传），agent/ src/ main.py 零 diff。pass_k 固定 1（AC 命令表口径）。
"""
import argparse
import asyncio
import logging
import random
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from unittest import mock

import llm.client as llm_client
from sqlalchemy import text

import agent.react as _agent_react
import agent.langgraph_react as _agent_lg
from eval import agent_tasks as at, langgraph_parity as lp
from src.database import async_session_factory, ensure_tool_call_logs_table

logger = logging.getLogger("parity_telemetry")

LOOP_HAND = lp.LOOP_HAND
LOOP_LANGGRAPH = lp.LOOP_LANGGRAPH

# 多轮聚合参与指标（质量三层 + System 延迟 + 三段遥测汇总，AC-2/AC-4/AC-6）
_METRICS = ("pass_1", "tool_correct_rate", "avg_tokens", "tokens_total",
            "p50_ms", "p95_ms", "llm_ms_total", "tool_ms_total",
            "orch_ms_total", "llm_calls", "prompt_tokens", "completion_tokens",
            "llm_in_tool_ms_total", "llm_in_tool_calls")

# 工具执行窗口深度（eval 层标记；串行 await 无并发，单元素列表即可）
_DEPTH = [0]


def _tool_guard(original):
    """包装 execute_tool_with_log：工具窗口深度标记（供 proxy 分桶，防双重计数）

    Args:
        original: agent.react.execute_tool_with_log（两环路共用的工具执行入口）

    Returns:
        同签名 async 包装（计数后透传原行为）
    """
    async def _inner(name, args, tool, ctx, allowed_tools=None):
        _DEPTH[0] += 1
        try:
            return await original(name, args, tool, ctx,
                                  allowed_tools=allowed_tools)
        finally:
            _DEPTH[0] -= 1
    return _inner


class _TimingClientProxy:
    """LLM 客户端计时代理（eval 层包装）：逐次计时并按工具内/环路级分桶

    chat/chat_with_tools/generate 逐次计时；_DEPTH>0 时归工具桶（耗时已含在
    tool_call_logs 工具时长中），否则归环路桶（含预算耗尽兜底生成）。

    Args:
        inner: 真实 LLM 客户端（LLMFactory 缓存实例，行为不变）
        loop_sink: 环路级 LLM 调用耗时收集列表（ms）
        tool_sink: 工具内 LLM 调用耗时收集列表（ms）
    """

    def __init__(self, inner, loop_sink: list, tool_sink: list):
        self._inner = inner
        self._loop, self._tool = loop_sink, tool_sink

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in ("chat", "chat_with_tools", "generate"):
            return attr

        async def _timed(*args, **kwargs):
            sink = self._tool if _DEPTH[0] else self._loop
            t0 = time.perf_counter()
            try:
                return await attr(*args, **kwargs)
            finally:
                sink.append((time.perf_counter() - t0) * 1000)

        return _timed


@contextmanager
def _usage_interceptor(records: list):
    # 包装 llm.client._record_usage：原函数先执行（观测口径不变）再本地捕获
    # records 逐次追加 {"label","prompt_tokens","completion_tokens"}（AC-4）
    original = llm_client._record_usage

    def _wrap(label, response):
        original(label, response)
        usage = llm_client._extract_usage(response)
        if usage is not None:
            records.append({"label": label, "prompt_tokens": usage[0],
                            "completion_tokens": usage[1]})

    with mock.patch("llm.client._record_usage", side_effect=_wrap):
        yield


async def _tool_rows(trace_id: str) -> list:
    """读回一次运行的 tool_call_logs 行（工具段数据源，AC-5）；失败返回 []"""
    try:
        async with async_session_factory() as session:
            rows = (await session.execute(
                text("SELECT tool_name, duration_ms, result_ok FROM tool_call_logs"
                     " WHERE trace_id = :t ORDER BY id"),
                {"t": trace_id})).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("tool_call_logs 读回失败（工具段记 0，如实标注）: %s", e)
        return []


def segment_summary(duration_ms: int, llm_durs: list, tool_rows: list) -> dict:
    """三段拆解 + 闭合校验（纯函数，AC-6/AC-7）

    编排开销 = 总 duration_ms − ΣLLM − Σ工具（残差定义，ADR-0020 归因口径）；
    闭合校验 = ΣLLM+Σ工具 是否溢出总时长窗口（残差 <0 即失败）。

    Args:
        duration_ms: 请求总耗时（run_side 实测）
        llm_durs: 环路级 LLM 调用耗时 ms 列表（含兜底生成，不含工具内调用）
        tool_rows: tool_call_logs 行 [{tool_name, duration_ms, result_ok}, ...]

    Returns:
        {"llm_ms","llm_calls","llm_mean_ms","llm_p50_ms",
         "tool_ms","tool_calls","tool_failures","orch_ms",
         "closure_ok","closure_err_pct"}
    """
    llm_ms = round(sum(llm_durs), 1)
    tool_ms = int(sum(r["duration_ms"] for r in tool_rows))
    orch_ms = round(duration_ms - llm_ms - tool_ms, 1)
    return {
        "llm_ms": llm_ms, "llm_calls": len(llm_durs),
        "llm_mean_ms": round(llm_ms / len(llm_durs), 1) if llm_durs else 0.0,
        "llm_p50_ms": round(at._percentile(sorted(llm_durs), 0.5), 1) if llm_durs else 0.0,
        "tool_ms": tool_ms, "tool_calls": len(tool_rows),
        "tool_failures": sum(1 for r in tool_rows if not r["result_ok"]),
        "orch_ms": orch_ms,
        "closure_ok": orch_ms >= 0,
        "closure_err_pct": round(max(0.0, -orch_ms) / duration_ms * 100, 2)
        if duration_ms else 0.0,
    }


async def run_telemetry_side(loop: str, item: dict, k: int) -> dict:
    """单次运行（一条任务 × 一条环路）+ 分阶段遥测（复用 091 run_side 全流程）

    Args:
        loop: LOOP_HAND 或 LOOP_LANGGRAPH
        item: 任务条目
        k: 独立尝试序号（进 trace_id，与 run_side 内部一致）

    Returns:
        091 同款逐任务明细 dict，附 "telemetry" 三段+tokens 遥测子 dict
    """
    trace_id = f"eval-{item['id']}-{loop}-{k}"
    llm_durs: list = []
    in_tool_durs: list = []
    usage_records: list = []
    proxy = _TimingClientProxy(llm_client.LLMFactory.get_client(),
                               llm_durs, in_tool_durs)
    try:  # 预清理同 trace 历史 tool_call_logs 行（防重复运行累积污染工具段；
        # 仅精确命中本 eval trace，066 历史行无 loop 段不匹配）
        async with async_session_factory() as session:
            await session.execute(
                text("DELETE FROM tool_call_logs WHERE trace_id = :t"),
                {"t": trace_id})
            await session.commit()
    except Exception as e:
        logger.warning("tool_call_logs 预清理失败（fail-open）: %s", e)
    with mock.patch(lp._LLM_PATCH[loop], return_value=proxy), \
            mock.patch.object(_agent_react, "execute_tool_with_log",
                              _tool_guard(_agent_react.execute_tool_with_log)), \
            mock.patch.object(_agent_lg, "execute_tool_with_log",
                              _tool_guard(_agent_react.execute_tool_with_log)), \
            _usage_interceptor(usage_records):
        result = await lp.run_side(loop, item, k, real=True)
    tool_rows = await _tool_rows(trace_id)
    tel = segment_summary(result["duration_ms"], llm_durs, tool_rows)
    for key in ("prompt_tokens", "completion_tokens"):
        tel[key] = sum(r[key] for r in usage_records)
    tel["llm_in_tool_ms"], tel["llm_in_tool_calls"] = round(sum(in_tool_durs), 1), len(in_tool_durs)
    tel["tool_rows"] = [{"tool_name": r["tool_name"],
                         "duration_ms": r["duration_ms"],
                         "result_ok": r["result_ok"]} for r in tool_rows]
    result["telemetry"] = tel
    return result


async def run_round_real(tasks: list) -> dict:
    """一轮：任务按传入顺序逐条、两环路交替执行（091 同款 hand→langgraph）

    Args:
        tasks: 本轮任务顺序（轮间已重洗，集合与首轮相同）

    Returns:
        {loop: per_question list（每项附 telemetry；pass^1 口径）}
    """
    out = {LOOP_HAND: [], LOOP_LANGGRAPH: []}
    for i, item in enumerate(tasks):
        for loop in (LOOP_HAND, LOOP_LANGGRAPH):
            first = await run_telemetry_side(loop, item, 1)
            out[loop].append(first)
            logger.info("[%d] %s %-9s pass=%s tools=%s %.0fms", i + 1,
                        item["id"], loop, first["pass"], first["actual_names"],
                        first["duration_ms"])
    return out


def round_scores(loop: str, per_question: list, dataset_size: int) -> dict:
    """单轮单环路指标（091 score_run 同款口径 + 遥测汇总，module=092）

    Args:
        loop: 环路名
        per_question: 逐任务明细（附 telemetry）
        dataset_size: 任务集规模

    Returns:
        scores dict（含三段遥测汇总与闭合失败计数）
    """
    scores = lp.score_run(loop, per_question, 1, dataset_size)
    scores["module"] = "092"
    tels = [t.get("telemetry") or {} for t in per_question]
    for key, field in (("llm_ms_total", "llm_ms"), ("tool_ms_total", "tool_ms"),
                       ("orch_ms_total", "orch_ms"), ("llm_calls", "llm_calls"),
                       ("prompt_tokens", "prompt_tokens"),
                       ("completion_tokens", "completion_tokens"),
                       ("llm_in_tool_ms_total", "llm_in_tool_ms"),
                       ("llm_in_tool_calls", "llm_in_tool_calls")):
        scores[key] = round(sum(t.get(field, 0) for t in tels), 1)
    scores["closure_fail"] = sum(1 for t in tels if t.get("closure_ok") is False)
    return scores


def round_order(sampled: list, repeat_idx: int) -> list:
    """轮内任务顺序：集合不变、顺序重洗（seed=1000+i，可复现，AC-1）

    Args:
        sampled: 固定抽样集（091 种子 42 抽样后排序）
        repeat_idx: 轮序号（0-based）

    Returns:
        重洗后的新列表（不改入参）
    """
    order = list(sampled)
    random.Random(1000 + repeat_idx).shuffle(order)
    return order


def aggregate_rounds(rounds_scores: list, metrics: tuple) -> dict:
    """跨轮聚合：每指标 mean±std/min/max + 逐轮值（样本 std，AC-2）

    Args:
        rounds_scores: 逐轮 [{loop: scores}, ...]
        metrics: 参与聚合的指标名元组

    Returns:
        {loop: {metric: {"mean","std","min","max","rounds"} 或 None}}
    """
    agg = {}
    for loop in (LOOP_HAND, LOOP_LANGGRAPH):
        agg[loop] = {}
        for m in metrics:
            vals = [r[loop][m] for r in rounds_scores
                    if r[loop].get(m) is not None]
            agg[loop][m] = None if not vals else {
                "mean": round(statistics.fmean(vals), 4),
                "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
                "min": min(vals), "max": max(vals), "rounds": vals,
            }
    return agg


def aggregate_tool_rows(rows: list) -> dict:
    """tool 行按 tool_name 分组统计（纯函数，AC-5）

    Args:
        rows: [{tool_name, duration_ms, result_ok}, ...]

    Returns:
        {tool_name: {"count","total_ms","mean_ms","p50_ms","failures"}}
    """
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["tool_name"], []).append(r)
    return {name: {
        "count": len(rs),
        "total_ms": sum(r["duration_ms"] for r in rs),
        "mean_ms": round(sum(r["duration_ms"] for r in rs) / len(rs), 1),
        "p50_ms": round(at._percentile(
            sorted(r["duration_ms"] for r in rs), 0.5), 1),
        "failures": sum(1 for r in rs if not r["result_ok"]),
    } for name, rs in sorted(grouped.items())}


def collect_cold_warm(rounds_results: list) -> dict:
    """跨轮收集 cold/warm（每轮第 1 条执行任务=cold，其余=warm，中位比值 AC-9）

    Args:
        rounds_results: 逐轮 {loop: per_question}（per_question 按执行顺序；
            缺环路侧容忍为空）

    Returns:
        {loop: {"cold_ms","warm_ms","ratio"}}；样本缺失侧为 None（如实标注）
    """
    out = {}
    for loop in (LOOP_HAND, LOOP_LANGGRAPH):
        colds = [per_q[loop][0]["duration_ms"] for per_q in rounds_results
                 if per_q.get(loop)]
        warms = [t["duration_ms"] for per_q in rounds_results
                 for t in (per_q.get(loop) or [])[1:]]
        cold = statistics.median(colds) if colds else None
        warm = statistics.median(warms) if warms else None
        out[loop] = {"cold_ms": cold, "warm_ms": warm,
                     "ratio": round(cold / warm, 4) if cold is not None and warm else None}
    return out


def measure_import_coldstart(trials: int = 3) -> dict:
    """子进程 import 冷启动计时（AC-8）：agent.react vs agent.langgraph_react

    每模块 trials 个独立子进程计时 import（后者含模块级 build_react_graph
    编译），取中位；进程噪声如实标注（样本全保留）。

    Args:
        trials: 每模块测量次数

    Returns:
        {"hand"/"langgraph": {"samples","median"}, "delta_ms": 编译冷启动差值}
    """
    out = {}
    for name, mod in (("hand", "agent.react"),
                      ("langgraph", "agent.langgraph_react")):
        samples = [int(subprocess.run(
            [sys.executable, "-c", f"import time;t0=time.perf_counter();"
             f"import {mod};print(int((time.perf_counter()-t0)*1000))"],
            capture_output=True, text=True, timeout=600)
            .stdout.strip().splitlines()[-1]) for _ in range(trials)]
        out[name] = {"samples": samples, "median": statistics.median(samples)}
    out["delta_ms"] = round(out["langgraph"]["median"] - out["hand"]["median"], 1)
    return out


def build_snapshot(base: dict, loop: str, repeat_idx: int, repeat_of: int) -> dict:
    """config_snapshot：rag_config + loop/module/repeat（JSONB，零新表零 ALTER）

    Args:
        base: load_rag_config() 快照（失败可为 None/空）
        loop: 环路名
        repeat_idx: 轮序号（0-based）
        repeat_of: 总轮数

    Returns:
        快照 dict
    """
    return {**(base or {}), "loop": loop, "module": "092",
            "repeat": repeat_idx, "repeat_of": repeat_of}


def _fmt(a) -> str:
    return "N/A" if not a else (
        f"mean={a['mean']:.4f} std={a['std']:.4f}"
        f" min={a['min']:.4f} max={a['max']:.4f} rounds={a['rounds']}")


def print_report(agg: dict, ratios: list, tool_stats: dict, coldstart: dict,
                 coldwarm: dict, rounds_results: list, repeat: int) -> None:
    """打印完整报告：多轮聚合 + P95 逐轮比值 + StateGraph 归因 + 工具明细
    + 冷启动 + 失败清单（AC-2/5/6/8/9/12/19/20）

    Args:
        agg: aggregate_rounds 结果
        ratios: 逐轮 P95 比值（langgraph/hand）
        tool_stats: {loop: aggregate_tool_rows 结果}
        coldstart: measure_import_coldstart 结果
        coldwarm: collect_cold_warm 结果
        rounds_results: 逐轮 {loop: per_question} 列表
        repeat: 总轮数

    Returns:
        None（打印到 stdout）
    """
    labels = (("pass_1", "pass^1"), ("tool_correct_rate", "工具正确率"),
              ("avg_tokens", "平均 token"), ("tokens_total", "tokens 总量"),
              ("p50_ms", "P50 ms"), ("p95_ms", "P95 ms"),
              ("llm_ms_total", "LLM 轮次 ms"), ("tool_ms_total", "工具执行 ms"),
              ("orch_ms_total", "编排开销 ms"), ("llm_calls", "LLM 调用次数"),
              ("prompt_tokens", "prompt tokens"),
              ("completion_tokens", "completion tokens"),
              ("llm_in_tool_ms_total", "工具内 LLM ms"),
              ("llm_in_tool_calls", "工具内 LLM 次数"))
    print(f"\n{'=' * 72}\n多轮采样聚合（repeat={repeat}，抽样集合固定、轮间顺序重洗）\n{'=' * 72}\n"
          + "\n".join(f"{label:<26}{_fmt(agg[LOOP_HAND].get(k)):>36}"
                      f"{_fmt(agg[LOOP_LANGGRAPH].get(k)):>36}"
                      for k, label in labels)
          + f"\n逐轮 P95 比值（langgraph/hand）: {ratios} | ≤1.20 阈值轮数:"
            f" {sum(1 for r in ratios if r is not None and r <= 1.20)}/"
            f"{sum(1 for r in ratios if r is not None)}"
            f" | 比值均值 {statistics.fmean([r for r in ratios if r is not None]):.4f}"
          + f"\n[StateGraph 归因] 编排开销差值 langgraph−hand = "
            f"{agg[LOOP_LANGGRAPH]['orch_ms_total']['mean'] - agg[LOOP_HAND]['orch_ms_total']['mean']:.1f}"
            f" ms/轮（lg={agg[LOOP_LANGGRAPH]['orch_ms_total']['mean']:.1f} vs"
            f" hand={agg[LOOP_HAND]['orch_ms_total']['mean']:.1f}，残差定义）")
    print(f"\n{'=' * 72}\n冷启动对比（子进程 import 计时，中位 ms；样本含进程噪声）\n{'=' * 72}\n"
          + "\n".join(
        f"  {tag:<10} import {mod} 中位={coldstart[tag]['median']} ms"
        f" samples={coldstart[tag]['samples']}"
        f" | cold/warm={coldwarm[tag]['ratio']}"
        f"（cold={coldwarm[tag]['cold_ms']} warm={coldwarm[tag]['warm_ms']} ms）"
        for tag, mod in ((LOOP_HAND, "agent.react"),
                         (LOOP_LANGGRAPH, "agent.langgraph_react")))
          + f"\n  框架 import+图编译冷启动差值 = {coldstart['delta_ms']} ms"
            "（langgraph − hand）")
    print(f"\n{'=' * 72}\n工具级明细（全轮合计；LLM 段=环路级调用含兜底生成，"
          f"工具内 LLM 已含在工具时长中，三段不相交）\n{'=' * 72}\n" + "\n".join(
        f"[{loop}] " + "; ".join(
            f"{n}: n={s['count']} total={s['total_ms']} mean={s['mean_ms']}"
            f" p50={s['p50_ms']} fail={s['failures']}"
            for n, s in tool_stats[loop].items())
        for loop in (LOOP_HAND, LOOP_LANGGRAPH)))
    fails = [f"repeat={i} {t['task_id']} {loop}: {t['fail_reason']}"
             for i, per in enumerate(rounds_results)
             for loop in (LOOP_HAND, LOOP_LANGGRAPH) for t in per[loop]
             if t.get("fail_reason")]
    print(f"运行期失败 {len(fails)} 条（如实列出，不重跑掩盖）: "
          + ("; ".join(fails) if fails else "无"))


async def main() -> None:
    """CLI 入口：多轮采样 + 分阶段遥测 + 冷启动（module-092 real 模式）

    Args:
        None（参数经 argparse：--mode/--sample/--repeat/--limit/--no-save；
        pass_k 固定 1，AC 命令表口径）

    Returns:
        None（报告打印到 stdout；结果落 agent_eval_runs 除非 --no-save）
    """
    parser = argparse.ArgumentParser(description="对比评测深化（module-092）")
    parser.add_argument("--mode", choices=["real"], default="real")
    parser.add_argument("--sample", type=int, default=12,
                        help="抽样条数（0=全量；种子 42 与 091 同款可复现）")
    parser.add_argument("--repeat", type=int, default=3,
                        help="采样轮数（每轮同集合重洗顺序）")
    parser.add_argument("--limit", type=int, default=0, help="冒烟：只跑前 N 条")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    repeat = max(1, args.repeat)
    tasks = at.load_agent_tasks()  # 先校验任务集（结构非法立即报错退出）
    tasks = tasks[:max(0, args.limit)] if args.limit else tasks
    sampled = sorted(
        random.Random(42).sample(tasks, min(args.sample, len(tasks)))
        if args.sample else tasks, key=lambda t: t["id"])
    try:  # real 模式依赖 tool_call_logs（grounding/工具段数据来源）
        await ensure_tool_call_logs_table()
    except Exception as e:
        logger.warning("tool_call_logs 建表失败（grounding 将标 None）: %s", e)

    coldstart = measure_import_coldstart()
    rounds_scores, rounds_results = [], []
    t0 = time.perf_counter()
    for i in range(repeat):
        results = await run_round_real(round_order(sampled, i))
        rounds_results.append(results)
        rounds_scores.append({loop: round_scores(loop, results[loop],
                                                 len(sampled))
                              for loop in (LOOP_HAND, LOOP_LANGGRAPH)})
    wall_min = (time.perf_counter() - t0) / 60

    if args.no_save:
        print("[--no-save] 跳过 agent_eval_runs 落库")
    else:
        from eval.golden.golden_retrieval import get_git_commit, load_rag_config
        commit, base = get_git_commit(), await load_rag_config()
        for i, loop in [(i, l) for i in range(repeat)
                        for l in (LOOP_HAND, LOOP_LANGGRAPH)]:
            run_id = await at.save_agent_eval_run(
                commit, build_snapshot(base, loop, i, repeat),
                rounds_scores[i][loop], rounds_results[i][loop])
            print(f"Saved agent_eval_runs id={run_id} loop={loop}"
                  f" repeat={i}/{repeat} commit={commit[:8]}")

    ratios = [round(r[LOOP_LANGGRAPH]["p95_ms"] / r[LOOP_HAND]["p95_ms"], 4)
              if r[LOOP_HAND]["p95_ms"] else None for r in rounds_scores]
    tool_stats = {loop: aggregate_tool_rows(
        [r for per_q in rounds_results for t in per_q[loop]
         for r in (t.get("telemetry", {}).get("tool_rows") or [])])
        for loop in (LOOP_HAND, LOOP_LANGGRAPH)}
    print_report(agg=aggregate_rounds(rounds_scores, _METRICS), ratios=ratios,
                 tool_stats=tool_stats, coldstart=coldstart,
                 coldwarm=collect_cold_warm(rounds_results),
                 rounds_results=rounds_results, repeat=repeat)
    print(f"墙钟 {wall_min:.1f} 分钟 | tokens 总量（两环路全轮合计）="
          f"{sum(r[loop]['tokens_total'] for r in rounds_scores for loop in (LOOP_HAND, LOOP_LANGGRAPH))}")
    await at._cleanup_eval_memory()  # 测后清理评测身份记忆残留（066 先例，防御性）


if __name__ == "__main__":
    asyncio.run(main())
