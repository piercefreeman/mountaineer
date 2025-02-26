from mountaineer.__tests__.development.conftest import AppPackageType
from mountaineer.development.packages import package_path_to_module


def test_package_path_to_module(app_package: AppPackageType):
    package_name, package_path, _ = app_package
    file_path = package_path / "test_controller.py"
    module_name = package_path_to_module(package_name, file_path)

    assert module_name == f"{package_name}.test_controller"
