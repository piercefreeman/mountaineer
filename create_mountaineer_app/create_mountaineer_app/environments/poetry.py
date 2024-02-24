import subprocess
from os import environ
from pathlib import Path
from tempfile import NamedTemporaryFile

from click import secho

from create_mountaineer_app.environments.base import EnvironmentBase


class PoetryEnvironment(EnvironmentBase):
    """
    Supports a Poetry environment backend for our webapp.

    """

    def __init__(self):
        # While running our script within poetry, poetry will inject a POETRY_ACTIVE
        # environment variable. This will cause poetry to only install within the
        # current directory. We want to avoid tthis since the path we're given could be
        # anywhere in the system. We'll limit the scope of the new poetry subprocess to
        # only the PATH environment variable.
        self.limited_scope_env = {
            "PATH": environ["PATH"],
        }

    def has_provider(self):
        try:
            # Attempt to get the version of poetry to check if it's installed
            subprocess.run(
                ["poetry", "--version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except subprocess.CalledProcessError:
            # Poetry is installed but there might be a problem with it
            return True
        except FileNotFoundError:
            # Poetry is not installed
            return False

    def install_project(self, project_path: Path):
        subprocess.run(
            ["poetry", "install"],
            check=True,
            cwd=str(project_path),
            env=self.limited_scope_env,
        )

        # Retrieve the location of the new virtualenv
        result = subprocess.run(
            ["poetry", "env", "info", "--path"],
            check=True,
            capture_output=True,
            cwd=str(project_path),
            env=self.limited_scope_env,
        )

        secho(f"Poetry venv created: {result.stdout.decode().strip()}", fg="green")

    def install_provider(self):
        """
        Attempt to install poetry via the official installation script:
        > curl -sSL https://install.python-poetry.org | python3 -

        Raises an exception if the installation fails.

        """
        with NamedTemporaryFile(delete=False) as tmp_file:
            subprocess.run(
                [
                    "curl",
                    "-sSL",
                    "https://install.python-poetry.org",
                    "-o",
                    tmp_file.name,
                ],
                check=True,
            )
            subprocess.run(["python3", tmp_file.name], check=True)

        secho("Poetry installed successfully.", fg="green")

    def run_command(self, command: list[str], path: Path):
        return subprocess.Popen(
            ["poetry", "run", *command],
            cwd=path,
            env=self.limited_scope_env,
        )
