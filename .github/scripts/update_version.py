"""
Update the version for the regular Mountaineer rust project.

"""

import sys
from pathlib import Path
from sys import stdout

import toml
from packaging.version import parse


def update_version_rust(new_version: str):
    cargo_path = Path("Cargo.toml")
    if not cargo_path.exists():
        stdout.write("Cargo.toml not found, skipping version update")
        return

    filedata = toml.loads(cargo_path.read_text())

    # If the new version is a pre-release version, we need to reformat it
    # to align with Cargo standards
    # pip format uses "0.1.0.dev1" while Cargo uses "0.1.0-dev1"
    cargo_version = format_cargo_version(new_version)

    if "package" not in filedata:
        raise ValueError("Cargo.toml is missing the [package] section")

    filedata["package"]["version"] = cargo_version

    cargo_path.write_text(toml.dumps(filedata))


def format_cargo_version(new_version: str) -> str:
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

    return cargo_version


def update_version_python(new_version: str):
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        stdout.write("pyproject.toml not found, skipping version update")
        return

    filedata = toml.loads(pyproject_path.read_text())

    # Parse the new version to ensure it's valid and potentially reformat
    python_version = format_python_version(new_version)

    if "tool" not in filedata or "poetry" not in filedata["tool"]:
        raise ValueError("pyproject.toml is missing the [tool.poetry] section")

    filedata["tool"]["poetry"]["version"] = python_version

    # Also update project.version if it exists
    if "project" in filedata and "version" in filedata["project"]:
        filedata["project"]["version"] = python_version

    pyproject_path.write_text(toml.dumps(filedata))


def format_python_version(new_version: str) -> str:
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
    return python_version


if __name__ == "__main__":
    if len(sys.argv) != 2:
        stdout.write("Usage: python update_version.py <new_version>")
        sys.exit(1)
    new_version = sys.argv[1].lstrip("v")
    update_version_rust(new_version)
    update_version_python(new_version)
    stdout.write(f"Updated version to: {new_version}")
