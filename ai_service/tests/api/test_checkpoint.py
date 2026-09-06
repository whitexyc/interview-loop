"""module-090：失败隔离 + checkpoint 单测（hermetic，不依赖真实 PG）

覆盖（验收 AC-1~13/18~19 单测侧，真实对账归 Tester T1-T6）：
- SQL 卫生：三条新 SQL 草案逐字 + 全参数化无拼接 + 作用域子句逐字锁定
  （AC-4/7/11）+ save 无 status 条件（覆盖语义）+ resume 白名单子句（AC-8）
- save_checkpoint：门控 ×3（空 task_id/开关关/非 dict → 零 spawn，AC-1）/
  JSON 字符串绑定回读逐值相等（中文/嵌套/datetime→str，AC-2）/ 序列化失败
  warning no-op（AC-3）/ last-save-wins 可重入（AC-4）/ 无 loop 静默（AC-19）
- load_checkpoint：dict 形态直返 / str 兜 json.loads / 行不存在 {} / 非 dict
  防御 {}（AC-5）/ 读侧不设闸 + 空 id 零 DB（AC-6）/ DB 异常上抛（AC-18）
- resume_task：failed→True / 悬挂 running 幂等 / completed→False 行零改动 /
  不存在·空 id·开关关→False（AC-7/8）/ checkpoint 保留 + ContextVar 零触碰
  （AC-9/10）/ DB 异常上抛（AC-18）
- 失败隔离契约：finish/save/budget 参数作用域恰一条（AC-12）+ TASKS_DDL 无
  REFERENCES/FOREIGN KEY/CREATE TRIGGER + _SQL_FINISH 不含 checkpoint（AC-11/13）

实现说明（对齐 test_tasks/test_budget 先例）：
- conftest autouse 钉住 tasks_enabled=false；本文件写路径用例显式开启，读侧
  用例保持关闭验证"不设闸"
- _reset_task_context 每用例复位三 ContextVar（含 _task_id_var）；save_checkpoint
  直调不包 asyncio.run（同步原语严禁包裹——089 坑②）；load/resume 包
  asyncio.run（async 原语；var 设置与被测调用必须同一 run——089 坑①）
- 真实对账（JSONB 驱动层往返/断点恢复/父子隔离）归 Tester T1-T6，mock 测不到
  驱动序列化（087 Tester 发现-1 教训）
"""
import asyncio
import json
from datetime import datetime
from unittest import mock

import pytest

from src import tasks
from src.config import settings
from src.database import TASKS_DDL


# ─── 打桩辅助（对齐 test_budget._reset_task_context / test_tasks._FakeSession）───


@pytest.fixture(autouse=True)
def _reset_task_context():
    """每用例后复位 task ContextVar（同步原语 var.set 落 pytest 共享上下文，
    跨用例泄漏会污染断言；088 LOW-3 / 089 坑②同源防御）"""
    yield
    tasks._task_id_var.set("")
    tasks._budget_limit_var.set(0)
    tasks._memory_write_var.set("write")


def _capture_spawn(monkeypatch) -> list:
    """打桩 _spawn 同步捕获 (sql, params)（不依赖真实 task 完成）"""
    calls: list = []
    monkeypatch.setattr(tasks, "_spawn",
                        lambda sql, params: calls.append((sql, dict(params))))
    return calls


def _enable_tasks(monkeypatch) -> None:
    """显式开启任务抽象（conftest autouse 默认钉住 false）"""
    monkeypatch.setattr(settings, "tasks_enabled", True)


class _FakeResult:
    """假 execute 返回：mappings().first() 可配置 + rowcount 可配置（resume）"""

    def __init__(self, rows=None, rowcount=0):
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def mappings(self):
        outer = self

        class _M:
            def first(self):
                return outer._rows[0] if outer._rows else None

        return _M()


