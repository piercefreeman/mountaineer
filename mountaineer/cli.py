import asyncio
import os
import traceback
from dataclasses import dataclass, field
from hashlib import md5
from multiprocessing import get_start_method, set_start_method
from pathlib import Path
from signal import SIGINT
from time import time
from typing import Any, Callable, Coroutine
import threading

from inflection import underscore
from rich.progress import Progress, SpinnerColumn, TimeElapsedColumn
from rich.traceback import install as rich_traceback_install

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.console import CONSOLE
from mountaineer.constants import KNOWN_JS_EXTENSIONS
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.manager import (
    DevAppManager,
)
from mountaineer.development.messages import (
    AsyncMessageBroker,
    ErrorResponse,
    IsolatedMessageBase,
    ReloadResponseError,
    ReloadResponseSuccess,
    SuccessResponse,
)
from mountaineer.development.packages import (
    find_packages_with_prefix,
    package_path_to_module,
)
from mountaineer.development.watch import (
    CallbackDefinition,
    CallbackMetadata,
    CallbackType,
    PackageWatchdog,
)
from mountaineer.development.watch_server import WatcherWebservice
from mountaineer.io import async_to_sync
from mountaineer.logging import LOGGER
from mountaineer.static import get_static_path
from firehot import isolate_imports
from multiprocessing import Manager, Queue
from multiprocessing.managers import BaseManager
import secrets


@dataclass
class FileChangeServerConfig:
    host: str
    port: int
    watcher_webservice: WatcherWebservice | None


@dataclass
class FileChangesState:
    pending_js: set[Path] = field(default_factory=set)
    pending_python: set[Path] = field(default_factory=set)


