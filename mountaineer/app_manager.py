import importlib
import os
import socket
import sys
import asyncio
import uuid
from typing import Optional, Any, Dict, TypeVar, Generic
from dataclasses import dataclass
from importlib.metadata import distributions
from multiprocessing import Process, Queue
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception
from types import ModuleType
from typing import Any, Literal, TypedDict
from asyncio import Future

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.controllers.exception_controller import (
    ExceptionController,
)
from mountaineer.logging import LOGGER
from mountaineer.webservice import UvicornThread
from mountaineer.hotreload import HotReloader


T = TypeVar('T')


class AsyncMessageBroker(Generic[T]):
    """
    A thread and process-safe message broker that allows async communication between
    processes. This broker maintains a mapping between message IDs and their corresponding
    futures, allowing async code to await responses from other processes.
    """
    def __init__(self):
        self.message_queue: Queue = Queue()
        self.response_queue: Queue = Queue()
        self._pending_futures: Dict[str, Future[T]] = {}
        self._response_task: Optional[asyncio.Task] = None

    def start(self):
        """Start the response consumer task"""
        if self._response_task is None:
            self._response_task = asyncio.create_task(self._consume_responses())

    async def stop(self):
        """Stop the response consumer task"""
        if self._response_task is not None:
            self._response_task.cancel()
            try:
                await self._response_task
            except asyncio.CancelledError:
                pass
            self._response_task = None

    async def _consume_responses(self):
        """Consume responses from the response queue and resolve corresponding futures"""
        while True:
            try:
                # Use run_in_executor to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                response_id, response = await loop.run_in_executor(None, self.response_queue.get)
                
                if response_id in self._pending_futures:
                    future = self._pending_futures.pop(response_id)
                    if not future.done():
                        future.set_result(response)
            except Exception as e:
                LOGGER.error(f"Error consuming response: {e}", exc_info=True)

    async def send_message(self, message: Any) -> T:
        """
        Send a message and return a future that will be resolved with the response
        """
        message_id = str(uuid.uuid4())
        future: Future[T] = asyncio.Future()
        self._pending_futures[message_id] = future
        
        # Send message with ID
        self.message_queue.put((message_id, message))
        return await future


@dataclass
class AppMessage:
    """Message passed between main process and isolated app context"""
    type: Literal["reload_modules", "build_js", "shutdown"]
    data: Any = None


class ReloadResponse(TypedDict):
    success: bool
    reloaded: list[str]
    needs_restart: bool


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
        message_broker: AsyncMessageBroker[Any],
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
                message: AppMessage = message

                if message.type == "shutdown":
                    break
                elif message.type == "reload_modules":
                    response = self.handle_module_reload()
                    print(f"Sending response: {response}")
                    self.message_broker.response_queue.put((message_id, response))
                elif message.type == "build_js":
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
            initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
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

    def handle_module_reload(self) -> ReloadResponse:
        """Handle module reloading within the isolated context"""
        try:
            # Get the list of modules to reload from the hot reloader
            success, reloaded, needs_restart, error = self.hot_reloader.reload_module(self.module_name)

            # TODO: We should have another message that does this
            if success and not needs_restart:
                # Re-initialize all app state
                # self.initialize_app_state()

                # Rebuild JS since module changed
                asyncio.run(self.js_compiler.build_use_server())

                # Restart the server with new controller
                self.start_server()

            return {
                "success": success,
                "reloaded": reloaded,
                "needs_restart": needs_restart,
                "exception": str(error) if error else None,
                "traceback": "".join(format_exception(error)) if error else None,
            }
        except Exception as e:
            LOGGER.debug(f"Failed to reload modules: {e}", exc_info=True)
            return {
                "success": False,
                "reloaded": [],
                "needs_restart": True,
                "exception": str(e),
                "traceback": "".join(format_exception(e)),
            }

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


class DevAppManager:
    """
    Manages the lifecycle of an isolated app context. This is only intended
    for development use.
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
        self.message_broker: AsyncMessageBroker[Any] = AsyncMessageBroker()
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
            self.message_broker.message_queue.put((str(uuid.uuid4()), AppMessage(type="shutdown")))
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
            return {
                "success": False,
                "reloaded": [],
                "needs_restart": True,
            }

        return await self.message_broker.send_message(AppMessage(
            type="reload_modules",
            data=module_names,
        ))

    def build_js(self):
        """Signal the context to rebuild JS"""
        if self.app_context and self.app_context.is_alive():
            self.message_broker.message_queue.put((
                str(uuid.uuid4()),
                AppMessage(type="build_js")
            ))

    def is_port_open(self, host, port):
        """Check if a port is open on the given host."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)
                s.connect((host, port))
                return True
            except (socket.timeout, ConnectionRefusedError):
                return False


def find_packages_with_prefix(prefix: str):
    """
    Find and return a list of all installed package names that start with the given prefix.

    """
    return [
        dist.metadata["Name"]
        for dist in distributions()
        if dist.metadata["Name"].startswith(prefix)
    ]


def package_path_to_module(package: str, file_path_raw: Path) -> str:
    """
    Convert a file path to its corresponding Python module path.

    Args:
        package: The root package name (e.g. 'amplify')
        file_path_raw: The file path to convert

    Returns:
        The full module path (e.g. 'amplify.controllers.auth')
    """
    # Get the package's root directory
    package_module = importlib.import_module(package)
    if not package_module.__file__:
        raise ValueError(f"The package {package} does not have a __file__ attribute")

    package_root = os.path.dirname(package_module.__file__)
    file_path = os.path.abspath(str(file_path_raw))

    # Check if the file is within the package
    if not file_path.startswith(package_root):
        raise ValueError(f"The file {file_path} is not in the package {package}")

    # Remove the package root and the file extension
    relative_path = os.path.relpath(file_path, package_root)
    module_path = os.path.splitext(relative_path)[0]

    # Convert path separators to dots and add the package name
    return f"{package}.{module_path.replace(os.sep, '.')}"
