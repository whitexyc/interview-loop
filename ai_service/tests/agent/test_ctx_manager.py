"""
上下文工程单测（module-093 / WP-A + WP-B）
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

覆盖：估算器边界（AC-1/AC-3）/ 五桶分类（AC-4/AC-5）/ 观测零行为（AC-6）/
clearing 占位符与保留窗口（AC-7/AC-8）/ compaction 块完整性（AC-10/AC-11）/
compress_view 视图不改原列表（AC-12/AC-13）。全部 hermetic（零 DB 零网络）。
"""
import math

import pytest

from agent.ctx_manager import (
    classify_context,
    clear_tool_results,
    compact_history,
    compress_view,
    estimate_tokens,
    observe_context,
)


# ─────────────────────────── WP-A 估算器 ───────────────────────────


def test_estimate_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_chinese_positive():
    assert estimate_tokens("中文") > 0


def test_estimate_english_positive():
    assert estimate_tokens("hello") > 0


def test_estimate_mixed_positive():
    assert estimate_tokens("中文 english 混合 123") > 0


def test_estimate_monotonic():
    a = estimate_tokens("a")
    b = estimate_tokens("a" * 100)
    c = estimate_tokens("中" * 200)
    assert b >= a and c >= a
    assert estimate_tokens("x" * 1000) >= estimate_tokens("x" * 500)


# ─────────────────────────── WP-A 五桶分类 ───────────────────────────


def _sample_messages():
    return [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": "回答一"},
        {"role": "tool", "tool_call_id": "c1", "content": "工具结果一"},
    ]


def test_classify_five_buckets():
    msgs = _sample_messages()
    buckets = classify_context(msgs, tool_schemas=[{"name": "search_knowledge"}])
    assert buckets["system"]["count"] == 1
    assert buckets["user"]["count"] == 1
    assert buckets["assistant"]["count"] == 1
    assert buckets["tool_results"]["count"] == 1
    assert buckets["tools"]["count"] == 1
    assert buckets["system"]["est_tokens"] == estimate_tokens("你是助手")


def test_classify_tools_from_schemas():
    schemas = [{"a": 1}, {"b": 2}, {"c": 3}]
    buckets = classify_context([], tool_schemas=schemas)
    assert buckets["tools"]["count"] == 3
    assert buckets["tools"]["est_tokens"] == estimate_tokens(
        '[{"a": 1}, {"b": 2}, {"c": 3}]')


def test_observe_no_mutation():
    msgs = _sample_messages()
    snapshot = [dict(m) for m in msgs]
    observe_context(msgs, tool_schemas=[])
    assert msgs == snapshot  # 只读不写


# ─────────────────────────── WP-B clearing ───────────────────────────


def _nested_messages():
    """构造嵌套轮次：system + 两轮（每轮 user→assistant(tool_calls)→tool）"""
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "search_knowledge", "arguments": "{}"}},
            {"id": "c2", "type": "function",
             "function": {"name": "search_fts", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "长结果A" * 50},
        {"role": "tool", "tool_call_id": "c2", "content": "长结果B" * 50},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c3", "type": "function",
             "function": {"name": "search_vector", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c3", "content": "长结果C" * 50},
    ]


def test_clear_placeholder_format_and_name():
    msgs = _nested_messages()
    view, cleared = clear_tool_results(msgs, keep_recent=1)
    # 保留最近 1 条 tool（c3），更早的 c1/c2 被清
    assert cleared == 2
    # 顺序与 role/tool_call_id 不变
    assert [m["role"] for m in view] == [m["role"] for m in msgs]
    assert view[3]["tool_call_id"] == "c1"
    assert view[4]["tool_call_id"] == "c2"
    assert "[tool result cleared:" in view[3]["content"]
    assert "search_knowledge" in view[3]["content"]
    assert "re-invoke the tool to retrieve" in view[3]["content"]
    # 最近一条原文保留
    assert view[7]["content"] == "长结果C" * 50


def test_clear_keep_window_and_no_original_mutation():
    msgs = _nested_messages()
    original = [dict(m) for m in msgs]
    view, cleared = clear_tool_results(msgs, keep_recent=2)
    assert cleared == 1  # 仅 c1 被清（c2/c3 保留）
    assert view[3]["content"] == "[tool result cleared: search_knowledge; re-invoke the tool to retrieve]"
    assert msgs == original  # 入参未被 mutate


def test_clear_all_when_keep_zero():
    msgs = _nested_messages()
    view, cleared = clear_tool_results(msgs, keep_recent=0)
    assert cleared == 3
    assert all("[tool result cleared:" in m["content"] for m in view if m["role"] == "tool")


# ─────────────────────────── WP-B compaction ───────────────────────────


def _no_orphan(view):
    """校验：每个 tool 消息前存在配对 assistant（tool_call_id 命中）"""
    seen_assistant_ids = set()
    for m in view:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                seen_assistant_ids.add(tc.get("id"))
        elif m.get("role") == "tool":
            assert m["tool_call_id"] in seen_assistant_ids, \
                f"孤儿 tool 消息: {m['tool_call_id']}"


def _deep_messages(rounds: int):
    """构造 rounds 轮嵌套（每轮 user→assistant(1 tool_call)→tool）"""
    msgs = [{"role": "system", "content": "s"}]
    for i in range(rounds):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "search_knowledge", "arguments": "{}"}},
        ]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"长结果{i}" * 40})
    return msgs


