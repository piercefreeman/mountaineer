from functools import wraps
from typing import Callable
from fastapi.staticfiles import StaticFiles

from fastapi import APIRouter, FastAPI
from inflection import underscore
from pydantic import BaseModel
from pathlib import Path

from filzl.actions import (
    FunctionActionType,
    fuse_metadata_to_response_typehint,
    init_function_metadata,
)
from filzl.controller import ControllerBase
from filzl.render import RenderBase


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

    def __init__(self, view_root: Path):
        self.app = FastAPI()
        self.controllers: list[ControllerDefinition] = []
        self.view_root = view_root

        self.internal_api_prefix = "/internal/api"

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

        # The controller superclass needs to be initialized before it's
        # registered into the application
        if not hasattr(controller, "initialized"):
            raise ValueError(
                f"You must call super().__init__() on {controller} before it can be registered."
            )

        # We need to passthrough the API of the render function to the FastAPI router so it's called properly
        # with the dependency injection kwargs
        @wraps(controller.render)
        def generate_controller_html(*args, **kwargs):
            return controller._generate_html(*args, **kwargs)

        # Strip the return annotations from the function, since we just intend to return an HTML page
        # and not a JSON response
        if not hasattr(generate_controller_html, "__wrapped__"):
            raise ValueError(
                "Unable to clear wrapped typehint, no wrapped function found."
            )

        return_model = generate_controller_html.__wrapped__.__annotations__.pop(
            "return", None
        )
        if not return_model:
            raise ValueError(
                "Controller render() function must have a return type annotation"
            )

        # Validate the return model is actually a RenderBase
        if not issubclass(return_model, RenderBase):
            raise ValueError(
                "Controller render() return type annotation is not a RenderBase"
            )

        # Attach a new metadata wrapper to the original function so we can easily
        # recover it when attached to the class
        metadata = init_function_metadata(controller.render, FunctionActionType.RENDER)
        metadata.render_model = return_model

        # Directly register the rendering view
        self.app.get(controller.url)(generate_controller_html)

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
                metadata, return_model
            )
            fn.__annotations__["return"] = metadata.return_model

            metadata.url = (
                f"{controller_url_prefix}/{metadata.function_name.strip('/')}"
            )
            print(f"Registering: {metadata.url}")

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
