from abc import ABC, abstractmethod
from importlib.metadata import PackageNotFoundError
from inspect import getmembers, isawaitable, ismethod
from pathlib import Path
from re import compile as re_compile
from time import monotonic_ns
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Generic,
    Iterable,
    Mapping,
    Optional,
    ParamSpec,
    cast,
)

from fastapi.responses import HTMLResponse
from inflection import underscore

from mountaineer.actions import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from mountaineer.config import get_config
from mountaineer.js_compiler.source_maps import SourceMapParser
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, resolve_package_path
from mountaineer.render import (
    LinkAttribute,
    MetaAttribute,
    Metadata,
    RenderBase,
    RenderNull,
    ScriptAttribute,
)
from mountaineer.ssr import V8RuntimeError, render_ssr

if TYPE_CHECKING:
    from mountaineer.app import ControllerDefinition

RenderInput = ParamSpec("RenderInput")


class ControllerBase(ABC, Generic[RenderInput]):
    url: str
    # Typically, view paths should be a relative path to the local
    # Paths are only used if you need to specify an absolute path to another
    # file on disk
    view_path: str | ManagedViewPath

    bundled_scripts: list[str]

    # Upon registration, the AppController will mount a wrapper
    # with state metadata
    definition: Optional["ControllerDefinition"] = None

    def __init__(
        self, slow_ssr_threshold: float = 0.1, hard_ssr_timeout: float | None = 10.0
    ):
        """
        One Controller should be created for every frontend page in your webapp. Clients can override
        this `__init__` function so long as they call `super().__init__()` at the start of their init
        to setup the internal handlers.

        :param slow_ssr_threshold: Each python process has a single V8 runtime associated with
        it, so SSR rendering can become a bottleneck if it requires processing. We log a warning
        if we detect that an SSR render took longer than this threshold.
        :param hard_ssr_timeout: If the SSR render takes longer than this threshold, we will
        automatically kill the V8 runtime and return an error to the client. This is useful for
        avoiding blocking the reset of the server process if the React render logic hangs.

        """
        # Injected by the build framework
        self.bundled_scripts: list[str] = []
        self.initialized = True
        self.slow_ssr_threshold = slow_ssr_threshold
        self.hard_ssr_timeout = hard_ssr_timeout
        self.source_map: SourceMapParser | None = None

        self.view_base_path: Path | None = None
        self.ssr_path: Path | None = None

        self.resolve_paths()

    @abstractmethod
    def render(
        self, *args: RenderInput.args, **kwargs: RenderInput.kwargs
    ) -> RenderBase | None | Coroutine[Any, Any, RenderBase | None]:
        """
        Render provides the raw data payload that will be sent to the frontend on initial
        render and during any sideeffect update. In most cases, you should return a RenderBase
        instance. If you have no data to display you can also return None.

        This function must be explicitly typehinted with your response type, which allows the
        AppController to generate the correct TypeScript types for the frontend:

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

        Render functions accept any number of arguments and keyword arguments, following the FastAPI
        route parameter style. This includes query parameters, path parameters, and request bodies.

        ```python
        class MyController:
            url = "/my-url/{path_param}"

            def render(
                self,
                query_param: str,
                path_param: int,
                dependency: MyDependency = Depends(MyDependency),
            ) -> MyServerData:
                ...
        ```

        :return: A RenderBase instance or None
        """
        pass

    async def _generate_html(self, *args, global_metadata: Metadata | None, **kwargs):
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

        header_str = "\n".join(self._build_header(self._merge_metadatas(metadatas)))

        ssr_html = self._generate_ssr_html(server_data)

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

    def _generate_ssr_html(self, server_data: RenderBase) -> str:
        self.resolve_paths()

        if not self.ssr_path:
            # Try to resolve the path dynamically now
            raise ValueError("No SSR path set for this controller")

        # Now that we've built the header, we can remove it from the server data
        # This makes our cache more efficient, since metadata changes don't affect
        # the actual page contents.
        server_data = server_data.model_copy(update={"metadata": None})

        # TODO: Provide a function to automatically sniff for the client view folder
        start = monotonic_ns()
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

        ssr_duration = (monotonic_ns() - start) / 1e9
        if ssr_duration > self.slow_ssr_threshold:
            LOGGER.warning(f"Slow SSR render detected: {ssr_duration:.2f}s")
        else:
            LOGGER.debug(f"SSR render took {ssr_duration:.2f}s")

        return cast(str, ssr_html)

    def _build_header(self, metadata: Metadata) -> list[str]:
        """
        Builds the header for this controller. Returns the list of tags that will be injected into the
        <head> tag of the rendered page.

        """
        tags: list[str] = []

        def format_optional_keys(payload: Mapping[str, str | bool | None]) -> str:
            attributes: list[str] = []
            for key, value in payload.items():
                if value is None:
                    continue
                elif isinstance(value, bool):
                    # Boolean attributes can just be represented by just their key
                    if value:
                        attributes.append(key)
                    else:
                        continue
                else:
                    attributes.append(f'{key}="{value}"')
            return " ".join(attributes)

        if metadata.title:
            tags.append(f"<title>{metadata.title}</title>")

        for meta_definition in metadata.metas:
            meta_attributes = {
                "name": meta_definition.name,
                "content": meta_definition.content,
                **meta_definition.optional_attributes,
            }
            tags.append(f"<meta {format_optional_keys(meta_attributes)} />")

        for script_definition in metadata.scripts:
            script_attributes: dict[str, str | bool] = {
                "src": script_definition.src,
                "async": script_definition.asynchronous,
                "defer": script_definition.defer,
                **script_definition.optional_attributes,
            }
            tags.append(f"<script {format_optional_keys(script_attributes)}></script>")

        for link_definition in metadata.links:
            link_attributes = {
                "rel": link_definition.rel,
                "href": link_definition.href,
                **link_definition.optional_attributes,
            }
            tags.append(f"<link {format_optional_keys(link_attributes)} />")

        return tags

    def _get_client_functions(self) -> Iterable[tuple[str, Callable, FunctionMetadata]]:
        """
        Returns all of the client-callable functions for this controller. Right now we force
        client accessible functions to either be wrapped by @sideeffect or @passthrough.

        """
        # Iterate over all the functions in this class and see which ones have a _metadata attribute
        # We specifically traverse through the MRO, except the last one (object class)
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

    def resolve_paths(self, view_base: Path | None = None, force: bool = True) -> bool:
        """
        Typically used internally by the Mountaineer build pipeline. Calling this function
        sets the active `view_base` of the frontend project, which allows us to resolve the
        built javascripts that are required for this controller.

        :return: Whether we have found all necessary files and fully updated the controller state.

        """
        if not force and self.view_base_path is not None:
            return False

        # Try to resolve the view base path from the global config
        if view_base is None:
            try:
                config = get_config()
                if config.PACKAGE:
                    view_base = Path(resolve_package_path(config.PACKAGE)) / "views"
            except (ValueError, PackageNotFoundError):
                # Config isn't registered yet
                pass

        if view_base is None:
            # Unable to resolve, no-op
            return False

        script_name = underscore(self.__class__.__name__)
        self.view_base_path = view_base

        # We'll update this bool if we can't find any dependencies
        found_dependencies = True

        # The SSR path is going to be static
        ssr_path = view_base / "_ssr" / f"{script_name}.js"
        if ssr_path.exists():
            self.ssr_path = ssr_path
            ssr_map_path = ssr_path.with_suffix(".js.map")
            self.source_map = (
                SourceMapParser(ssr_map_path) if ssr_map_path.exists() else None
            )
        else:
            found_dependencies = False

        # Find the md5-converted cache path
        md5_script_pattern = re_compile(script_name + "-" + "[a-f0-9]{32}" + ".js")
        if (view_base / "_static").exists():
            self.bundled_scripts = [
                path.name
                for path in (view_base / "_static").iterdir()
                if md5_script_pattern.match(path.name) and ".js.map" not in path.name
            ]
            if not self.bundled_scripts:
                found_dependencies = False
            LOGGER.debug(
                f"[{self.__class__.__name__}] Resolved paths... {self.bundled_scripts}"
            )
        else:
            found_dependencies = False

        return found_dependencies

    def _merge_metadatas(self, metadatas: list[Metadata]):
        """
        Merges a list of metadata objects, sorted by priority. Some fields will
        take the union (like scripts) - others will prioritize earlier entries (title).

        """
        # Keep track of the unique values we've seen already to ensure that we are:
        # 1. Only including unique values
        # 2. Ranking them in the same order as they were provided
        metas: set[MetaAttribute] = set()
        links: set[LinkAttribute] = set()
        scripts: set[ScriptAttribute] = set()

        final_metadata = Metadata()

        for metadata in metadatas:
            final_metadata.title = final_metadata.title or metadata.title

            final_metadata.metas.extend(
                [element for element in metadata.metas if element not in metas]
            )
            final_metadata.links.extend(
                [element for element in metadata.links if element not in links]
            )
            final_metadata.scripts.extend(
                [element for element in metadata.scripts if element not in scripts]
            )

            metas |= set(metadata.metas)
            links |= set(metadata.links)
            scripts |= set(metadata.scripts)

        return final_metadata
