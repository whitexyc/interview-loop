"""
上下文工程 — 预算观测 + 历史压缩（module-093）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

两份能力，纯函数/视图模式，零侵入 agent 主链路：

WP-A 预算观测（默认开，零行为变化）：
  - estimate_tokens：启发式 token 估算（ASCII 4 chars/token、CJK ~0.8
    chars/token，按字符类别分段累计向上取整；精确分词不做，误差方向
    宁可高估，用于触发线安全侧，AC-2 与 tiktoken 抽样对齐）。
  - classify_context：五桶（system/tools/user/assistant/tool_results）分类，
    各桶 {count, est_tokens}；tools 桶基于 tool_schemas 序列化估算。
  - observe_context：五桶汇总 + record_span("ctx_budget","observe")（决策级
    日志，复用 module-088 机制，开关关首行短路）。

WP-B 历史压缩（默认关，D5）：
  - clear_tool_results：保留最近 keep_recent 条 tool 消息原文，更早的 content
    替换为占位符（只换 content，role/tool_call_id/顺序逐字不变）。
  - compact_history：clearing 后估算仍超阈 → 折叠中部完整轮次块（user →
    assistant(±tool_calls) → 配对 tools 原子单元）为单条摘要 user 消息（D3），
    保留 system 全部 + 首条 user 原文 + 最近 keep_recent 条；规则式摘要 v1（D6）。
  - compress_view：编排入口；未启用/未超限 → 返回原 list 引用（D1，`is` 断言）；
    超阈 → clear →（仍超）compact → 返回（视图副本，元信息）。

设计红线（plan §1 D1/D3/D5/D6）：压缩是"视图"——传给 chat_with_tools 的是
副本，react_loop/langgraph_react_loop 本地 messages 保持完整（tool_call_id
引用链不被破坏，AC-10 无孤儿 tool 消息由单测锁定）。
"""
import json
import logging
import math
from typing import Optional

from src.config import settings
from src import tracing

logger = logging.getLogger(__name__)

# 估算器系数（启发式，宁可高估，AC-2）：CJK ~0.8 chars/token、其余（ASCII/符号/
# 空白）~4 chars/token。偏离 plan WP-A 建议的 1.5：实测 cl100k_base 对中文约
# 1 token/字，1.5 会低估（触发线偏晚、不安全）；0.8 对抽样 5 条（中英混合）
# 估算值均 ≥ tiktoken 参考值（ratio 1.03–1.26，误差方向安全侧）。三臂比较用
# 同比，相对比值与系数无关，见 ctx-report。
_CJK_CHARS_PER_TOKEN = 0.8
_ASCII_CHARS_PER_TOKEN = 4.0

# clearing 占位符（只换 content 不动结构；{name}=工具名，可 tool_call_logs 回溯）
_CLEARED_MARKER = "[tool result cleared: {name}; re-invoke the tool to retrieve]"

# 摘要截断长度（review-report LOW-3：魔法数字提常量）
_SUMMARY_USER_CHARS = 80
_SUMMARY_ASSISTANT_CHARS = 120

# compaction 规则式摘要前缀
_SUMMARY_PREFIX = "[context summary:"


def _is_cjk(ch: str) -> bool:
    """判断字符是否计入 CJK 估算桶（Unicode 主要表意范围，粗略）

    Args:
        ch: 单字符

    Returns:
        True=CJK（按 0.8 chars/token 估算）；False=其余（按 4 chars/token）
    """
    o = ord(ch)
    return (
        0x3000 <= o <= 0x303F or   # CJK 符号标点
        0x3040 <= o <= 0x30FF or   # 平假名/片假名
        0x3400 <= o <= 0x4DBF or   # CJK 扩展 A
        0x4E00 <= o <= 0x9FFF or   # CJK 统一表意
        0xFF00 <= o <= 0xFFEF      # 全角字符
    )


