"""module-088：链路式观测单测（hermetic，不依赖真实 PG）

覆盖（验收 AC-1~AC-45 单测侧）：
- DDL：request_spans 文本口径（列/索引/COMMENT）+ ensure 拆分执行（AC-1/2）
- sanitize_incoming_trace：合法/归一/超长/非法/None（AC-8）
- span 原语：开关关零落库/无 trace 上下文跳过/根 span 字段/父子挂接/
  decision 截 500/fail-open/INSERT 参数化/读侧组树（AC-4~7/9/26/35）
- advance_phase reason 枚举（AC-15）+ 工具 span 三态（AC-17/18）
- 预算截断 span（AC-19）+ langgraph 透传（AC-16/22）
- trace 端点：200 形状/嵌套透传/不存在 code 1/异常 fail-open（AC-24/25/27/28/29）
- 传播：X-Trace-Id 接收/回退自生成/开关矩阵/health+429 零 span/隔离（AC-10~14/34/36/37）
- SSE done 带 trace_id（AC-30/31 机制）
- SQL hygiene：无拼接 + SELECT 只读（AC-7/28）
- 集成：一次请求一条 trace、根唯一、树深 ≥2、决策非空（AC-23）

实现说明：
- conftest autouse 钉住 trace_spans_enabled=false（存量零漂移）；本文件显式
  开启 + mock tracing._spawn_insert 捕获行（不依赖真实 task 完成，对齐
  test_observability / test_tool_call_logs / test_dashboard 打桩模式）
- 端点用例 httpx ASGITransport（对齐 test_observability 接线用例）
"""
import asyncio
import json
import re
from datetime import datetime
from unittest import mock

import httpx
import pytest

import main as main_module
from agent.langgraph_react import langgraph_react_loop
from agent.react import (
    ReactContext, _build_messages, advance_phase, execute_tool_with_log,
    react_loop,
)
from agent.tool_registry import ToolRegistry
from src import observability, tracing
from src.config import settings
from src.database import REQUEST_SPANS_DDL, ensure_request_spans_table


# ─── 打桩辅助（对齐 test_dashboard / test_tool_call_logs 模式） ───


class _FakeResult:
    """假 execute 返回：mappings() 可配置（读侧行）"""

    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def mappings(self):
        return list(self._rows)


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

    async def commit(self):
        pass


def _fake_factory(session):
    """把 async_session_factory 打桩成返回 session 的异步上下文管理器"""
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


def _enable_spans(monkeypatch) -> None:
    """显式开启链路式观测（conftest autouse 默认钉住 false）"""
    monkeypatch.setattr(settings, "trace_spans_enabled", True)


def _capture_spans(monkeypatch) -> list:
    """打桩 _spawn_insert 同步捕获待落库 span 行（不依赖真实 task 完成）"""
    rows: list = []
    monkeypatch.setattr(tracing, "_spawn_insert",
                        lambda row: rows.append(dict(row)))
    return rows


def _stub_tool(result="stub 结果", error: Exception | None = None):
    """假工具实例（真实注册表工具会触发 DB 检索，测试不用）"""

    class _Tool:
        async def run(self, args, ctx):
            if error:
                raise error
            return result

    return _Tool()


def _stub_registry() -> ToolRegistry:
    """两个 stub 工具注册表（检索组 + 生成组各一）"""

    async def _f(ctx, args):
        return "stub 结果"

    reg = ToolRegistry()
    reg.register("search_knowledge", "混合检索",
                 {"type": "object",
                  "properties": {"query": {"type": "string"}},
                  "required": ["query"]},
                 _f, group=["retrieval"])
    reg.register("generate_answer", "生成答案",
                 {"type": "object",
                  "properties": {"query": {"type": "string"}},
                  "required": ["query"]},
                 _f, group=["generation"])
    return reg


def _tool_call(name: str, args: dict, cid: str = "c1") -> dict:
    return {
        "content": "",
        "tool_calls": [{"id": cid, "name": name, "args": args}],
        "message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(args, ensure_ascii=False)}}],
        },
    }


def _answer(content: str) -> dict:
    return {"content": content, "tool_calls": [],
            "message": {"role": "assistant", "content": content}}


def _two_tool_calls() -> dict:
    """单轮响应携带 2 个 tool_calls（预算截断触发器：budget=1 → 执行 1）"""
    calls = [{"id": "c1", "name": "search_knowledge", "args": {"query": "a"}},
             {"id": "c2", "name": "search_knowledge", "args": {"query": "b"}}]
    return {
        "content": "",
        "tool_calls": calls,
        "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": c["id"], "type": "function",
                                    "function": {"name": c["name"],
                                                 "arguments": json.dumps(c["args"])}}
                                   for c in calls]},
    }


class _FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def chat_with_tools(self, messages, tools):
        return self.responses.pop(0)

    async def chat(self, messages):
        return "直接回答"


