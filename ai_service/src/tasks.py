"""
任务抽象（module-087）— task 写侧原语 + 读侧单任务概览
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

一次对话请求 = 1 task：中间件建（INSERT status=running）→ persist_request_log
收口（UPDATE intent/status/tokens_used/finished_at，WHERE status='running'
天然幂等）。写侧 fire-and-forget fail-open 对齐 src/tracing.py（088 先例，
无 ORM 模型）；观测聚合经 tasks.trace_id 与 request_logs/tool_call_logs/
request_spans 读侧 join（裁定 1：三表既有 DDL 零改动零迁移）。
"子只读父写"所有权（roadmap 关键设计约束）：tasks.memory_write 列
（父 task=write 子 task=read）+ _memory_write_var 原语 + MemoryService.save
入口闸（rag/memory/memory.py）；v1 无生产调用方置 read（默认 write = 现状
行为逐字），调用方在 T5 子 Agent 编排。
不实现子 Agent 编排（T5）——budget_token_limit 仅结构预留（089 执法面在
agent/react.py 熔断）；checkpoint 逻辑 module-090 接管：save_checkpoint /
load_checkpoint / resume_task 三原语（本文件，v1 无生产调用方，调用方 T5）。
开关 tasks_enabled（PW_TASKS_ENABLED）首行短路：false 零建零收口。
"""
import asyncio
import contextvars
import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import text

from src.config import settings

logger = logging.getLogger(__name__)

# 当前 task_id（begin_task 压入；downstream task 经 contextvar 快照继承，
# 058/088 已实证）+ 记忆写所有权（"子只读父写"：父 task=write 子 task=read）
# + 任务 token 预算上限（module-089；begin_task 解析 config 压入，0=不限）
_task_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_task_id", default="")
_memory_write_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "memory_write_mode", default="write")
_budget_limit_var: contextvars.ContextVar[int] = contextvars.ContextVar(
    "task_budget_limit", default=0)

# task 建行参数化 INSERT（11 绑定列全 :xxx 绑定，无任何拼接；created_at 走
# DB default、finished_at 由收口 UPDATE 传入——NULL=仍 running）
_SQL_INSERT = """
    INSERT INTO tasks
        (task_id, parent_task_id, trace_id, endpoint, intent, status,
         budget_token_limit, tokens_used, memory_write, checkpoint, identity)
    VALUES (:task_id, :parent_task_id, :trace_id, :endpoint, :intent, :status,
            :budget_token_limit, :tokens_used, :memory_write, :checkpoint,
            :identity)
"""

# 收口 UPDATE（一次落定 intent/status/tokens_used/finished_at）：intent 空串
# 不覆盖（CASE）；WHERE status='running' 幂等（重放安全，单收口点无并发双写）；
# checkpoint/budget 列不触碰（089/090 接管）
_SQL_FINISH = """
    UPDATE tasks
    SET intent = CASE WHEN :intent <> '' THEN :intent ELSE intent END,
        status = :status, tokens_used = :tokens_used, finished_at = :finished_at
    WHERE task_id = :task_id AND status = 'running'
"""

# 读侧单任务概览：task 行 13 列 + 3 个标量子查询计数（全参数化只读，经
# trace_id 与观测三表 join——"观测聚合挂在 task 上"的读侧实现）
_SQL_OVERVIEW = """
    SELECT t.task_id, t.parent_task_id, t.trace_id, t.endpoint, t.intent,
           t.status, t.budget_token_limit, t.tokens_used, t.memory_write,
           t.checkpoint, t.identity, t.created_at, t.finished_at,
           (SELECT COUNT(*) FROM request_logs r
            WHERE r.trace_id = t.trace_id) AS request_logs,
           (SELECT COUNT(*) FROM request_spans s
            WHERE s.trace_id = t.trace_id) AS request_spans,
           (SELECT COUNT(*) FROM tool_call_logs c
            WHERE c.trace_id = t.trace_id) AS tool_calls
    FROM tasks t
    WHERE t.task_id = :task_id
"""

