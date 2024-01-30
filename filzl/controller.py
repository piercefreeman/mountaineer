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
from filzl.render import Metadata, RenderBase
from filzl.ssr import render_ssr


class ControllerBase(ABC):
    url: str
    view_path: str | Path

    bundled_scripts: list[str]

    def __init__(self):
        # Injected by the build framework
        self.bundled_scripts = []
        self.ssr_path: Path | None = None
        self.initialized = True

    @abstractmethod
    def render(self, *args, **kwargs) -> RenderBase:
        pass

    def _generate_html(self, *args, **kwargs):
        if not self.ssr_path:
            raise ValueError("No SSR path set for this controller")

        # Because JSON is a subset of JavaScript, we can just dump the model as JSON and
        # insert it into the page.
        server_data = self.render(*args, **kwargs)
        header_str = "\n".join(
            self.build_header(server_data.metadata) if server_data.metadata else []
        )

        # Now that we've built the header, we can remove it from the server data
        # This makes our cache more efficient, since metadata changes don't affect
        # the actual page contents.
        server_data = server_data.model_copy(update={"metadata": None})

        # TODO: Provide a function to automatically sniff for the client view folder
        ssr_html = render_ssr(
            self.ssr_path.read_text(),
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
        {header_str}
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

        return HTMLResponse(page_contents)

    def build_header(self, metadata: Metadata) -> list[str]:
        """
        Builds the header for this controller. Returns the list of tags that will be injected into the
        <head> tag of the rendered page.

        """
        tags: list[str] = []

        def format_optional_keys(payload: dict[str, str | None]) -> str:
            return " ".join(
                [
                    f'{key}="{value}"'
                    for key, value in payload.items()
                    if value is not None
                ]
            )

        if metadata.title:
            tags.append(f"<title>{metadata.title}</title>")

        for meta_definition in metadata.metas:
            all_attributes = {
                "name": meta_definition.name,
                "content": meta_definition.content,
                **meta_definition.optional_attributes,
            }
            tags.append(f"<meta {format_optional_keys(all_attributes)} />")

        for link_definition in metadata.links:
            all_attributes = {
                "rel": link_definition.rel,
                "href": link_definition.href,
                **link_definition.optional_attributes,
            }
            tags.append(f"<link {format_optional_keys(all_attributes)} />")

        return tags

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
