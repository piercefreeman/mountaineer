from abc import ABC, abstractmethod

from fastapi.responses import HTMLResponse
from filzl.render import RenderBase
from inspect import isfunction, ismethod, getmembers
from filzl.sideeffects import METADATA_ATTRIBUTE, FunctionMetadata
from typing import Iterable, Callable
from pathlib import Path

class BaseController(ABC):
    url: str
    template_path: str | Path

    @abstractmethod
    def render(self, *args, **kwargs) -> RenderBase:
        pass

    def _generate_html(self):
        # TODO: Implement SSR
        return HTMLResponse(Path(self.template_path).read_text())

    def _get_client_functions(self) -> Iterable[tuple[str, Callable, FunctionMetadata]]:
        """
        Returns all of the client-callable functions for this controller. Right now we force
        client accessible functions to either be wrapped by @sideeffect or @passthrough.

        """
        # Iterate over all the functions in this class and see which ones have a _metadata attribute
        for name, func in getmembers(self, predicate=ismethod):
            metadata = getattr(func, METADATA_ATTRIBUTE, None)
            if metadata is not None:
                yield name, func, metadata
