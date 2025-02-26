import textwrap
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import pytest_asyncio

from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.messages import (
    AsyncMessageBroker,
    BootupMessage,
    BuildUseServerMessage,
    ErrorResponse,
    ShutdownMessage,
    SuccessResponse,
)


@dataclass
class MockControllerDefinition:
    controller: Any


@pytest.fixture
def simple_webapp(isolated_package_dir: tuple[Path, str]) -> tuple[Path, str]:
    """
    Create test package structure with unique name per test.
    Returns (package_dir, package_name)
    """
    package_path, package_name = isolated_package_dir

    # Create basic app structure
    (package_path / "__init__.py").write_text("")
    (package_path / "app.py").write_text(
        textwrap.dedent(
            """
            from pathlib import Path
            from mountaineer.app import AppController

            app = AppController(
                view_root=Path(__file__).parent / "views"
            )

            @app.app.get("/")
            def root():
                return {"message": "Hello World"}
            """
        )
    )

    return package_path, package_name


@pytest.fixture
def mock_message_broker():
    """Create a mock message broker for testing"""

    class MockMessageBroker:
        def __init__(self):
            self.message_queue = Queue()  # type: ignore
            self.response_queue = Queue()  # type: ignore

    return cast(AsyncMessageBroker, MockMessageBroker())


@pytest_asyncio.fixture
async def isolated_context(
    simple_webapp: tuple[Path, str], mock_message_broker: AsyncMessageBroker
):
    """Create an IsolatedAppContext instance for testing"""
    pkg_dir, pkg_name = simple_webapp
    context = IsolatedAppContext(
        package=pkg_name,
        module_name=f"{pkg_name}.app",
        controller_name="app",
        host="127.0.0.1",
        port=5030,
        live_reload_port=None,
        message_broker=mock_message_broker,
    )
    try:
        yield context
    finally:
        # Send it a shutdown message
        await context.handle_shutdown()


@pytest.mark.asyncio
async def test_handle_bootstrap(isolated_context: IsolatedAppContext):
    """Test bootstrap message handling"""
    response = await isolated_context.handle_bootstrap()
    assert isinstance(response, SuccessResponse)
    assert isolated_context.app_controller is not None
    assert isolated_context.js_compiler is not None
    assert isolated_context.app_compiler is not None
    assert isolated_context.hot_reloader is not None
    assert isolated_context.webservice_thread is not None
    assert isolated_context.webservice_thread.is_alive()


@pytest.mark.asyncio
async def test_handle_restart_server(isolated_context: IsolatedAppContext):
    """Test server restart handling"""
    # First bootstrap to initialize
    await isolated_context.handle_bootstrap()
    initial_thread = isolated_context.webservice_thread

    # Then restart
    response = await isolated_context.handle_restart_server()
    assert isinstance(response, SuccessResponse)
    assert isolated_context.webservice_thread is not None
    assert isolated_context.webservice_thread != initial_thread
    assert isolated_context.webservice_thread.is_alive()


@pytest.mark.asyncio
async def test_handle_build_use_server(isolated_context: IsolatedAppContext):
    """Test use_server build handling"""
    assert isolated_context.js_compiler is not None

    # First bootstrap to initialize
    await isolated_context.handle_bootstrap()

    # Mock the build_use_server method
    async def mock_build():
        pass

    with patch.object(isolated_context.js_compiler, "build_use_server", mock_build):
        response = await isolated_context.handle_build_use_server()
        assert isinstance(response, SuccessResponse)


@pytest.mark.asyncio
async def test_handle_js_build(isolated_context: IsolatedAppContext):
    """Test JS build handling"""
    assert isolated_context.app_compiler is not None

    # First bootstrap to initialize
    await isolated_context.handle_bootstrap()

    # Mock the run_builder_plugins method
    async def mock_build(*args, **kwargs):
        pass

    with patch.object(isolated_context.app_compiler, "run_builder_plugins", mock_build):
        response = await isolated_context.handle_js_build([Path("test.js")])
        assert isinstance(response, SuccessResponse)


def test_run_message_loop(isolated_context: IsolatedAppContext):
    """Test the main message loop"""
    # Queue up some messages
    isolated_context.message_broker.message_queue.put((1, BootupMessage()))
    isolated_context.message_broker.message_queue.put((2, ShutdownMessage()))

    # Run the process
    isolated_context.run()

    # Verify responses
    message_id, response = isolated_context.message_broker.response_queue.get()
    assert message_id == 1
    assert isinstance(response, SuccessResponse)

    message_id, response = isolated_context.message_broker.response_queue.get()
    assert message_id == 2
    assert isinstance(response, SuccessResponse)


def test_error_handling(isolated_context: IsolatedAppContext):
    """Test error handling in message loop"""
    # Queue up a message that will cause an error
    isolated_context.message_broker.message_queue.put(
        (1, BuildUseServerMessage())  # Will fail because js_compiler isn't initialized
    )
    isolated_context.message_broker.message_queue.put((2, ShutdownMessage()))

    # Run the process
    isolated_context.run()

    # Verify error response
    message_id, response = isolated_context.message_broker.response_queue.get()
    assert message_id == 1
    assert isinstance(response, ErrorResponse)
    assert "JS compiler not initialized" in response.exception
