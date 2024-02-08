from abc import ABC, abstractmethod
from pathlib import Path
from subprocess import Popen


class EnvironmentBase(ABC):
    """
    Base class for backend environments where we'll install the python
    dependencies in the remote project, so we avoid a system wide install.

    """

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

    @abstractmethod
    def run_command(self, command: list[str], path: Path) -> Popen:
        """
        Run a command in the environment

        """
        pass
