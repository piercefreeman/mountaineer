from fastapi import APIRouter, FastAPI
from filzl.controller import BaseController
from inflection import underscore

class AppController:
    """
    Main entrypoint

    """
    def __init__(self):
        self.app = FastAPI()

        self.internal_api_router = APIRouter()
        self.app.include_router(self.internal_api_router, prefix="/internal/api")

    def register(self, controller: BaseController):
        """
        Register controller
        """
        # Directly register the rendering view
        self.app.get(controller.url)(controller._generate_html)

        # Create a wrapper router for each controller to hold the side-effects
        controller_api = APIRouter()
        for _, fn, metadata in controller._get_client_functions():
            controller_api.post(f"/{metadata.function_name}")
        self.app.include_router(controller_api, prefix=f"/{underscore(self.get_controller_name(controller))})

    def get_controller_name(self, controller: BaseController):
        return controller.__name__
