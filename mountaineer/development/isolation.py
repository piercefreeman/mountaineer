import importlib
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception
from typing import TYPE_CHECKING

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.development.messages import (
    BootupMessage,
    BuildJsMessage,
    BuildUseServerMessage,
    ErrorResponse,
    MessageTypes,
    StartServerMessage,
    SuccessResponse,
)
from mountaineer.development.messages_broker import AsyncMessageBroker
from mountaineer.development.uvicorn import UvicornThread
from mountaineer.logging import setup_internal_logger

if TYPE_CHECKING:
    from mountaineer_exceptions.controllers.exception_controller import (
        ExceptionController,
    )

LOGGER = setup_internal_logger(__name__)


class IsolatedAppContext:
    """
    Manages the app controller, server, and compilation.

    """

    def __init__(
        self,
        package: str,
        package_path: Path,
        module_name: str,
        controller_name: str,
        use_dev_exceptions: bool = True,
    ):
        """
        Initialize an isolated application context in a separate process.

        :param package: Name of the main package
        :param package_path: Path to the package on disk
        :param module_name: Module name containing the app controller
        :param controller_name: Variable name of the app controller within the module
        """
        super().__init__()
        self.package = package
        self.package_path = package_path
        self.module_name = module_name
        self.controller_name = controller_name
        self.webservice_thread: UvicornThread | None = None

        self.app_controller: AppController | None = None
        self.exception_controller: "ExceptionController | None" = None
        self.use_dev_exceptions = use_dev_exceptions

        self.js_compiler: APIBuilder | None = None
        self.app_compiler: ClientCompiler | None = None

    @classmethod
    def from_webcontroller(cls, webcontroller: str, use_dev_exceptions: bool = True):
        package = webcontroller.split(".")[0]
        module_name = webcontroller.split(":")[0]
        controller_name = webcontroller.split(":")[1]

        return cls(
            package=package,
            package_path=Path(package.replace(".", "/")),
            module_name=module_name,
            controller_name=controller_name,
            use_dev_exceptions=use_dev_exceptions,
        )

    async def run_async(self, broker: AsyncMessageBroker[MessageTypes]):
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
                LOGGER.debug("Will block on next message")
                message_id, message = await broker.get_job()
                LOGGER.debug(f"Got message: {message}")

                try:
                    response: SuccessResponse | ErrorResponse
                    if isinstance(message, BootupMessage):
                        response = await self.initialize_app_state()
                    elif isinstance(message, StartServerMessage):
                        response = await self.handle_start_server(
                            host=message.host,
                            port=message.port,
                            live_reload_port=message.live_reload_port,
                        )
                    elif isinstance(message, BuildJsMessage):
                        response = await self.handle_js_build(message.updated_js)
                    elif isinstance(message, BuildUseServerMessage):
                        response = await self.handle_build_use_server()
                    else:
                        LOGGER.error(f"Invalid message type: {type(message)} {message}")
                        raise ValueError(
                            f"Invalid message type: {type(message)} {message}"
                        )
                    LOGGER.debug(f"Will write response: {response}")
                    await broker.send_response(message_id, response)
                except Exception as e:
                    LOGGER.debug(
                        f"Isolated app context failed to process message: {e}, continuing...",
                        exc_info=True,
                    )
                    await broker.send_response(
                        message_id,
                        ErrorResponse(
                            exception=str(e), traceback="".join(format_exception(e))
                        ),
                    )
        except Exception as e:
            LOGGER.error(f"Isolated app context failed: {e}", exc_info=True)
        finally:
            if self.webservice_thread:
                await self.webservice_thread.astop()

    #
    # Message Handlers
    #

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

    #
    # Server Initialization
    #

    async def initialize_app_state(self):
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
        self.module = importlib.import_module(self.module_name)
        initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
        self.app_controller = initial_state[self.controller_name]

        if self.app_controller is None:
            raise ValueError("App controller not initialized")

        # Mount exceptions
        self.mount_exceptions(self.app_controller)

        # Initialize builders in isolated context
        global_build_cache = Path(mkdtemp())
        self.js_compiler = APIBuilder(
            self.app_controller,
            build_cache=global_build_cache,
        )
        self.app_compiler = ClientCompiler(
            app=self.app_controller,
        )

        return SuccessResponse()

    async def handle_start_server(self, host: str, port: int, live_reload_port: int):
        """
        Start the Uvicorn server for the web application.

        Configures and launches a UvicornThread to serve the application.
        If a server is already running, it will be stopped first.

        :raises ValueError: If app controller is not initialized
        """
        if self.webservice_thread is not None:
            LOGGER.debug("Server is already running")
            return SuccessResponse()

        if self.app_controller is None:
            raise ValueError("App controller not initialized")

        # Inject the live reload port
        self.app_controller.live_reload_port = live_reload_port or 0

        self.webservice_thread = UvicornThread(
            name="Dev webserver",
            emoticon="🚀",
            app=self.app_controller.app,
            host=host,
            port=port,
        )
        await self.webservice_thread.astart()

        return SuccessResponse()

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
        if not self.use_dev_exceptions:
            LOGGER.debug("Dev exceptions are disabled, skipping...")
            return

        try:
            from mountaineer_exceptions.controllers.exception_controller import (
                ExceptionController,
            )
            from mountaineer_exceptions.plugin import plugin  # type: ignore

            app_controller.register(plugin)
            self.exception_controller = [
                controller
                for controller in plugin.get_controllers()
                if isinstance(controller, ExceptionController)
            ][0]
            app_controller.app.exception_handler(Exception)(self.handle_dev_exception)
        except ImportError:
            LOGGER.warning("mountaineer-exceptions plugin not found, skipping...")

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
        LOGGER.error(f"Handling dev exception: {exc}")

        if not self.exception_controller:
            raise ValueError("Exception controller not initialized")

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
