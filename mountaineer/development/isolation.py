import asyncio
import importlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from multiprocessing import Process
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception
from typing import Any

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
    CaptureLogsSuccessResponse,
    ErrorResponse,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponseError,
    ReloadResponseSuccess,
    RestartServerMessage,
    ShutdownMessage,
    StartCaptureLogsMessage,
    StopCaptureLogsMessage,
    SuccessResponse,
)
from mountaineer.development.uvicorn import UvicornThread
from mountaineer.logging import setup_internal_logger

LOGGER = setup_internal_logger(__name__)


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

        self.app_controller: AppController | None = None

        self.js_compiler: APIBuilder | None = None
        self.app_compiler: ClientCompiler | None = None
        self.hot_reloader: HotReloader | None = None

        # Log capture state
        self._stdout_capture: StringIO | None = None
        self._stderr_capture: StringIO | None = None
        self._stdout_redirect: redirect_stdout | None = None
        self._stderr_redirect: redirect_stderr | None = None

    def run(self):
        """Main worker process loop"""
        asyncio.run(self.run_async())

    async def run_async(self):
        try:
            LOGGER.debug("[IsolatedAppContext] Starting isolated context")

            # Process messages until shutdown
            while True:
                message_id, message = self.message_broker.message_queue.get()
                LOGGER.debug(f"[IsolatedAppContext] Got message: {message}")

                try:
                    response: SuccessResponse | ErrorResponse
                    if isinstance(message, BootupMessage):
                        response = await self.handle_bootstrap()
                    elif isinstance(message, ReloadModulesMessage):
                        response = await self.handle_module_reload(message.module_names)
                    elif isinstance(message, RestartServerMessage):
                        response = await self.handle_restart_server()
                    elif isinstance(message, BuildJsMessage):
                        response = await self.handle_js_build(message.updated_js)
                    elif isinstance(message, BuildUseServerMessage):
                        response = await self.handle_build_use_server()
                    elif isinstance(message, StartCaptureLogsMessage):
                        response = await self.handle_start_capture_logs()
                    elif isinstance(message, StopCaptureLogsMessage):
                        response = await self.handle_stop_capture_logs()
                    elif isinstance(message, ShutdownMessage):
                        self.message_broker.response_queue.put(
                            (message_id, SuccessResponse())
                        )
                        break
                    else:
                        LOGGER.error(f"Invalid message type: {type(message)} {message}")
                        continue
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

    #
    # Message Handlers
    #

    async def handle_bootstrap(self):
        response = self.initialize_app_state()
        if isinstance(response, SuccessResponse):
            self.start_server()

        return response

    async def handle_restart_server(self):
        # Restart the server with new controller
        self.load_webservice()
        self.start_server()
        return SuccessResponse()

    async def handle_build_use_server(self):
        if self.js_compiler is None:
            raise ValueError("JS compiler not initialized")

        await self.js_compiler.build_use_server()
        return SuccessResponse()

    async def handle_module_reload(self, module_names: list[str]):
        """Handle module reloading within the isolated context"""
        needs_restart = True

        try:
            if self.hot_reloader is None:
                raise ValueError("Hot reloader not initialized")

            # Get the list of modules to reload from the hot reloader
            reload_status = self.hot_reloader.reload_modules(module_names)

            if reload_status.error:
                raise reload_status.error

            return ReloadResponseSuccess(
                reloaded=reload_status.reloaded_modules,
                needs_restart=reload_status.needs_restart,
            )
        except Exception as e:
            LOGGER.debug(f"Failed to reload modules: {e}", exc_info=True)
            return ReloadResponseError(
                needs_restart=needs_restart,
                exception=str(e),
                traceback="".join(format_exception(e)),
            )

    async def handle_js_build(self, updated_js: list[Path] | None = None):
        """Handle JS compilation within the isolated context"""
        if self.app_compiler is None:
            raise ValueError("App compiler not initialized")
        if self.app_controller is None:
            raise ValueError("App controller not initialized")

        await self.app_compiler.run_builder_plugins(limit_paths=updated_js)
        for path in updated_js or []:
            self.app_controller.invalidate_view(path)

        return SuccessResponse()

    async def handle_start_capture_logs(self) -> SuccessResponse:
        """
        Start capturing stdout and stderr during module reload.
        This method activates the context managers and saves the captures to the instance.
        """
        self._stdout_capture = StringIO()
        self._stderr_capture = StringIO()
        self._stdout_redirect = redirect_stdout(self._stdout_capture)
        self._stderr_redirect = redirect_stderr(self._stderr_capture)
        self._stdout_redirect.__enter__()
        self._stderr_redirect.__enter__()

        return SuccessResponse()

    async def handle_stop_capture_logs(self) -> CaptureLogsSuccessResponse:
        """
        End capturing stdout and stderr, restore standard streams, and return the captured content.
        Returns a tuple of (stdout_capture, stderr_capture) containing the captured output.
        """
        if (
            not self._stdout_capture
            or not self._stderr_capture
            or not self._stdout_redirect
            or not self._stderr_redirect
        ):
            raise RuntimeError("Cannot end capture logs before starting")

        self._stdout_redirect.__exit__(None, None, None)
        self._stderr_redirect.__exit__(None, None, None)

        stdout_capture = self._stdout_capture
        stderr_capture = self._stderr_capture

        # Clear the state
        self._stdout_capture = None
        self._stderr_capture = None
        self._stdout_redirect = None
        self._stderr_redirect = None

        return CaptureLogsSuccessResponse(
            captured_logs=stdout_capture.getvalue(),
            captured_errors=stderr_capture.getvalue(),
        )

    #
    # Server Initialization
    #

    def initialize_app_state(self):
        """Initialize all app state within the isolated context"""
        # Import and initialize the module
        self.load_webservice()

        if self.app_controller is None:
            raise ValueError("App controller not initialized")

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

        if self.app_controller is None:
            raise ValueError("App controller not initialized")

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

    #
    # Dev Hooks
    #

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
