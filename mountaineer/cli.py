import asyncio
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from importlib import import_module
from importlib.metadata import distributions
from multiprocessing import Event, Process, Queue, get_start_method, set_start_method
from multiprocessing.queues import Queue as QueueType
from pathlib import Path
from signal import SIGINT, signal
from tempfile import mkdtemp
from threading import Thread
from time import sleep, time
from traceback import format_exception
from typing import Any, Callable, MutableMapping

from click import secho
from fastapi import Request

from mountaineer.app import AppController
from mountaineer.client_builder.builder import ClientBuilder
from mountaineer.controllers.exception_controller import ExceptionController
from mountaineer.js_compiler.exceptions import BuildProcessException
from mountaineer.logging import LOGGER
from mountaineer.watch import (
    CallbackDefinition,
    CallbackMetadata,
    CallbackType,
    PackageWatchdog,
)
from mountaineer.watch_server import WatcherWebservice
from mountaineer.webservice import UvicornThread


@dataclass
class IsolatedBuildConfig:
    webcontroller: str

    # When builds are completed, a notification will be sent from the subprocess->main process
    # via this channel
    notification_channel: QueueType | None = None

    # If the main process needs to rebuild client js, this flag will open a channel
    # to the subprocess to rebuild the client js
    allow_js_reloads: bool = True

    # Optional arguments to inherit a global cache from the main process
    build_cache: Path | None = None
    build_state: MutableMapping[Any, Any] | None = None


@dataclass
class IsolatedRunserverConfig:
    entrypoint: str
    port: int
    live_reload_port: int


class IsolatedEnvProcess(Process):
    """
    We need a fully separate process for our runserver and watch, so we're able to re-import
    all of the dependent files when there are changes.

    """

    def __init__(
        self,
        build_config: IsolatedBuildConfig,
        runserver_config: IsolatedRunserverConfig | None = None,
    ):
        """
        build_state: State that was originally initialized in the main process, before
        we spawned this worker. This can be used to inherit settings or multiprocessing-safe
        objects that will stick around for the duration of the process lifecycle inbetween-watchers.

        """
        super().__init__()

        self.build_config = build_config
        self.runserver_config = runserver_config
        self.close_signal = Event()
        self.rebuild_channel: QueueType[bool | None] | None = (
            Queue() if build_config.allow_js_reloads else None
        )

    def run(self):
        LOGGER.debug(
            f"Starting isolated environment process with\nbuild_config: {self.build_config}\nrunserver_config: {self.runserver_config}"
        )

        app_controller = import_from_string(self.build_config.webcontroller)
        if not isinstance(app_controller, AppController):
            raise ValueError(
                f"Expected {self.build_config.webcontroller} to be an instance of AppController"
            )

        # Mount our exceptions controller, since we'll need these artifacts built
        # as part of the JS build phase
        self.exception_controller = ExceptionController()
        app_controller.register(self.exception_controller)
        app_controller.app.exception_handler(Exception)(self.handle_dev_exception)

        # Finish the build before we start the server since the server launch is going to sniff
        # for the built artifacts
        if self.build_config is not None:
            # Inject our tmp directory instead of the directories for the already registered
            # build components
            if self.build_config.build_cache:
                for builder in app_controller.builders:
                    builder.tmp_dir = self.build_config.build_cache
            if self.build_config.build_state:
                for builder in app_controller.builders:
                    builder.global_state = self.build_config.build_state

            self.run_build(app_controller)

            # If the client passed a rebuild channel, we'll listen for rebuild requests
            if self.build_config.allow_js_reloads:
                self.listen_for_rebuilds(app_controller)

        if self.runserver_config is not None:
            thread = UvicornThread(
                app=app_controller.app,
                port=self.runserver_config.port,
            )
            thread.start()
            try:
                self.close_signal.wait()
            except KeyboardInterrupt:
                pass
            thread.stop()
            thread.join()

        LOGGER.debug("IsolatedEnvProcess finished")

    def rebuild_js(self):
        LOGGER.debug("JS-Only rebuild started")
        if self.rebuild_channel is not None:
            self.rebuild_channel.put(True)
        else:
            raise ValueError("No rebuild channel was provided")

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
            if self.build_config.notification_channel is None:
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

            if self.build_config.notification_channel:
                self.build_config.notification_channel.put(True)

        alert_thread = Thread(target=wait_for_server)
        alert_thread.start()

    def listen_for_rebuilds(self, app_controller: AppController):
        """
        If clients place an object into the rebuild channel, our background thread
        will pick up on these updates and cause a JS-only reload. This only works if the
        application controller's logic hasn't changed, since we use the global one
        that was previously created in our isolated process.

        """

        def wait_for_rebuild():
            if not self.rebuild_channel:
                raise ValueError("No rebuild channel was provided")
            while True:
                rebuild = self.rebuild_channel.get()
                if rebuild is None:
                    break
                self.run_build(app_controller)

        LOGGER.debug("Will launch rebuild thread")
        rebuild_thread = Thread(target=wait_for_rebuild)
        rebuild_thread.start()

    def run_build(self, app_controller: AppController):
        secho("Starting build...", fg="yellow")
        start = time()
        js_compiler = ClientBuilder(
            app_controller,
            live_reload_port=(
                self.runserver_config.live_reload_port
                if self.runserver_config
                else None
            ),
            build_cache=self.build_config.build_cache,
        )
        try:
            js_compiler.build()
            secho(f"Build finished in {time() - start:.2f} seconds", fg="green")

            # Completed successfully
            app_controller.build_exception = None

            self.alert_notification_channel()
        except BuildProcessException as e:
            secho(f"Build failed: {e}", fg="red")
            app_controller.build_exception = e

    def stop(self, hard_timeout: float = 5.0):
        """
        Client-side stop method to shut down the running process.
        """
        # If we've already stopped, don't try to stop again
        if not self.is_alive():
            return

        if self.rebuild_channel is not None:
            self.rebuild_channel.put(None)

        if self.runserver_config is not None:
            self.close_signal.set()

        # Try to give the process time to shut down gracefully
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

    async def handle_dev_exception(self, request: Request, exc: Exception):
        # If we're receiving a GET request, show the exception. Otherwise fall back
        # on the normal REST handlers
        if request.method == "GET":
            response = await self.exception_controller._generate_html(
                global_metadata=None,
                exception=str(exc),
                stack="".join(format_exception(exc)),
            )
            response.status_code = 500
            return response
        else:
            raise exc


