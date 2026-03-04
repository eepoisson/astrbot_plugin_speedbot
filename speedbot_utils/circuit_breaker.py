"""
熔断器 / Circuit Breaker

防止下游服务异常导致请求雪崩，实现三状态（CLOSED / OPEN / HALF_OPEN）熔断保护。

Protects against cascading failures caused by downstream service errors.
Implements three-state circuit breaking: CLOSED (normal) → OPEN (tripped) →
HALF_OPEN (probing recovery).
"""

import asyncio
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import AsyncGenerator


class CircuitState(Enum):
    """
    熔断器状态枚举 / Circuit breaker state enumeration.

    CLOSED   — 正常运行，允许所有请求通过 / Normal; all requests pass through.
    OPEN     — 熔断开启，拒绝所有请求 / Tripped; all requests rejected.
    HALF_OPEN — 半开探测，允许有限请求通过以探测恢复 / Probing; limited requests pass.
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """
    熔断器开路异常 / Raised when the circuit breaker is OPEN.

    携带友好的用户提示信息 / Carries a user-friendly message.
    """

    pass


class CircuitBreaker:
    """
    三状态熔断器 / Three-state Circuit Breaker.

    当连续失败次数达到 failure_threshold 时触发熔断（OPEN）；
    经过 recovery_timeout 秒后进入半开（HALF_OPEN）探测状态；
    若探测成功则恢复正常（CLOSED）。

    Trips (OPEN) after failure_threshold consecutive failures.
    Enters HALF_OPEN after recovery_timeout seconds.
    Resets to CLOSED if probing call succeeds.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        name: str = "default",
    ) -> None:
        """
        初始化熔断器 / Initialise the circuit breaker.

        Args:
            failure_threshold: 连续失败阈值，达到后触发熔断 / Consecutive failure threshold.
            recovery_timeout: 冷却时间（秒），OPEN → HALF_OPEN / Recovery timeout in seconds.
            half_open_max_calls: 半开状态最大探测调用数 / Max calls in HALF_OPEN state.
            name: 熔断器名称（用于日志） / Circuit breaker name (for logging).
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.name = name

        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls: int = 0
        self._lock = asyncio.Lock()

        # 统计
        self.total_calls: int = 0
        self.total_failures: int = 0
        self.total_rejected: int = 0
        self.total_successes: int = 0

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态 / Current circuit breaker state."""
        return self._state

    async def _update_state(self) -> CircuitState:
        """
        根据时间和状态更新熔断器状态 / Update state based on time and transitions.

        Returns:
            当前有效状态 / Current effective state.
        """
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
        return self._state

    @asynccontextmanager
    async def protect(self) -> AsyncGenerator[None, None]:
        """
        熔断保护上下文管理器 / Circuit breaker protection context manager.

        OPEN 状态时抛出 CircuitBreakerError；
        HALF_OPEN 超出探测数时也拒绝请求。
        Raises CircuitBreakerError when OPEN or when HALF_OPEN quota is exceeded.

        Usage::

            async with breaker.protect():
                result = await call_external_service()

        Raises:
            CircuitBreakerError: 熔断器开路时 / When circuit is open.
        """
        async with self._lock:
            current_state = await self._update_state()
            self.total_calls += 1

            if current_state == CircuitState.OPEN:
                self.total_rejected += 1
                raise CircuitBreakerError(
                    f"⚠️ 服务暂时不可用（熔断器已开启，名称: {self.name}）。"
                    f"请稍后再试，预计 {self.recovery_timeout:.0f} 秒后恢复探测。"
                )

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    self.total_rejected += 1
                    raise CircuitBreakerError(
                        f"⚠️ 服务恢复探测中（熔断器半开，名称: {self.name}）。"
                        f"请稍候片刻再重试。"
                    )
                self._half_open_calls += 1

        try:
            yield
            # 成功：重置失败计数
            async with self._lock:
                self._failure_count = 0
                self._state = CircuitState.CLOSED
                self.total_successes += 1
        except CircuitBreakerError:
            raise
        except Exception:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                self.total_failures += 1

                if self._state == CircuitState.HALF_OPEN:
                    # 半开探测失败，重新开路
                    self._state = CircuitState.OPEN
                elif self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
            raise

    def get_stats_text(self) -> str:
        """
        返回格式化的熔断器统计文本 / Return formatted circuit breaker statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        state_emoji = {
            CircuitState.CLOSED: "✅",
            CircuitState.OPEN: "🔴",
            CircuitState.HALF_OPEN: "🟡",
        }
        emoji = state_emoji.get(self._state, "❓")
        return (
            f"🛡️ 熔断器统计 ({self.name})\n"
            f"  当前状态:   {emoji} {self._state.value}\n"
            f"  总调用数:   {self.total_calls}\n"
            f"  成功数:     {self.total_successes}\n"
            f"  失败数:     {self.total_failures}\n"
            f"  拒绝数:     {self.total_rejected}\n"
            f"  连续失败:   {self._failure_count}/{self.failure_threshold}"
        )
