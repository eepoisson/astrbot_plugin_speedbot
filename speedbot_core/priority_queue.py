"""
优先级消息队列 / Priority Message Queue

使用 asyncio.PriorityQueue 对消息按优先级排序处理，
管理指令获得更高优先级，避免在高并发时被聊天消息饿死。
配合 asyncio.Semaphore 控制最大并发数。

Uses asyncio.PriorityQueue to process messages by priority. Admin commands
get higher priority to avoid starvation under high concurrency. Pairs with
asyncio.Semaphore to cap maximum concurrent workers.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable, Optional


class Priority(IntEnum):
    """
    任务优先级枚举 / Task priority enumeration.

    数值越小，优先级越高 / Lower value = higher priority.
    """

    CRITICAL = 0
    ADMIN = 10
    HIGH = 20
    NORMAL = 50
    LOW = 80
    BACKGROUND = 100


@dataclass(order=True)
class QueuedTask:
    """
    优先级队列中的任务封装 / Queued task wrapper for priority queue.

    order=True 使得 PriorityQueue 可以按优先级字段排序。
    order=True enables PriorityQueue to sort by priority field.
    """

    priority: int
    seq: int = field(compare=True)  # 保证同优先级 FIFO / FIFO within same priority
    coro: Any = field(compare=False)  # coroutine object
    enqueue_time: float = field(default_factory=time.monotonic, compare=False)


class PriorityQueue:
    """
    优先级消息处理队列 / Priority Message Processing Queue.

    将异步协程按优先级调度执行，通过 Semaphore 限制最大并发数，
    并记录队列峰值大小、平均等待时间等统计信息。

    Schedules async coroutines by priority with concurrency capped by
    Semaphore. Tracks peak queue size, average wait time, etc.
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        """
        初始化优先级队列 / Initialise the priority queue.

        Args:
            max_concurrent: 最大并发协程数 / Max concurrent coroutines.
        """
        self.max_concurrent = max_concurrent
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._seq: int = 0
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None

        # 统计
        self.processed_count: int = 0
        self.total_wait_time: float = 0.0
        self.peak_queue_size: int = 0
        self._error_count: int = 0

    async def submit(
        self,
        coro: Awaitable,
        priority: int = Priority.NORMAL,
    ) -> None:
        """
        提交协程到队列 / Submit a coroutine to the queue.

        Args:
            coro: 待执行的异步协程 / Awaitable coroutine to execute.
            priority: 任务优先级（Priority 枚举或整数） / Task priority.
        """
        self._seq += 1
        task = QueuedTask(priority=priority, seq=self._seq, coro=coro)
        await self._queue.put(task)
        current_size = self._queue.qsize()
        if current_size > self.peak_queue_size:
            self.peak_queue_size = current_size

    async def _worker(self) -> None:
        """
        内部工作循环 / Internal worker loop.

        持续从队列取出任务并在 Semaphore 控制下并发执行。
        Continuously dequeues and executes tasks under Semaphore concurrency control.
        """
        while self._running:
            try:
                task: QueuedTask = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            wait_time = time.monotonic() - task.enqueue_time
            self.total_wait_time += wait_time

            async with self._semaphore:
                try:
                    await task.coro
                    self.processed_count += 1
                except Exception:
                    self._error_count += 1
                finally:
                    self._queue.task_done()

    async def start(self) -> None:
        """
        启动队列工作循环 / Start the queue worker loop.
        """
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """
        停止队列工作循环并等待当前任务完成 / Stop the queue worker and drain pending tasks.
        """
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    def get_stats_text(self) -> str:
        """
        返回格式化的队列统计文本 / Return formatted queue statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        avg_wait = (
            self.total_wait_time / self.processed_count
            if self.processed_count > 0
            else 0.0
        )
        return (
            f"⚡ 优先级队列统计\n"
            f"  已处理任务: {self.processed_count}\n"
            f"  错误任务数: {self._error_count}\n"
            f"  平均等待:   {avg_wait * 1000:.2f} ms\n"
            f"  队列峰值:   {self.peak_queue_size}\n"
            f"  当前队列:   {self._queue.qsize()}\n"
            f"  最大并发:   {self.max_concurrent}"
        )
