import asyncio
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from typing import Generic, TypeVar

from filzl.logging import LOGGER

T = TypeVar("T")


class ShutdownTask:
    pass


class AsyncProcessQueue(Generic[T]):
    """
    A wrapper around a multiprocessing.Queue that allows for async operations.
    Original logic: https://stackoverflow.com/a/24704950
    """

    def __init__(self, maxsize: int = 0):
        self._queue: multiprocessing.Queue[T | ShutdownTask] = multiprocessing.Queue(
            maxsize=maxsize
        )
        self._real_executor: ThreadPoolExecutor | None = None

    @property
    def _executor(self):
        if not self._real_executor:
            self._real_executor = ThreadPoolExecutor(max_workers=4)
        return self._real_executor

    def __getstate__(self):
        self_dict = self.__dict__.copy()
        self_dict["_real_executor"] = None
        return self_dict

    def __getattr__(self, name):
        if name in [
            "qsize",
            "empty",
            "full",
            "put",
            "put_nowait",
            "get",
            "get_nowait",
            "close",
        ]:
            return getattr(self._queue, name)
        else:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

    async def aput(self, item):
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._queue.put, item)
        except asyncio.CancelledError:
            # If we're blocking, try to read from the queue so we can unblock the workers
            self._queue.get_nowait()
            raise

    async def aget(self):
        loop = asyncio.get_running_loop()
        wait_task = loop.run_in_executor(self._executor, self._queue.get)

        try:
            await asyncio.wait({wait_task}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            # Put something into the queue to unblock the get operation
            self._queue.put(ShutdownTask())
            raise
        return wait_task.result()

    def shutdown_executor(self):
        if self._real_executor:
            self._real_executor.shutdown()


class AlertThread(Thread):
    """
    By default threads silently die if an exception is raised. This class
    logs the exception first.

    """

    def run(self):
        try:
            # Call the original run method
            super().run()
        except Exception as e:
            # Log the exception or handle it
            LOGGER.exception(f"Error in thread {self.name}: {e}")
            raise
