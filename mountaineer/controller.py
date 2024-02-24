from abc import ABC, abstractmethod
from inspect import getmembers, isawaitable, ismethod
from pathlib import Path
from re import compile as re_compile
from time import time
from typing import Any, Callable, Coroutine, Iterable

from fastapi.responses import HTMLResponse
from inflection import underscore

from mountaineer.actions import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from mountaineer.js_compiler.source_maps import SourceMapParser
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath
from mountaineer.render import Metadata, RenderBase, RenderNull
from mountaineer.ssr import V8RuntimeError, render_ssr


class ControllerBase(ABC):
    url: str
    # Typically, view paths should be a relative path to the local
    # Paths are only used if you need to specify an absolute path to another
    # file on disk
    view_path: str | ManagedViewPath

    bundled_scripts: list[str]

    def __init__(
        self, slow_ssr_threshold: float = 0.1, hard_ssr_timeout: float | None = 10.0
    ):
        """
        :param slow_ssr_threshold: Each python process has a single V8 runtime associated with
        it, so SSR rendering can become a bottleneck if it requires processing. We log a warning
        if we detect that an SSR render took longer than this threshold.
        :param hard_ssr_timeout: If the SSR render takes longer than this threshold, we will
        automatically kill the V8 runtime and return an error to the client. This is useful for
        avoiding blocking the reset of the server process if the React render logic hangs.

        """
        # Injected by the build framework
        self.bundled_scripts: list[str] = []
        self.ssr_path: Path | None = None
        self.initialized = True
        self.slow_ssr_threshold = slow_ssr_threshold
        self.hard_ssr_timeout = hard_ssr_timeout
        self.source_map: SourceMapParser | None = None

    @abstractmethod
    def render(
        self, *args, **kwargs
    ) -> RenderBase | None | Coroutine[Any, Any, RenderBase]:
        """
        Client implementations must override render() to define the data that will
        be pushed from the server to the client. This function must be typehinted with
        your response type:

        ```python
        class MyServerData(RenderBase):
            pass

        class MyController:
            def render(self) -> MyServerData:
                pass
        ```

        If you don't intend to sync any data from server->client you can typehint this function
        with an explicit None return annotation:

        ```python
        class MyController:
            def render(self) -> None:
                pass
        ```

        """
        pass

    async def _generate_html(self, *args, global_metadata: Metadata | None, **kwargs):
        if not self.ssr_path:
            # Try to resolve the path dynamically now
            raise ValueError("No SSR path set for this controller")

        # Because JSON is a subset of JavaScript, we can just dump the model as JSON and
        # insert it into the page.
        server_data = self.render(*args, **kwargs)
        if isawaitable(server_data):
            server_data = await server_data
        if server_data is None:
            server_data = RenderNull()

        # This isn't expected to happen, but we add a check to typeguard the following logic
        if not isinstance(server_data, RenderBase):
            raise ValueError(
                f"Controller.render() must return a RenderBase instance, not {type(server_data)}"
            )

        # If we got back metadata that includes a redirect, we should short-circuit the rest of the
        # render process and return a redirect response
        if server_data.metadata and server_data.metadata.explicit_response:
            return server_data.metadata.explicit_response

        metadatas: list[Metadata] = []
        if server_data.metadata:
            metadatas.append(server_data.metadata)
        if global_metadata and (
            server_data.metadata is None
            or not server_data.metadata.ignore_global_metadata
        ):
            metadatas.append(global_metadata)

        header_str = "\n".join(self.build_header(self.merge_metadatas(metadatas)))

        # Now that we've built the header, we can remove it from the server data
        # This makes our cache more efficient, since metadata changes don't affect
        # the actual page contents.
        server_data = server_data.model_copy(update={"metadata": None})

        # TODO: Provide a function to automatically sniff for the client view folder
        start = time()
        try:
            ssr_html = render_ssr(
                self.ssr_path.read_text(),
                server_data,
                hard_timeout=self.hard_ssr_timeout,
            )
        except V8RuntimeError as e:
            # Try to parse the file sources and re-raise the error with the
            # maps on the current filesystem
            if self.source_map is not None:
                # parse() is a no-op if the source map is already parsed, so we can do it again
                self.source_map.parse()
                raise V8RuntimeError(self.source_map.map_exception(str(e)))
            raise e

        ssr_duration = time() - start
        if ssr_duration > self.slow_ssr_threshold:
            LOGGER.warning(f"Slow SSR render detected: {ssr_duration:.2f}s")
        else:
            LOGGER.debug(f"SSR render took {ssr_duration:.2f}s")

        # Client-side react scripts that will hydrate the server side contents on load
        server_data_json = server_data.model_dump_json()
        optional_scripts = "\n".join(
            [
                f"<script src='/static/{script_name}'></script>"
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

    def resolve_paths(self, view_base: Path):
        """
        Given the path to the root /view directory, resolve our various
        on-disk paths.

        """
        script_name = underscore(self.__class__.__name__)

        # The SSR path is going to be static
        ssr_path = view_base / "_ssr" / f"{script_name}.js"
        ssr_map_path = ssr_path.with_suffix(".js.map")
        self.ssr_path = ssr_path if ssr_path.exists() else None
        self.source_map = (
            SourceMapParser(ssr_map_path) if ssr_map_path.exists() else None
        )

        # Find the md5-converted cache path
        md5_script_pattern = re_compile(script_name + "-" + "[a-f0-9]{32}" + ".js")

        self.bundled_scripts = [
            path.name
            for path in (view_base / "_static").iterdir()
            if md5_script_pattern.match(path.name) and ".js.map" not in path.name
        ]
        LOGGER.debug(
            f"[{self.__class__.__name__}] Resolved paths... {self.bundled_scripts}"
        )

    def merge_metadatas(self, metadatas: list[Metadata]):
        """
        Merges a list of metadata objects, sorted by priority. Some fields will
        take the union (like scripts) - others will prioritize earlier entries (title).

        """
        base_metadata = Metadata()

        for metadata in metadatas:
            base_metadata.title = base_metadata.title or metadata.title

            base_metadata.metas.extend(metadata.metas)
            base_metadata.links.extend(metadata.links)

        return base_metadata
