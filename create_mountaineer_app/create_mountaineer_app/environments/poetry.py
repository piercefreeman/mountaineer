import subprocess
from os import environ, pathsep
from pathlib import Path
from tempfile import NamedTemporaryFile

from click import secho

from create_mountaineer_app.environments.base import EnvironmentBase


class PoetryEnvironment(EnvironmentBase):
    """
    Supports a Poetry environment backend for our webapp.

    """

    def __init__(self):
        super().__init__()

        # While running our script within poetry, poetry will inject a POETRY_ACTIVE
        # environment variable. This will cause poetry to only install within the
        # current directory. We want to avoid this since the path we're given could be
        # anywhere in the system. We'll limit the scope of the new poetry subprocess to
        # only the PATH environment variable.
        self.limited_scope_env = {
            "PATH": environ["PATH"],
            **self.global_env,
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
        env_path = self.get_env_path(project_path)
        secho(f"Poetry venv created: {env_path}", fg="green")

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

    def add_poetry_to_path(self) -> None:
        """
        Mount poetry in the current terminal session and the user's shell profile.

        """
        directory = str(Path.home() / ".local" / "bin")

        shell = environ.get("SHELL")
        if not shell:
            secho("Could not detect the shell environment.", fg="red")
            raise Exception("Shell environment detection failed.")

        profile_path: Path
        if "bash" in shell:
            profile_path = Path("~/.bashrc")
        elif "zsh" in shell:
            profile_path = Path("~/.zshrc")
        else:
            secho(f"Unsupported shell: {shell}", fg="red")
            raise Exception("Unsupported shell.")

        # Expand the user's home directory and prepare the command to modify the profile file.
        profile_abs_path = profile_path.expanduser()
        path_command = f'export PATH="$PATH:{directory}"\n'

        # Check if the path is already in the file to avoid duplication
        with open(profile_abs_path, "r+") as profile:
            if path_command not in profile.read():
                profile.write(path_command)
                secho(f"Added {directory} to {profile_path}", fg="green")
            else:
                secho(f"{directory} is already in {profile_path}", fg="yellow")

        # Apply the path change to the current session
        environ["PATH"] += pathsep + directory
        secho("The PATH has been updated for the current session.", fg="green")

    def run_command(self, command: list[str], path: Path):
        return subprocess.Popen(
            ["poetry", "run", *command],
            cwd=path,
            env=self.limited_scope_env,
        )

    def get_env_path(self, project_path: Path) -> str:
        result = subprocess.run(
            ["poetry", "env", "info", "--path"],
            check=True,
            capture_output=True,
            cwd=str(project_path),
            env=self.limited_scope_env,
        )

        return result.stdout.decode().strip()
