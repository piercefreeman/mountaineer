from abc import ABC, abstractmethod
from os import environ
from pathlib import Path
from subprocess import Popen

import toml
from click import secho


class EnvironmentBase(ABC):
    """
    Base class for backend environments where we'll install the python
    dependencies in the remote project, so we avoid a system wide install.

    """

    def __init__(self):
        self.global_env = {
            "HOME": environ.get("HOME", ""),
            "MOUNTAINEER_LOG_LEVEL": environ.get("MOUNTAINEER_LOG_LEVEL", "WARNING"),
        }

    @abstractmethod
    def has_provider(self) -> bool:
        """
        Determines whether the environment can be executed locally
        by a given provider

        """
        pass

    @abstractmethod
    def install_project(self, project_path: Path) -> None:
        """
        Perform the installation of the python dependencies into
        the current project.

        """
        pass

    def insert_wheel(
        self, package_name: str, wheel_path: Path, project_path: Path
    ) -> None:
        """
        Update the project's dependency configuration to use a local wheel file instead
        of pulling from PyPI.

        :param package_name: Name of the package to replace
        :param wheel_path: Path to the wheel file to use
        :param project_path: Path to the project root
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

    @abstractmethod
    def run_command(self, command: list[str], path: Path) -> Popen:
        """
        Run a command in the environment

        """
        pass

    @abstractmethod
    def get_env_path(self, project_path: Path) -> str:
        """
        Get the environment path. Only valid after the installation
        process has completed. Otherwise will raise an error.

        """
        pass
