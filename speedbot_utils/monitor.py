"""
性能监控模块 / Performance Monitor

提供请求级别的计时和统计，识别慢响应并输出 p50/p95 等百分位延迟数据。

Provides request-level timing and statistics. Identifies slow responses and
outputs p50/p95 percentile latency data.
"""

import asyncio
import statistics
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict, List, Optional


@dataclass
class RequestMetrics:
    """
    单次请求的性能指标 / Per-request performance metrics.

    Attributes:
        request_id: 请求唯一标识 / Unique request identifier.
        start_time: 请求开始单调时间 / Request start monotonic time.
        end_time: 请求结束单调时间（完成后设置） / End monotonic time (set on finish).
        cache_hit: 是否命中语义缓存 / Whether semantic cache hit occurred.
        intent_routed: 是否被意图路由直接处理 / Whether intent router handled directly.
        source: 响应来源 ("cache" | "intent" | "llm") / Response source.
    """

    request_id: str
    start_time: float = field(default_factory=time.monotonic)
    end_time: Optional[float] = None
    cache_hit: bool = False
    intent_routed: bool = False
    source: str = "llm"

    @property
    def total_latency_ms(self) -> float:
        """总延迟（毫秒） / Total latency in milliseconds."""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000


class PerformanceMonitor:
    """
    性能监控器 / Performance Monitor.

    通过 asynccontextmanager track() 对请求全程计时，
    记录缓存命中、意图路由等来源，统计 p50/p95 等延迟百分位。

    Times full request lifecycle via asynccontextmanager track().
    Records cache hit / intent-routed / LLM source and computes p50/p95
    latency percentiles.
    """

    def __init__(self, slow_threshold_ms: float = 3000.0) -> None:
        """
        初始化性能监控器 / Initialise the performance monitor.

        Args:
            slow_threshold_ms: 慢响应阈值（毫秒），超过则记录警告 / Slow threshold in ms.
        """
        self.slow_threshold_ms = slow_threshold_ms
        self._metrics: List[RequestMetrics] = []
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def track(self, request_id: str) -> AsyncGenerator[RequestMetrics, None]:
        """
        追踪单次请求性能的异步上下文管理器 / Async context manager for tracking one request.

        Usage::

            async with monitor.track("req-001") as m:
                m.cache_hit = True
                m.source = "cache"

        Args:
            request_id: 请求唯一标识 / Unique request identifier.

        Yields:
            RequestMetrics 实例（可在内部修改 cache_hit / source 等字段）。
            RequestMetrics instance (caller can set cache_hit, source, etc.).
        """
        metrics = RequestMetrics(request_id=request_id)
        try:
            yield metrics
        finally:
            metrics.end_time = time.monotonic()
            async with self._lock:
                self._metrics.append(metrics)

    def get_stats_text(self) -> str:
        """
        返回格式化的性能统计文本 / Return formatted performance statistics text.

        包含 avg/p50/p95/min/max 延迟和来源分布。
        Includes avg/p50/p95/min/max latency and source distribution.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        if not self._metrics:
            return "📊 性能监控\n  暂无数据"

        latencies = [m.total_latency_ms for m in self._metrics if m.end_time is not None]
        if not latencies:
            return "📊 性能监控\n  暂无完成请求"

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        avg = statistics.mean(sorted_lat)
        p50 = sorted_lat[int(n * 0.50)]
        p95 = sorted_lat[min(int(n * 0.95), n - 1)]
        min_lat = sorted_lat[0]
        max_lat = sorted_lat[-1]

        # 来源分布
        source_dist: Dict[str, int] = {}
        for m in self._metrics:
            source_dist[m.source] = source_dist.get(m.source, 0) + 1

        lines = [
            f"📊 性能监控统计",
            f"  总请求数: {n}",
            f"  平均延迟: {avg:.1f} ms",
            f"  P50 延迟: {p50:.1f} ms",
            f"  P95 延迟: {p95:.1f} ms",
            f"  最小延迟: {min_lat:.1f} ms",
            f"  最大延迟: {max_lat:.1f} ms",
            f"  来源分布:",
        ]
        for source, count in sorted(source_dist.items(), key=lambda x: -x[1]):
            pct = count / n * 100
            lines.append(f"    {source}: {count} ({pct:.1f}%)")
        return "\n".join(lines)
