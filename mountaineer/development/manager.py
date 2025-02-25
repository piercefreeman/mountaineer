import socket
import uuid
from typing import Any

from mountaineer.console import CONSOLE
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.messages import (
    AsyncMessageBroker,
    BuildJsMessage,
    IsolatedMessageBase,
    ReloadModulesMessage,
    ReloadResponse,
    ShutdownMessage,
)


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

    async def __aenter__(self):
        """Start the message broker when entering async context"""
        self.message_broker.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Stop the message broker when exiting async context"""
        await self.message_broker.stop()

    def restart_server(self):
        """Restart the server in a fresh process"""
        if not self.port:
            raise ValueError("Port not set")

        # Stop existing context if running
        if self.app_context and self.app_context.is_alive():
            self.message_broker.message_queue.put(
                (str(uuid.uuid4()), ShutdownMessage())
            )
            self.app_context.join(timeout=5)
            if self.app_context.is_alive():
                self.app_context.terminate()

        # Start new context
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

    async def reload_modules(self, module_names: list[str]) -> ReloadResponse:
        """
        Signal the context to reload modules and wait for response.
        Returns a tuple of (success, reloaded_modules, needs_restart).
        """
        if not (self.app_context and self.app_context.is_alive()):
            return ReloadResponse(
                success=False,
                reloaded=[],
                needs_restart=True,
            )

        response = await self.message_broker.send_message(
            ReloadModulesMessage(
                module_names=module_names,
            )
        )

        CONSOLE.print(f"Reload response: {response}")

    def build_js(self):
        """Signal the context to rebuild JS"""
        if self.app_context and self.app_context.is_alive():
            self.message_broker.message_queue.put((str(uuid.uuid4()), BuildJsMessage()))

    def is_port_open(self, host, port):
        """Check if a port is open on the given host."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)
                s.connect((host, port))
                return True
            except (socket.timeout, ConnectionRefusedError):
                return False
