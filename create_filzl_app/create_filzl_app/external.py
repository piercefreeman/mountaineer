import subprocess
from pathlib import Path

from click import secho


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
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None
