import importlib
import sys
from inspect import getmembers, isclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

import pytest
from fastapi import Request
from fastapi.responses import Response

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.app_manager import HotReloadManager
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
def manager(app_package: AppPackageType) -> HotReloadManager:
    package_name, _, _ = app_package
    return HotReloadManager.from_webcontroller(  # type: ignore
        f"{package_name}.test_controller:test_controller",
        host="localhost",
        port=8000,
        live_reload_port=8001,
    )


def test_from_webcontroller(manager: HotReloadManager, app_package: AppPackageType):
    package_name, _, _ = app_package
    assert manager.package == package_name
    assert manager.module_name == f"{package_name}.test_controller"
    assert manager.controller_name == "test_controller"
    assert manager.host == "localhost"
    assert manager.port == 8000
    assert manager.live_reload_port == 8001


def test_update_module(manager: HotReloadManager, app_package: AppPackageType):
    _, _, controller_file = app_package

    # Modify the controller file
    with controller_file.open("a") as f:
        f.write("\ntest_controller.new_attribute = 'test'\n")

    manager.update_module()

    # Check if the new attribute is present
    assert hasattr(manager.app_controller, "new_attribute")
    assert manager.app_controller.new_attribute == "test"  # type: ignore


def test_restart_server(manager: HotReloadManager):
    manager.restart_server()

    assert manager.webservice_thread is not None
    assert isinstance(manager.webservice_thread, UvicornThread)
    assert manager.webservice_thread.is_alive()

    # Give the server another second to boot
    sleep(1)
    manager.webservice_thread.stop()


def test_objects_in_module(manager: HotReloadManager, app_package: AppPackageType):
    package_name, _, _ = app_package
    module = importlib.import_module(f"{package_name}.test_controller")

    objects = manager.objects_in_module(module)

    # Only counts the TestController class, not the test_controller object
    assert len(objects) == 1


def test_package_path_to_module(manager: HotReloadManager, app_package: AppPackageType):
    package_name, temp_dir, _ = app_package
    file_path = temp_dir / package_name / "test_controller.py"
    module_name = manager.package_path_to_module(file_path)

    assert module_name == f"{package_name}.test_controller"


def test_module_to_package_path(manager: HotReloadManager, app_package: AppPackageType):
    package_name, temp_dir, _ = app_package
    module_name = manager.module_to_package_path(f"{package_name}.test_controller")

    assert module_name == temp_dir / package_name / "test_controller.py"


def test_get_submodules_with_objects(
    manager: HotReloadManager, app_package: AppPackageType
):
    package_name, _, _ = app_package
    root_module = importlib.import_module(package_name)
    objects = set(
        manager.objects_in_module(
            importlib.import_module(f"{package_name}.test_controller")
        )
    )

    submodules = list(manager.get_submodules_with_objects(root_module, objects))

    assert len(submodules) == 1
    assert submodules[0].__name__ == f"{package_name}.test_controller"


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


def test_mount_exceptions(manager: HotReloadManager):
    # Check if the exception handler is mounted
    assert Exception in manager.app_controller.app.exception_handlers


@pytest.mark.asyncio
async def test_handle_dev_exception(manager: HotReloadManager):
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


@pytest.mark.parametrize(
    "superclass_names, expected_subclasses",
    [
        # Our function only finds direct subclasses
        (["SuperClass1"], ["SubClass1"]),
        (["SuperClass2"], ["SubClass2"]),
        (["SuperClass1", "SuperClass2"], ["SubClass1", "SubClass2"]),
        (["SubClass1"], ["SubSubClass"]),
        (["UnrelatedClass"], []),
        (["SuperClass1", "UnrelatedClass"], ["SubClass1"]),
    ],
)
def test_get_objects_with_superclasses(
    superclass_names: list[str],
    expected_subclasses: list[str],
    manager: HotReloadManager,
    app_package: AppPackageType,
):
    package_name, package_root, _ = app_package

    # Create a simple class hierarchy
    class_definitions = [
        ("simple_classes_1.py", "simple_classes_1"),
        ("simple_classes_2.py", "simple_classes_2"),
    ]
    for original_path, module_name in class_definitions:
        controller_path = package_root / package_name / f"{module_name}.py"
        controller_path.write_text(
            (get_fixture_path("mock_webapp") / original_path).read_text()
        )

    superclass_ids: set[int] = set()

    for _, module_name in class_definitions:
        class_module = importlib.import_module(f"{package_name}.{module_name}")

        # Sniff out the IDs for different classes
        module_classes = getmembers(class_module, isclass)
        for name, cls in module_classes:
            if name in superclass_names:
                superclass_ids.add(id(cls))

    assert len(superclass_ids) == len(superclass_names)

    subclasses = []
    for _, module_name in class_definitions:
        class_module = importlib.import_module(f"{package_name}.{module_name}")

        subclasses += manager.get_modified_subclass_modules(
            class_module, superclass_ids
        )

    assert {subclass for _, subclass in subclasses} == set(expected_subclasses)
