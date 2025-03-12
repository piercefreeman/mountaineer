import importlib
from os import environ
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.controllers.exception_controller import (
    ExceptionController,
)
from mountaineer.development.messages import (
    BootupMessage,
    BuildJsMessage,
    BuildUseServerMessage,
    ErrorResponse,
    SuccessResponse,
)
from mountaineer.development.messages_broker import AsyncMessageBroker
from mountaineer.development.uvicorn import UvicornThread
from mountaineer.development.messages import MessageTypes
from mountaineer.logging import setup_internal_logger

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
        host: str | None,
        port: int,
        live_reload_port: int | None,
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
        self.webservice_thread: UvicornThread | None = None

        self.app_controller: AppController | None = None

        self.js_compiler: APIBuilder | None = None
        self.app_compiler: ClientCompiler | None = None

    @classmethod
    def from_webcontroller(
        cls,
        webcontroller: str,
        host: str,
        port: int,
        live_reload_port: int | None = None,
    ):
        package = webcontroller.split(".")[0]
        module_name = webcontroller.split(":")[0]
        controller_name = webcontroller.split(":")[1]

        return cls(
            package=package,
            package_path=Path(package.replace(".", "/")),
            module_name=module_name,
            controller_name=controller_name,
            host=host,
            port=port,
            live_reload_port=live_reload_port,
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
        print("OS ENV IN ISOLATED APP CONTEXt", environ)
        try:
            LOGGER.debug("[IsolatedAppContext] Starting isolated context")

            # Process messages until shutdown
            while True:
                print("WILL BLOCK ON NEXT MESSAGE", flush=True)
                message_id, message = await broker.get_job()
                print(f"GOT MESSAGE RAW: {message}", flush=True)
                # LOGGER.debug(f"[IsolatedAppContext] Got message: {message}")
                print(f"MESSAGE: {isinstance(message, BuildJsMessage)}", flush=True)

                try:
                    response: SuccessResponse | ErrorResponse
                    if isinstance(message, BootupMessage):
                        response = await self.handle_bootstrap()
                    elif isinstance(message, BuildJsMessage):
                        print("BUILD JS!!")
                        response = await self.handle_js_build(message.updated_js)
                    elif isinstance(message, BuildUseServerMessage):
                        response = await self.handle_build_use_server()
                    else:
                        LOGGER.error(f"Invalid message type: {type(message)} {message}")
                        raise ValueError(f"Invalid message type: {type(message)} {message}")
                    print(f"WILL WRITE RESPONSE: {response}", flush=True)
                    print(f"MESSAGE ID: {message_id}", flush=True)
                    await broker.send_response(message_id, response)
                    print(f"DID WRITE RESPONSE: {response}", flush=True)
                except Exception as e:
                    # The only location where we log errors that occur in the build lifecycle
                    # TODO: GET THIS TO SHOW UP WITH STDERR
                    LOGGER.error(
                        f"Isolated app context failed to process message: {e}, continuing...",
                        exc_info=True,
                    )
                    print(
                        f"Isolated app context failed to process message: {e}, continuing...",
                        flush=True,
                    )
                    print(f"WILL WRITE ERROR RESPONSE: {e}", flush=True)
                    await broker.send_response(message_id, ErrorResponse(
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

    async def handle_bootstrap(self):
        """
        Initialize the application state and start the server.

        This is called in response to a BootupMessage and performs the initial setup
        of the application in the isolated process.

        :return: Success or error response
        """
        print("Initialize app state")
        response = self.initialize_app_state()
        if not isinstance(response, SuccessResponse):
            print("handle_bootstrap", response)
            return response

        print("START start_server")
        return await self.start_server()

    async def handle_build_use_server(self):
        """
        Build the useServer support files for client-side React Server Components.

        :return: Success response on successful build
        :raises ValueError: If JS compiler is not initialized
        """
        if self.js_compiler is None:
            print("JS COMPILER IS NULL", flush=True)
            raise ValueError("JS compiler not initialized")

        print("WILL BUILD USE SERVER", flush=True)
        await self.js_compiler.build_use_server()
        print("DID BUILD USE SERVER", flush=True)
        return SuccessResponse()

    async def handle_js_build(self, updated_js: list[Path] | None = None):
        """
        Compile JavaScript files based on updated paths.

        Runs the builder plugins and invalidates any affected views in the app controller.

        :param updated_js: Optional list of specific JS files that were updated
        :return: Success response on successful build
        :raises ValueError: If app compiler or controller is not initialized
        """
        print("WILL CHECK APP COMPILER", flush=True)
        if self.app_compiler is None:
            raise ValueError("App compiler not initialized")
        print("WILL CHECK APP CONTROLLER", flush=True)
        if self.app_controller is None:
            raise ValueError("App controller not initialized")

        print("WILL RUN RUN BUILDER PLUGINS", flush=True)
        await self.app_compiler.run_builder_plugins(limit_paths=updated_js)
        print("DID RUN RUN BUILDER PLUGINS", flush=True)
        for path in updated_js or []:
            self.app_controller.invalidate_view(path)

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
        print("WILL START astart")
        await self.webservice_thread.astart()
        print("DID START astart")

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
