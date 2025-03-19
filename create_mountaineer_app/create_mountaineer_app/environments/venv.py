import subprocess
from os import environ
from pathlib import Path
from shutil import which

import toml
from click import secho

from create_mountaineer_app.environments.base import EnvironmentBase


class VEnvEnvironment(EnvironmentBase):
    """
    Use the python bundled venv module to create a virtual environment
    for the current project.

    """

    def __init__(self, venv_name: str = "venv"):
        super().__init__()
        self.venv_name = venv_name

    def has_provider(self):
        return which("python3") is not None

    def insert_wheel(
        self, package_name: str, wheel_path: Path, project_path: Path
    ) -> None:
        """
        Update the pyproject.toml to use a local wheel file instead of pulling from PyPI.
        """
        pyproject_path = project_path / "pyproject.toml"
        if not pyproject_path.exists():
            raise ValueError("pyproject.toml not found")

        # Read the current pyproject.toml
        with open(pyproject_path) as f:
            pyproject = toml.load(f)

        # Update the dependency to point to the wheel file
        if "project" not in pyproject:
            pyproject["project"] = {}
        if "dependencies" not in pyproject["project"]:
            pyproject["project"]["dependencies"] = []

        # Remove any existing dependency for this package
        pyproject["project"]["dependencies"] = [
            dep
            for dep in pyproject["project"]["dependencies"]
            if not (isinstance(dep, str) and dep.startswith(package_name))
        ]

        # Add the wheel file as a dependency using PEP 508 format
        # Format: package_name @ file:///absolute/path/to/wheel
        wheel_path_str = wheel_path.resolve().as_uri()
        pyproject["project"]["dependencies"].append(
            f"{package_name} @ {wheel_path_str}"
        )

        secho(
            f"Updated pyproject.toml to use local wheel: {pyproject['project']['dependencies']}",
            fg="blue",
        )

        # Write the updated pyproject.toml
        with open(pyproject_path, "w") as f:
            toml.dump(pyproject, f)

    def install_project(self, project_path: Path):
        # Create a virtual environment
        venv_path = project_path / self.venv_name
        subprocess.run(["python3", "-m", "venv", str(venv_path)], check=True)

        secho(f"Virtual environment created at: {venv_path}", fg="green")

        # Install packages using pip
        subprocess.run(
            [str(venv_path / "bin" / "pip"), "install", "-e", "."],
            check=True,
            cwd=project_path,
            # Install within our virtualenv
            env={"PATH": f"{venv_path}/bin:{environ['PATH']}", **self.global_env},
        )

        secho("Packages installed.", fg="green")

    def run_command(self, command: list[str], path: Path):
        venv_path = path / self.venv_name
        if not venv_path.exists():
            raise ValueError(f"Virtual environment not found at: {venv_path}")

        return subprocess.Popen(
            command,
            cwd=path,
            env={"PATH": f"{venv_path}/bin:{environ['PATH']}", **self.global_env},
        )

    def get_env_path(self, project_path: Path) -> str:
        venv_path = project_path / self.venv_name
        if not venv_path.exists():
            raise ValueError(f"Virtual environment not found at: {venv_path}")

        return str(venv_path)
