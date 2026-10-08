#!/usr/bin/env python3
"""把 Markdown 笔记批量同步进 RAG 知识库。

用途：把 Obsidian vault（或其他目录）下的 `.md` 笔记灌进 AI 层的文档管线
（解析 → 清洗 → 去重 → 分块 → 嵌入 → 入库），作为「笔记 → 出题 → 面试 → 学习」
闭环的语料入口。

幂等性：走的是 `/ai/rag/documents/upload`，管线内含三级去重（sha256 完全重复
丢弃 / 语义余弦 ≥0.95 标簇抑制），因此**重复执行安全**——已入库的笔记不会被
重复灌入，只会补充新增或改动过的内容。

用法示例：

    # 预演：只列出将要上传的文件，不发请求
    python scripts/sync_notes.py --dry-run \
        --vault llm-push=/path/to/notes/llm-push

    # 实际同步多个 vault（可重复 --vault）
    python scripts/sync_notes.py \
        --vault llm-push=/path/to/notes/llm-push \
        --vault python-push=/path/to/notes/python-push \
        --vault backend-push=/path/to/notes/backend-push

    # 先试一个文件，确认链路
    python scripts/sync_notes.py --vault llm-push=/path/to/notes/llm-push --limit 1

`source` 字段写为 `<label>:<vault 内相对路径>`，用于引用溯源与按 vault 统计。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx

# 不参与同步的目录/文件（编辑器配置、Agent 工作目录、系统垃圾）
SKIP_DIRS = {".obsidian", ".workbuddy", ".trash", ".git", "__pycache__", "node_modules"}
SKIP_FILES = {"Thumbs.db", "desktop.ini", ".DS_Store"}

DEFAULT_API = "http://localhost:8001"
UPLOAD_PATH = "/ai/rag/documents/upload"


def iter_notes(root: Path) -> Iterator[Path]:
    """按稳定顺序产出 vault 下的 .md 文件（跳过隐藏/工具目录）。"""
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in SKIP_FILES:
            continue
        yield path


def parse_vault(spec: str) -> tuple[str, Path]:
    """解析 `LABEL=PATH` 形式的参数；省略 LABEL 时取目录名。"""
    if "=" in spec:
        label, _, raw = spec.partition("=")
        label = label.strip()
        root = Path(raw.strip())
    else:
        root = Path(spec)
        label = root.name
    if not label:
        raise argparse.ArgumentTypeError(f"缺少 label: {spec}")
    if not root.is_dir():
        raise argparse.ArgumentTypeError(f"目录不存在: {root}")
    return label, root


def upload(client: httpx.Client, api: str, path: Path, root: Path, label: str) -> tuple[bool, str]:
    """上传单个笔记，返回 (是否成功, 说明)。"""
    source = f"{label}:{path.relative_to(root).as_posix()}"
    try:
        with path.open("rb") as fh:
            resp = client.post(
                api + UPLOAD_PATH,
                files={"file": (path.name, fh, "text/markdown")},
                data={"title": path.stem, "source": source},
            )
    except httpx.HTTPError as exc:
        return False, f"请求失败: {exc}"

    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:160]}"

    try:
        payload = resp.json()
    except ValueError:
        return False, f"响应非 JSON: {resp.text[:160]}"

    # 管线约定：code == 0 视为成功；其余为业务错误（格式不支持/解析失败等）
    if isinstance(payload, dict) and payload.get("code", 0) != 0:
        return False, str(payload.get("message") or payload)[:200]
    return True, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="把 Markdown 笔记同步进 RAG 知识库")
    parser.add_argument(
        "--vault",
        action="append",
        required=True,
        type=parse_vault,
        metavar="LABEL=PATH",
        help="vault 目录，可重复；省略 LABEL 时用目录名",
    )
    parser.add_argument("--api", default=DEFAULT_API, help=f"AI 服务地址（默认 {DEFAULT_API}）")
    parser.add_argument("--limit", type=int, default=0, help="每个 vault 最多处理多少个文件（0=不限）")
    parser.add_argument("--timeout", type=float, default=600.0, help="单文件上传超时秒数")
    parser.add_argument("--dry-run", action="store_true", help="只列出将要上传的文件")
    args = parser.parse_args()

    jobs: list[tuple[str, Path, Path]] = []
    for label, root in args.vault:
        notes = list(iter_notes(root))
        if args.limit:
            notes = notes[: args.limit]
        jobs.extend((label, root, note) for note in notes)

    total = len(jobs)
    print(f"待处理 {total} 个笔记（{len(args.vault)} 个 vault）", flush=True)

    if args.dry_run:
        for label, root, note in jobs:
            print(f"  {label}:{note.relative_to(root).as_posix()}")
        return 0

    ok = failed = 0
    started = time.time()
    # trust_env=False：目标是本机服务，不应走代理；且 no_proxy 含 IPv6 写法
    # （如 `[::1]`）时 httpx 解析环境代理会抛 InvalidURL，故显式忽略环境代理。
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for index, (label, root, note) in enumerate(jobs, start=1):
            success, detail = upload(client, args.api, note, root, label)
            if success:
                ok += 1
                status = "ok"
            else:
                failed += 1
                status = f"FAIL {detail}"
            elapsed = time.time() - started
            print(f"[{index}/{total}] {label}:{note.name} -> {status} ({elapsed:.0f}s)", flush=True)

    print(f"\n完成：成功 {ok}，失败 {failed}，用时 {time.time() - started:.0f}s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
