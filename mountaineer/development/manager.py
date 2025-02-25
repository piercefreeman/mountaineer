import os
import socket
import uuid
from contextlib import asynccontextmanager
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
from mountaineer.logging import LOGGER


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
        LOGGER.debug(
            f"[DevAppManager] Initializing manager for {package}.{module_name}:{controller_name}"
        )
        self.package = package
        self.module_name = module_name
        self.controller_name = controller_name
        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port

        # Message broker for communicating with isolated context
        LOGGER.debug("[DevAppManager] Creating message broker")
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
        LOGGER.debug(
            f"[DevAppManager] Creating manager from webcontroller: {webcontroller}"
        )
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
            LOGGER.debug("[DevAppManager] Entering async context")
            self.message_broker.start()
            yield self
        finally:
            await self.message_broker.stop()

    def restart_server(self):
        """Restart the server in a fresh process"""
        LOGGER.debug("[DevAppManager] Restarting server")
        if not self.port:
            LOGGER.debug("[DevAppManager] Error: Port not set")
            raise ValueError("Port not set")

        # Stop existing context if running
        if self.app_context and self.app_context.is_alive():
            LOGGER.debug("[DevAppManager] Shutting down existing app context")
            message_id = str(uuid.uuid4())
            LOGGER.debug(f"[DevAppManager] Sending shutdown message {message_id}")
            self.message_broker.message_queue.put((message_id, ShutdownMessage()))
            LOGGER.debug("[DevAppManager] Waiting for app context to join")
            self.app_context.join(timeout=5)
            if self.app_context.is_alive():
                LOGGER.debug(
                    "[DevAppManager] App context did not shut down gracefully, terminating"
                )
                self.app_context.terminate()

        # Start new context
        LOGGER.debug("[DevAppManager] Starting new app context")
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
        LOGGER.debug("[DevAppManager] New app context started")

    async def reload_modules(self, module_names: list[str]) -> ReloadResponse:
        """
        Signal the context to reload modules and wait for response.
        Returns a tuple of (success, reloaded_modules, needs_restart).
        """
        LOGGER.debug(f"[DevAppManager] Attempting to reload modules: {module_names}")
        LOGGER.debug(f"[DevAppManager] Current process: {os.getpid()}")

        if not (self.app_context and self.app_context.is_alive()):
            LOGGER.debug(
                "[DevAppManager] No active app context, returning needs_restart"
            )
            return ReloadResponse(
                success=False,
                reloaded=[],
                needs_restart=True,
            )

        LOGGER.debug("[DevAppManager] Sending reload message")
        LOGGER.debug(f"[DevAppManager] App context process ID: {self.app_context.pid}")
        response = await self.message_broker.send_message(
            ReloadModulesMessage(
                module_names=module_names,
            )
        )
        LOGGER.debug(f"[DevAppManager] Received reload response: {response}")
        LOGGER.debug(f"[DevAppManager] Response type: {type(response)}")

        CONSOLE.print(f"Reload response: {response}")
        return response

    def build_js(self):
        """Signal the context to rebuild JS"""
        LOGGER.debug("[DevAppManager] Requesting JS build")
        if self.app_context and self.app_context.is_alive():
            message_id = str(uuid.uuid4())
            LOGGER.debug(f"[DevAppManager] Sending build JS message {message_id}")
            self.message_broker.message_queue.put((message_id, BuildJsMessage()))
        else:
            LOGGER.debug("[DevAppManager] No active app context, skipping JS build")

    def is_port_open(self, host, port):
        """Check if a port is open on the given host."""
        LOGGER.debug(f"[DevAppManager] Checking if port {port} is open on {host}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)
                s.connect((host, port))
                LOGGER.debug(f"[DevAppManager] Port {port} is open")
                return True
            except (socket.timeout, ConnectionRefusedError):
                LOGGER.debug(f"[DevAppManager] Port {port} is closed")
                return False
