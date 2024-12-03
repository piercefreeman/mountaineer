import json
import subprocess
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


def create_package_json(package_path: Path) -> None:
    """
    Create a package.json file with necessary React dependencies.

    """
    package_json = {
        "name": "test-package",
        "version": "1.0.0",
        "description": "Test package for mountaineer",
        "main": "index.js",
        "scripts": {"test": 'echo "Error: no test specified" && exit 1'},
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
        "devDependencies": {
            "@types/react": "^18.2.0",
            "@types/react-dom": "^18.2.0",
            "typescript": "^5.0.0",
        },
    }

    with open(package_path / "package.json", "w") as f:
        json.dump(package_json, f, indent=2)


def setup_npm_environment(package_path: Path) -> None:
    """
    Install npm dependencies in the package directory.

    """
    subprocess.run(
        ["npm", "install"],
        cwd=package_path,
        check=True,
        capture_output=True,
        text=True,
    )


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
    A simple AppController, with a single component controller. Sets up a complete
    React environment with necessary dependencies.

    """
    package_name = "test_package"
    package_path = Path(tmp_app_package_dir) / package_name
    package_path.mkdir()

    # Package init
    (package_path / "__init__.py").touch()

    # Views directory with TypeScript React component
    views_dir = package_path / "views"
    views_dir.mkdir()

    # Set up package.json and install dependencies
    create_package_json(views_dir)
    setup_npm_environment(views_dir)

    # Controller
    controller_file = package_path / "test_controller.py"
    controller_file.write_text(
        (get_fixture_path("mock_webapp") / "simple_controller.py").read_text()
    )

    (views_dir / "test_controller").mkdir()
    (views_dir / "test_controller" / "page.tsx").write_text("")

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
