from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Callable, Type

from fastapi import APIRouter

from mountaineer.actions.fields import FunctionMetadata
from mountaineer.controller import ControllerBase
from mountaineer.controller_layout import LayoutControllerBase
from mountaineer.graph.cache import (
    ControllerDevCache,
    ControllerProdCache,
    DevCacheConfig,
    ProdCacheConfig,
)
from mountaineer.logging import LOGGER


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
class ControllerDefinition:
    controller: ControllerBase
    route: ControllerRoute | None

    cache: ControllerDevCache | ControllerProdCache | None = None
    cache_args: DevCacheConfig | ProdCacheConfig | None = None

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
        if not self.route:
            raise ValueError(
                f"Controller {self.controller} has no route. This should never happen."
            )

        return f"{self.route.url_prefix}/{metadata.function_name.strip('/')}"

    def get_parents(self):
        parents: list[ControllerDefinition] = []
        current_node: ControllerDefinition | None = self
        while current_node is not None:
            parents.append(current_node)
            current_node = current_node.parent
        return parents

    def get_hierarchy_view_paths(self):
        layouts = self.get_parents()
        layouts.reverse()
        return [
            [str(layout.controller.full_view_path.absolute()) for layout in layouts]
        ]

    def resolve_cache(self):
        if self.cache_args is None:
            raise ValueError("Cache args are not set for this controller")

        if self.cache:
            return self.cache

        if isinstance(self.cache_args, DevCacheConfig):
            self.cache = ControllerDevCache.resolve_dev_cache(self, self.cache_args)
            return self.cache
        elif isinstance(self.cache_args, ProdCacheConfig):
            self.cache = ControllerProdCache.resolve_prod_cache(self, self.cache_args)
            return self.cache
        else:
            raise ValueError("Invalid cache args")

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
        cache_args: DevCacheConfig | ProdCacheConfig | None,
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
                cache_args=cache_args,
            )
            self.controllers.append(controller_definition)

        # All the attributes even if we didn't find one
        controller_definition.controller = controller
        controller_definition.route = route
        controller_definition.graph = self
        controller_definition.cache_args = cache_args

        # Set the back-reference to the controller definition in case the controller
        # needs to access the graph directly
        controller._definition = controller_definition
        return controller_definition

    def link_controllers(
        self, parent: ControllerDefinition, child: ControllerDefinition
    ):
        # This doesn't guarantee that the structure won't become a cyclic graph, but it's a good
        # and fast first-pass check that future graph traversal code won't loop indefinitely.
        if parent == child:
            raise ValueError("Parent and child cannot be the same controller")

        parent.children.append(child)
        child.parent = parent

        LOGGER.debug(
            f"Will link {parent.controller.__class__.__name__} -> {child.controller.__class__.__name__}"
        )

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

        # Remove duplicates by in-memory hash because the actual objects are not hashable
        unique_updated: dict[int, ControllerDefinition] = {}
        for updated_definition in updated_definitions:
            if updated_definition is None:
                continue
            unique_updated[id(updated_definition)] = updated_definition

        return list(unique_updated.values())

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
