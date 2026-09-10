"""LLM 阶段输入输出留痕（eval 层旁路，module-092 扩展）

需求来源：用户 2026-09-10「各个阶段的输入输出也需要」。

- **工具阶段**：`tool_call_logs` 已含 `args`（输入）+ `result_preview`（输出），无需新增
- **LLM 阶段**：本模块在 eval 层包裹客户端，逐次记录
  `(messages/prompt/tools)` → `(content/tool_calls)`，追加写 JSONL

设计约束：
- **零生产 diff**：不改 `llm/client.py`；mock 包装全在 eval 层
- **不参与 092 三段遥测的计时/分桶口径**：纯旁路记录，只读不改

产物：`ai_service/eval_io_traces/io-<时间戳>.jsonl`（一行一次 LLM 调用；
不入 git，见 .gitignore）
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from src.database import async_session_factory

logger = logging.getLogger("parity_io")

IO_TRACE_DIR = Path(__file__).resolve().parent.parent / "eval_io_traces"
_MAX_FIELD = 20000  # 单字段字符上限（超长截断并标注原长度，防单条记录过大）
_TRACE_FILE: Optional[Path] = None


def _trunc(value):
    """超长字符串截断（保留前缀 + 标注原长度）；非字符串原样返回"""
    if isinstance(value, str) and len(value) > _MAX_FIELD:
        return value[:_MAX_FIELD] + f"...[truncated,total={len(value)}]"
    return value


def _snap_input(method: str, args: tuple, kwargs: dict) -> dict:
    """序列化 LLM 调用入参（按方法形态区分）

    Args:
        method: chat / chat_with_tools / generate
        args: 位置参数
        kwargs: 关键字参数

    Returns:
        {"method", "messages"|"prompt", "tools"?}
    """
    snap: dict = {"method": method}
    if method == "generate":
        snap["prompt"] = _trunc(args[0] if args else kwargs.get("prompt"))
        return snap
    snap["messages"] = _trunc(args[0] if args else kwargs.get("messages"))
    if method == "chat_with_tools":
        snap["tools"] = args[1] if len(args) > 1 else kwargs.get("tools")
    return snap


def _snap_output(out) -> dict:
    """序列化 LLM 调用出参（chat/generate 返回 str；chat_with_tools 返回 dict）

    Args:
        out: 客户端返回值

    Returns:
        {"content", "tool_calls"?, "message"?}
    """
    if isinstance(out, dict):
        return {
            "content": _trunc(out.get("content")),
            "tool_calls": out.get("tool_calls"),
            "message": _trunc(json.dumps(out.get("message"), ensure_ascii=False,
                                         default=str)),
        }
    return {"content": _trunc(out)}


def _usage_delta(records, start: int) -> dict:
    """取本次 LLM 调用新增的 usage（与 _record_usage 调用顺序对齐）

    `_record_usage` 在客户端内部、每次调用返回前触发，顺序与 LLM 调用一致；
    故用「调用前长度 → 调用后长度」差分即可把 usage 精确归属到本次调用，
    无需改动生产代码（module-092 分阶段 token 口径）。

    Args:
        records: usage 收集列表（_usage_interceptor 填充）；None 表示未接入
        start: 本次调用前的列表长度

    Returns:
        {"prompt_tokens", "completion_tokens", "calls"}；无新增返回 {}
    """
    if not records or len(records) <= start:
        return {}
    new = records[start:]
    return {"prompt_tokens": sum(r["prompt_tokens"] for r in new),
            "completion_tokens": sum(r["completion_tokens"] for r in new),
            "calls": len(new)}


class LlmIoTracer:
    """LLM 客户端 IO 留痕代理（包在 _TimingClientProxy 外层，只旁路记录）

    Args:
        inner: 被包装客户端（_TimingClientProxy 或真实 client，行为透传）
        records: 本次运行的记录收集列表
        meta: 运行上下文 {"loop","task_id","round"}
        tool_name_getter: 返回当前工具名（None = 环路级调用）
        usage_records: usage 收集列表（差分归属本次调用的 token；None = 不记录）
    """

    METHODS = ("chat", "chat_with_tools", "generate")

    def __init__(self, inner, records: list, meta: dict, tool_name_getter=None,
                 usage_records=None):
        self._inner = inner
        self._records = records
        self._meta = meta
        self._tool_name = tool_name_getter
        self._usage = usage_records
        self._seq = 0

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in self.METHODS:
            return attr

        async def _traced(*args, **kwargs):
            tool = self._tool_name() if self._tool_name else None
            u0 = len(self._usage) if self._usage else 0
            rec = {"seq": self._seq, **self._meta,
                   "tool": tool, "in_tool": tool is not None,
                   "input": _snap_input(name, args, kwargs)}
            self._seq += 1
            t0 = time.perf_counter()
            try:
                out = await attr(*args, **kwargs)
            except Exception as e:
                rec["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                rec["output"] = {"error": f"{type(e).__name__}: {e}"}
                self._records.append(rec)
                raise
            rec["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            rec["output"] = _snap_output(out)
            rec["usage"] = _usage_delta(self._usage, u0)
            self._records.append(rec)
            return out

        return _traced


def wrap_llm_io(inner, records: list, loop: str, task_id: str, k: int,
                tool_name_getter=None, usage_records=None) -> LlmIoTracer:
    """构造 IO 留痕代理（便捷工厂，封装 meta 组装）

    Args:
        inner: 被包装客户端
        records: 记录收集列表（调用方持有，运行结束交由 write_io_trace 落盘）
        loop: 环路名
        task_id: 任务 id
        k: 独立尝试序号（轮次）
        tool_name_getter: 返回当前工具名（None = 环路级调用）
        usage_records: usage 收集列表（差分归属 token；None = 不记录）

    Returns:
        LlmIoTracer 实例（可 mock.patch 回填给 agent 层）
    """
    return LlmIoTracer(inner, records,
                       {"loop": loop, "task_id": task_id, "round": k},
                       tool_name_getter=tool_name_getter,
                       usage_records=usage_records)


def stage_tokens(records: list) -> dict:
    """按阶段汇总 token（module-092 分阶段 token 口径）

    阶段划分与三段遥测一致：
      - `loop`  环路级 LLM 调用（ReAct 推理轮次 + 预算耗尽兜底生成）
      - `tool`  工具内 LLM 调用（generate_answer 内部生成、re_search 图抽取等）

    Args:
        records: 一次运行或全量的 IO 留痕记录列表

    Returns:
        {"loop": {...}, "tool": {...}, "total": {...}}，每项含
        prompt_tokens / completion_tokens / calls / by_tool（工具内按工具名细分）
    """
    out: dict = {"loop": {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0,
                          "by_tool": {}},
                 "tool": {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0,
                          "by_tool": {}}}
    for r in records:
        usage = r.get("usage") or {}
        if not usage:
            continue
        stage = "tool" if r.get("in_tool") else "loop"
        bucket = out[stage]
        for key in ("prompt_tokens", "completion_tokens", "calls"):
            bucket[key] += usage.get(key, 0)
        if stage == "tool":
            name = r.get("tool") or "unknown"
            sub = bucket["by_tool"].setdefault(
                name, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
            for key in ("prompt_tokens", "completion_tokens", "calls"):
                sub[key] += usage.get(key, 0)
    out["total"] = {k: out["loop"][k] + out["tool"][k]
                    for k in ("prompt_tokens", "completion_tokens", "calls")}
    return out


def trace_file() -> Path:
    """当前运行的 JSONL 落盘路径（进程内首次调用生成，时间戳命名）"""
    global _TRACE_FILE
    if _TRACE_FILE is None:
        IO_TRACE_DIR.mkdir(parents=True, exist_ok=True)
        _TRACE_FILE = IO_TRACE_DIR / f"io-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        logger.info("IO 留痕落盘: %s", _TRACE_FILE)
    return _TRACE_FILE


def write_io_trace(records: list) -> int:
    """追加写 JSONL（一行一次 LLM 调用）

    Args:
        records: 一次运行的记录列表

    Returns:
        写入条数（失败 fail-open 返回 0，不中断跑批）
    """
    if not records:
        return 0
    try:
        with open(trace_file(), "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        return len(records)
    except Exception as e:
        logger.warning("IO 留痕写入失败（fail-open）: %s", e)
        return 0


async def read_tool_rows(trace_id: str) -> list:
    """读回一次运行的 tool_call_logs 行（工具段数据源，AC-5）

    原位于 parity_telemetry._tool_rows，迁入本模块以腾出 AST 空间
    （parity_telemetry 受 module-092 的 ≤200 AST 红线约束）。

    Args:
        trace_id: 运行 trace 标识（eval-<id>-<loop>-<k>）

    Returns:
        行 dict 列表（tool_name / duration_ms / result_ok）；失败返回 []
    """
    try:
        async with async_session_factory() as session:
            rows = (await session.execute(
                text("SELECT tool_name, duration_ms, result_ok FROM tool_call_logs"
                     " WHERE trace_id = :t ORDER BY id"),
                {"t": trace_id})).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("tool_call_logs 读回失败（工具段记 0，如实标注）: %s", e)
        return []
