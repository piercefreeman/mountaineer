import asyncio
import socket
from importlib import import_module
from multiprocessing import Event, Process, get_start_method, set_start_method
from multiprocessing.queues import Queue
from signal import SIGINT, signal
from threading import Thread
from time import sleep, time
from typing import Callable

from click import secho
from pydantic.main import BaseModel

from filzl.client_builder.builder import ClientBuilder
from filzl.logging import LOGGER
from filzl.watch import CallbackDefinition, CallbackType, PackageWatchdog
from filzl.watch_server import get_watcher_webservice
from filzl.webservice import UvicornThread


class IsolatedRunserverConfig(BaseModel):
    entrypoint: str
    port: int
    live_reload_port: int


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
        build_notification_channel: Queue | None = None,
    ):
        super().__init__()

        if runserver_config is None and watch_config is None:
            raise ValueError("Must provide either runserver_config or watch_config")

        self.runserver_config = runserver_config
        self.watch_config = watch_config
        self.close_signal = Event()
        self.build_notification_channel = build_notification_channel

    def run(self):
        # Finish the build before we start the server since the server launch is going to sniff
        # for the built artifacts
        if self.watch_config is not None:
            secho("Starting build...", fg="yellow")
            start = time()
            js_compiler = ClientBuilder(
                import_from_string(self.watch_config.webcontroller),
                live_reload_port=(
                    self.runserver_config.live_reload_port
                    if self.runserver_config
                    else None
                ),
            )
            js_compiler.build()
            secho(f"Build finished in {time() - start:.2f} seconds", fg="green")

            self.alert_notification_channel()

        if self.runserver_config is not None:
            thread = UvicornThread(
                self.runserver_config.entrypoint, self.runserver_config.port
            )
            thread.start()
            try:
                self.close_signal.wait()
            except KeyboardInterrupt:
                pass
            thread.stop()
            thread.join()

        LOGGER.debug("IsolatedEnvProcess finished")

    def alert_notification_channel(self):
        """
        Alerts the notification channel of a build update, once the server
        comes back online. Before this the client might refresh and get a blank
        page because the server hasn't yet booted.
        """

        def wait_for_server():
            # No need to do anything if we don't have a notification channel
            if self.runserver_config is None:
                return
            if self.build_notification_channel is None:
                return

            # Loop until there is something bound to the runserver_config.port
            start = time()
            LOGGER.debug("Waiting for server to come online")
            while True:
                try:
                    with socket.create_connection(
                        ("localhost", self.runserver_config.port)
                    ):
                        break
                except ConnectionRefusedError:
                    sleep(0.1)
            LOGGER.debug(f"Server took {time() - start:.2f} seconds to come online")

            # Buffer to make sure the server is fully booted
            sleep(0.5)

            if self.build_notification_channel:
                self.build_notification_channel.put(True)

        alert_thread = Thread(target=wait_for_server)
        alert_thread.start()

    def stop(self, hard_timeout: float = 5.0):
        """
        Client-side stop method to shut down the running process.
        """
        # If we've already stopped, don't try to stop again
        if not self.is_alive():
            return
        if self.runserver_config is not None:
            self.close_signal.set()
            # Try to give the server time to shut down gracefully
            while self.is_alive() and hard_timeout > 0:
                self.join(1)
                hard_timeout -= 1

            if hard_timeout == 0:
                secho(
                    f"Server shutdown reached hard timeout deadline: {self.is_alive()}",
                    fg="red",
                )

        # As a last resort we send a hard termination signal
        if self.is_alive():
            self.terminate()


def handle_watch(
    *,
    package: str,
    webcontroller: str,
    subscribe_to_fizl: bool = False,
):
    """
    Watch the file directory and rebuild auto-generated files.

    :param client_package: "my_website"
    :param client_controller: "my_website.app:controller"

    """
    update_multiprocessing_settings()

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

    watchdog = build_common_watchdog(
        package, update_build, subscribe_to_fizl=subscribe_to_fizl
    )
    watchdog.start_watching()


def handle_runserver(
    *,
    package: str,
    webservice: str,
    webcontroller: str,
    port: int,
    subscribe_to_fizl: bool = False,
):
    """
    :param client_package: "my_website"
    :param client_webservice: "my_website.app:app"
    :param client_controller: "my_website.app:controller"

    """
    update_multiprocessing_settings()

    current_process: IsolatedEnvProcess | None = None

    # Start the webservice - it should persist for the lifetime of the
    # runserver, so a single websocket frontend can be notified across
    # multiple builds
    watcher_webservice = get_watcher_webservice()
    watcher_webservice.start()

    def update_webservice():
        asyncio.run(watcher_webservice.broadcast_listeners())

    def update_build():
        nonlocal current_process

        if current_process is not None:
            # Stop the current process if it's running
            current_process.stop()

        current_process = IsolatedEnvProcess(
            runserver_config=IsolatedRunserverConfig(
                entrypoint=webservice,
                port=port,
                live_reload_port=watcher_webservice.port,
            ),
            watch_config=IsolatedWatchConfig(webcontroller=webcontroller),
            build_notification_channel=watcher_webservice.notification_queue,
        )
        current_process.start()

    # Install a signal handler to catch SIGINT and try to
    # shut down gracefully
    def graceful_shutdown(signum, frame):
        if current_process is not None:
            current_process.stop()
        if watcher_webservice is not None:
            watcher_webservice.stop()
        secho("Services shutdown, now exiting...", fg="yellow")
        exit(0)

    signal(SIGINT, graceful_shutdown)

    watchdog = build_common_watchdog(
        package, update_build, subscribe_to_fizl=subscribe_to_fizl
    )
    watchdog.start_watching()


def update_multiprocessing_settings():
    """
    fork() is still the default on Linux, and can result in stalls with our asyncio
    event loops. For consistency and expected behavior, try to switch to spawn()
    if it's not already enabled.

    """
    if (spawn_method := get_start_method()) and spawn_method != "spawn":
        LOGGER.warning(
            f"The watch command should be run with the spawn start method, but it's currently set to {spawn_method}",
        )

        try:
            set_start_method("spawn", force=True)
            LOGGER.info("Start method is now set to 'spawn'.")
        except RuntimeError as e:
            # We might catch errors if set_start_method('spawn') is called
            # in an inappropriate context or after multiprocessing has started, which
            # is not allowed.
            LOGGER.error(f"Cannot change the start method after it has been used: {e}")


def import_from_string(import_string: str):
    """
    Given a string to the package (like "my_website.app:controller") import the
    actual variable
    """
    module_name, attribute_name = import_string.split(":")
    module = import_module(module_name)
    return getattr(module, attribute_name)


def build_common_watchdog(
    client_package: str,
    callback: Callable,
    subscribe_to_fizl: bool,
):
    """
    Useful creation class to build a watchdog the common client class
    and our internal package.

    :param subscribe_to_fizl: If True, we'll also subscribe to the filzl package
    changes in the local environment. This is helpful for local development of the core
    package concurrent with a downstream client application.

    """
    return PackageWatchdog(
        client_package,
        dependent_packages=["filzl"] if subscribe_to_fizl else [],
        callbacks=[
            CallbackDefinition(
                CallbackType.CREATED | CallbackType.MODIFIED,
                callback,
            )
        ],
        # We want to generate a build on the first load
        run_on_bootup=True,
    )
