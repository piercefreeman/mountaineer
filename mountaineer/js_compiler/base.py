from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Coroutine, MutableMapping

from pydantic import BaseModel

from mountaineer.controller import ControllerBase
from mountaineer.paths import ManagedViewPath


class ClientBundleMetadata(BaseModel):
    live_reload_port: int | None = None


class ClientBuilderBase(ABC):
    """
    Base class for client builders. When mounted to an AppController, these build plugins
    will be called for every file defined in the view/app directory. It's up to the plugin
    whether to handle the incoming file.

    """

    def __init__(self, tmp_dir: Path | None = None):
        # We keep a tmpdir open for the duration of the build process, so our rust
        # logic can leverage file-based caches for faster builds
        # Note that this tmpdir is shared across all client builders, so it's important
        # that you enforce uniqueness of filenames if you leverage this cache
        self.tmp_dir = tmp_dir if tmp_dir else Path(mkdtemp())

        self.metadata : ClientBundleMetadata | None = None

        self.dirty_files: set[Path] = set()
        self.controllers : list[tuple[ControllerBase, ManagedViewPath]] = []

    def set_metadata(self, metadata: ClientBundleMetadata):
        self.metadata = metadata

    def register_controller(self, controller: ControllerBase, view_path: ManagedViewPath):
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