# 预算上限覆盖（module-089：task 级 set_task_budget 原语的落库 UPDATE；不加
# status 条件——覆盖语义重放安全；无 JSONB 列，全标量绑定）
_SQL_BUDGET = """
    UPDATE tasks SET budget_token_limit = :budget_token_limit
    WHERE task_id = :task_id
"""

# checkpoint 保存（module-090：JSONB 列必须传 JSON 字符串——087 真缺陷教训，
# 绝不直绑 dict；无 status 条件 = 覆盖语义重放安全（对齐 _SQL_BUDGET），
# finish_task 不触碰 checkpoint 列 → 末次保存必存活）
_SQL_SAVE_CHECKPOINT = """
    UPDATE tasks SET checkpoint = :checkpoint
    WHERE task_id = :task_id
"""

# checkpoint 读取（module-090 读侧；行不存在由调用方兜 {}；asyncpg 对 JSONB
# 默认解码为 dict——load 侧双兼容 dict/str）
_SQL_LOAD_CHECKPOINT = """
    SELECT checkpoint FROM tasks
    WHERE task_id = :task_id
"""

# 恢复（module-090：同 task_id 复用置回 running + finished_at 复位 NULL；
# 白名单 failed/悬挂 running——completed 终态不可复活；checkpoint/trace_id/
# intent/tokens_used 零触碰；幂等：重复调用状态不变）
_SQL_RESUME = """
    UPDATE tasks SET status = 'running', finished_at = NULL
    WHERE task_id = :task_id AND status IN ('failed', 'running')
"""

# fire-and-forget 任务引用池（防 GC：asyncio 规范要求保存任务引用，否则任务
# 可能在完成前被回收——088 minor-1 先例 tracing.py/_pending_tasks；done
# callback 自清理，集合不随请求增长）
_pending_tasks: set = set()


def _spawn(sql: str, params: dict) -> None:
    """fire-and-forget 落库调度（无运行事件循环时静默放弃，fail-open）"""
    try:
        task = asyncio.create_task(_run_sql(sql, params))
    except RuntimeError:  # 无运行 loop（同步脚本/解释器收尾）→ 放弃本条
        return
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


async def _run_sql(sql: str, params: dict) -> None:
    """单条参数化 SQL 执行（全异常 warning 不上抛，不影响主链路）

    Args:
        sql: 参数化 SQL 文本（INSERT/UPDATE，全 :xxx 绑定）
        params: 绑定参数 dict
    """
    try:
        from src.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(text(sql), params)
            await session.commit()
    except Exception as e:
        logger.warning("tasks 落库失败（fail-open，不影响主链路）: %s", e)


def begin_task(trace_id: str, endpoint: str, identity: str = "") -> str:
    """请求入口建 task（INSERT status=running）并压入 task 上下文

    开关关闭时仍 set task 上下文（无害）但不落库（对齐 begin_request 先例）；
    trace 缺失（logs+spans 全关）时由调用方（中间件 087 块）跳过——聚合锚缺失。

    Args:
        trace_id: 请求追踪 ID（观测聚合读侧 join 锚）
        endpoint: 端点路径（对话四端点白名单内）
        identity: 请求身份（user_id 优先 client_ip 兜底，对齐 048 口径）

    Returns:
        task_id（uuid4 hex 32；同时写入 _task_id_var）
    """
    task_id = uuid.uuid4().hex
    _task_id_var.set(task_id)
    budget_limit = int(settings.task_budget_token_limit or 0)  # module-089
    _budget_limit_var.set(budget_limit)
    if not settings.tasks_enabled:
        return task_id
    _spawn(_SQL_INSERT, {
        "task_id": task_id, "parent_task_id": "", "trace_id": trace_id,
        "endpoint": endpoint, "intent": "", "status": "running",
        "budget_token_limit": budget_limit, "tokens_used": 0,
        "memory_write": "write",
        # JSONB 列经 text() 绑定必须传 JSON 字符串（asyncpg 对 dict 调 .encode()
        # 必炸 DataError 且被 fail-open 吞——Tester 发现-1；与 DDL default 同值）
        "checkpoint": "{}", "identity": identity or "",
    })
    return task_id


