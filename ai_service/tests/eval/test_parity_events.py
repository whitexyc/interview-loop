"""module-092 延伸：记录维度增强单测（parity_events）

覆盖：
- `answer_point_hits`：全命中 / 部分命中 / 全漏 / 空要点 / answer=None
- `failed_points`：挑出失分点 / 无失分返回空
- `quality_detail`：组合入口（含 item/result 缺字段的兜底）
- `capture_tool_events`：捕获 WARNING+ / 过滤 INFO / 退出后 handler 已移除
  / 采集异常 fail-open
- `summarize_events`：三类计数 / 重叠计数（"重试超时"同计 retry+timeout）
  / 空列表 / details 透传

实现说明：日志用例用独立 logger 名避免污染全局；同步用例内无异步。
"""
import logging
from unittest import mock

import pytest

from eval import parity_events


class TestAnswerPointHits:
    """答案要点命中（判定口径与 outcome_pass 一致：子串包含）"""

    def test_all_hit(self):
        hits = parity_events.answer_point_hits(["G1", "Region"], "G1 是分代收集器，用 Region 划分")
        assert hits == {"G1": True, "Region": True}

    def test_partial_hit(self):
        hits = parity_events.answer_point_hits(["G1", "Region"], "只提到 G1 的回收流程")
        assert hits == {"G1": True, "Region": False}
        assert parity_events.failed_points(hits) == ["Region"]

    def test_none_hit(self):
        hits = parity_events.answer_point_hits(["G1", "Region"], "完全不相关的内容")
        assert hits == {"G1": False, "Region": False}

    def test_empty_points(self):
        assert parity_events.answer_point_hits([], "任意答案") == {}
        assert parity_events.answer_point_hits(None, "任意答案") == {}

    def test_none_answer_treated_as_empty(self):
        """answer=None 时不应崩，且全部判未命中"""
        hits = parity_events.answer_point_hits(["G1"], None)
        assert hits == {"G1": False}

    def test_no_failed_points_when_all_hit(self):
        hits = parity_events.answer_point_hits(["A"], "答案是 A")
        assert parity_events.failed_points(hits) == []

    def test_failed_points_handles_none(self):
        assert parity_events.failed_points(None) == []


class TestQualityDetail:
    """组合入口"""

    def test_combines_hits_and_failed(self):
        item = {"answer_points": ["G1", "Region"]}
        result = {"answer": "G1 的分代回收"}
        out = parity_events.quality_detail(item, result)
        assert out["answer_points_hit"] == {"G1": True, "Region": False}
        assert out["failed_points"] == ["Region"]

    def test_missing_fields_fail_open(self):
        """item/result 缺字段时不抛异常（评测健壮性）"""
        assert parity_events.quality_detail({}, {}) == {
            "answer_points_hit": {}, "failed_points": []}
        assert parity_events.quality_detail(None, None) == {
            "answer_points_hit": {}, "failed_points": []}


