"""module-085 WP-C：可观测看板读侧聚合单测（hermetic，不依赖真实 PG）

覆盖（验收 AC-1~AC-14 + AC-33/34）：
- 行→dict 纯函数：requests 求和/全错/空窗口/round 精度、latency 数组行/NULL/
  单样本、cost 分桶求和/缺键防御、tools 分组/失败计数/空窗口
- get_dashboard_metrics：4 条 SQL 顺序执行 + 文本口径断言（percentile_cont /
  jsonb_each_text / jsonb_each）+ 全参数化（仅 :since 绑定）+ hours 偏移 /
  hours=0 → 1970 + 返回四键齐 + window ISO 字段 + 异常向上抛（端点层统一
  fail-open，聚合层不吞）
- 端点 GET /ai/observability/dashboard：200 形状四指标键齐 / 聚合结果原样
  透传 / hours 缺省 24 与透传 / 非法 hours code 1 零触达 / 聚合异常
  fail-open code 1 不 500 / 非 int 422（FastAPI 既有行为）
- SQL hygiene：无 f-string/format/% 拼接残留 + 全程只读（无写语句关键字）

实现说明：
- _FakeSession 按序弹出预置结果并记录 (SQL, 参数)（对齐 test_tool_call_logs
  / test_observability 假 session 打桩模式）；端点用例 httpx ASGITransport +
  monkeypatch main.get_dashboard_metrics（对齐 test_observability 接线用例）
"""
import asyncio
import copy
import re
from datetime import datetime, timedelta
from unittest import mock

import httpx
import pytest

import main as main_module
from src import dashboard

# 响应契约 fixture（字段名与 plan §8 逐字一致，勿改）
_FIXTURE = {
    "window": {"hours": 24, "since": "2026-09-05T12:00:00",
               "generated_at": "2026-09-06T12:00:00"},
    "requests": {"total": 31, "errors": 1, "success_rate": 0.9677,
                 "by_endpoint": [{"endpoint": "chat_stream", "total": 14,
                                  "errors": 0}]},
    "latency": {"p50_ms": 4100.5, "p95_ms": 8200.0, "samples": 30},
    "cost": {"total_prompt": 123456, "total_completion": 23456,
             "by_provider": [{"provider": "deepseek", "prompt_tokens": 100000,
                              "completion_tokens": 20000},
                             {"provider": "llm", "prompt_tokens": 23456,
                              "completion_tokens": 3456}]},
    "tools": {"total": 467,
              "by_tool": [{"tool_name": "search_knowledge", "calls": 285,
                           "failures": 0, "duration_p95_ms": 4200.0}]},
}

_SQLS = (dashboard._SQL_REQUESTS, dashboard._SQL_LATENCY,
         dashboard._SQL_COST, dashboard._SQL_TOOLS)


class _FakeResult:
    """假 execute 返回：fetchall / first 可配置"""

    def __init__(self, rows=None, first=None):
        self._rows = list(rows or [])
        self._first = first

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._first


class _FakeSession:
    """假 AsyncSession：按 execute 顺序弹出预置结果并记录 (SQL, 参数)"""

    def __init__(self, results=None, execute_error: Exception | None = None):
        self.executed: list = []
        self._results = list(results or [])
        self._execute_error = execute_error

    async def execute(self, stmt, params=None):
        if self._execute_error:
            raise self._execute_error
        self.executed.append((str(stmt), params or {}))
        return self._results.pop(0) if self._results else _FakeResult()


def _fake_factory(session):
    """把 async_session_factory 打桩成返回 session 的异步上下文管理器"""
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


def _preset_results():
    """按 requests → latency → cost → tools 顺序预置一批非空结果"""
    return [
        _FakeResult(rows=[("chat_stream", 14, 0), ("agent", 7, 1)]),
        _FakeResult(first=([4100.5, 8200.0], 29)),
        _FakeResult(rows=[("deepseek", 100000, 20000), ("llm", 23456, 3456)]),
        _FakeResult(rows=[("search_knowledge", 285, 0, 4200.0)]),
    ]


