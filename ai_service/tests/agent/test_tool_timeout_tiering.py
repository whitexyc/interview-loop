"""工具超时分档（2026-09-11）单测

验证 register 在 settings.tool_timeout_tiering 开关下的分档行为：
- 默认关 → 全部 15s（存量行为逐字不变）
- 开启 → 分档表命中工具放宽（40/40/30），未命中保持默认
- 显式传 timeout 优先级最高（不受分档覆盖）
"""

import unittest
from unittest import mock

from agent.tool_registry import ToolRegistry, _TOOL_TIMEOUT_TIERS
from src.config import settings


def _noop(ctx, args):
    return "ok"


class TestToolTimeoutTiering(unittest.TestCase):

    def test_default_off_keeps_15s(self):
        """默认关：分档表命中的工具也是 15s（存量行为零变化）"""
        reg = ToolRegistry()
        with mock.patch.object(settings, "tool_timeout_tiering", False):
            reg.register("generate_answer", "d", {}, _noop)
        assert reg.get("generate_answer").timeout == settings.tool_default_timeout

    def test_on_applies_tier(self):
        """开启：分档表命中工具按表放宽（40/40/30）"""
        reg = ToolRegistry()
        with mock.patch.object(settings, "tool_timeout_tiering", True):
            for name in _TOOL_TIMEOUT_TIERS:
                reg.register(name, "d", {}, _noop)
        for name, tier in _TOOL_TIMEOUT_TIERS.items():
            assert reg.get(name).timeout == tier

    def test_on_unlisted_tool_stays_default(self):
        """开启：未命中分档表的工具保持默认 15s"""
        reg = ToolRegistry()
        with mock.patch.object(settings, "tool_timeout_tiering", True):
            reg.register("search_knowledge", "d", {}, _noop)
        assert reg.get("search_knowledge").timeout == settings.tool_default_timeout

    def test_explicit_timeout_wins_over_tier(self):
        """显式传 timeout 优先级最高（不受分档覆盖）"""
        reg = ToolRegistry()
        with mock.patch.object(settings, "tool_timeout_tiering", True):
            reg.register("generate_answer", "d", {}, _noop, timeout=5.0)
        assert reg.get("generate_answer").timeout == 5.0

    def test_tier_table_values(self):
        """分档表取值与 092 遥测依据一致（生成/验证 40s，改写重检 30s）"""
        assert _TOOL_TIMEOUT_TIERS == {
            "generate_answer": 40.0,
            "verify_answer": 40.0,
            "re_search": 30.0,
        }


if __name__ == "__main__":
    unittest.main()
