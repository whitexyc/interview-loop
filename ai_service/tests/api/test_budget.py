"""module-089：预算账本单测（hermetic，不依赖真实 PG）

覆盖（验收 AC-1~AC-27 单测侧，真实对账归 Tester T1-T6）：
- config：task_budget_token_limit 字段存在、默认 0（AC-1）
- 原语：budget_used 汇总口径（多供应商/缺键兜 0/空 usage，与 087 收口同式）/
  budget_exceeded 判定矩阵（limit<=0 / tasks_enabled 关 / >= 边界）/ 
  set_task_budget 正数生效+UPDATE spawn、负数 no-op / get_budget_limit 默认 0
  （AC-2~7）
- begin_task：config 解析 → INSERT budget_token_limit + var 同值（AC-2）
- 工具层熔断：超限 → tool.run 未调 + 熔断文本 + span blocked + decision 含
  module-089（AC-7）；未超限/limit=0 零拦截（AC-8）
- 循环层熔断：超限 → chat_with_tools 不再被调 + 兜底生成被调 + budget_break
  span（AC-9~11）；未超限零 budget_break（AC-12）
- SQL 卫生：_SQL_BUDGET 常量参数化（AC-16）

实现说明：
- conftest autouse 钉 task_budget_token_limit=0（存量零漂移）；本文件显式开启
- budget_used 数据源经 monkeypatch observability.get_request_stats（只读快照，
  不 mock 写入侧）
- ContextVar 入口（begin_task/set_task_budget/react_loop 消费）统一包
  asyncio.run（088 LOW-3 教训：防"幽灵 task"向 pytest 共享上下文泄漏）
"""
import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest

from src import observability, tasks, tracing
from src.config import settings
from agent.react import ReactContext, execute_tool_with_log, react_loop


@pytest.fixture(autouse=True)
def _reset_task_context():
    """每用例后复位 task ContextVar（set_task_budget 是同步函数，var.set 落在
    pytest 共享上下文——跨用例泄漏会污染"默认 0"断言；088 LOW-3 同源防御）"""
    yield
    tasks._task_id_var.set("")
    tasks._budget_limit_var.set(0)
    tasks._memory_write_var.set("write")


def _capture_spawn(monkeypatch) -> list:
    """打桩 _spawn 同步捕获 (sql, params)（对齐 test_tasks._capture 模式）"""
    calls: list = []
    monkeypatch.setattr(tasks, "_spawn",
                        lambda sql, params: calls.append((sql, dict(params))))
    return calls


def _patch_usage(monkeypatch, prompt: int, completion: int = 0, empty=False):
    """打桩 usage 快照（budget_used 数据源；empty=True 模拟 logs 关恒空）"""
    usage = {} if empty else {"qwen": {"prompt": prompt, "completion": completion}}
    monkeypatch.setattr(observability, "get_request_stats",
                        lambda: {"usage": usage})


def _fake_tool(return_value="ok"):
    return SimpleNamespace(run=mock.AsyncMock(return_value=return_value))


def _capture_spans(monkeypatch) -> list:
    spans: list = []
    monkeypatch.setattr(tracing, "record_span",
                        lambda name, kind, **kw: spans.append(
                            {"name": name, "kind": kind, **kw}))
    return spans


# ══════════════════════════════════════════════════════════════════
# config（AC-1）
# ══════════════════════════════════════════════════════════════════


class TestConfig:
    def test_field_exists_default_zero(self):
        # AC-1：字段存在、默认 0=不限（存量零行为变化）
        assert settings.task_budget_token_limit == 0


# ══════════════════════════════════════════════════════════════════
# 原语（AC-3~7）
# ══════════════════════════════════════════════════════════════════


