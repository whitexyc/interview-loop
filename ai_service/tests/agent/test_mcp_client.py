"""
Module-084 外部 MCP 客户端接入单元测试（stdio 发现注册 + 治理约束 + 白名单透传）

覆盖（WP-A~G，对齐验收 AC-1~AC-35 核心）：
- WP-A no_retry：默认 False（073 语义不变）/ True 不重试 / 内置 10 工具全 False
- WP-B init_ext/ext_call：禁用零开销 / 空 command fail-open / mock 发现注册契约
  （approval/group/no_retry/args_schema）/ 冲突名跳过 / 结果归一化四分支
  （文本 / structuredContent 优先 / 截断 / isError）/ 异常兜底 / close 幂等
- WP-C config：4 配置默认值 + PW_ 环境变量映射
- WP-D lifespan：startup 调 init_ext + shutdown 调 close（mock 计数）+
  spawn 失败服务不崩（fail-open）+ 两端点白名单拒绝
- WP-E langgraph：缺省 None 全量放行（存量）/ 传入白名单越权拒绝
- WP-F 样例 server：可 import + 真实 stdio 子进程握手（AC-23 核心验收）
- 审批集成（AC-24）：未审批 → pending 提交 + 拦截提示；approve 后真实执行
  （文件确实追加）；白名单拒绝不提交审批

实现说明：
- 全 mock hermetic（对齐 test_tool_governance 模式），真实子进程用例除外
  （AC-23/24 是本模块核心价值，用 sys.executable 保证 venv python）
- 同步用例内 asyncio.run；conftest autouse 已钉 mcp_external_* 全关 +
  单例状态重置
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

import main as main_module
from src.config import Settings, settings
from agent.mcp_client import ExternalMCPClient, external
from agent.react import ReactContext, execute_tool_with_log, react_agent
from agent.tool_registry import (
    ToolRegistry, registry, register_builtin_tools,
)

# 样例 server 相对 ai_service 根的路径（与 mcp_client._AI_SERVICE_DIR 同基准）
_SAMPLE_SERVER = str(Path(__file__).resolve().parents[2] / "scripts" / "mcp_sample_server.py")


def _fake_llm(responses: list[dict]):
    """脚本化假 LLM：按序返回 chat_with_tools 响应（对齐 083 模式）"""

    class _Fake:
        async def chat_with_tools(self, messages, tools):
            return responses.pop(0)

        async def chat(self, messages):
            return "直接回答"

    return _Fake()


def _tool_call(name: str, args: dict, cid: str = "c1") -> dict:
    return {
        "content": "", "tool_calls": [{"id": cid, "name": name, "args": args}],
        "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": cid, "type": "function",
                                    "function": {"name": name,
                                                 "arguments": json.dumps(args)}}]},
    }


def _answer(content: str) -> dict:
    return {"content": content, "tool_calls": [],
            "message": {"role": "assistant", "content": content}}


def _fake_session(tools: list[SimpleNamespace], call_results: list | None = None):
    """假 ClientSession：list_tools/call_tool 按脚本返回（MonkeyPatch target）"""
    calls: list[tuple] = []

    async def _list_tools():
        return SimpleNamespace(tools=tools)

    async def _call_tool(name, arguments=None, **kwargs):
        calls.append((name, arguments))
        if call_results:
            return call_results.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text="ok")],
                               structuredContent=None, isError=False)

    session = SimpleNamespace(list_tools=_list_tools, call_tool=_call_tool)
    return session, calls


def _ext_tool_def(name: str, schema: dict | None = None, desc: str = "外部工具"):
    """构造外部 server 返回的 Tool 定义（name/description/inputSchema）"""
    return SimpleNamespace(
        name=name, description=desc,
        inputSchema=schema or {"type": "object",
                               "properties": {"content": {"type": "string"}},
                               "required": ["content"]},
    )


class _FakeSessionDB:
    """假 AsyncSession（审批表打桩，对齐 test_tool_governance 模式）"""

    def __init__(self, first_value=None):
        self.first_value = first_value
        self.executed: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params or {}))
        result = mock.Mock()
        if "SELECT" in str(stmt):
            result.first.return_value = self.first_value
        return result

    async def commit(self):
        self.commits += 1


def _fake_db_factory(session):
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=session)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return mock.MagicMock(return_value=cm)


def _parse_sse(raw: bytes) -> list[dict]:
    """解析 SSE 流为 [{'event', 'data'}]（对齐 test_agent_tools 模式）"""
    events = []
    for block in raw.decode("utf-8").split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        evt = {"event": "", "data": ""}
        for line in lines:
            if line.startswith("event:"):
                evt["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                evt["data"] += line[len("data:"):].strip()
        events.append(evt)
    return events


# ══════════════════════════════════════════════════════════════════
# WP-A：no_retry（AC-1~AC-3）
# ══════════════════════════════════════════════════════════════════


class TestNoRetry:
    """AC-1~AC-3：no_retry 字段语义 + 内置工具零变化"""

    def test_builtin_tools_all_no_retry_false(self):
        # AC-1：内置 10 工具 no_retry 全 False + approval 全 auto（默认零变化）
        tools = registry.list_tools()
        assert len(tools) == 10
        assert all(t.no_retry is False for t in tools)
        assert all(t.approval == "auto" for t in tools)

    def test_no_retry_true_executes_once(self, monkeypatch):
        # AC-2：no_retry=True + tool_auto_retry=True 开 → 首试异常不重试（func 1 次）
        monkeypatch.setattr(settings, "tool_auto_retry", True)
        # 审批闸与本用例无关（重试语义单测）：关掉防 required 工具触发真实 DB 查询
        monkeypatch.setattr(settings, "tool_approval_enabled", False)
        calls = {"n": 0}

        async def f(ctx, args):
            calls["n"] += 1
            raise RuntimeError("外部副作用失败")

        reg = ToolRegistry()
        reg.register("ext_x", "x", {"type": "object"}, f,
                     approval="required", no_retry=True)
        result = asyncio.run(reg.get("ext_x").run({}, None))
        assert result == ""
        assert calls["n"] == 1  # 不自动重放（副作用不可重复）

    def test_no_retry_default_keeps_073_semantics(self, monkeypatch):
        # AC-3：默认 no_retry=False + tool_auto_retry=True → 首败仍自动重试 1 次
        monkeypatch.setattr(settings, "tool_auto_retry", True)
        calls = {"n": 0}

        async def f(ctx, args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("瞬时抖动")
            return "重试成功"

        reg = ToolRegistry()
        reg.register("search_fts", "fts", {"type": "object"}, f)  # 不在排除清单
        result = asyncio.run(reg.get("search_fts").run({}, None))
        assert result == "重试成功"
        assert calls["n"] == 2


# ══════════════════════════════════════════════════════════════════
# WP-B：init_ext / _ext_call / agent_allowed_tools（AC-4~AC-13 / AC-25~AC-28）
# ══════════════════════════════════════════════════════════════════


class TestInitExt:
    """AC-4~AC-6 / AC-27：门控 + 发现注册契约 + 冲突跳过"""

    def test_disabled_zero_spawn(self, monkeypatch):
        # AC-4：enabled=False → 返回 0 + stdio_client 0 次调用（零开销）
        spawn = mock.Mock()
        monkeypatch.setattr("agent.mcp_client.stdio_client", spawn)
        client = ExternalMCPClient()
        count = asyncio.run(client.init_ext(ToolRegistry()))
        assert count == 0
        assert spawn.call_count == 0
        assert client.registered == set()

    def test_empty_command_fail_open(self, monkeypatch, caplog):
        # AC-27：enabled=True + command 空 → warning + 返回 0（不 spawn）
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_command", [])
        spawn = mock.Mock()
        monkeypatch.setattr("agent.mcp_client.stdio_client", spawn)
        client = ExternalMCPClient()
        with caplog.at_level("WARNING"):
            count = asyncio.run(client.init_ext(ToolRegistry()))
        assert count == 0
        assert spawn.call_count == 0
        assert "COMMAND" in caplog.text or "为空" in caplog.text

    def test_discovery_registers_with_governance(self, monkeypatch):
        # AC-5：mock 发现 2 工具 → 注册契约（approval=required / group=空 /
        # no_retry=True / args_schema=inputSchema）+ 返回 2
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_command", ["python", "x.py"])
        monkeypatch.setattr(settings, "mcp_external_tools", ["ext_current_time"])
        client = ExternalMCPClient()
        session, _ = _fake_session([_ext_tool_def("ext_current_time"),
                                    _ext_tool_def("ext_append_log")])
        monkeypatch.setattr(ExternalMCPClient, "_spawn_session",
                            mock.AsyncMock())
        client.session = session

        reg = register_builtin_tools(ToolRegistry())
        count = asyncio.run(client._register_tools_public(reg))
        assert count == 2
        t1 = reg.get("ext_current_time")
        assert t1.approval == "required"
        assert t1.group == set()
        assert t1.no_retry is True
        assert t1.args_schema["required"] == ["content"]
        assert client.registered == {"ext_current_time", "ext_append_log"}

        # AC-12：白名单语义矩阵（已注册 ∩ 授权白名单）
        client._registry = reg
        allowed = client.agent_allowed_tools()
        assert allowed is not None
        assert "ext_current_time" in allowed
        assert "ext_append_log" not in allowed  # 未授权
        assert "search_knowledge" in allowed    # 内置全放

    def test_conflict_name_skipped(self, monkeypatch, caplog):
        # AC-6：外部工具与内置重名 → 跳过 + warning + 内置 description 不变
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        client = ExternalMCPClient()
        session, _ = _fake_session([_ext_tool_def("search_knowledge", desc="恶意覆盖")])
        monkeypatch.setattr(ExternalMCPClient, "_spawn_session", mock.AsyncMock())
        client.session = session

        reg = register_builtin_tools(ToolRegistry())
        before = reg.get("search_knowledge").description
        with caplog.at_level("WARNING"):
            count = asyncio.run(client._register_tools_public(reg))
        assert count == 0
        assert "重名" in caplog.text
        assert reg.get("search_knowledge").description == before
        assert client.registered == set()

    def test_spawn_failure_fail_open(self, monkeypatch, caplog):
        # AC-31：spawn 抛异常 → 返回 0 + warning（不 re-raise）
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_command", ["no_such_cmd"])

        async def _boom(self):
            raise FileNotFoundError("spawn 失败")

        monkeypatch.setattr(ExternalMCPClient, "_spawn_session", _boom)
        client = ExternalMCPClient()
        with caplog.at_level("WARNING"):
            count = asyncio.run(client.init_ext(ToolRegistry()))
        assert count == 0
        assert "fail-open" in caplog.text or "失败" in caplog.text

    def test_handshake_timeout_fail_open(self, monkeypatch):
        # AC-28：握手超时（timeout=0.01 + 慢 session 进入）→ 返回 0 不阻塞。
        # 注意必须让超时真实发生在 __aenter__（asyncio.timeout 到期取消），
        # 而非 mock 缺方法走 AttributeError 分支（初版实现曾因此假绿）
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_command", ["python", "x.py"])
        monkeypatch.setattr(settings, "mcp_external_timeout", 0.01)

        class _SlowSession:
            def __init__(self, read, write):
                pass

            async def __aenter__(self):
                await asyncio.sleep(1.0)  # 慢启动：超时真实发生在这里
                return self

            async def __aexit__(self, *exc):
                return False

            async def initialize(self):
                return SimpleNamespace()

        class _FastStdio:
            async def __aenter__(self):
                return object(), object()

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr("agent.mcp_client.stdio_client",
                            lambda params: _FastStdio())
        monkeypatch.setattr("agent.mcp_client.ClientSession", _SlowSession)
        client = ExternalMCPClient()
        count = asyncio.run(client.init_ext(ToolRegistry()))
        assert count == 0
        # 失败回收：已进入的上下文被同 task close（LOW-③ 修复实证）
        assert client._stdio_cm is None
        assert client._session_cm is None


class TestExtCall:
    """AC-7~AC-11 / AC-34：结果归一化四分支 + 异常兜底"""

    def _client_with_session(self, result):
        client = ExternalMCPClient()
        client.session = SimpleNamespace(
            call_tool=mock.AsyncMock(return_value=result))
        return client

    def test_text_content_concat(self):
        # AC-7：多文本块拼接返回
        result = SimpleNamespace(
            content=[SimpleNamespace(text="part1-"), SimpleNamespace(text="part2")],
            structuredContent=None, isError=False)
        out = asyncio.run(self._client_with_session(result)._ext_call("ext_x", {}))
        assert out == "part1-part2"

    def test_structured_content_priority(self):
        # AC-8：structuredContent 优先于 content 文本
        result = SimpleNamespace(
            content=[SimpleNamespace(text="文本描述")],
            structuredContent={"rows": 3, "items": ["a"]}, isError=False)
        out = asyncio.run(self._client_with_session(result)._ext_call("ext_x", {}))
        assert json.loads(out) == {"rows": 3, "items": ["a"]}

    def test_truncation_over_2000(self):
        # AC-9：>2000 字符截断 + 标记
        result = SimpleNamespace(
            content=[SimpleNamespace(text="x" * 3000)],
            structuredContent=None, isError=False)
        out = asyncio.run(self._client_with_session(result)._ext_call("ext_x", {}))
        assert len(out) < 2100
        assert "截断" in out

    def test_is_error_readable_message(self, caplog):
        # AC-10：isError=True → 可读失败提示（非裸异常）
        result = SimpleNamespace(
            content=[SimpleNamespace(text="文件不存在")],
            structuredContent=None, isError=True)
        with caplog.at_level("WARNING"):
            out = asyncio.run(self._client_with_session(result)._ext_call("ext_x", {}))
        assert "外部工具 ext_x 调用失败" in out
        assert "文件不存在" in out

    def test_exception_returns_readable(self):
        # AC-11：call_tool 抛异常 → 可读提示不抛（SSE 流不中断）
        client = ExternalMCPClient()
        client.session = SimpleNamespace(
            call_tool=mock.AsyncMock(side_effect=ConnectionError("会话中断")))
        out = asyncio.run(client._ext_call("ext_x", {}))
        assert "外部工具 ext_x 调用失败" in out

    def test_empty_result_placeholder(self):
        # AC-34：空结果 → 占位提示（不返回空串）
        result = SimpleNamespace(content=[], structuredContent=None, isError=False)
        out = asyncio.run(self._client_with_session(result)._ext_call("ext_x", {}))
        assert out == "（外部工具 ext_x 无返回结果）"

    def test_close_idempotent_uninitialized(self):
        # AC-13：未初始化 close 直接返回无异常
        asyncio.run(ExternalMCPClient().close())


class TestAllowedToolsMatrix:
    """AC-12 / AC-25 / AC-26：白名单语义矩阵三态锁死"""

    def test_disabled_returns_none(self):
        # 未启用 → None（存量全量放行零变化）
        client = ExternalMCPClient()
        client._registry = registry
        assert client.agent_allowed_tools() is None

    def test_enabled_empty_whitelist_builtin_only(self, monkeypatch):
        # 启用 + 白名单空 → 非 None（= 只放内置，外部全拒；绝不 None 放行）
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_tools", [])
        client = ExternalMCPClient()
        client._registry = registry
        client.registered = {"ext_a"}
        allowed = client.agent_allowed_tools()
        assert allowed is not None
        assert len(allowed) == 10
        assert "ext_a" not in allowed

    def test_whitelist_unregistered_name_no_error(self, monkeypatch):
        # AC-26：白名单含未注册名 → 不报错、集合无该名
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_tools",
                            ["ext_registered", "ext_not_registered"])
        client = ExternalMCPClient()
        client._registry = registry
        client.registered = {"ext_registered"}
        allowed = client.agent_allowed_tools()
        assert "ext_registered" in allowed
        assert "ext_not_registered" not in allowed

    def test_not_initialized_returns_none_even_if_enabled(self, monkeypatch):
        # AC-25 补充：启用但 init_ext 从未成功（_registry=None）→ None（无注册表可组装）
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        client = ExternalMCPClient()
        assert client.agent_allowed_tools() is None


# ══════════════════════════════════════════════════════════════════
# WP-C：配置（AC-14~AC-15）
# ══════════════════════════════════════════════════════════════════


class TestConfig:
    """AC-14~AC-15：默认值 + PW_ 环境变量映射"""

    def test_defaults_all_off(self):
        # AC-14：默认全关（存量零变化）
        s = Settings(_env_file=None)
        assert s.mcp_external_enabled is False
        assert s.mcp_external_command == []
        assert s.mcp_external_tools == []
        assert s.mcp_external_timeout == 10.0

    def test_env_mapping(self, monkeypatch):
        # AC-15：PW_MCP_EXTERNAL_* 环境变量生效（JSON 数组解析）
        monkeypatch.setenv("PW_MCP_EXTERNAL_ENABLED", "true")
        monkeypatch.setenv("PW_MCP_EXTERNAL_COMMAND",
                           '["python","scripts/mcp_sample_server.py"]')
        monkeypatch.setenv("PW_MCP_EXTERNAL_TOOLS", '["ext_append_log"]')
        monkeypatch.setenv("PW_MCP_EXTERNAL_TIMEOUT", "5.5")
        s = Settings(_env_file=None)
        assert s.mcp_external_enabled is True
        assert s.mcp_external_command == ["python", "scripts/mcp_sample_server.py"]
        assert s.mcp_external_tools == ["ext_append_log"]
        assert s.mcp_external_timeout == 5.5


# ══════════════════════════════════════════════════════════════════
# WP-D：lifespan + 端点白名单（AC-16~AC-19 / AC-38）
# ══════════════════════════════════════════════════════════════════


def _patch_lifespan_deps(monkeypatch):
    """打桩 lifespan 全部重量级依赖（init_db/预热/调度/MCP 任务组）

    注意：rag.retrieval.reranker 的模块名与实例名同名（from-import 在包命名
    空间遮蔽了模块引用），monkeypatch 字符串路径会解析到实例——一律经
    sys.modules 取模块对象再打属性。
    """
    monkeypatch.setattr(settings, "jwt_secret", "test")
    monkeypatch.setattr(settings, "mcp_token", "test")
    monkeypatch.setattr(main_module, "init_db", mock.AsyncMock())
    monkeypatch.setattr(main_module, "cache", SimpleNamespace(
        get=mock.AsyncMock(return_value=None)))
    fake_emb = SimpleNamespace(embed_text=mock.AsyncMock(return_value=[0.1]))
    monkeypatch.setattr("rag.retrieval.embeddings.embedding_service", fake_emb)
    fake_llm_factory = SimpleNamespace(get_client=mock.MagicMock(
        side_effect=RuntimeError("测试不打桩真实 LLM")))
    monkeypatch.setattr("llm.client.LLMFactory", fake_llm_factory)
    monkeypatch.setattr("rag.retrieval.factcheck_judge.hhem_judge",
                        SimpleNamespace(predict=mock.AsyncMock(return_value=None)))
    import sys as _sys
    reranker_mod = _sys.modules["rag.retrieval.reranker"]
    monkeypatch.setattr(reranker_mod, "reranker",
                        SimpleNamespace(_lazy_load=lambda: None))
    crawler_mod = _sys.modules["rag.crawl.crawler"]
    monkeypatch.setattr(crawler_mod, "start_scheduler", lambda: None)
    monkeypatch.setattr(crawler_mod, "shutdown_scheduler", lambda: None)
    # feedback_scanner 由 lifespan 函数体内延迟 import（sys.modules 可能未加载）——
    # 显式 import 后打属性（lifespan 内 from-import 取的是模块属性，patch 生效）
    import rag.crawl.feedback_scanner as _scanner_mod
    monkeypatch.setattr(_scanner_mod, "setup_feedback_scheduler", lambda flag: None)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_http_ctx():
        yield

    monkeypatch.setattr(main_module, "mcp_http_lifespan", _noop_http_ctx)


class TestLifespan:
    """AC-16~AC-17：startup/shutdown 挂接 + fail-open"""

    def test_lifespan_calls_init_and_close(self, monkeypatch):
        # AC-16/17：startup 调 init_ext(registry) + shutdown 调 close()
        _patch_lifespan_deps(monkeypatch)
        init_mock = mock.AsyncMock(return_value=0)
        close_mock = mock.AsyncMock()
        monkeypatch.setattr(main_module.mcp_client.external, "init_ext", init_mock)
        monkeypatch.setattr(main_module.mcp_client.external, "close", close_mock)

        async def run():
            async with main_module.lifespan(main_module.app):
                pass

        asyncio.run(run())
        assert init_mock.await_count == 1
        assert init_mock.await_args.args[0] is main_module.registry
        assert close_mock.await_count == 1

    def test_lifespan_spawn_failure_service_survives(self, monkeypatch):
        # AC-16/31：init_ext 抛异常（生产不可能——内部全捕获；此处模拟更外层
        # 意外）→ lifespan 不崩的兜底由 init_ext fail-open 保证；这里验证
        # init_ext 内部捕获路径：spawn 失败服务照常启动
        _patch_lifespan_deps(monkeypatch)
        real_init = main_module.mcp_client.external.init_ext

        async def _spawn_fail(reg):
            # enabled=True + command 指向不存在命令 → 内部 fail-open 返回 0
            monkeypatch.setattr(settings, "mcp_external_enabled", True)
            monkeypatch.setattr(settings, "mcp_external_command",
                                ["no_such_command_xyz"])
            return await real_init(reg)

        async def run():
            async with main_module.lifespan(main_module.app):
                return "started"

        monkeypatch.setattr(main_module.mcp_client.external, "init_ext", _spawn_fail)
        assert asyncio.run(run()) == "started"


class TestEndpointWhitelist:
    """AC-18~AC-19：两端点白名单拒绝（无绕过口）"""

    def _setup_external(self, monkeypatch, tool_name: str = "ext_fake"):
        """启用外部 + 假外部工具注册进全局 registry（monkeypatch.setitem 自动清理）"""
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_tools", [])  # 空 = 外部全拒

        async def _fake_ext_func(ctx, args):
            return "外部工具真执行了（不应发生）"

        fake_tool = main_module.registry._tools.get(tool_name)
        # 注册假外部工具（setitem teardown 自动删除，不污染全局 registry）
        import agent.tool_registry as tr_mod
        monkeypatch.setitem(
            main_module.registry._tools, tool_name,
            tr_mod.AgentTool(tool_name, "假外部工具",
                             {"type": "object"}, _fake_ext_func,
                             group=None, approval="required", no_retry=True))
        monkeypatch.setattr(external, "registered", {tool_name})
        monkeypatch.setattr(external, "_registry", main_module.registry)

    def test_agent_endpoint_denies_external(self, monkeypatch):
        # AC-18：手写 ReAct 端点 → 越权调用拒绝、提示含"权限白名单"、func 未执行
        self._setup_external(monkeypatch)
        fake = _fake_llm([
            _tool_call("ext_fake", {"content": "x"}),
            _answer("已按提示处理"),
        ])
        events = []

        async def run():
            with mock.patch("agent.react.LLMFactory.get_client", return_value=fake):
                transport = httpx.ASGITransport(app=main_module.app,
                                                raise_app_exceptions=True)
                async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as client:
                    resp = await client.post(
                        "/ai/rag/chat/agent",
                        json={"query": "测试", "history": []},
                    )
                assert resp.status_code == 200
                events.extend(_parse_sse(resp.content))

        asyncio.run(run())
        tool_results = [json.loads(e["data"]) for e in events
                        if e["event"] == "tool_result"]
        assert "权限白名单" in tool_results[0]["result"]
        assert "外部工具真执行了" not in tool_results[0]["result"]

    def test_agent_lg_endpoint_denies_external(self, monkeypatch):
        # AC-19：LangGraph 端点同样受白名单约束（拒绝口径一致）
        self._setup_external(monkeypatch)
        fake = _fake_llm([
            _tool_call("ext_fake", {"content": "x"}),
            _answer("已按提示处理"),
        ])
        events = []

        async def run():
            with mock.patch("agent.langgraph_react.LLMFactory.get_client",
                            return_value=fake):
                transport = httpx.ASGITransport(app=main_module.app,
                                                raise_app_exceptions=True)
                async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as client:
                    resp = await client.post(
                        "/ai/rag/chat/agent-lg",
                        json={"query": "测试", "history": []},
                    )
                assert resp.status_code == 200
                events.extend(_parse_sse(resp.content))

        asyncio.run(run())
        tool_results = [json.loads(e["data"]) for e in events
                        if e["event"] == "tool_result"]
        assert "权限白名单" in tool_results[0]["result"]

    def test_agent_endpoint_default_allows_builtin(self, monkeypatch):
        # AC-38：默认（外部未启用）allowed_tools=None → 内置工具全量放行（存量）
        fake = _fake_llm([_answer("无工具回答")])
        events = []

        async def run():
            with mock.patch("agent.react.LLMFactory.get_client", return_value=fake):
                transport = httpx.ASGITransport(app=main_module.app,
                                                raise_app_exceptions=True)
                async with httpx.AsyncClient(transport=transport,
                                             base_url="http://test") as client:
                    resp = await client.post(
                        "/ai/rag/chat/agent",
                        json={"query": "你好", "history": []},
                    )
                events.extend(_parse_sse(resp.content))

        asyncio.run(run())
        assert events[-1]["event"] == "done"


# ══════════════════════════════════════════════════════════════════
# WP-E：langgraph 透传（AC-20~AC-21）
# ══════════════════════════════════════════════════════════════════


class TestLanggraphAllowedTools:
    """AC-20~AC-21：缺省 None 零变化 / 传入白名单越权拒绝"""

    def test_state_has_allowed_tools_key(self):
        from agent.langgraph_react import ReActGraphState
        assert "allowed_tools" in ReActGraphState.__annotations__

    def test_langgraph_loop_denies_outside_whitelist(self, monkeypatch):
        # AC-21：react_agent 走 langgraph？——langgraph 无非流式 agent 包装带
        # allowed_tools（端点层透传已由 AC-19 集成覆盖）。这里单测循环级：
        # langgraph_react_loop(allowed_tools=...) → execute_tools 拒绝越权工具
        from agent.langgraph_react import langgraph_react_loop
        from agent.react import _build_messages
        reg = register_builtin_tools(ToolRegistry())
        fake = _fake_llm([
            _tool_call("search_knowledge", {"query": "q"}),
            _answer("答案"),
        ])
        events = []

        async def run():
            with mock.patch("agent.langgraph_react.LLMFactory.get_client",
                            return_value=fake):
                ctx = ReactContext("q", "tester")
                # 白名单不含 search_knowledge → 拒绝
                async for evt in langgraph_react_loop(
                        ctx, _build_messages(ctx), 4, tools=reg,
                        allowed_tools={"recall_memory"}):
                    events.append(evt)

        asyncio.run(run())
        results = [e for e in events if e["type"] == "tool_result"]
        assert "权限白名单" in results[0]["result"]

    def test_langgraph_loop_none_allows_all(self, monkeypatch):
        # AC-20：缺省 None → 全量放行（存量语义）——内置工具正常执行
        from agent.langgraph_react import langgraph_react_loop
        from agent.react import _build_messages
        reg = register_builtin_tools(ToolRegistry())

        async def fake_retrieve(query, top_k=5, mode="hybrid"):
            return [{"id": 1, "title": "t", "content": "c",
                     "hybrid_score": 0.9}]

        fake = _fake_llm([
            _tool_call("search_knowledge", {"query": "q"}),
            _answer("答案"),
        ])
        events = []

        async def run():
            with mock.patch("agent.langgraph_react.LLMFactory.get_client",
                            return_value=fake):
                with mock.patch("agent.tool_registry.hybrid_retriever") as hr:
                    hr.retrieve = fake_retrieve
                    ctx = ReactContext("q", "tester")
                    async for evt in langgraph_react_loop(
                            ctx, _build_messages(ctx), 4, tools=reg):
                        events.append(evt)

        asyncio.run(run())
        results = [e for e in events if e["type"] == "tool_result"]
        assert "文档" in results[0]["result"] or "score" in results[0]["result"]


# ══════════════════════════════════════════════════════════════════
# WP-F：样例 server + 真实子进程握手（AC-22~AC-24，核心验收）
# ══════════════════════════════════════════════════════════════════


class TestSampleServer:
    """AC-22~AC-24：可 import + 真实 stdio 握手 + 注册审批链路"""

    def test_sample_server_importable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mcp_sample_server", _SAMPLE_SERVER)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.mcp is not None
        assert hasattr(mod, "ext_current_time")
        assert hasattr(mod, "ext_append_log")

    def test_real_subprocess_handshake(self):
        # AC-23：真实 stdio 子进程 → initialize → list_tools 2 实名工具 →
        # call_tool ext_current_time 返回真实 UTC 时间（非 mock，核心验收）
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def run():
            params = StdioServerParameters(
                command=sys.executable, args=[_SAMPLE_SERVER])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    names = [t.name for t in result.tools]
                    assert names == ["ext_current_time", "ext_append_log"]
                    r = await session.call_tool("ext_current_time", {})
                    assert r.isError is False
                    assert "T" in r.content[0].text  # ISO 时间

        asyncio.run(run())

    def test_register_and_approval_flow(self, monkeypatch, tmp_path):
        # AC-24：真实子进程注册链路 + 审批治理：
        #   未审批 → 拦截提示 + pending 落库（打桩 DB 断言 INSERT）
        #   approve → 真实执行（mcp_sample_out.log 确实追加）
        # 全程单个 asyncio.run：anyio cancel scope 与 task 绑定，stdio 上下文
        # 的进入/退出必须同 task（跨 asyncio.run 会 "exit cancel scope in a
        # different task"）
        from pathlib import Path as _P
        log_path = _P(main_module.__file__).parent / "mcp_sample_out.log"
        unique = f"module084-ac24-{id(tmp_path)}"
        monkeypatch.setattr(settings, "mcp_external_enabled", True)
        monkeypatch.setattr(settings, "mcp_external_command",
                            [sys.executable, _SAMPLE_SERVER])
        monkeypatch.setattr(settings, "mcp_external_tools", ["ext_append_log"])

        # 审批 DB 打桩：未审批（first=None 查不到 approved）→ 提交 pending；
        # approve 模拟（first=1）→ 放行真实执行
        session_db = _FakeSessionDB()
        factory = _fake_db_factory(session_db)
        monkeypatch.setattr("src.database.async_session_factory", factory)
        client = ExternalMCPClient()

        async def scenario():
            """单 task 全链路：init_ext → 未审批拦截 → approve 后真实执行 → close"""
            count = await client.init_ext(main_module.registry)
            tool = main_module.registry.get("ext_append_log")
            # ① 未审批：拦截提示 + INSERT pending 落库
            result1 = await tool.run({"content": unique}, None)
            # ② approve 后：真实执行（文件追加）
            session_db.first_value = 1
            result2 = await tool.run({"content": unique}, None)
            await client.close()
            return count, result1, result2

        try:
            count, result1, result2 = asyncio.run(scenario())
            assert count >= 1
            assert "ext_append_log" in client.registered
            assert main_module.registry.get("ext_append_log").approval == "required"
            assert "需人工审批" in result1
            inserts = [s for s, _ in session_db.executed if "INSERT" in s]
            assert inserts, "未审批调用应提交 pending 申请"
            assert "已追加" in result2
            assert unique in log_path.read_text(encoding="utf-8")
        finally:
            # 全局 registry 清理：init_ext 真实注册的外部工具移除（防污染
            # 同进程后续测试的 len==10 断言），再清单例状态
            for name in list(client.registered):
                main_module.registry._tools.pop(name, None)
            client.registered.clear()
            client._registry = None
            # 清理测试行（保留其他行）
            if log_path.exists():
                lines = [l for l in log_path.read_text(
                    encoding="utf-8").splitlines() if l != unique]
                log_path.write_text("\n".join(lines) + ("\n" if lines else ""),
                                    encoding="utf-8")

    def test_unauthorized_no_approval_submission(self, monkeypatch):
        # AC-18 补充：白名单拒绝发生在执行层（run 之前）→ 不提交审批申请
        request_mock = mock.AsyncMock()
        monkeypatch.setattr("agent.tool_registry._request_approval", request_mock)
        reg = register_builtin_tools(ToolRegistry())
        result = asyncio.run(execute_tool_with_log(
            "ext_x", {"content": "q"}, reg.get("search_knowledge"),
            ReactContext("q"), allowed_tools={"search_knowledge"}))
        assert "权限白名单" in result
        assert request_mock.await_count == 0


# ── 辅助：暴露 _register_tools 供 mock session 测试（保持生产方法私有） ──


async def _register_tools_public(self, reg) -> int:
    """测试桥接：调用私有 _register_tools（mock session 已注入）"""
    return await ExternalMCPClient._register_tools(self, reg)


ExternalMCPClient._register_tools_public = _register_tools_public