def estimate_tokens(text: str) -> int:
    """启发式 token 估算（纯函数，无网络/无模型，AC-3）

    按字符类别分段累计：CJK 按 0.8 chars/token、其余按 4 chars/token；分段
    求和后向上取整（宁可高估，安全侧，AC-2 实测 ≥ tiktoken 抽样）。精确分词不做。

    Args:
        text: 待估算文本（None/空 → 0）

    Returns:
        est_tokens（≥0 整数；空串 0、单字符中文/英文均 ≥1，随长度非减，AC-1）
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return math.ceil(cjk / _CJK_CHARS_PER_TOKEN + other / _ASCII_CHARS_PER_TOKEN)


def _content_text(msg: dict) -> str:
    """提取消息文本内容（兼容 str 与 list[content-part] 两种 content 形态）

    Args:
        msg: OpenAI dict 格式消息

    Returns:
        拼接后的文本（无 content → 空串）
    """
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, dict):
                parts.append(p.get("text") or "")
            else:
                parts.append(str(p))
        return "".join(parts)
    return ""


def classify_context(messages: list, tool_schemas: Optional[list] = None) -> dict:
    """五桶分类：system/tools/user/assistant/tool_results（AC-4/AC-5）

    各桶返回 {"count", "est_tokens"}；tools 桶基于 tool_schemas 序列化估算
    （与传入 schemas 一致），无 schemas 时 count=0/est_tokens=0。只读不写。

    Args:
        messages: OpenAI dict 格式消息列表
        tool_schemas: 工具 schema 列表（tools 桶来源）；None 跳过该桶

    Returns:
        {"system"/"tools"/"user"/"assistant"/"tool_results": {"count","est_tokens"}}
    """
    buckets = {name: {"count": 0, "est_tokens": 0}
               for name in ("system", "tools", "user", "assistant", "tool_results")}
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            b = "tool_results"
        elif role in buckets:
            b = role
        else:
            continue
        buckets[b]["count"] += 1
        buckets[b]["est_tokens"] += estimate_tokens(_content_text(msg))
    if tool_schemas:
        buckets["tools"]["count"] = len(tool_schemas)
        buckets["tools"]["est_tokens"] = estimate_tokens(
            json.dumps(tool_schemas, ensure_ascii=False))
    return buckets


def observe_context(messages: list, tool_schemas: Optional[list] = None,
                    where: str = "") -> dict:
    """预算观测：五桶汇总 + record_span("ctx_budget","observe")（AC-6/AC-15）

    只读不写 messages；返回五桶 dict（调用方可进一步聚合）。开关关首行短路
    （record_span 内部），无 trace 上下文跳过落库。

    Args:
        messages: 当前会话消息列表
        tool_schemas: 工具 schema 列表（tools 桶来源）
        where: 观测位置标签（react_loop / langgraph_llm_call）

    Returns:
        五桶 classify_context 结果（含 tools 桶）
    """
    buckets = classify_context(messages, tool_schemas)
    summary = {name: b["est_tokens"] for name, b in buckets.items()}
    summary["total"] = sum(b["est_tokens"] for b in buckets.values())
    summary["where"] = where
    tracing.record_span("ctx_budget", "observe",
                        decision=json.dumps(summary, ensure_ascii=False))
    return buckets


def _tool_name(messages: list, idx: int) -> str:
    """查 tool 消息对应的工具名（依 tool_call_id 回溯 assistant 的 tool_calls）

    Args:
        messages: 完整消息列表
        idx: tool 消息下标

    Returns:
        工具名（回溯失败 → "unknown"）
    """
    tcid = messages[idx].get("tool_call_id")
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            if tc.get("id") == tcid and name:
                return name
    return "unknown"


def clear_tool_results(messages: list, keep_recent: int) -> tuple[list, int]:
    """clearing：保留最近 keep_recent 条 tool 消息原文，更早的 content 换占位符

    只换 content，role/tool_call_id/顺序逐字不变（AC-7）。返回副本，不 mutate
    入参；clear 计数 = 被替换的 tool 消息数。

    Args:
        messages: 完整消息列表
        keep_recent: 保留最近 N 条 tool 消息原文（≤0 全清）

    Returns:
        (新消息列表, 清除条数)
    """
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    clearable = tool_indices[:-keep_recent] if keep_recent > 0 else tool_indices
    cleared = 0
    new_messages = [dict(m) for m in messages]
    for i in clearable:
        name = _tool_name(messages, i)
        new_messages[i] = dict(messages[i])
        new_messages[i]["content"] = _CLEARED_MARKER.format(name=name)
        cleared += 1
    return new_messages, cleared


def _segment_rounds(body: list) -> list:
    """按 user 边界切分 body 为轮次块（user 起新轮，含其 assistant/tool）

    Args:
        body: 非 system 消息列表

    Returns:
        轮次列表，每轮 = [user, ...assistant/tool]（保持原序）
    """
    rounds: list = []
    cur: list = []
    for m in body:
        if m.get("role") == "user" and cur:
            rounds.append(cur)
            cur = [m]
        else:
            cur.append(m)
    if cur:
        rounds.append(cur)
    return rounds


def _summarize_rounds(rounds: list) -> str:
    """规则式摘要：抽取每轮 user 提问 + assistant 回答要点（首句截断，D6）

    Args:
        rounds: 待折叠轮次列表

    Returns:
        单条摘要文本（含 [_SUMMARY_PREFIX 前缀与闭合 ]）
    """
    parts = []
    for r in rounds:
        q, a = "", ""
        for m in r:
            if m.get("role") == "user" and not q:
                q = _content_text(m)[:_SUMMARY_USER_CHARS]
            elif m.get("role") == "assistant" and not a:
                a = _content_text(m)[:_SUMMARY_ASSISTANT_CHARS]
        if q:
            parts.append(f"用户问「{q}」")
        if a:
            parts.append(f"assistant答「{a}」")
    return f"{_SUMMARY_PREFIX} {'；'.join(parts)}]"


def compact_history(messages: list, keep_recent: int) -> tuple[list, int]:
    """compaction：折叠中部完整轮次块为单条摘要 user 消息（D3 原子块）

    保留 system 全部 + 首条 user 原文（含首轮）+ 最近 keep_recent 条（按 round
    snap 到轮边界，避免尾部切断产生孤儿 tool 消息，AC-10）。中部轮次折叠为单条
    摘要 user 消息（AC-11 摘要为单条消息）。返回副本，不 mutate 入参。

    Args:
        messages: 完整消息列表（通常为已 clearing 后的视图）
        keep_recent: 尾部保留最近条数（snap 到 round 边界）

    Returns:
        (新消息列表, 折叠轮次数)；无可折叠 → (原样副本, 0)
    """
    system = [dict(m) for m in messages if m.get("role") == "system"]
    body = [m for m in messages if m.get("role") != "system"]
    rounds = _segment_rounds(body)
    if len(rounds) <= 1:
        return [dict(m) for m in messages], 0
    # 末 keep_recent 条 snap 到 round 边界保留；中部（首轮之后）折叠
    tail_rounds = 0
    tail_msgs = 0
    for r in reversed(rounds[1:]):
        if tail_msgs >= keep_recent:
            break
        tail_rounds += 1
        tail_msgs += len(r)
    middle = rounds[1:len(rounds) - tail_rounds] if tail_rounds else rounds[1:]
    if not middle:
        return [dict(m) for m in messages], 0
    tail = rounds[len(rounds) - tail_rounds:] if tail_rounds else []
    summary = {"role": "user", "content": _summarize_rounds(middle)}
    new_messages = (system + list(rounds[0]) + [summary]
                    + [m for r in tail for m in r])
    return new_messages, len(middle)


def compress_view(messages: list, tool_schemas: Optional[list] = None,
                  cfg=None, compact: bool = True) -> tuple[list, dict]:
    """压缩编排入口：估算 → 超阈则先 clear 再 compact → 返回（视图，元信息）

    未启用或未超限 → 返回（原 list 引用，零动作元信息），调用方 `is` 断言成立
    （D1/AC-12）。启用且超阈 → 副本上 clear →（仍超阈且 compact=True）compact
    → 返回视图副本 + 元信息 {cleared, compacted, before_tokens, after_tokens,
    triggered}。

    `compact` 仅用于 eval 三臂对拍（clearing-only 臂传 False）；生产接线默认
    True，单一接线点（D4 公平），不引入新配置项（红线 config 三字段）。

    Args:
        messages: 完整消息列表（本地，保持完整）
        tool_schemas: 工具 schema 列表（tools 桶 + 触发估算来源）
        cfg: 配置源（默认 settings）；可读 ctx_compress_enabled/ctx_token_threshold
            /ctx_keep_recent
        compact: 是否允许 compaction（clearing-only 臂 False；默认 True）

    Returns:
        (视图 messages, 元信息 dict)
    """
    cfg = cfg or settings
    enabled = getattr(cfg, "ctx_compress_enabled", False)
    threshold = getattr(cfg, "ctx_token_threshold", 24000)
    keep_recent = getattr(cfg, "ctx_keep_recent", 6)
    meta = {"cleared": 0, "compacted": 0, "before_tokens": 0,
            "after_tokens": 0, "enabled": enabled, "triggered": False}
    meta["before_tokens"] = sum(
        b["est_tokens"] for b in classify_context(messages, tool_schemas).values())
    if not enabled or meta["before_tokens"] <= threshold:
        return messages, meta   # 原引用，零行为变化
    view, cleared = clear_tool_results(messages, keep_recent)
    meta["cleared"] = cleared
    if compact and sum(
            b["est_tokens"] for b in classify_context(view, tool_schemas).values()
    ) > threshold:
        view, compacted = compact_history(view, keep_recent)
        meta["compacted"] = compacted
    meta["after_tokens"] = sum(
        b["est_tokens"] for b in classify_context(view, tool_schemas).values())
    meta["triggered"] = True
    return view, meta
