"""module-091：langgraph_parity 单测（WP-A 等价逻辑 + AC-6 双 mock 点 + 落库字段）

覆盖（验收 AC-2/3/4/5/6/9 + plan §2）：
- AC-6 双 mock 点：两个 patch 目标字符串逐字断言（hand → agent.react.LLMFactory；
  langgraph → agent.langgraph_react.LLMFactory），且 fixture 运行确实生效（零真实 LLM）
- 等价性 fixture 全量：36 条四维（工具序列/次数/答案/判定器四规则）等价率 = 1.0
- compare_pair 比对逻辑：任一维不一致可检出，diffs 逐条归因（不静默通过）
- equivalence_rate：空集 0.0、部分等价比例正确
- 落库字段：score_run 附 loop/module；build_config_snapshot 注入 {"loop","module"}

实现说明：
- conftest autouse 钉住 tool_call_logs_enabled=false（hermetic，fixture 零 DB）
- real 模式（真实 LLM/DB）不在单测内跑，由真实跑批覆盖（--mode real --sample）
"""
import asyncio
from unittest import mock

import eval.langgraph_parity as m
from eval.agent_tasks import load_agent_tasks

TASKS = load_agent_tasks()


class TestMockTargets:
    """AC-6：双 mock 点字符串断言（不得混用）"""

    def test_hand_patch_target(self):
        """手写侧必须 patch agent.react.LLMFactory.get_client"""
        assert m._LLM_PATCH[m.LOOP_HAND] == "agent.react.LLMFactory.get_client"

    def test_langgraph_patch_target(self):
        """LangGraph 侧必须 patch agent.langgraph_react.LLMFactory.get_client"""
        assert m._LLM_PATCH[m.LOOP_LANGGRAPH] == \
            "agent.langgraph_react.LLMFactory.get_client"

    def test_patch_targets_distinct_strings(self):
        """两个 patch 目标是不同字符串（分模块 import 点各自声明）"""
        assert m._LLM_PATCH[m.LOOP_HAND] != m._LLM_PATCH[m.LOOP_LANGGRAPH]

    def test_loop_fn_mapping(self):
        """环路→函数映射：hand=react_loop / langgraph=langgraph_react_loop"""
        from agent.react import react_loop
        from agent.langgraph_react import langgraph_react_loop
        assert m._LOOP_FN[m.LOOP_HAND] is react_loop
        assert m._LOOP_FN[m.LOOP_LANGGRAPH] is langgraph_react_loop

    def test_patch_actually_swaps_llm(self):
        """patch 生效性：两条环路 fixture 运行时 LLMFactory.get_client 返回假客户端"""
        import importlib
        for loop in (m.LOOP_HAND, m.LOOP_LANGGRAPH):
            client = object()
            with mock.patch(m._LLM_PATCH[loop], return_value=client):
                mod_name, cls_name, attr = m._LLM_PATCH[loop].rsplit(".", 2)
                factory = getattr(importlib.import_module(mod_name), cls_name)
                assert getattr(factory, attr)() is client


class TestEquivalenceFixture:
    """WP-A：fixture 全量等价性（零 LLM，确定性）"""

    def test_full_dataset_equivalent(self):
        """36 条任务四维逐字等价，等价率 = 1.0；不一致条目须为空"""
        pairs = asyncio.run(m.run_equivalence(TASKS))
        assert len(pairs) == len(TASKS)
        diffs = [p for p in pairs if not p["equal"]]
        assert m.equivalence_rate(pairs) == 1.0
        assert diffs == [], f"不一致条目: {[(p['task_id'], p['diffs']) for p in diffs]}"

    def test_pair_dimensions_recorded(self):
        """比对结果记录四维原始值（可对账：序列/次数/答案/判定字段）"""
        pairs = asyncio.run(m.run_equivalence(TASKS[:1]))
        p = pairs[0]
        for side in ("hand", "langgraph"):
            assert set(p[side]) >= {"actual_names", "tool_count", "answer",
                                    "coverage", "no_extra", "args_ok", "pass"}
        assert p["hand"]["actual_names"] == p["langgraph"]["actual_names"]
        assert p["hand"]["tool_count"] == p["langgraph"]["tool_count"]
        assert p["hand"]["answer"] == p["langgraph"]["answer"]


class TestComparePair:
    """compare_pair 比对逻辑（单侧构造成对结果，不跑环路）"""

    @staticmethod
    def _task(name="at-001", **overrides):
        base = {"actual_names": ["search_knowledge"], "tool_count": 1,
                "answer": "G1。", "coverage": True, "no_extra": True,
                "args_ok": True, "pass": True}
        base.update(overrides)
        return base

    def test_equal_when_identical(self):
        """两侧完全一致 → equal=True 且 diffs 为空"""
        item = {"id": "x"}
        p = m.compare_pair(item, self._task(), self._task())
        assert p["equal"] is True and p["diffs"] == []

    def test_detects_each_dimension(self):
        """任一维不一致都可检出且 diffs 含该维描述"""
        item = {"id": "x"}
        cases = [
            ({"actual_names": ["search_fts"]}, "工具序列"),
            ({"tool_count": 2}, "工具次数"),
            ({"answer": "别的"}, "答案"),
            ({"coverage": False}, "coverage"),
            ({"no_extra": False}, "no_extra"),
            ({"args_ok": False}, "args_ok"),
            ({"pass": False}, "pass"),
        ]
        for overrides, label in cases:
            p = m.compare_pair(item, self._task(), self._task(**overrides))
            assert p["equal"] is False, label
            assert any(label in d for d in p["diffs"]), (label, p["diffs"])

    def test_tool_count_follows_sequence_length(self):
        """次数不一致与序列不一致可同时出现在 diffs（逐条归因）"""
        item = {"id": "x"}
        p = m.compare_pair(item, self._task(),
                           self._task(actual_names=["a", "b"], tool_count=2))
        assert p["equal"] is False and len(p["diffs"]) == 2


class TestEquivalenceRate:
    """equivalence_rate 纯函数"""

    def test_empty(self):
        assert m.equivalence_rate([]) == 0.0

    def test_partial(self):
        pairs = [{"equal": True}, {"equal": False}, {"equal": True}]
        assert m.equivalence_rate(pairs) == round(2 / 3, 4)


class TestSaveFields:
    """AC-9：落库 loop 字段（score_run / build_config_snapshot）"""

    def test_score_run_carries_loop_and_module(self):
        per_q = [{"pass": True, "tool_correct": True, "no_extra": True,
                  "args_ok": True, "coverage": True, "grounding": 1.0,
                  "tool_count": 2, "tokens": 100, "duration_ms": 10,
                  "path": "knowledge_single"}]
        scores = m.score_run(m.LOOP_LANGGRAPH, per_q, 1, 1)
        assert scores["loop"] == "langgraph"
        assert scores["module"] == "091"
        assert scores["tokens_total"] == 100

    def test_config_snapshot_injects_loop(self):
        """config_snapshot 注入 loop/module（JSONB 列，零新表零 ALTER）"""
        snap = m.build_config_snapshot({"rag_chunk_size": 500}, m.LOOP_HAND)
        assert snap["loop"] == "hand"
        assert snap["module"] == "091"
        assert snap["rag_chunk_size"] == 500

    def test_config_snapshot_tolerates_none_base(self):
        """base 为 None（load_rag_config 异常兜底）时不炸且仍含 loop 字段"""
        snap = m.build_config_snapshot(None, m.LOOP_LANGGRAPH)
        assert snap["loop"] == "langgraph" and snap["module"] == "091"