async def _collect(gen):
    """把异步生成器事件收进 list（测试辅助）"""
    return [evt async for evt in gen]


# ─── AC-1/2：DDL 文本 + 幂等 ensure ───


class TestDDL:
    """request_spans DDL 文本口径 + 拆分执行"""

    def test_ddl_text_columns_index_comment(self):
        """10 列齐 + CREATE TABLE/INDEX IF NOT EXISTS + COMMENT（AC-1/2）"""
        for col in ("trace_id", "span_id", "parent_span_id", "name", "kind",
                    "identity", "decision", "status", "duration_ms", "started_at"):
            assert col in REQUEST_SPANS_DDL
        assert "CREATE TABLE IF NOT EXISTS request_spans" in REQUEST_SPANS_DDL
        assert ("CREATE INDEX IF NOT EXISTS idx_request_spans_trace "
                "ON request_spans (trace_id)") in REQUEST_SPANS_DDL
        assert "COMMENT ON TABLE request_spans" in REQUEST_SPANS_DDL

    def test_ensure_splits_and_executes(self, monkeypatch):
        """ensure_request_spans_table 按 ';' 拆分逐条执行（CREATE+INDEX+COMMENT）"""
        session = _FakeSession()
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        asyncio.run(ensure_request_spans_table())
        sqls = [s for s, _ in session.executed]
        assert len(sqls) == 13  # CREATE TABLE + CREATE INDEX + 11 条 COMMENT
        assert any("CREATE TABLE IF NOT EXISTS request_spans" in s for s in sqls)
        assert any("CREATE INDEX IF NOT EXISTS idx_request_spans_trace" in s
                   for s in sqls)
        assert any("COMMENT ON TABLE request_spans" in s for s in sqls)


# ─── AC-8：入站 trace_id 清洗 ───


class TestSanitize:
    """sanitize_incoming_trace：白名单 + 归一 + 兜底"""

    def test_valid_hex_kept_verbatim(self):
        """合法小写 hex（含连字符）原样返回"""
        assert tracing.sanitize_incoming_trace("0123abcd") == "0123abcd"
        assert tracing.sanitize_incoming_trace(
            "0123abcd-0123abcd-0123abcd-0123abcd"
        ) == "0123abcd-0123abcd-0123abcd-0123abcd"

    def test_uppercase_normalized(self):
        """大写归一小写（A-F 合法字符）"""
        assert tracing.sanitize_incoming_trace("ABC123DEF") == "abc123def"

    def test_over_64_rejected(self):
        """超 64 字符 → 空串（回退自生成）"""
        assert tracing.sanitize_incoming_trace("a" * 64) == "a" * 64
        assert tracing.sanitize_incoming_trace("a" * 65) == ""

    def test_illegal_chars_rejected(self):
        """白名单外字符（g/斜杠/中缀空格）→ 空串"""
        assert tracing.sanitize_incoming_trace("gg123") == ""
        assert tracing.sanitize_incoming_trace("../evil") == ""
        assert tracing.sanitize_incoming_trace("abc 123") == ""
        assert tracing.sanitize_incoming_trace("<script>") == ""

    def test_none_and_blank_rejected(self):
        """None/空串/纯空白 → 空串（调用方回退 make_trace_id）"""
        assert tracing.sanitize_incoming_trace(None) == ""
        assert tracing.sanitize_incoming_trace("") == ""
        assert tracing.sanitize_incoming_trace("   ") == ""


# ─── AC-4~7/9/35：span 写侧原语 ───


