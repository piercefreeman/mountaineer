from inspect import Parameter, signature
from typing import Callable, Type

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

from mountaineer.actions.fields import FunctionMetadata
from mountaineer.controller import ControllerBase


class ControllerDefinition(BaseModel):
    controller: ControllerBase
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

    graph: "AppGraph"
    """
    Back-reference to the parent graph that this controller belongs to.
    """

    model_config = {
        "arbitrary_types_allowed": True,
    }

    def get_url_for_metadata(self, metadata: FunctionMetadata):
        return f"{self.url_prefix}/{metadata.function_name.strip('/')}"


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
        controller_api: APIRouter,
        generate_controller_html: Callable,
        controller_url_prefix: str,
        view_router: APIRouter,
    ):
        controller_definition = ControllerDefinition(
            controller=controller,
            router=controller_api,
            view_route=generate_controller_html,
            url_prefix=controller_url_prefix,
            render_router=view_router,
            graph=self,
        )
        controller._definition = controller_definition

        self.controllers.append(controller_definition)

    def get_definitions_for_cls(self, cls: Type[ControllerBase]):
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
