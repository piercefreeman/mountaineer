
from mountaineer.__tests__.development.conftest import AppPackageType
from mountaineer.development.manager import DevAppManager


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


def test_is_port_open(manager: DevAppManager):
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
