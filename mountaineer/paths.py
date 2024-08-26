import importlib.metadata
import sys
from json import loads as json_loads
from os import PathLike, walk as os_walk
from os.path import realpath, relpath
from pathlib import Path
from re import search as re_search
from typing import TYPE_CHECKING, Optional

from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.logging import LOGGER

if TYPE_CHECKING:
    from mountaineer.controller import ControllerBase


class ManagedViewPath(type(Path())):  # type: ignore
    """
    Helper class to manage our view directory conventions. We choose the superclass of this
    class at runtime to conform to the OS-specific Path implementation.

    """

    # Root link to the view directory
    root_link: Optional["ManagedViewPath"]

    # Root link to the directory that stores package.json / node_modules / etc
    # Typically this is the same thing as the root_link, but in the case of plugins
    # they may be different
    package_root_link: Optional["ManagedViewPath"]

    def __new__(cls, *args, **kwargs):
        # Ensure instances are created properly by using the __new__ method of the Path class
        # path = ManagedViewPath(*args, **kwargs)
        path = super().__new__(cls, *args, **kwargs)
        path.root_link = None
        path.package_root_link = None
        return path

    @classmethod
    def from_view_root(
        cls,
        root_path: PathLike | str,
        package_root_link: PathLike
        | str
        | None
        | MountaineerUnsetValue = MountaineerUnsetValue(),
    ):
        """
        Constructor to create a ManagedViewPath from the view root
        """
        path = cls(root_path)
        path.root_link = path
        if isinstance(package_root_link, MountaineerUnsetValue):
            path.package_root_link = path
        elif package_root_link is not None:
            path.package_root_link = cls(package_root_link)
        return path

    def __truediv__(self, key):
        # Override '/' operation for when ManagedViewPath is on the left
        result = super().__truediv__(key)
        return self._inherit_root_link(result)

    def __rtruediv__(self, key):
        # Override '/' operation for when ManagedViewPath is on the right
        result = super().__rtruediv__(key)
        return ManagedViewPath(result)

    def get_root_link(self):
        """
        Get the original root link for this view path. If the current view is a root link, it will return itself.
        """
        if self.root_link is None:
            raise ValueError(
                f"Cannot get root link from a non-root linked view path: {self}"
            )
        return self.root_link

    def get_package_root_link(self):
        """
        Get the original package root link for this view path. If the current view is a root link, it will return itself.
        """
        if self.package_root_link is None:
            raise ValueError(
                f"Cannot get package root link from current view path: {self}"
            )
        return self.package_root_link

    def get_managed_code_dir(self, create_dir: bool = True):
        return self.get_managed_dir_common("_server", create_dir=create_dir)

    def get_managed_static_dir(self, tmp_build: bool = False, create_dir: bool = True):
        # Only root paths can have static directories
        if not self.is_root_link:
            raise ValueError(
                "Cannot get static directory from a non-root linked view path"
            )
        path = self.get_managed_dir_common("_static", create_dir=create_dir)
        if tmp_build:
            path = path / "tmp"
            path.mkdir(exist_ok=True)
        return path

    def get_managed_ssr_dir(self, tmp_build: bool = False, create_dir: bool = True):
        # Only root paths can have SSR directories
        if not self.is_root_link:
            raise ValueError(
                "Cannot get SSR directory from a non-root linked view path"
            )
        path = self.get_managed_dir_common("_ssr", create_dir=create_dir)
        if tmp_build:
            path = path / "tmp"
            path.mkdir(exist_ok=True)
        return path

    def get_managed_dir_common(
        self,
        managed_dir: str,
        create_dir: bool = True,
    ):
        # If the path is to a file, we want to get the parent directory
        # so that we can create the managed code directory
        # We also create the managed code directory if it doesn't exist so all subsequent
        # calls can immediately start writing to it
        path = self
        if path.is_file():
            path = path.parent
        managed_code_dir = path / managed_dir
        if create_dir:
            managed_code_dir.mkdir(exist_ok=True)
        return managed_code_dir

    def get_controller_view_path(self, controller: "ControllerBase"):
        """
        Assume all paths are specified in terms of their relative root
        """
        # Ensure we are being take relative to the root view
        if not self.is_root_link:
            raise ValueError(
                "Cannot get controller view path from a non-root linked view path"
            )

        controller_path = controller.view_path

        # If the user has specified a full path, we will use that
        if isinstance(controller_path, ManagedViewPath):
            # Merge in the current attributes, if they don't exist
            controller_path = controller_path.copy()

            if controller_path.root_link is None:
                controller_path.root_link = self.root_link
            if controller_path.package_root_link is None:
                controller_path.package_root_link = self.package_root_link
            return controller_path

        relative_path = Path(controller_path.lstrip("/"))
        return self / relative_path

    def copy(self) -> "ManagedViewPath":
        path = self.__class__(self)
        path.root_link = self.root_link
        path.package_root_link = self.package_root_link
        return path

    if sys.version_info >= (3, 12):

        def rglob(self, pattern: str, *, case_sensitive: bool | None = None):
            for path in super().rglob(pattern, case_sensitive=case_sensitive):
                yield self._inherit_root_link(path)
    else:

        def rglob(self, pattern: str):
            # Override the rglob method to return a ManagedViewPath
            for path in super().rglob(pattern):
                yield self._inherit_root_link(path)

    if sys.version_info >= (3, 12):

        def walk(self, top_down=True, on_error=None, follow_symlinks=False):
            for root, dirs, files in super().walk(
                top_down=top_down, on_error=on_error, follow_symlinks=follow_symlinks
            ):
                yield self._inherit_root_link(root), dirs, files

    else:

        def walk(self):
            for root, dirs, files in os_walk(str(self)):
                yield self._inherit_root_link(root), dirs, files

    def resolve(self, strict=False):
        return self._inherit_root_link(super().resolve())

    def absolute(self):
        return self._inherit_root_link(super().absolute())

    if sys.version_info >= (3, 12):

        def relative_to(self, __other, *_deprecated, walk_up: bool = False):
            return self._inherit_root_link(
                super().relative_to(__other, *_deprecated, walk_up=walk_up)
            )
    else:

        def relative_to(self, *other):
            return self._inherit_root_link(super().relative_to(*other))

    def with_name(self, name):
        return self._inherit_root_link(super().with_name(name))

    def with_suffix(self, suffix):
        return self._inherit_root_link(super().with_suffix(suffix))

    @property
    def is_root_link(self):
        return self == self.root_link

    @property
    def parent(self):  # type: ignore
        return self._inherit_root_link(super().parent)

    def realpath(self):
        return self._inherit_root_link(realpath(self))

    def _inherit_root_link(self, new_path: Path | str) -> "ManagedViewPath":
        managed_path = ManagedViewPath(new_path)
        managed_path.root_link = self.root_link
        managed_path.package_root_link = self.package_root_link
        return managed_path


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
    current_import = current_import.resolve()
    desired_import = desired_import.resolve()

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


