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
        self.global_state: MutableMapping[Any, Any] | None = None

    async def init_state(self, global_state: MutableMapping[Any, Any]):
        pass

    async def start_build(self):
        pass

    @abstractmethod
    async def handle_file(
        self,
        file_path: ManagedViewPath,
        controller: ControllerBase | None,
        metadata: ClientBundleMetadata,
    ) -> None | Coroutine[Any, Any, None]:
        """
        Only direct controller views are called with (view, controller) inputs. Otherwise we do a
        recursive search of the raw files on disk with controller=None.

        """
        pass

    async def finish_build(self):
        pass
