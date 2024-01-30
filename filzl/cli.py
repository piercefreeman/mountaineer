from importlib import import_module
from multiprocessing import Event, Process
from time import time
from typing import Callable

from click import secho
from pydantic.main import BaseModel

from filzl.client_interface.builder import ClientBuilder
from filzl.watch import CallbackDefinition, CallbackType, PackageWatchdog
from filzl.webservice import UvicornThread


class IsolatedRunserverConfig(BaseModel):
    entrypoint: str
    port: int


class IsolatedWatchConfig(BaseModel):
    webcontroller: str


class IsolatedEnvProcess(Process):
    """
    We need a fully separate process for our runserver and watch, so we're able to re-import
    all of the dependent files when there are changes.

    """

    def __init__(
        self,
        runserver_config: IsolatedRunserverConfig | None = None,
        watch_config: IsolatedWatchConfig | None = None,
    ):
        super().__init__()

        if runserver_config is None and watch_config is None:
            raise ValueError("Must provide either runserver_config or watch_config")

        self.runserver_config = runserver_config
        self.watch_config = watch_config
        self.close_signal = Event()

    def run(self):
        # Finish the build before we start the server since the server launch is going to sniff
        # for the built artifacts
        if self.watch_config is not None:
            secho("Starting build...", fg="yellow")
            start = time()
            client_builder = ClientBuilder(
                import_from_string(self.watch_config.webcontroller)
            )
            client_builder.build()
            secho(f"Build finished in {time() - start:.2f} seconds", fg="green")

        if self.runserver_config is not None:
            thread = UvicornThread(
                self.runserver_config.entrypoint, self.runserver_config.port
            )
            thread.start()
            self.close_signal.wait()
            thread.stop()
            thread.join()

    def stop(self, hard_timeout: float = 5.0):
        # If we've already stopped, don't try to stop again
        if not self.is_alive():
            return
        if self.runserver_config is not None:
            self.close_signal.set()
            # Try to give the server time to shut down gracefully
            while self.is_alive() and hard_timeout > 0:
                self.join(1)
                hard_timeout -= 1

        # As a last resort we send a hard termination signal
        if self.is_alive():
            self.terminate()


def handle_watch(
    *,
    package: str,
    webcontroller: str,
):
    """
    Watch the file directory and rebuild auto-generated files.

    :param client_package: "my_website"
    :param client_controller: "my_website.app:controller"

    """
    current_process: IsolatedEnvProcess | None = None

    def update_build():
        nonlocal current_process

        if current_process is not None:
            # Stop the current process if it's running
            current_process.stop()

        current_process = IsolatedEnvProcess(
            watch_config=IsolatedWatchConfig(webcontroller=webcontroller),
        )
        current_process.start()

    # Initial build right on load
    update_build()

    watchdog = build_common_watchdog(package, update_build)
    watchdog.start_watching()


def handle_runserver(
    *,
    package: str,
    webservice: str,
    webcontroller: str,
    port: int,
):
    """
    :param client_package: "my_website"
    :param client_webservice: "my_website.app:app"
    :param client_controller: "my_website.app:controller"

    """
    current_process: IsolatedEnvProcess | None = None

    def update_build():
        nonlocal current_process

        if current_process is not None:
            # Stop the current process if it's running
            current_process.stop()

        current_process = IsolatedEnvProcess(
            runserver_config=IsolatedRunserverConfig(
                entrypoint=webservice,
                port=port,
            ),
            watch_config=IsolatedWatchConfig(webcontroller=webcontroller),
        )
        current_process.start()

    # Initial launch - both build and run the server, since we may not have
    # any built client-side files yet
    update_build()

    watchdog = build_common_watchdog(package, update_build)
    watchdog.start_watching()


def import_from_string(import_string: str):
    """
    Given a string to the package (like "my_website.app:controller") import the
    actual variable
    """
    module_name, attribute_name = import_string.split(":")
    module = import_module(module_name)
    return getattr(module, attribute_name)


def restart_build_server(webcontroller: str):
    client_builder = ClientBuilder(import_from_string(webcontroller))
    client_builder.build()


def build_common_watchdog(client_package: str, callback: Callable):
    """
    Useful creation class to build a watchdog the common client class
    and our internal package.

    """
    return PackageWatchdog(
        client_package,
        dependent_packages=["filzl"],
        callbacks=[
            CallbackDefinition(
                CallbackType.CREATED | CallbackType.MODIFIED,
                callback,
            )
        ],
    )
