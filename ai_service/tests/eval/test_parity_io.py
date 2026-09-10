"""module-092 扩展：LLM 阶段输入输出留痕单测（parity_io）

覆盖：
- `_trunc`：超长截断（标注原长度）、非字符串原样透传
- `_snap_input`：三方法形态（generate 取 prompt / chat 取 messages /
  chat_with_tools 额外带 tools）、kwargs 回退
- `_snap_output`：str 与 chat_with_tools dict 两种形态
- `LlmIoTracer`：行为透传（原返回值不变）、逐次记录、seq 递增、
  in_tool 标记跟随深度回调、异常路径记录后仍抛出、非 LLM 属性透传
- `write_io_trace`：写 JSONL + 条数、空列表返回 0、追加累积、
  写失败 fail-open 返回 0（不中断跑批）
- `read_tool_rows`：DB 异常 fail-open 返回 []

实现说明：落盘路径经 fixture 钉到 tmp_path，避免污染项目目录与跨用例串扰；
同步用例内 asyncio.run 执行（对齐 test_reflector_temperature.py 风格）。
"""
import asyncio
import json
from unittest import mock

import pytest

from eval import parity_io


@pytest.fixture(autouse=True)
def isolate_trace_file(tmp_path, monkeypatch):
    """钉住落盘路径到 tmp（防污染项目目录、防跨用例串扰）"""
    monkeypatch.setattr(parity_io, "_TRACE_FILE", tmp_path / "io-test.jsonl",
                        raising=False)


class _FakeClient:
    """假 LLM 客户端：三方法可配（返回固定值或抛错），记录调用"""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls: list = []

    async def chat(self, messages):
        self.calls.append(("chat", messages))
        if self._error:
            raise self._error
        return self._result

    async def chat_with_tools(self, messages, tools):
        self.calls.append(("chat_with_tools", messages, tools))
        return self._result

    async def generate(self, prompt):
        self.calls.append(("generate", prompt))
        return self._result


class TestSnapshots:
    """入参/出参序列化"""

    def test_trunc_passthrough_non_string(self):
        assert parity_io._trunc(123) == 123
        assert parity_io._trunc(None) is None

    def test_trunc_marks_original_length(self):
        total = parity_io._MAX_FIELD + 10
        out = parity_io._trunc("x" * total)
        assert out.startswith("x" * 100)
        assert f"...[truncated,total={total}]" in out

    def test_snap_input_generate_takes_prompt(self):
        snap = parity_io._snap_input("generate", ("提示词",), {})
        assert snap == {"method": "generate", "prompt": "提示词"}

    def test_snap_input_chat_takes_messages(self):
        msgs = [{"role": "user", "content": "hi"}]
        snap = parity_io._snap_input("chat", (msgs,), {})
        assert snap["method"] == "chat"
        assert snap["messages"] == msgs
        assert "tools" not in snap

    def test_snap_input_chat_with_tools_carries_tools(self):
        msgs, tools = [{"role": "user", "content": "x"}], [{"type": "function"}]
        snap = parity_io._snap_input("chat_with_tools", (msgs, tools), {})
        assert snap["messages"] == msgs
        assert snap["tools"] == tools

    def test_snap_input_kwargs_fallback(self):
        snap = parity_io._snap_input("chat", (), {"messages": [{"role": "user"}]})
        assert snap["messages"] == [{"role": "user"}]

    def test_snap_output_str(self):
        assert parity_io._snap_output("答案") == {"content": "答案"}

    def test_snap_output_dict(self):
        out = {"content": "c", "tool_calls": [{"name": "t"}],
               "message": {"role": "assistant", "content": "c"}}
        snap = parity_io._snap_output(out)
        assert snap["content"] == "c"
        assert snap["tool_calls"] == [{"name": "t"}]
        assert "assistant" in snap["message"]


