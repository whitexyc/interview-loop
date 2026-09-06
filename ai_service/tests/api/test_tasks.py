"""module-087：任务抽象单测（hermetic，不依赖真实 PG）

覆盖（验收 AC-1~AC-26/28~38 单测侧）：
- DDL：tasks 文本口径（14 列/UNIQUE/索引/COMMENT）+ ensure 拆分执行（AC-1/2）
- 原语：begin_task 开关矩阵/INSERT 11 列全字段/finish failed·completed/
  WHERE status='running' 幂等/intent CASE/空 task_id no-op/finished_at
  Python 侧/所有权原语（AC-4~8/21/28/29/30）
- 中间件：四端点建 task/非白名单零 task/开关关零 task/trace 缺失跳过/
  429 零 task 位置锁（AC-10~13）
- persist 收口钩子：参数透传/独立于 logs 开关/state 无 task_id no-op（AC-14）
- 概览：obs 组装/无行 None/_SQL_OVERVIEW 只读词边界（AC-19/9）
- 端点：200 契约形状/不存在 code 1/异常 fail-open/obs 三键（AC-17/18）
- 记忆所有权闸：默认放行/read 拒绝 + warning/save_short+session 不受影响
  （AC-22~24）
- 集成：一次请求 = 1 task（恰 1 INSERT + 1 UPDATE，trace_id 三面同值，AC-15）
- SQL 卫生：三条 SQL 无拼接（AC-9）

实现说明：
- conftest autouse 钉住 tasks_enabled=false（存量零漂移）；本文件显式开启
  + mock src.tasks._spawn 同步捕获（不依赖真实 task 完成，对齐 test_tracing
  的 _capture_spans 打桩模式）
- 直调 begin_task/finish_task/所有权原语包 asyncio.run（088 LOW-3 教训：
  ContextVar 直调会向 pytest 共享上下文泄漏"幽灵 task"）
- 端点/中间件用例 httpx ASGITransport（对齐 test_observability / test_tracing）
"""
import asyncio
import re
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

import httpx

import main as main_module
from rag.memory.memory import memory_service
from rag.memory.session_memory import session_memory_service
from rag.schemas import ChatResponse
from src import observability, tasks, tracing
from src.config import settings
from src.database import TASKS_DDL, ensure_tasks_table


# ─── 打桩辅助（对齐 test_tracing / test_dashboard 模式） ───


class _FakeResult:
    """假 execute 返回：mappings().first() 可配置（读侧行）"""

    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def mappings(self):
        outer = self

        class _M:
            def first(self):
                return outer._rows[0] if outer._rows else None

        return _M()


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


def _enable_tasks(monkeypatch) -> None:
    """显式开启任务抽象（conftest autouse 默认钉住 false）"""
    monkeypatch.setattr(settings, "tasks_enabled", True)


def _capture(monkeypatch) -> list:
    """打桩 _spawn 同步捕获 (sql, params)（不依赖真实 task 完成）"""
    calls: list = []
    monkeypatch.setattr(tasks, "_spawn",
                        lambda sql, params: calls.append((sql, dict(params))))
    return calls


def _task_row() -> dict:
    """_SQL_OVERVIEW 形状的假行（13 列 + 3 计数）"""
    return {
        "task_id": "a" * 32, "parent_task_id": "", "trace_id": "f" * 32,
        "endpoint": "/ai/rag/chat", "intent": "knowledge",
        "status": "completed", "budget_token_limit": 0, "tokens_used": 1234,
        "memory_write": "write", "checkpoint": {}, "identity": "user-1",
        "created_at": "2026-09-06T12:00:00", "finished_at": "2026-09-06T12:00:03",
        "request_logs": 1, "request_spans": 7, "tool_calls": 3,
    }


def _overview_row() -> dict:
    """get_task_overview 返回形状（13 列 + obs 子 dict，三计数键已 pop）"""
    row = {k: v for k, v in _task_row().items()
           if k not in ("request_logs", "request_spans", "tool_calls")}
    row["obs"] = {"request_logs": 1, "request_spans": 7, "tool_calls": 3}
    return row


