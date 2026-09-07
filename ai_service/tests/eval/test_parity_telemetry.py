"""module-092：parity_telemetry 单测（拦截器捕获 + 三段闭合 + 聚合统计 + cold/warm）

覆盖（验收 AC-4/6/7/9/16）：
- AC-4 拦截器：_usage_interceptor 包装 llm.client._record_usage 后原行为不变
  （observability 统计照常累积）+ 本地列表逐次捕获 (label, prompt, completion)；
  _TimingClientProxy 逐次计时且返回值透传
- AC-6 编排开销：segment_summary 残差定义（总时长−ΣLLM−Σ工具）与闭合校验
  （残差 <0 即闭合失败，误差=|残差|/总时长）
- AC-2 聚合统计：aggregate_rounds 每指标 mean/std/min/max（样本 std，n>1）
- AC-5 工具遥测：aggregate_tool_rows 按 tool_name 分组（次数/总/mean/P50/失败）
- AC-9 cold/warm：cold_warm_stats 中位比值 + collect_cold_warm 每轮首条=cold
- AC-1 轮间顺序：round_order 抽样集合不变、顺序重洗且可复现
- AC-3 落库字段：build_snapshot 注入 repeat/repeat_of/module=092

实现说明：真实 LLM/DB 跑批不在单测内（--mode real 由真实跑批覆盖）。
"""
import asyncio
from unittest import mock

import llm.client as llm_client
from src import observability

import eval.parity_telemetry as pt
from eval.langgraph_parity import LOOP_HAND, LOOP_LANGGRAPH


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5


class _FakeResponse:
    usage = _FakeUsage()


class TestUsageInterceptor:
    """AC-4：_record_usage 包装拦截（原行为不变 + 本地捕获）"""

    def test_original_behavior_preserved_and_capture_grows(self):
        """包装后原埋点（observability.record_usage）照常触发，且本地列表逐次捕获"""
        records = []
        observability.init_request("test-092-interceptor")
        with mock.patch.object(observability, "record_usage",
                               wraps=observability.record_usage) as spy:
            with pt._usage_interceptor(records):
                llm_client._record_usage("qwen", _FakeResponse())
                llm_client._record_usage("qwen", _FakeResponse())
        # 原行为不变：观测埋点照常触发 2 次（conftest 钉 request_logs_enabled
        # =false 时 record_usage 内部短路，但调用链本身必须发生）
        assert spy.call_count == 2
        # 本地捕获：逐次 (label, prompt, completion)
        assert records == [
            {"label": "qwen", "prompt_tokens": 10, "completion_tokens": 5}] * 2

    def test_no_usage_response_skipped(self):
        """无 usage 响应（None/空壳）不产生本地记录也不中断"""

        class _Empty:
            pass

        records = []
        observability.init_request("test-092-interceptor-empty")
        with pt._usage_interceptor(records):
            llm_client._record_usage("qwen", _Empty())
            llm_client._record_usage("qwen", None)
        assert records == []

    def test_unpatched_outside_context(self):
        """退出上下文后 _record_usage 恢复原函数（mock 范围仅限 with 块）"""
        original = llm_client._record_usage
        with pt._usage_interceptor([]):
            assert llm_client._record_usage is not original
        assert llm_client._record_usage is original


class TestTimingProxy:
    """AC-4：_TimingClientProxy 逐次计时 + 透传 + 工具内/环路级分桶"""

    def test_times_and_delegates(self):
        class _Inner:
            def __init__(self):
                self.calls = 0

            async def chat_with_tools(self, messages, tools):
                self.calls += 1
                return {"content": "ok", "tool_calls": []}

        inner = _Inner()
        loop_sink, tool_sink = [], []
        proxy = pt._TimingClientProxy(inner, loop_sink, tool_sink)
        out = asyncio.run(proxy.chat_with_tools([{"role": "user", "content": "q"}], []))
        assert out == {"content": "ok", "tool_calls": []}
        assert inner.calls == 1
        assert len(loop_sink) == 1 and loop_sink[0] >= 0 and tool_sink == []

    def test_chat_also_timed(self):
        class _Inner:
            async def chat(self, messages):
                return "ans"

        loop_sink, tool_sink = [], []
        proxy = pt._TimingClientProxy(_Inner(), loop_sink, tool_sink)
        assert asyncio.run(proxy.chat([])) == "ans"
        assert len(loop_sink) == 1 and tool_sink == []

    def test_in_tool_call_classified(self):
        """工具窗口内（_tool_guard 深度>0）的 LLM 调用归入工具桶（不与工具时长重叠）"""
        class _Inner:
            async def generate(self, prompt):
                return "gen"

        loop_sink, tool_sink = [], []
        proxy = pt._TimingClientProxy(_Inner(), loop_sink, tool_sink)

        async def fake_exec(name, args, tool, ctx, allowed_tools=None):
            return await proxy.generate("q")

        guarded = pt._tool_guard(fake_exec)
        assert asyncio.run(guarded("n", {}, None, object())) == "gen"
        assert len(tool_sink) == 1 and loop_sink == []


