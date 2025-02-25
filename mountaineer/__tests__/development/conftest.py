import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mountaineer.__tests__.fixtures import get_fixture_path
from mountaineer.development.manager import DevAppManager

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
