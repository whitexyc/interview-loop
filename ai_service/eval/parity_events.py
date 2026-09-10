"""评测记录维度增强（module-092 延伸）：答案质量细节 + 异常事件捕获

需求来源：用户 2026-09-10「哪些东西需要记录」讨论——补两个诊断维度：

1. **答案质量细节**：现有判定只给 pass/不 pass，看不出**漏了哪个要点**。
   任务集 `answer_points` 是 1~3 个关键词（`eval/agent_tasks.py:194`），
   故逐要点记录命中情况即可回答"这题为什么没过"。
2. **异常事件**：工具超时/失败在 `agent/tool_registry.py:_execute` 里是
   **返回文案而非抛异常**（`"(工具 X 执行超时)"` / `""`），自动重试**只记日志**。
   故从日志侧旁路捕获是**零生产改动**的唯一途径（红线：`agent/` 零 diff）。

设计约束：不改生产代码；捕获失败一律 fail-open（不影响跑批）；不参与
092 三段遥测的计时/分桶口径。
"""
import logging
from contextlib import contextmanager

_logger = logging.getLogger("parity_events")

# 事件源：工具执行的超时/重试/失败都记在这个 logger 上（agent/tool_registry.py）
TOOL_LOGGER_NAME = "agent.tool_registry"

# 事件分类模式（**按生产日志原文精确匹配**，见 agent/tool_registry.py:_execute）
#   1. "工具 X 超时 (15.0s)"            → timeout
#   2. "工具 X 首次失败，自动重试: e"    → retry（触发重试路径，最终结果未知）
#   3. "工具 X 重试超时 (15.0s)"         → retry + timeout
#   4. "工具 X 重试仍失败，返回空: e"    → retry + fail（重试也失败 = 最终失败）
#   5. "工具 X 执行失败，返回空: e"      → fail（未走重试的最终失败）
# 注意：**不能用裸 "失败" 泛匹配**——它会把 #2 的"首次失败"误算成最终失败（首次失败
# 只是触发重试，重试可能成功），导致 fail 计数虚高。
_EVENT_PATTERNS = (
    ("timeout", ("超时",)),
    ("retry", ("自动重试", "重试超时", "重试仍失败")),
    ("fail", ("执行失败", "重试仍失败")),
)


def answer_point_hits(points, answer) -> dict:
    """逐要点命中情况（答案质量细节）

    判定口径与 `agent_tasks.outcome_pass` 一致（子串包含），故命中情况可
    直接解释"为什么这题没过"：任一 False 即失分点。

    Args:
        points: 任务集的 `answer_points`（1~3 个关键词）
        answer: 该次运行的最终答案（可为 None）

    Returns:
        {"<要点>": bool, ...}；`points` 为空时返回 {}
    """
    text = answer or ""
    return {str(p): (str(p) in text) for p in (points or [])}


def failed_points(hits: dict) -> list:
    """从命中情况中挑出未命中要点（供报告直出失分点）

    Args:
        hits: `answer_point_hits` 的返回值

    Returns:
        未命中要点列表（全命中则空列表）
    """
    return [p for p, ok in (hits or {}).items() if not ok]


def quality_detail(item: dict, result: dict) -> dict:
    """答案质量细节（组合入口，供调用方一行接入）

    Args:
        item: 任务条目（取 `answer_points`）
        result: `run_side` 的逐任务明细（取 `answer`）

    Returns:
        {"answer_points_hit": {要点: bool}, "failed_points": [未命中要点]}
    """
    hits = answer_point_hits((item or {}).get("answer_points"),
                             (result or {}).get("answer"))
    return {"answer_points_hit": hits, "failed_points": failed_points(hits)}


class _EventSink(logging.Handler):
    """把目标 logger 的 WARNING+ 记录追加进 sink（旁路，不改变原日志行为）"""

    def __init__(self, sink: list):
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink.append({"level": record.levelname,
                               "msg": record.getMessage()})
        except Exception as e:  # noqa: BLE001 —— 采集失败不得影响跑批（fail-open）
            # 铁律 5：fail-open 可以吞异常，但**必须留痕**，不得静默
            # （对齐 parity_io.write_io_trace / read_tool_rows 的先例）
            _logger.warning("事件采集失败（fail-open，本次记录丢弃）: %s", e)


@contextmanager
def capture_tool_events(sink: list):
    """旁路捕获工具执行异常事件（超时/重试/失败）

    在 `agent.tool_registry` logger 上挂临时 Handler，退出时移除。
    **不改生产代码**：只旁听，原日志行为逐字不变。

    Args:
        sink: 事件收集列表（本作用域内累积）

    Yields:
        None
    """
    handler = _EventSink(sink)
    target = logging.getLogger(TOOL_LOGGER_NAME)
    target.addHandler(handler)
    try:
        yield
    finally:
        target.removeHandler(handler)


def summarize_events(events: list) -> dict:
    """按类型聚合异常事件（超时 / 重试 / 失败）

    一条日志可计入多类（例："工具 X 重试超时" 同时计入 retry 与 timeout），
    因为二者的诊断含义不同：前者说明触发了重试路径，后者说明最终仍超时。

    Args:
        events: `capture_tool_events` 收集的事件列表

    Returns:
        {"timeout": int, "retry": int, "fail": int, "total": int,
         "details": [{"level","msg"}, ...]}
    """
    out = {"timeout": 0, "retry": 0, "fail": 0, "total": len(events or []),
           "details": list(events or [])}
    for evt in (events or []):
        msg = evt.get("msg", "") if isinstance(evt, dict) else str(evt)
        for key, keywords in _EVENT_PATTERNS:
            if any(kw in msg for kw in keywords):
                out[key] += 1
    return out
