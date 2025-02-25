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
    BuildJsMessage,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponse,
    ShutdownMessage,
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
            # Initialize app state
            self.initialize_app_state()

            # Start the server
            self.start_server()

            # Process messages until shutdown
            while True:
                message_id, message = self.message_broker.message_queue.get()

                if isinstance(message, ShutdownMessage):
                    break
                elif isinstance(message, ReloadModulesMessage):
                    response = self.handle_module_reload(message.module_names)
                    self.message_broker.response_queue.put((message_id, response))
                elif isinstance(message, BuildJsMessage):
                    self.handle_js_build()

        except Exception as e:
            LOGGER.error(f"Isolated app context failed: {e}", exc_info=True)
        finally:
            if self.webservice_thread:
                self.webservice_thread.stop()

    def initialize_app_state(self):
        """Initialize all app state within the isolated context"""
        try:
            # Import and initialize the module
            self.module = importlib.import_module(self.module_name)
            initial_state = {
                name: getattr(self.module, name) for name in dir(self.module)
            }
            self.app_controller = initial_state[self.controller_name]

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
        except Exception as e:
            LOGGER.error(f"Failed to initialize app state: {e}", exc_info=True)
            raise

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

    def handle_module_reload(self, module_names: List[str]) -> ReloadResponse:
        """Handle module reloading within the isolated context"""
        try:
            # Get the list of modules to reload from the hot reloader
            success, reloaded, needs_restart, error = self.hot_reloader.reload_modules(
                module_names
            )

            # TODO: We should have another message that does this
            if success and not needs_restart:
                # Re-initialize all app state
                # self.initialize_app_state()

                # Rebuild JS since module changed
                asyncio.run(self.js_compiler.build_use_server())

                # Restart the server with new controller
                self.start_server()

            return ReloadResponse(
                success=success,
                reloaded=reloaded,
                needs_restart=needs_restart,
                exception=str(error) if error else None,
                traceback="".join(format_exception(error)) if error else None,
            )
        except Exception as e:
            LOGGER.debug(f"Failed to reload modules: {e}", exc_info=True)
            return ReloadResponse(
                success=False,
                reloaded=[],
                needs_restart=True,
                exception=str(e),
                traceback="".join(format_exception(e)),
            )

    def handle_js_build(self):
        """Handle JS compilation within the isolated context"""
        try:
            asyncio.run(self.js_compiler.build_use_server())
            asyncio.run(self.app_compiler.run_builder_plugins())
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
