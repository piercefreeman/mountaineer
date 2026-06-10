import subprocess
from pathlib import Path

from create_mountaineer_app import ui


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
        ui.run_command(
            ["npm", "install"],
            cwd=str(path),
        )
        return True
    except Exception as e:
        ui.error(
            f"An unexpected error occurred while installing npm dependencies: {e}",
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
