"""
样例外部 MCP server（module-084 验收 fixture）— FastMCP stdio 子进程
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用途：外部 MCP 客户端接入（agent/mcp_client.py）的真实验收对象——
`PW_MCP_EXTERNAL_COMMAND='["python","scripts/mcp_sample_server.py"]'` 启动
本子进程，client 经真实 stdio 握手发现并注册下面 2 个工具。属验收样例
（非 Agent 核心生产链路）。生产使用方把 command 指向任意真实 server 即可
（如官方 filesystem server），client 与 server 内容无关。

两个工具（ext_ 前缀可辨识，AC-29）：
  - ext_current_time：只读——返回当前 UTC 时间（演示读取类工具）
  - ext_append_log：副作用——向 mcp_sample_out.log 追加一行参数内容
    （演示审批治理价值：approval="required" 人工审批后才真实执行）

日志走 logging（stderr）——stdio 模式 stdout 是协议通道，禁 print
（对齐 mcp_server.py 先例）。
"""
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [sample-server] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("mcp-sample-server")

_LOG_FILE = "mcp_sample_out.log"


@mcp.tool()
def ext_current_time() -> str:
    """返回当前 UTC 时间（ISO 8601 格式，只读演示工具）"""
    return datetime.now(timezone.utc).isoformat()


@mcp.tool()
def ext_append_log(content: str) -> str:
    """向本地 mcp_sample_out.log 追加一行内容（副作用演示工具，需审批）"""
    with open(_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{content}\n")
    return f"已追加到 {_LOG_FILE}: {content[:100]}"


if __name__ == "__main__":
    # stdio 传输（client 经 StdioServerParameters 子进程启动）
    logger.info("样例 MCP server 启动（stdio）")
    mcp.run()