def finish_task(task_id: str, intent: str = "", error: bool = False,
                tokens_used: int = 0) -> None:
    """请求收口（UPDATE intent/status/tokens_used/finished_at 一次落定）

    独立于 request_logs_enabled（tasks_enabled 自有开关）；流式请求在流
    finally 调用 → 终态与 request_logs 同快照同口径。

    Args:
        task_id: begin_task 返回值；空串（未建 task 的请求）静默跳过
        intent: 任务意图（空串不覆盖既有值，CASE 兜底）
        error: 请求错误标记（True → status=failed）
        tokens_used: usage 各供应商 prompt+completion 之总和（标量不分桶，
            089 账本若需分桶由其裁定）

    Returns:
        None（fire-and-forget 调度即返回；落库经 _spawn 异步旁路，失败仅 warning）
    """
    if not task_id or not settings.tasks_enabled:
        return
    _spawn(_SQL_FINISH, {
        "task_id": task_id,
        "intent": intent or "",
        "status": "failed" if error else "completed",
        "tokens_used": int(tokens_used or 0),
        "finished_at": datetime.utcnow(),
    })


def set_memory_write_mode(mode: str) -> None:
    """设置当前上下文记忆写所有权（"子只读父写"运行时原语）

    仅接受 read/write；非法值 no-op 保持原值。生产写入方在 T5 子 Agent
    编排（子 task 置 read 经 contextvar 快照继承生效），v1 无调用方。

    Args:
        mode: "write"（父 task，默认）或 "read"（子 task 只读）

    Returns:
        None（无返回值；非法值 no-op 保持原值，可用 memory_write_allowed() 验证）
    """
    if mode in ("read", "write"):
        _memory_write_var.set(mode)


def memory_write_allowed() -> bool:
    """当前上下文是否允许长期记忆写（read 模式拒绝；默认/非法值放行）

    Args:
        无（只读当前上下文 _memory_write_var，不修改任何状态）

    Returns:
        True=允许长期记忆写（默认 write 或未设置）；False=拒绝（read，
        子 task 只读——MemoryService.save 入口闸的消费口径）
    """
    return _memory_write_var.get() != "read"


def get_budget_limit() -> int:
    """当前上下文任务 token 预算上限（module-089）

    Returns:
        预算上限（0=不限；begin_task 压入 config 解析值，set_task_budget 覆盖）
    """
    return _budget_limit_var.get()


def budget_used() -> int:
    """当前请求已用 token 总量（实时口径，与 087 收口逐字同式）

    数据源 observability.get_request_stats()（只读快照，不改写入侧）；Σ 各
    供应商 usage 的 prompt+completion，缺键兜 0，空 usage → 0。边界：logs 关
    时 record_usage 短路 → 恒 0（087 tokens_used 恒 0 同源边界，如实声明）。

    Returns:
        已用 token 标量（不分桶；供应商细分读侧经 request_logs.usage join，085 口径）
    """
    from src import observability

    stats = observability.get_request_stats()
    return sum(int(u.get("prompt", 0)) + int(u.get("completion", 0))
               for u in (stats.get("usage") or {}).values())


def budget_exceeded() -> bool:
    """当前上下文是否已超任务 token 预算（module-089 熔断执法判定）

    语义（plan §1 决策 6 钉死）：limit<=0（不限/未建 task）或 tasks_enabled
    关 → False（零执法）；used >= limit 即 True（到达即熔断，防恰等于上限时
    再烧一轮）。纯 ContextVar + usage 快照，零 DB 访问。

    Returns:
        True=已超预算（两拦截点应拒绝增量成本）；False=未超或预算未启用
    """
    limit = get_budget_limit()
    if limit <= 0 or not settings.tasks_enabled:
        return False
    return budget_used() >= limit


def set_task_budget(limit: int) -> None:
    """覆盖当前上下文任务 token 预算（task 级原语，module-089）

    负数 no-op（对齐 set_memory_write_mode 非法值语义）；正数/0 更新上下文
    var，且 tasks_enabled 且已建 task 时 fire-and-forget UPDATE
    tasks.budget_token_limit（fail-open，审计列可查）。v1 无生产调用方
    （调用方 T5 子任务差异化预算），语义由单测锁定。

    Args:
        limit: 新预算上限（0=不限；负数 no-op）

    Returns:
        None（落库经 _spawn 异步旁路，失败仅 warning）
    """
    if limit < 0:
        return
    _budget_limit_var.set(int(limit))
    if settings.tasks_enabled and _task_id_var.get():
        _spawn(_SQL_BUDGET, {"budget_token_limit": int(limit),
                             "task_id": _task_id_var.get()})