class _FakeSession:
    """假 AsyncSession：按 execute 顺序弹出预置结果并记录 (SQL, 参数)"""

    def __init__(self, results=None, rowcount=0, execute_error=None):
        self.executed: list = []
        self.commits = 0
        self._execute_error = execute_error
        if results:
            self._results = [_FakeResult(rows=r, rowcount=rowcount)
                             for r in results]
        else:
            self._results = [_FakeResult(rows=[], rowcount=rowcount)]

    async def execute(self, stmt, params=None):
        if self._execute_error:
            raise self._execute_error
        self.executed.append((str(stmt), params or {}))
        return self._results.pop(0) if self._results else _FakeResult()

    async def commit(self):
        self.commits += 1


def _fake_factory(session):
    """把 async_session_factory 打桩成返回 session 的异步上下文管理器"""
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


def _patch_load(monkeypatch, results):
    """load 用假 session（results 为每次 execute 的行 list 列表，如
    [[{"checkpoint": {...}}]]；多元素 = 多次 execute 顺序弹出）"""
    session = _FakeSession(results=results)
    monkeypatch.setattr("src.database.async_session_factory",
                        _fake_factory(session))
    return session


# ─── AC-4/7/8/11：SQL 卫生 + 作用域子句逐字锁定 ───


class TestSQLHygiene:
    def test_three_new_sqls_verbatim_and_parameterized(self):
        # AC-4/7：三条新 SQL 与 plan 草案逐字一致 + 全参数化无拼接
        assert tasks._SQL_SAVE_CHECKPOINT.strip() == (
            "UPDATE tasks SET checkpoint = :checkpoint\n"
            "    WHERE task_id = :task_id")
        assert tasks._SQL_LOAD_CHECKPOINT.strip() == (
            "SELECT checkpoint FROM tasks\n"
            "    WHERE task_id = :task_id")
        assert tasks._SQL_RESUME.strip() == (
            "UPDATE tasks SET status = 'running', finished_at = NULL\n"
            "    WHERE task_id = :task_id"
            " AND status IN ('failed', 'running')")
        for sql in (tasks._SQL_SAVE_CHECKPOINT, tasks._SQL_LOAD_CHECKPOINT,
                    tasks._SQL_RESUME):
            assert "{" not in sql and "}" not in sql  # 无 f-string 残留
            assert "%s" not in sql and "%(" not in sql  # 无 % 拼接
            assert "+" not in sql
            assert ":task_id" in sql

    def test_scope_clauses_and_semantic_clauses(self):
        # AC-11：五条写/读 SQL 作用域子句逐字（子 task 失败无 SQL 路径触父行）；
        # AC-4：save 无 status 条件（覆盖语义）；AC-8：resume 白名单逐字
        for sql in (tasks._SQL_SAVE_CHECKPOINT, tasks._SQL_RESUME,
                    tasks._SQL_BUDGET):
            assert "WHERE task_id = :task_id" in sql
        assert "WHERE task_id = :task_id" in tasks._SQL_FINISH
        assert "status = 'running'" in tasks._SQL_FINISH
        assert "status" not in tasks._SQL_SAVE_CHECKPOINT  # 覆盖语义（AC-4）
        assert "status IN ('failed', 'running')" in tasks._SQL_RESUME
        assert "completed" not in tasks._SQL_RESUME  # 终态不可复活（AC-8）
        assert "finished_at = NULL" in tasks._SQL_RESUME


# ─── AC-1~4/19：save_checkpoint ───


