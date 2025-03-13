import shutil
import subprocess
import sys
from json import dump as json_dump
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mountaineer.__tests__.fixtures import get_fixture_path

# from mountaineer.development.manager import DevAppManager

AppPackageType = tuple[str, Path, Path]


def create_package_json(views_path: Path) -> None:
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

    with open(views_path / "package.json", "w") as f:
        json_dump(package_json, f, indent=2)


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
def simple_package_dependencies():
    """
    Cache the results of create_package_json() system-wide so we don't have to
    re-install node modules for each test that needs to execute against our
    Javascript environment.

    """
    # The tmp_path fixture is scoped to the individual test function level, so we need
    # a manual cache for module scoped fixtures
    with TemporaryDirectory() as tmp_path_raw:
        tmp_path = Path(tmp_path_raw)

        # Create our standard package.json in this path
        create_package_json(tmp_path)

        # Install dependencies
        setup_npm_environment(tmp_path)

        yield tmp_path / "node_modules"


@pytest.fixture
def isolated_package_dir(
    tmp_path: Path,
    simple_package_dependencies: Path,
    request,
):
    """
    Create test package structure with unique name per test so we allow
    client functions to modify their files without adverse affects on other tests.

    Provides:
    - An isolated python package directory
    - A views directory with node_modules copied in
    - A package.json in the views directory

    """
    test_name = request.node.name.replace("test_", "")
    pkg_name = f"test_package_{test_name}".replace("[", "_").replace("]", "_")

    # Create the python code directory
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()

    # Create a views directory
    views_dir = pkg_dir / "views"
    views_dir.mkdir()

    # Create a package.json in the views directory
    create_package_json(views_dir)
    shutil.copytree(simple_package_dependencies, views_dir / "node_modules")

    # Make the path reachable only within this test scope
    sys.path.insert(0, str(tmp_path))
    try:
        yield pkg_dir, pkg_name
    finally:
        sys.path.pop(0)


@pytest.fixture
def app_package(isolated_package_dir: tuple[Path, str]) -> AppPackageType:
    """
    A simple AppController, with a single component controller. Sets up a complete
    React environment with necessary dependencies.

    """
    package_path, package_name = isolated_package_dir

    # Package init
    (package_path / "__init__.py").touch()

    # Views directory with TypeScript React component
    views_dir = package_path / "views"

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

    return package_name, package_path, controller_file
