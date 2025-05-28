from pathlib import Path
from textwrap import dedent

from create_mountaineer_app.environments.base import EnvironmentBase
from create_mountaineer_app.environments.uv import UvEnvironment


def create_test_pyproject_toml(project_path: Path) -> None:
    """Create a synthetic pyproject.toml with dev dependencies for testing."""
    pyproject_content = dedent("""
        [build-system]
        requires = ["setuptools>=61.0", "wheel"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "test_project"
        version = "0.1.0"
        description = "Test project for dev dependency installation"
        requires-python = ">=3.8"
        dependencies = [
            "requests>=2.25.0",
        ]

        [dependency-groups]
        dev = [
            "pytest>=7.0.0",
            "black>=22.0.0",
        ]

        [project.optional-dependencies]
        dev = [
            "pytest>=7.0.0",
            "black>=22.0.0",
        ]

        [tool.poetry.group.dev.dependencies]
        pytest = ">=7.0.0"
        black = ">=22.0.0"
    """).strip()

    pyproject_path = project_path / "pyproject.toml"
    pyproject_path.write_text(pyproject_content)

    # Also create a minimal setup.py for setuptools compatibility
    setup_py_content = dedent("""
        from setuptools import setup, find_packages
        
        setup(
            name="test_project",
            packages=find_packages(),
        )
    """).strip()

    setup_py_path = project_path / "setup.py"
    setup_py_path.write_text(setup_py_content)

    # Create an empty package directory
    package_dir = project_path / "test_project"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").touch()


def check_package_installed(
    env: EnvironmentBase, project_path: Path, package_name: str
) -> bool:
    """Check if a package is installed using the environment's run_command method."""
    try:
        # Use pip show to check if package is installed
        command = ["pip", "show", package_name]
        if isinstance(env, UvEnvironment):
            # Use the uv shim to run pip
            command = ["uv", "pip", "show", package_name]
        process = env.run_command(command, project_path)
        process.wait()
        return process.returncode == 0
    except Exception:
        return False
