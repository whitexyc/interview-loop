"""
module-093 WP-C 对拍裁定 — 三臂 off / clearing / clearing+compaction
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

三臂逐臂跑同一剧本集（ctx_tasks.CTX_SCRIPTS）：臂间唯一差异 = ctx_mode
（D4 公平，接线点单一）。复用 066 判定器（outcome_pass 要点子串口径）与
066/092 基建落库（agent_eval_runs，config_snapshot.module='093' + ctx_mode）。

三判据（plan §2.9，跑批前定死，结果不利照实写）：
  ① 质量：压缩臂 pass^1 ≥ off 臂 − 0.10
  ② 收益：压缩臂 history 桶 est_tokens 总量 < off 臂 × 0.70
  ③ 成本：压缩臂 LLM 次数 ≤ off 臂 × 1.15
  任一不满足 → 该臂"不引入"；② 满足且 ①③ 满足 → 建议默认开启。

用法（ai_service 目录）:
    python -m eval.ctx_parity --mode real --repeat 1          # 全量 3 剧本 × 3 臂
    python -m eval.ctx_parity --mode fixture                  # 零 LLM/DB 管线验证
    python -m eval.ctx_parity --mode real --sample 1 --no-save # 单剧本冒烟

红线：只读生产代码；拦截/配置全在 eval 层（mock.patch 包装且原行为透传），
agent/ src/ main.py 零 diff。三臂通过 settings + 对 compress_view 的 patch
表达，不引入新配置项（config 三字段红线）。
"""
import argparse
import asyncio
import json
import logging
import time
from contextlib import nullcontext
from typing import Optional
from unittest import mock

from src import observability
from src.config import settings

import agent.react as react_mod
import agent.langgraph_react as lg_mod
import agent.ctx_manager as cm
from agent.react import ReactContext, _build_messages, react_loop
from agent.ctx_manager import classify_context
from eval import agent_tasks as at
from eval.ctx_tasks import load_ctx_scripts

logger = logging.getLogger("ctx_parity")

# 对拍固定匿名身份（记忆只读不写，测后清理不污染真实记忆）
EVAL_IDENTITY = "eval-093-anon"

# 三臂定义（ctx_mode 值 + 压缩参数）；阈值压低以保证 18 轮长对话触发压缩，
# 实验参数写入报告（AC-22 诚实标注）。
ARMS = ("off", "clearing", "clearing_compaction")
EXP_THRESHOLD = 3000
EXP_KEEP_RECENT = 6


def _arm_cfg(arm: str) -> dict:
    """返回臂的压缩配置（仅用于快照与日志，真实行为由 settings + patch 落地）

    Args:
        arm: off / clearing / clearing_compaction

    Returns:
        {ctx_mode, enabled, compact, threshold, keep_recent}
    """
    if arm == "off":
        return {"ctx_mode": arm, "enabled": False, "compact": True,
                "threshold": EXP_THRESHOLD, "keep_recent": EXP_KEEP_RECENT}
    if arm == "clearing":
        return {"ctx_mode": arm, "enabled": True, "compact": False,
                "threshold": EXP_THRESHOLD, "keep_recent": EXP_KEEP_RECENT}
    return {"ctx_mode": arm, "enabled": True, "compact": True,
            "threshold": EXP_THRESHOLD, "keep_recent": EXP_KEEP_RECENT}


# ==================== LLM 客户端插桩（eval 层，零生产 diff） ====================


class _InstrumentedClient:
    """LLM 客户端插桩代理：逐次记录传给 chat_with_tools 的视图 history tokens

    压缩臂传入的是 compress_view 产出的视图副本，故记录的 history tokens 即
    实际发给 LLM 的上下文量（D1 视图模式可被实测印证）。其余方法（generate/
    chat 等，含工具内部检索/反思/生成调用）经 __getattr__ 透明透传，不破坏
    工具内 LLM 路径；仅拦截 chat_with_tools 做 token 采集。

    Args:
        inner: 真实/假 LLM 客户端
        token_sink: 每次 chat_with_tools 调用的 history est_tokens 收集列表
            （user+assistant+tool_results 三桶，不含 system/tools，契合
            "history 桶"口径）
    """

    def __init__(self, inner, token_sink: list):
        self._inner = inner
        self._sink = token_sink

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def chat_with_tools(self, messages, tools):
        buckets = classify_context(messages, tools)
        hist = sum(buckets[k]["est_tokens"] for k in
                   ("user", "assistant", "tool_results"))
        self._sink.append(hist)
        return await self._inner.chat_with_tools(messages, tools)


