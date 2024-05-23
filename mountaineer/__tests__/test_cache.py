import asyncio
from contextlib import contextmanager
from random import random, seed
from typing import Any
from unittest.mock import MagicMock

import pytest

from mountaineer.cache import AsyncLoopObjectCache, extended_lru_cache

#
# LRU Cache
#


@extended_lru_cache(maxsize=100)
def get_random_data(param: int):
    return random()


@pytest.fixture(autouse=True)
def reset_cache():
    get_random_data._cache.clear()  # type: ignore


def test_extended_lru_cache():
    seed(20)
    val1 = get_random_data(0)
    val2 = get_random_data(0)

    assert val1 == val2


def test_extended_lru_cache_different_params():
    seed(20)
    val1 = get_random_data(0)
    val2 = get_random_data(1)

    assert val1 != val2


def test_extended_lru_no_cache():
    seed(20)
    val1 = get_random_data(0, use_cache=False)
    val2 = get_random_data(0, use_cache=False)

    assert val1 != val2


#
# AsyncLoopObjectCache
#


@contextmanager
def create_temporary_event_loop(set_running: bool = True):
    current_event_loop = asyncio._get_running_loop()

    # Out session cache requires the running loop to be set
    event_loop = asyncio.new_event_loop()
    asyncio._set_running_loop(event_loop if set_running else None)
    try:
        yield event_loop
    finally:
        event_loop.close()
        asyncio._set_running_loop(current_event_loop)


def test_get_obj_no_session():
    with create_temporary_event_loop():
        session_cache: AsyncLoopObjectCache[Any] = AsyncLoopObjectCache()
        assert session_cache.get_obj() is None


def test_set_and_get_obj():
    with create_temporary_event_loop():
        session_cache: AsyncLoopObjectCache[Any] = AsyncLoopObjectCache()
        mock_session = MagicMock()

        session_cache.set_obj(mock_session)
        obj = session_cache.get_obj()

        assert obj
        assert obj == mock_session


def test_get_lock_first_time():
    async def get_lock():
        session_cache: AsyncLoopObjectCache[Any] = AsyncLoopObjectCache()

        async with session_cache.get_lock():
            assert id(event_loop) in session_cache.loop_locks
            assert isinstance(session_cache.loop_locks[id(event_loop)], asyncio.Lock)

    with create_temporary_event_loop(set_running=False) as event_loop:
        event_loop.run_until_complete(get_lock())


def test_get_lock_reuse_lock():
    """
    get_lock should reuse an existing lock if one is already associated with the current
    event loop, so different tasks actually block on one another for the common object.

    """

    async def get_lock():
        session_cache: AsyncLoopObjectCache[Any] = AsyncLoopObjectCache()

        async with session_cache.get_lock():
            lock_first = session_cache.loop_locks[id(event_loop)]

        async with session_cache.get_lock():
            lock_second = session_cache.loop_locks[id(event_loop)]

        assert lock_first == lock_second

    with create_temporary_event_loop(set_running=False) as event_loop:
        event_loop.run_until_complete(get_lock())