class TestPrimitives:
    def test_budget_used_multi_provider_sum(self, monkeypatch):
        # AC-3：Σ 各供应商 prompt+completion（与 087 收口逐字同式）
        monkeypatch.setattr(observability, "get_request_stats", lambda: {
            "usage": {"qwen": {"prompt": 100, "completion": 40},
                      "deepseek": {"prompt": 10, "completion": 2}}})
        assert tasks.budget_used() == 152

    def test_budget_used_missing_keys_fallback_zero(self, monkeypatch):
        # AC-3：缺键兜 0（usage 形状异常不炸）
        monkeypatch.setattr(observability, "get_request_stats", lambda: {
            "usage": {"qwen": {}}})
        assert tasks.budget_used() == 0

    def test_budget_used_empty(self, monkeypatch):
        # AC-3：空 usage（logs 关）→ 0（边界如实声明）
        _patch_usage(monkeypatch, 0, 0, empty=True)
        assert tasks.budget_used() == 0

    def test_exceeded_limit_zero_never(self, monkeypatch):
        # AC-4：limit=0（不限）→ 恒 False，零执法
        _patch_usage(monkeypatch, 999999)
        assert tasks.budget_exceeded() is False

    def test_exceeded_boundary_equal(self, monkeypatch):
        # AC-4：used == limit 即熔断（>= 边界，防恰等再烧一轮）
        monkeypatch.setattr(settings, "tasks_enabled", True)
        _patch_usage(monkeypatch, 100)
        tasks.set_task_budget(100)
        assert tasks.budget_exceeded() is True

    def test_not_exceeded_below(self, monkeypatch):
        # AC-4：used < limit → False
        monkeypatch.setattr(settings, "tasks_enabled", True)
        _patch_usage(monkeypatch, 99)
        tasks.set_task_budget(100)
        assert tasks.budget_exceeded() is False

    def test_exceeded_tasks_disabled(self, monkeypatch):
        # AC-4：tasks_enabled=False（conftest 钉桩默认）→ 不执法
        _patch_usage(monkeypatch, 999999)
        tasks.set_task_budget(1)
        assert settings.tasks_enabled is False  # conftest 钉桩前提
        assert tasks.budget_exceeded() is False

    def test_set_task_budget_positive_updates_and_spawns(self, monkeypatch):
        # AC-5：正数 → var 更新 + UPDATE spawn（tasks_enabled=False → 不 spawn，
        # 只验证 var；spawn 路径由 begin_task 集成用例覆盖）
        _patch_usage(monkeypatch, 0)
        tasks.set_task_budget(500)
        assert tasks.get_budget_limit() == 500

    def test_set_task_budget_negative_noop(self, monkeypatch):
        # AC-5：负数 no-op 保持原值（对齐 set_memory_write_mode 语义）
        _patch_usage(monkeypatch, 0)
        tasks.set_task_budget(300)
        tasks.set_task_budget(-1)
        assert tasks.get_budget_limit() == 300

    def test_get_budget_limit_default_zero(self):
        # AC-6：ContextVar default 0（请求间天然隔离）
        assert tasks.get_budget_limit() == 0

    def test_set_task_budget_spawn_when_enabled(self, monkeypatch):
        # AC-5 补充：tasks_enabled=True + 已建 task → UPDATE spawn 参数正确
        monkeypatch.setattr(settings, "tasks_enabled", True)
        calls = _capture_spawn(monkeypatch)
        _patch_usage(monkeypatch, 0)

        async def run():
            tid = tasks.begin_task("f" * 32, "/ai/rag/chat")
            tasks.set_task_budget(250)
            return tid

        asyncio.run(run())
        budget_calls = [(s, p) for s, p in calls if "UPDATE tasks" in s]
        assert len(budget_calls) == 1
        s, p = budget_calls[0]
        assert p["budget_token_limit"] == 250
        assert p["task_id"]


# ══════════════════════════════════════════════════════════════════
# begin_task 集成（AC-2）
# ══════════════════════════════════════════════════════════════════


class TestBeginTask:
    def test_config_budget_parsed_into_insert_and_var(self, monkeypatch):
        # AC-2：config=200 → INSERT budget_token_limit=200 + var 同值
        monkeypatch.setattr(settings, "tasks_enabled", True)
        monkeypatch.setattr(settings, "task_budget_token_limit", 200)
        calls = _capture_spawn(monkeypatch)

        async def run():
            tid = tasks.begin_task("t" * 32, "/ai/rag/chat")
            return tid, tasks.get_budget_limit()

        tid, limit = asyncio.run(run())
        assert limit == 200
        inserts = [p for s, p in calls if "INSERT INTO tasks" in s]
        assert inserts and inserts[0]["budget_token_limit"] == 200
        assert inserts[0]["task_id"] == tid

    def test_config_default_zero_insert_unchanged(self, monkeypatch):
        # AC-2：config=0（默认）→ INSERT 恒 0（087 行为逐字，存量断言兼容）
        monkeypatch.setattr(settings, "tasks_enabled", True)
        monkeypatch.setattr(settings, "task_budget_token_limit", 0)
        calls = _capture_spawn(monkeypatch)

        async def run():
            return tasks.begin_task("t" * 32, "/ai/rag/chat")

        asyncio.run(run())
        inserts = [p for s, p in calls if "INSERT INTO tasks" in s]
        assert inserts and inserts[0]["budget_token_limit"] == 0


# ══════════════════════════════════════════════════════════════════
# 工具层熔断（AC-7~8）
# ══════════════════════════════════════════════════════════════════


