from pathlib import Path

import pytest

from create_mountaineer_app.__tests__.environments.common import (
    check_package_installed,
    create_test_pyproject_toml,
)
from create_mountaineer_app.environments.venv import VEnvEnvironment


def test_venv_installs_dev_dependencies(tmp_path: Path) -> None:
    """Test that venv environment installs dev dependencies correctly."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    # Create synthetic pyproject.toml with dev dependencies
    create_test_pyproject_toml(project_path)

    # Install the project with dev dependencies
    venv_env = VEnvEnvironment()
    venv_env.install_project(project_path)

    # Verify main dependency is installed
    assert check_package_installed(venv_env, project_path, "requests"), (
        "Main dependency 'requests' should be installed"
    )

    # Verify dev dependencies are installed
    assert check_package_installed(venv_env, project_path, "pytest"), (
        "Dev dependency 'pytest' should be installed"
    )
    assert check_package_installed(venv_env, project_path, "black"), (
        "Dev dependency 'black' should be installed"
    )


@pytest.mark.skipif(
    not VEnvEnvironment().has_provider(), reason="Python3 venv not available"
)
def test_venv_dev_deps_integration(tmp_path: Path) -> None:
    """Integration test to verify dev dependencies work in venv environment."""
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    create_test_pyproject_toml(project_path)

    venv_env = VEnvEnvironment()
    venv_env.install_project(project_path)

    # Try to run pytest (a dev dependency) through the venv using run_command
    process = venv_env.run_command(["pytest", "--version"], project_path)
    process.wait()

    assert process.returncode == 0, (
        f"venv should be able to run pytest. Return code: {process.returncode}"
    )