class TestSpanPrimitives:
    """begin_request / record_span / _insert_span / 读侧"""

    def test_disabled_zero_rows_but_parent_set(self, monkeypatch):
        """开关关（conftest 默认）→ 零落库；父上下文仍 set（无害）"""
        rows = _capture_spans(monkeypatch)  # trace_spans_enabled 保持 False

        async def run():
            observability.init_request("t-off")
            sid = tracing.begin_request("t-off", "/x", "u1")
            tracing.record_span("advance_phase", "decision", decision="r")
            return sid, tracing._parent_var.get()

        sid, parent = asyncio.run(run())
        assert rows == []  # 零落库（AC-4）
        assert len(sid) == 16 and parent == sid

    def test_no_trace_context_skips(self, monkeypatch):
        """无 trace 上下文（get_trace_id()==""）→ record_span 静默跳过（AC-5）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def run():
            # 新 asyncio 上下文未 init_request → 无 trace 上下文
            tracing.record_span("advance_phase", "decision", decision="r")

        asyncio.run(run())
        assert rows == []  # 不落库不报错

    def test_begin_request_root_fields(self, monkeypatch):
        """根 span 字段：kind=request/parent=""/status=ok/duration=0/identity（AC-9）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def run():
            # begin_request 收进 asyncio.run：_parent_var.set 落在 task 上下文，
            # 不向 pytest 共享 context 泄漏"幽灵父"（Reviewer LOW-3 测试卫生）
            sid = tracing.begin_request("t1", "/ai/rag/chat", "u1")
            return sid, tracing._parent_var.get()

        sid, parent = asyncio.run(run())
        assert len(rows) == 1
        row = rows[0]
        assert row["trace_id"] == "t1"
        assert row["span_id"] == sid and len(sid) == 16
        assert row["parent_span_id"] == ""
        assert row["name"] == "/ai/rag/chat"
        assert row["kind"] == "request"
        assert row["identity"] == "u1"
        assert row["status"] == "ok" and row["duration_ms"] == 0
        assert row["decision"] == ""
        assert row["started_at"] is not None
        assert parent == sid  # 父上下文已压入（task 上下文内）

    def test_record_span_parent_is_root(self, monkeypatch):
        """record_span 行 parent_span_id == begin_request 返回值（AC-9）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def run():
            observability.init_request("t2")
            rid = tracing.begin_request("t2", "/agent", "u1")
            tracing.record_span("advance_phase", "decision",
                                decision="retrieval_hit:search_knowledge",
                                duration_ms=5)
            return rid

        rid = asyncio.run(run())
        assert len(rows) == 2
        child = rows[1]
        assert child["parent_span_id"] == rid
        assert child["trace_id"] == "t2"
        assert child["kind"] == "decision" and child["status"] == "ok"
        assert child["decision"] == "retrieval_hit:search_knowledge"
        assert child["duration_ms"] == 5

    def test_decision_truncated_to_500(self, monkeypatch):
        """超长 decision 截断 500（防撑爆列，AC-35）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def run():
            observability.init_request("t3")
            tracing.begin_request("t3", "/x")
            tracing.record_span("intent_routing", "decision", decision="x" * 700)

        asyncio.run(run())
        assert rows[1]["decision"] == "x" * 500

    def test_insert_span_fail_open(self, monkeypatch):
        """session 抛异常 → fail-open 不上抛（AC-6/38）"""
        _enable_spans(monkeypatch)
        broken = _FakeSession(execute_error=RuntimeError("数据库不可用"))
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(broken))
        row = {"trace_id": "t", "span_id": "s", "parent_span_id": "",
               "name": "n", "kind": "decision", "identity": "",
               "decision": "", "status": "ok", "duration_ms": 0,
               "started_at": datetime.utcnow()}
        asyncio.run(tracing._insert_span(row))  # 不抛异常即通过

    def test_insert_sql_fully_parametrized(self, monkeypatch):
        """INSERT 10 列全 :xxx 绑定 + started_at 为 Python 侧 datetime（AC-7）"""
        _enable_spans(monkeypatch)
        session = _FakeSession()
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        from datetime import datetime
        started = datetime.utcnow()
        row = {"trace_id": "t", "span_id": "s", "parent_span_id": "",
               "name": "n", "kind": "decision", "identity": "",
               "decision": "d", "status": "ok", "duration_ms": 1,
               "started_at": started}
        asyncio.run(tracing._insert_span(row))
        sql, params = session.executed[0]
        assert "INSERT INTO request_spans" in sql
        for col in ("trace_id", "span_id", "parent_span_id", "name", "kind",
                    "identity", "decision", "status", "duration_ms", "started_at"):
            assert f":{col}" in sql
        assert "{" not in sql and "}" not in sql  # 无 f-string 拼接
        assert set(params) == {c for c in ("trace_id", "span_id", "parent_span_id",
                                           "name", "kind", "identity", "decision",
                                           "status", "duration_ms", "started_at")}
        assert params["started_at"] == started  # Python 侧传入，非 DB default

    def test_get_trace_tree_reads_and_assembles(self, monkeypatch):
        """读侧：SELECT + mappings 行 → {trace_id, span_count, tree}；空 → None"""
        now = "2026-09-06T12:00:00"
        db_rows = [
            {"trace_id": "t9", "span_id": "root1", "parent_span_id": "",
             "name": "/x", "kind": "request", "identity": "u", "decision": "",
             "status": "ok", "duration_ms": 0, "started_at": now},
            {"trace_id": "t9", "span_id": "kid1", "parent_span_id": "root1",
             "name": "retrieval", "kind": "retrieval", "identity": "",
             "decision": "mode=hybrid docs=2", "status": "ok",
             "duration_ms": 9, "started_at": now},
        ]
        session = _FakeSession(results=[_FakeResult(rows=db_rows)])
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        out = asyncio.run(tracing.get_trace_tree("t9"))
        sql, params = session.executed[0]
        assert "SELECT trace_id, span_id" in sql and ":t" in sql
        assert params == {"t": "t9"}
        assert out["trace_id"] == "t9" and out["span_count"] == 2
        tree = out["tree"]
        assert len(tree) == 1 and tree[0]["span_id"] == "root1"
        assert tree[0]["children"][0]["span_id"] == "kid1"

        empty = _FakeSession(results=[_FakeResult(rows=[])])
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(empty))
        assert asyncio.run(tracing.get_trace_tree("t-none")) is None


