"""
HTTP 连接池管理器 / HTTP Connection Pool Manager

使用 aiohttp.TCPConnector 创建持久化连接池，复用 TCP 长连接，
避免每次请求 LLM API 时重复三次握手，显著降低网络延迟。

Uses aiohttp.TCPConnector to maintain a persistent connection pool. Reuses
TCP keep-alive connections to avoid repeated three-way handshakes on every
LLM API request, significantly reducing network latency.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

try:
    import aiohttp
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


class ConnectionPool:
    """
    HTTP 连接池管理器 / HTTP Connection Pool Manager.

    懒初始化、线程安全（Double-check + asyncio.Lock）。
    提供 asynccontextmanager get_session() 方法供调用方使用。

    Lazy-initialised, concurrency-safe (double-check + asyncio.Lock).
    Exposes an asynccontextmanager get_session() for callers.
    """

    def __init__(
        self,
        pool_size: int = 100,
        per_host_limit: int = 30,
        keepalive_timeout: int = 60,
    ) -> None:
        """
        初始化连接池管理器 / Initialise the connection pool manager.

        Args:
            pool_size: 最大连接数 / Maximum total connections.
            per_host_limit: 每主机最大连接数 / Maximum connections per host.
            keepalive_timeout: 长连接保活时间（秒） / Keep-alive timeout in seconds.
        """
        self.pool_size = pool_size
        self.per_host_limit = per_host_limit
        self.keepalive_timeout = keepalive_timeout

        self._connector: Optional[object] = None
        self._session: Optional[object] = None
        self._lock = asyncio.Lock()

        self.request_count: int = 0
        self.error_count: int = 0

    async def _ensure_session(self) -> object:
        """
        懒初始化确保 session 已就绪 / Lazily initialise the aiohttp session.

        Returns:
            aiohttp.ClientSession 实例 / aiohttp ClientSession instance.

        Raises:
            ImportError: aiohttp 未安装时 / When aiohttp is not installed.
            RuntimeError: 无法创建 session 时 / When session cannot be created.
        """
        if not _AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp 未安装，请运行: pip install aiohttp>=3.9.0"
            )
        # Double-check pattern
        if self._session is not None and not self._session.closed:
            return self._session

        async with self._lock:
            if self._session is not None and not self._session.closed:
                return self._session

            self._connector = aiohttp.TCPConnector(
                limit=self.pool_size,
                limit_per_host=self.per_host_limit,
                keepalive_timeout=self.keepalive_timeout,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                connector=self._connector,
                connector_owner=True,
            )
            return self._session

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator:
        """
        获取共享 aiohttp.ClientSession / Obtain the shared aiohttp.ClientSession.

        使用方式 / Usage::

            async with pool.get_session() as session:
                async with session.get(url) as resp:
                    data = await resp.json()

        Yields:
            aiohttp.ClientSession 实例 / aiohttp ClientSession instance.
        """
        try:
            session = await self._ensure_session()
            self.request_count += 1
            yield session
        except Exception:
            self.error_count += 1
            raise

    async def close(self) -> None:
        """
        优雅关闭连接池 / Gracefully close the connection pool.

        等待所有连接释放后关闭 session 和 connector。
        Waits for all connections to be released before closing.
        """
        async with self._lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
                self._session = None
            if self._connector is not None:
                await self._connector.close()
                self._connector = None

    def get_stats_text(self) -> str:
        """
        返回格式化的连接池统计文本 / Return formatted connection pool statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        status = "已就绪" if (self._session and not self._session.closed) else "未初始化"
        return (
            f"🌐 连接池统计\n"
            f"  状态:         {status}\n"
            f"  总请求数:     {self.request_count}\n"
            f"  错误数:       {self.error_count}\n"
            f"  最大连接数:   {self.pool_size}\n"
            f"  每主机限制:   {self.per_host_limit}\n"
            f"  保活时间:     {self.keepalive_timeout}s"
        )
