from inspect import Parameter, signature
from typing import Callable, Type, cast

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel
from dataclasses import dataclass, field

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.actions.fields import FunctionMetadata
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.logging import LOGGER
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path
from mountaineer.paths import ManagedViewPath

@dataclass(kw_only=True)
class ControllerRoute:
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

@dataclass(kw_only=True)
class ControllerDevCache:
    """
    Cache of the controller definition for the given controller.
    """

    cached_server_script: str
    cached_server_sourcemap: str | None = None

    cached_client_script: str
    cached_client_sourcemap: str | None = None


@dataclass(kw_only=True)
class ControllerProdCache:
    cached_server_script: str
    cached_server_sourcemap: str | None = None

@dataclass(kw_only=True)
class ControllerDefinition:
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

    children: list["ControllerDefinition"] = field(default_factory=list)
    """
    Child layout controllers that this layout controller modifies.
    """

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

    def resolve_dev_cache(
        self,
        *,
        node_modules_path: ManagedViewPath,
        live_reload_port: int,
    ) -> ControllerDevCache:
        # If we already have the correct cache, we can return it
        if self.cache and isinstance(self.cache, ControllerDevCache):
            return self.cache

        layouts = self.get_parents()
        layouts.reverse()
        view_paths = [[str(layout.controller.full_view_path) for layout in layouts]]

        # Find tsconfig.json in the parent directories of the view paths
        tsconfig_path = find_tsconfig(view_paths)

        print(f"Server-side bundle paths: {self.controller.__class__.__name__} {view_paths} {node_modules_path}")

        LOGGER.debug(
            f"Compiling server-side bundle for {self.controller.__class__.__name__}: {view_paths}"
        )
        (
            script_payloads,
            sourcemap_payloads,
        ) = mountaineer_rs.compile_independent_bundles(
            view_paths,
            str(node_modules_path.resolve().absolute()),
            "development",
            0,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            True,
            tsconfig_path,
        )
        cached_server_script = cast(str, script_payloads[0])
        cached_server_sourcemap = cast(str | None, sourcemap_payloads[0])

        LOGGER.debug(
            f"Compiling client-side bundle for {self.controller.__class__.__name__}: {view_paths}"
        )
        script_payloads, _ = mountaineer_rs.compile_independent_bundles(
            view_paths,
            str(node_modules_path.resolve().absolute()),
            "development",
            live_reload_port,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            False,
            tsconfig_path,
        )
        cached_client_script = cast(str, script_payloads[0])
        cached_client_sourcemap = cast(str | None, sourcemap_payloads[0])

        self.cache = ControllerDevCache(
            cached_server_script=cached_server_script,
            cached_server_sourcemap=cached_server_sourcemap,
            cached_client_script=cached_client_script,
            cached_client_sourcemap=cached_client_sourcemap,
        )
        return self.cache

    def clear_cache(self, recursive: bool = True):
        self.cache = None

        if recursive:
            for child in self.children:
                child.clear_cache(recursive=True)


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
        # it's likely because we have a concrete implementation of a synthetic controller that
        # we created based on the disk hierarchy alone
        if isinstance(controller, LayoutControllerBase):
            for definition in self.controllers:
                if (
                    definition.controller.full_view_path.absolute()
                    == controller.full_view_path.absolute()
                ):
                    controller_definition = definition
                    break

        if not controller_definition:
            controller_definition = ControllerDefinition(
                controller=controller,
                route=route,
                graph=self,
            )
            self.controllers.append(controller_definition)

        # All the attributes even if we didn't find one
        controller_definition.controller = controller
        controller_definition.route = route
        controller_definition.graph = self

        # Set the back-reference to the controller definition in case the controller
        # needs to access the graph directly
        controller._definition = controller_definition
        return controller_definition

    def link_controllers(self, parent: ControllerDefinition, child: ControllerDefinition):
        # This doesn't guarantee that the structure won't become a cyclic graph, but it's a good
        # and fast first-pass check that future graph traversal code won't loop indefinitely.
        if parent == child:
            raise ValueError("Parent and child cannot be the same controller")

        parent.children.append(child)
        child.parent = parent

        print(f"Will link {parent.controller.__class__.__name__} -> {child.controller.__class__.__name__}")

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

        # TODO: Improve the algorithm here - right now this is too slow in a large application
        # since we re-traverse multiple

        def explore_children(current_node: ControllerDefinition):
            for child in current_node.children:
                yield child
                yield from explore_children(child)

        def explore_parents(current_node: ControllerDefinition):
            while current_node.parent is not None:
                yield current_node.parent
                current_node = current_node.parent

        parents = list(explore_parents(controller_definition))
        children = list(explore_children(controller_definition))

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
        if not reference_controller.route or not target_controller.route:
            return

        reference_signature = signature(reference_controller.route.view_route)
        target_signature = signature(target_controller.route.view_route)

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

        target_controller.route.view_route.__signature__ = target_signature.replace(  # type: ignore
            parameters=target_parameters
        )

        return target_controller
