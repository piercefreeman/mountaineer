import sys
import textwrap
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from typing import Any

import pytest

from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.messages import (
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
def test_package_dir(tmp_path: Path, request) -> tuple[Path, str]:
    """
    Create test package structure with unique name per test.
    Returns (package_dir, package_name)
    """
    test_name = request.node.name.replace("test_", "")
    pkg_name = f"test_package_{test_name}".replace("[", "_").replace("]", "_")

    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()

    # Create views directory for AppController
    views_dir = pkg_dir / "views"
    views_dir.mkdir()

    # Create basic app structure
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "app.py").write_text(
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

    # Make it immediately importable
    sys.path.insert(0, str(pkg_dir.parent))
    sys.path.insert(0, str(pkg_dir))

    return pkg_dir, pkg_name


@pytest.fixture
def mock_message_broker():
    """Create a mock message broker for testing"""

    class MockMessageBroker:
        def __init__(self):
            self.message_queue = Queue()  # type: ignore
            self.response_queue = Queue()  # type: ignore

    return MockMessageBroker()


@pytest.fixture
def isolated_context(test_package_dir, mock_message_broker):
    """Create an IsolatedAppContext instance for testing"""
    pkg_dir, pkg_name = test_package_dir
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
        if context.webservice_thread:
            context.webservice_thread.stop()


@pytest.mark.asyncio
async def test_handle_bootstrap(isolated_context):
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
async def test_handle_restart_server(isolated_context):
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
async def test_handle_build_use_server(isolated_context):
    """Test use_server build handling"""
    # First bootstrap to initialize
    await isolated_context.handle_bootstrap()

    # Mock the build_use_server method
    async def mock_build():
        pass

    isolated_context.js_compiler.build_use_server = mock_build

    response = await isolated_context.handle_build_use_server()
    assert isinstance(response, SuccessResponse)


@pytest.mark.asyncio
async def test_handle_js_build(isolated_context):
    """Test JS build handling"""
    # First bootstrap to initialize
    await isolated_context.handle_bootstrap()

    # Mock the run_builder_plugins method
    async def mock_build(*args, **kwargs):
        pass

    isolated_context.app_compiler.run_builder_plugins = mock_build

    response = await isolated_context.handle_js_build([Path("test.js")])
    assert isinstance(response, SuccessResponse)


def test_run_message_loop(isolated_context):
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


def test_error_handling(isolated_context):
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