class TestSaveCheckpoint:
    def test_empty_task_id_noop(self, monkeypatch):
        # AC-1：空 task_id → 零 spawn
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        tasks.save_checkpoint("", {"step": 1})
        assert calls == []

    def test_disabled_noop(self, monkeypatch):
        # AC-1：开关关（conftest 默认）→ 零 spawn
        calls = _capture_spawn(monkeypatch)  # tasks_enabled 保持 False
        assert settings.tasks_enabled is False
        tasks.save_checkpoint("a" * 32, {"step": 1})
        assert calls == []

    def test_non_dict_payload_noop(self, monkeypatch):
        # AC-1：非 dict payload → 零 spawn（对齐非法值先例）
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        for bad in ([1, 2], "x", None, 42):
            tasks.save_checkpoint("a" * 32, bad)
        assert calls == []

    def test_json_string_binding_roundtrip(self, monkeypatch):
        # AC-2：checkpoint 恒为 JSON 字符串 + json.loads 回读逐值相等；
        # 中文 ensure_ascii=False 原文可读 / 嵌套结构 / datetime→default=str
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        ts = datetime(2026, 9, 6, 12, 0, 0)
        payload = {"step": 5, "done": ["检索", "改写"],
                   "nested": {"a": [1, 2, {"b": True}]}, "ts": ts}
        tasks.save_checkpoint("a" * 32, payload)
        assert len(calls) == 1
        sql, params = calls[0]
        assert "UPDATE tasks SET checkpoint = :checkpoint" in sql
        raw = params["checkpoint"]
        assert isinstance(raw, str)  # 绝无 dict 直绑（JSONB 坑③）
        assert "检索" in raw  # ensure_ascii=False（中文不转义）
        loaded = json.loads(raw)
        assert loaded["step"] == 5
        assert loaded["done"] == ["检索", "改写"]
        assert loaded["nested"] == {"a": [1, 2, {"b": True}]}
        assert loaded["ts"] == str(ts)  # default=str 兜不可序列化类型
        assert params["task_id"] == "a" * 32

    def test_serialization_failure_warning_noop(self, monkeypatch, caplog):
        # AC-3：循环引用 (TypeError, ValueError) → warning + no-op 不炸调用方
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        circular: dict = {}
        circular["self"] = circular
        with caplog.at_level("WARNING", logger="src.tasks"):
            tasks.save_checkpoint("a" * 32, circular)  # 不抛
        assert calls == []
        assert "序列化失败" in caplog.text

    def test_last_save_wins_reentrant(self, monkeypatch):
        # AC-4：重复保存同 task 可重入，两次 spawn 参数各自（后写覆盖语义）
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        tasks.save_checkpoint("a" * 32, {"step": 1})
        tasks.save_checkpoint("a" * 32, {"step": 2})
        saves = [p for s, p in calls if "checkpoint = :checkpoint" in s]
        assert [json.loads(p["checkpoint"])["step"] for p in saves] == [1, 2]
        assert all(p["task_id"] == "a" * 32 for p in saves)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_no_loop_spawn_silent(self, monkeypatch):
        # AC-19：无运行事件循环 → _spawn RuntimeError 窄捕获静默放弃
        #（不 mock _spawn，走真实路径——create_task 前即放弃，零 DB 访问）。
        # filterwarnings：_spawn 先构造 _run_sql 协程对象再 create_task，无 loop
        # 时协程被放弃 → GC RuntimeWarning（087 fire-and-forget 设计固有良性
        # 产物，生产恒有运行 loop 不会出现）
        _enable_tasks(monkeypatch)
        tasks.save_checkpoint("a" * 32, {"step": 1})  # 不抛即锁定语义


# ─── AC-5/6/18：load_checkpoint ───