class _CtxFixtureClient:
    """fixture 假 LLM：直接回答并注入当前轮 answer_points（零 LLM/DB 演示用）

    单轮无工具：每轮一次 chat_with_tools 即产出最终答案；answer_points 由
    驱动方在每轮前写入 _cur_points，使 fixture 质量命中可演示。答案为较长模板
    （>200 字），使 compaction 折叠（assistant 截断至 120 字）能真实体现"压缩
    降本"，贴合真实长答案场景；fixture 仅验证管线（触发/指标/落库），非真实
    质量，报告如实标注。
    """

    def __init__(self):
        self._cur_points: list[str] = []

    def _answer(self) -> str:
        pts = self._cur_points or ["相关概念"]
        detail = "；".join(pts)
        return ("关于您的问题，需要从原理、实现与工程权衡三个维度展开说明。"
                f"具体而言，{detail} 在真实生产系统中必须结合业务场景、资源约束与"
                "可维护性综合判断，并警惕边界条件与常见误区，切忌生搬硬套。"
                "建议在压测与灰度中验证其稳定性与正确性，结合监控指标持续观察"
                "实际表现，再据此迭代优化，方能兼顾效果与成本。")

    async def chat_with_tools(self, messages, tools):
        ans = self._answer()
        return {"content": ans, "tool_calls": [],
                "message": {"role": "assistant", "content": ans}}

    async def chat(self, messages):
        return self._answer()


# ==================== 单剧本驱动 ====================


async def _run_script(arm: str, script: dict, fixture: bool,
                      token_sink: list, fixture_client: Optional[_CtxFixtureClient]
                      ) -> list[dict]:
    """驱动单个剧本（initial + 18 轮）走 react_loop，返回逐轮明细

    每轮答案追加进 history（与 066 同款多轮累积），压缩在 react_loop 内部按
    本臂 settings + compress_view patch 生效；视图 history tokens 由
    _InstrumentedClient 收集到 token_sink（跨剧本累计，落库后按臂汇总）。

    Args:
        arm: 臂名（仅日志）
        script: load_ctx_scripts() 单条
        fixture: True=fixture 假 LLM（零 DB/LLM）
        token_sink: 本臂 history tokens 收集列表（跨剧本共享）
        fixture_client: fixture 模式假客户端（每轮前注入 answer_points）

    Returns:
        逐轮明细 [{"q","answer_points","answer","pass"}]
    """
    history: list[dict] = []
    per_round: list[dict] = []
    rounds = [{"q": script["initial"], "answer_points": []}] + script["rounds"]
    for r in rounds:
        if fixture and fixture_client is not None:
            fixture_client._cur_points = r["answer_points"]
        ctx = ReactContext(r["q"], identity=EVAL_IDENTITY, history=history)
        answer = ""
        try:
            async for evt in react_loop(ctx, _build_messages(ctx),
                                        settings.max_agent_tools):
                if evt.get("type") == "done":
                    answer = evt.get("answer", "") or ""
        except Exception as e:  # 单轮失败不中断整剧本，记空答案 + fail_reason
            logger.error("[%s/%s] 轮次失败: %s", arm, script["id"], e)
            answer = ""
        pseudo = {"expected_tools": [], "answer_points": r["answer_points"]}
        per_round.append({
            "q": r["q"], "answer_points": r["answer_points"],
            "answer": (answer or "")[:300],
            "pass": at.outcome_pass(pseudo, answer, []),
        })
        history.append({"role": "user", "content": r["q"]})
        if answer:
            history.append({"role": "assistant", "content": answer})
    return per_round


# ==================== 单臂 ====================