# ─── AC-15：advance_phase reason 枚举 ───


class TestAdvancePhaseReason:
    """advance_phase 返回 reason（向后兼容：phase 语义逐字不变）"""

    def test_generation_branch_reason(self):
        """分支①：生成工具切换 → generation_tool_called"""
        ctx = ReactContext("q", "u1", [])
        reason = advance_phase(ctx, ["generate_answer"])
        assert reason == "generation_tool_called"
        assert ctx.phase == "generation"  # 存量语义不变

    def test_retrieval_hit_branch_reason(self):
        """分支②：检索命中 → retrieval_hit 开头 + 首个命中工具名"""
        ctx = ReactContext("q", "u1", [])
        reason = advance_phase(ctx, ["search_knowledge"],
                               ["[1] 文档 (score=0.9)\n真实内容"])
        assert reason.startswith("retrieval_hit")
        assert "search_knowledge" in reason
        assert ctx.phase == "generation"

    def test_idle_force_branch_reason(self, monkeypatch):
        """分支③：防空转强制切 → idle_force_rounds=<settings 值>"""
        monkeypatch.setattr(settings, "agent_retrieval_max_rounds", 2)
        ctx = ReactContext("q", "u1", [])
        assert advance_phase(ctx, ["search_knowledge"]) == ""  # rounds=1
        reason = advance_phase(ctx, ["search_knowledge"])      # rounds=2 → 强制
        assert reason == "idle_force_rounds=2"
        assert ctx.phase == "generation"

    def test_no_switch_empty_reason(self):
        """未切换 → ""（零 span 防噪音约定）"""
        ctx = ReactContext("q", "u1", [])
        assert advance_phase(ctx, ["search_knowledge"]) == ""
        assert ctx.phase == "retrieval"

    def test_old_signature_backward_compat(self):
        """存量语义：results=None 旧行为（仅生成工具判定，命中不判）"""
        ctx = ReactContext("q", "u1", [])
        assert advance_phase(ctx, ["search_knowledge"]) == ""  # 无 results 不判命中
        assert ctx.retrieval_rounds == 1   # 兜底计数照常递增
        assert advance_phase(ctx, ["re_search"]) == ""         # re_search 不触发
        assert advance_phase(ctx, ["generate_answer"]) == "generation_tool_called"
        assert advance_phase(ctx, ["re_search"]) == ""         # 不回退


# ─── AC-17/18：工具 span 三态（execute_tool_with_log 汇聚点） ───


class TestToolSpan:
    """execute_tool_with_log 工具 span：ok / blocked / error"""

    def _setup(self, monkeypatch) -> list:
        _enable_spans(monkeypatch)
        return _capture_spans(monkeypatch)

    def test_ok_status_with_phase_decision(self, monkeypatch):
        """正常执行 → status=ok，decision 含 phase=<ctx.phase>，duration 实测"""
        rows = self._setup(monkeypatch)

        async def run():
            observability.init_request("t-tool")
            tracing.begin_request("t-tool", "/agent", "u1")
            ctx = ReactContext("q")
            return await execute_tool_with_log("search_knowledge", {},
                                               _stub_tool(), ctx)

        asyncio.run(run())
        span = [r for r in rows if r["kind"] == "tool"][0]
        assert span["name"] == "search_knowledge"
        assert span["status"] == "ok"
        assert "phase=retrieval" in span["decision"]
        assert isinstance(span["duration_ms"], int) and span["duration_ms"] >= 0

    def test_blocked_status_with_rejection_reason(self, monkeypatch):
        """守门拒绝（权限白名单）→ status=blocked，decision 含拒绝原因 + phase"""
        rows = self._setup(monkeypatch)

        async def run():
            observability.init_request("t-block")
            tracing.begin_request("t-block", "/agent", "u1")
            ctx = ReactContext("q")
            return await execute_tool_with_log("search_knowledge", {},
                                               _stub_tool(), ctx,
                                               allowed_tools=set())

        asyncio.run(run())
        span = [r for r in rows if r["kind"] == "tool"][0]
        assert span["status"] == "blocked"
        assert "白名单" in span["decision"]   # 拒绝原因原文
        assert "phase=retrieval" in span["decision"]

    def test_error_status_on_run_exception(self, monkeypatch):
        """run 抛异常 → status=error（decision 仅 phase，无拒绝原因）"""
        rows = self._setup(monkeypatch)

        async def run():
            observability.init_request("t-err")
            tracing.begin_request("t-err", "/agent", "u1")
            ctx = ReactContext("q")
            return await execute_tool_with_log(
                "search_knowledge", {},
                _stub_tool(error=RuntimeError("boom")), ctx)

        asyncio.run(run())
        span = [r for r in rows if r["kind"] == "tool"][0]
        assert span["status"] == "error"
        assert span["decision"] == "phase=retrieval"


