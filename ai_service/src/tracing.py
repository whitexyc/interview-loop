"""
链路式观测（module-088）— span 写侧原语 + 读侧 trace 树
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

写侧：每 span 即时 INSERT fire-and-forget fail-open（对齐 record_tool_call
raw INSERT 先例，无 ORM 模型）；一次请求 = 一条 trace = N spans，根 span
（kind=request）在中间件入口由 begin_request 建立，子 span（工具/决策/检索）
挂在当前根下。trace_id 只消费 src/observability.py 的 contextvar（module-058
零 diff，本模块不写观测上下文）；不引入 task 抽象（module-087 底座）。
读侧：get_trace_tree 按 trace_id 取全部 span 组树（端点层统一 fail-open）。
开关 trace_spans_enabled=false 时零埋点零落库（所有写入原语首行短路）。
不引入新依赖（复用现有 SQLAlchemy + 标准库，无重型 tracing 框架）。
"""
import asyncio
import contextvars
import logging
import re
import uuid
from datetime import datetime

from sqlalchemy import text

from src.config import settings
from src.observability import get_trace_id

logger = logging.getLogger(__name__)

# 当前根 span_id（begin_request 压入；downstream task 经 contextvar 快照继承
# ——BaseHTTPMiddleware 下 call_next 前设置的 contextvar 传给 downstream，
# module-058 已实证）。default ""：无请求上下文时子 span 挂空父（读侧视为根）。
_parent_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_parent_span", default=""
)

# 入站 X-Trace-Id 白名单（传播裁定 3：strip+lower、≤64、字符 [0-9a-f-]）
_TRACE_ID_RE = re.compile(r"^[0-9a-f-]+$")

# span 单条参数化 INSERT（10 列全 :xxx 绑定，无任何拼接；started_at 由 Python
# 侧 utcnow 传入，非 DB default——请求内排序不依赖 DB 时钟）
_SQL_INSERT = """
    INSERT INTO request_spans
        (trace_id, span_id, parent_span_id, name, kind, identity,
         decision, status, duration_ms, started_at)
    VALUES (:trace_id, :span_id, :parent_span_id, :name, :kind, :identity,
            :decision, :status, :duration_ms, :started_at)
"""

# 读侧：按 trace_id 取全部 span（started_at,id 序——请求内因果排序）
_SQL_SELECT = """
    SELECT trace_id, span_id, parent_span_id, name, kind, identity,
           decision, status, duration_ms, started_at
    FROM request_spans
    WHERE trace_id = :t
    ORDER BY started_at, id
"""


def sanitize_incoming_trace(value) -> str:
    """入站 X-Trace-Id 清洗（传播方向裁定：Python 作接收方）

    strip + lower 归一；空/None/超 64/含白名单外字符（非 [0-9a-f-]）→ ""
    （调用方回退 make_trace_id() 自生成，058 行为零回归）。

    Args:
        value: 上游 header 原始值（str 或 None）

    Returns:
        合法 trace_id（小写）或空串
    """
    if not value:
        return ""
    v = str(value).strip().lower()
    if not v or len(v) > 64 or not _TRACE_ID_RE.match(v):
        return ""
    return v


def _new_span_id() -> str:
    """生成 span_id（uuid4 hex 截 16）"""
    return uuid.uuid4().hex[:16]


# fire-and-forget 任务引用池（防 GC：asyncio 规范要求保存任务引用，否则任务
# 可能在完成前被回收——仓库先例 verify_tasks.py / main.py _HHEM_WARMUP_TASK；
# done callback 自清理，集合不随请求增长）
_pending_tasks: set = set()


def _spawn_insert(row: dict) -> None:
    """fire-and-forget 落库调度（无运行事件循环时静默放弃，fail-open）"""
    try:
        task = asyncio.create_task(_insert_span(row))
    except RuntimeError:  # 无运行 loop（同步脚本/解释器收尾）→ 放弃本条 span
        return
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _insert_span(row: dict) -> None:
    """单条 span 参数化 INSERT（全异常 warning 不上抛，不影响主链路）

    Args:
        row: 10 列绑定参数（trace_id/span_id/parent_span_id/name/kind/
            identity/decision/status/duration_ms/started_at）
    """
    try:
        from src.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(text(_SQL_INSERT), row)
            await session.commit()
    except Exception as e:
        logger.warning("request_spans 落库失败（fail-open，不影响主链路）: %s", e)


