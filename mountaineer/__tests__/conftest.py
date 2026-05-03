import asyncio
from warnings import filterwarnings

import pytest

from mountaineer.config import unregister_config


@pytest.fixture(autouse=True)
def ignore_httpx_deprecation_warnings():
    # Ignore httpx deprecation warnings until fastapi updates its internal test constructor
    # https://github.com/encode/httpx/blame/master/httpx/_client.py#L678
    filterwarnings("ignore", category=DeprecationWarning, module="httpx.*")


@pytest.fixture(autouse=True)
def ignore_memory_object_resource_warnings():
    # @pierce - Fix a warning exposed in test_build_exception_on_get
    # from one of our underlying libraries
    # filterwarnings("ignore", category=ResourceWarning, module="anyio.*")
    filterwarnings("ignore", category=ResourceWarning)


@pytest.fixture(autouse=True)
def ignore_pluggy_warnings():
    filterwarnings(
        "ignore",
        category=pytest.PytestWarning,
        message=".*PluggyTeardownRaisedWarning.*",
    )


@pytest.fixture(autouse=True)
def clear_config_cache():
    unregister_config()


def _cleanup_main_thread_event_loop() -> None:
    """
    pytest-asyncio on Python 3.10 may leave the main thread's default loop attached to the
    event loop policy after async tests finish. Close that loop explicitly so pytest doesn't
    surface it later as an unraisable ResourceWarning for the loop's socketpair.
    """

    policy = asyncio.get_event_loop_policy()
    event_loop = getattr(getattr(policy, "_local", None), "_loop", None)
    if event_loop is None:
        return

    if not event_loop.is_closed():
        if event_loop.is_running():
            return
        event_loop.close()

    asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def cleanup_main_thread_event_loop():
    yield
    _cleanup_main_thread_event_loop()


@pytest.fixture(scope="session", autouse=True)
def cleanup_main_thread_event_loop_session():
    yield
    _cleanup_main_thread_event_loop()