class TestSegmentSummary:
    """AC-6/AC-7：三段拆解（残差定义）+ 闭合校验"""

    @staticmethod
    def _rows(*durs_ok):
        return [{"tool_name": "t", "duration_ms": d, "result_ok": ok}
                for d, ok in durs_ok]

    def test_residual_and_closure_ok(self):
        tel = pt.segment_summary(1000, [100.0, 200.0],
                                 self._rows((100, True), (50, False)))
        assert tel["llm_ms"] == 300.0
        assert tel["llm_calls"] == 2
        assert tel["llm_mean_ms"] == 150.0
        assert tel["llm_p50_ms"] == 150.0
        assert tel["tool_ms"] == 150
        assert tel["tool_calls"] == 2
        assert tel["tool_failures"] == 1
        assert tel["orch_ms"] == 550.0
        assert tel["closure_ok"] is True and tel["closure_err_pct"] == 0.0

    def test_overflow_flags_closure_failure(self):
        """ΣLLM+Σ工具 溢出总时长窗口（残差<0）→ 闭合失败 + 误差百分比"""
        tel = pt.segment_summary(100, [200.0], [])
        assert tel["orch_ms"] == -100.0
        assert tel["closure_ok"] is False
        assert tel["closure_err_pct"] == 100.0

    def test_empty_segments(self):
        tel = pt.segment_summary(500, [], [])
        assert tel["llm_ms"] == 0.0 and tel["tool_ms"] == 0
        assert tel["orch_ms"] == 500.0
        assert tel["llm_mean_ms"] == 0.0 and tel["llm_p50_ms"] == 0.0
        assert tel["closure_ok"] is True


class TestAggregateRounds:
    """AC-2：跨轮聚合 mean/std/min/max（样本 std）"""

    @staticmethod
    def _rounds(metric, vals):
        return [{LOOP_HAND: {metric: v},
                 LOOP_LANGGRAPH: {metric: None if v is None else v * 2}}
                for v in vals]

    def test_mean_std_min_max(self):
        import statistics
        vals = [100.0, 200.0, 400.0]
        agg = pt.aggregate_rounds(self._rounds("p95_ms", vals), ("p95_ms",))
        h = agg[LOOP_HAND]["p95_ms"]
        assert h["mean"] == round(statistics.fmean(vals), 4)
        assert h["std"] == round(statistics.stdev(vals), 4)
        assert h["min"] == 100.0 and h["max"] == 400.0
        assert h["rounds"] == vals
        lg = agg[LOOP_LANGGRAPH]["p95_ms"]
        assert lg["mean"] == round(statistics.fmean([v * 2 for v in vals]), 4)

    def test_single_round_std_zero(self):
        agg = pt.aggregate_rounds(self._rounds("pass_1", [0.5]), ("pass_1",))
        assert agg[LOOP_HAND]["pass_1"]["std"] == 0.0

    def test_none_metric_yields_none(self):
        agg = pt.aggregate_rounds(self._rounds("tool_correct_rate", [None]),
                                  ("tool_correct_rate",))
        assert agg[LOOP_HAND]["tool_correct_rate"] is None


class TestToolAggregation:
    """AC-5：tool_call_logs 行按 tool_name 分组"""

    def test_grouping(self):
        rows = [
            {"tool_name": "search_knowledge", "duration_ms": 100, "result_ok": True},
            {"tool_name": "search_knowledge", "duration_ms": 300, "result_ok": True},
            {"tool_name": "generate_answer", "duration_ms": 50, "result_ok": False},
        ]
        stats = pt.aggregate_tool_rows(rows)
        sk = stats["search_knowledge"]
        assert sk["count"] == 2 and sk["total_ms"] == 400
        assert sk["mean_ms"] == 200.0 and sk["p50_ms"] == 200.0
        assert sk["failures"] == 0
        ga = stats["generate_answer"]
        assert ga["count"] == 1 and ga["failures"] == 1

    def test_empty(self):
        assert pt.aggregate_tool_rows([]) == {}


