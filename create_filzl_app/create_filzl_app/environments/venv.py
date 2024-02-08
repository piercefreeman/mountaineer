import asyncio
import subprocess
from os import environ
from pathlib import Path
from shutil import which

from click import secho

from create_filzl_app.environments.base import EnvironmentBase


class VEnvEnvironment(EnvironmentBase):
    """
    Use the python bundled venv module to create a virtual environment
    for the current project.

    """

    def __init__(self, venv_name: str = "venv"):
        self.venv_name = venv_name

    def has_provider(self):
        return which("python3") is not None

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
            env={"PATH": f"{venv_path}/bin:{environ['PATH']}"},
        )

        secho("Packages installed.", fg="green")

    async def run_command(self, command: list[str], path: Path):
        venv_path = path / self.venv_name
        if not venv_path.exists():
            raise ValueError(f"Virtual environment not found at: {venv_path}")

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=path,
            env={"PATH": f"{venv_path}/bin:{environ['PATH']}"},
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode or -1, command, stdout, stderr
            )
