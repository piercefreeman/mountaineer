import subprocess
from pathlib import Path

import pytest

from create_mountaineer_app.__tests__.environments.common import (
    check_package_installed,
    create_test_pyproject_toml,
)
from create_mountaineer_app.environments.poetry import PoetryEnvironment


def test_poetry_installs_dev_dependencies(tmp_path: Path) -> None:
    """Test that Poetry environment installs dev dependencies correctly."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    # Create synthetic pyproject.toml with dev dependencies
    create_test_pyproject_toml(project_path)

    # Initialize poetry project
    poetry_env = PoetryEnvironment()

    # Install the project with dev dependencies
    poetry_env.install_project(project_path)

    # Verify main dependency is installed
    assert check_package_installed(poetry_env, project_path, "requests"), (
        "Main dependency 'requests' should be installed"
    )

    # Verify dev dependencies are installed
    assert check_package_installed(poetry_env, project_path, "pytest"), (
        "Dev dependency 'pytest' should be installed"
    )
    assert check_package_installed(poetry_env, project_path, "black"), (
        "Dev dependency 'black' should be installed"
    )


@pytest.mark.skipif(
    not PoetryEnvironment().has_provider(), reason="Poetry not available"
)
def test_poetry_dev_deps_integration(tmp_path: Path) -> None:
    """Integration test to verify dev dependencies work in Poetry environment."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    create_test_pyproject_toml(project_path)

    poetry_env = PoetryEnvironment()
    poetry_env.install_project(project_path)

    # Try to run pytest (a dev dependency) through poetry
    result = subprocess.run(
        ["poetry", "run", "pytest", "--version"],
        cwd=project_path,
        capture_output=True,
        text=True,
        env=poetry_env.limited_scope_env,
    )

    assert result.returncode == 0, (
        f"Poetry should be able to run pytest. Error: {result.stderr}"
    )
    assert "pytest" in result.stdout, "pytest version should be displayed"
