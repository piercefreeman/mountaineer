import subprocess
from os import environ
from pathlib import Path
from tempfile import NamedTemporaryFile

from click import secho


def has_poetry():
    """
    Detect if there is a system-wide poetery install that's already
    mounted in the path.

    """
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


def install_poetry():
    """
    If poetry is not installed, install it via the official
    installation script:

    ```
    curl -sSL https://install.python-poetry.org | python3 -
    ```

    """
    try:
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
        return True
    except subprocess.CalledProcessError as e:
        # Handle possible errors during the installation process
        secho(f"Failed to install Poetry: {e}", fg="red")
        return False
    except Exception as e:
        # Handle any other exception
        secho(f"An unexpected error occurred: {e}", fg="red")
        return False


def poetry_install(path: Path):
    """
    Perform a poetry install in the given path.

    """
    # While running our script within poetry, poetry will inject a POETRY_ACTIVE
    # environment variable. This will cause poetry to only install within the
    # current directory. We want to avoid tthis since the path we're given could be
    # anywhere in the system. We'll limit the scope of the new poetry subprocess to
    # only the PATH environment variable.
    limited_scope_env = {
        "PATH": environ["PATH"],
    }

    try:
        subprocess.run(
            ["poetry", "install"],
            check=True,
            cwd=str(path),
            env=limited_scope_env,
        )

        # Retrieve the location of the new virtualenv
        result = subprocess.run(
            ["poetry", "env", "info", "--path"],
            check=True,
            capture_output=True,
            cwd=str(path),
            env=limited_scope_env,
        )

        secho(f"Poetry venv created: {result.stdout.decode().strip()}", fg="green")
        return True
    except Exception as e:
        # Handle any other exception
        secho(
            f"An unexpected error occurred while installing project dependencies: {e}",
            fg="red",
        )
        return False


def has_npm():
    try:
        subprocess.run(
            ["npm", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return True
    except FileNotFoundError:
        return False


def npm_install(path: Path):
    try:
        subprocess.run(
            ["npm", "install"],
            check=True,
            cwd=str(path),
        )
        return True
    except Exception as e:
        secho(
            f"An unexpected error occurred while installing npm dependencies: {e}",
            fg="red",
        )
        return False


def get_git_user_info():
    """
    Get the global Git user name and email, if git is set up on the system.

    """
    try:
        git_user_name = (
            subprocess.check_output(["git", "config", "--global", "user.name"])
            .strip()
            .decode()
        )
        git_user_email = (
            subprocess.check_output(["git", "config", "--global", "user.email"])
            .strip()
            .decode()
        )
        return git_user_name, git_user_email
    except subprocess.CalledProcessError:
        return None, None