class TestLoadCheckpoint:
    def test_roundtrip_dict_form(self, monkeypatch):
        # AC-5：asyncpg JSONB 默认解码形态（dict）直返，逐值相等
        payload = {"step": 5, "done": ["检索", "改写"]}
        session = _patch_load(monkeypatch, [[{"checkpoint": payload}]])
        out = asyncio.run(tasks.load_checkpoint("a" * 32))
        assert out == payload
        sql, params = session.executed[0]
        assert "SELECT checkpoint FROM tasks" in sql
        assert params == {"task_id": "a" * 32}

    def test_str_form_json_loads_fallback(self, monkeypatch):
        # AC-5：str 形态（双兼容坑④）→ json.loads 兜底
        raw = json.dumps({"step": 7}, ensure_ascii=False)
        _patch_load(monkeypatch, [[{"checkpoint": raw}]])
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {"step": 7}

    def test_missing_row_empty_dict(self, monkeypatch):
        # AC-5：行不存在 → {}
        _patch_load(monkeypatch, [[]])
        assert asyncio.run(tasks.load_checkpoint("z" * 32)) == {}

    def test_non_dict_defense(self, monkeypatch):
        # AC-5：非 dict 脏数据防御 → {}（list 直返形态 / str 解码出非 dict /
        # 非法 JSON 字符串 → json.loads 抛 JSONDecodeError 落窄捕获（Reviewer
        # LOW-1 补测，changelog 偏离 3 分支锁定）/ JSONB NULL——NOT NULL
        # DEFAULT '{}' 列真实 DB 不会出现，防御兜底）
        _patch_load(monkeypatch, [[{"checkpoint": [1, 2]}],
                                  [{"checkpoint": json.dumps("plain")}],
                                  [{"checkpoint": "{oops"}],
                                  [{"checkpoint": None}]])
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {}
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {}
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {}
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {}

    def test_read_without_gate_and_empty_id(self, monkeypatch):
        # AC-6：读侧不设闸（tasks_enabled=False 仍可读——对齐 087 读端点先例）；
        # 空 task_id → {} 零 DB 访问
        session = _patch_load(monkeypatch, [[{"checkpoint": {"k": 1}}]])
        assert settings.tasks_enabled is False  # conftest 钉桩前提（不设闸）
        assert asyncio.run(tasks.load_checkpoint("a" * 32)) == {"k": 1}
        assert asyncio.run(tasks.load_checkpoint("")) == {}
        assert len(session.executed) == 1  # 空 id 零 SQL

    def test_db_exception_raises(self, monkeypatch):
        # AC-6/18：DB 异常原样上抛（对齐 get_task_overview，调用方定降级）
        session = _FakeSession(execute_error=RuntimeError("数据库不可用"))
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        with pytest.raises(RuntimeError):
            asyncio.run(tasks.load_checkpoint("a" * 32))


# ─── AC-7~10/18：resume_task ───


class TestResumeTask:
    def test_failed_resumes_true(self, monkeypatch):
        # AC-7：failed 行 → True；SQL 含置回 running + finished_at=NULL +
        # 白名单子句；commit 落库（UPDATE 不 commit 等于回滚）
        _enable_tasks(monkeypatch)
        session = _FakeSession(rowcount=1)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        assert asyncio.run(tasks.resume_task("a" * 32)) is True
        sql, params = session.executed[0]
        assert "UPDATE tasks SET status = 'running', finished_at = NULL" in sql
        assert "status IN ('failed', 'running')" in sql
        assert params == {"task_id": "a" * 32}
        assert session.commits == 1

    def test_hanging_running_idempotent(self, monkeypatch):
        # AC-7：悬挂 running（进程死亡遗留行）→ True；重复恢复幂等（两次均
        # True，SQL 无排他条件——状态不变重放安全）
        _enable_tasks(monkeypatch)
        session = _FakeSession(results=[[], []], rowcount=1)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        assert asyncio.run(tasks.resume_task("a" * 32)) is True
        assert asyncio.run(tasks.resume_task("a" * 32)) is True
        assert len(session.executed) == 2

    def test_completed_rejected_false_zero_change(self, monkeypatch):
        # AC-8：completed 终态不可复活 → False（rowcount=0 = 行零改动）；
        # 白名单子句不含 completed（调用方 bug 被 SQL 挡住）
        _enable_tasks(monkeypatch)
        session = _FakeSession(rowcount=0)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        assert asyncio.run(tasks.resume_task("a" * 32)) is False
        assert "completed" not in session.executed[0][0]
        assert "WHERE task_id = :task_id" in session.executed[0][0]

    def test_not_found_empty_id_disabled_false(self, monkeypatch):
        # AC-8：行不存在（rowcount=0）→ False；空 task_id / 开关关 → False
        # 零 DB 访问
        _enable_tasks(monkeypatch)
        session = _FakeSession(rowcount=0)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        assert asyncio.run(tasks.resume_task("z" * 32)) is False
        assert asyncio.run(tasks.resume_task("")) is False
        assert len(session.executed) == 1  # 空 id 零 SQL
        monkeypatch.setattr(settings, "tasks_enabled", False)  # 开关关
        disabled_session = _FakeSession(rowcount=0)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(disabled_session))
        assert asyncio.run(tasks.resume_task("a" * 32)) is False  # 开关关
        assert len(disabled_session.executed) == 0

    def test_resume_preserves_checkpoint_and_contextvars(self, monkeypatch):
        # AC-9：_SQL_RESUME 零触碰 checkpoint/trace_id/intent/tokens_used
        #（旧 checkpoint 保留 = "续跑不从头"数据前提，编排者裁定①）；
        # AC-10：resume 不改任何 ContextVar（纯行状态原语）
        for word in ("checkpoint", "trace_id", "intent", "tokens_used"):
            assert word not in tasks._SQL_RESUME
        _enable_tasks(monkeypatch)
        session = _FakeSession(rowcount=1)
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))

        async def run():
            # var 设置与被测调用同一 asyncio.run（坑①：跨 run 不继承）
            tasks._task_id_var.set("t" * 32)
            tasks._budget_limit_var.set(100)
            tasks._memory_write_var.set("read")
            await tasks.resume_task("a" * 32)
            return (tasks._task_id_var.get(), tasks._budget_limit_var.get(),
                    tasks._memory_write_var.get())

        assert asyncio.run(run()) == ("t" * 32, 100, "read")

    def test_db_exception_raises(self, monkeypatch):
        # AC-10/18：DB 异常上抛（对齐 get_task_overview 读侧先例）
        _enable_tasks(monkeypatch)
        session = _FakeSession(execute_error=RuntimeError("数据库不可用"))
        monkeypatch.setattr("src.database.async_session_factory",
                            _fake_factory(session))
        with pytest.raises(RuntimeError):
            asyncio.run(tasks.resume_task("a" * 32))


