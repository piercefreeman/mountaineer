from pathlib import Path
from os.path import relpath


def generate_relative_import(current_import: Path, desired_import: Path):
    """
    Given the path of the current file and the file that should be imported, try to find
    a relative path that can be used to import the file.

    """
    # Calculate the relative path
    relative_path = relpath(
        desired_import,
        current_import.parent if current_import.is_file() else current_import,
    )

    # Convert to JavaScript import format
    if not relative_path.startswith("."):
        relative_path = "./" + relative_path

    # Strip the file extension
    for js_extensions in [".js", ".jsx", ".ts", ".tsx"]:
        if relative_path.endswith(js_extensions):
            relative_path = relative_path.removesuffix(js_extensions)

    return relative_path
