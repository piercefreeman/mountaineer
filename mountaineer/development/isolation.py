import asyncio
import importlib
from multiprocessing import Process
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception
from typing import Any, List

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.controllers.exception_controller import (
    ExceptionController,
)
from mountaineer.development.hotreload import HotReloader
from mountaineer.development.messages import (
    AsyncMessageBroker,
    BootupMessage,
    BuildJsMessage,
    BuildUseServerMessage,
    ErrorResponse,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponseError,
    ReloadResponseSuccess,
    RestartServerMessage,
    ShutdownMessage,
    SuccessResponse,
)
from mountaineer.development.uvicorn import UvicornThread
from mountaineer.logging import LOGGER


class IsolatedAppContext(Process):
    """
    Isolated process that manages the app controller, server, and compilation.
    This provides a clean slate for module reloading and compilation.
    """

    def __init__(
        self,
        package: str,
        module_name: str,
        controller_name: str,
        host: str | None,
        port: int,
        live_reload_port: int | None,
        message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
    ):
        super().__init__()
        self.package = package
        self.module_name = module_name
        self.controller_name = controller_name
        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port
        self.message_broker = message_broker
        self.webservice_thread: UvicornThread | None = None

    def run(self):
        """Main worker process loop"""
        try:
            # Process messages until shutdown
            while True:
                message_id, message = self.message_broker.message_queue.get()

                try:
                    response: SuccessResponse | ErrorResponse
                    if isinstance(message, BootupMessage):
                        response = self.bootstrap()
                    elif isinstance(message, ReloadModulesMessage):
                        response = self.handle_module_reload(message.module_names)
                    elif isinstance(message, RestartServerMessage):
                        response = self.restart_server()
                    elif isinstance(message, BuildJsMessage):
                        response = self.handle_js_build(message.updated_js)
                    elif isinstance(message, BuildUseServerMessage):
                        response = self.handle_build_use_server()
                    elif isinstance(message, ShutdownMessage):
                        response = SuccessResponse()
                    self.message_broker.response_queue.put((message_id, response))
                except Exception as e:
                    LOGGER.info(
                        f"Isolated app context failed: {e}, continuing...",
                        exc_info=True,
                    )
                    self.message_broker.response_queue.put(
                        (
                            message_id,
                            ErrorResponse(
                                exception=str(e), traceback="".join(format_exception(e))
                            ),
                        )
                    )
        except Exception as e:
            LOGGER.error(f"Isolated app context failed: {e}", exc_info=True)
        finally:
            if self.webservice_thread:
                self.webservice_thread.stop()

    def bootstrap(self):
        response = self.initialize_app_state()
        if isinstance(response, SuccessResponse):
            self.start_server()

        return response

    def restart_server(self):
        # Restart the server with new controller
        self.load_webservice()
        self.start_server()
        return SuccessResponse()

    def handle_build_use_server(self):
        asyncio.run(self.js_compiler.build_use_server())
        return SuccessResponse()

    def initialize_app_state(self):
        """Initialize all app state within the isolated context"""
        # Import and initialize the module
        self.load_webservice()

        # Initialize hot reloader
        self.hot_reloader = HotReloader(
            root_package=self.package,
            package_path=Path(self.package.replace(".", "/")),
            entrypoint=self.module_name,
        )

        # Mount exceptions
        self.exception_controller = ExceptionController()
        self.mount_exceptions(self.app_controller)

        # Initialize builders in isolated context
        global_build_cache = Path(mkdtemp())
        self.js_compiler = APIBuilder(
            self.app_controller,
            live_reload_port=self.live_reload_port,
            build_cache=global_build_cache,
        )
        self.app_compiler = ClientCompiler(
            app=self.app_controller,
        )

        return SuccessResponse()

    def load_webservice(self):
        self.module = importlib.import_module(self.module_name)
        initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
        self.app_controller = initial_state[self.controller_name]

    def start_server(self):
        """Start the uvicorn server"""
        if self.webservice_thread is not None:
            self.webservice_thread.stop()

        # Inject the live reload port
        self.app_controller.live_reload_port = self.live_reload_port or 0

        self.webservice_thread = UvicornThread(
            name="Dev webserver",
            emoticon="🚀",
            app=self.app_controller.app,
            host=self.host or "127.0.0.1",
            port=self.port,
        )
        self.webservice_thread.start()

    def handle_module_reload(self, module_names: List[str]):
        """Handle module reloading within the isolated context"""
        needs_restart = True

        try:
            # Get the list of modules to reload from the hot reloader
            success, reloaded, needs_restart, error = self.hot_reloader.reload_modules(
                module_names
            )

            if error:
                raise error

            return ReloadResponseSuccess(
                reloaded=reloaded,
                needs_restart=needs_restart,
            )
        except Exception as e:
            LOGGER.debug(f"Failed to reload modules: {e}", exc_info=True)
            return ReloadResponseError(
                needs_restart=needs_restart,
                exception=str(e),
                traceback="".join(format_exception(e)),
            )

    def handle_js_build(self, updated_js: list[str] | None = None):
        """Handle JS compilation within the isolated context"""
        try:
            # asyncio.run(self.js_compiler.build_use_server())
            asyncio.run(self.app_compiler.run_builder_plugins(limit_paths=updated_js))
            for path in (updated_js or []):
                self.app_controller.invalidate_view(path)
        except Exception as e:
            LOGGER.error(f"Failed to build JS: {e}", exc_info=True)

    def mount_exceptions(self, app_controller: AppController):
        # Don't re-mount the exception controller
        current_controllers = [
            controller_definition.controller.__class__.__name__
            for controller_definition in app_controller.controllers
        ]

        if self.exception_controller.__class__.__name__ not in current_controllers:
            app_controller.register(self.exception_controller)
            app_controller.app.exception_handler(Exception)(self.handle_dev_exception)

    async def handle_dev_exception(self, request: Request, exc: Exception):
        if request.method == "GET":
            html = await self.exception_controller._definition.view_route(  # type: ignore
                exception=str(exc),
                stack="".join(format_exception(exc)),
                parsed_exception=self.exception_controller.traceback_parser.parse_exception(
                    exc
                ),
            )
            return html
        else:
            raise exc
