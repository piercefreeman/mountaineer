from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from inspect import Parameter, Signature, isawaitable, isclass, signature
from json import dumps as json_dumps
from pathlib import Path
from time import monotonic_ns
from typing import Any, Callable, Optional, Type, cast, overload
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from inflection import underscore
from pydantic import BaseModel
from starlette.routing import BaseRoute

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    init_function_metadata,
)
from mountaineer.actions.fields import FunctionMetadata
from mountaineer.annotation_helpers import MountaineerUnsetValue
from mountaineer.client_compiler.base import ClientBuilderBase
from mountaineer.config import ConfigBase
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.exceptions import APIException
from mountaineer.logging import LOGGER
from mountaineer.paths import ManagedViewPath, resolve_package_path
from mountaineer.render import Metadata, RenderBase, RenderNull
from mountaineer.ssr import render_ssr
from mountaineer.static import get_static_path


class ControllerDefinition(BaseModel):
    controller: ControllerBase
    router: APIRouter
    # URL prefix to the root of the server
    url_prefix: str
    # Dynamically generated function that actually renders the html content
    # This is a hybrid between render() and _generate_html()
    view_route: Callable
    # Render router is provided for all pages, only None for layouts that can't
    # be independently rendered as a webpage
    render_router: APIRouter | None

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def get_url_for_metadata(self, metadata: FunctionMetadata):
        return f"{self.url_prefix}/{metadata.function_name.strip('/')}"


class ExceptionSchema(BaseModel):
    status_code: int
    schema_name: str
    schema_name_long: str
    schema_value: dict[str, Any]

    model_config = {
        "extra": "forbid",
    }


@dataclass
class LayoutElement:
    id: UUID

    # Can be null if a layout doesn't have a path
    controller: ControllerBase | None

    # Absolute path to the tsx / jsx entrypoint
    path: Path

    # Only models direct parent layouts at the next highest layer
    # Traverse these to find the full layout hierarchy
    parent: Optional["LayoutElement"] = None
    children: list["LayoutElement"] = field(default_factory=list)

    cached_server_script: str | None = None
    cached_client_script: str | None = None


