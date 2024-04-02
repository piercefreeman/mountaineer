"""
Update the version for the regular Mountaineer rust project.

"""

import re
import sys
from pathlib import Path
from sys import stdout

from packaging.version import parse


def update_version_rust(new_version: str):
    cargo_path = Path("Cargo.toml")
    if not cargo_path.exists():
        stdout.write("Cargo.toml not found, skipping version update")
        return

    filedata = cargo_path.read_text()

    # If the new version is a pre-release version, we need to reformat it
    # to align with Cargo standards
    # pip format uses "0.1.0.dev1" while Cargo uses "0.1.0-dev1"
    parsed_version = parse(new_version)

    cargo_version = (
        f"{parsed_version.major}.{parsed_version.minor}.{parsed_version.micro}"
    )
    if parsed_version.is_prerelease and parsed_version.pre is not None:
        pre_release = ".".join(str(x) for x in parsed_version.pre)
        cargo_version += f"-{pre_release.replace('.', '')}"
    if parsed_version.is_postrelease and parsed_version.post is not None:
        cargo_version += f"-post{parsed_version.post}"
    if parsed_version.is_devrelease and parsed_version.dev is not None:
        cargo_version += f"-dev{parsed_version.dev}"

    # Update the version in the file
    filedata = re.sub(
        r'^version = ".*"$',
        f'version = "{cargo_version}"',
        filedata,
        flags=re.MULTILINE,
    )
    cargo_path.write_text(filedata)


def update_version_python(new_version: str):
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        stdout.write("pyproject.toml not found, skipping version update")
        return

    filedata = pyproject_path.read_text()

    # Parse the new version to ensure it's valid and potentially reformat
    parsed_version = parse(new_version)
    # Assuming semantic versioning, format it as needed
    python_version = (
        f"{parsed_version.major}.{parsed_version.minor}.{parsed_version.micro}"
    )
    if parsed_version.is_prerelease and parsed_version.pre is not None:
        pre_release = ".".join(str(x) for x in parsed_version.pre)
        python_version += (
            f".dev{parsed_version.pre[-1]}"
            if pre_release.startswith("dev")
            else f"b{parsed_version.pre[-1]}"
        )
    if parsed_version.is_postrelease and parsed_version.post is not None:
        python_version += f".post{parsed_version.post}"
    if parsed_version.is_devrelease and parsed_version.dev is not None:
        python_version += f".dev{parsed_version.dev}"

    # Update the version in the filedata
    # This regex targets the version field under the [project] table, assuming it's formatted as expected
    filedata = re.sub(
        r'version = ".*?"',
        f'version = "{python_version}"',
        filedata,
        flags=re.MULTILINE,
    )
    pyproject_path.write_text(filedata)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        stdout.write("Usage: python update_version.py <new_version>")
        sys.exit(1)
    new_version = sys.argv[1].lstrip("v")
    update_version_rust(new_version)
    update_version_python(new_version)
    stdout.write(f"Updated version to: {new_version}")