class TestRowsToRequests:
    """_rows_to_requests：分组求和 / 全错 / 空窗口 / round 精度"""

    def test_sums_groups_and_rate(self):
        """总体行由分组行求和（不二次查询）；rate = round((total-errors)/total, 4)"""
        out = dashboard._rows_to_requests([("chat", 5, 0), ("agent", 7, 1)])
        assert out["total"] == 12 and out["errors"] == 1
        assert out["success_rate"] == round(11 / 12, 4)
        assert out["by_endpoint"] == [
            {"endpoint": "chat", "total": 5, "errors": 0},
            {"endpoint": "agent", "total": 7, "errors": 1}]

    def test_all_errors_rate_zero(self):
        """全错窗口 success_rate=0.0（有请求才有 0，不与空窗口 None 混淆）"""
        out = dashboard._rows_to_requests([("agent", 3, 3)])
        assert out["success_rate"] == 0.0

    def test_empty_window_rate_none(self):
        """空窗口 total=0 → success_rate=None（不伪造 0/1，AC-2/AC-15）"""
        assert dashboard._rows_to_requests([]) == {
            "total": 0, "errors": 0, "success_rate": None, "by_endpoint": []}

    def test_rate_rounded_to_4_places(self):
        """round 4 位精度（30 行 1 错 → 0.9667）"""
        out = dashboard._rows_to_requests([("chat", 30, 1)])
        assert out["success_rate"] == 0.9667


class TestRowsToLatency:
    """_rows_to_latency：数组行 / NULL → None / 单样本"""

    def test_percentile_array_row(self):
        """p[0]=P50、p[1]=P95 + 样本数如实透传"""
        out = dashboard._rows_to_latency(([4100.5, 8200.0], 29))
        assert out == {"p50_ms": 4100.5, "p95_ms": 8200.0, "samples": 29}

    def test_null_or_missing_row_none(self):
        """无行（row=None）/ 聚合零行（数组位 NULL）→ latency 整体 None（AC-3）"""
        assert dashboard._rows_to_latency(None) is None
        assert dashboard._rows_to_latency((None, 0)) is None

    def test_single_sample_p50_equals_p95(self):
        """单样本 percentile_cont 返回该行值（P50=P95，AC-21 口径）"""
        out = dashboard._rows_to_latency(([1200.0, 1200.0], 1))
        assert out == {"p50_ms": 1200.0, "p95_ms": 1200.0, "samples": 1}


class TestRowsToCost:
    """_rows_to_cost：分桶 / 求和 / 空窗口 / 缺键防御"""

    def test_buckets_and_totals(self):
        """按供应商分桶 + total 为各桶求和（历史桶 'llm' 原样保留不合并，AC-4/17）"""
        out = dashboard._rows_to_cost([("deepseek", 100000, 20000),
                                       ("llm", 23456, 3456)])
        assert out["total_prompt"] == 123456
        assert out["total_completion"] == 23456
        assert [b["provider"] for b in out["by_provider"]] == ["deepseek", "llm"]

    def test_null_completion_defense(self):
        """单桶缺 completion 键（SQL COALESCE 兜 0；纯函数 or-0 双保险，AC-23）"""
        out = dashboard._rows_to_cost([("deepseek", 100, None)])
        assert out["by_provider"][0] == {"provider": "deepseek",
                                         "prompt_tokens": 100,
                                         "completion_tokens": 0}
        assert out["total_completion"] == 0

    def test_empty_window(self):
        """空窗口 → 0 总量 + 空分桶列表（AC-20）"""
        assert dashboard._rows_to_cost([]) == {"total_prompt": 0,
                                               "total_completion": 0,
                                               "by_provider": []}


class TestRowsToTools:
    """_rows_to_tools：分组 / 失败计数 / 空窗口"""

    def test_grouped_rows(self):
        """calls 求和为 total；duration_p95_ms 如实透传（AC-5/18）"""
        out = dashboard._rows_to_tools([("search_knowledge", 285, 0, 4200.0),
                                        ("write_file", 2, 2, 15.5)])
        assert out["total"] == 287
        assert out["by_tool"][1] == {"tool_name": "write_file", "calls": 2,
                                     "failures": 2, "duration_p95_ms": 15.5}

    def test_failures_counted(self):
        """failures = result_ok=false 计数语义（SQL 已归一，纯函数透传）"""
        out = dashboard._rows_to_tools([("recall_memory", 24, 3, 100.0)])
        assert out["by_tool"][0]["failures"] == 3

    def test_empty_window(self):
        """空窗口 → total=0 + 空列表（AC-20）"""
        assert dashboard._rows_to_tools([]) == {"total": 0, "by_tool": []}


