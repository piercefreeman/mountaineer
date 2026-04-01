import asyncio

import pytest

from mountaineer.io import async_to_sync, lru_cache_async


def test_async_to_sync_without_current_event_loop(
    monkeypatch: pytest.MonkeyPatch,
):
    created_loops: list[asyncio.AbstractEventLoop] = []
    original_new_event_loop = asyncio.new_event_loop

    @async_to_sync
    async def get_value(value: int):
        await asyncio.sleep(0)
        return value

    def raise_no_current_loop():
        raise RuntimeError("There is no current event loop in thread 'MainThread'.")

    def track_new_event_loop():
        loop = original_new_event_loop()
        created_loops.append(loop)
        return loop

    monkeypatch.setattr(asyncio, "get_event_loop", raise_no_current_loop)
    monkeypatch.setattr(asyncio, "new_event_loop", track_new_event_loop)

    assert get_value(42) == 42
    assert len(created_loops) == 1
    assert created_loops[0].is_closed()


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