# ─── AC-19：预算截断 span（仅手写 react_loop） ───


class TestBudgetTruncateSpan:
    """react_loop 预算截断 → budget_truncate span"""

    def test_truncate_span_recorded(self, monkeypatch):
        """假 LLM 单轮提议 2 执行 1（budget=1）→ span 存在且 decision 含 proposed/executed"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr(
            "agent.react.LLMFactory.get_client",
            mock.Mock(return_value=_FakeLLM([_two_tool_calls()])))
        with mock.patch("agent.react.reflector.generate_answer",
                        mock.AsyncMock(return_value="兜底答案")):
            ctx = ReactContext("什么是RRF")

            async def run():
                observability.init_request("t-budget")
                tracing.begin_request("t-budget", "/agent", "u1")
                await _collect(react_loop(ctx, _build_messages(ctx), budget=1,
                                          tools=_stub_registry()))

            asyncio.run(run())
        span = [r for r in rows if r["name"] == "budget_truncate"]
        assert len(span) == 1
        assert span[0]["kind"] == "decision"
        assert span[0]["decision"] == "proposed=2 executed=1"

    def test_no_truncate_zero_span(self, monkeypatch):
        """未截断（提议 1 执行 1）→ 零 budget_truncate span"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr(
            "agent.react.LLMFactory.get_client",
            mock.Mock(return_value=_FakeLLM([
                _tool_call("search_knowledge", {"query": "RRF"}, "c1"),
                _answer("答案"),
            ])))
        ctx = ReactContext("什么是RRF")

        async def run():
            observability.init_request("t-notrunc")
            tracing.begin_request("t-notrunc", "/agent", "u1")
            await _collect(react_loop(ctx, _build_messages(ctx), budget=4,
                                      tools=_stub_registry()))

        asyncio.run(run())
        assert [r for r in rows if r["name"] == "budget_truncate"] == []


# ─── AC-16/22：langgraph 透传（advance_phase span 经共享函数） ───


