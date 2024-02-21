from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from queue import Empty
from typing import Generic, TypeVar

from filzl.logging import LOGGER


def safe_task(fn):
    @wraps(fn)
    async def inner(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            LOGGER.error("Unhandled exception in task", exc_info=True)
            raise e

    return inner


T = TypeVar("T")


class AsyncMultiprocessingQueue(Generic[T]):
    def __init__(self, maxsize=0, max_workers=4):
        self.max_workers = max_workers

        self._queue: multiprocessing.Queue[T] = multiprocessing.Queue(maxsize=maxsize)
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

    def __getstate__(self):
        return {
            "_queue": self._queue,
            "max_workers": self.max_workers,
        }

    def __setstate__(self, state):
        self._queue = state["_queue"]
        self.max_workers = state["max_workers"]
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

    async def async_get(self):
        loop = asyncio.get_running_loop()
        while True:
            try:
                return await loop.run_in_executor(
                    self._executor, self._queue.get_nowait
                )
            except Empty:
                # Short sleep to yield control and check for cancellation
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise

    async def async_put(self, item):
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._queue.put, item)

    def close(self):
        self._executor.shutdown(wait=True)
