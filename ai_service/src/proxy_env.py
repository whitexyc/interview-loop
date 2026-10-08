"""环境代理变量兜底：剔除 httpx 无法解析的 no_proxy 条目。

## 为什么需要

httpx 在构造客户端时会把 `no_proxy` 的每一项当作 URL 模式解析。Windows 上常见的
写法会包含 IPv6 方括号形式：

    no_proxy=localhost,127.0.0.1,::1,[::1]

其中 `[::1]` 会让 httpx 抛：

    httpx.InvalidURL: Invalid port: ':1]'

**表现极具误导性**：所有出站 HTTP 调用（LLM 供应商、爬取、内部服务调用）直接失败，
但错误信息里完全看不出与代理有关。在本项目里，它表现为「检索正常、回答生成失败」，
前端只显示一句笼统的兜底文案 —— 排查时极易误判为代码 bug。

## 做法

只动 `no_proxy` / `NO_PROXY`：移除含方括号或 `::` 的条目，保留 `localhost`、
`127.0.0.1` 等常规项。这样既消除崩溃，又不牺牲代理能力（本机流量仍然直连）。

在 `src/__init__.py` 中调用，确保早于任何 httpx 客户端构造。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_ENV_NAMES = ("no_proxy", "NO_PROXY")


def _is_unparseable(entry: str) -> bool:
    """httpx 解析不了的条目：IPv6 方括号写法，以及裸 `::` 形式。"""
    return "[" in entry or "]" in entry or "::" in entry


def sanitize_no_proxy() -> list[str]:
    """就地清理 no_proxy/NO_PROXY，返回被移除的条目（便于自检脚本复用）。"""
    removed: list[str] = []
    for name in _ENV_NAMES:
        raw = os.environ.get(name)
        if not raw:
            continue
        entries = [e.strip() for e in raw.split(",") if e.strip()]
        kept = [e for e in entries if not _is_unparseable(e)]
        dropped = [e for e in entries if _is_unparseable(e)]
        if dropped:
            os.environ[name] = ",".join(kept)
            removed.extend(dropped)
    if removed:
        logger.warning(
            "已从 no_proxy 移除 httpx 无法解析的条目 %s —— 不移除会导致所有出站 HTTP "
            "调用抛 InvalidURL（表现为 LLM 调用失败）", removed)
    return removed
