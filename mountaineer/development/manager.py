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
    The main entrypoint for the main process to communicate with our isolated
    app context that's spawned in its own process. We execute logic within the
    isolated context through message passing.

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
