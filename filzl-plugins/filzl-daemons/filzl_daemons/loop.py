import asyncio
import heapq
from contextvars import Context
from typing import (
    Any,
    Awaitable,
    Callable,
    Generator,
    List,
    Optional,
    TypeVar,
    Union,
)

from filzl_daemons.actions import ActionMeta
from filzl_daemons.logging import LOGGER
from filzl_daemons.tasks import TASK_MANAGER

_T = TypeVar("_T")


class CustomRunLoop(asyncio.AbstractEventLoop):
    def __init__(self):
        self._running: bool = False
        self._immediate: List[asyncio.Handle] = []
        self._scheduled: List[asyncio.TimerHandle] = []
        self._exc: Optional[Exception] = None
        self._time: float = 0

    def run_forever(self) -> None:
        asyncio._set_running_loop(self)
        self._running = True
        while (self._immediate or self._scheduled) and self._running:
            # Run greedily if we can
            if self._immediate:
                handle = self._immediate.pop(0)
            else:
                # TODO: Determine if we can use the scheduled tasks yet
                # handle = heapq.heappop(self._scheduled)
                raise NotImplementedError()
            if not handle._cancelled:
                handle._run()
            if self._exc is not None:
                raise self._exc

    def run_until_complete(
        self, future: Generator[Any, None, _T] | Awaitable[_T]
    ) -> Any:
        valid_future: asyncio.Future

        if not isinstance(future, asyncio.Future):
            # Ensure future is an asyncio.Future. `asyncio.ensure_future` accepts Awaitable as an argument.
            valid_future = asyncio.ensure_future(future, loop=self)  # type: ignore
        else:
            valid_future = future

        valid_future.add_done_callback(lambda f: self.stop())
        self.run_forever()
        valid_future.remove_done_callback(lambda f: self.stop())

        exception = valid_future.exception()
        if exception is not None:
            raise exception

        return valid_future.result()

    def call_soon(
        self, callback: Callable[..., Any], *args: Any, context: Context | None = None
    ) -> asyncio.Handle:
        handle = asyncio.Handle(callback, args, self)
        self._immediate.append(handle)
        return handle

    # def call_soon_threadsafe(
    #    self, callback: Callable[..., Any], *args: Any, context: Context | None = None
    # )  -> None:
    #    raise NotImplementedError()

    def call_later(
        self,
        delay: float,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> asyncio.TimerHandle:
        if delay < 0:
            raise ValueError("Can't schedule in the past")
        return self.call_at(self._time + delay, callback, *args, context=context)

    def call_at(
        self,
        when: float,
        callback: Callable[..., Any],
        *args: Any,
        context: Context | None = None,
    ) -> asyncio.TimerHandle:
        if when < self._time:
            raise ValueError("Can't schedule in the past")
        handle = asyncio.TimerHandle(when, callback, args, self)
        heapq.heappush(self._scheduled, handle)
        return handle

    def call_exception_handler(self, context: dict) -> None:
        self._exc = context.get("exception", None)

    async def shutdown_asyncgens(self) -> None:
        pass

    def create_future(self) -> asyncio.Future:
        return asyncio.Future(loop=self)

    def create_task(
        self,
        coro: Union[Callable[..., Awaitable[Any]], Any],
        *,
        name: Optional[str] = None,
        context: Context | None = None,
    ) -> asyncio.Task:
        async def wrapper():
            try:
                awaitable_result = coro() if callable(coro) else coro
                result = await awaitable_result
                if isinstance(result, ActionMeta):
                    # This should be scheduled in a task worker
                    LOGGER.info(f"ActionMeta received, scheduling task: {result}")
                    # See if it's already been queued
                    task_id, wait_for_completion = await TASK_MANAGER.queue_work(result)
                    # TODO: GET THE RESULT
                    await wait_for_completion
                    result = TASK_MANAGER.results[task_id]
                return result
            except Exception as e:
                LOGGER.warning(f"Internal exception: {e}")
                self._exc = e

        # inspect coro to get the args and kwargs
        return asyncio.Task(wrapper(), loop=self)

    def get_debug(self) -> bool:
        return False

    def time(self) -> float:
        return self._time

    def is_running(self) -> bool:
        return self._running

    def is_closed(self) -> bool:
        return not self._running

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
