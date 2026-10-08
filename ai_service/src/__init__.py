"""src 包：导入即做一次环境代理变量兜底。

放在这里是因为任何 `from src.* import ...` 都会先执行本文件，从而保证
清理动作早于所有 httpx 客户端的构造（LLM 供应商、爬虫、内部服务调用）。

详见 src/proxy_env.py 的模块说明：`no_proxy` 含 `[::1]` 会让 httpx 抛
`InvalidURL: Invalid port: ':1]'`，导致所有出站 HTTP 调用失败，而错误信息
完全看不出与代理有关。
"""
from src.proxy_env import sanitize_no_proxy as _sanitize_no_proxy

_sanitize_no_proxy()
