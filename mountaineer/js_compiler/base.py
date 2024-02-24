from abc import ABC, abstractmethod
from typing import Any, Coroutine

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

    @abstractmethod
    def handle_file(
        self,
        current_path: ManagedViewPath,
        controller: ControllerBase | None,
        metadata: ClientBundleMetadata,
    ) -> None | Coroutine[Any, Any, None]:
        """
        Only direct controller views are called with (view, controller) inputs. Otherwise we do a
        recursive search of the raw files on disk with controller=None.

        """
        pass
