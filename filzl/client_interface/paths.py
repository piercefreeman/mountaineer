from os.path import relpath
from pathlib import Path

from filzl.logging import LOGGER


def is_path_file(path: Path):
    if path.exists():
        return path.is_file()

    # If the file doesn't actually exist (common in unit tests), we guess the path
    LOGGER.warning(f"File {path} does not exist. Guessing file status.")

    # Only use is_file if the current path is ambiguous
    dot_components = [
        component for component in path.name.split(".") if component.strip()
    ]
    return len(dot_components) > 1


def generate_relative_import(
    current_import: Path,
    desired_import: Path,
    strip_js_extensions: bool = True,
):
    """
    Given the path of the current file and the file that should be imported, try to find
    a relative path that can be used to import the file.

    :param strip_js_extensions: This function is usually called by our JS import header
    constructors. In the ESM syntax importing other files shouldn't include the javascript
    suffix. This flag allows callers to strip the suffix from the import path.

    """
    # Calculate the relative path
    relative_path = relpath(
        desired_import,
        current_import.parent if is_path_file(current_import) else current_import,
    )

    # Convert to JavaScript import format
    if not relative_path.startswith("."):
        relative_path = "./" + relative_path

    # Strip the file extension
    if strip_js_extensions:
        for js_extensions in [".js", ".jsx", ".ts", ".tsx"]:
            if relative_path.endswith(js_extensions):
                relative_path = relative_path.removesuffix(js_extensions)

    return relative_path
