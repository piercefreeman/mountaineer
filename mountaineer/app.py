from collections import defaultdict
from functools import partial, wraps
from hashlib import md5
from inspect import Signature, isawaitable, isclass, signature
from json import JSONDecodeError, dumps as json_dumps, loads as json_loads
from pathlib import Path
from re import match as re_match
from time import monotonic_ns
from typing import Any, Callable, Type, overload

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError as RequestValidationErrorRaw
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from inflection import underscore
from pydantic import BaseModel
from starlette.routing import BaseRoute

from mountaineer.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    get_function_metadata,
    init_function_metadata,
)
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.client_compiler.base import APIBuilderBase
from mountaineer.client_compiler.build_metadata import BuildMetadata
from mountaineer.config import ConfigBase
from mountaineer.constants import DEFAULT_STATIC_DIR
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.exceptions import (
    APIException,
    RequestValidationError,
    RequestValidationFailure,
)
from mountaineer.graph.app_graph import AppGraph, ControllerDefinition, ControllerRoute
from mountaineer.graph.cache import (
    ControllerDevCache,
    ControllerProdCache,
    DevCacheConfig,
    ProdCacheConfig,
)
from mountaineer.logging import LOGGER, debug_log_artifact
from mountaineer.paths import ManagedViewPath, resolve_package_path
from mountaineer.plugin import MountaineerPlugin
from mountaineer.render import Metadata, RenderBase, RenderNull
from mountaineer.ssr import render_ssr


class ExceptionSchema(BaseModel):
    status_code: int
    schema_name: str
    schema_name_long: str
    schema_value: dict[str, Any]

    model_config = {
        "extra": "forbid",
    }


