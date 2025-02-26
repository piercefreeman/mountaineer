import os
import socket
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from mountaineer.console import CONSOLE
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.messages import (
    AsyncMessageBroker,
    BootupMessage,
    BuildJsMessage,
    BuildUseServerMessage,
    ErrorResponse,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponseError,
    RestartServerMessage,
    ShutdownMessage,
    SuccessResponse,
)
from mountaineer.logging import setup_internal_logger

LOGGER = setup_internal_logger(__name__)

TSuccess = TypeVar("TSuccess", bound=SuccessResponse)
TError = TypeVar("TError", bound=ErrorResponse)


class BuildFailed(Exception):
    context: ErrorResponse

    def __init__(self, context: ErrorResponse):
        self.context = context

    def __str__(self):
        return f"Build failed: {self.context.exception}"


class DevAppManager:
    """
    The main entrypoint for managing an isolated development application process with hot-reloading capabilities.

    DevAppManager handles the lifecycle and communication with an isolated Python web application,
    running in a separate process for development purposes. It provides process isolation,
    hot module reloading, and message-based communication between the main process and the
    isolated application context.

    Key features:
    - Process isolation for development server
    - Asynchronous message-based communication
    - Hot module reloading support
    - Automatic process lifecycle management
    - JS build triggering for frontend changes

    The manager operates through an async context manager pattern:

    ```python
    async with DevAppManager.from_webcontroller(
        webcontroller="myapp.controllers:HomeController",
        host="localhost",
        port=8000
    ) as manager:
        await manager.reload_modules(["myapp.views"])
    ```

    When changes are detected, the manager can either reload specific modules or
    restart the entire server process if necessary. Communication between the main
    process and isolated context happens through a message broker, ensuring clean
    separation of concerns.

    """

    package: str
    """
    The root package name of the application
    """

    module_name: str
    """
    The module containing the web controller
    """

    controller_name: str
    """
    The name of the web controller class
    """

    host: str | None
    """
    The host to bind the server to
    """

    port: int | None
    """
    The port to run the server on
    """

    live_reload_port: int | None
    """
    The port for live reload websocket connections
    """

    def __init__(
        self,
        package: str,
        module_name: str,
        controller_name: str,
        host: str | None,
        port: int | None,
        live_reload_port: int | None,
    ):
        self.package = package
        self.module_name = module_name
        self.controller_name = controller_name
        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port
        self.successful_bootup = False

        # Message broker for communicating with isolated context
        self.message_broker = AsyncMessageBroker[IsolatedMessageBase[Any]]()
        self.app_context: IsolatedAppContext | None = None

    @classmethod
    def from_webcontroller(
        cls,
        webcontroller: str,
        host: str | None = None,
        port: int | None = None,
        live_reload_port: int | None = None,
    ):
        package = webcontroller.split(".")[0]
        module_name = webcontroller.split(":")[0]
        controller_name = webcontroller.split(":")[1]

        return cls(
            package=package,
            module_name=module_name,
            controller_name=controller_name,
            host=host,
            port=port,
            live_reload_port=live_reload_port,
        )

    @asynccontextmanager
    async def start_broker(self):
        """Start the message broker when entering async context"""
        try:
            self.message_broker.start()
            yield self
        finally:
            await self.message_broker.stop()

    #
    # Server Management
    #

    async def restart_server(self):
        """Restart the server in a fresh process"""
        LOGGER.debug("Restarting server")
        if not self.port:
            LOGGER.debug("Error: Port not set")
            raise ValueError("Port not set")

        # Stop existing context if running
        if self.app_context and self.app_context.is_alive():
            LOGGER.debug("Shutting down existing app context")
            await self.communicate(ShutdownMessage())
            LOGGER.debug("Waiting for app context to join")

            self.app_context.join(timeout=5)
            if self.app_context.is_alive():
                LOGGER.debug("Context did not shut down gracefully, terminating")
                self.app_context.terminate()

        # Start new context
        LOGGER.debug("Starting new app context")
        self.app_context = IsolatedAppContext(
            package=self.package,
            module_name=self.module_name,
            controller_name=self.controller_name,
            host=self.host,
            port=self.port,
            live_reload_port=self.live_reload_port,
            message_broker=self.message_broker,
        )
        self.app_context.start()
        LOGGER.debug("New app context started")

        bootstrap_response = await self.bootstrap()
        if isinstance(bootstrap_response, ErrorResponse):
            return bootstrap_response

        frontend_response = await self.reload_frontend()
        if isinstance(frontend_response, ErrorResponse):
            return frontend_response

        return SuccessResponse()

    async def bootstrap(self):
        # Send a bootup request and handle the initialization process
        # Any subsequent reload message received before we bootstrap should do a full bootup
        try:
            await self.communicate(BootupMessage())
            LOGGER.debug("App context bootstrapped successfully")
            self.successful_bootup = True
        except BuildFailed as e:
            LOGGER.debug("App context failed to bootstrap")
            self.successful_bootup = False

            return e.context

        # Only if successful should we build the useServer support files
        try:
            return await self.communicate(BuildUseServerMessage())
        except BuildFailed as e:
            return e.context

    async def reload_modules(self, module_names: list[str]):
        """
        Signal the context to reload modules and wait for response.
        Returns a tuple of (success, reloaded_modules, needs_restart).
        """
        LOGGER.debug(f"Attempting to reload modules: {module_names}")
        LOGGER.debug(f"Current process: {os.getpid()}")

        if self.app_context_missing():
            LOGGER.debug(
                "No active app context, returning needs_restart"
            )
            return ReloadResponseError(
                needs_restart=True,
            )

        # If we haven't booted up yet, we need to do a formal boot
        if not self.successful_bootup:
            try:
                await self.bootstrap()
            except BuildFailed as e:
                return ReloadResponseError(
                    exception=e.context.exception,
                    traceback=e.context.traceback,
                    # Permanent error - we did reboot but it failed
                    needs_restart=False,
                )

            # If we reached this point, we successfully booted up.
            # Reloading specific modules won't hurt.
            LOGGER.debug("Successfully booted up")

        LOGGER.debug("Sending reload message")
        LOGGER.debug(f"App context process ID: {self.app_context.pid}")

        try:
            reload_response = await self.communicate(
                ReloadModulesMessage(module_names=module_names)
            )
            await self.communicate(BuildUseServerMessage())
            await self.communicate(RestartServerMessage())
            return reload_response
        except BuildFailed as e:
            return e.context

    async def reload_frontend(self, updated_js: list[str] | None = None):
        """Signal the context to rebuild JS"""
        LOGGER.debug("Requesting JS build")
        if self.app_context_missing():
            return ErrorResponse(
                exception="No active app context",
                traceback="No active app context",
            )

        try:
            return await self.communicate(BuildJsMessage(updated_js=updated_js))
        except BuildFailed as e:
            return e.context

    #
    # Helper methods
    #

    def app_context_missing(self):
        return not (self.app_context and self.app_context.is_alive())

    def is_port_open(self, host, port):
        """Check if a port is open on the given host."""
        LOGGER.debug(f"Checking if port {port} is open on {host}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)
                s.connect((host, port))
                LOGGER.debug(f"Port {port} is open")
                return True
            except (socket.timeout, ConnectionRefusedError):
                LOGGER.debug(f"Port {port} is closed")
                return False

    async def communicate(
        self, message: IsolatedMessageBase[TSuccess | TError]
    ) -> TSuccess:
        LOGGER.debug(
            f"Host->Context: Communicating with message: {message}"
        )
        response = await self.message_broker.send_message(message)
        LOGGER.debug(f"Host<-Context: Got response: {response}")

        if isinstance(response, ErrorResponse):
            CONSOLE.print(f"[bold red]Webapp Error: {response.exception}")
            CONSOLE.print(response.traceback)
            raise BuildFailed(context=response)
        if not isinstance(response, SuccessResponse):
            raise ValueError(f"Invalid response type: {type(response)} {response}")
        return response
