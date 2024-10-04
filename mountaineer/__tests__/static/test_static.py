import os
import subprocess
from shutil import copy2, copytree

import pytest

from mountaineer.__tests__.static import get_static_fixtures_path
from mountaineer.logging import LOGGER
from mountaineer.static import get_static_path


def run_command(command: str, cwd: str) -> tuple[str, str]:
    try:
        # Use subprocess.Popen to capture output in real-time
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=dict(os.environ, FORCE_COLOR="true"),  # Force color output
        )

        # Capture both stdout and stderr
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, command, stdout, stderr
            )

        return stdout, stderr
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"Error executing command: {command}")
        LOGGER.error(f"Error output:\n{e.stderr}")
        raise


@pytest.fixture(scope="session")
def setup_test_environment(tmp_path_factory: pytest.TempPathFactory):
    temp_dir = tmp_path_factory.mktemp("test_environment")
    harness_path = get_static_fixtures_path("harness")
    api_file_path = get_static_path("api.ts")

    # Copy all files from harness directory to temp directory
    for item in os.listdir(harness_path):
        s = os.path.join(harness_path, item)
        d = os.path.join(temp_dir, item)
        if os.path.isdir(s):
            copytree(s, d)
        else:
            copy2(s, d)

    # Copy current api.ts to temp directory
    copy2(api_file_path, temp_dir)

    try:
        run_command("npm install", cwd=str(temp_dir))
        yield temp_dir
    finally:
        LOGGER.info(f"Test environment cleaned up at {temp_dir}")


def test_static_frontend(setup_test_environment: str):
    try:
        # Jest should return a non-zero exit code if tests fail, so if it came
        # back normally we can assume the tests passed
        stdout, stderr = run_command("npm run test", cwd=setup_test_environment)
        print(f"Jest stdout:\n{stdout}")  # noqa: T201
        print(f"Jest stderr:\n{stderr}")  # noqa: T201
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"Jest tests failed. Error output:\n{e.stderr}")
        LOGGER.error(f"Jest stdout output:\n{e.stdout}")
        raise
