from unittest.mock import patch
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
def ignore_websockets_deprecation_warnings():
    # Ignore websockets.legacy deprecation warnings until uvicorn updates
    filterwarnings("ignore", category=DeprecationWarning, module="websockets.legacy.*")
    # Also ignore any thread exceptions related to these warnings
    filterwarnings(
        "ignore",
        category=pytest.PytestUnhandledThreadExceptionWarning,
        message=".*websockets.legacy is deprecated.*",
    )


@pytest.fixture(autouse=True)
def mock_rich_console():
    """
    Mock the Rich console during tests to prevent "Only one live display may be active at once" errors.
    This replaces the console's set_live method with a version that allows multiple live displays.
    """
    from rich.console import Console

    original_set_live = Console.set_live

    def patched_set_live(self, live):
        # If there's already a live display, just replace it without raising an error
        if hasattr(self, "_live") and self._live is not None:
            self._live = live
            return
        # Otherwise, use the original method
        original_set_live(self, live)

    with patch.object(Console, "set_live", patched_set_live):
        yield


@pytest.fixture(autouse=True)
def clear_config_cache():
    unregister_config()