async def run_arm(arm: str, scripts: list[dict], fixture: bool) -> dict:
    """运行单臂（三剧本顺序跑，配置经 settings + patch 表达）

    落库在 main 统一做（按臂一次 save_agent_eval_run）。本函数返回本臂指标。

    Args:
        arm: off / clearing / clearing_compaction
        scripts: load_ctx_scripts() 结果
        fixture: 是否 fixture 假 LLM

    Returns:
        {"ctx_mode","per_question","scores","meta"}
    """
    cfg = _arm_cfg(arm)
    settings.ctx_compress_enabled = cfg["enabled"]
    settings.ctx_token_threshold = cfg["threshold"]
    settings.ctx_keep_recent = cfg["keep_recent"]
    token_sink: list = []
    fixture_client = _CtxFixtureClient() if fixture else None

    def _clearing_only(messages, schemas, c=None):
        return cm.compress_view(messages, schemas, c, compact=False)

    # LLM 客户端插桩：real 模式包装 LLMFactory 真实客户端；fixture 包装假客户端
    if fixture:
        real_get = lambda *a, **k: _InstrumentedClient(fixture_client, token_sink)
    else:
        from llm.client import LLMFactory
        _orig = LLMFactory.get_client

        def real_get(*a, **k):
            return _InstrumentedClient(_orig(*a, **k), token_sink)

    # 三臂差异经 settings（enabled/threshold/keep_recent）+ 对 compress_view 的
    # patch（clearing-only 臂 compact=False）表达；LLM 客户端插桩收集视图 tokens。
    # 全部 eval 层 mock.patch，原行为透传，零生产 diff。
    active_clearing = (arm == "clearing")
    with mock.patch.object(react_mod, "compress_view",
                            _clearing_only if active_clearing else react_mod.compress_view), \
            mock.patch.object(lg_mod, "compress_view",
                              _clearing_only if active_clearing else lg_mod.compress_view), \
            mock.patch("agent.react.LLMFactory.get_client", real_get), \
            (mock.patch("agent.langgraph_react.LLMFactory.get_client", real_get)
             if not fixture else nullcontext()):
        per_question = []
        for s in scripts:
            observability.init_request(f"ctx-{arm}-{s['id']}")
            per = await _run_script(arm, s, fixture, token_sink, fixture_client)
            per_question.extend(per)

    passes = sum(1 for r in per_question if r["pass"])
    scores = {
        "pass_1": round(passes / len(per_question), 4) if per_question else 0.0,
        "history_tokens_total": int(sum(token_sink)),
        "llm_calls_total": len(token_sink),
        "scripts": len(scripts),
        "rounds": len(per_question),
        "fixture": fixture,
        "module": "093",
        "ctx_mode": arm,
    }
    return {"ctx_mode": arm, "per_question": per_question, "scores": scores,
            "meta": cfg}


# ==================== 三判据裁定 ====================


def judge_criteria(off: dict, clearing: dict, compaction: dict) -> dict:
    """三判据逐臂裁定（plan §2.9，跑批前定死）

    Args:
        off/clearing/compaction: 各臂 run_arm 返回的 scores

    Returns:
        {arm: {quality_ok, tokens_ok, cost_ok, introduce}}
    """
    def _verdict(m):
        q_ok = m["pass_1"] >= off["pass_1"] - 0.10
        t_ok = m["history_tokens_total"] < off["history_tokens_total"] * 0.70
        c_ok = m["llm_calls_total"] <= off["llm_calls_total"] * 1.15
        return {"quality_ok": q_ok, "tokens_ok": t_ok, "cost_ok": c_ok,
                "introduce": bool(t_ok and q_ok and c_ok)}
    return {"clearing": _verdict(clearing),
            "clearing_compaction": _verdict(compaction)}


# ==================== 落库 + 报告 ====================


def _build_snapshot(arm: str, cfg: dict) -> dict:
    """config_snapshot：module='093' + ctx_mode + 压缩参数（JSONB，零新表）

    Args:
        arm: 臂名
        cfg: _arm_cfg 结果

    Returns:
        快照 dict
    """
    return {"module": "093", "ctx_mode": arm,
            "ctx_compress_enabled": cfg["enabled"],
            "ctx_compact": cfg["compact"],
            "ctx_token_threshold": cfg["threshold"],
            "ctx_keep_recent": cfg["keep_recent"],
            "loop": "hand"}