class TestLlmIoTracer:
    """IO 留痕代理：透传 + 记录"""

    def test_passthrough_and_record(self):
        records: list = []
        tracer = parity_io.wrap_llm_io(_FakeClient(result="答案"), records,
                                       "hand", "at-001", 1)
        out = asyncio.run(tracer.chat([{"role": "user", "content": "q"}]))
        assert out == "答案"                     # 返回值原样透传
        assert len(records) == 1
        rec = records[0]
        assert (rec["seq"], rec["loop"], rec["task_id"], rec["round"]) == \
            (0, "hand", "at-001", 1)
        assert rec["input"]["method"] == "chat"
        assert rec["output"]["content"] == "答案"
        assert rec["duration_ms"] >= 0

    def test_seq_increments_per_call(self):
        records: list = []
        tracer = parity_io.wrap_llm_io(_FakeClient(result="x"), records,
                                       "hand", "t", 1)
        asyncio.run(tracer.chat([{"role": "user"}]))
        asyncio.run(tracer.generate("p"))
        assert [r["seq"] for r in records] == [0, 1]
        assert records[1]["input"]["method"] == "generate"

    def test_in_tool_flag_follows_depth(self):
        records: list = []
        depth = [0]
        tracer = parity_io.wrap_llm_io(_FakeClient(result="x"), records,
                                       "hand", "t", 1,
                                       depth_getter=lambda: depth[0])
        asyncio.run(tracer.chat([{"role": "user"}]))
        depth[0] = 2                                  # 进入工具窗口
        asyncio.run(tracer.chat([{"role": "user"}]))
        assert [r["in_tool"] for r in records] == [False, True]

    def test_chat_with_tools_records_tool_calls(self):
        records: list = []
        payload = {"content": "", "tool_calls": [{"name": "search_knowledge"}],
                   "message": {"role": "assistant"}}
        tracer = parity_io.wrap_llm_io(_FakeClient(result=payload), records,
                                       "lg", "at-002", 1)
        asyncio.run(tracer.chat_with_tools([{"role": "user"}], [{"type": "function"}]))
        assert records[0]["output"]["tool_calls"] == [{"name": "search_knowledge"}]
        assert records[0]["input"]["tools"] == [{"type": "function"}]

    def test_error_records_then_raises(self):
        records: list = []
        tracer = parity_io.wrap_llm_io(_FakeClient(error=RuntimeError("boom")),
                                       records, "hand", "t", 2)
        with pytest.raises(RuntimeError):
            asyncio.run(tracer.chat([{"role": "user"}]))
        assert len(records) == 1                      # 失败也留痕（含 error 字段）
        assert "boom" in records[0]["output"]["error"]

    def test_non_llm_attr_passthrough(self):
        records: list = []
        inner = _FakeClient(result="x")
        inner._provider_label = lambda: "opencode"    # 非三方法属性应透传
        tracer = parity_io.wrap_llm_io(inner, records, "hand", "t", 1)
        assert tracer._provider_label() == "opencode"
        assert records == []


class TestWriteTrace:
    """JSONL 落盘"""

    def test_write_and_count(self):
        records = [{"seq": 0,
                    "input": {"messages": [{"role": "user", "content": "中文"}]}}]
        assert parity_io.write_io_trace(records) == 1
        line = parity_io.trace_file().read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        assert parsed["input"]["messages"][0]["content"] == "中文"   # 中文不转义

    def test_empty_records_returns_zero(self):
        assert parity_io.write_io_trace([]) == 0

    def test_append_accumulates_lines(self):
        parity_io.write_io_trace([{"seq": 0}])
        parity_io.write_io_trace([{"seq": 1}])
        lines = parity_io.trace_file().read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_write_failure_is_fail_open(self, monkeypatch):
        def _boom():
            raise OSError("disk full")

        monkeypatch.setattr(parity_io, "trace_file", _boom)
        assert parity_io.write_io_trace([{"seq": 0}]) == 0   # 不抛，不中断跑批


class TestReadToolRows:
    """工具段读回（自 parity_telemetry 迁入）"""

    def test_db_failure_is_fail_open(self):
        with mock.patch("eval.parity_io.async_session_factory",
                        side_effect=RuntimeError("db down")):
            assert asyncio.run(parity_io.read_tool_rows("t")) == []
