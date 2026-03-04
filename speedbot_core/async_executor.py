"""
异步执行器 / Async Executor

使用 loop.run_in_executor() 将同步阻塞操作委托给 ThreadPoolExecutor，
防止主事件循环被阻塞，保持 AstrBot 的高响应性。

Uses loop.run_in_executor() to offload synchronous blocking operations to a
ThreadPoolExecutor, keeping the main event loop unblocked and AstrBot
responsive.
"""

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional


class AsyncExecutor:
    """
    异步执行器 / Async Executor.

    封装 ThreadPoolExecutor，通过 run_in_executor 在独立线程中运行同步函数，
    避免阻塞 asyncio 事件循环。

    Wraps ThreadPoolExecutor to run synchronous functions via run_in_executor,
    preventing asyncio event loop blocking.
    """

    def __init__(self, max_workers: Optional[int] = None) -> None:
        """
        初始化异步执行器 / Initialise the async executor.

        Args:
            max_workers: 线程池最大线程数，None 使用默认值 / Max threads; None = default.
        """
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="speedbot_worker",
        )
        self.task_count: int = 0
        self.error_count: int = 0

    async def run(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        在线程池中运行同步函数 / Run a synchronous function in the thread pool.

        Args:
            func: 同步可调用对象 / Synchronous callable.
            *args: 位置参数 / Positional arguments.
            **kwargs: 关键字参数 / Keyword arguments.

        Returns:
            函数返回值 / Return value of func.

        Raises:
            Exception: 函数执行过程中抛出的任何异常 / Any exception raised by func.
        """
        loop = asyncio.get_event_loop()
        self.task_count += 1
        try:
            if kwargs:
                # run_in_executor 不支持 kwargs，使用 functools.partial 包装
                partial_func = functools.partial(func, *args, **kwargs)
                return await loop.run_in_executor(self._executor, partial_func)
            return await loop.run_in_executor(self._executor, func, *args)
        except Exception:
            self.error_count += 1
            raise

    def shutdown(self, wait: bool = True) -> None:
        """
        关闭线程池 / Shut down the thread pool.

        Args:
            wait: 是否等待所有线程完成 / Whether to wait for all threads to finish.
        """
        self._executor.shutdown(wait=wait)

    def get_stats_text(self) -> str:
        """
        返回格式化的执行器统计文本 / Return formatted executor statistics text.

        Returns:
            多行统计字符串 / Multi-line statistics string.
        """
        return (
            f"🔧 异步执行器统计\n"
            f"  总任务数: {self.task_count}\n"
            f"  错误数:   {self.error_count}"
        )
