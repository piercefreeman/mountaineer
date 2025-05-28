from pathlib import Path

import pytest

from create_mountaineer_app.__tests__.environments.common import (
    check_package_installed,
    create_test_pyproject_toml,
)
from create_mountaineer_app.environments.uv import UvEnvironment


def test_uv_installs_dev_dependencies(tmp_path: Path) -> None:
    """Test that uv environment installs dev dependencies correctly."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    # Create synthetic pyproject.toml with dev dependencies
    create_test_pyproject_toml(project_path)

    # Install the project with dev dependencies
    uv_env = UvEnvironment()
    uv_env.install_project(project_path)

    # Verify main dependency is installed
    assert check_package_installed(uv_env, project_path, "requests"), (
        "Main dependency 'requests' should be installed"
    )

    # Verify dev dependencies are installed
    assert check_package_installed(uv_env, project_path, "pytest"), (
        "Dev dependency 'pytest' should be installed"
    )
    assert check_package_installed(uv_env, project_path, "black"), (
        "Dev dependency 'black' should be installed"
    )


@pytest.mark.skipif(not UvEnvironment().has_provider(), reason="uv not available")
def test_uv_dev_deps_integration(tmp_path: Path) -> None:
    """Integration test to verify dev dependencies work in uv environment."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    create_test_pyproject_toml(project_path)

    uv_env = UvEnvironment()
    uv_env.install_project(project_path)

    # Try to run pytest (a dev dependency) through the uv environment using run_command
    process = uv_env.run_command(["pytest", "--version"], project_path)
    process.wait()

    assert process.returncode == 0, (
        f"uv should be able to run pytest. Return code: {process.returncode}"
    )
