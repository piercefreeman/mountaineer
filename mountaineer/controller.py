from abc import ABC, abstractmethod
from importlib.metadata import PackageNotFoundError
from inspect import getmembers, ismethod
from pathlib import Path
from re import compile as re_compile
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Generic,
    Iterable,
    Optional,
    ParamSpec,
)

from inflection import underscore

from mountaineer.actions import (
    FunctionActionType,
    FunctionMetadata,
    get_function_metadata,
)
from mountaineer.client_compiler.source_maps import SourceMapParser
from mountaineer.config import get_config
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, resolve_package_path
from mountaineer.render import (
    RenderBase,
)

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

        # Set by the path resolution layer
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

        self.view_base_path = view_base

        # We'll update this bool if we can't find any dependencies
        found_dependencies = True

        # The SSR path is going to be static
        ssr_path = view_base / "_ssr" / f"{self.script_name}.js"
        if ssr_path.exists():
            self.ssr_path = ssr_path
            ssr_map_path = ssr_path.with_suffix(".js.map")
            self.source_map = (
                SourceMapParser(ssr_map_path) if ssr_map_path.exists() else None
            )
        else:
            found_dependencies = False

        # Find the md5-converted cache path
        md5_script_pattern = re_compile(self.script_name + "-" + "[a-f0-9]{32}" + ".js")
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

    @property
    def script_name(self):
        return underscore(self.__class__.__name__)