def begin_request(trace_id: str, endpoint: str, identity: str = "") -> str:
    """请求入口建根 span（kind=request）并压入父 span 上下文

    开关关闭时仍 set 父上下文（无害）但不落库；trace_id 由调用方（中间件
    088 块）先行 sanitize/生成，本函数不改动观测上下文（058 零 diff）。

    Args:
        trace_id: 请求追踪 ID（上游 X-Trace-Id 优先，缺失回退自生成）
        endpoint: 请求路径（根 span name）
        identity: 请求身份（user_id 优先 client_ip 兜底，仅根 span 填）

    Returns:
        根 span_id（同时写入 _parent_var，后续 record_span 行挂在它下面）
    """
    span_id = _new_span_id()
    _parent_var.set(span_id)
    if not settings.trace_spans_enabled:
        return span_id
    _spawn_insert({
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": "",
        "name": endpoint,
        "kind": "request",
        "identity": identity or "",
        "decision": "",
        "status": "ok",
        "duration_ms": 0,
        "started_at": datetime.utcnow(),
    })
    return span_id


def record_span(name: str, kind: str, decision: str = "",
                status: str = "ok", duration_ms: int = 0) -> None:
    """记录一条子 span（挂在当前根 span 下；决策级日志的统一入口）

    开关关闭首行短路（零埋点）；无 trace 上下文（get_trace_id()==""）静默
    跳过（非请求链路的调用——评测脚本/后台任务——零开销零落库）。

    Args:
        name: span 名（工具名/决策点名如 advance_phase/intent_routing/检索）
        kind: span 类型（request/tool/decision/retrieval）
        decision: 决策原因（为什么选这个工具/分支；截断 500 防撑爆）
        status: ok/error/blocked（守门拒绝）
        duration_ms: 耗时毫秒（决策点可为 0）
    """
    if not settings.trace_spans_enabled:
        return
    trace_id = get_trace_id()
    if not trace_id:
        return
    _spawn_insert({
        "trace_id": trace_id,
        "span_id": _new_span_id(),
        "parent_span_id": _parent_var.get(),
        "name": name,
        "kind": kind,
        "identity": "",
        "decision": (decision or "")[:500],
        "status": status,
        "duration_ms": int(duration_ms or 0),
        "started_at": datetime.utcnow(),
    })


def _build_tree(rows: list[dict]) -> list[dict]:
    """span 行列表 → 因果树（纯函数，零副作用）

    每行拷贝并加 children=[]；parent_span_id 非空且父存在 → 挂父 children，
    否则（根 span/孤儿——父缺失的异常数据）入 roots。正常数据恰 1 个根，
    多根容忍返回列表（不丢行）。

    Args:
        rows: SQL 行 dict 列表（started_at,id 序）

    Returns:
        根节点列表（children 嵌套）
    """
    nodes, index = [], {}
    for r in rows:
        node = dict(r)
        node["children"] = []
        nodes.append(node)
        index[node.get("span_id")] = node
    roots = []
    for node in nodes:
        parent = index.get(node.get("parent_span_id") or "")
        if parent is not None and parent is not node:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


async def get_trace_tree(trace_id: str) -> dict | None:
    """读侧：单 trace 的 span 树（端点层统一 fail-open，本函数不吞异常）

    Args:
        trace_id: 请求追踪 ID

    Returns:
        {"trace_id", "span_count", "tree"}（tree 为根节点列表，正常恰 1 根）；
        无数据 → None（端点层转 code 1 "trace 不存在"）

    Raises:
        Exception: DB 异常原样上抛（端点层 except + logger.warning 降级）
    """
    from src.database import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(text(_SQL_SELECT), {"t": trace_id})
        rows = [dict(m) for m in result.mappings()]
    if not rows:
        return None
    return {"trace_id": trace_id, "span_count": len(rows),
            "tree": _build_tree(rows)}