class AppController:
    """
    Main entrypoint of a project web application.

    """

    builders: list[APIBuilderBase]

    global_metadata: Metadata | None
    """
    Metadata that's injected into every page. This is useful for setting
    global stylesheets and scripts. It's also useful for setting fallback
    metadata if it isn't overloaded by individual pages like setting a page title.

    """

    config: ConfigBase | None
    """
    The configuration object for the application. This is the main place
    to place runtime configuration values that might be changed across
    environments. One instance is registered as a global singleton and cached
    within the AppController class as well.

    """

    app: FastAPI
    """
    Internal FastAPI application instance used by Mountaineer. Exposed to add
    API-only endpoints and middleware.

    """

    fastapi_args: dict[str, Any] | None
    """
    Override or add additional arguments to the FastAPI constructor. See
    the FastAPI [documentation](https://fastapi.tiangolo.com/reference/fastapi/) for
    the attributes of this constructor.

    """

    live_reload_port: int
    """
    Port to use for live reloading of the webserver. This will be used to create a websocket connection
    to the browser to trigger a reload when the frontend has updates. By default
    we will bind to port 0 to guarantee an open system port.

    """

    graph: AppGraph
    """
    Graph of the app that represents the hierarchy of controllers and their
    dependencies.

    """

    internal_api_prefix: str
    """
    URL prefix used for the action APIs that are auto-generated through @passthrough
    and @sideeffect decorators.

    """

    def __init__(
        self,
        *,
        name: str = "Mountaineer Webapp",
        version: str = "0.1.0",
        view_root: Path | None = None,
        global_metadata: Metadata | None = None,
        custom_builders: list[APIBuilderBase] | None = None,
        config: ConfigBase | None = None,
        fastapi_args: dict[str, Any] | None = None,
    ):
        self.app = FastAPI(title=name, version=version, **(fastapi_args or {}))
        self.graph = AppGraph()
        self.name = name
        self.version = version
        self.global_metadata = global_metadata
        self.builders = custom_builders if custom_builders else []

        # If this flag is present, we will re-raise this error during render()
        # so users can see the error in the browser.
        # This is useful for debugging, but should not be used in production
        self._build_exception: Exception | None = None

        # Follow our managed path conventions
        if config is not None and config.PACKAGE is not None:
            package_path = resolve_package_path(config.PACKAGE)
            self._view_root = ManagedViewPath.from_view_root(package_path / "views")
        elif view_root is not None:
            self._view_root = ManagedViewPath.from_view_root(view_root)
        else:
            raise ValueError(
                "You must provide either a config.package or a view_root to the AppController"
            )

        # Check our view directory is valid
        self._validate_view(self._view_root)

        # The act of instantiating the config should register it with the
        # global settings registry. We keep a reference to it so we can shortcut
        # to the user-defined settings later, but this is largely optional.
        self.config = config

        self.internal_api_prefix = "/internal/api"

        # The static directory has to exist before we try to mount it
        static_dir = self._view_root.get_managed_static_dir()

        # Mount the view_root / _static directory, since we'll need
        # this for the client mounted view files
        self.app.mount(
            DEFAULT_STATIC_DIR,
            StaticFiles(directory=str(static_dir)),
            name="static",
        )

        self.app.exception_handler(RequestValidationErrorRaw)(
            self._parse_validation_exception
        )
        self.app.exception_handler(APIException)(self._handle_exception)

        self.app.openapi = self.generate_openapi  # type: ignore

        self.path_to_layout: dict[str, ControllerDefinition] = {}

        self.live_reload_port: int = 0

    def _validate_view(self, view_root: ManagedViewPath):
        """
        Validates the view directory setup, including checking React version compatibility.

        :param view_root: The root directory containing the view files
        :raises ValueError: If any validation checks fail
        """
        package_json_path = view_root / "package.json"
        if not package_json_path.exists():
            LOGGER.warning(
                f"package.json not found at {package_json_path}. Please ensure your project has a valid package.json file."
            )
            return

        try:
            package_json = json_loads(package_json_path.read_text())
            react_version = package_json.get("dependencies", {}).get("react", "")
            if not react_version:
                react_version = package_json.get("devDependencies", {}).get("react", "")

            if not react_version:
                raise ValueError("React dependency not found in package.json")

            # Extract version number from semver string (e.g. "^19.0.0" -> "19.0.0")
            version_match = re_match(r"[\^~]?(\d+)\.\d+\.\d+", react_version)
            if not version_match:
                LOGGER.warning(f"Invalid React version format: {react_version}")
                return

            major_version = int(version_match.group(1))
            if major_version < 19:
                LOGGER.warning(
                    f"React version {react_version} is not supported. This application requires React 19.0 or higher."
                )
        except JSONDecodeError:
            LOGGER.warning(f"Invalid JSON in {package_json_path}")
        except Exception as e:
            LOGGER.warning(f"Error checking React version: {str(e)}")

    def register(self, controller: ControllerBase | MountaineerPlugin):
        """
        Register a new controller. This will:

        - Mount the html of the controller to the main application service
        - Mount all actions (ie. @sideeffect and @passthrough decorated functions) to their public API

        :param controller: The controller instance that should be added to your webapp. The class accepts a full
        instance instead of just a class, so you're able to perform any kind of runtime initialization of the
        kwarg args that you need before it's registered.

        """
        if isinstance(controller, ControllerBase):
            self._register_controller(controller)
        elif isinstance(controller, MountaineerPlugin):
            self._register_plugin(controller)
        else:
            raise ValueError(f"Unknown controller type: {type(controller)}")

    def _register_controller(self, controller: ControllerBase):
        # This allows each view to avoid having to find these on disk, as well as gives
        # a proactive error if any view will be unable to render when their script files
        # are missing
        controller.resolve_paths(self._view_root, force=True)

        controller_definition = self._register_controller_common(
            controller,
            dev_enabled=self.development_enabled,
        )

        # If we just registered a layout controller, we need to add it to the graph
        if isinstance(controller, LayoutControllerBase):
            self.path_to_layout[str(controller.full_view_path.absolute())] = (
                controller_definition
            )

        # We might have added a fresh root path to the graph with this addition, so we should
        # scan the file path for layout files that might wrap this controller
        layout_paths = self._collect_layouts_for_controller(controller)

        child_controller = controller_definition
        for layout_path in layout_paths:
            layout_path = layout_path.absolute()
            layout, layout_is_new = self._get_layout_for_path(layout_path)
            self.graph.link_controllers(layout, child_controller)
            child_controller = layout

            # If the layout is not new, by definition we have already linked its relationships
            # so we can skip the rest of the loop
            if not layout_is_new:
                break

        updated_controllers = self.graph.merge_hierarchy_signatures(
            controller_definition
        )
        for controller_definition in updated_controllers:
            self._remount_controller(controller_definition)

    def _register_plugin(self, plugin: MountaineerPlugin):
        for controller in plugin.get_controllers():
            if isinstance(controller.view_path, str):
                controller.view_path = (
                    ManagedViewPath.from_view_root(plugin.view_root)
                    / controller.view_path
                )

            # This should find our precompiled static and ssr files
            controller._scripts_prefix = f"/static_plugins/{plugin.name}"
            controller._build_enabled = False

            controller.resolve_paths(plugin.view_root, force=True)

            # Unlike standard controllers, plugins are expected to have precompiled scripts
            # at all times
            if not controller._ssr_path:
                raise ValueError(
                    f"Controller {controller} was not able to find SSR scripts for plugin {plugin.name}"
                )
            if not controller._bundled_scripts:
                raise ValueError(
                    f"Controller {controller} was not able to find bundled scripts for plugin {plugin.name}"
                )

            # Dev mode is disabled so the app is forced to load the full built javascript
            # bundle when the pages load. This doesn't affect how the controller API endpoints
            # are mounted or otherwise how the view controller is added to the app.
            self._register_controller_common(controller, dev_enabled=False)

        # Mount the view_root / _static directory, since we'll need
        # this for the client mounted view files
        self.app.mount(
            f"/static_plugins/{plugin.name}",
            StaticFiles(directory=str(plugin.view_root / "_static")),
            name=f"static-{plugin.name}",
        )

    def _register_controller_common(
        self, controller: ControllerBase, dev_enabled: bool = True
    ):
        # Since the controller name is used to build dependent files, we ensure
        # that we only register one controller of a given name
        if self.graph.get_definitions_for_cls(controller.__class__):
            raise ValueError(
                f"Controller with name {controller.__class__.__name__} already registered."
            )

        # Register a stub for the new controller, which will be updated with its
        # router preferences later
        controller_definition = self.graph.register(
            controller,
            route=None,
            cache_args=(
                DevCacheConfig(
                    node_modules_path=self._view_root / "node_modules",
                    # This will be 0 on first mount, until the build pipeline overrides
                    # the app param
                    live_reload_port=self.live_reload_port,
                )
                if dev_enabled
                else ProdCacheConfig()
            ),
        )

        # If we're running in production, sniff for the script files ahead of time so we
        # can fail early if they're missing
        if not dev_enabled:
            controller_definition.resolve_cache()

        # The controller superclass needs to be initialized before it's
        # registered into the application
        if not hasattr(controller, "initialized"):
            raise ValueError(
                f"You must call super().__init__() on {controller} before it can be registered."
            )

        # We need to passthrough the API of the render function to the FastAPI router so it's called properly
        # with the dependency injection kwargs
        generate_controller_html = wraps(controller.render)(
            partial(
                self._generate_controller_html,
                dev_enabled=dev_enabled,
                controller_definition=controller_definition,
            )
        )

        # Strip the return annotations from the function, since we just intend to return an HTML page
        # and not a JSON response
        if not hasattr(generate_controller_html, "__wrapped__"):
            raise ValueError(
                "Unable to clear wrapped typehint, no wrapped function found."
            )

        return_model = generate_controller_html.__wrapped__.__annotations__.get(
            "return", MountaineerUnsetValue()
        )
        if isinstance(return_model, MountaineerUnsetValue):
            raise ValueError(
                "Controller render() function must have a return type annotation"
            )

        # Only the signature of the actual rendering function, not the original. We might
        # need to sniff render() again for its typehint
        generate_controller_html.__signature__ = signature(  # type: ignore
            generate_controller_html,
        ).replace(return_annotation=None)

        # Validate the return model is actually a RenderBase or explicitly marked up as None
        if not (
            return_model is None
            or (isclass(return_model) and issubclass(return_model, RenderBase))
        ):
            raise ValueError(
                "Controller render() return type annotation is not a RenderBase"
            )

        # Attach a new metadata wrapper to the original function so we can easily
        # recover it when attached to the class
        render_metadata = init_function_metadata(
            controller.render, FunctionActionType.RENDER
        )
        render_metadata.render_model = return_model

        # Register the rendering view to an isolated APIRoute, so we can keep track of its
        # the resulting router independently of the rest of the application
        # This is useful in cases where we need to do a render()->FastAPI lookup
        #
        # We only mount standard controllers, we don't expect LayoutControllers to have
        # a directly accessible URL
        if isinstance(controller, LayoutControllerBase):
            if hasattr(controller, "url"):
                raise ValueError(
                    f"LayoutControllers are not directly mountable to the router. {controller} should not have a url specified."
                )
            view_router = None
        else:
            view_router = APIRouter()
            view_router.get(controller.url)(generate_controller_html)
            self.app.include_router(view_router)
            render_metadata.register_controller_url(
                controller.__class__, controller.url
            )

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        controller_url_prefix = (
            f"{self.internal_api_prefix}/{underscore(controller.__class__.__name__)}"
        )
        for _, fn, metadata in controller._get_client_functions():
            if not metadata.get_is_raw_response():
                # We need to delay adding the typehint for each function until we are here, adding the view. Since
                # decorators run before the class is actually mounted, they're isolated from the larger class/controller
                # context that the action function is being defined within. Here since we have a global view
                # of the controller (render function + actions) this becomes trivial
                return_model = fuse_metadata_to_response_typehint(
                    metadata, controller, render_metadata.get_render_model()
                )

                # Only mount the first time we register the function, otherwise we risk overwriting
                # the same function multiple times
                if controller.__class__ not in metadata.return_models:
                    metadata.register_return_model(controller.__class__, return_model)

                # Update the signature of the internal function, which fastapi will sniff for the return declaration
                # https://github.com/tiangolo/fastapi/blob/a235d93002b925b0d2d7aa650b7ab6d7bb4b24dd/fastapi/dependencies/utils.py#L207
                # Since these are consumed immediately by FastAPI, it's okay to overwrite previously set values (in the case
                # of superclass functions that are imported by multiple subclass controllers)
                method_function: Callable = fn.__func__  # type: ignore
                method_function.__signature__ = signature(method_function).replace(  # type: ignore
                    return_annotation=return_model
                )

            action_path = f"/{metadata.function_name}"
            controller_api.post(action_path)(fn)
            function_metadata = get_function_metadata(fn)
            function_metadata.register_controller_url(
                controller.__class__, f"{controller_url_prefix}{action_path}"
            )

        # Originally we tried implementing a sub-router for the internal API that was registered in the __init__
        # But the application greedily copies all contents from the router when it's added via `include_router`, so this
        # resulted in our endpoints not being seen even after calls to `.register(). We therefore attach the new
        # controller router directly to the application, since this will trigger a new copy of the routes.
        self.app.include_router(
            controller_api,
            prefix=controller_url_prefix,
        )

        LOGGER.debug(f"Did register controller: {controller}")

        controller_definition.route = ControllerRoute(
            router=controller_api,
            view_route=generate_controller_html,
            url_prefix=controller_url_prefix,
            render_router=view_router,
        )

        return controller_definition

    async def _generate_controller_html(
        self,
        *args,
        dev_enabled: bool,
        controller_definition: ControllerDefinition,
        **kwargs,
    ):
        start = monotonic_ns()
        controller = controller_definition.controller

        # We want to render the hierarchies top-down
        direct_hierarchy = controller_definition.get_parents()
        direct_hierarchy.reverse()

        # Assemble the metadata for each controller involved in rendering this view
        # (this includes the current page and any wrapper LayoutControllers)
        render_overhead_by_controller = {}
        render_output = {}
        for node in direct_hierarchy:
            time = monotonic_ns()
            render_values = self._get_value_mask_for_signature(
                signature(node.controller.render), kwargs
            )
            server_data = node.controller.render(**render_values)
            if isawaitable(server_data):
                server_data = await server_data
            if server_data is None:
                server_data = RenderNull()
            render_overhead_by_controller[node.controller.__class__.__name__] = (
                monotonic_ns() - time
            )

            render_output[node.controller.__class__.__name__] = server_data

        # If the output of this controller's rendering is an explicit response, we should
        # just return that without any rendering
        controller_output = render_output[controller.__class__.__name__]
        if not isinstance(controller_output, RenderBase):
            return controller_output
        if controller_output.metadata and controller_output.metadata.explicit_response:
            return controller_output.metadata.explicit_response

        LOGGER.debug(
            f"Controller {controller.__class__.__name__} data acquired in {(monotonic_ns() - start) / 1e9}"
        )
        LOGGER.debug(
            f"Controller {controller.__class__.__name__} controller breakdown:\n"
            + "\n".join(
                [
                    f"{controller_name}: {overhead / 1e9}"
                    for controller_name, overhead in render_overhead_by_controller.items()
                ]
            )
        )

        # If we're in development mode, we should recompile the script on page
        # load to make sure we have the latest if there's any chance that it
        # was affected by recent code changes
        if dev_enabled:
            # Update the params to reflect the current host-time config
            if not isinstance(controller_definition.cache_args, DevCacheConfig):
                raise ValueError("Dev cache is not a DevCacheConfig")
            controller_definition.cache_args.live_reload_port = self.live_reload_port

            # We delay the cache resolution until we need it, so we don't need to
            # pay the cost of building the cache if we're not in dev mode
            dev_cache = controller_definition.resolve_cache()
            if not isinstance(dev_cache, ControllerDevCache):
                raise ValueError("Dev cache is not a ControllerDevCache")

            LOGGER.debug(f"Compiled dev scripts in {(monotonic_ns() - start) / 1e9}")
            html = self.compile_html(
                dev_cache.cached_server_script,
                controller_output,
                render_output,
                inline_client_script=dev_cache.cached_client_script,
                external_client_imports=None,
                sourcemap=dev_cache.cached_server_sourcemap,
            )
        else:
            # Production payload
            prod_cache = controller_definition.resolve_cache()
            if not isinstance(prod_cache, ControllerProdCache):
                raise ValueError("Prod cache is not a ControllerProdCache")

            html = self.compile_html(
                prod_cache.cached_server_script,
                controller_output,
                render_output,
                inline_client_script=None,
                external_client_imports=[
                    f"{controller._scripts_prefix}/{script_name}"
                    for script_name in controller._bundled_scripts
                ],
                sourcemap=prod_cache.cached_server_sourcemap,
            )

        LOGGER.debug(
            f"Controller {controller.__class__.__name__} load time took {(monotonic_ns() - start) / 1e9}"
        )
        return html

    @overload
    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: str,
        external_client_imports: None,
        sourcemap: str | None,
    ): ...

    @overload
    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: None,
        external_client_imports: list[str],
        sourcemap: str | None,
    ): ...

    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: str | None = None,
        external_client_imports: list[str] | None = None,
        sourcemap: str | None = None,
    ):
        """
        Compiles the HTML for a given page, with all the controller-returned
        values hydrated into the page.

        """
        header_str: str
        if page_metadata.metadata:
            metadata = page_metadata.metadata
            if not metadata.ignore_global_metadata and self.global_metadata:
                metadata = metadata.merge(self.global_metadata)
            header_str = "\n".join(
                metadata.build_header(build_metadata=self.get_build_metadata())
            )
        else:
            if self.global_metadata:
                metadata = self.global_metadata
                header_str = "\n".join(
                    metadata.build_header(build_metadata=self.get_build_metadata())
                )
            else:
                header_str = ""

        # Client-side react scripts that will hydrate the server side contents on load
        server_data_json = {
            render_key: context.model_dump(mode="json")
            for render_key, context in all_render.items()
        }

        ssr_html = render_ssr(
            server_script,
            server_data_json,
            # TODO: Update to build param
            hard_timeout=10,
            sourcemap=sourcemap,
        )

        # Before building up the inline client script, log it to the temp directory
        # so we can inspect it in the debugger
        if inline_client_script is not None:
            debug_log_artifact("inline_client", "js", inline_client_script)

        client_import: str
        if inline_client_script:
            # We need to escape these inline. Otherwise we will close the parent script tag
            # prematurely and break the page.
            inline_client_script = inline_client_script.replace(
                "</script>", "<\\/script>"
            )

            # When we're running in debug mode, we just import
            # the script into each page so we can pick up on the latest changes

            # Wrap client-side code in an immediately invoked function expression (IIFE)
            # to isolate variables from the global scope and prevent conflicts with browser
            # built-in properties (e.g., 'chrome' in Chrome browser, 'safari' in Safari).
            # This prevents "duplicate variable" errors when client code defines variables
            # that match browser globals.
            client_import = f"""<script type='module' type='text/javascript'>
                (function() {{
                    {inline_client_script}
                }})();
                </script>"""
        elif external_client_imports:
            # This will point to our minified bundle that will in-turn import the other
            # common dependencies
            # Module types are required for browsers to use the import syntax
            # https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules
            # All major browsers have had support since 2018
            client_import = "\n".join(
                [
                    f"<script type='module' src='{import_path}'></script>"
                    for import_path in external_client_imports
                ]
            )
        else:
            raise ValueError("Invalid client script import")

        page_contents = f"""
        <html>
        <head>
        {header_str}
        </head>
        <body>
        <div id="root">{ssr_html}</div>
        <script type="text/javascript">
        var SERVER_DATA = {json_dumps(server_data_json)};
        </script>
        {client_import}
        </body>
        </html>
        """

        return HTMLResponse(page_contents)

    def _collect_layouts_for_controller(
        self, controller: ControllerBase
    ) -> list[ManagedViewPath]:
        """
        Recursively parse the parent paths to find the first layout (if any)

        We go up until the view root.

        Resolve the path to the real underlying system path, necessary for /private/var
        and /private symlinking in tmp paths

        Returns the path where result[0] is the closest layout, and result[-1] is the furthest

        """
        full_view_path = controller.full_view_path.resolve().absolute()
        current_path = full_view_path.realpath()
        package_root = full_view_path.get_root_link().realpath()

        found_layouts: list[ManagedViewPath] = []

        while current_path != package_root:
            # We should never get to the OS root
            if str(current_path) == "/":
                raise ValueError(
                    f"View path ({full_view_path}) is not within the package root: {package_root}"
                )

            layout_file = current_path / "layout.tsx"
            if layout_file.exists():
                # Never create a self-referential layout
                # This can happen with layout controllers that will also find their
                # own layout.tsx file
                if layout_file.absolute() != full_view_path:
                    found_layouts.append(layout_file)

            current_path = current_path.parent

        return found_layouts

    def _get_layout_for_path(
        self, layout_path: Path
    ) -> tuple[ControllerDefinition, bool]:
        """
        Gets an existing layout for a given path. If no layout exists, we will
        create a new one.

        :returns: A tuple of the layout controller and a boolean indicating if it was newly created

        """
        layout_path = layout_path.resolve().absolute()
        if str(layout_path) in self.path_to_layout:
            return self.path_to_layout[str(layout_path)], False

        # Synthetic layout controllers let us use the same code handling that we
        # use for explicit controllers, but without having to define a new class.
        # The name needs to be deterministic so it can resolve to the same path
        # during view building and production hosting
        layout_name = f"Layout_{md5(str(layout_path).encode()).hexdigest()}"
        new_layout = type(
            layout_name,
            (LayoutControllerBase,),
            {
                "view_path": layout_path,
            },
        )
        LOGGER.debug(f"Creating synthetic layout {layout_name} for {layout_path}")
        new_definition = self.graph.register(new_layout(), route=None, cache_args=None)
        self.path_to_layout[str(layout_path)] = new_definition
        return new_definition, True

    def _remount_controller(self, target_controller: ControllerDefinition):
        """
        Re-mount the controller exactly as it was first mounted. Works around limitations
        in fastapi where the router is not updated if the controller is mounted
        to the same path twice.

        """
        if not target_controller.route or not target_controller.route.render_router:
            return

        LOGGER.debug(f"Remounting {target_controller.controller.__class__.__name__}")

        # Clear the previous definition before re-adding it
        # Both the app route is required (for the actual page resolution) and the render router
        # (to avoid conflicts in the OpenAPI generation)
        for route_list in [
            self.app.routes,
            target_controller.route.render_router.routes,
        ]:
            for route in list(route_list):
                if (
                    isinstance(route, APIRoute)
                    and route.path == target_controller.controller.url
                    and route.methods == {"GET"}
                ):
                    route_list.remove(route)

        target_controller.route.render_router.get(target_controller.controller.url)(
            target_controller.route.view_route
        )

        self.app.include_router(target_controller.route.render_router)

    def invalidate_view(self, path: Path):
        """
        After an on-disk change of a given path, we should clear all current
        script caches in development so we rebuild with the latest changes.

        Since we don't parse TypeScript import dependencies, we take an aggressive
        approach and clear all development caches when any view file changes.
        This ensures that shared components and common files are properly recompiled
        across all controllers that might import them.
        """
        path = path.resolve().absolute()

        # Only invalidate if the changed file is within our view root
        try:
            path.relative_to(self._view_root.resolve().absolute())
        except ValueError:
            # File is outside our view root, ignore it
            LOGGER.debug(f"Ignoring file change outside view root: {path}")
            return

        # In development mode, clear all controller caches since any view file
        # could potentially be imported by any controller
        if self.development_enabled:
            cleared_controllers: list[ControllerDefinition] = []

            for controller_definition in self.graph.controllers:
                # Only clear caches that are in development mode
                if isinstance(controller_definition.cache_args, DevCacheConfig):
                    if controller_definition.cache is not None:
                        controller_definition.clear_cache(recursive=False)
                        cleared_controllers.append(controller_definition)

            controller_names = [
                controller.controller.__class__.__name__
                for controller in cleared_controllers
            ]
            LOGGER.debug(
                f"Invalidated all development caches for {len(cleared_controllers)} controllers due to file change: {path}"
            )
            LOGGER.debug(f"Cleared caches for: {controller_names}")
        else:
            LOGGER.debug(f"Skipping cache invalidation in production mode for: {path}")

    async def _handle_exception(self, request: Request, exc: APIException):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.internal_model.model_dump(),
        )

    async def _parse_validation_exception(
        self, request: Request, exc: RequestValidationErrorRaw
    ):
        raise RequestValidationError(
            errors=[
                RequestValidationFailure(
                    error_type=error["type"],
                    location=error["loc"],
                    message=error["msg"],
                    value_input=error["input"],
                )
                for error in exc.errors()
            ]
        )

    def _get_value_mask_for_signature(
        self,
        signature: Signature,
        values: dict[str, Any],
    ):
        # Assume the values match the parameters specified in the signature
        passthrough_names = {
            parameter.name for parameter in signature.parameters.values()
        }
        return {
            name: value for name, value in values.items() if name in passthrough_names
        }

    def generate_openapi(self, routes: list[BaseRoute] | None = None):
        """
        Bundle custom user exceptions in the OpenAPI schema. By default
        endpoints just include the 422 Validation Error, but this allows
        for custom derived user methods.

        """
        openapi_base = get_openapi(
            title=self.name,
            version=self.version,
            routes=(routes if routes is not None else self.app.routes),
        )

        #
        # Exception injection
        #

        exceptions_by_url: dict[str, list[ExceptionSchema]] = {}
        for controller_definition in self.graph.controllers:
            for (
                _,
                _,
                metadata,
            ) in controller_definition.controller._get_client_functions():
                url = controller_definition.get_url_for_metadata(metadata)
                # Not included in the specified routes, we should ignore this controller
                if url not in openapi_base["paths"]:
                    continue

                exceptions_models = metadata.get_exception_models()
                if not exceptions_models:
                    continue

                exceptions_by_url[url] = [
                    self._format_exception_model(exception_model)
                    for exception_model in exceptions_models
                ]

        # Users are allowed to reference the same schema name multiple times so long
        # as they have the same value. If they use conflicting values we'll have
        # to use the long name instead of the short module name to avoid conflicting
        # schema definitions.
        schema_names_to_long: defaultdict[str, set[str]] = defaultdict(set)
        for exception_payloads in exceptions_by_url.values():
            for payload in exception_payloads:
                schema_names_to_long[payload.schema_name].add(payload.schema_name_long)

        duplicate_schema_names = {
            schema_name
            for schema_name, schema_name_longs in schema_names_to_long.items()
            if len(schema_name_longs) > 1
        }

        for url, exception_payloads in exceptions_by_url.items():
            existing_status_codes: set[int] = set()

            for payload in exception_payloads:
                # Validate the exception state doesn't override existing values
                # Status codes are local to this particular endpoint but schema names
                # are global because they're placed in the global components section
                if payload.status_code in existing_status_codes:
                    raise ValueError(
                        f"Duplicate status code {payload.status_code} for {url}"
                    )

                schema_name = (
                    payload.schema_name
                    if payload.schema_name not in duplicate_schema_names
                    else payload.schema_name_long
                )

                other_definitions = {
                    definition_name: self._update_ref_path(definition)
                    for definition_name, definition in payload.schema_value.pop(
                        "$defs", {}
                    ).items()
                }
                openapi_base["components"]["schemas"].update(other_definitions)
                openapi_base["components"]["schemas"][schema_name] = (
                    self._update_ref_path(payload.schema_value)
                )

                # All actions are "posts" by definition
                openapi_base["paths"][url]["post"]["responses"][
                    str(payload.status_code)
                ] = {
                    "description": f"Custom Error: {payload.schema_name}",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                }

                existing_status_codes.add(payload.status_code)

        return openapi_base

    def _format_exception_model(self, model: Type[APIException]) -> ExceptionSchema:
        # By default all fields are optional. Since we are sending them
        # from the server we are guaranteed they will either be explicitly
        # provided or fallback to their defaults
        json_schema = model.InternalModel.model_json_schema()
        json_schema["required"] = list(json_schema["properties"].keys())

        return ExceptionSchema(
            status_code=model.status_code,
            schema_name=model.InternalModel.__name__,
            schema_name_long=f"{model.InternalModel.__module__}.{model.InternalModel.__name__}",
            schema_value=json_schema,
        )

    def _update_ref_path(self, schema: Any):
        """
        The $ref values that come out of the model schema are tied to #/defs instead
        of the #/components/schemas. This function updates the schema to use the
        correct prefix for the final OpenAPI schema.

        """
        if isinstance(schema, dict):
            new_schema: dict[str, Any] = {}
            for key, value in schema.items():
                if key == "$ref":
                    schema_name = value.split("/")[-1]
                    new_schema[key] = f"#/components/schemas/{schema_name}"
                    continue
                elif key == "additionalProperties":
                    # If the value is "False", we need to remove the key
                    if value is False:
                        continue

                new_schema[key] = self._update_ref_path(value)
            return new_schema
        elif isinstance(schema, list):
            return [self._update_ref_path(value) for value in schema]
        else:
            return schema

    def get_build_metadata(self):
        """
        Will cache the build metadata in production but not in development, since
        we expect production developments will compile their metadata once and then
        use it for all endpoints.

        """
        if not self.development_enabled:
            # Determine if we've already cached the build
            if hasattr(self, "_build_metadata"):
                return getattr(self, "_build_metadata")

        metadata_path = self._view_root.get_managed_metadata_dir() / "metadata.json"
        if not metadata_path.exists():
            return None
        self._build_metadata = BuildMetadata.model_validate_json(
            metadata_path.read_text()
        )
        return self._build_metadata

    @property
    def development_enabled(self):
        return not self.config or self.config.ENVIRONMENT == "development"