class TestToolGate:
    def _setup(self, monkeypatch, used: int):
        monkeypatch.setattr(settings, "tasks_enabled", True)
        _patch_usage(monkeypatch, used)
        spans = _capture_spans(monkeypatch)
        monkeypatch.setattr("agent.react.record_tool_call", mock.AsyncMock())
        return spans

    def test_exceeded_blocks_tool(self, monkeypatch):
        # AC-7：超限 → tool.run 未调 + 熔断文本 + span blocked + decision 含 089
        #（预算 var 与被测代码必须同一 asyncio.run——ContextVar 跨 run 不继承）
        spans = self._setup(monkeypatch, used=100)
        tool = _fake_tool()

        async def run():
            tasks.set_task_budget(100)
            return await execute_tool_with_log(
                "search_knowledge", {"query": "q"}, tool, ReactContext("q"))

        result = asyncio.run(run())
        assert "熔断" in result and "module-089" in result
        tool.run.assert_not_awaited()
        blocked = [s for s in spans if s["status"] == "blocked"]
        assert blocked and "module-089" in blocked[0]["decision"]

    def test_not_exceeded_executes_normally(self, monkeypatch):
        # AC-8：未超限 → 正常执行（083/088 现状逐字）
        spans = self._setup(monkeypatch, used=10)
        tool = _fake_tool(return_value="检索结果")

        async def run():
            tasks.set_task_budget(100)
            return await execute_tool_with_log(
                "search_knowledge", {"query": "q"}, tool, ReactContext("q"))

        result = asyncio.run(run())
        assert result == "检索结果"
        tool.run.assert_awaited_once()
        assert all(s["status"] != "blocked" for s in spans)

    def test_limit_zero_never_blocks(self, monkeypatch):
        # AC-8：limit=0（不限）→ 零执法
        spans = self._setup(monkeypatch, used=999999)
        tool = _fake_tool(return_value="ok")

        async def run():
            tasks.set_task_budget(0)
            return await execute_tool_with_log(
                "search_knowledge", {"query": "q"}, tool, ReactContext("q"))

        assert asyncio.run(run()) == "ok"
        tool.run.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════
# 循环层熔断（AC-9~12）
# ══════════════════════════════════════════════════════════════════


class TestReactLoopGate:
    def _llm(self, monkeypatch):
        fake = SimpleNamespace(
            chat_with_tools=mock.AsyncMock(
                return_value={"content": "直接回答", "tool_calls": [],
                             "message": {"role": "assistant", "content": "直接回答"}}),
            chat=mock.AsyncMock(return_value="直接回答"))
        monkeypatch.setattr("agent.react.LLMFactory.get_client",
                            lambda *a, **k: fake)
        return fake

    def _run_loop(self, monkeypatch, used: int, limit: int):
        monkeypatch.setattr(settings, "tasks_enabled", True)
        _patch_usage(monkeypatch, used)
        spans = _capture_spans(monkeypatch)
        fake = self._llm(monkeypatch)
        fallback = mock.AsyncMock(return_value="兜底答案")
        monkeypatch.setattr("agent.react.reflector.generate_answer", fallback)
        events = []

        async def run():
            tasks.set_task_budget(limit)  # 同一上下文（跨 asyncio.run 不继承）
            ctx = ReactContext("q", "tester")
            async for evt in react_loop(ctx, [{"role": "user", "content": "q"}],
                                        budget=4):
                events.append(evt)

        asyncio.run(run())
        return spans, fake, fallback, events

    def test_exceeded_breaks_to_fallback(self, monkeypatch):
        # AC-9~11：超限 → chat_with_tools 不再被调 + 兜底生成 + budget_break span
        spans, fake, fallback, events = self._run_loop(monkeypatch,
                                                       used=100, limit=100)
        fake.chat_with_tools.assert_not_called()
        fallback.assert_awaited_once()
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["answer"] == "兜底答案"
        breaks = [s for s in spans if s["name"] == "budget_break"]
        assert breaks and "used=100" in breaks[0]["decision"] \
            and "limit=100" in breaks[0]["decision"]

    def test_not_exceeded_normal_loop(self, monkeypatch):
        # AC-12：未超限 → 正常循环零 budget_break（088 现状逐字）
        spans, fake, fallback, events = self._run_loop(monkeypatch,
                                                       used=1, limit=100)
        fake.chat_with_tools.assert_called_once()
        fallback.assert_not_called()
        assert all(s["name"] != "budget_break" for s in spans)
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["answer"] == "直接回答"


# ══════════════════════════════════════════════════════════════════
# SQL 卫生（AC-16）
# ══════════════════════════════════════════════════════════════════


class TestSQLHygiene:
    def test_sql_budget_parameterized_constant(self):
        # AC-16：_SQL_BUDGET 纯常量参数化，无拼接面
        assert tasks._SQL_BUDGET.strip() == (
            "UPDATE tasks SET budget_token_limit = :budget_token_limit\n"
            "    WHERE task_id = :task_id")
