import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

import pytest
from fastapi import Request
from fastapi.responses import Response

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.app_manager import DevAppManager, package_path_to_module
from mountaineer.webservice import UvicornThread

AppPackageType = tuple[str, Path, Path]


@pytest.fixture(scope="module")
def tmp_app_package_dir():
    # The pytest bundled tmp_path only works for function
    # scoped fixtures
    with TemporaryDirectory() as tmp_path_raw:
        tmp_path = Path(tmp_path_raw)
        yield tmp_path


@pytest.fixture(scope="module")
def app_package(tmp_app_package_dir: Path):
    """
    A simple AppController, with a single component controller. Stub view
    files but no implemented views.

    """
    package_name = "test_package"
    package_path = Path(tmp_app_package_dir) / package_name
    package_path.mkdir()

    # Package init
    (package_path / "__init__.py").touch()

    # Controller
    controller_file = package_path / "test_controller.py"
    controller_file.write_text(
        (get_fixture_path("mock_webapp") / "simple_controller.py").read_text()
    )

    # Views
    (package_path / "views").mkdir()
    (package_path / "views" / "test.tsx").touch()

    # Make the path reachable only within this test scope
    sys.path.insert(0, str(tmp_app_package_dir))
    yield package_name, tmp_app_package_dir, controller_file
    sys.path.pop(0)


@pytest.fixture
def manager(app_package: AppPackageType) -> DevAppManager:
    package_name, _, _ = app_package
    return DevAppManager.from_webcontroller(  # type: ignore
        f"{package_name}.test_controller:test_controller",
        host="localhost",
        port=8000,
        live_reload_port=8001,
    )


def test_from_webcontroller(manager: DevAppManager, app_package: AppPackageType):
    package_name, _, _ = app_package
    assert manager.package == package_name
    assert manager.module_name == f"{package_name}.test_controller"
    assert manager.controller_name == "test_controller"
    assert manager.host == "localhost"
    assert manager.port == 8000
    assert manager.live_reload_port == 8001


def test_update_module(manager: DevAppManager, app_package: AppPackageType):
    _, _, controller_file = app_package

    # Modify the controller file
    with controller_file.open("a") as f:
        f.write("\ntest_controller.new_attribute = 'test'\n")

    manager.update_module()

    # Check if the new attribute is present
    assert hasattr(manager.app_controller, "new_attribute")
    assert manager.app_controller.new_attribute == "test"  # type: ignore


def test_restart_server(manager: DevAppManager):
    manager.restart_server()

    assert manager.webservice_thread is not None
    assert isinstance(manager.webservice_thread, UvicornThread)
    assert manager.webservice_thread.is_alive()

    # Give the server another second to boot
    sleep(1)
    manager.webservice_thread.stop()


def test_package_path_to_module(app_package: AppPackageType):
    package_name, temp_dir, _ = app_package
    file_path = temp_dir / package_name / "test_controller.py"
    module_name = package_path_to_module(package_name, file_path)

    assert module_name == f"{package_name}.test_controller"


def test_is_port_open(manager):
    # Test with a likely closed port
    assert not manager.is_port_open("localhost", 12345)

    # Start a simple server on a port
    import socket

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("localhost", 0))
    server_socket.listen(1)
    port = server_socket.getsockname()[1]

    # Test with the open port
    assert manager.is_port_open("localhost", port)

    # Close the server socket
    server_socket.close()


def test_mount_exceptions(manager: DevAppManager):
    # Check if the exception handler is mounted
    assert Exception in manager.app_controller.app.exception_handlers


@pytest.mark.asyncio
async def test_handle_dev_exception(manager: DevAppManager):
    # Create a mock request
    request = Request({"type": "http", "method": "GET"})

    # Create a test exception
    test_exception = ValueError("Test exception")

    # Call the exception handler
    response = await manager.handle_dev_exception(request, test_exception)

    # Check if the response contains the exception information
    assert isinstance(response, Response)
    assert isinstance(response.body, bytes)
    assert "ValueError: Test exception" in response.body.decode()
