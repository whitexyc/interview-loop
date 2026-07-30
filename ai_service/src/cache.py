"""
Redis 查询缓存 — 检索结果缓存层
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

在整个 RAG 链路中的位置：
  本模块是检索结果的可选缓存层，放在 _retrieve() 的入口处。
  不参与核心检索逻辑，Redis 不可用时静默降级（不影响检索功能）。

设计决策：
  1. 为什么用 SHA256 的前 12 位作为 key？
     完整 query 可能很长（包含中文和特殊字符），SHA256 提供固定
     长度的唯一标识，12 位十六进制 = 48 bits 碰撞概率极低。
     比直接截断 query 更可靠（不同语义的 query 可能前缀相同）。

  2. 为什么用 300 秒 TTL？
     5 分钟在缓存命中率和数据新鲜度之间取得平衡。对于知识库场景，
     文档不会频繁更新，5 分钟的缓存能为常见问题提供良好的响应速度。

  3. 为什么用懒连接？
     如果 Redis 在启动时不可用，主动连接会导致应用启动失败。
     懒连接将连接推迟到首次使用时，Redis 恢复后可自动重连。

  4. 为什么用 try/except 包裹所有 Redis 操作？
     Redis 是可选的优化层，不是核心功能依赖。Redis 故障时
     必须静默降级，不能影响用户的检索功能。
"""
import hashlib
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis 查询缓存（异步，优雅降级）

    职责：
    1. 缓存 _retrieve() 的检索结果（以 query SHA256 为键）
    2. TTL 300 秒自动过期
    3. Redis 不可用时静默降级，不影响检索链路

    使用示例：
        cache = RedisCache()
        docs = await cache.get("rag:retrieve:abc123")
        if docs is None:
            docs = await do_retrieve(query)
            await cache.set("rag:retrieve:abc123", docs)

    注意：这是一个单例实例（见文件底部的 cache 变量）。
    """

    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._connected: bool = False

    async def _ensure_client(self) -> Optional[redis.Redis]:
        """懒连接 Redis 客户端

        Redis 启动时不可用不会影响应用启动。首次 get/set 调用时
        尝试连接，失败则标记 _connected=False 并返回 None。
        后续调用检测到 _connected=False 会跳过 Redis 操作。

        不维护连接池（单例实例 + 异步连接足够轻量），
        但每次连接失败后不会自动重试（等待下次 _ensure_client 调用）。
        """
        if self._client is not None and self._connected:
            return self._client
        self._client = None  # 确保每次重试都创建新连接

        try:
            self._client = redis.from_url(
                settings.redis_url,
                decode_responses=True,  # 自动 decode bytes → str
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            # 验证连接可用（空 ping 只是连接检查，无副作用）
            await self._client.ping()
            self._connected = True
            logger.info("Redis 缓存连接成功: %s", settings.redis_url)
            return self._client
        except Exception as e:
            logger.warning("Redis 缓存不可用 (连接失败): %s", e)
            self._connected = False
            self._client = None
            return None

    async def get(self, key: str) -> Optional[list[dict]]:
        """从缓存读取检索结果

        如果 key 不存在返回 None，调用方正常执行检索。
        所有异常都 catch 并降级（返回 None），不抛出到调用方。

        Args:
            key: 缓存键（如 "rag:retrieve:abc123"）

        Returns:
            文档列表，或 None（未命中/Redis 不可用）
        """
        try:
            client = await self._ensure_client()
            if client is None or not self._connected:
                return None
            data = await client.get(key)
            if data is None:
                return None
            return json.loads(data)
        except Exception as e:
            logger.warning("Redis 缓存读取失败: %s", e)
            self._connected = False  # 标记不可用，后续调用跳过
            self._client = None      # 释放死连接，下次尝试重连
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """写入检索结果到缓存

        以 JSON 序列化存储，TTL 默认 300 秒。
        所有异常都 catch 并降级（返回 False），不抛出到调用方。

        Args:
            key: 缓存键
            value: 待缓存的数据（会被 JSON 序列化）
            ttl: 过期时间（秒），默认 300

        Returns:
            True 如果写入成功，False 如果失败
        """
        try:
            client = await self._ensure_client()
            if client is None or not self._connected:
                return False
            await client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
            return True
        except Exception as e:
            logger.warning("Redis 缓存写入失败: %s", e)
            self._connected = False
            self._client = None      # 释放死连接，下次尝试重连
            return False


# 全局单例 — 整个应用共享一个缓存实例
cache = RedisCache()