def handle_watch(
    *,
    package: str,
    webcontroller: str,
    subscribe_to_mountaineer: bool = False,
):
    """
    Watch the file directory and rebuild auto-generated files.

    :param package: Ex. "ci_webapp"
    :param webcontroller: Ex. "ci_webapp.app:controller"
    :param subscribe_to_mountaineer:
        If True, will subscribe the local build server to changes in
        the `mountaineer` package. This is useful when doing concurrent
        development in `mountaineer` and a client package. Rarely
        used otherwise.

    """
    update_multiprocessing_settings()

    current_process: IsolatedEnvProcess | None = None

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    def update_build(
        metadata: CallbackMetadata, global_state: MutableMapping[Any, Any]
    ):
        nonlocal current_process

        # JS-Only build needed
        if all(is_view_update(event.path) for event in metadata.events):
            if current_process is not None:
                current_process.rebuild_js()
                return

        if current_process is not None:
            # Stop the current process if it's running
            current_process.stop()

        current_process = IsolatedEnvProcess(
            build_config=IsolatedBuildConfig(
                webcontroller=webcontroller,
                build_cache=global_build_cache,
                build_state=global_state,
            ),
        )
        current_process.start()

    with init_global_state(webcontroller) as global_state:
        watchdog = build_common_watchdog(
            package,
            partial(update_build, global_state=global_state),
            subscribe_to_mountaineer=subscribe_to_mountaineer,
        )
        watchdog.start_watching()


