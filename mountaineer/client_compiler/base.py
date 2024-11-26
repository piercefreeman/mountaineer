from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from mountaineer.controller import ControllerBase
from mountaineer.paths import ManagedViewPath


@dataclass
class ClientBundleMetadata:
    package_root_link: ManagedViewPath

    # We keep a tmpdir open for the duration of the build process, so our rust
    # logic can leverage file-based caches for faster builds
    # Note that this tmpdir is shared across all client builders, so it's important
    # that you enforce uniqueness of filenames if you leverage this cache
    tmp_dir: Path

    live_reload_port: int | None = None


class APIBuilderBase(ABC):
    """
    Base class for client builders. When mounted to an AppController, these build plugins
    will be called for every file defined in the view/app directory. It's up to the plugin
    whether to handle the incoming file.

    """

    def __init__(self):
        self.metadata: ClientBundleMetadata | None = None

        self.dirty_files: set[Path] = set()
        self.controllers: list[tuple[ControllerBase, ManagedViewPath]] = []

    def set_metadata(self, metadata: ClientBundleMetadata):
        self.metadata = metadata

    def register_controller(
        self, controller: ControllerBase, view_path: ManagedViewPath
    ):
        self.controllers.append((controller, view_path))

    def mark_file_dirty(self, file_path: Path):
        self.dirty_files.add(file_path)

    async def build_wrapper(self):
        """
        All internal users should use this instead of .build()
        """
        await self.build()
        self.dirty_files.clear()

    @abstractmethod
    async def build(self):
        """
        Builds the dirty files.

        """
        pass

    def managed_views_from_paths(self, paths: list[Path]) -> list[ManagedViewPath]:
        """
        Given a list of paths, assume these fall somewhere within the view directories
        specified by the controllers. Returns the ManagedViewPath objects for
        all paths where a match is found.

        """
        # Index all of the unique view roots to track the DAG hierarchies
        unique_roots = {view_path.get_root_link() for _, view_path in self.controllers}

        # Convert all of the dirty files into managed paths
        converted_paths: list[ManagedViewPath] = []
        for path in paths:
            # Each file must be relative to one of our known view roots, otherwise
            # we ignore it
            for root in unique_roots:
                if path.is_relative_to(root):
                    relative_path = path.relative_to(root)
                    converted_paths.append(root / relative_path)
                    break

        return converted_paths
