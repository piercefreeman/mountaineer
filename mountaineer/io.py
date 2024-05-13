import asyncio
import socket
from functools import lru_cache, wraps
from typing import Any, Callable, Coroutine, TypeVar


async def gather_with_concurrency(
    tasks: list[Coroutine[Any, Any, Any]],
    *,
    n: int,
    catch_exceptions: bool = False,
) -> list[Any]:
    semaphore = asyncio.Semaphore(n)

    async def sem_task(task: Coroutine[Any, Any, Any]) -> Any:
        async with semaphore:
            return await task

    return await asyncio.gather(
        *(sem_task(task) for task in tasks),
        return_exceptions=catch_exceptions,
    )


T = TypeVar("T")


def async_to_sync(async_fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., T]:
    @wraps(async_fn)
    def wrapper(*args, **kwargs) -> T:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(async_fn(*args, **kwargs))
        return result

    return wrapper


def get_free_port() -> int:
    """
    Leverage the OS-port shortcut :0 to get a free port. Return the value
    of the port that was assigned.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
        s.close()
    return int(port)


def lru_cache_async(
    maxsize: int | None = 100,
):
    def decorator(
        async_function: Callable[..., Coroutine[Any, Any, T]],
    ):
        @lru_cache(maxsize=maxsize)
        @wraps(async_function)
        def internal(*args, **kwargs):
            coroutine = async_function(*args, **kwargs)
            # Unlike regular coroutine functions, futures can be awaited multiple times
            # so our caller functions can await the same future on multiple cache hits
            return asyncio.ensure_future(coroutine)

        return internal

    return decorator
