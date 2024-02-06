import subprocess
from click import secho
from tempfile import NamedTemporaryFile


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
