import importlib
import os
import socket
import sys
from dataclasses import dataclass
from importlib.metadata import distributions
from multiprocessing import Process, Queue
from pathlib import Path
from tempfile import mkdtemp
from traceback import format_exception
from types import ModuleType
from typing import Any, Literal

from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.controllers.exception_controller import (
    ExceptionController,
)
from mountaineer.logging import LOGGER
from mountaineer.webservice import UvicornThread


@dataclass
class ServerMessage:
    """Message passed between main process and server worker"""
    type: Literal["reload_modules", "shutdown"]
    data: Any = None


class ServerWorker(Process):
    """
    Worker process that runs the server and handles module reloading.
    This isolates the server from the main process, allowing for clean restarts.
    """

    def __init__(
        self,
        package: str,
        module_name: str,
        controller_name: str,
        host: str | None,
        port: int,
        live_reload_port: int | None,
        message_queue: Queue,
    ):
        super().__init__()
        self.package = package
        self.module_name = module_name
        self.controller_name = controller_name
        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port
        self.message_queue = message_queue
        self.webservice_thread: UvicornThread | None = None

    def run(self):
        """Main worker process loop"""
        try:
            # Initialize the app controller
            module = importlib.import_module(self.module_name)
            initial_state = {name: getattr(module, name) for name in dir(module)}
            self.app_controller = initial_state[self.controller_name]

            # Mount exceptions
            self.exception_controller = ExceptionController()
            self.mount_exceptions(self.app_controller)

            # Start the server
            self.start_server()

            # Process messages until shutdown
            while True:
                message: ServerMessage = self.message_queue.get()
                if message.type == "shutdown":
                    break
                elif message.type == "reload_modules":
                    self.handle_module_reload()

        except Exception as e:
            LOGGER.error(f"Server worker failed: {e}", exc_info=True)
        finally:
            if self.webservice_thread:
                self.webservice_thread.stop()

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

    def handle_module_reload(self):
        """Handle module reloading within the worker process"""
        try:
            # Re-import the module to get fresh state
            self.module = importlib.import_module(self.module_name)
            initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
            self.app_controller = initial_state[self.controller_name]

            # Re-mount exceptions
            self.mount_exceptions(self.app_controller)

            # Restart the server with new controller
            self.start_server()
        except Exception as e:
            LOGGER.error(f"Failed to reload modules: {e}", exc_info=True)

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
    Manages the lifecycle of a single app controller. This is only intended
    for development use.

    """

    def __init__(
        self,
        package: str,
        module: ModuleType,
        module_name: str,
        controller_name: str,
        app_controller: AppController,
        host: str | None,
        port: int | None,
        live_reload_port: int | None,
    ):
        self.package = package
        self.module = module
        self.module_name = module_name
        self.controller_name = controller_name
        self.app_controller = app_controller

        self.host = host
        self.port = port
        self.live_reload_port = live_reload_port

        # Message queue for communicating with server worker
        self.message_queue = Queue()
        self.server_worker: ServerWorker | None = None

        # Initialize builders
        global_build_cache = Path(mkdtemp())
        self.js_compiler = APIBuilder(
            app_controller,
            live_reload_port=live_reload_port,
            build_cache=global_build_cache,
        )

        self.app_compiler = ClientCompiler(
            app=app_controller,
        )

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

        module = importlib.import_module(module_name)
        initial_state = {name: getattr(module, name) for name in dir(module)}
        app_controller = initial_state[controller_name]

        return cls(
            package=package,
            module=module,
            module_name=module_name,
            controller_name=controller_name,
            app_controller=app_controller,
            host=host,
            port=port,
            live_reload_port=live_reload_port,
        )

    def update_module(self):
        """Update the module in the main process for builders"""
        self.module = sys.modules[self.module.__name__]
        initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
        self.app_controller = initial_state[self.controller_name]

        # Update builders with new controller
        self.js_compiler.update_controller(self.app_controller)
        self.app_compiler.update_controller(self.app_controller)

    def restart_server(self):
        """Restart the server in a fresh process"""
        if not self.port:
            raise ValueError("Port not set")

        # Stop existing worker if running
        if self.server_worker and self.server_worker.is_alive():
            self.message_queue.put(ServerMessage(type="shutdown"))
            self.server_worker.join(timeout=5)
            if self.server_worker.is_alive():
                self.server_worker.terminate()

        # Start new worker
        self.server_worker = ServerWorker(
            package=self.package,
            module_name=self.module_name,
            controller_name=self.controller_name,
            host=self.host,
            port=self.port,
            live_reload_port=self.live_reload_port,
            message_queue=self.message_queue,
        )
        self.server_worker.start()

    def reload_modules(self):
        """Signal the worker to reload modules"""
        if self.server_worker and self.server_worker.is_alive():
            self.message_queue.put(ServerMessage(type="reload_modules"))

    def is_port_open(self, host, port):
        """
        Check if a port is open on the given host.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.settimeout(0.1)  # Set a short timeout for the connection attempt
                s.connect((host, port))
                return True
            except (socket.timeout, ConnectionRefusedError):
                return False

    def mount_exceptions(self, app_controller: AppController):
        # Don't re-mount the exception controller; this can happen if we
        # re-import the module and the underlying app controller is not re-initialized
        current_controllers = [
            controller_definition.controller.__class__.__name__
            for controller_definition in app_controller.controllers
        ]

        if self.exception_controller.__class__.__name__ not in current_controllers:
            app_controller.register(self.exception_controller)
            app_controller.app.exception_handler(Exception)(self.handle_dev_exception)

    async def handle_dev_exception(self, request: Request, exc: Exception):
        # If we're receiving a GET request, show the exception. Otherwise fall back
        # on the normal REST handlers
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
