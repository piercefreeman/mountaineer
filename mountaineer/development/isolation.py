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

    This class runs the application in a separate process, providing a clean
    environment for module reloading and compilation without affecting the main process.

    It communicates with the main process through a message broker, handling various
    operations like module reloading, server restarts, and JS compilation. This isolation
    enables Mountaineer's hot-reloading capabilities by allowing code to be reloaded
    without restarting the entire application.

    ```python {{sticky: True}}
    import asyncio
    from pathlib import Path
    from mountaineer.development.messages import AsyncMessageBroker, BootupMessage, ShutdownMessage
    from mountaineer.development.isolation import IsolatedAppContext

    # Create a message broker for communication
    broker = AsyncMessageBroker()
    broker.start()

    # Initialize the isolated context
    isolated_app = IsolatedAppContext(
        package="my_app",
        package_path=Path("./my_app"),
        module_name="my_app.main",
        controller_name="app",
        host="127.0.0.1",
        port=8000,
        live_reload_port=3001,
        message_broker=broker
    )

    # Start the isolated process
    isolated_app.start()

    try:
        # Send bootup message to initialize the app
        await broker.send_message(BootupMessage())

        print("App started successfully in isolated process!")

        # Wait for some time (in a real app, this would be until shutdown is needed)
        await asyncio.sleep(5)

    finally:
        # Send shutdown message and wait for it to complete
        await broker.send_message(ShutdownMessage())

        # Wait for the process to terminate
        isolated_app.join(timeout=2)
        if isolated_app.is_alive():
            isolated_app.terminate()

        # Clean up the broker
        await broker.stop()
    ```
    """

    def __init__(
        self,
        package: str,
        package_path: Path,
        module_name: str,
        controller_name: str,
        host: str | None,
        port: int,
        live_reload_port: int | None,
        message_broker: AsyncMessageBroker[IsolatedMessageBase[Any]],
    ):
        """
        Initialize an isolated application context in a separate process.

        :param package: Name of the main package
        :param package_path: Path to the package on disk
        :param module_name: Module name containing the app controller
        :param controller_name: Variable name of the app controller within the module
        :param host: Host address to bind the server to
        :param port: Port number for the web server
        :param live_reload_port: Port number for the live reload watcher service
        :param message_broker: Broker for communication between main and isolated processes
        """
        super().__init__()
        self.package = package
        self.package_path = package_path
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
        """
        Main process entry point that runs when the process starts.

        This method is called automatically when the process is started with start().
        It runs the async event loop and handles exceptions gracefully.
        """
        try:
            asyncio.run(self.run_async())
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        except Exception as e:
            LOGGER.error(f"Isolated app context failed: {e}", exc_info=True)

        LOGGER.debug("Isolated app shutdown complete")

    async def run_async(self):
        """
        Asynchronous main loop that processes messages from the broker.

        This is the core message handling loop that:
        1. Retrieves messages from the queue
        2. Dispatches them to appropriate handlers
        3. Sends responses back through the broker

        The loop continues until a ShutdownMessage is received.
        """
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
                        # Send immediately before breaking out of the loop, which should
                        # trigger a shutdown of this process
                        response = await self.handle_shutdown()
                        self.message_broker.response_queue.put((message_id, response))
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
                await self.webservice_thread.astop()

    #
    # Message Handlers
    #

    async def handle_bootstrap(self):
        """
        Initialize the application state and start the server.

        This is called in response to a BootupMessage and performs the initial setup
        of the application in the isolated process.

        :return: Success or error response
        """
        print("bootstrapping...", flush=True)
        response = self.initialize_app_state()
        print("bootstrapped", response, flush=True)
        if isinstance(response, SuccessResponse):
            await self.start_server()
        print("started server", flush=True)

        return response

    async def handle_restart_server(self):
        """
        Restart the web server with the current app controller.

        This reloads the web service and starts a new server instance.
        Used when the application structure has changed but doesn't need full reinitialization.

        :return: Success response on successful restart
        """
        # Restart the server with new controller
        self.load_webservice()
        await self.start_server()
        return SuccessResponse()

    async def handle_build_use_server(self):
        """
        Build the useServer support files for client-side React Server Components.

        :return: Success response on successful build
        :raises ValueError: If JS compiler is not initialized
        """
        if self.js_compiler is None:
            raise ValueError("JS compiler not initialized")

        await self.js_compiler.build_use_server()
        return SuccessResponse()

    async def handle_module_reload(self, module_names: list[str]):
        """
        Reload specified Python modules in the isolated context.

        Uses the HotReloader to safely reload modules and their dependencies.

        :param module_names: List of module names to reload
        :return: Success or error response with details about reloaded modules and restart needs
        """
        needs_restart = True
        reloaded: list[str] = []

        try:
            if self.hot_reloader is None:
                raise ValueError("Hot reloader not initialized")

            # Get the list of modules to reload from the hot reloader
            reload_status = self.hot_reloader.reload_modules(module_names)

            if reload_status.error:
                reloaded = reload_status.reloaded_modules
                raise reload_status.error

            return ReloadResponseSuccess(
                reloaded=reload_status.reloaded_modules,
                needs_restart=reload_status.needs_restart,
            )
        except Exception as e:
            LOGGER.debug(f"Failed to reload modules: {e}", exc_info=True)
            return ReloadResponseError(
                reloaded=reloaded,
                needs_restart=needs_restart,
                exception=str(e),
                traceback="".join(format_exception(e)),
            )

    async def handle_js_build(self, updated_js: list[Path] | None = None):
        """
        Compile JavaScript files based on updated paths.

        Runs the builder plugins and invalidates any affected views in the app controller.

        :param updated_js: Optional list of specific JS files that were updated
        :return: Success response on successful build
        :raises ValueError: If app compiler or controller is not initialized
        """
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

        :return: Success response when capture is started
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

        :return: Success response containing the captured stdout and stderr
        :raises RuntimeError: If capturing was not started before stopping
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

    async def handle_shutdown(self):
        """
        Handle shutdown of the isolated context by stopping the web server.

        :return: Success response when shutdown is complete
        """
        if self.webservice_thread:
            await self.webservice_thread.astop()
        return SuccessResponse()

    #
    # Server Initialization
    #

    def initialize_app_state(self):
        """
        Initialize all application state components within the isolated context.

        This method:
        1. Loads the web service and app controller
        2. Initializes the hot reloader
        3. Mounts the exception controller for development error pages
        4. Sets up JS and app compilers

        :return: Success response on successful initialization
        :raises ValueError: If app controller fails to initialize
        """
        # Import and initialize the module
        self.load_webservice()

        if self.app_controller is None:
            raise ValueError("App controller not initialized")

        # Initialize hot reloader
        self.hot_reloader = HotReloader(
            root_package=self.package,
            package_path=self.package_path,
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
        """
        Import the specified module and extract the app controller.

        Dynamically loads the module containing the app controller and
        retrieves the controller instance from it.
        """
        self.module = importlib.import_module(self.module_name)
        initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
        self.app_controller = initial_state[self.controller_name]

    async def start_server(self):
        """
        Start the Uvicorn server for the web application.

        Configures and launches a UvicornThread to serve the application.
        If a server is already running, it will be stopped first.

        :raises ValueError: If app controller is not initialized
        """
        if self.webservice_thread is not None:
            await self.webservice_thread.astop()

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
        await self.webservice_thread.astart()

    #
    # Dev Hooks
    #

    def mount_exceptions(self, app_controller: AppController):
        """
        Mount the exception controller to the app controller for custom error pages.

        This adds development-friendly error pages with stack traces and debugging information.
        It ensures the exception controller is only mounted once.

        :param app_controller: The app controller to mount the exception controller on
        """
        # Don't re-mount the exception controller
        current_controllers = [
            controller_definition.controller.__class__.__name__
            for controller_definition in app_controller.controllers
        ]

        if self.exception_controller.__class__.__name__ not in current_controllers:
            app_controller.register(self.exception_controller)
            app_controller.app.exception_handler(Exception)(self.handle_dev_exception)

    async def handle_dev_exception(self, request: Request, exc: Exception):
        """
        Handle exceptions in development mode with enhanced error pages.

        For GET requests, renders a detailed error page with stack traces and debugging info.
        For other request types, re-raises the exception to be handled by the framework.

        :param request: The FastAPI request object
        :param exc: The exception that was raised
        :return: HTML response for GET requests
        :raises: The original exception for non-GET requests
        """
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
