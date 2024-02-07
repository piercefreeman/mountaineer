from abc import ABC, abstractmethod
from pathlib import Path


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
    async def run_command(self, command: list[str], path: Path) -> tuple[str, str]:
        """
        Run a command in the environment

        """
        pass
