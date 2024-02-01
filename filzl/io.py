import asyncio
from typing import Any, Coroutine


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
