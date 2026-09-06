"""临时探针：module-084 client 接入真实官方 filesystem MCP server（演示用，非模块产物）

流程：init_ext 发现注册 → 治理属性断言 → 白名单矩阵 → 未授权拒绝 →
未审批拦截（真实 PG approval_requests 落 pending）→ 真实批准（UPDATE DB）
→ 真实执行（list_directory / read_text_file 真实读写演示目录）。
用后清理：approval_requests 中本探针产生的行由外部清理，探针自身不删表。
"""
import asyncio
import os

from sqlalchemy import text

from src.config import settings
from src.database import async_session_factory
from agent.mcp_client import external
from agent.react import ReactContext, execute_tool_with_log
from agent.tool_registry import ToolRegistry, register_builtin_tools

FS_INDEX = r"<home>\node_modules\@modelcontextprotocol\server-filesystem\dist\index.js"
DEMO = os.path.join(os.environ["TEMP"], "mcp-real-demo")


async def main():
    settings.mcp_external_enabled = True
    settings.mcp_external_command = ["node", FS_INDEX, DEMO]
    settings.mcp_external_tools = ["list_directory", "read_text_file"]

    reg = ToolRegistry()
    register_builtin_tools(reg)
    n = await external.init_ext(reg)
    print(f"[1] 真实 server 发现并注册 {n} 个外部工具: {sorted(external.registered)}")

    t = reg.get("list_directory")
    print(f"[2] 治理属性: approval={t.approval} no_retry={t.no_retry} "
          f"timeout={t.timeout}s group={t.group or '未分组(全阶段可见)'}")

    allowed = external.agent_allowed_tools()
    granted = allowed & external.registered
    print(f"[3] 白名单矩阵: 可执行 {len(allowed)} 个（内置 10 + 授权外部 "
          f"{len(granted)} {sorted(granted)}），未授权外部 "
          f"{len(external.registered - allowed)} 个被拒")

    ctx = ReactContext("demo", "probe")
    denied = await execute_tool_with_log("write_file", {"path": "x", "content": "y"},
                                         reg.get("write_file"), ctx,
                                         allowed_tools=allowed)
    print(f"[4] 未授权 write_file（未列入白名单）执行层拒绝: {denied.strip()[:45]}")

    blocked = await t.run({"path": DEMO}, ctx)
    print(f"[5] 已授权未审批调用拦截: {blocked}")

    async with async_session_factory() as s:
        rows = (await s.execute(text(
            "SELECT id, tool_name, status, requester FROM approval_requests "
            "WHERE tool_name='list_directory' AND status='pending'"))).fetchall()
    print(f"[6] 真实 approval_requests 表 pending 行: {rows}")

    async with async_session_factory() as s:
        await s.execute(text(
            "UPDATE approval_requests SET status='approved', decided_at=now() "
            "WHERE tool_name='list_directory' AND status='pending'"))
        await s.commit()
    result = await t.run({"path": DEMO}, ctx)
    print(f"[7] 批准后真实执行 list_directory: {result[:60]}")

    t2 = reg.get("read_text_file")
    content = await t2.run({"path": os.path.join(DEMO, "sample.txt")}, ctx)
    if "需人工审批" in content:
        print("[8] read_text_file 首调同样被审批闸拦截（符合预期）")
        async with async_session_factory() as s:
            await s.execute(text(
                "INSERT INTO approval_requests (tool_name, args, status, requester, decided_at) "
                "VALUES ('read_text_file', '{}', 'approved', 'probe', now())"))
            await s.commit()
        content = await t2.run({"path": os.path.join(DEMO, "sample.txt")}, ctx)
    print(f"[9] read_text_file 真实读取 sample.txt: {content[:70]}")

    await external.close()
    print("[10] 外部会话已关闭（幂等）")


asyncio.run(main())
