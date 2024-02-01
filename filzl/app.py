from functools import wraps
from inspect import isclass, signature
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from inflection import underscore
from pydantic import BaseModel

from filzl.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    init_function_metadata,
)
from filzl.annotation_helpers import FilzlUnsetValue
from filzl.client_builder.base import ClientBuilderBase
from filzl.client_builder.bundler import JavascriptBundler
from filzl.controller import ControllerBase


class ControllerDefinition(BaseModel):
    controller: ControllerBase
    router: APIRouter
    # URL prefix to the root of the server
    url_prefix: str
    # Dynamically generated function that actually renders the html content
    # This is a hybrid between render() and _generate_html()
    view_route: Callable

    model_config = {
        "arbitrary_types_allowed": True,
    }


class AppController:
    """
    Main entrypoint

    """

    builders: list[ClientBuilderBase]

    def __init__(
        self, view_root: Path, custom_builders: list[ClientBuilderBase] | None = None
    ):
        self.app = FastAPI()
        self.controllers: list[ControllerDefinition] = []
        self.view_root = view_root
        self.builders = [
            # Default builders
            JavascriptBundler(),
            # Custom builders
            *(custom_builders if custom_builders else []),
        ]

        self.internal_api_prefix = "/internal/api"

        # The static directory has to exist before we try to mount it
        (self.view_root / "_static").mkdir(exist_ok=True)

        # Mount the view_root / _static directory, since we'll need
        # this for the client mounted view files
        self.app.mount(
            "/static_js",
            StaticFiles(directory=self.view_root / "_static"),
            name="static",
        )
        print("Will mount", self.view_root / "_static")

    def register(self, controller: ControllerBase):
        """
        Register a new controller. This will:
            - Mount the html of the controller to the main application service
            - Mount all actions (ie. @sideeffect and @passthrough decorated functions) to their public API

        """
        # Update the paths now that we have access to the runtime package path
        controller.resolve_paths(self.view_root)

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
            return await controller._generate_html(*args, **kwargs)

        # Strip the return annotations from the function, since we just intend to return an HTML page
        # and not a JSON response
        if not hasattr(generate_controller_html, "__wrapped__"):
            raise ValueError(
                "Unable to clear wrapped typehint, no wrapped function found."
            )

        return_model = generate_controller_html.__wrapped__.__annotations__.get(
            "return", FilzlUnsetValue()
        )
        if isinstance(return_model, FilzlUnsetValue):
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
            or (isclass(return_model) and issubclass(return_model, BaseModel))
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
        view_router = APIRouter()
        view_router.get(controller.url)(generate_controller_html)
        render_metadata.render_router = view_router
        self.app.include_router(view_router)

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        controller_url_prefix = (
            f"{self.internal_api_prefix}/{underscore(controller.__class__.__name__)}"
        )
        for _, fn, metadata in controller._get_client_functions():
            # We need to delay adding the typehint for each function until we are here, adding the view. Since
            # decorators run before the class is actually mounted, they're isolated from the larger class/controller
            # context that the action function is being defined within. Here since we have a global view
            # of the controller (render function + actions) this becomes trivial
            metadata.return_model = fuse_metadata_to_response_typehint(
                metadata, render_metadata.get_render_model()
            )

            # Update the signature of the internal function, which fastapi will sniff for the return declaration
            # https://github.com/tiangolo/fastapi/blob/a235d93002b925b0d2d7aa650b7ab6d7bb4b24dd/fastapi/dependencies/utils.py#L207
            method_function: Callable = fn.__func__  # type: ignore
            method_function.__signature__ = signature(method_function).replace(  # type: ignore
                return_annotation=metadata.return_model
            )

            metadata.url = (
                f"{controller_url_prefix}/{metadata.function_name.strip('/')}"
            )

            controller_api.post(f"/{metadata.function_name}")(fn)

        # Originally we tried implementing a sub-router for the internal API that was registered in the __init__
        # But the application greedily copies all contents from the router when it's added via `include_router`, so this
        # resulted in our endpoints not being seen even after calls to `.register(). We therefore attach the new
        # controller router directly to the application, since this will trigger a new copy of the routes.
        self.app.include_router(
            controller_api,
            prefix=controller_url_prefix,
        )

        self.controllers.append(
            ControllerDefinition(
                controller=controller,
                router=controller_api,
                view_route=generate_controller_html,
                url_prefix=controller_url_prefix,
            )
        )