def test_compact_no_orphan_and_keeps_system_first_user():
    msgs = _deep_messages(4)
    view, folded = compact_history(msgs, keep_recent=2)
    _no_orphan(view)  # AC-10 块完整性
    assert view[0]["role"] == "system"  # AC-11 system 全保留
    # 首条 user 原文保留
    assert any(m["role"] == "user" and m["content"] == "q0" for m in view)
    # 摘要为单条消息
    summaries = [m for m in view if m["content"].startswith("[context summary:")]
    assert len(summaries) == 1
    assert folded >= 1


def test_compact_recent_kept_intact():
    msgs = _nested_messages()
    view, _ = compact_history(msgs, keep_recent=6)
    # 尾部 round（q2/c3）完整保留，未被折叠
    assert any(m["role"] == "user" and m["content"] == "q2" for m in view)
    assert any(m["role"] == "tool" and m["content"] == "长结果C" * 50 for m in view)


def test_compact_deep_no_orphan():
    """构造 6 轮嵌套（每轮多 tool），折叠中部后无孤儿（AC-10）"""
    msgs = [{"role": "system", "content": "s"}]
    for i in range(6):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}a", "type": "function",
             "function": {"name": "search_knowledge", "arguments": "{}"}},
            {"id": f"c{i}b", "type": "function",
             "function": {"name": "search_fts", "arguments": "{}"}},
        ]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}a", "content": f"ra{i}" * 30})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}b", "content": f"rb{i}" * 30})
    view, folded = compact_history(msgs, keep_recent=6)
    _no_orphan(view)
    assert folded >= 1
    # 首轮 user 原文 + 末轮保留
    assert view[1]["content"] == "q0"
    assert any(m["role"] == "user" and m["content"] == "q5" for m in view)


# ─────────────────────────── WP-B compress_view 编排 ───────────────────────────


def _cfg(enabled, threshold=24000, keep_recent=6):
    class C:
        ctx_compress_enabled = enabled
        ctx_token_threshold = threshold
        ctx_keep_recent = keep_recent
    return C()


def test_compress_view_disabled_returns_original_ref():
    msgs = _nested_messages()
    view, meta = compress_view(msgs, [], cfg=_cfg(enabled=False))
    assert view is msgs  # AC-12/AC-13 原引用
    assert meta["triggered"] is False
    assert meta["cleared"] == 0


def test_compress_view_under_threshold_returns_original_ref():
    msgs = _nested_messages()
    view, meta = compress_view(msgs, [], cfg=_cfg(enabled=True, threshold=10 ** 9))
    assert view is msgs
    assert meta["triggered"] is False


def test_compress_view_triggered_clears_and_reports_meta():
    msgs = _nested_messages()
    view, meta = compress_view(msgs, [], cfg=_cfg(enabled=True, threshold=1, keep_recent=1))
    assert view is not msgs  # 返回副本
    assert meta["triggered"] is True
    assert meta["cleared"] >= 1
    assert meta["after_tokens"] <= meta["before_tokens"]


def test_compress_view_default_settings_off():
    """默认 config（ctx_compress_enabled=False）→ 返回原引用，零行为变化"""
    from src.config import settings
    msgs = _nested_messages()
    view, meta = compress_view(msgs, [])
    assert view is msgs
    assert meta["enabled"] is False


def test_compress_view_triggered_no_orphan():
    msgs = [{"role": "system", "content": "s"}]
    for i in range(5):
        msgs.append({"role": "user", "content": f"q{i}"})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "search_knowledge", "arguments": "{}"}},
        ]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"r{i}" * 40})
    view, meta = compress_view(msgs, [], cfg=_cfg(enabled=True, threshold=1, keep_recent=3))
    _no_orphan(view)
    assert meta["triggered"] is True