async def handle_file_changes_base(
    *,
    package: str,
    metadata: CallbackMetadata,
    app_manager: DevAppManager,
    file_changes_state: FileChangesState,
    server_config: FileChangeServerConfig | None = None,
) -> None:
    """
    Shared file change handler that can be used by both watch and runserver modes.

    :param metadata: The metadata about which files changed
    :param app_manager: The app manager instance
    :param js_compiler: Optional js compiler for watch mode
    :param launch_server: Whether to launch/restart the server (runserver mode)
    :param watcher_webservice: Optional watcher webservice for runserver mode
    :param host: Optional host for runserver mode
    :param port: Optional port for runserver mode
    """
    LOGGER.info(f"Handling file changes: {metadata}")
    start = time()
    success = True

    # First collect all the files that need updating
    for event in metadata.events:
        if event.path.suffix in KNOWN_JS_EXTENSIONS:
            file_changes_state.pending_js.add(event.path)
        elif event.path.suffix == ".py":
            file_changes_state.pending_python.add(event.path)

    if not (file_changes_state.pending_js or file_changes_state.pending_python):
        return

    # Capture all the logs while our progress bar is the main object
    # This avoids application-level logging interrupting the progress bar
    try:
        async with app_manager.capture_logs() as (stdout_capture, stderr_capture):
            # Use Progress for the countable operations
            with Progress(
                SpinnerColumn(),
                *Progress.get_default_columns(),
                TimeElapsedColumn(),
                console=CONSOLE,
                transient=True,
            ) as progress:
                total_steps = len(file_changes_state.pending_python) + (
                    1 if file_changes_state.pending_js else 0
                )
                build_task = progress.add_task("[cyan]Building...", total=total_steps)

                # Handle Python changes
                if file_changes_state.pending_python:
                    progress.update(
                        build_task, description="[cyan]Reloading Python modules..."
                    )
                    module_names = {
                        package_path_to_module(package, module_path): module_path
                        for module_path in file_changes_state.pending_python
                    }
                    response = await app_manager.reload_backend_diff(
                        list(module_names.keys())
                    )

                    if isinstance(response, ErrorResponse):
                        if (
                            isinstance(response, ReloadResponseError)
                            and response.needs_restart
                        ):
                            progress.update(
                                build_task, description="[cyan]Restarting server..."
                            )
                            # Full server restart needed - start fresh process
                            if server_config:
                                restart_response = (
                                    await app_manager.reload_backend_all()
                                )
                                if isinstance(restart_response, ErrorResponse):
                                    success = False
                        else:
                            success = False

                    # Mark successful reloads as handled. Note that the response includes all of the
                    # modules that were reloaded among the DAG of dependencies, so we need to filter
                    # down to the ones that were requested on disk.
                    if isinstance(
                        response, (ReloadResponseSuccess, ReloadResponseError)
                    ):
                        reloaded_paths = {
                            module_names[module_name]
                            for module_name in response.reloaded
                            if module_name in module_names
                        }
                        file_changes_state.pending_python -= reloaded_paths

                    progress.update(
                        build_task, advance=len(file_changes_state.pending_python)
                    )

                # Handle JS changes
                if file_changes_state.pending_js:
                    progress.update(
                        build_task, description="[cyan]Rebuilding frontend..."
                    )
                    if server_config:
                        await app_manager.reload_frontend(
                            list(file_changes_state.pending_js)
                        )
                    progress.update(build_task, advance=1)

                    file_changes_state.pending_js.clear()

            # Wait before we get the logs so we can still capture the logs
            if server_config and success:
                start_time = time()
                while time() - start_time < 5:
                    if app_manager.is_port_open(server_config.host, server_config.port):
                        break
                    await asyncio.sleep(0.1)

        # Print captured logs if available
        captured_logs = stdout_capture.getvalue()
        captured_errors = stderr_capture.getvalue()

        if captured_logs.strip():
            CONSOLE.print("\n[bold blue]App Build Logs:[/bold blue]")
            CONSOLE.print(captured_logs)
        if captured_errors.strip():
            CONSOLE.print("\n[bold red]App Build Errors:[/bold red]")
            CONSOLE.print(captured_errors)

        if server_config and server_config.watcher_webservice:
            server_config.watcher_webservice.notification_queue.put(True)

        if server_config:
            build_time = time() - start
            if success:
                CONSOLE.print(
                    f"[bold green]🚀 App relaunched in {build_time:.2f} seconds"
                )
            else:
                CONSOLE.print(
                    "[bold red]🚨 App failed to launch, waiting for code change..."
                )
    except Exception as e:
        CONSOLE.print(f"[red]File reload error: {e}\n{traceback.format_exc()}")


@async_to_sync
async def handle_watch(
    *,
    package: str,
    webcontroller: str,
    subscribe_to_mountaineer: bool = False,
):
    """
    Watch the file directory and rebuild auto-generated files. This only
    creates the frontend files necessary to get server-side typehints. It
    doesn't build the package for production use.

    :param package: Ex. "ci_webapp"
    :param webcontroller: Ex. "ci_webapp.app:controller"
    :param subscribe_to_mountaineer:
        If True, will subscribe the local build server to changes in
        the `mountaineer` package. This is useful when doing concurrent
        development in `mountaineer` and a client package. Rarely
        used otherwise.

    """
    update_multiprocessing_settings()
    rich_traceback_install()

    app_manager = DevAppManager.from_webcontroller(webcontroller)
    file_changes_state = FileChangesState()

    async def update_build(metadata: CallbackMetadata):
        await handle_file_changes_base(
            package=package,
            metadata=metadata,
            app_manager=app_manager,
            file_changes_state=file_changes_state,
            server_config=None,
        )

    async with app_manager.start_broker():
        watchdog = build_common_watchdog(
            package,
            update_build,
            subscribe_to_mountaineer=subscribe_to_mountaineer,
        )
        await watchdog.start_watching()


def run_isolated(address: tuple[str, int], authkey: bytes):
    print("DID BOOT CHILD")
    # Connect to the manager server as a client
    class QueueManager(BaseManager): pass
    QueueManager.register('get_queue')

    manager = QueueManager(address=address, authkey=authkey)
    manager.connect()
    queue = manager.get_queue()
    
    print(f"Child process connected to queue manager at {address}", flush=True)
    
    while True:
        metadata = queue.get()
        with open("test.txt", "a") as f:
            f.write(f"SUBPROCESS {metadata}\n")

