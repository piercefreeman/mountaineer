from fastapi import APIRouter, FastAPI
from filzl.controller import BaseController
from inflection import underscore
from functools import wraps
from filzl.sideeffects import init_function_metadata, FunctionActionType
from filzl.render import RenderBase


class AppController:
    """
    Main entrypoint

    """

    def __init__(self):
        self.app = FastAPI()
        self.controllers: list[BaseController] = []

        self.internal_api_router = APIRouter()
        self.app.include_router(self.internal_api_router, prefix="/internal/api")

    def register(self, controller: BaseController):
        """
        Register controller
        """
        self.controllers.append(controller)

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
        for _, fn, metadata in controller._get_client_functions():
            controller_api.post(f"/{metadata.function_name}")(fn)
        self.app.include_router(
            controller_api,
            prefix=f"/{underscore(self.get_controller_name(controller))}",
        )

    def get_controller_name(self, controller: BaseController):
        return controller.__class__.__name__