class _FakeReq:
    """persist_request_log 直调用假请求（state 经 SimpleNamespace 注入）"""

    def __init__(self, **state):
        self.state = SimpleNamespace(**state)


def _patch_engine():
    """mock rag_engine.chat + 会话缓存写入（端点最轻路径，对齐 test_tracing）"""
    return (
        mock.patch("rag.engine.rag_engine.chat",
                   new=mock.AsyncMock(return_value=ChatResponse(
                       answer="答案", sources=[], message="ok"))),
        mock.patch("main.save_messages_to_session"),
    )


def _post_chat(headers=None):
    """POST /ai/rag/chat（ASGITransport；sleep 放行 fire-and-forget 任务）"""

    async def run():
        transport = httpx.ASGITransport(app=main_module.app,
                                        raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://test") as client:
            resp = await client.post("/ai/rag/chat",
                                     json={"query": "线程池", "history": []},
                                     headers=headers or {})
        await asyncio.sleep(0.05)
        return resp

    return asyncio.run(run())


def _inserts(calls) -> list:
    return [p for s, p in calls if "INSERT INTO tasks" in s]


def _updates(calls) -> list:
    return [p for s, p in calls if "UPDATE tasks" in s]


# ─── AC-1/2：DDL 文本 + 幂等 ensure ───


class TestDDL:
    """tasks DDL 文本口径 + 拆分执行"""

    def test_ddl_text_columns_unique_index_comment(self):
        """14 列齐 + UNIQUE(task_id) + CREATE TABLE/INDEX IF NOT EXISTS + COMMENT"""
        for col in ("id", "task_id", "parent_task_id", "trace_id", "endpoint",
                    "intent", "status", "budget_token_limit", "tokens_used",
                    "memory_write", "checkpoint", "identity", "created_at",
                    "finished_at"):
            assert col in TASKS_DDL
        assert "CREATE TABLE IF NOT EXISTS tasks" in TASKS_DDL
        assert "task_id            VARCHAR(32)  NOT NULL UNIQUE" in TASKS_DDL
        assert "CREATE INDEX IF NOT EXISTS idx_tasks_trace ON tasks (trace_id)" \
            in TASKS_DDL
        assert "COMMENT ON TABLE tasks" in TASKS_DDL
        # 预算/checkpoint/所有权三列结构预留归属注释（AC-28/29 声明位）
        assert "module-089" in TASKS_DDL and "module-090" in TASKS_DDL
        assert "子只读父写" in TASKS_DDL

    def test_ensure_splits_and_executes(self, monkeypatch):
        """ensure_tasks_table 按 ';' 拆分逐条执行（CREATE+INDEX+COMMENT 15 条）"""
        session = _FakeSession()
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        asyncio.run(ensure_tasks_table())
        sqls = [s for s, _ in session.executed]
        assert len(sqls) == 15  # CREATE TABLE + CREATE INDEX + COMMENT 表 + 12 列 COMMENT
        assert any("CREATE TABLE IF NOT EXISTS tasks" in s for s in sqls)
        assert any("CREATE INDEX IF NOT EXISTS idx_tasks_trace" in s
                   for s in sqls)
        assert any("COMMENT ON TABLE tasks" in s for s in sqls)


# ─── AC-4~8/21/30：task 写侧原语 + 所有权原语 ───


class TestPrimitives:
    """begin_task / finish_task / set_memory_write_mode / memory_write_allowed"""

    def test_disabled_zero_rows_but_var_set(self, monkeypatch):
        """开关关（conftest 默认）→ 零落库；task 上下文仍 set；恒 32hex（AC-4）"""
        calls = _capture(monkeypatch)  # tasks_enabled 保持 False

        async def run():
            tid = tasks.begin_task("t-off", "/x", "u1")
            return tid, tasks._task_id_var.get()

        tid, var = asyncio.run(run())
        assert _inserts(calls) == [] and _updates(calls) == []  # 零落库
        assert len(tid) == 32 and re.fullmatch(r"[0-9a-f]+", tid)
        assert var == tid

    def test_enabled_insert_all_11_columns(self, monkeypatch):
        """开关开：INSERT 捕获 11 绑定列全字段；created_at 不在参数（DB default，AC-5）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)

        async def run():
            tid = tasks.begin_task("trace-1", "/ai/rag/chat", "u1")
            return tid

        tid = asyncio.run(run())
        rows = _inserts(calls)
        assert len(rows) == 1
        p = rows[0]
        assert set(p) == {
            "task_id", "parent_task_id", "trace_id", "endpoint", "intent",
            "status", "budget_token_limit", "tokens_used", "memory_write",
            "checkpoint", "identity"}
        assert p["task_id"] == tid and len(tid) == 32
        assert p["parent_task_id"] == ""      # v1 恒根（AC-30）
        assert p["trace_id"] == "trace-1"     # 透传（读侧 join 锚）
        assert p["endpoint"] == "/ai/rag/chat"
        assert p["intent"] == "" and p["status"] == "running"
        assert p["budget_token_limit"] == 0   # 0=不限（AC-29 结构）
        assert p["tokens_used"] == 0
        assert p["memory_write"] == "write"   # 默认父写（存量行为）
        assert p["checkpoint"] == "{}"        # JSONB 绑定须 JSON 字符串（asyncpg
        # 对 dict 调 .encode() 必炸 DataError——Tester 发现-1；与 DDL default 同值）
        assert p["identity"] == "u1"
        assert "created_at" not in p          # INSERT 不含该列（DB default）

    def test_finish_error_maps_status(self, monkeypatch):
        """error=True → failed；error=False → completed（AC-7）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)
        tasks.finish_task("a" * 32, intent="knowledge", error=True)
        tasks.finish_task("b" * 32, intent="agent")
        updates = _updates(calls)
        assert updates[0]["status"] == "failed"
        assert updates[1]["status"] == "completed"

    def test_finish_sql_idempotent_where_and_case(self):
        """_SQL_FINISH 文本：WHERE status='running' 幂等 + intent CASE 空串不覆盖（AC-7）"""
        assert "WHERE task_id = :task_id AND status = 'running'" in tasks._SQL_FINISH
        assert "CASE WHEN :intent <> '' THEN :intent ELSE intent END" \
            in tasks._SQL_FINISH
        assert "finished_at = :finished_at" in tasks._SQL_FINISH
        assert "checkpoint" not in tasks._SQL_FINISH  # 090 列不触碰（AC-28）
        assert "budget_token_limit" not in tasks._SQL_FINISH  # 089 列不执法

    def test_finish_empty_task_id_noop(self, monkeypatch):
        """空 task_id（未建 task 的请求）→ 首行 return 零落库零报错（AC-8）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)
        tasks.finish_task("")
        assert calls == []

    def test_finish_disabled_noop(self, monkeypatch):
        """开关关 → finish 首行 return 零落库（AC-8）"""
        calls = _capture(monkeypatch)  # tasks_enabled 保持 False
        tasks.finish_task("a" * 32, intent="knowledge")
        assert calls == []

    def test_finish_finished_at_python_side(self, monkeypatch):
        """finished_at 为 Python 侧 datetime.utcnow() 传入（AC-7）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)
        before = datetime.utcnow()
        tasks.finish_task("a" * 32)
        assert isinstance(_updates(calls)[0]["finished_at"], datetime)
        assert _updates(calls)[0]["finished_at"] >= before

    def test_memory_write_mode_primitives(self, monkeypatch):
        """默认放行 / read 拒绝 / 回置放行 / 非法值 no-op（AC-21）"""
        async def run():
            out = []
            out.append(tasks.memory_write_allowed())          # 默认 write
            tasks.set_memory_write_mode("read")
            out.append(tasks.memory_write_allowed())          # read 拒绝
            tasks.set_memory_write_mode("child")              # 非法 no-op
            out.append(tasks.memory_write_allowed())
            tasks.set_memory_write_mode("")                   # 非法 no-op
            out.append(tasks.memory_write_allowed())
            tasks.set_memory_write_mode("write")
            out.append(tasks.memory_write_allowed())          # 回置放行
            return out

        assert asyncio.run(run()) == [True, False, False, False, True]