class TestLanggraphPassthrough:
    """langgraph_react_loop advance_phase reason span 透传"""

    def test_langgraph_advance_phase_span(self, monkeypatch):
        """命中切阶段 → advance_phase span（langgraph 侧 ~4 行透传）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr(
            "agent.langgraph_react.LLMFactory.get_client",
            mock.Mock(return_value=_FakeLLM([
                _tool_call("search_knowledge", {"query": "RRF"}, "c1"),
                _answer("最终答案"),
            ])))
        ctx = ReactContext("什么是RRF")

        async def run():
            observability.init_request("t-lg")
            tracing.begin_request("t-lg", "/agent-lg", "u1")
            await _collect(langgraph_react_loop(ctx, _build_messages(ctx),
                                                budget=2,
                                                tools=_stub_registry()))

        asyncio.run(run())
        spans = [r for r in rows if r["name"] == "advance_phase"]
        assert len(spans) == 1
        assert spans[0]["decision"].startswith("retrieval_hit")
        assert spans[0]["parent_span_id"] != ""  # 挂根 span 下（非孤儿）


# ─── _build_tree 纯函数（AC-26） ───


class TestBuildTree:
    """_build_tree：单根 / 孤儿挂根 / 多根容忍"""

    @staticmethod
    def _row(span_id, parent="", name="n", kind="decision"):
        return {"trace_id": "t", "span_id": span_id, "parent_span_id": parent,
                "name": name, "kind": kind, "identity": "", "decision": "",
                "status": "ok", "duration_ms": 0, "started_at": "2026-09-06"}

    def test_single_root_child_nested(self):
        """正常数据：根 span（parent=""）恰 1 个，子 span 挂 children"""
        rows = [self._row("r", "", "root", "request"),
                self._row("c1", "r", "tool", "tool"),
                self._row("c2", "r", "decision", "decision")]
        tree = tracing._build_tree(rows)
        assert len(tree) == 1
        assert tree[0]["name"] == "root"
        assert [c["name"] for c in tree[0]["children"]] == ["tool", "decision"]

    def test_orphan_treated_as_root(self):
        """孤儿（parent 指向不存在的 span）→ 视为根，不丢行"""
        rows = [self._row("r", "", "root", "request"),
                self._row("ghost-child", "missing-parent", "orphan")]
        tree = tracing._build_tree(rows)
        assert len(tree) == 2
        assert {n["name"] for n in tree} == {"root", "orphan"}

    def test_multi_root_tolerated(self):
        """异常数据多根 → 容忍返回列表（正常恰 1 根由写侧保证）"""
        rows = [self._row("r1", "", "root1", "request"),
                self._row("r2", "", "root2", "request")]
        tree = tracing._build_tree(rows)
        assert len(tree) == 2


# ─── AC-24/25/27/28/29：trace 端点 ───


class TestTraceEndpoint:
    """GET /ai/observability/trace/{trace_id}（ASGITransport）"""

    _TREE = [{
        "span_id": "a1b2c3d4e5f60718", "parent_span_id": "",
        "name": "/ai/rag/chat", "kind": "request", "identity": "user-1",
        "decision": "", "status": "ok", "duration_ms": 0,
        "started_at": "2026-09-06T12:00:00", "trace_id": "t1",
        "children": [
            {"span_id": "kid", "parent_span_id": "a1b2c3d4e5f60718",
             "name": "intent_routing", "kind": "decision", "identity": "",
             "decision": "intent=knowledge reason=L4 classifier",
             "status": "ok", "duration_ms": 420,
             "started_at": "2026-09-06T12:00:01", "trace_id": "t1",
             "children": []},
        ],
    }]

    @staticmethod
    def _get(path: str):
        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.get(path)

        return asyncio.run(run())

    def test_200_code0_contract_shape(self, monkeypatch):
        """200 + {code:0, msg:success, data:{trace_id, span_count, tree}}（AC-24/29）"""
        monkeypatch.setattr(tracing, "get_trace_tree",
                            mock.AsyncMock(return_value={
                                "trace_id": "t1", "span_count": 2,
                                "tree": self._TREE}))
        resp = self._get("/ai/observability/trace/t1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["msg"] == "success"
        assert set(body["data"]) == {"trace_id", "span_count", "tree"}
        assert body["data"]["span_count"] == 2

    def test_tree_nested_passthrough(self, monkeypatch):
        """data.tree 原样透传（children 嵌套字段名与 plan §7 契约逐字一致，AC-25）"""
        monkeypatch.setattr(tracing, "get_trace_tree",
                            mock.AsyncMock(return_value={
                                "trace_id": "t1", "span_count": 2,
                                "tree": self._TREE}))
        body = self._get("/ai/observability/trace/t1").json()
        node = body["data"]["tree"][0]
        for key in ("span_id", "parent_span_id", "name", "kind", "identity",
                    "decision", "status", "duration_ms", "started_at", "children"):
            assert key in node
        assert node["children"][0]["name"] == "intent_routing"

    def test_trace_not_found_code_1(self, monkeypatch):
        """trace 不存在 → 200 + code 1 "trace 不存在"，不 500（AC-27）"""
        monkeypatch.setattr(tracing, "get_trace_tree",
                            mock.AsyncMock(return_value=None))
        resp = self._get("/ai/observability/trace/none")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"code": 1, "msg": "trace 不存在"}

    def test_query_exception_fail_open(self, monkeypatch):
        """get_trace_tree 抛异常 → 200 + code 1 fail-open，不 500（AC-28/38）"""
        monkeypatch.setattr(tracing, "get_trace_tree",
                            mock.AsyncMock(side_effect=RuntimeError("数据库不可用")))
        resp = self._get("/ai/observability/trace/t1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert body["msg"] == "trace 查询失败（fail-open）"


# ─── AC-10~14/34/36/37：中间件传播 + 零 span 边界 ───


class TestPropagation:
    """中间件 088 块：X-Trace-Id 接收 / 回退 / 开关矩阵 / 位置语义"""

    @staticmethod
    def _post_chat(headers=None):
        """POST /ai/rag/chat（mock 引擎；sleep 放行 fire-and-forget 落库任务）"""
        from rag.schemas import ChatResponse

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                resp = await client.post("/ai/rag/chat",
                                         json={"query": "线程池", "history": []},
                                         headers=headers or {})
            await asyncio.sleep(0.05)  # 让后台落库任务完成（test_observability 同款）
            return resp

        return asyncio.run(run())

    @staticmethod
    def _patch_engine():
        """mock rag_engine.chat + 会话缓存写入（端点最轻路径）"""
        from rag.schemas import ChatResponse
        return (
            mock.patch("rag.engine.rag_engine.chat",
                       new=mock.AsyncMock(return_value=ChatResponse(
                           answer="答案", sources=[], message="ok"))),
            mock.patch("main.save_messages_to_session"),
        )

    def test_valid_header_propagates_both_sides(self, monkeypatch):
        """合法 X-Trace-Id → 根 span 与 request_logs 同 trace_id（AC-10/12）"""
        _enable_spans(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        rows = _capture_spans(monkeypatch)
        save_mock = mock.AsyncMock()
        eng, sess = self._patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = self._post_chat({"X-Trace-Id": "0123abcd"})
        assert resp.status_code == 200
        root = [r for r in rows if r["kind"] == "request"][0]
        assert root["trace_id"] == "0123abcd"
        assert root["name"] == "/ai/rag/chat"
        assert root["identity"]  # user_id 优先 client_ip 兜底（048 口径）
        assert save_mock.called
        assert save_mock.call_args[0][0]["trace_id"] == "0123abcd"  # AC-12 同值

    def test_invalid_header_falls_back_to_generated(self, monkeypatch):
        """非法 header（../evil）→ 自生成 32 位小写 hex（AC-11/39）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        eng, sess = self._patch_engine()
        with eng, sess:
            resp = self._post_chat({"X-Trace-Id": "../evil"})
        assert resp.status_code == 200
        root = [r for r in rows if r["kind"] == "request"][0]
        assert root["trace_id"] != "../evil"
        assert len(root["trace_id"]) == 32
        assert root["trace_id"] == root["trace_id"].lower()
        assert re.fullmatch(r"[0-9a-f]+", root["trace_id"])

    def test_disabled_058_behavior_verbatim(self, monkeypatch):
        """开关关（AC-13）：无根 span，058 块生成 trace_id 行为逐字不变"""
        rows = _capture_spans(monkeypatch)  # trace_spans_enabled 保持 False
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        save_mock = mock.AsyncMock()
        eng, sess = self._patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = self._post_chat({"X-Trace-Id": "0123abcd"})
        assert resp.status_code == 200
        assert rows == []                       # 零根 span
        record = save_mock.call_args[0][0]
        assert len(record["trace_id"]) == 32    # 058 自生成（header 不消费）
        assert record["trace_id"] != "0123abcd"

    def test_matrix_spans_on_logs_off(self, monkeypatch):
        """开关矩阵②：request_logs=false + spans=true → spans 照常落库（AC-36）"""
        _enable_spans(monkeypatch)  # request_logs 保持 conftest 钉住的 false
        rows = _capture_spans(monkeypatch)
        save_mock = mock.AsyncMock()
        eng, sess = self._patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = self._post_chat()
        assert resp.status_code == 200
        root = [r for r in rows if r["kind"] == "request"][0]
        assert len(root["trace_id"]) == 32      # 088 块自生成
        assert not save_mock.called             # request_logs 零落库

    def test_health_zero_span(self, monkeypatch):
        """/ai/health 零 span（088 块在 health 早期 return 之后——位置锁，AC-34）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.get("/ai/health")

        resp = asyncio.run(run())
        assert resp.status_code == 200
        assert rows == []

    def test_429_zero_span(self, monkeypatch):
        """限流 429 零 span（088 块在限流短路之后——位置锁，AC-34）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr(main_module, "check_rate_limit",
                            lambda ip, **kw: (False, 5))
        eng, sess = self._patch_engine()
        with eng, sess:
            resp = self._post_chat({"X-Trace-Id": "0123abcd"})
        assert resp.status_code == 429
        assert rows == []  # 限流请求不进链路

    def test_two_requests_trace_isolation(self, monkeypatch):
        """两请求不同 header → 各自 span trace_id 不串（AC-37）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        eng, sess = self._patch_engine()
        with eng, sess:
            self._post_chat({"X-Trace-Id": "aaaa0000aaaa0000aaaa0000aaaa0000"})
            self._post_chat({"X-Trace-Id": "bbbb1111bbbb1111bbbb1111bbbb1111"})
        roots = [r for r in rows if r["kind"] == "request"]
        assert [r["trace_id"] for r in roots] == [
            "aaaa0000aaaa0000aaaa0000aaaa0000",
            "bbbb1111bbbb1111bbbb1111bbbb1111"]

    def test_chat_stream_intent_routing_span(self, monkeypatch):
        """流式路径（chat_stream 自行路由）intent_routing span（AC-20 双路径锁，
        Reviewer MAJOR-1 修复实证：无 docs 兜底最轻链 root+intent_routing）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr("main.resolve_tool_history",
                            mock.AsyncMock(return_value=None))
        monkeypatch.setattr("agent.router.router_agent.classify", mock.AsyncMock(
            return_value={"intent": "knowledge", "confidence": 0.97,
                          "reason": "L4 classifier {knowledge: 0.97}"}))
        monkeypatch.setattr("rag.engine.rag_engine._retrieve",
                            mock.AsyncMock(return_value=[]))
        monkeypatch.setattr("main.schedule_stream_persist", mock.Mock())
        monkeypatch.setattr("rag.engine.rag_engine._schedule_session_persist",
                            mock.Mock())
        fake_client = mock.MagicMock()

        async def fake_stream(prompt):
            yield "知识库暂无"
            yield "兜底回答"

        fake_client.generate_stream = fake_stream
        monkeypatch.setattr("llm.client.LLMFactory.get_client",
                            mock.Mock(return_value=fake_client))
        header = "abcd1234abcd1234abcd1234abcd1234"

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.post("/ai/rag/chat/stream",
                                         json={"query": "线程池", "history": []},
                                         headers={"X-Trace-Id": header})

        resp = asyncio.run(run())
        assert resp.status_code == 200
        roots = [r for r in rows if r["kind"] == "request"]
        assert roots and roots[0]["trace_id"] == header
        intent_spans = [r for r in rows if r["name"] == "intent_routing"]
        assert len(intent_spans) == 1
        assert intent_spans[0]["kind"] == "decision"
        assert intent_spans[0]["decision"].startswith("intent=knowledge")
        assert "L4 classifier" in intent_spans[0]["decision"]  # router reason 原文
        assert intent_spans[0]["parent_span_id"] == roots[0]["span_id"]  # 挂根下


