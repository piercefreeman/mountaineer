import asyncio
from functools import wraps
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
