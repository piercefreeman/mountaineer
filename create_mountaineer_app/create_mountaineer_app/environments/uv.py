import subprocess
from os import environ
from pathlib import Path

from click import secho

from create_mountaineer_app.environments.base import EnvironmentBase


class UvEnvironment(EnvironmentBase):
    """
    Use uv as the Python package installer and environment manager.
    uv is a modern, fast package installer and resolver written in Rust.
    """

    def __init__(self, venv_name: str = ".venv"):
        super().__init__()
        self.venv_name = venv_name
        self.limited_scope_env = {
            "PATH": environ["PATH"],
            **self.global_env,
        }

    def has_provider(self) -> bool:
        try:
            # Attempt to get the version of uv to check if it's installed
            subprocess.run(
                ["uv", "--version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except subprocess.CalledProcessError:
            # uv is installed but there might be a problem with it
            return True
        except FileNotFoundError:
            # uv is not installed
            return False

    def install_project(self, project_path: Path) -> None:
        # Create a virtual environment using uv
        venv_path = project_path / self.venv_name
        subprocess.run(
            ["uv", "venv", str(venv_path)],
            check=True,
            cwd=str(project_path),
            env=self.limited_scope_env,
        )

        secho(f"Virtual environment created at: {venv_path}", fg="green")

        # Install packages using uv pip
        subprocess.run(
            ["uv", "pip", "install", "-e", "."],
            check=True,
            cwd=project_path,
            env={
                "VIRTUAL_ENV": str(venv_path),
                "PATH": f"{venv_path}/bin:{environ['PATH']}",
                **self.global_env,
            },
        )

        secho("Packages installed.", fg="green")

    def install_provider(self) -> None:
        """
        Install uv using the official installation method:
        > curl -LsSf https://astral.sh/uv/install.sh | sh

        Raises an exception if the installation fails.
        """
        subprocess.run(
            ["curl", "-LsSf", "https://astral.sh/uv/install.sh", "|", "sh"],
            check=True,
            shell=True,  # Required for pipe operation
        )
        secho("uv installed successfully.", fg="green")

    def run_command(self, command: list[str], path: Path):
        venv_path = path / self.venv_name
        if not venv_path.exists():
            raise ValueError(f"Virtual environment not found at: {venv_path}")

        return subprocess.Popen(
            command,
            cwd=path,
            env={
                "VIRTUAL_ENV": str(venv_path),
                "PATH": f"{venv_path}/bin:{environ['PATH']}",
                **self.global_env,
            },
        )

    def get_env_path(self, project_path: Path) -> str:
        venv_path = project_path / self.venv_name
        if not venv_path.exists():
            raise ValueError(f"Virtual environment not found at: {venv_path}")

        return str(venv_path)