class TestGetDashboardMetrics:
    """get_dashboard_metrics：4 SQL 顺序 + 参数化 + 绑定值 + 结构 + 异常上抛"""

    def test_four_sqls_in_order_with_metric_semantics(self, monkeypatch):
        """按序执行 4 条 SQL（requests→latency→cost→tools）+ 文本口径断言（AC-7/8）"""
        session = _FakeSession(_preset_results())
        monkeypatch.setattr(dashboard, "async_session_factory",
                            _fake_factory(session))
        asyncio.run(dashboard.get_dashboard_metrics(24))

        assert len(session.executed) == 4
        req_sql, lat_sql, cost_sql, tool_sql = [s for s, _ in session.executed]
        assert "FROM request_logs" in req_sql
        assert "SUM(CASE WHEN error THEN 1 ELSE 0 END)" in req_sql
        assert "GROUP BY endpoint" in req_sql
        assert "percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP" in lat_sql
        assert "SUM((v)::float8) FROM jsonb_each_text(timings)" in lat_sql
        assert "WHERE total_ms IS NOT NULL" in lat_sql
        assert "jsonb_each(usage)" in cost_sql and "::bigint" in cost_sql
        assert ("percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)"
                in tool_sql)
        assert "SUM(CASE WHEN result_ok THEN 0 ELSE 1 END)" in tool_sql
        assert "FROM tool_call_logs" in tool_sql

    def test_only_since_bound_and_offset_by_hours(self, monkeypatch):
        """全参数化：唯一绑定参数 :since，值 = utcnow-hours（窗口随 hours 偏移，AC-1/6）"""
        session = _FakeSession(_preset_results())
        monkeypatch.setattr(dashboard, "async_session_factory",
                            _fake_factory(session))
        before = datetime.utcnow()
        asyncio.run(dashboard.get_dashboard_metrics(24))
        after = datetime.utcnow()
        assert len(session.executed) == 4
        for _, params in session.executed:
            assert set(params) == {"since"}
            assert before - timedelta(hours=24) <= params["since"] \
                <= after - timedelta(hours=24)

    def test_hours_zero_binds_epoch(self, monkeypatch):
        """hours=0 → :since 绑定 1970-01-01（全部数据窗口，AC-6）"""
        session = _FakeSession(_preset_results())
        monkeypatch.setattr(dashboard, "async_session_factory",
                            _fake_factory(session))
        out = asyncio.run(dashboard.get_dashboard_metrics(0))
        assert all(p["since"] == datetime(1970, 1, 1)
                   for _, p in session.executed)
        assert out["window"]["hours"] == 0

    def test_result_assembly_four_keys_and_window(self, monkeypatch):
        """返回 {window, requests, latency, cost, tools} 四指标齐 + window ISO 字段（AC-7）"""
        session = _FakeSession(_preset_results())
        monkeypatch.setattr(dashboard, "async_session_factory",
                            _fake_factory(session))
        before = datetime.utcnow()
        out = asyncio.run(dashboard.get_dashboard_metrics(24))
        after = datetime.utcnow()
        assert set(out) == {"window", "requests", "latency", "cost", "tools"}
        assert out["window"]["hours"] == 24
        assert before - timedelta(hours=24) <= datetime.fromisoformat(
            out["window"]["since"]) <= after - timedelta(hours=24)
        assert before <= datetime.fromisoformat(
            out["window"]["generated_at"]) <= after
        assert out["requests"]["total"] == 21
        assert out["latency"] == {"p50_ms": 4100.5, "p95_ms": 8200.0,
                                  "samples": 29}
        assert out["cost"]["total_prompt"] == 123456
        assert out["tools"]["total"] == 285

    def test_db_error_propagates(self, monkeypatch):
        """聚合层不吞异常（session.execute 抛错 → 同抛，端点层统一 fail-open，AC-9）"""
        session = _FakeSession(execute_error=RuntimeError("数据库不可用"))
        monkeypatch.setattr(dashboard, "async_session_factory",
                            _fake_factory(session))
        with pytest.raises(RuntimeError, match="数据库不可用"):
            asyncio.run(dashboard.get_dashboard_metrics(24))


