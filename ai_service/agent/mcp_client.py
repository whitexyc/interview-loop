"""
外部 MCP 客户端接入（module-084）— 服务作为 MCP client 连接外部 server
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

方向说明：module-067（ADR-0018）是把自家只读工具经 FastMCP 暴露给外部
（入向 server）；本模块相反（出向 client）——启动时经 stdio 连接 1 个外部
MCP server 子进程，发现（list_tools）后注册进 ToolRegistry，让 Agent 可
调用外部工具。外部工具自动受 module-083 治理约束：

  - 审批：全部硬编码 approval="required"（外部工具可能有副作用，宁可多审
    不少审；审批工作流复用 083 approval_requests 表 + /ai/tools/approvals）
  - 白名单：agent_allowed_tools() 显式授权语义矩阵（两端点透传 allowed_tools）
  - schema：MCP inputSchema 即 JSON Schema，083 jsonschema 校验天然复用
  - 超时：AgentTool.timeout（默认 settings.tool_default_timeout=15.0）围栏继承
  - 幂等：外部工具不在 _IDEMPOTENT_TOOLS → 不拦截（治理 = 审批 + 白名单）
  - 重试：no_retry=True（副作用不可自动重放，073 自动重试逐工具排除）

fail-open 契约：enabled=false / command 空 / spawn 失败 / 握手超时 →
warning + 跳过注册，服务照常启动，内置 10 工具零影响。连接中断不做自动
重连（v1 明确不做，重启服务恢复）；Streamable HTTP client 不做（plan §12）。

mcp 1.26.0 实测（勿照抄旧文档）：
  - stdio_client(StdioServerParameters) → (read, write) 元组异步上下文
  - ClientSession(read, write) 异步上下文 → await initialize() 握手
  - list_tools() → ListToolsResult.tools（Tool.name/description/inputSchema）
  - call_tool(name, arguments=args) → CallToolResult(content/structuredContent/isError)
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from src.config import settings

logger = logging.getLogger(__name__)

# 子进程工作目录：ai_service 根（样例 server 相对路径 / 生产相对命令的解析基准）
_AI_SERVICE_DIR = str(Path(__file__).resolve().parent.parent)

# 外部工具结果截断（对齐 module-067 _TRUNCATE_LIMIT，防大 payload 撑爆 LLM 上下文）
_TRUNCATE_LIMIT = 2000
_TRUNCATE_SUFFIX = "…（外部工具结果已截断）"


def _truncate(text: str) -> str:
    """超长截断（未超限原样返回）"""
    if not text or len(text) <= _TRUNCATE_LIMIT:
        return text
    return text[:_TRUNCATE_LIMIT] + _TRUNCATE_SUFFIX


def _extract_text(result) -> str:
    """从 CallToolResult.content 提取文本块拼接（非 TextContent 块跳过）"""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


class ExternalMCPClient:
    """外部 MCP server 连接与工具注册（模块级单例 external）

    状态所有权：stdio / session 两个异步上下文句柄 + 已注册外部工具名集合。
    init_ext 由 lifespan startup 调用一次，close 由 shutdown 调用（幂等）。
    """

    def __init__(self) -> None:
        self._stdio_cm = None    # stdio_client 异步上下文（保持子进程存活）
        self._session_cm = None  # ClientSession 异步上下文
        self.session = None      # 已握手 ClientSession（_ext_call 使用）
        # 已注册外部工具名集合（冲突检测 / 白名单交集 / allowed_tools 组装）
        self.registered: set[str] = set()
        self._registry = None    # init_ext 传入的注册表（agent_allowed_tools 用）

    async def init_ext(self, reg) -> int:
        """连接外部 server → 发现工具 → 注册进 ToolRegistry（fail-open）

        门控：mcp_external_enabled=false 或 command 为空 → 返回 0 零开销
        （不 spawn 子进程）。连接/握手/发现/注册任何一步异常 → warning +
        返回已注册数（不 re-raise，不阻塞服务启动——内置 10 工具零影响）。

        Args:
            reg: ToolRegistry（全局 registry）

        Returns:
            成功注册的外部工具数（0 = 未启用 / command 空 / 失败）
        """
        if not settings.mcp_external_enabled:
            return 0
        if not settings.mcp_external_command:
            logger.warning("PW_MCP_EXTERNAL_COMMAND 为空，外部 MCP 接入跳过（fail-open）")
            return 0
        self._registry = reg
        try:
            await self._spawn_session()
            count = await self._register_tools(reg)
        except Exception as e:
            # fail-open：外部工具不可用不拖垮服务（与 067 入向 fail-closed 语义区分）
            logger.warning("MCP 外部接入失败（fail-open，内置工具不受影响）: %s", e)
            return len(self.registered)
        logger.info("外部 MCP 工具注册完成: %d 个 %s", count, sorted(self.registered))
        return count

    async def _spawn_session(self) -> None:
        """启动 stdio 子进程 + ClientSession + initialize 握手（超时 fail-open）

        stdio_client / ClientSession 两个异步上下文句柄存实例字段——会话需
        跨越 init_ext 生命周期存活至 close()。

        **必须用 asyncio.timeout 而非 asyncio.wait_for 包 __aenter__**：
        anyio 的 cancel scope 绑定"进入上下文的 task"，wait_for 会把协程
        ensure_future 进临时 task——close() 时从 lifespan task 退出 scope 报
        "Attempted to exit cancel scope in a different task"（真实 filesystem
        server 接入实测）；asyncio.timeout 在当前 task 内到期取消，scope 归属
        不变。握手全程受 settings.mcp_external_timeout 围栏。
        """
        command = list(settings.mcp_external_command)
        params = StdioServerParameters(
            command=command[0], args=command[1:], cwd=_AI_SERVICE_DIR,
        )
        self._stdio_cm = stdio_client(params)
        try:
            async with asyncio.timeout(settings.mcp_external_timeout):
                read, write = await self._stdio_cm.__aenter__()
                self._session_cm = ClientSession(read, write)
                self.session = await self._session_cm.__aenter__()
                await self.session.initialize()
        except BaseException:
            # 握手中途失败：同 task 内回收已进入的上下文（close 幂等，
            # 逐段 try/except），防 stdio 子进程孤儿存活到进程退出
            await self.close()
            raise

    async def _register_tools(self, reg) -> int:
        """list_tools 发现 → 逐工具冲突检测 → 注册（approval/no_retry 治理默认）

        重名跳过不覆盖（register() 是同名覆盖语义，防外部工具顶掉内置 10 工具）。
        注册契约：group=None（未分组，全阶段 schema 可见——外部工具与执行阶段
        无关，可见性交给审批 + 白名单两闸，plan §0 定案）/ approval="required"
        （硬编码非配置）/ no_retry=True（副作用不可重放）。
        """
        result = await asyncio.wait_for(self.session.list_tools(),
                                        timeout=settings.mcp_external_timeout)
        count = 0
        for tool in result.tools:
            if tool.name in reg.list_tool_names():
                logger.warning("外部工具 %s 与存量工具重名，跳过注册（防覆盖）", tool.name)
                continue
            reg.register(
                tool.name,
                tool.description or f"外部 MCP 工具 {tool.name}",
                tool.inputSchema or {"type": "object"},
                self._make_ext_func(tool.name),
                group=None,
                approval="required",
                no_retry=True,
            )
            self.registered.add(tool.name)
            count += 1
        return count

    def _make_ext_func(self, name: str):
        """构造外部工具执行闭包（AgentTool func 契约 async (ctx, args) -> str）"""

        async def _ext_func(ctx, args) -> str:
            """调用外部 MCP 工具并返回 LLM 可读文本（失败返回提示不抛）"""
            return await self._ext_call(name, args)

        return _ext_func

    async def _ext_call(self, name: str, args: dict) -> str:
        """执行外部工具调用并归一化结果（任何失败返回可读提示，不抛裸异常）

        结果优先级：isError → 可读失败提示；structuredContent 非空 → JSON
        序列化（结构化数据优先，防文本块重复表达）；否则 content 文本块拼接。
        空结果给占位提示（防 LLM 把空串当执行成功）。异常提示不含堆栈
        （铁律 8；异常消息本身可能含路径，仅文本层面，无密钥）。
        """
        try:
            result = await self.session.call_tool(name, arguments=args or {})
        except Exception as e:
            logger.warning("外部工具 %s 调用失败: %s", name, e)
            return f"（外部工具 {name} 调用失败: {e}）"
        if getattr(result, "isError", False):
            detail = _extract_text(result) or "未知错误"
            logger.warning("外部工具 %s 返回 isError: %s", name, detail[:200])
            return f"（外部工具 {name} 调用失败: {detail}）"
        if getattr(result, "structuredContent", None):
            return _truncate(json.dumps(result.structuredContent, ensure_ascii=False))
        text = _extract_text(result)
        if not text:
            return f"（外部工具 {name} 无返回结果）"
        return _truncate(text)

    async def close(self) -> None:
        """关闭 session 与 stdio 子进程（幂等；未初始化直接返回）

        关闭异常仅告警不抛（shutdown 路径不因外部清理失败而失败）。
        """
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("关闭 MCP session 异常（忽略）: %s", e)
            self._session_cm = None
            self.session = None
        if self._stdio_cm is not None:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("关闭 MCP stdio 异常（忽略）: %s", e)
            self._stdio_cm = None

    def agent_allowed_tools(self) -> Optional[set[str]]:
        """Agent 级显式授权白名单组装（module-083 WP-E 语义矩阵，两端点透传）

        语义矩阵（AC-12 红线）：
          - 外部未启用（或 init_ext 未曾调用）→ None：存量全量放行行为零变化；
          - 外部启用（**无论白名单是否为空**）→ 非 None：
            内置工具名 ∪（已注册外部 ∩ mcp_external_tools 显式授权）。
            启用分支绝不返回 None——None = 全量放行会把未授权外部工具放进
            白名单；白名单空 = 只放内置、外部全拒。
          - 白名单含未注册名（server 未提供）→ 交集为空自然不出现，不报错。
        """
        if not settings.mcp_external_enabled or self._registry is None:
            return None
        builtin = set(self._registry.list_tool_names()) - self.registered
        return builtin | (self.registered & set(settings.mcp_external_tools))


# 模块级单例（main.py lifespan / 两个 agent 端点共用）
external = ExternalMCPClient()
