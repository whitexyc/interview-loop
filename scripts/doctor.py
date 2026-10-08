#!/usr/bin/env python3
"""环境自检：把部署这条路上最容易踩的坑一次性查出来。

这些检查项来自真实的排障记录——每一条都曾经让人以为「代码坏了」，
实际只是环境没对齐：

  1. Redis 密码不一致   → 后端发 AUTH 被拒，表现为连不上缓存
  2. JWT 密钥不一致     → 不报错，静默把所有请求按匿名（client_ip）处理
  3. 本机绝对路径残留   → 入库脚本指向别人的目录，导入 0 篇却不报错
  4. no_proxy 含 [::1]  → httpx 解析环境代理时抛 InvalidURL，同步脚本直接崩
  5. 端口被占           → 服务起不来，日志里只有一行 addrinfo 错误
  6. 模型权重缺失       → 重排模型按设计**明确报错**（不静默降级）
  7. AGE 扩展缺失       → 图谱通道静默为空，检索结果少一路

用法：
    python scripts/doctor.py                 # 全量自检
    python scripts/doctor.py --no-docker     # 跳过 Docker 相关检查
    python scripts/doctor.py --api http://localhost:8001
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
AI_DIR = ROOT / "ai_service"

# Windows 控制台默认 GBK，直接打印 ✓/✗ 会抛 UnicodeEncodeError；
# 显式切到 UTF-8（errors=replace 兜底，避免自检脚本自己先崩）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

OK, WARN, FAIL = "  ✓", "  !", "  ✗"
_results: list[tuple[str, str, str]] = []


def record(level: str, title: str, detail: str = "", fix: str = "") -> None:
    _results.append((level, title, detail))
    line = f"{level} {title}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    if fix and level is not FAIL:
        print(f"      ↳ {fix}", flush=True)
    elif fix:
        print(f"      修复：{fix}", flush=True)


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """执行外部命令，返回 (returncode, 合并输出)。缺失命令时返回 (-1, 原因)。"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return -1, f"命令不存在: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -1, f"命令超时: {' '.join(cmd)}"


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    """探测端口是否有服务在听。

    同时尝试 IPv4/IPv6：Vite dev server 在 Windows 上常只监听 IPv6（::1），
    只探 127.0.0.1 会误报「未监听」。
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for family, socktype, proto, _, addr in infos:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                if sock.connect_ex(addr) == 0:
                    return True
        except OSError:
            continue
    return False


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001 —— 自检脚本，任何异常都只作诊断信息
        return 0, str(exc)


# ---------------------------------------------------------------- 各项检查

def check_python() -> None:
    ver = sys.version_info
    if ver >= (3, 11):
        record(OK, f"Python {ver.major}.{ver.minor}.{ver.micro}")
    else:
        record(FAIL, f"Python {ver.major}.{ver.minor} 版本过低", fix="需要 3.11+")


def check_env_file() -> None:
    env_path = AI_DIR / ".env"
    if not env_path.is_file():
        record(FAIL, "ai_service/.env 不存在",
               fix="cp ai_service/.env.example ai_service/.env 后填入 LLM API Key")
        return
    record(OK, "ai_service/.env 存在")
    text = env_path.read_text(encoding="utf-8", errors="replace")

    secret = ""
    m = re.search(r"^PW_JWT_SECRET\s*=\s*(.+)$", text, re.MULTILINE)
    if m:
        secret = m.group(1).strip()

    app_yml = ROOT / "backend" / "src" / "main" / "resources" / "application.yml"
    java_secret = ""
    if app_yml.is_file():
        ym = re.search(r"secret:\s*\$\{APP_JWT_SECRET:([^}]*)\}", app_yml.read_text(encoding="utf-8"))
        if ym:
            java_secret = ym.group(1).strip()

    if not secret:
        record(FAIL, "PW_JWT_SECRET 未配置", fix="AI 层会拒绝启动（fail-fast）")
    elif len(secret.encode("utf-8")) < 32:
        record(FAIL, f"PW_JWT_SECRET 只有 {len(secret.encode('utf-8'))} 字节",
               fix="HS256 要求 ≥32 字节，否则签发/验签会失败")
    elif java_secret and secret != java_secret:
        record(FAIL, "PW_JWT_SECRET 与 Java 侧 jwt.secret 不一致",
               detail="不会报错，但登录后所有 /ai 请求会被当作匿名（按 client_ip 隔离长期记忆）",
               fix="让两处取同一个值（或都用 APP_JWT_SECRET 环境变量注入）")
    else:
        record(OK, "JWT 密钥长度与两侧一致性")


def check_proxy_env() -> None:
    """httpx 解析 no_proxy 时遇到 [::1] 这类写法会抛 InvalidURL。"""
    for name in ("no_proxy", "NO_PROXY"):
        raw = os.environ.get(name, "")
        if "[::1]" in raw or "[::" in raw:
            record(WARN, f"{name} 含 IPv6 方括号写法（{raw}）",
                   detail="httpx 解析环境代理时会抛 InvalidURL，同步脚本等会直接崩溃",
                   fix="去掉 [::1]，或调用 httpx 时传 trust_env=False")
            return
    record(OK, "环境代理变量格式")


def check_models() -> None:
    models = AI_DIR / "models"
    required = [
        ("bge-m3 GGUF（嵌入，必需）", models / "bge-m3-gguf" / "bge-m3-q8_0.gguf"),
        ("bge-reranker-v2-m3（重排，必需）", models / "bge-reranker-v2-m3" / "model.safetensors"),
        ("HHEM-2.1-Open（幻觉裁判，缺失可降级）", models / "hhem-2.1-open"),
    ]
    for label, path in required:
        if path.is_dir():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            record(OK if size > 0 else FAIL, label, f"{size / 1e6:.0f} MB")
        elif path.is_file():
            record(OK if path.stat().st_size > 0 else FAIL, label,
                   f"{path.stat().st_size / 1e6:.0f} MB")
        else:
            # 重排模型缺失是硬失败；HHEM 缺失只降级
            hard = "reranker" in str(path) or "gguf" in str(path)
            record(FAIL if hard else WARN, label, "缺失",
                   fix="见 README「下载本地模型」；国内建议 HF_ENDPOINT=https://hf-mirror.com")


def check_ports() -> None:
    for label, port in (("PostgreSQL", 5432), ("Redis", 6379),
                        ("AI 层", 8001), ("Java 后端", 8081), ("前端", 3001)):
        if port_open("127.0.0.1", port):
            record(OK, f"{label} 端口 {port} 已监听")
        else:
            # 应用服务没起不算错误（自检可能在启动前跑）
            level = WARN if port in (8001, 8081, 3001) else FAIL
            hint = "docker compose up -d" if port in (5432, 6379) else "尚未启动该服务"
            record(level, f"{label} 端口 {port} 未监听", fix=hint)


def check_docker(api: str) -> None:
    rc, out = run(["docker", "version", "--format", "{{.Server.Version}}"])
    if rc != 0:
        record(FAIL, "Docker daemon 不可用", detail=out.strip()[:120],
               fix="启动 Docker Desktop 后重试")
        return
    record(OK, f"Docker daemon 可用（{out.strip()}）")

    rc, out = run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"])
    if rc != 0:
        record(WARN, "无法列出容器", detail=out.strip()[:120])
        return
    names = [ln.split("\t")[0] for ln in out.strip().splitlines() if ln.strip()]
    record(OK if names else WARN, "运行中的容器", ", ".join(names) if names else "无（先 docker compose up -d）")

    # PostgreSQL 扩展与图谱
    pg = next((n for n in names if "postgres" in n.lower()), None)
    if not pg:
        record(WARN, "未发现 Postgres 容器，跳过扩展检查")
        return
    db = os.environ.get("PW_DB_NAME", "personal_website")
    rc, out = run(["docker", "exec", pg, "psql", "-U", "postgres", "-d", db, "-t", "-A", "-c",
                   "SELECT extname FROM pg_extension WHERE extname IN ('vector','age');"])
    exts = {ln.strip() for ln in out.splitlines() if ln.strip()}
    if {"vector", "age"} <= exts:
        record(OK, "pgvector + Apache AGE 扩展就位")
    else:
        missing = {"vector", "age"} - exts
        record(FAIL, f"数据库缺少扩展: {', '.join(sorted(missing))}",
               fix="docker compose down -v && docker compose up -d（initdb 只在空卷时执行）")

    if "age" in exts:
        rc, out = run(["docker", "exec", pg, "psql", "-U", "postgres", "-d", db, "-t", "-A", "-c",
                       "SELECT name FROM ag_catalog.ag_graph;"])
        graph = out.strip()
        record(OK if graph else WARN, "AGE 图谱", graph or "未创建（图谱通道会为空）",
               fix="" if graph else "跑一次入库或 backfill_graph.py 后会创建")

    rc, out = run(["docker", "exec", pg, "psql", "-U", "postgres", "-d", db, "-t", "-A", "-c",
                   "SELECT count(*) FROM documents;"])
    if rc == 0 and out.strip().isdigit():
        count = int(out.strip())
        record(OK if count else WARN, "已入库文档块", str(count),
               fix="" if count else "用 scripts/sync_notes.py 把笔记灌进来")

    # Redis 密码
    redis = next((n for n in names if "redis" in n.lower()), None)
    if not redis:
        record(WARN, "未发现 Redis 容器，跳过鉴权检查")
        return
    env_path = AI_DIR / ".env"
    password = ""
    if env_path.is_file():
        m = re.search(r"^PW_REDIS_URL\s*=\s*redis://(?::([^@]*)@)?", 
                      env_path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if m:
            password = m.group(1) or ""
    rc_auth, out_auth = run(["docker", "exec", redis, "redis-cli"] +
                            (["-a", password] if password else []) + ["ping"])
    rc_anon, out_anon = run(["docker", "exec", redis, "redis-cli", "ping"])
    if "PONG" in out_auth:
        record(OK, f"Redis 鉴权通过（{'带密码' if password else '无密码'}）")
    else:
        record(FAIL, "Redis 鉴权失败", detail=out_auth.strip()[:100],
               fix="确认容器 requirepass 与 PW_REDIS_URL / spring.data.redis.password 一致")
    if password and "PONG" in out_anon:
        record(WARN, "Redis 无密码也能连上", fix="与后端默认密码不一致，建议给 Redis 设 requirepass")


def check_services(api: str) -> None:
    status, body = http_get(api.rstrip("/") + "/ai/health")
    if status == 200:
        record(OK, f"AI 层健康检查（{status}）", body[:80])
    else:
        record(WARN, "AI 层健康检查失败", detail=body[:120],
               fix="cd ai_service && python -m uvicorn main:app --port 8001")

    status, body = http_get("http://localhost:8081/api/v1/health")
    record(OK if status == 200 else WARN, "Java 后端健康检查",
           f"{status}" if status else body[:100],
           fix="" if status == 200 else "cd backend && mvn spring-boot:run")

    status, _ = http_get("http://localhost:3001/")
    record(OK if status == 200 else WARN, "前端", f"{status}" if status else "未启动",
           fix="" if status == 200 else "cd frontend && npm run dev")


def main() -> int:
    parser = argparse.ArgumentParser(description="interview-loop 环境自检")
    parser.add_argument("--api", default="http://localhost:8001", help="AI 服务地址")
    parser.add_argument("--no-docker", action="store_true", help="跳过 Docker 相关检查")
    args = parser.parse_args()

    print("\ninterview-loop 环境自检\n" + "─" * 46, flush=True)
    check_python()
    check_env_file()
    check_proxy_env()
    check_models()
    check_ports()
    if not args.no_docker:
        check_docker(args.api)
    check_services(args.api)

    fails = sum(1 for lvl, _, _ in _results if lvl is FAIL)
    warns = sum(1 for lvl, _, _ in _results if lvl is WARN)
    print("─" * 46)
    print(f"结果：{len(_results)} 项检查，{fails} 项失败，{warns} 项警告\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