def _git_commit() -> str:
    try:
        from eval.golden.golden_retrieval import get_git_commit
        return get_git_commit()
    except Exception:  # noqa: BLE001 —— eval 层容错：失败返回空串不阻塞跑批（review LOW-2 补留痕）
        logger.debug("git commit 获取失败", exc_info=True)
        return ""


def print_report(arms_out: dict, verdict: dict) -> None:
    """打印三臂指标 + 三判据裁定（逐值，不利结论不弱化）"""
    print("\n" + "=" * 72)
    print("module-093 上下文压缩对拍裁定（三臂：off / clearing / clearing+compaction）")
    print("=" * 72)
    hdr = f"{'ctx_mode':<20}{'pass_1':>10}{'hist_tokens':>14}{'llm_calls':>12}"
    print(hdr)
    for arm in ARMS:
        s = arms_out[arm]["scores"]
        print(f"{arm:<20}{s['pass_1']:>10.4f}{s['history_tokens_total']:>14}"
              f"{s['llm_calls_total']:>12}")
    print("-" * 72)
    o = arms_out["off"]["scores"]
    for arm in ("clearing", "clearing_compaction"):
        m = arms_out[arm]["scores"]
        v = verdict[arm]
        print(f"[{arm}]")
        print(f"  ①质量 pass_1={m['pass_1']:.4f} ≥ off({o['pass_1']:.4f})−0.10="
              f"{o['pass_1']-0.10:.4f} -> {'OK' if v['quality_ok'] else 'FAIL'}")
        print(f"  ②收益 hist={m['history_tokens_total']} < off({o['history_tokens_total']})"
              f"×0.70={int(o['history_tokens_total']*0.70)} -> "
              f"{'OK' if v['tokens_ok'] else 'FAIL'}")
        print(f"  ③成本 llm={m['llm_calls_total']} ≤ off({o['llm_calls_total']})"
              f"×1.15={o['llm_calls_total']*1.15:.1f} -> {'OK' if v['cost_ok'] else 'FAIL'}")
        print(f"  -> 裁定: {'建议引入（默认开启）' if v['introduce'] else '不引入'}")
    print("=" * 72)


async def main() -> None:
    """CLI 入口：三臂对拍（fixture 验证管线 / real 真实裁定）"""
    parser = argparse.ArgumentParser(description="module-093 上下文压缩对拍（三臂）")
    parser.add_argument("--mode", choices=["real", "fixture"], default="real")
    parser.add_argument("--sample", type=int, default=0, help="抽样剧本数（0=全量 3）")
    parser.add_argument("--threshold", type=int, default=0,
                        help="覆盖触发阈值（0=用默认 EXP_THRESHOLD，fixture 验证可压低）")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    fixture = args.mode == "fixture"
    if args.threshold:
        global EXP_THRESHOLD
        EXP_THRESHOLD = args.threshold
    scripts = load_ctx_scripts()
    if args.sample:
        scripts = scripts[:max(0, args.sample)]

    arms_out: dict = {}
    t0 = time.perf_counter()
    for arm in ARMS:
        out = await run_arm(arm, scripts, fixture)
        arms_out[arm] = out
        logger.info("臂 %s 完成：pass_1=%.4f hist=%d llm=%d",
                    arm, out["scores"]["pass_1"],
                    out["scores"]["history_tokens_total"],
                    out["scores"]["llm_calls_total"])

    verdict = judge_criteria(arms_out["off"]["scores"],
                             arms_out["clearing"]["scores"],
                             arms_out["clearing_compaction"]["scores"])
    print_report(arms_out, verdict)

    if not args.no_save:
        commit = _git_commit()
        for arm in ARMS:
            run_id = await at.save_agent_eval_run(
                commit, _build_snapshot(arm, arms_out[arm]["meta"]),
                arms_out[arm]["scores"], arms_out[arm]["per_question"])
            print(f"Saved agent_eval_runs id={run_id} ctx_mode={arm} "
                  f"commit={commit[:8]}")
    else:
        print("[--no-save] 跳过 agent_eval_runs 落库")
    print(f"墙钟 {(time.perf_counter()-t0)/60:.1f} 分钟 | fixture={fixture}")
    await at._cleanup_eval_memory()


if __name__ == "__main__":
    asyncio.run(main())
