from inspect import Parameter, signature
from typing import Callable, Type

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.actions.fields import FunctionMetadata
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.logging import LOGGER
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path


class ControllerRoute(BaseModel):
    router: APIRouter

    # URL prefix to the root of the server
    url_prefix: str

    view_route: Callable
    """
    Dynamically generated function that actually renders the html content
    This is a hybrid between render() and _generate_html()

    """

    render_router: APIRouter | None
    """
    Render router is provided for all pages, only None for layouts that can't
    be independently rendered as a webpage

    """

    model_config = {
        "arbitrary_types_allowed": True,
    }


class ControllerDevCache(BaseModel):
    """
    Cache of the controller definition for the given controller.
    """

    cached_server_script: str
    cached_server_sourcemap: str | None = None

    cached_client_script: str
    cached_client_sourcemap: str | None = None


class ControllerProdCache(BaseModel):
    cached_server_script: str
    cached_server_sourcemap: str | None = None


class ControllerDefinition(BaseModel):
    controller: ControllerBase
    route: ControllerRoute | None
    cache: ControllerDevCache | ControllerProdCache | None = None

    graph: "AppGraph"
    """
    Back-reference to the parent graph that this controller belongs to.
    """

    parent: "ControllerDefinition | None" = None
    """
    Parent layout controller that this controller is a child of.
    """

    children: list["ControllerDefinition"] = []
    """
    Child layout controllers that this layout controller modifies.
    """

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def get_url_for_metadata(self, metadata: FunctionMetadata):
        return f"{self.url_prefix}/{metadata.function_name.strip('/')}"

    def get_parents(self):
        parents: list[ControllerDefinition] = []
        current_node: ControllerDefinition | None = self
        while current_node is not None:
            parents.append(current_node)
            current_node = current_node.parent
        return parents

    def resolve_prod_cache(self) -> ControllerProdCache:
        if isinstance(self.cache, ControllerProdCache):
            return self.cache

        if not self.controller._ssr_path:
            raise ValueError(
                f"Controller {self.controller} was not able to find its server-side script on disk. Make sure to run your `build` CLI before starting your webapp."
            )

        if not self.controller._ssr_path.exists():
            raise ValueError(
                f"Controller {self.controller} was not able to find its server-side script on disk. Make sure to run your `build` CLI before starting your webapp."
            )

        self.cache = ControllerProdCache(
            cached_server_script=self.controller._ssr_path.read_text()
        )
        return self.cache

    def resolve_dev_cache(self) -> ControllerDevCache:
        layouts = self.get_parents()
        layouts.reverse()
        view_paths = [[str(layout.controller.view_path) for layout in layouts]]

        # Find tsconfig.json in the parent directories of the view paths
        tsconfig_path = find_tsconfig(view_paths)

        cached_server_script: str
        cached_server_sourcemap: str | None
        cached_client_script: str
        cached_client_sourcemap: str | None

        if not self.cache.cached_server_script:
            LOGGER.debug(
                f"Compiling server-side bundle for {self.controller.__class__.__name__}: {view_paths}"
            )
            (
                script_payloads,
                sourcemap_payloads,
            ) = mountaineer_rs.compile_independent_bundles(
                view_paths,
                str((self._view_root / "node_modules").resolve().absolute()),
                "development",
                0,
                str(get_static_path("live_reload.ts").resolve().absolute()),
                True,
                tsconfig_path,
            )
            cached_server_script = script_payloads[0]
            cached_server_sourcemap = sourcemap_payloads[0]
        else:
            cached_server_script = self.cache.cached_server_script
            cached_server_sourcemap = self.cache.cached_server_sourcemap

        if not self.cache.cached_client_script:
            LOGGER.debug(
                f"Compiling client-side bundle for {self.controller.__class__.__name__}: {view_paths}"
            )
            script_payloads, _ = mountaineer_rs.compile_independent_bundles(
                view_paths,
                str((self._view_root / "node_modules").resolve().absolute()),
                "development",
                self.live_reload_port,
                str(get_static_path("live_reload.ts").resolve().absolute()),
                False,
                tsconfig_path,
            )
            cached_client_script = script_payloads[0]
            cached_client_sourcemap = sourcemap_payloads[0]
        else:
            cached_client_script = self.cache.cached_client_script
            cached_client_sourcemap = self.cache.cached_client_sourcemap

        self.cache = ControllerDevCache(
            cached_server_script=cached_server_script,
            cached_server_sourcemap=cached_server_sourcemap,
            cached_client_script=cached_client_script,
            cached_client_sourcemap=cached_client_sourcemap,
        )
        return self.cache


class AppGraph:
    """
    Defined API that represents the graph of the app. Since controllers are arranged
    in a layout view with some parents and children, this class allows for easy
    traversal of the app.

    """

    controllers: list[ControllerDefinition]
    """
    Mounted controllers that are used to render the web application. Add
    a new one through `.register()`.

    """

    def __init__(self):
        self.controllers: list[ControllerDefinition] = []

    def register(
        self,
        controller: ControllerBase,
        route: ControllerRoute | None,
    ):
        controller_definition: ControllerDefinition | None = None

        # Layout controllers are unique - if we're re-registering a layout controller,
        # we need to remove any existing definitions that are children of this controller
        if isinstance(controller, LayoutControllerBase):
            for controller_definition in self.controllers:
                if (
                    controller_definition.controller.view_path.absolute()
                    == controller.view_path.absolute()
                ):
                    controller_definition = controller_definition
                    break

        if not controller_definition:
            controller_definition = ControllerDefinition(
                controller=controller,
                route=route,
                graph=self,
            )
            self.controllers.append(controller_definition)
        else:
            controller_definition.controller = controller
            controller_definition.route = route
            controller_definition.graph = self

        # Set the back-reference to the controller definition in case the controller
        # needs to access the graph directly
        controller._definition = controller_definition
        return controller_definition

    def get_definitions_for_cls(
        self, cls: Type[ControllerBase]
    ) -> list[ControllerDefinition]:
        """
        Get all controller definitions for a given controller class. We use name here
        since a lot of dependent logic is parameterized on the name (linkGenerator, etc).

        """
        return [
            controller_definition
            for controller_definition in self.controllers
            if controller_definition.controller.__class__.__name__ == cls.__name__
        ]

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

        updated_definitions: list[ControllerDefinition | None] = []

        for parent in parent_definitions:
            updated_definitions.append(
                self._merge_render_signatures(
                    controller_definition,
                    reference_controller=parent,
                )
            )
        for child in child_definitions:
            updated_definitions.append(
                self._merge_render_signatures(
                    child,
                    reference_controller=controller_definition,
                )
            )

        return [
            updated_definition
            for updated_definition in updated_definitions
            if updated_definition is not None
        ]

    def _merge_render_signatures(
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
            return target_controller