class TestColdWarm:
    """AC-9：cold/warm 中位比值（每轮首条执行任务=cold）"""

    def test_ratio(self):
        rounds = [{LOOP_HAND: [{"duration_ms": 100}, {"duration_ms": 50},
                               {"duration_ms": 70}]}]
        out = pt.collect_cold_warm(rounds)
        assert out[LOOP_HAND]["cold_ms"] == 100
        assert out[LOOP_HAND]["warm_ms"] == 60  # median([50,70])
        assert out[LOOP_HAND]["ratio"] == round(100 / 60, 4)

    def test_no_warm_samples(self):
        rounds = [{LOOP_HAND: [{"duration_ms": 120}]}]
        out = pt.collect_cold_warm(rounds)
        assert out[LOOP_HAND]["cold_ms"] == 120
        assert out[LOOP_HAND]["warm_ms"] is None
        assert out[LOOP_HAND]["ratio"] is None

    def test_collect_per_round_first_is_cold(self):
        rounds = [
            {LOOP_HAND: [{"duration_ms": 100}, {"duration_ms": 50}],
             LOOP_LANGGRAPH: [{"duration_ms": 300}, {"duration_ms": 100}]},
            {LOOP_HAND: [{"duration_ms": 200}, {"duration_ms": 60}],
             LOOP_LANGGRAPH: [{"duration_ms": 400}, {"duration_ms": 120}]},
        ]
        out = pt.collect_cold_warm(rounds)
        # hand：cold=[100,200] 中位 150；warm=[50,60] 中位 55
        assert out[LOOP_HAND]["cold_ms"] == 150
        assert out[LOOP_HAND]["warm_ms"] == 55
        assert out[LOOP_LANGGRAPH]["cold_ms"] == 350
        assert out[LOOP_LANGGRAPH]["warm_ms"] == 110


class TestRoundOrder:
    """AC-1：轮间集合不变、顺序重洗、可复现"""

    def test_same_ids_shuffled_order(self):
        sampled = [{"id": f"at-{i:03d}"} for i in range(12)]
        r0 = pt.round_order(sampled, 0)
        r1 = pt.round_order(sampled, 1)
        assert [t["id"] for t in r0] == [t["id"] for t in pt.round_order(sampled, 0)]
        assert sorted(t["id"] for t in r0) == sorted(t["id"] for t in sampled)
        assert [t["id"] for t in r0] != [t["id"] for t in r1]  # 顺序确有重洗
        assert sampled[0]["id"] == "at-000"  # 入参未被改动


class TestSnapshotAndScores:
    """AC-3：落库字段（repeat/repeat_of/module=092）+ 单轮遥测汇总"""

    def test_build_snapshot_fields(self):
        snap = pt.build_snapshot({"rag_chunk_size": 500}, LOOP_LANGGRAPH, 2, 3)
        assert snap["loop"] == "langgraph"
        assert snap["module"] == "092"
        assert snap["repeat"] == 2 and snap["repeat_of"] == 3
        assert snap["rag_chunk_size"] == 500

    def test_round_scores_telemetry_sums(self):
        per_q = [
            {"pass": True, "tool_correct": True, "no_extra": True, "args_ok": True,
             "coverage": True, "grounding": 1.0, "tool_count": 2, "tokens": 100,
             "duration_ms": 1000, "path": "knowledge_single",
             "telemetry": {"llm_ms": 300.0, "tool_ms": 200, "orch_ms": 500.0,
                           "llm_calls": 3, "prompt_tokens": 900,
                           "completion_tokens": 100, "closure_ok": True}},
            {"pass": False, "tool_correct": False, "no_extra": True, "args_ok": True,
             "coverage": False, "grounding": None, "tool_count": 1, "tokens": 50,
             "duration_ms": 500, "path": "casual",
             "telemetry": {"llm_ms": 200.0, "tool_ms": 0, "orch_ms": 300.0,
                           "llm_calls": 2, "prompt_tokens": 400,
                           "completion_tokens": 50, "closure_ok": False}},
        ]
        scores = pt.round_scores(LOOP_HAND, per_q, 2)
        assert scores["module"] == "092" and scores["loop"] == "hand"
        assert scores["llm_ms_total"] == 500.0
        assert scores["tool_ms_total"] == 200
        assert scores["orch_ms_total"] == 800.0
        assert scores["llm_calls"] == 5
        assert scores["prompt_tokens"] == 1300
        assert scores["completion_tokens"] == 150
        assert scores["closure_fail"] == 1


class TestColdStartSubprocess:
    """AC-8：子进程 import 计时（真实子进程，秒级可承受）"""

    def test_import_coldstart_positive_and_delta(self):
        out = pt.measure_import_coldstart(trials=1)
        assert out["hand"]["median"] > 0
        assert out["langgraph"]["median"] > 0
        assert out["delta_ms"] == round(
            out["langgraph"]["median"] - out["hand"]["median"], 1)