class TestEndpoint:
    """端点 GET /ai/observability/dashboard（ASGITransport + mock 聚合函数）"""

    @staticmethod
    def _get(path: str) -> dict:
        """发起一次真实 app 请求并返回 JSON 体（同步封装，用例内直接断言）"""
        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                resp = await client.get(path)
            return resp

        resp = asyncio.run(run())
        return resp

    def test_200_shape_four_metric_keys(self, monkeypatch):
        """200 + {code:0, msg:success, data} 且四指标 + window 键齐（AC-10）"""
        agg = mock.AsyncMock(return_value=copy.deepcopy(_FIXTURE))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        resp = self._get("/ai/observability/dashboard?hours=24")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["msg"] == "success"
        assert set(body["data"]) == {"window", "requests", "latency", "cost",
                                     "tools"}

    def test_agg_result_verbatim_passthrough(self, monkeypatch):
        """data 与聚合函数返回 fixture 逐字一致，不被改写（AC-14）"""
        agg = mock.AsyncMock(return_value=copy.deepcopy(_FIXTURE))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        resp = self._get("/ai/observability/dashboard?hours=24")
        assert resp.json()["data"] == _FIXTURE

    def test_hours_default_and_passthrough(self, monkeypatch):
        """hours 缺省 24；168/720/0 原样透传聚合函数（AC-11）"""
        agg = mock.AsyncMock(return_value=copy.deepcopy(_FIXTURE))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        self._get("/ai/observability/dashboard")
        self._get("/ai/observability/dashboard?hours=168")
        self._get("/ai/observability/dashboard?hours=720")
        self._get("/ai/observability/dashboard?hours=0")
        assert agg.await_count == 4
        agg.assert_any_call(24)
        agg.assert_any_call(168)
        agg.assert_any_call(720)
        agg.assert_any_call(0)

    def test_invalid_hours_code_1_without_agg(self, monkeypatch):
        """hours=-1/8761 → code 1 提示"hours 参数非法"，不触达聚合函数（AC-12）"""
        agg = mock.AsyncMock(return_value=copy.deepcopy(_FIXTURE))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        for hours in ("-1", "8761"):
            body = self._get(
                f"/ai/observability/dashboard?hours={hours}").json()
            assert body["code"] == 1
            assert "hours 参数非法" in body["msg"]
        assert not agg.called

    def test_agg_exception_fail_open_no_500(self, monkeypatch):
        """聚合函数抛异常 → 200 + code 1 fail-open 提示，不 500（AC-13）"""
        agg = mock.AsyncMock(side_effect=RuntimeError("数据库不可用"))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        resp = self._get("/ai/observability/dashboard?hours=24")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert body["msg"] == "看板查询失败（fail-open）"

    def test_non_int_hours_422(self, monkeypatch):
        """hours=abc → FastAPI 422（既有行为，不特殊处理，AC-12）"""
        agg = mock.AsyncMock(return_value=copy.deepcopy(_FIXTURE))
        monkeypatch.setattr(main_module, "get_dashboard_metrics", agg)
        resp = self._get("/ai/observability/dashboard?hours=abc")
        assert resp.status_code == 422
        assert not agg.called


class TestSQLHygiene:
    """SQL hygiene：无拼接残留 + 全程只读（AC-1/33/34）"""

    def test_no_interpolation_artifacts(self):
        """4 条 SQL 仅 :since 绑定，无 f-string/.format/% 拼接残留"""
        for sql in _SQLS:
            assert ":since" in sql
            assert "{" not in sql and "}" not in sql
            assert "%s" not in sql and "%(" not in sql and "%d" not in sql

    def test_read_only_statements(self):
        """聚合全程只读：无任何写语句关键字（词边界防 created_at 误报，AC-33）"""
        write_re = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b")
        for sql in _SQLS:
            assert write_re.search(sql) is None
