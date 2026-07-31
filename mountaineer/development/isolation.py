import importlib
from traceback import format_exception
from typing import TYPE_CHECKING

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.logging import log_time_duration, setup_internal_logger
from mountaineer.plugin import MountaineerPlugin

if TYPE_CHECKING:
    from mountaineer_exceptions.controllers.exception_controller import (
        ExceptionController,
    )

LOGGER = setup_internal_logger(__name__)


class IsolatedAppContext:
    """Load one application controller inside a Python runtime process."""

    def __init__(
        self,
        module_name: str,
        controller_name: str,
        use_dev_exceptions: bool = True,
    ):
        self.module_name = module_name
        self.controller_name = controller_name
        self.use_dev_exceptions = use_dev_exceptions
        self.app_controller: AppController | None = None
        self.exception_controller: "ExceptionController | None" = None
        self.js_compiler: APIBuilder | None = None

    @classmethod
    def from_webcontroller(cls, webcontroller: str, use_dev_exceptions: bool = True):
        module_name, separator, controller_name = webcontroller.partition(":")
        if not separator or not module_name or not controller_name:
            raise ValueError("webcontroller must look like package.module:controller")
        return cls(
            module_name=module_name,
            controller_name=controller_name,
            use_dev_exceptions=use_dev_exceptions,
        )

    async def initialize_app_state(self) -> None:
        controller = getattr(
            importlib.import_module(self.module_name),
            self.controller_name,
        )
        if not isinstance(controller, AppController):
            raise TypeError(
                f"{self.module_name}:{self.controller_name} is not an AppController"
            )

        self.app_controller = controller
        self.mount_exceptions(controller)
        self.js_compiler = APIBuilder(controller)

    def mount_exceptions(self, app_controller: AppController) -> None:
        """Register Mountaineer's development exception page plugin."""
        if not self.use_dev_exceptions:
            LOGGER.debug("Dev exceptions are disabled, skipping...")
            return

        try:
            from mountaineer_exceptions.controllers.exception_controller import (
                ExceptionController,
            )
            from mountaineer_exceptions.views import get_core_view_path
        except ImportError as error:
            LOGGER.warning("mountaineer-exceptions is unavailable: %s", error)
            return

        plugin = MountaineerPlugin(
            name="mountaineer-exceptions",
            controllers=[ExceptionController],
            view_root=get_core_view_path(""),
        )
        app_controller.register(plugin)
        self.exception_controller = next(
            controller
            for controller in plugin.get_controllers()
            if isinstance(controller, ExceptionController)
        )
        app_controller.app.exception_handler(Exception)(self.handle_dev_exception)

    async def handle_dev_exception(self, request: Request, exc: Exception):
        """Render the development exception page for GET requests."""
        LOGGER.error("Handling dev exception: %s", exc)
        if self.exception_controller is None:
            raise RuntimeError("Exception controller not initialized")
        if request.method != "GET":
            raise exc

        with log_time_duration("Exception parsing took", warning_threshold=0.5):
            parsed_exception = (
                self.exception_controller.traceback_parser.parse_exception(exc)
            )
        with log_time_duration(
            "Exception controller took to render the exception page",
            warning_threshold=0.5,
        ):
            return await self.exception_controller._definition.route.view_route(  # type: ignore
                exception=str(exc),
                stack="".join(format_exception(exc)),
                parsed_exception=parsed_exception,
            )