class TestCaptureToolEvents:
    """日志侧事件捕获（零生产改动的旁路手段）"""

    @pytest.fixture
    def logger(self, monkeypatch):
        """隔离 logger 名，避免污染全局 agent.tool_registry"""
        name = "agent.tool_registry.test_events"
        monkeypatch.setattr(parity_events, "TOOL_LOGGER_NAME", name)
        lg = logging.getLogger(name)
        lg.setLevel(logging.DEBUG)
        return lg

    def test_captures_warning(self, logger):
        sink: list = []
        with parity_events.capture_tool_events(sink):
            logger.warning("工具 generate_answer 超时 (15.0s)")
        assert len(sink) == 1
        assert sink[0]["level"] == "WARNING"
        assert "超时" in sink[0]["msg"]

    def test_filters_info(self, logger):
        """INFO 级不应被采集（只关心异常事件）"""
        sink: list = []
        with parity_events.capture_tool_events(sink):
            logger.info("常规信息")
            logger.warning("工具 X 首次失败，自动重试")
        assert len(sink) == 1
        assert "自动重试" in sink[0]["msg"]

    def test_handler_removed_after_exit(self, logger):
        sink: list = []
        before = len(logger.handlers)
        with parity_events.capture_tool_events(sink):
            assert len(logger.handlers) == before + 1
        assert len(logger.handlers) == before      # 退出后必须移除

    def test_handler_removed_on_exception(self, logger):
        sink: list = []
        before = len(logger.handlers)
        with pytest.raises(RuntimeError):
            with parity_events.capture_tool_events(sink):
                raise RuntimeError("boom")
        assert len(logger.handlers) == before

    def test_emit_failure_is_logged_not_silent(self, caplog):
        """采集失败必须留痕（铁律 5：fail-open 可吞异常但不得静默）

        这是实现期自查发现的问题：初版用裸 `except Exception: pass`，
        与 parity_io 的 fail-open 先例（带 logger.warning）不一致。
        """
        broken_sink = mock.MagicMock()
        broken_sink.append.side_effect = RuntimeError("sink 不可写")
        handler = parity_events._EventSink(broken_sink)
        record = logging.LogRecord("x", logging.WARNING, __file__, 1,
                                   "工具 X 超时", None, None)
        with caplog.at_level(logging.WARNING, logger="parity_events"):
            handler.emit(record)          # 不得抛出
        assert any("fail-open" in r.message for r in caplog.records)


class TestSummarizeEvents:
    """事件聚合"""

    def test_counts_three_kinds(self):
        events = [
            {"level": "WARNING", "msg": "工具 generate_answer 超时 (15.0s)"},
            {"level": "WARNING", "msg": "工具 re_search 首次失败，自动重试: boom"},
            {"level": "WARNING", "msg": "工具 verify_answer 执行失败，返回空: x"},
        ]
        out = parity_events.summarize_events(events)
        assert out["timeout"] == 1
        assert out["retry"] == 1
        assert out["fail"] == 1
        assert out["total"] == 3

    def test_retry_timeout_counts_both(self):
        """'重试超时' 同时计入 retry 与 timeout（诊断含义不同）"""
        out = parity_events.summarize_events(
            [{"level": "WARNING", "msg": "工具 X 重试超时 (15.0s)"}])
        assert out["retry"] == 1
        assert out["timeout"] == 1

    def test_initial_failure_not_counted_as_final_fail(self):
        """'首次失败，自动重试' 只算 retry —— 重试可能成功，不得算作最终失败

        这是实现期踩到的坑：早期用裸 "失败" 泛匹配，会把触发重试的日志误计为
        最终失败，导致 fail 计数虚高。
        """
        out = parity_events.summarize_events(
            [{"level": "WARNING", "msg": "工具 X 首次失败，自动重试: boom"}])
        assert out["retry"] == 1
        assert out["fail"] == 0

    def test_retry_exhausted_counts_retry_and_fail(self):
        """'重试仍失败，返回空' = retry + fail（重试也失败即最终失败）"""
        out = parity_events.summarize_events(
            [{"level": "WARNING", "msg": "工具 X 重试仍失败，返回空: boom"}])
        assert out["retry"] == 1
        assert out["fail"] == 1

    def test_empty_events(self):
        out = parity_events.summarize_events([])
        assert out == {"timeout": 0, "retry": 0, "fail": 0, "total": 0,
                       "details": []}
        assert parity_events.summarize_events(None)["total"] == 0

    def test_details_preserved(self):
        events = [{"level": "WARNING", "msg": "工具 X 超时"}]
        assert parity_events.summarize_events(events)["details"] == events

    def test_unknown_message_falls_to_no_bucket(self):
        """不匹配任何关键词的日志只计 total，不进三类桶"""
        out = parity_events.summarize_events([{"level": "WARNING", "msg": "其他告警"}])
        assert out["total"] == 1
        assert (out["timeout"], out["retry"], out["fail"]) == (0, 0, 0)
