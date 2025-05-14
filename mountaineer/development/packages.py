import importlib
import os
from importlib.metadata import distributions
from pathlib import Path


def find_packages_with_prefix(prefix: str):
    """
    Find and return a list of all installed package names that start with the given prefix.

    """
    return [
        dist.metadata["Name"]
        for dist in distributions()
        if dist.metadata["Name"].startswith(prefix)
    ]


def package_path_to_module(package: str, file_path_raw: Path) -> str:
    """
    Convert a file path to its corresponding Python module path.

    Args:
        package: The root package name (e.g. 'amplify')
        file_path_raw: The file path to convert

    Returns:
        The full module path (e.g. 'amplify.controllers.auth')
    """
    # Get the package's root directory
    package_module = importlib.import_module(package)
    if not package_module.__file__:
        raise ValueError(f"The package {package} does not have a __file__ attribute")

    package_root = os.path.dirname(package_module.__file__)
    file_path = os.path.abspath(str(file_path_raw))

    # Check if the file is within the package
    if not file_path.startswith(package_root):
        raise ValueError(
            f"The file {file_path} is not in the package {package} ({package_root})"
        )

    # Remove the package root and the file extension
    relative_path = os.path.relpath(file_path, package_root)
    module_path = os.path.splitext(relative_path)[0]

    # Convert path separators to dots and add the package name
    return f"{package}.{module_path.replace(os.sep, '.')}"
