from random import random, seed

import pytest

from mountaineer.cache import extended_lru_cache


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
