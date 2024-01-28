from abc import ABC, abstractmethod

from fastapi.responses import HTMLResponse
from filzl.render import RenderBase
from inspect import ismethod, getmembers
from filzl.sideeffects import (
    get_function_metadata,
    FunctionMetadata,
    FunctionActionType,
)
from typing import Iterable, Callable
from pathlib import Path


class ControllerBase(ABC):
    url: str
    view_path: str | Path

    @abstractmethod
    def render(self, *args, **kwargs) -> RenderBase:
        pass

    def _generate_html(self, *args, **kwargs):
        # TODO: Implement SSR
        _ = self.render(*args, **kwargs)
        return HTMLResponse(Path(self.view_path).read_text())

    def _get_client_functions(self) -> Iterable[tuple[str, Callable, FunctionMetadata]]:
        """
        Returns all of the client-callable functions for this controller. Right now we force
        client accessible functions to either be wrapped by @sideeffect or @passthrough.

        """
        # Iterate over all the functions in this class and see which ones have a _metadata attribute
        for name, func in getmembers(self, predicate=ismethod):
            try:
                metadata = get_function_metadata(func)
                if metadata.action_type in {
                    FunctionActionType.PASSTHROUGH,
                    FunctionActionType.SIDEEFFECT,
                }:
                    yield name, func, metadata
            except AttributeError:
                continue