@async_to_sync
async def handle_runserver(
    *,
    package: str,
    webservice: str,
    webcontroller: str,
    host: str = "127.0.0.1",
    port: int,
    hotreload_host: str | None = None,
    hotreload_port: int | None = None,
    subscribe_to_mountaineer: bool = False,
):
    """
    Start a local development server. This will hot-reload your browser any time
    your frontend or backend code changes.

    :param package: Ex. "ci_webapp"
    :param webservice: Ex. "ci_webapp.app:app"
    :param webcontroller: Ex. "ci_webapp.app:controller"
    :param port: Desired port for the webapp while running locally
    :param subscribe_to_mountaineer: See `handle_watch` for more details.

    """
    update_multiprocessing_settings()
    rich_traceback_install()

    watcher_webservice = WatcherWebservice(
        webservice_host=hotreload_host or host, webservice_port=hotreload_port
    )
    file_changes_state = FileChangesState()

    # Nonlocal vars for shutdown context
    watchdog: PackageWatchdog
    loop = asyncio.get_event_loop()
    shutdown_count = 0

    await watcher_webservice.start()

    # Use a random port for the manager and a secure random auth key
    manager_port = port + 1000  # Use a different port than the webserver
    manager_host = host
    manager_address = (manager_host, manager_port)
    auth_key = secrets.token_bytes(32)  # Secure random authentication key
    
    # Set up the manager server with a shared queue
    queue = Queue()
    class QueueManager(BaseManager): pass
    QueueManager.register('get_queue', callable=lambda: queue)
    
    # Create and start the manager server in a separate thread
    manager_server = QueueManager(address=manager_address, authkey=auth_key)
    server = manager_server.get_server()
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    CONSOLE.print(f"[bold blue]Process manager started at {manager_host}:{manager_port}")

    i = 0

    with isolate_imports(package) as environment:
        async def handle_file_changes(metadata: CallbackMetadata):
            nonlocal i
            print("DID CHANGE", metadata)

            # We might have updated imports, so pass to the env to optionally update
            environment.update_environment()

            print("UPDATE DONE!")

            # Launch the subprocess with the manager connection details
            runner = environment.exec(
                run_isolated,
                manager_address,
                auth_key,
            )

            print("LAUNCHED!")

            # Send a message to the subprocess through the queue
            queue.put(f"test message from main {i}")
            print("SENT MESSAGE")
            i += 1

            #from time import sleep
            #sleep(1)

            #print("COMMUNICATING")
            # TODO: Allow timeout parameter
            #environment.communicate_isolated(runner)
            #print("DONE COMMUNICATING")

        CONSOLE.print(f"[bold green]🚀 Dev webserver ready at http://{host}:{port}")

        watchdog = build_common_watchdog(
            package,
            handle_file_changes,
            subscribe_to_mountaineer=subscribe_to_mountaineer,
        )
        await watchdog.start_watching()

        print("SHUTDOWN")

    CONSOLE.print("[green]Shutdown complete")

