import socket
import uuid
from typing import Any
import os
import asyncio
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
from contextlib import asynccontextmanager


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
        print(f"[DevAppManager] Initializing manager for {package}.{module_name}:{controller_name}")
        self.package = package
        self.module_name = module_name
        self.controller_name = controller_name
        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port

        # Message broker for communicating with isolated context
        print("[DevAppManager] Creating message broker")
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
        print(f"[DevAppManager] Creating manager from webcontroller: {webcontroller}")
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
            print("[DevAppManager] Entering async context")
            self.message_broker.start()
            yield self
        finally:
            await self.message_broker.stop()

    def restart_server(self):
        """Restart the server in a fresh process"""
        print("[DevAppManager] Restarting server")
        if not self.port:
            print("[DevAppManager] Error: Port not set")
            raise ValueError("Port not set")

        # Stop existing context if running
        if self.app_context and self.app_context.is_alive():
            print("[DevAppManager] Shutting down existing app context")
            message_id = str(uuid.uuid4())
            print(f"[DevAppManager] Sending shutdown message {message_id}")
            self.message_broker.message_queue.put(
                (message_id, ShutdownMessage())
            )
            print("[DevAppManager] Waiting for app context to join")
            self.app_context.join(timeout=5)
            if self.app_context.is_alive():
                print("[DevAppManager] App context did not shut down gracefully, terminating")
                self.app_context.terminate()

        # Start new context
        print("[DevAppManager] Starting new app context")
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
        print("[DevAppManager] New app context started")

    async def reload_modules(self, module_names: list[str]) -> ReloadResponse:
        """
        Signal the context to reload modules and wait for response.
        Returns a tuple of (success, reloaded_modules, needs_restart).
        """
        print(f"[DevAppManager] Attempting to reload modules: {module_names}")
        print(f"[DevAppManager] Current process: {os.getpid()}")
        
        if not (self.app_context and self.app_context.is_alive()):
            print("[DevAppManager] No active app context, returning needs_restart")
            return ReloadResponse(
                success=False,
                reloaded=[],
                needs_restart=True,
            )

        print("[DevAppManager] Sending reload message")
        print(f"[DevAppManager] App context process ID: {self.app_context.pid}")
        response = await self.message_broker.send_message(
            ReloadModulesMessage(
                module_names=module_names,
            )
        )
        print(f"[DevAppManager] Received reload response: {response}")
        print(f"[DevAppManager] Response type: {type(response)}")

        CONSOLE.print(f"Reload response: {response}")
        return response

    def build_js(self):
        """Signal the context to rebuild JS"""
        print("[DevAppManager] Requesting JS build")
        if self.app_context and self.app_context.is_alive():
            message_id = str(uuid.uuid4())
            print(f"[DevAppManager] Sending build JS message {message_id}")
            self.message_broker.message_queue.put((message_id, BuildJsMessage()))
        else:
            print("[DevAppManager] No active app context, skipping JS build")

    def is_port_open(self, host, port):
        """Check if a port is open on the given host."""
        print(f"[DevAppManager] Checking if port {port} is open on {host}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)
                s.connect((host, port))
                print(f"[DevAppManager] Port {port} is open")
                return True
            except (socket.timeout, ConnectionRefusedError):
                print(f"[DevAppManager] Port {port} is closed")
                return False