# ─── AC-10~13：中间件挂接（建 task 面 + 边界） ───


class TestMiddleware:
    """中间件 087 块：白名单建 task / 零 task 边界 / 位置语义"""

    def test_chat_creates_task_with_full_fields(self, monkeypatch):
        """tasks on + chat → INSERT 捕获：task_id 32hex、trace_id==state.trace_id、
        endpoint、identity（AC-10）"""
        _enable_tasks(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        calls = _capture(monkeypatch)
        save_mock = mock.AsyncMock()
        eng, sess = _patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = _post_chat()
        assert resp.status_code == 200
        rows = _inserts(calls)
        assert len(rows) == 1
        p = rows[0]
        assert len(p["task_id"]) == 32
        # trace_id 与 state.trace_id 同值（save record 的 trace_id 同源 058 块）
        assert p["trace_id"] == save_mock.call_args[0][0]["trace_id"]
        assert p["endpoint"] == "/ai/rag/chat"
        assert p["identity"]  # resolve_identity 结果（user_id 优先 client_ip 兜底）

    def test_non_whitelist_path_zero_task(self, monkeypatch):
        """非白名单路径（/ai/memory/save）零 task（AC-11）"""
        _enable_tasks(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        calls = _capture(monkeypatch)
        monkeypatch.setattr(memory_service, "save",
                            mock.AsyncMock(return_value={"status": "saved"}))

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.post("/ai/memory/save",
                                         json={"content": "记忆内容"})

        resp = asyncio.run(run())
        assert resp.status_code == 200
        assert calls == []

    def test_tasks_disabled_zero_task(self, monkeypatch):
        """tasks off（conftest 默认）→ 全链路零 task 零收口（AC-12）"""
        calls = _capture(monkeypatch)  # tasks_enabled 保持 False
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        save_mock = mock.AsyncMock()
        eng, sess = _patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = _post_chat()
        assert resp.status_code == 200
        assert calls == []          # 零 INSERT 零 UPDATE
        assert save_mock.called     # 058 request_logs 行为逐字不变

    def test_trace_missing_skips_task(self, monkeypatch):
        """logs+spans 全关（state.trace_id 不存在）→ 零 task（AC-13 聚合锚缺失）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)
        eng, sess = _patch_engine()
        with eng, sess:
            resp = _post_chat()
        assert resp.status_code == 200
        assert calls == []

    def test_429_zero_task(self, monkeypatch):
        """限流 429 零 task（087 块在限流短路之后——位置锁，AC-11/10 反向）"""
        _enable_tasks(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        calls = _capture(monkeypatch)
        monkeypatch.setattr(main_module, "check_rate_limit",
                            lambda ip, **kw: (False, 5))
        eng, sess = _patch_engine()
        with eng, sess:
            resp = _post_chat()
        assert resp.status_code == 429
        assert calls == []


# ─── AC-14：persist 收口钩子 ───


class TestFinishHook:
    """persist_request_log → tasks.finish_task（stats 上移 + gate 前旁路）"""

    def test_finish_params_and_logs_path_intact(self, monkeypatch):
        """logs on：finish 参数透传（intent/error/tokens 汇总）且 record 落库
        照常（AC-14 + AC-16 既有语义不变）"""
        _enable_tasks(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        calls = _capture(monkeypatch)
        save_mock = mock.AsyncMock()

        async def run():
            observability.init_request("t-fin")
            observability.record_usage("deepseek", 10, 5)
            observability.record_usage("qwen", 2, 1)
            main_module.persist_request_log(
                _FakeReq(task_id="a" * 32, user_id="", client_ip="1.2.3.4"),
                "chat", intent="knowledge", error=False)

        with mock.patch.object(observability, "save_request_log", save_mock):
            asyncio.run(run())
        updates = _updates(calls)
        assert len(updates) == 1
        p = updates[0]
        assert p["task_id"] == "a" * 32
        assert p["intent"] == "knowledge"
        assert p["status"] == "completed"
        # tokens 汇总口径 = usage 各供应商 prompt+completion 之总和（10+5+2+1）
        assert p["tokens_used"] == 18
        assert save_mock.called  # request_logs 既有分支照常执行（AC-16）

    def test_finish_independent_of_logs_switch(self, monkeypatch):
        """logs off（conftest 默认）→ finish 仍执行（独立开关，AC-14）"""
        _enable_tasks(monkeypatch)
        assert settings.request_logs_enabled is False
        calls = _capture(monkeypatch)

        async def run():
            observability.init_request("t-nologs")
            main_module.persist_request_log(
                _FakeReq(task_id="b" * 32, user_id="", client_ip="1.2.3.4"),
                "chat_stream", intent="realtime", error=True)

        asyncio.run(run())
        updates = _updates(calls)
        assert len(updates) == 1
        assert updates[0]["status"] == "failed"
        assert updates[0]["intent"] == "realtime"
        assert updates[0]["tokens_used"] == 0  # usage 恒空（record_usage 短路）

    def test_state_without_task_id_noop(self, monkeypatch):
        """state 无 task_id（未建 task 的请求）→ finish no-op（AC-14）"""
        _enable_tasks(monkeypatch)
        calls = _capture(monkeypatch)

        async def run():
            observability.init_request("t-notask")
            main_module.persist_request_log(
                _FakeReq(user_id="", client_ip="1.2.3.4"),
                "chat", intent="knowledge", error=False)

        asyncio.run(run())
        assert _updates(calls) == []


# ─── AC-19/9：读侧概览聚合 ───


class TestOverview:
    """get_task_overview：obs 组装 / 无行 None / SQL 只读"""

    def test_overview_assembles_obs_subdict(self, monkeypatch):
        """单 SQL 行 → 13 列 + 三计数键 pop 进 obs 子 dict（AC-19）"""
        session = _FakeSession(results=[_FakeResult(rows=[_task_row()])])
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        out = asyncio.run(tasks.get_task_overview("a" * 32))
        sql, params = session.executed[0]
        assert "FROM tasks t" in sql and "WHERE t.task_id = :task_id" in sql
        assert params == {"task_id": "a" * 32}
        assert out["task_id"] == "a" * 32
        assert out["intent"] == "knowledge" and out["status"] == "completed"
        assert out["checkpoint"] == {}  # 原样透传（AC-28）
        # 三计数键已 pop 进 obs（顶层不再有 request_logs 等裸键）
        assert set(out["obs"]) == {"request_logs", "request_spans", "tool_calls"}
        assert out["obs"] == {"request_logs": 1, "request_spans": 7,
                              "tool_calls": 3}
        assert set(out) == {
            "task_id", "parent_task_id", "trace_id", "endpoint", "intent",
            "status", "budget_token_limit", "tokens_used", "memory_write",
            "checkpoint", "identity", "created_at", "finished_at", "obs"}

    def test_overview_none_when_missing(self, monkeypatch):
        """无行 → None（端点层转 code 1 "task 不存在"）"""
        session = _FakeSession(results=[_FakeResult(rows=[])])
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        assert asyncio.run(tasks.get_task_overview("z" * 32)) is None

    def test_overview_sql_read_only(self):
        """_SQL_OVERVIEW 只读：词边界断言无写语句（AC-9）"""
        write_re = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b")
        assert write_re.search(tasks._SQL_OVERVIEW) is None
        assert "WHERE r.trace_id = t.trace_id" in tasks._SQL_OVERVIEW
        assert "WHERE s.trace_id = t.trace_id" in tasks._SQL_OVERVIEW
        assert "WHERE c.trace_id = t.trace_id" in tasks._SQL_OVERVIEW


# ─── AC-17/18：task 概览端点 ───


class TestTaskEndpoint:
    """GET /ai/observability/task/{task_id}（ASGITransport）"""

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
        """200 + {code:0, msg:success, data: plan §7 字段名逐字}（AC-17）"""
        monkeypatch.setattr(tasks, "get_task_overview",
                            mock.AsyncMock(return_value=_overview_row()))
        resp = self._get("/ai/observability/task/" + "a" * 32)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0 and body["msg"] == "success"
        assert set(body["data"]) == {
            "task_id", "parent_task_id", "trace_id", "endpoint", "intent",
            "status", "budget_token_limit", "tokens_used", "memory_write",
            "checkpoint", "identity", "created_at", "finished_at", "obs"}

    def test_data_obs_three_keys(self, monkeypatch):
        """data.obs 三键 = 标量子查询计数（AC-17/19）"""
        monkeypatch.setattr(tasks, "get_task_overview",
                            mock.AsyncMock(return_value=_overview_row()))
        body = self._get("/ai/observability/task/" + "a" * 32).json()
        assert set(body["data"]["obs"]) == {
            "request_logs", "request_spans", "tool_calls"}

    def test_task_not_found_code_1(self, monkeypatch):
        """task 不存在 → 200 + code 1 "task 不存在"，不 500（AC-18）"""
        monkeypatch.setattr(tasks, "get_task_overview",
                            mock.AsyncMock(return_value=None))
        resp = self._get("/ai/observability/task/none")
        assert resp.status_code == 200
        assert resp.json() == {"code": 1, "msg": "task 不存在"}

    def test_query_exception_fail_open(self, monkeypatch):
        """DB 异常 → 200 + code 1 fail-open，不 500（AC-18）"""
        monkeypatch.setattr(tasks, "get_task_overview",
                            mock.AsyncMock(side_effect=RuntimeError("数据库不可用")))
        resp = self._get("/ai/observability/task/" + "a" * 32)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert body["msg"] == "task 查询失败（fail-open）"


# ─── AC-22~24：长期记忆所有权闸 ───


class TestMemoryGate:
    """MemoryService.save 入口闸（"子只读父写"，WP-D）"""

    def test_save_allowed_by_default(self, monkeypatch):
        """默认 write → _save 被调、返回语义逐字不变（AC-22）"""
        save_mock = mock.AsyncMock(return_value={"status": "saved"})
        monkeypatch.setattr(memory_service, "_save", save_mock)
        out = asyncio.run(memory_service.save("用户喜欢摄影", "u1"))
        assert out == {"status": "saved"}
        assert save_mock.call_args[0][:2] == ("用户喜欢摄影", "u1")

    def test_save_blocked_in_read_mode(self, monkeypatch, caplog):
        """read 模式 → 不调 _save、返回 {"status":"blocked"}、warning 含
        "子只读父写"、不上抛（AC-23 fail-open）"""
        save_mock = mock.AsyncMock(return_value={"status": "saved"})
        monkeypatch.setattr(memory_service, "_save", save_mock)

        async def run():
            tasks.set_memory_write_mode("read")
            return await memory_service.save("用户喜欢摄影", "u1")

        with caplog.at_level("WARNING", logger="rag.memory.memory"):
            out = asyncio.run(run())
        assert out == {"status": "blocked"}
        assert not save_mock.called
        assert "子只读父写" in caplog.text

    def test_save_short_and_session_unaffected_in_read_mode(self, monkeypatch):
        """read 模式下 save_short 与 session_memory 写入不受影响（AC-24：
        闸只设 save 入口，不设 _save/save_short——plan §0.3）"""
        save_mock = mock.AsyncMock(return_value={"status": "updated"})
        monkeypatch.setattr(memory_service, "_save", save_mock)
        # rag.memory 被旧路径别名覆盖为普通模块（module-050 兼容机制），
        # 'import rag.memory.session_memory as m' 会撞属性遮蔽——经 sys.modules 取
        session_memory_module = sys.modules["rag.memory.session_memory"]
        session = _FakeSession()
        monkeypatch.setattr(session_memory_module, "async_session_factory",
                            _fake_factory(session))
        ingest_mock = mock.AsyncMock(return_value=2)
        monkeypatch.setattr(session_memory_service, "_ingest_messages",
                            ingest_mock)
        monkeypatch.setattr(session_memory_service, "_trim", mock.AsyncMock())

        async def run():
            tasks.set_memory_write_mode("read")
            short = await memory_service.save_short("临时事实", "u1")
            session_n = await session_memory_service.save_session_messages(
                "u1", [{"role": "user", "content": "q"},
                       {"role": "assistant", "content": "a"}])
            return short, session_n

        short, session_n = asyncio.run(run())
        assert short == {"status": "updated"}   # save_short 正常委托 _save
        assert save_mock.called                 # 未被闸拦截
        assert session_n == 2                   # 会话层写入不受影响

    def _post_memory_save(self, body=None):
        """POST /ai/memory/save（ASGITransport，最轻路径）"""

        async def run():
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                return await client.post("/ai/memory/save",
                                         json=body or {"content": "记忆内容"})

        return asyncio.run(run())

    def test_endpoint_save_blocked_returns_code_1(self, monkeypatch):
        """read 模式端点级：POST /ai/memory/save → code 1 + message 含"子只读父写"
        （编排者裁定：拒绝必须可见，fail-closed 对齐 083；Reviewer 阻塞 #1）"""
        save_mock = mock.AsyncMock(return_value={"status": "saved"})
        monkeypatch.setattr(memory_service, "_save", save_mock)

        async def run():
            # set 与 POST 同一 asyncio.run：ContextVar 经 task 派生链继承到端点
            #（set 在 pytest 共享上下文外，不泄漏；结束复位双保险——088 LOW-3 教训）
            tasks.set_memory_write_mode("read")
            transport = httpx.ASGITransport(app=main_module.app,
                                            raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="http://test") as client:
                resp = await client.post("/ai/memory/save",
                                         json={"content": "记忆内容"})
            tasks.set_memory_write_mode("write")
            return resp

        resp = asyncio.run(run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert "子只读父写" in body["message"]
        assert not save_mock.called             # 闸拦截，未落库

    def test_endpoint_save_normal_returns_code_0(self, monkeypatch):
        """默认 write 端点级：POST /ai/memory/save → code 0 + data.status=saved
        （存量透传语义逐字不变，仅 blocked 分支新增）"""
        monkeypatch.setattr(memory_service, "_save",
                            mock.AsyncMock(return_value={"status": "saved"}))
        resp = self._post_memory_save()
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"status": "saved"}


# ─── AC-15：集成终证（一次请求 = 1 task） ───


class TestOneRequestOneTask:
    """ASGITransport chat 最轻链（对齐 088 TestOneRequestOneTrace 模式）"""

    def test_exactly_one_insert_one_update_same_ids(self, monkeypatch):
        """恰 1 INSERT + 1 UPDATE，task_id 两侧同值；INSERT trace_id == 根 span
        trace_id == request_logs trace_id（AC-15 三面同值）"""
        _enable_tasks(monkeypatch)
        monkeypatch.setattr(settings, "request_logs_enabled", True)
        monkeypatch.setattr(settings, "trace_spans_enabled", True)
        calls = _capture(monkeypatch)
        spans: list = []
        monkeypatch.setattr(tracing, "_spawn_insert",
                            lambda row: spans.append(dict(row)))
        save_mock = mock.AsyncMock()
        eng, sess = _patch_engine()
        with mock.patch.object(observability, "save_request_log", save_mock):
            with eng, sess:
                resp = _post_chat()
        assert resp.status_code == 200
        inserts, updates = _inserts(calls), _updates(calls)
        assert len(inserts) == 1 and len(updates) == 1
        assert inserts[0]["task_id"] == updates[0]["task_id"]
        trace_id = inserts[0]["trace_id"]
        assert len(trace_id) == 32
        roots = [s for s in spans if s["kind"] == "request"]
        assert len(roots) == 1
        assert roots[0]["trace_id"] == trace_id  # 088 根 span 同值（兼容）
        assert save_mock.call_args[0][0]["trace_id"] == trace_id  # request_logs
        assert updates[0]["status"] == "completed"


# ─── AC-9：SQL hygiene ───


class TestSQLHygiene:
    """三条 SQL 全参数化：无 f-string/%/+ 拼接"""

    def test_three_sqls_no_interpolation(self):
        """_SQL_INSERT/_SQL_FINISH/_SQL_OVERVIEW 无拼接残留，仅 :xxx 绑定"""
        for sql in (tasks._SQL_INSERT, tasks._SQL_FINISH, tasks._SQL_OVERVIEW):
            assert "{" not in sql and "}" not in sql
            assert "%s" not in sql and "%(" not in sql and "%d" not in sql
            assert "+" not in sql
            assert ":task_id" in sql
        assert "INSERT INTO tasks" in tasks._SQL_INSERT
        assert "UPDATE tasks" in tasks._SQL_FINISH
        assert "FROM tasks t" in tasks._SQL_OVERVIEW
