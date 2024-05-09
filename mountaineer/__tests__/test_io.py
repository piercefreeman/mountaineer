import pytest

from mountaineer.io import lru_cache_async


@pytest.mark.asyncio
async def test_lru_cache_async_infinite_cache():
    exec_counts = 0

    @lru_cache_async(maxsize=None)
    async def cache_values():
        nonlocal exec_counts
        exec_counts += 1
        return exec_counts

    assert await cache_values() == 1
    assert await cache_values() == 1
    assert await cache_values() == 1


@pytest.mark.asyncio
async def test_lru_cache_async_limited_cache():
    exec_counts = 0

    @lru_cache_async(maxsize=2)
    async def cache_values(a: int):
        nonlocal exec_counts
        exec_counts += 1
        return exec_counts

    assert await cache_values(1) == 1
    assert await cache_values(1) == 1
    assert await cache_values(1) == 1

    assert await cache_values(2) == 2

    # At this point the cache is full with [1, 2]
    # If the next value is out of scope, it will clear
    # the oldest value (1)
    assert await cache_values(3) == 3

    # This new call will recompute the value for 1
    assert await cache_values(1) == 4
