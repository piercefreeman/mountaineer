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
from filzl.ssr import render_ssr


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
        # Because JSON is a subset of JavaScript, we can just dump the model as JSON and
        # insert it into the page.
        server_data = self.render(*args, **kwargs)

        # TODO: Provide a function to automatically sniff for the client view folder
        ssr_html = render_ssr(
            Path(
                "/Users/piercefreeman/projects/filzl/my_website/my_website/views/_ssr/home_controller.js"
            ).read_text(),
            server_data,
        )

        # Client-side react scripts that will hydrate the server side contents on load
        server_data_json = server_data.model_dump_json()
        optional_scripts = "\n".join(
            [
                f"<script src='/static_js/{script_name}'></script>"
                for script_name in self.bundled_scripts
            ]
        )

        page_contents = f"""
        <html>
        <head>
        </head>
        <body>
        <div id="root">{ssr_html}</div>
        <script type="text/javascript">
        const SERVER_DATA = {server_data_json};
        </script>
        {optional_scripts}
        </body>
        </html>
        """

        # return HTMLResponse(Path(self.view_path).read_text())
        return HTMLResponse(page_contents)

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