def resolve_package_path(package_name: str):
    """
    Given a package distribution, returns the local file directory where the code
    is located. This is resolved to the original reference if installed with `-e`
    otherwise is a copy of the package.

    """
    dist = importlib.metadata.distribution(package_name)

    def normalize_package(package: str):
        return package.replace("-", "_").lower()

    # Recent versions of poetry install development packages (-e .) as direct URLs
    # https://the-hitchhikers-guide-to-packaging.readthedocs.io/en/latest/introduction.html
    # "Path configuration files have an extension of .pth, and each line must
    # contain a single path that will be appended to sys.path."
    package_name = normalize_package(dist.name)
    symbolic_links = [
        path
        for path in (dist.files or [])
        if path.name.lower() == f"{package_name}.pth"
    ]
    dist_links = [
        path
        for path in (dist.files or [])
        if path.name == "direct_url.json"
        and re_search(package_name + r"-[0-9-.]+\.dist-info", path.parent.name.lower())
    ]
    explicit_links = [
        path
        for path in (dist.files or [])
        if path.parent.name.lower() == package_name
        and (
            # Sanity check that the parent is the high level project directory
            # by looking for common base files
            path.name == "__init__.py"
        )
    ]

    # The user installed code as an absolute package (ie. with pip install .) instead of
    # as a reference. There's no need to sniff for the additional package path since
    # we've already found it
    if explicit_links:
        # Right now we have a file pointer to __init__.py. Go up one level
        # to the main package directory to return a directory
        explicit_link = explicit_links[0]
        return Path(str(dist.locate_file(explicit_link.parent)))

    # Raw path will capture the path to the pyproject.toml file directory,
    # not the actual package code directory
    # Find the root, then resolve the package directory
    raw_path: Path | None = None

    if symbolic_links:
        direct_url_path = symbolic_links[0]
        raw_path = Path(str(dist.locate_file(direct_url_path.read_text().strip())))
    elif dist_links:
        dist_link = dist_links[0]
        direct_metadata = json_loads(dist_link.read_text())
        package_path = "/" + direct_metadata["url"].lstrip("file://").lstrip("/")
        raw_path = Path(str(dist.locate_file(package_path)))

    if not raw_path:
        raise ValueError(
            f"Could not find a valid path for package {dist.name}, found files: {dist.files}"
        )

    # Sniff for the presence of the code directory
    for path in raw_path.iterdir():
        if path.is_dir() and normalize_package(path.name) == package_name:
            return path

    raise ValueError(
        f"No matching package found in root path: {raw_path} {list(raw_path.iterdir())}"
    )