# ─── AC-30/31：SSE done 事件带 trace_id ───


class TestSSETraceId:
    """done payload trace_id：_build_done_event extra 吸收 + agent 端点直拼点"""

    def test_build_done_event_absorbs_trace_id(self):
        """_build_done_event 签名不改，**extra 吸收 trace_id（AC-30 机制）"""
        raw = main_module._build_done_event([], verified=False, trace_id="t-x")
        assert raw.startswith("event: done\ndata: ")
        payload = json.loads(raw.split("data: ", 1)[1].strip())
        assert payload["trace_id"] == "t-x"
        assert payload["sources"] == [] and payload["verified"] is False

    def test_agent_done_carries_trace_id(self, monkeypatch):
        """agent 端点 done payload 含 trace_id == header（AC-31，最轻路径）"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)

        async def fake_loop(*a, **k):
            yield {"type": "done", "answer": "答案", "tool_count": 0}

        monkeypatch.setattr("agent.react.react_loop", fake_loop)
        monkeypatch.setattr("rag.engine.rag_engine._resolve_session_history",
                            mock.AsyncMock(return_value=[]))
        monkeypatch.setattr("rag.engine.rag_engine._schedule_session_persist",
                            mock.Mock())
        header = "abcd1234abcd1234abcd1234abcd1234"

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.post("/ai/rag/chat/agent",
                                         json={"query": "q", "history": []},
                                         headers={"X-Trace-Id": header})

        resp = asyncio.run(run())
        assert resp.status_code == 200
        done = [e for e in resp.text.split("\n\n")
                if e.startswith("event: done")][0]
        payload = json.loads(done.split("data: ", 1)[1])
        assert payload["trace_id"] == header
        assert [r for r in rows if r["kind"] == "request"][0]["trace_id"] == header


# ─── AC-7/28：SQL hygiene ───


class TestSQLHygiene:
    """INSERT 参数化 / SELECT 只读"""

    def test_insert_no_interpolation(self):
        """_SQL_INSERT 无 f-string/% 拼接残留，仅 :xxx 绑定"""
        sql = tracing._SQL_INSERT
        assert "{" not in sql and "}" not in sql
        assert "%s" not in sql and "%(" not in sql and "%d" not in sql
        assert "VALUES" in sql and ":trace_id" in sql and ":started_at" in sql

    def test_select_read_only(self):
        """_SQL_SELECT 全程只读：无写语句关键字（词边界防 started_at 误报）"""
        write_re = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b")
        assert write_re.search(tracing._SQL_SELECT) is None


# ─── AC-23：集成终证（一次请求一条 trace，父 span 含决策原因） ───


class TestOneRequestOneTrace:
    """真实 react_loop 全链路 span 树（hermetic：假 LLM + 捕获 _spawn_insert）"""

    def test_root_unique_tree_depth_and_decision(self, monkeypatch):
        """全部 span 同 trace_id + 根恰 1 + 树深 ≥2 + advance_phase 决策非空"""
        _enable_spans(monkeypatch)
        rows = _capture_spans(monkeypatch)
        monkeypatch.setattr(
            "agent.react.LLMFactory.get_client",
            mock.Mock(return_value=_FakeLLM([
                _tool_call("search_knowledge", {"query": "RRF"}, "c1"),
                _answer("最终答案"),
            ])))
        ctx = ReactContext("什么是RRF")

        async def run():
            observability.init_request("t-int-1")
            tracing.begin_request("t-int-1", "/ai/rag/chat/agent", "u1")
            await _collect(react_loop(ctx, _build_messages(ctx), budget=2,
                                      tools=_stub_registry()))

        asyncio.run(run())
        # 一次请求一条 trace：全部 span 同 trace_id
        assert rows and all(r["trace_id"] == "t-int-1" for r in rows)
        # 根 span（kind=request）恰 1 个
        roots = [r for r in rows if r["kind"] == "request"]
        assert len(roots) == 1
        # 树深 ≥2 且父 span 含决策原因（advance_phase decision 非空）
        tree = tracing._build_tree(sorted(rows, key=lambda r: r["started_at"]))
        assert len(tree) == 1
        child_names = {c["name"] for c in tree[0]["children"]}
        assert {"search_knowledge", "advance_phase"} <= child_names
        adv = [r for r in rows if r["name"] == "advance_phase"][0]
        assert adv["decision"]  # 非空（retrieval_hit:search_knowledge）
        assert adv["parent_span_id"] == roots[0]["span_id"]
        # 未截断 → 无 budget_truncate（零噪音）
        assert [r for r in rows if r["name"] == "budget_truncate"] == []