def save_checkpoint(task_id: str, payload: dict) -> None:
    """保存任务检查点（module-090，fire-and-forget 覆盖语义 last-save-wins）

    payload dict → json.dumps(ensure_ascii=False, default=str) JSON 字符串后
    绑定（JSONB 列经 text() 直绑 dict 必炸 DataError 且被 fail-open 吞——087
    真缺陷教训）；UPDATE 无 status 条件（覆盖语义重放安全，对齐 _SQL_BUDGET；
    finish_task 不触碰 checkpoint 列 → 末次保存必存活）。序列化失败 warning
    no-op 不炸调用方（fail-open：检查点保存永不 crash 任务主链路）。

    Args:
        task_id: 任务 ID（begin_task 返回值；空串 no-op）
        payload: 检查点数据（须 dict；非 dict no-op——对齐非法值先例）

    Returns:
        None（落库经 _spawn 异步旁路，失败仅 warning）
    """
    if not task_id or not settings.tasks_enabled \
            or not isinstance(payload, dict):
        return
    try:
        checkpoint = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.warning("checkpoint 序列化失败（fail-open 不炸调用方）: %s",
                       task_id)
        return
    _spawn(_SQL_SAVE_CHECKPOINT,
           {"task_id": task_id, "checkpoint": checkpoint})


async def load_checkpoint(task_id: str) -> dict:
    """读取任务检查点（module-090 读侧原语，无开关闸——对齐 087 读端点先例）

    Args:
        task_id: 任务 ID（空串 → {} 零 DB 访问）

    Returns:
        检查点 dict（行不存在 → {}；asyncpg JSONB 默认解码 dict 直返 / str
        形态 json.loads 兜底 / 非 dict 脏数据防御 → {}）

    Raises:
        Exception: DB 异常原样上抛（对齐 get_task_overview，调用方定降级）
    """
    if not task_id:
        return {}
    from src.database import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(text(_SQL_LOAD_CHECKPOINT),
                                       {"task_id": task_id})
    value = (result.mappings().first() or {}).get("checkpoint")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


async def resume_task(task_id: str) -> bool:
    """恢复任务（module-090：同 task_id 复用置回 running，断点续跑入口）

    白名单语义：failed（失败收口）与悬挂 running（进程死亡遗留行）可恢复；
    completed 终态不可复活（返回 False）。checkpoint/trace_id/intent/
    tokens_used 零触碰（checkpoint 保留为"续跑不从头"数据前提）；幂等：
    悬挂 running 重复恢复状态不变。v1 无生产调用方（T5 长任务编排）。

    Args:
        task_id: 任务 ID（空串 / 开关关 → False 零 DB 访问）

    Returns:
        True=已置回 running 可续跑；False=行不存在 / completed 终态 / 开关关

    Raises:
        Exception: DB 异常原样上抛（对齐 get_task_overview 读侧先例）
    """
    if not task_id or not settings.tasks_enabled:
        return False
    from src.database import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(text(_SQL_RESUME),
                                       {"task_id": task_id})
        await session.commit()
    return bool(result.rowcount)


async def get_task_overview(task_id: str) -> dict | None:
    """读侧单任务概览（单 SQL 标量子查询聚合三表；端点层统一 fail-open）

    Args:
        task_id: 任务 ID（begin_task 返回值）

    Returns:
        task 13 列 dict + obs 子 dict（request_logs/request_spans/tool_calls
        三计数，经 trace_id join）；无数据 → None（端点层转 code 1）

    Raises:
        Exception: DB 异常原样上抛（端点层 except + logger.warning 降级）
    """
    from src.database import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(text(_SQL_OVERVIEW), {"task_id": task_id})
        row = result.mappings().first()
    if row is None:
        return None
    task = dict(row)
    task["obs"] = {k: task.pop(k) for k in
                   ("request_logs", "request_spans", "tool_calls")}
    return task
