import asyncio
import importlib
import sys
from importlib.metadata import distributions
from multiprocessing import get_start_method, set_start_method
from pathlib import Path
from signal import SIGINT, signal
from tempfile import mkdtemp
from time import sleep, time
from typing import Callable

from rich.traceback import install as rich_traceback_install

from mountaineer.app_manager import AppManager
from mountaineer.cache import LRUCache
from mountaineer.client_builder.builder import ClientBuilder
from mountaineer.console import CONSOLE
from mountaineer.constants import KNOWN_JS_EXTENSIONS
from mountaineer.logging import LOGGER
from mountaineer.ssr import render_ssr
from mountaineer.watch import (
    CallbackDefinition,
    CallbackMetadata,
    CallbackType,
    PackageWatchdog,
)
from mountaineer.watch_server import WatcherWebservice


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

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    app_manager = AppManager.from_webcontroller(webcontroller)
    js_compiler = ClientBuilder(
        app_manager.app_controller,
        live_reload_port=None,
        build_cache=global_build_cache,
    )

    asyncio.run(js_compiler.build_all())

    def update_build(metadata: CallbackMetadata):
        updated_js: set[Path] = set()
        updated_python: set[Path] = set()

        for event in metadata.events:
            if event.path.suffix in KNOWN_JS_EXTENSIONS:
                updated_js.add(event.path)
            elif event.path.suffix in {".py"}:
                updated_python.add(event.path)

        # Update the use-server definitions in case modifications to the
        # python file affected the API spec
        if updated_python:
            asyncio.run(js_compiler.build_use_server())
        if updated_js:
            asyncio.run(js_compiler.build_fe_diff(list(updated_js)))

    watchdog = build_common_watchdog(
        package,
        update_build,
        subscribe_to_mountaineer=subscribe_to_mountaineer,
    )
    watchdog.start_watching()


def handle_runserver(
    *,
    package: str,
    webservice: str,
    webcontroller: str,
    host: str = "127.0.0.1",
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
    rich_traceback_install()

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    # Start the webservice - it should persist for the lifetime of the
    # runserver, so a single websocket frontend can be notified across
    # multiple builds
    start = time()
    watcher_webservice = WatcherWebservice(webservice_host=host)
    watcher_webservice.start()

    app_manager = AppManager.from_webcontroller(webcontroller)
    LOGGER.debug(f"Initial load of {webcontroller} complete.")

    js_compiler = ClientBuilder(
        app_manager.app_controller,
        live_reload_port=watcher_webservice.port,
        build_cache=global_build_cache,
    )
    asyncio.run(js_compiler.build_all())

    # Start the initial thread
    # TODO: Clean up the variable passing between clientbuilder and app controller
    app_manager.port = port
    app_manager.host = host
    app_manager.app_controller.live_reload_port = watcher_webservice.port
    app_manager.restart_server()
    CONSOLE.print(f"[bold green]🚀 App launched in {time() - start:.2f} seconds")

    def update_build(metadata: CallbackMetadata):
        start = time()

        # Consider the case where we have the app controller that imports a given module
        # ```
        # import myapp.controller as controller
        # ```
        # And within this controller we have an import from the file that we've changed as part
        # of this modification
        # ```
        # from myapp.module import MyController as MyController
        # ```
        # By default, an importlib.refresh(app_controller_module) won't update this given sub-dependency, since
        # Python holds tighly to objects that are brought into scope and are not only global system modules.
        #
        # We keep track of the unique objects that are contained within the updated files, so we can
        # manually inspect the project for any objects that are still referencing the old module.
        # and update them manually.
        objects_to_reload: set[int] = set()

        updated_js: set[Path] = set()
        updated_python: set[Path] = set()

        for event in metadata.events:
            if (
                event.action != CallbackType.MODIFIED
                and event.action != CallbackType.CREATED
            ):
                # Keep deleted files around for now
                continue

            if event.path.suffix == ".py":
                updated_python.add(event.path)
                module_name = app_manager.package_path_to_module(event.path)

                # Get the IDs before we reload the module, since they'll change after
                # the re-import
                current_module = sys.modules[module_name]
                objects_to_reload |= app_manager.objects_in_module(current_module)

                # Now, once we've cached the ids of objects currently in memory we can clear
                # the actual model definition from the module cache
                updated_module = importlib.import_module(module_name)
                importlib.reload(updated_module)
            elif event.path.suffix in KNOWN_JS_EXTENSIONS:
                updated_js.add(event.path)

        # Logging in the following section assumes we're actually doing some
        # work; if we're not, we should just exit early
        if not updated_js and not updated_python:
            return

        if updated_python:
            LOGGER.debug(f"Changed Python: {updated_python}")
            asyncio.run(js_compiler.build_use_server())

        if updated_js:
            LOGGER.debug(f"Changed JS: {updated_js}")
            asyncio.run(js_compiler.build_fe_diff(list(updated_js)))

            # TODO: Switch to the DAG state management of imports
            # that's provided by mountaineer_rs
            for path in updated_js:
                app_manager.app_controller.invalidate_view(path)

        if updated_python:
            # Update the nested dependencies of our app that are brought into runtime
            # and still hold on to an outdated version of the module. We reload these
            # so they'll proceed to fetch and update themselves with the contents of the new module.
            all_updated_components = list(
                app_manager.get_submodules_with_objects(
                    app_manager.module, objects_to_reload
                )
            )
            for updated_module in all_updated_components:
                LOGGER.debug(f"Updating dependent module: {updated_module}")
                importlib.reload(updated_module)

            # Now we re-mount the app entrypoint, which should initialize the changed
            # controllers with their new values
            app_manager.update_module()

            # Clear the cache so changes to the python logic should re-calculate
            # their ssr views
            if hasattr("render_ssr", "_cache"):
                lru_cache: LRUCache = getattr(render_ssr, "_cache")
                LOGGER.debug(f"Clearing SSR cache of {len(lru_cache.cache)} items")
                lru_cache.clear()

            app_manager.restart_server()

        if updated_js or updated_python:
            # Wait up to 5s for our webserver to start, so when we refresh
            # the new page is ready immediately.
            start_time = time()
            max_wait_time = 5
            while time() - start_time < max_wait_time:
                if app_manager.is_port_open("127.0.0.1", port):
                    CONSOLE.print(f"[blue]Webserver is ready on {"127.0.0.1"}:{port}!")
                    break
                sleep(0.1)  # Short sleep to prevent busy-waiting

            watcher_webservice.notification_queue.put(True)

        CONSOLE.print(f"[bold green]🚀 App relaunched in {time() - start:.2f} seconds")

    # Install a signal handler to catch SIGINT and try to
    # shut down gracefully
    def graceful_shutdown(signum, frame):
        if watcher_webservice is not None:
            watcher_webservice.stop()
        CONSOLE.print("[yellow]Services shutdown, now exiting...")
        exit(0)

    signal(SIGINT, graceful_shutdown)

    watchdog = build_common_watchdog(
        package,
        update_build,
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
    app_manager = AppManager.from_webcontroller(webcontroller)

    js_compiler = ClientBuilder(
        app_manager.app_controller,
        live_reload_port=None,
    )
    start = time()

    asyncio.run(js_compiler.build_all())
    CONSOLE.print(f"[bold green]App built in {time() - start:.2f}s")


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


def find_packages_with_prefix(prefix: str):
    """
    Find and return a list of all installed package names that start with the given prefix.

    """
    return [
        dist.metadata["Name"]
        for dist in distributions()
        if dist.metadata["Name"].startswith(prefix)
    ]


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
