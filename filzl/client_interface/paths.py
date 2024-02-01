from os import PathLike
from os.path import relpath
from pathlib import Path

from filzl.controller import ControllerBase
from filzl.logging import LOGGER


class ManagedViewPath(type(Path())):
    """
    Helper class to manage our view directory conventions.

    """

    is_root_link: bool

    def __new__(cls, *args, **kwargs):
        # Ensure instances are created properly by using the __new__ method of the Path class
        # path = ManagedViewPath(*args, **kwargs)
        path = super().__new__(cls, *args, **kwargs)
        path.is_root_link = False
        return path

    @classmethod
    def from_view_root(cls, root_path: PathLike | str):
        """
        Constructor to create a ManagedViewPath from the view root
        """
        path = cls(root_path)
        path.is_root_link = True
        return path

    def __truediv__(self, key):
        # Override '/' operation for when ManagedViewPath is on the left
        result = super().__truediv__(key)
        return ManagedViewPath(result)

    def __rtruediv__(self, key):
        # Override '/' operation for when ManagedViewPath is on the right
        result = super().__rtruediv__(key)
        return ManagedViewPath(result)

    def get_managed_code_dir(self):
        return self.get_managed_dir_common("_server")

    def get_managed_static_dir(self):
        # Only root paths can have static directories
        if not self.is_root_link:
            raise ValueError("Cannot get static directory from a non-root linked view path")
        return self.get_managed_dir_common("_static")

    def get_managed_ssr_dir(self):
        # Only root paths can have SSR directories
        if not self.is_root_link:
            raise ValueError("Cannot get SSR directory from a non-root linked view path")
        return self.get_managed_dir_common("_ssr")

    def get_managed_dir_common(self, managed_dir: str):
        # If the path is to a file, we want to get the parent directory
        # so that we can create the managed code directory
        # We also create the managed code directory if it doesn't exist so all subsequent
        # calls can immediately start writing to it
        path = self
        if path.is_file():
            path = path.parent
        managed_code_dir = path / managed_dir
        managed_code_dir.mkdir(exist_ok=True)
        return managed_code_dir

    def get_controller_view_path(self, controller: ControllerBase):
        """
        Assume all paths are specified in terms of their relative root
        """
        # Ensure we are being take relative to the root view
        if not self.is_root_link:
            raise ValueError(
                "Cannot get controller view path from a non-root linked view path"
            )
        relative_path = Path(controller.view_path.lstrip("/"))
        return self / relative_path


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
