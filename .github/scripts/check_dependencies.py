"""
We specify packages both as python dependencies and venv packages depending
on the local linking strategy. This script ensures that both dependency lists
align so we don't end up out of sync with one install pipeline.

"""

from dataclasses import dataclass
from sys import stdout

import toml

IGNORE_PACKAGE_NAMES = {"python"}


@dataclass(frozen=True, eq=True)
class Package:
    name: str
    extras: frozenset


def parse_poetry_dependencies(data) -> set[Package]:
    deps = set()
    for key, value in data.items():
        if key in IGNORE_PACKAGE_NAMES:
            continue
        package_name = key.split("[")[0]
        extras: frozenset[str] = frozenset()
        if isinstance(value, dict) and "version" in value and "extras" in value:
            extras = frozenset(value["extras"])
        deps.add(Package(name=package_name, extras=extras))
    return deps


def parse_project_dependencies(data) -> set[Package]:
    deps = set()
    for dep in data:
        parts = dep.split("[")
        package_name = parts[0]
        if package_name in IGNORE_PACKAGE_NAMES:
            continue
        extras = frozenset(parts[1][:-1].split(",")) if len(parts) > 1 else frozenset()
        deps.add(Package(name=package_name, extras=extras))
    return deps


def compare_dependencies(poetry_deps: set[Package], project_deps: set[Package]):
    missing_in_project = poetry_deps - project_deps
    missing_in_poetry = project_deps - poetry_deps

    if missing_in_project or missing_in_poetry:
        if missing_in_project:
            stdout.write(f"Missing in project dependencies: {missing_in_project}")
        if missing_in_poetry:
            stdout.write(f"Missing in Poetry dependencies: {missing_in_poetry}")
        exit(1)
    else:
        stdout.write("All dependencies match!")


if __name__ == "__main__":
    with open("pyproject.toml", "r") as toml_file:
        pyproject_data = toml.load(toml_file)

    poetry_deps = parse_poetry_dependencies(
        pyproject_data["tool"]["poetry"]["dependencies"]
    )
    project_deps = parse_project_dependencies(pyproject_data["project"]["dependencies"])

    compare_dependencies(poetry_deps, project_deps)