def handle_runserver(
    *,
    package: str,
    webservice: str,
    webcontroller: str,
    port: int,
    subscribe_to_mountaineer: bool = False,
):
    """
    :param package: Ex. "ci_webapp"
    :param webservice: Ex. "ci_webapp.app:app"
    :param webcontroller: Ex. "ci_webapp.app:controller"
    :param port: Desired port for the webapp while running locally
    :param subscribe_to_mountaineer: See `handle_watch` for more details.

    """
    update_multiprocessing_settings()

    current_process: IsolatedEnvProcess | None = None

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    # Start the webservice - it should persist for the lifetime of the
    # runserver, so a single websocket frontend can be notified across
    # multiple builds
    watcher_webservice = WatcherWebservice()
    watcher_webservice.start()

    def update_build(metadata: CallbackMetadata, global_state: dict[Any, Any]):
        nonlocal current_process

        # JS-Only build needed
        if all(is_view_update(event.path) for event in metadata.events):
            if current_process is not None:
                current_process.rebuild_js()
                return

        if current_process is not None:
            # Stop the current process if it's running
            current_process.stop()

        current_process = IsolatedEnvProcess(
            runserver_config=IsolatedRunserverConfig(
                entrypoint=webservice,
                port=port,
                live_reload_port=watcher_webservice.port,
            ),
            build_config=IsolatedBuildConfig(
                webcontroller=webcontroller,
                notification_channel=watcher_webservice.notification_queue,
                build_cache=global_build_cache,
                build_state=global_state,
            ),
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

    with init_global_state(webcontroller) as global_state:
        watchdog = build_common_watchdog(
            package,
            partial(update_build, global_state=global_state),
            subscribe_to_mountaineer=subscribe_to_mountaineer,
        )
        watchdog.start_watching()


def handle_build(
    *,
    webcontroller: str,
):
    """
    Handle a one-off build. Most often used in production CI pipelines.

    """
    app_controller = import_from_string(webcontroller)
    js_compiler = ClientBuilder(
        app_controller,
        live_reload_port=None,
    )
    start = time()
    js_compiler.build()
    secho(f"Build finished in {time() - start:.2f} seconds", fg="green")


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
    Given a string to the package (like "ci_webapp.app:controller") import the
    actual variable
    """
    module_name, attribute_name = import_string.split(":")
    module = import_module(module_name)
    return getattr(module, attribute_name)


def find_packages_with_prefix(prefix: str):
    """
    Find and return a list of all installed package names that start with the given prefix.

    """
    return [
        dist.metadata["Name"]
        for dist in distributions()
        if dist.metadata["Name"].startswith(prefix)
    ]


def is_view_update(path: Path):
    """
    Determines if the file change is a view update. This assumes
    the user subscribes to our "views" convention.

    """
    return any(part == "views" for part in path.parts)


def build_common_watchdog(
    client_package: str,
    callback: Callable[[CallbackMetadata], None],
    subscribe_to_mountaineer: bool,
):
    """
    Useful creation class to build a watchdog the common client class
    and our internal package.

    :param subscribe_to_mountaineer: If True, we'll also subscribe to the mountaineer package
    changes in the local environment. This is helpful for local development of the core
    package concurrent with a downstream client application.

    """
    dependent_packages: list[str] = []
    if subscribe_to_mountaineer:
        # Found mountaineer core and mountaineer external dependencies
        dependent_packages = find_packages_with_prefix("mountaineer")
        LOGGER.debug(
            f"Subscribing to changes in local mountaineer packages: {dependent_packages}"
        )

    return PackageWatchdog(
        client_package,
        dependent_packages=dependent_packages,
        callbacks=[
            CallbackDefinition(
                CallbackType.CREATED | CallbackType.MODIFIED,
                callback,
            )
        ],
        # We want to generate a build on the first load
        run_on_bootup=True,
    )


@contextmanager
def init_global_state(webcontroller: str):
    """
    Initialize global state: signal to each builder that they can
    initialize global state before the fork.

    """
    global_state: dict[Any, Any] = {}

    app_controller = import_from_string(webcontroller)

    if not isinstance(app_controller, AppController):
        raise ValueError(f"Unknown app controller: {app_controller}")

    async def entrypoint():
        await asyncio.gather(
            *[builder.init_state(global_state) for builder in app_controller.builders]
        )

    asyncio.run(entrypoint())

    yield global_state
