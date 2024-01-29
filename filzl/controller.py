from abc import ABC, abstractmethod
from inspect import getmembers, ismethod
from pathlib import Path
from typing import Callable, Iterable

from fastapi.responses import HTMLResponse

from filzl.actions import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from filzl.render import RenderBase


class ControllerBase(ABC):
    url: str
    view_path: str | Path

    bundled_scripts: list[str]

    def __init__(self):
        # Injected by the build framework
        self.bundled_scripts = []
        self.initialized = True

    @abstractmethod
    def render(self, *args, **kwargs) -> RenderBase:
        pass

    def _generate_html(self, *args, **kwargs):
        # TODO: Implement SSR
        _ = self.render(*args, **kwargs)

        optional_scripts = "\n".join(
            [
                f"<script src='/static_js/{script_name}'></script>"
                for script_name in self.bundled_scripts
            ]
        )
        TEMPLATE = f"""
        <html>
        <head>
        <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
        <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
        </head>
        <body>
        <div id="root"></div>
        {optional_scripts}
        </body>
        </html>
        """

        # return HTMLResponse(Path(self.view_path).read_text())
        return HTMLResponse(TEMPLATE)

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
