import importlib
import socket
import sys
from importlib.metadata import distributions
from traceback import format_exception
from types import ModuleType

from fastapi import Request
from fastapi.responses import Response

from mountaineer.app import AppController
from mountaineer.controllers.exception_controller import ExceptionController
from mountaineer.webservice import UvicornThread


class HotReloadManager:
    """
    Manages the lifecycle of a single app controller, including its webservice thread
    and utilities for hot-reloading.

    This is only intended for development use.

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

        self.webservice_thread: UvicornThread | None = None
        self.host = host
        self.port = port

        self.live_reload_port = live_reload_port

        self.exception_controller = ExceptionController()

        # Initial mount
        self.mount_exceptions(app_controller)

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
        print("SHOULD UPDATE MODULE", self.module.__name__)
        # By the time we get to this point, our hot reloader should
        # have already reloaded the module in global space
        self.module = sys.modules[self.module.__name__]
        # self.module = importlib.reload(self.module)
        initial_state = {name: getattr(self.module, name) for name in dir(self.module)}
        self.app_controller = initial_state[self.controller_name]

        # Re-mount the exceptions now that we have a new app controller
        self.mount_exceptions(self.app_controller)

    def restart_server(self):
        if not self.port:
            raise ValueError("Port not set")

        if self.webservice_thread is not None:
            self.webservice_thread.stop()

        # Inject the live reload port so it's picked up even
        # when the app changes
        self.app_controller.live_reload_port = self.live_reload_port or 0

        self.webservice_thread = UvicornThread(
            app=self.app_controller.app,
            host=self.host or "127.0.0.1",
            port=self.port,
        )
        self.webservice_thread.start()

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
            # raise NotImplementedError
            # response = await self.exception_controller._generate_html(
            #     global_metadata=None,
            #     exception=str(exc),
            #     stack="".join(format_exception(exc)),
            # )
            # response.status_code = 500
            # return response
            return Response("".join(format_exception(exc)))
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
