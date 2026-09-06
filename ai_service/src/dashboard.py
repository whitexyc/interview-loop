"""可观测看板读侧聚合（module-085）：成功率 / 延迟 P50+P95 / token 成本 / 工具调用
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

写侧在 src/observability.py（module-058，零改动）；本模块只读聚合
request_logs / tool_call_logs 两表（零新表，4 条独立参数化 SQL 单 session
顺序执行，对齐 module-072 resolve_tool_history / module-081 SAG 先例）。

4 指标口径（plan §1 决策 2 钉死，Tester 对账 SQL 同法复现即一致）：
  1. 成功率 = error=false 行占比（round 4 位；空窗口 None 不伪造 0/1），
     按 endpoint 分组（总体行由纯函数对分组求和，不二次查询）。
  2. 延迟 = SUM(timings 各阶段毫秒) 为每请求总延迟（表无总延迟列），
     PG percentile_cont(ARRAY[0.5, 0.95]) 连续插值法；空 timings 行排除出
     分布（WHERE total_ms IS NOT NULL）但计入请求数/成功率（两口径独立）。
  3. 成本 = usage JSONB 按供应商 token 分桶（历史桶 'llm' 原样保留不合并），
     不引入价格配置（金额换算留 module-089 预算账本定口径）。
  4. 工具 = tool_call_logs 按 tool_name 分组 calls + failures(result_ok=false)
     + duration_p95_ms（兑现 module-083 WP-C "看板拉 P95" 预留）。
"""
from datetime import datetime, timedelta

from sqlalchemy import text

from src.database import async_session_factory

# 窗口内请求按 endpoint 分组（error=true 行计入分母）
_SQL_REQUESTS = """
    SELECT endpoint,
           COUNT(*) AS total,
           SUM(CASE WHEN error THEN 1 ELSE 0 END) AS errors
    FROM request_logs
    WHERE created_at >= :since
    GROUP BY endpoint
    ORDER BY total DESC
"""

# 每请求总延迟 = timings 各阶段毫秒求和（jsonb_each_text 值为 text 须 ::float8）；
# 一条 SQL 同时取 P50/P95 数组 + 样本数（样本 = 非空 timings 行数）
_SQL_LATENCY = """
    SELECT percentile_cont(ARRAY[0.5, 0.95]) WITHIN GROUP (ORDER BY total_ms) AS p,
           COUNT(*) AS samples
    FROM (
        SELECT (SELECT SUM((v)::float8) FROM jsonb_each_text(timings) AS e(k, v)) AS total_ms
        FROM request_logs
        WHERE created_at >= :since
    ) sub
    WHERE total_ms IS NOT NULL
"""

# usage 按供应商分桶；::bigint 防 int4 溢出，COALESCE 防单桶缺 prompt/completion
# 键时 SUM 全 NULL（AC-23 防御，Developer 裁定 COALESCE 兜 0 而非如实 NULL）
_SQL_COST = """
    SELECT k AS provider,
           COALESCE(SUM((v->>'prompt')::bigint), 0) AS prompt_tokens,
           COALESCE(SUM((v->>'completion')::bigint), 0) AS completion_tokens
    FROM request_logs, jsonb_each(usage) AS e(k, v)
    WHERE created_at >= :since
    GROUP BY k
    ORDER BY prompt_tokens DESC
"""

# 工具按自身 created_at 过滤（表无 endpoint 列，不 JOIN）；探针行如实进统计
_SQL_TOOLS = """
    SELECT tool_name,
           COUNT(*) AS calls,
           SUM(CASE WHEN result_ok THEN 0 ELSE 1 END) AS failures,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS duration_p95_ms
    FROM tool_call_logs
    WHERE created_at >= :since
    GROUP BY tool_name
    ORDER BY calls DESC
"""


def _rows_to_requests(rows) -> dict:
    """分组行 → {total, errors, success_rate, by_endpoint}；total=0 → success_rate None"""
    by_endpoint = [{"endpoint": r[0], "total": r[1], "errors": r[2]} for r in rows]
    total = sum(r[1] for r in rows)
    errors = sum(r[2] for r in rows)
    rate = round((total - errors) / total, 4) if total else None
    return {"total": total, "errors": errors, "success_rate": rate,
            "by_endpoint": by_endpoint}


def _rows_to_latency(row) -> dict | None:
    """percentile_cont 数组行 → {p50_ms, p95_ms, samples}；无行/全 NULL → None"""
    if row is None or row[0] is None:
        return None
    return {"p50_ms": float(row[0][0]), "p95_ms": float(row[0][1]),
            "samples": int(row[1])}


def _rows_to_cost(rows) -> dict:
    """分桶行 → {total_prompt, total_completion, by_provider}（total 为各桶求和）"""
    by_provider = [{"provider": r[0], "prompt_tokens": int(r[1] or 0),
                    "completion_tokens": int(r[2] or 0)} for r in rows]
    return {"total_prompt": sum(p["prompt_tokens"] for p in by_provider),
            "total_completion": sum(p["completion_tokens"] for p in by_provider),
            "by_provider": by_provider}


def _rows_to_tools(rows) -> dict:
    """分组行 → {total, by_tool}（total 为各工具 calls 求和）"""
    by_tool = [{"tool_name": r[0], "calls": r[1], "failures": r[2],
                "duration_p95_ms": r[3]} for r in rows]
    return {"total": sum(t["calls"] for t in by_tool), "by_tool": by_tool}


async def get_dashboard_metrics(hours: int) -> dict:
    """看板 4 指标聚合（读侧端点唯一入口；异常向上抛由端点层统一 fail-open）

    Args:
        hours: 统计窗口小时数（0=全部数据；1-8760 由端点层校验）

    Returns:
        {window, requests, latency, cost, tools}（字段名即 plan §8 前后端契约，
        window 含 hours / since ISO 串 / generated_at ISO 串）
    """
    since = (datetime(1970, 1, 1) if hours == 0
             else datetime.utcnow() - timedelta(hours=hours))
    async with async_session_factory() as session:
        req_rows = (await session.execute(
            text(_SQL_REQUESTS), {"since": since})).fetchall()
        lat_row = (await session.execute(
            text(_SQL_LATENCY), {"since": since})).first()
        cost_rows = (await session.execute(
            text(_SQL_COST), {"since": since})).fetchall()
        tool_rows = (await session.execute(
            text(_SQL_TOOLS), {"since": since})).fetchall()
    return {
        "window": {"hours": hours, "since": since.isoformat(),
                   "generated_at": datetime.utcnow().isoformat()},
        "requests": _rows_to_requests(req_rows),
        "latency": _rows_to_latency(lat_row),
        "cost": _rows_to_cost(cost_rows),
        "tools": _rows_to_tools(tool_rows),
    }
