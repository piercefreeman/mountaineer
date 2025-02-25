from time import sleep

import pytest
from fastapi import Request
from fastapi.responses import Response

from mountaineer.__tests__.development.conftest import AppPackageType
from mountaineer.development.manager import DevAppManager
from mountaineer.webservice import UvicornThread


def test_from_webcontroller(manager: DevAppManager, app_package: AppPackageType):
    package_name, _, _ = app_package
    assert manager.package == package_name
    assert manager.module_name == f"{package_name}.test_controller"
    assert manager.controller_name == "test_controller"
    assert manager.host == "localhost"
    assert manager.port == 8000
    assert manager.live_reload_port == 8001


def test_npm_setup(app_package: AppPackageType):
    """Test that npm dependencies were installed correctly."""
    _, tmp_dir, _ = app_package
    package_path = tmp_dir / "test_package"

    # Check that node_modules exists
    assert (package_path / "views" / "node_modules").exists()

    # Check that React was installed
    assert (package_path / "views" / "node_modules" / "react").exists()
    assert (package_path / "views" / "node_modules" / "react-dom").exists()


def test_update_module(manager: DevAppManager, app_package: AppPackageType):
    _, _, controller_file = app_package

    # Make sure we are able to pull an app controller from the mounted
    # system module state
    manager.app_controller = None  # type: ignore

    manager.update_module()

    assert manager.app_controller is not None


def test_restart_server(manager: DevAppManager):
    manager.restart_server()

    assert manager.webservice_thread is not None
    assert isinstance(manager.webservice_thread, UvicornThread)
    assert manager.webservice_thread.is_alive()

    # Give the server another second to boot
    sleep(1)
    manager.webservice_thread.stop()


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
    await manager.js_compiler.build_all()
    await manager.app_compiler.run_builder_plugins()

    # Create a mock request
    request = Request({"type": "http", "method": "GET"})

    # Create a test exception
    test_exception: Exception | None = None
    try:
        raise ValueError("Test exception")
    except Exception as e:
        test_exception = e

    assert test_exception

    # Force un-mount so we can mount again
    manager.app_controller.controllers = [
        controller
        for controller in manager.app_controller.controllers
        if controller.controller.__class__.__name__
        != manager.exception_controller.__class__.__name__
    ]
    manager.app_controller._controller_names.remove(
        manager.exception_controller.__class__.__name__
    )

    # Call the exception handler
    manager.mount_exceptions(manager.app_controller)
    response = await manager.handle_dev_exception(request, test_exception)

    # Check if the response contains the exception information
    assert isinstance(response, Response)
    assert isinstance(response.body, bytes)
    assert "ValueError: Test exception" in response.body.decode()