@async_to_sync
async def handle_build(
    *,
    webcontroller: str,
    minify: bool = True,
):
    """
    Creates a production bundle of frontend files that is ready for service.

    Building your app will compile your TypeScript into the client-side bundle that will be downloaded
    by the browser. It also ahead-of-time generates the server code that will be run as part of [SSR](./ssr.md).
    You'll want to do it before deploying your application into production - but since a full build can take up
    to 10s, `handle_runserver` provides a better workflow for daily development.

    :param webcontroller: Ex. "ci_webapp.app:controller"
    :param minify: Minify the JS bundle, strip debug symbols

    """
    start = time()

    # Parse the webcontroller string
    package = webcontroller.split(".")[0]
    module_name = webcontroller.split(":")[0]
    controller_name = webcontroller.split(":")[1]

    # Create message broker for isolated context
    message_broker = AsyncMessageBroker[IsolatedMessageBase[Any]]()
    message_broker.start()

    # Initialize the isolated context directly
    isolated_context = IsolatedAppContext(
        package=package,
        package_path=Path(package.replace(".", "/")),
        module_name=module_name,
        controller_name=controller_name,
        host=None,
        port=0,
        live_reload_port=None,
        message_broker=message_broker,
    )

    try:
        # Initialize app state
        response = isolated_context.initialize_app_state()
        if not isinstance(response, SuccessResponse):
            raise ValueError("Failed to initialize app state")

        # Build the latest client support files
        if isolated_context.js_compiler is None:
            raise ValueError("JS compiler not initialized")
        if isolated_context.app_compiler is None:
            raise ValueError("App compiler not initialized")
        if isolated_context.app_controller is None:
            raise ValueError("App controller not initialized")

        await isolated_context.js_compiler.build_use_server()
        await isolated_context.app_compiler.run_builder_plugins()

        # Get view paths for all controllers
        all_view_paths: list[list[str]] = []
        for controller_definition in isolated_context.app_controller.controllers:
            (
                _,
                direct_hierarchy,
            ) = isolated_context.app_controller._view_hierarchy_for_controller(
                controller_definition.controller
            )
            direct_hierarchy.reverse()
            all_view_paths.append([str(layout.path) for layout in direct_hierarchy])

        # Compile the final client bundle
        client_bundle_result = mountaineer_rs.compile_production_bundle(
            all_view_paths,
            str(isolated_context.app_controller._view_root / "node_modules"),
            "production",
            minify,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            False,
        )

        static_output = (
            isolated_context.app_controller._view_root.get_managed_static_dir()
        )
        ssr_output = isolated_context.app_controller._view_root.get_managed_ssr_dir()

        # If we don't have the same number of entrypoints as controllers, something went wrong
        if len(client_bundle_result["entrypoints"]) != len(
            isolated_context.app_controller.controllers
        ):
            raise ValueError(
                f"Mismatch between number of controllers and number of entrypoints in the client bundle\n"
                f"Controllers: {len(isolated_context.app_controller.controllers)}\n"
                f"Entrypoints: {len(client_bundle_result['entrypoints'])}"
            )

        # Try to parse the format (entrypoint{}.js or entrypoint{}.js.map)
        for controller_definition, content, map_content in zip(
            isolated_context.app_controller.controllers,
            client_bundle_result["entrypoints"],
            client_bundle_result["entrypoint_maps"],
        ):
            script_root = underscore(
                controller_definition.controller.__class__.__name__
            )
            content_hash = md5(content.encode()).hexdigest()
            (static_output / f"{script_root}-{content_hash}.js").write_text(content)
            (static_output / f"{script_root}-{content_hash}.map.js").write_text(
                map_content
            )

        # Copy the other files 1:1 because they'll be referenced by name in the
        # entrypoints
        for path, content in client_bundle_result["supporting"].items():
            (static_output / path).write_text(content)

        # Now we go one-by-one to provide the SSR files, which will be consolidated
        # into a single runnable script for ease of use by the V8 engine
        result_scripts, _ = mountaineer_rs.compile_independent_bundles(
            all_view_paths,
            str(isolated_context.app_controller._view_root / "node_modules"),
            "production",
            0,
            str(get_static_path("live_reload.ts").resolve().absolute()),
            True,
        )

        for controller, script in zip(
            isolated_context.app_controller.controllers, result_scripts
        ):
            script_root = underscore(controller.controller.__class__.__name__)
            content_hash = md5(script.encode()).hexdigest()
            (ssr_output / f"{script_root}.js").write_text(script)

        CONSOLE.print(f"[bold green]App built in {time() - start:.2f}s")

    finally:
        # Clean up the message broker
        await message_broker.stop()


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


def build_common_watchdog(
    client_package: str,
    callback: Callable[[CallbackMetadata], Coroutine[Any, Any, None]],
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
