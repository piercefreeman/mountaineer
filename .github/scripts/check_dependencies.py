"""
We specify packages both as python dependencies and venv packages depending
on the local linking strategy. This script ensures that both dependency lists
align so we don't end up out of sync with one install pipeline.

"""

from dataclasses import dataclass
from logging import info
from sys import stdout
from typing import Optional, Union

import toml
from packaging import specifiers, version

IGNORE_PACKAGE_NAMES = {"python"}


@dataclass(frozen=True, eq=True)
class Package:
    name: str
    extras: frozenset
    version: Optional[str] = None


def normalize_version_constraint(version_str: Optional[str]) -> Optional[str]:
    """Convert different version constraints to a normalized form."""
    if not version_str:
        return None

    # Handle caret notation
    if version_str.startswith("^"):
        ver = version_str[1:]  # Remove caret
        base_version = version.parse(ver)
        return f">={ver},<{base_version.major + 1}.0.0"

    # Handle tilde notation
    if version_str.startswith("~"):
        ver = version_str[1:]  # Remove tilde
        base_version = version.parse(ver)
        return f">={ver},<{base_version.major}.{base_version.minor + 1}.0"

    return version_str


def parse_version_spec(value: Union[str, dict]) -> Optional[str]:
    """Parse version specification from poetry dependency definition."""
    if isinstance(value, str):
        return value
    elif isinstance(value, dict) and "version" in value:
        return value["version"]  # type: ignore
    return None


def parse_poetry_dependencies(data) -> set[Package]:
    deps = set()
    for key, value in data.items():
        if key in IGNORE_PACKAGE_NAMES:
            continue

        # Handle package name with optional extras
        package_parts = key.split("[")
        package_name = package_parts[0]

        # Parse extras and version
        extras: frozenset[str] = frozenset()
        version: Optional[str] = None

        if isinstance(value, dict):
            if "extras" in value:
                extras = frozenset(value["extras"])
            version = parse_version_spec(value)
        else:
            version = parse_version_spec(value)

        # Normalize version constraint
        normalized_version = normalize_version_constraint(version)

        pkg = Package(name=package_name, extras=extras, version=normalized_version)
        info(f"Poetry dependency: {pkg}")
        deps.add(pkg)
    return deps


def parse_project_dependencies(data) -> set[Package]:
    deps = set()
    for dep in data:
        info(f"\nParsing project dependency: {dep}")

        if "[" in dep:
            # Split name and extras+version
            base_name, rest = dep.split("[", 1)
            base_name = base_name.strip()

            # Find closing bracket for extras
            bracket_idx = rest.find("]")
            if bracket_idx == -1:
                continue

            # Split extras and version info
            extras_str = rest[:bracket_idx]
            version_str = rest[bracket_idx + 1 :].strip()

            # Parse extras
            extras = frozenset(part.strip() for part in extras_str.split(","))

            # Create package with extras and version
            pkg = Package(
                name=base_name,
                extras=extras,
                version=normalize_version_constraint(
                    version_str if version_str else None
                ),
            )
            info(f"  Created package: {pkg}")
            deps.add(pkg)

        else:
            # Handle version specs in the package name
            if any(op in dep for op in [">=", "<=", "==", "<", ">"]):
                for op in [">=", "<=", "==", "<", ">"]:
                    if op in dep:
                        name, version = dep.split(op, 1)
                        pkg = Package(
                            name=name.strip(),
                            extras=frozenset(),
                            version=normalize_version_constraint(
                                f"{op}{version.strip()}"
                            ),
                        )
                        info(f"  Created package with version: {pkg}")
                        deps.add(pkg)
                        break
            else:
                pkg = Package(name=dep.strip(), extras=frozenset(), version=None)
                info(f"  Created simple package: {pkg}")
                deps.add(pkg)
    return deps


def compare_dependencies(poetry_deps: set[Package], project_deps: set[Package]):
    info("\nPoetry dependencies:")
    for dep in poetry_deps:
        info(f"  {dep}")

    info("\nProject dependencies:")
    for dep in project_deps:
        info(f"  {dep}")

    # First compare just names and extras
    poetry_base = {Package(name=p.name, extras=p.extras) for p in poetry_deps}
    project_base = {Package(name=p.name, extras=p.extras) for p in project_deps}

    missing_in_project = poetry_base - project_base
    missing_in_poetry = project_base - poetry_base

    # Then check for version mismatches in matching packages
    version_mismatches = []
    for poetry_pkg in poetry_deps:
        for project_pkg in project_deps:
            if (
                poetry_pkg.name == project_pkg.name
                and poetry_pkg.extras == project_pkg.extras
            ):
                if not are_version_constraints_compatible(
                    poetry_pkg.version, project_pkg.version
                ):
                    version_mismatches.append((poetry_pkg, project_pkg))

    if missing_in_project or missing_in_poetry or version_mismatches:
        if missing_in_project:
            stdout.write(f"Missing in project dependencies: {missing_in_project}\n")
        if missing_in_poetry:
            stdout.write(f"Missing in Poetry dependencies: {missing_in_poetry}\n")
        if version_mismatches:
            stdout.write("Version mismatches found:\n")
            for poetry_pkg, project_pkg in version_mismatches:
                stdout.write(
                    f"  {poetry_pkg.name}: Poetry={poetry_pkg.version}, Project={project_pkg.version}\n"
                )
        exit(1)
    else:
        stdout.write("All dependencies match!\n")


def are_version_constraints_compatible(
    ver1: Optional[str], ver2: Optional[str]
) -> bool:
    """Check if two version constraints are semantically equivalent."""
    if ver1 == ver2:
        return True
    if ver1 is None or ver2 is None:
        return False

    try:
        # Parse both version constraints
        spec1 = specifiers.SpecifierSet(ver1)
        spec2 = specifiers.SpecifierSet(ver2)

        # Check if they match the same versions
        test_versions = ["2.0.0", "2.5.0", "2.5.3", "2.9.9", "3.0.0", "3.0.1", "4.0.0"]

        return all((str(v) in spec1) == (str(v) in spec2) for v in test_versions)
    except Exception:
        return False


if __name__ == "__main__":
    with open("pyproject.toml", "r") as toml_file:
        pyproject_data = toml.load(toml_file)

    poetry_deps = parse_poetry_dependencies(
        pyproject_data["tool"]["poetry"]["dependencies"]
    )
    project_deps = parse_project_dependencies(pyproject_data["project"]["dependencies"])

    compare_dependencies(poetry_deps, project_deps)