class AppController:
    """
    Main entrypoint of a project web application.

    """

    builders: list[ClientBuilderBase]
    global_metadata: Metadata | None

    def __init__(
        self,
        *,
        name: str = "Mountaineer Webapp",
        version: str = "0.1.0",
        view_root: Path | None = None,
        global_metadata: Metadata | None = None,
        custom_builders: list[ClientBuilderBase] | None = None,
        config: ConfigBase | None = None,
        fastapi_args: dict[str, Any] | None = None,
    ):
        """
        :param global_metadata: Script and meta will be applied to every
            page rendered by this application. Title will only be applied
            if the page does not already have a title set.
        :param config: Application global configuration.

        """
        self.app = FastAPI(title=name, version=version, **(fastapi_args or {}))
        self.controllers: list[ControllerDefinition] = []
        self.controller_names: set[str] = set()
        self.name = name
        self.version = version
        self.global_metadata = global_metadata
        self.builders = custom_builders if custom_builders else []

        # If this flag is present, we will re-raise this error during render()
        # so users can see the error in the browser.
        # This is useful for debugging, but should not be used in production
        self.build_exception: Exception | None = None

        # Follow our managed path conventions
        if config is not None and config.PACKAGE is not None:
            package_path = resolve_package_path(config.PACKAGE)
            self.view_root = ManagedViewPath.from_view_root(package_path / "views")
        elif view_root is not None:
            self.view_root = ManagedViewPath.from_view_root(view_root)
        else:
            raise ValueError(
                "You must provide either a config.package or a view_root to the AppController"
            )

        # The act of instantiating the config should register it with the
        # global settings registry. We keep a reference to it so we can shortcut
        # to the user-defined settings later, but this is largely optional.
        self.config = config

        self.internal_api_prefix = "/internal/api"

        # The static directory has to exist before we try to mount it
        static_dir = self.view_root.get_managed_static_dir()

        # Mount the view_root / _static directory, since we'll need
        # this for the client mounted view files
        self.app.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="static",
        )

        self.app.exception_handler(APIException)(self.handle_exception)

        self.app.openapi = self.generate_openapi  # type: ignore

        # Edges that link the hierarchy together
        self.hierarchy_paths: dict[Path, LayoutElement] = {}

        self.live_reload_port: int = 0

    def register(self, controller: ControllerBase):
        """
        Register a new controller. This will:

        - Mount the html of the controller to the main application service
        - Mount all actions (ie. @sideeffect and @passthrough decorated functions) to their public API

        :param controller: The controller instance that should be added to your webapp. The class accepts a full
        instance instead of just a class, so you're able to perform any kind of runtime initialization of the
        kwarg args that you need before it's registered.

        """
        # Since the controller name is used to build dependent files, we ensure
        # that we only register one controller of a given name
        controller_name = controller.__class__.__name__
        if controller_name in self.controller_names:
            raise ValueError(
                f"Controller with name {controller_name} already registered."
            )

        # Update the paths now that we have access to the runtime package path
        controller_node = self.update_hierarchy(known_controller=controller)

        # The controller superclass needs to be initialized before it's
        # registered into the application
        if not hasattr(controller, "initialized"):
            raise ValueError(
                f"You must call super().__init__() on {controller} before it can be registered."
            )

        # We need to passthrough the API of the render function to the FastAPI router so it's called properly
        # with the dependency injection kwargs
        @wraps(controller.render)
        async def generate_controller_html(*args, **kwargs):
            start = monotonic_ns()

            # Figure out which controller we're rendering
            controller_node, direct_hierarchy = self._view_hierarchy_for_controller(
                controller,
            )

            direct_hierarchy.reverse()
            view_paths = [[str(layout.path) for layout in direct_hierarchy]]

            # Assemble the metadata for each controller involved in rendering this view
            # (this includes the current page and any wrapper LayoutControllers)
            render_overhead_by_controller = {}
            render_output = {}
            for node in direct_hierarchy:
                # Must be a layout-only component
                if not node.controller:
                    continue

                time = monotonic_ns()
                render_values = self.get_value_mask_for_signature(
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
            if (
                controller_output.metadata
                and controller_output.metadata.explicit_response
            ):
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
            if self.config and self.config.ENVIRONMENT == "development":
                # Caching the build files saves about 0.3 on every load
                # during development
                start = monotonic_ns()
                if not controller_node.cached_server_script:
                    controller_node.cached_server_script = (
                        mountaineer_rs.compile_independent_bundles(
                            view_paths,
                            str(self.view_root / "node_modules"),
                            "development",
                            0,
                            str(get_static_path("live_reload.ts").resolve().absolute()),
                            True,
                        )[0]
                    )
                if not controller_node.cached_client_script:
                    controller_node.cached_client_script = (
                        mountaineer_rs.compile_independent_bundles(
                            view_paths,
                            str(self.view_root / "node_modules"),
                            "development",
                            self.live_reload_port,
                            str(get_static_path("live_reload.ts").resolve().absolute()),
                            False,
                        )[0]
                    )
                LOGGER.debug(
                    f"Compiled dev scripts in {(monotonic_ns() - start) / 1e9}"
                )

                html = self.compile_html(
                    cast(str, controller_node.cached_server_script),
                    controller_output,
                    render_output,
                    inline_client_script=cast(
                        str, controller_node.cached_client_script
                    ),
                    external_client_imports=None,
                )
            else:
                # Production payload
                html = self.compile_html(
                    cast(str, controller_node.cached_server_script),
                    controller_output,
                    render_output,
                    inline_client_script=None,
                    external_client_imports=[
                        f"/static/{script_name}"
                        for script_name in controller.bundled_scripts
                    ],
                )

            LOGGER.debug(
                f"Controller {controller.__class__.__name__} load time took {(monotonic_ns() - start) / 1e9}"
            )
            return html

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

        # If we're running in production, sniff for the script files ahead of time and
        # attach them to the controller
        # This allows each view to avoid having to find these on disk, as well as gives
        # a proactive error if any view will be unable to render when their script files
        # are missing
        if self.config and self.config.ENVIRONMENT != "development":
            controller.resolve_paths(self.view_root, force=True)
            if not controller.bundled_scripts:
                raise ValueError(
                    f"Controller {controller} was not able to find its scripts on disk. Make sure to run your `build` CLI before starting your webapp."
                )
            if not controller.ssr_path:
                raise ValueError(
                    f"Controller {controller} was not able to find its server-side script on disk. Make sure to run your `build` CLI before starting your webapp."
                )

            controller_node.cached_server_script = controller.ssr_path.read_text()

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

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        controller_url_prefix = (
            f"{self.internal_api_prefix}/{underscore(controller.__class__.__name__)}"
        )
        for _, fn, metadata in controller._get_client_functions():
            openapi_extra: dict[str, Any] = {
                "is_raw_response": metadata.get_is_raw_response()
            }

            if not metadata.get_is_raw_response():
                # We need to delay adding the typehint for each function until we are here, adding the view. Since
                # decorators run before the class is actually mounted, they're isolated from the larger class/controller
                # context that the action function is being defined within. Here since we have a global view
                # of the controller (render function + actions) this becomes trivial
                metadata.return_model = fuse_metadata_to_response_typehint(
                    metadata, controller, render_metadata.get_render_model()
                )

                # Update the signature of the internal function, which fastapi will sniff for the return declaration
                # https://github.com/tiangolo/fastapi/blob/a235d93002b925b0d2d7aa650b7ab6d7bb4b24dd/fastapi/dependencies/utils.py#L207
                method_function: Callable = fn.__func__  # type: ignore
                method_function.__signature__ = signature(method_function).replace(  # type: ignore
                    return_annotation=metadata.return_model
                )

                # Pass along relevant tags in the OpenAPI meta struct
                # This will appear in the root key of the API route, at the same level of "summary" and "parameters"
                if metadata.get_media_type():
                    openapi_extra["media_type"] = metadata.get_media_type()

            controller_api.post(
                f"/{metadata.function_name}", openapi_extra=openapi_extra
            )(fn)

        # Originally we tried implementing a sub-router for the internal API that was registered in the __init__
        # But the application greedily copies all contents from the router when it's added via `include_router`, so this
        # resulted in our endpoints not being seen even after calls to `.register(). We therefore attach the new
        # controller router directly to the application, since this will trigger a new copy of the routes.
        self.app.include_router(
            controller_api,
            prefix=controller_url_prefix,
        )

        LOGGER.debug(f"Did register controller: {controller_name}")

        controller_definition = ControllerDefinition(
            controller=controller,
            router=controller_api,
            view_route=generate_controller_html,
            url_prefix=controller_url_prefix,
            render_router=view_router,
        )
        controller.definition = controller_definition

        self.controllers.append(controller_definition)
        self.controller_names.add(controller_name)

        self.merge_hierarchy_signatures(controller_definition)

    def _view_hierarchy_for_controller(self, controller: ControllerBase):
        """
        Determines the nested parent layouts for the given controller, according
        to the currently mounted LayoutElement hierarchy.

        """
        # Figure out which controller we're rendering
        controller_node = next(
            node
            for node in self.hierarchy_paths.values()
            if node.controller == controller
        )
        # print("CONTROLLER", controller_node)

        # We need to figure out the layout controllers that should
        # wrap this controller
        direct_hierarchy: list[LayoutElement] = []
        current_node: LayoutElement | None = controller_node
        while current_node is not None:
            if current_node in direct_hierarchy:
                raise ValueError(f"Recursive layout detected: {current_node.path}")
            direct_hierarchy.append(current_node)
            current_node = current_node.parent

        return controller_node, direct_hierarchy

    def merge_hierarchy_signatures(self, controller_definition: ControllerDefinition):
        # We should:
        # Update _this_ controller with anything in the above hierarchy (known layout controllers)
        # Update _child_ controller with this view (in the case that this definition is
        # a layout controller)
        node = next(
            node
            for node in self.hierarchy_paths.values()
            if node.controller == controller_definition.controller
        )

        def explore_children(node):
            for child in node.children:
                yield child
                yield from explore_children(child)

        def explore_parents(current_node):
            while current_node.parent is not None:
                yield current_node.parent
                current_node = current_node.parent

        parents = list(explore_parents(node))
        children = list(explore_children(node))

        parent_controllers = [node.controller for node in parents if node.controller]
        children_controllers = [node.controller for node in children if node.controller]

        parent_definitions = [
            controller_definition
            for controller_definition in self.controllers
            if controller_definition.controller in parent_controllers
        ]
        child_definitions = [
            controller_definition
            for controller_definition in self.controllers
            if controller_definition.controller in children_controllers
        ]

        for parent in parent_definitions:
            self.merge_render_signatures(
                controller_definition,
                reference_controller=parent,
            )
        for child in child_definitions:
            self.merge_render_signatures(
                child,
                reference_controller=controller_definition,
            )

    def invalidate_view(self, path: Path):
        """
        After an on-disk change of a given path, we should clear its current
        script cache so we rebuild with the latest changes. We should also clear
        out any nested children - so in the case of a layout change, we refresh
        all of its subpages.

        """
        if path.resolve().absolute() not in self.hierarchy_paths:
            # We have changed a path that isn't tracked as part of our
            # hierarchy. This is most likely a dependent file (like a component) that
            # is imported by some pages. Some early POC work has handled this explicitly
            # via parsing the whole project import dependences, but this introduces unnecessary
            # complexity when fresh-compile times are only ~0.3s and we only impact on dev.
            #
            # We allow components to clear all cached scripts and allow the next page
            # refresh to handle the rebuild.
            for path in list(self.hierarchy_paths):
                self.invalidate_view(path)

            return

        LOGGER.debug(f"Will invalidate path and children controllers: {path}")

        def _invalidate_node(node: LayoutElement):
            node.cached_server_script = None
            node.cached_client_script = None

            for child in node.children:
                _invalidate_node(child)

        node = self.hierarchy_paths[path]
        _invalidate_node(node)

    @overload
    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: str,
        external_client_imports: None,
    ):
        ...

    @overload
    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: None,
        external_client_imports: list[str],
    ):
        ...

    def compile_html(
        self,
        server_script: str,
        page_metadata: RenderBase,
        all_render: dict[str, RenderBase],
        *,
        inline_client_script: str | None = None,
        external_client_imports: list[str] | None = None,
    ):
        # header_str = "\n".join(self._build_header(self._merge_metadatas(metadatas)))
        if page_metadata.metadata:
            metadata = page_metadata.metadata
            if not metadata.ignore_global_metadata and self.global_metadata:
                metadata = metadata.merge(self.global_metadata)
            header_str = "\n".join(metadata.build_header())

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
        )

        client_import: str
        if inline_client_script:
            # When we're running in debug mode, we just import
            # the script into each page so we can pick up on the latest changes
            client_import = (
                f"<script type='text/javascript'>{inline_client_script}</script>"
            )
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
        const SERVER_DATA = {json_dumps(server_data_json)};
        </script>
        {client_import}
        </body>
        </html>
        """

        return HTMLResponse(page_contents)

    def update_hierarchy(
        self,
        *,
        known_controller: ControllerBase | None = None,
        known_view_path: ManagedViewPath | None = None,
    ):
        """
        When we register a new element, we need to:

        - Find if there are any on-disk layouts that have been defined. We add these greedily, before
        we know if they're backed by a layout controller
        - Add the controller as a LayoutElement if it's new. Otherwise update the existing element

        This function is built to be invariant to the order of the updates, so we can call it multiple times
        and call it progressively as more controllers are added. It will be valid at
        any given state for the current webapp mounting.

        """
        if known_view_path is None:
            if known_controller is None:
                raise ValueError(
                    "Either new_hierarchy or known_view_path must be provided"
                )

            full_view_path = (
                self.view_root / known_controller.view_path.lstrip("/")
                if isinstance(known_controller.view_path, str)
                else known_controller.view_path
            )
            full_view_path = full_view_path.resolve().absolute()
        else:
            full_view_path = known_view_path.resolve().absolute()

        # We should only update the current definition, we don't need to re-parse its hierarchy since
        # we assume the disk layout hasn't changed
        if full_view_path in self.hierarchy_paths:
            view_element = self.hierarchy_paths[full_view_path]
            if known_controller is not None:
                view_element.controller = known_controller
            return view_element

        view_element = LayoutElement(
            id=uuid4(), controller=known_controller, path=full_view_path
        )
        self.hierarchy_paths[full_view_path] = view_element

        # Recursively parse the parent paths to find the first layout (if any)
        # We go up until the view root. We allow the update_hierarchy to capture
        # the root view path, but we don't allow it to be a layout. This allows
        # layouts to inherit other layouts
        #
        # Resolve the path to the real underlying system path, necessary for /private/var
        # and /private symlinking in tmp paths
        current_path = full_view_path.realpath()
        package_root = full_view_path.get_root_link().realpath()
        while current_path != package_root:
            # We should never get to the OS root
            if str(current_path) == "/":
                raise ValueError(
                    f"View path ({full_view_path}) is not within the package root: {package_root}"
                )

            layout_file = current_path / "layout.tsx"
            if layout_file.exists():
                LOGGER.debug(
                    f"Layout found on disk, adding link: {view_element.path} {layout_file}"
                )
                parent_layout = self.update_hierarchy(known_view_path=layout_file)

                # Never create a self-referential layout
                # This can happen with layout controllers that will also find their
                # own layout.tsx file
                if parent_layout != view_element:
                    parent_layout.children.append(view_element)
                    view_element.parent = parent_layout

                    # We should break at the nearest level, since each page
                    # can only have one direct parent
                    break

            current_path = current_path.parent

        return view_element

    async def handle_exception(self, request: Request, exc: APIException):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.internal_model.model_dump(),
        )

    def merge_render_signatures(
        self,
        target_controller: ControllerDefinition,
        *,
        reference_controller: ControllerDefinition,
    ):
        """
        Collects the signature from the "reference_controller" and replaces the active target_controller's
        render endpoint with this new signature. We require all these new parameters to be kwargs so they
        can be injected into the render function by name alone.

        """
        reference_signature = signature(reference_controller.view_route)
        target_signature = signature(target_controller.view_route)

        reference_parameters = reference_signature.parameters.values()
        target_parameters = list(target_signature.parameters.values())

        # For any additional arguments provided by the reference, inject them into
        # the target controller
        # For duplicate ones, the target controller should win
        for parameter in reference_parameters:
            if parameter.name not in target_signature.parameters:
                target_parameters.append(
                    parameter.replace(
                        kind=Parameter.KEYWORD_ONLY,
                    )
                )
            else:
                # We only throw an error if the types are different. If they're the same we assume
                # that the resolution is intended to be shared.
                target_annotation_type = target_signature.parameters[
                    parameter.name
                ].annotation
                reference_annotation_type = parameter.annotation

                if target_annotation_type != reference_annotation_type:
                    raise TypeError(
                        f"Duplicate parameter {parameter.name} in {target_controller.controller} and {reference_controller.controller}.\n"
                        f"Conflicting types: {target_annotation_type} vs {reference_annotation_type}"
                    )

        target_controller.view_route.__signature__ = target_signature.replace(  # type: ignore
            parameters=target_parameters
        )

        # Re-mount the controller exactly as it was first mounted
        if target_controller.render_router:
            # Clear the previous definition before re-adding it
            # Both the app route is required (for the actual page resolution) and the render router
            # (to avoid conflicts in the OpenAPI generation)
            for route_list in [self.app.routes, target_controller.render_router.routes]:
                for route in list(route_list):
                    if (
                        isinstance(route, APIRoute)
                        and route.path == target_controller.controller.url
                        and route.methods == {"GET"}
                    ):
                        route_list.remove(route)

            target_controller.render_router.get(target_controller.controller.url)(
                target_controller.view_route
            )
            self.app.include_router(target_controller.render_router)

    def get_value_mask_for_signature(
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
        for controller_definition in self.controllers:
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
                openapi_base["components"]["schemas"][
                    schema_name
                ] = self._update_ref_path(payload.schema_value)

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

    def definition_for_controller(
        self, controller: ControllerBase
    ) -> ControllerDefinition:
        for controller_definition in self.controllers:
            if controller_definition.controller == controller:
                return controller_definition
        raise ValueError(f"Controller {controller} not found")