# ─── AC-11/12/13：失败隔离语义契约（零代码补强，机制 = 087 单行作用域） ───


class TestIsolationContract:
    def test_finish_child_error_scoped_to_child_row(self, monkeypatch):
        # AC-12：finish_task(子 id, error=True) → 恰一条 spawn 且参数
        # task_id == 子 id（单行作用域——父行零触达）
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        child = "c" * 32
        tasks.finish_task(child, intent="knowledge", error=True)
        updates = [(s, p) for s, p in calls if "UPDATE tasks" in s]
        assert len(updates) == 1
        assert updates[0][1]["task_id"] == child
        assert updates[0][1]["status"] == "failed"

    def test_save_and_budget_scoped_to_target_row(self, monkeypatch):
        # AC-12：save_checkpoint / set_task_budget 同理参数作用域——调用只
        # 作用目标任务行，父行零触达
        _enable_tasks(monkeypatch)
        calls = _capture_spawn(monkeypatch)
        child = "c" * 32
        tasks.save_checkpoint(child, {"step": 3})
        saves = [p for s, p in calls if "checkpoint = :checkpoint" in s]
        assert len(saves) == 1 and saves[0]["task_id"] == child

        async def run():
            tasks._task_id_var.set(child)
            tasks.set_task_budget(250)

        asyncio.run(run())
        budgets = [p for s, p in calls
                   if "budget_token_limit = :budget_token_limit" in s]
        assert len(budgets) == 1 and budgets[0]["task_id"] == child

    def test_ddl_no_cascade_and_finish_never_touches_checkpoint(self):
        # AC-11：TASKS_DDL 无外键无触发器（零级联路径——父子隔离的机制保证）；
        # AC-13：_SQL_FINISH 不含 checkpoint 字样（087 收口语义保持——断点
        # 进度不因任务收口丢失）
        ddl = TASKS_DDL.upper()
        assert "REFERENCES" not in ddl
        assert "FOREIGN KEY" not in ddl
        assert "CREATE TRIGGER" not in ddl
        assert "checkpoint" not in tasks._SQL_FINISH
