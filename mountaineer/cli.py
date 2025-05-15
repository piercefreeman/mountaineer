import traceback
from contextlib import contextmanager
from hashlib import md5
from multiprocessing import get_start_method, set_start_method
from os import getenv
from time import time
from typing import Any, Callable, Coroutine

from firehot import isolate_imports
from inflection import underscore
from rich.traceback import install as rich_traceback_install

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.console import CONSOLE
from mountaineer.constants import KNOWN_JS_EXTENSIONS
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.development.manager import (
    FileChangesState,
    IsolatedContext,
    WebserverConfig,
    rebuild_frontend,
    restart_backend,
)
from mountaineer.development.messages import (
    SuccessResponse,
)
from mountaineer.development.messages_broker import (
    AsyncMessageBroker,
    BrokerExecutionError,
)
from mountaineer.development.packages import (
    find_packages_with_prefix,
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
from mountaineer.ssr import find_tsconfig
from mountaineer.static import get_static_path


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

    file_changes_state = FileChangesState()
    first_run: bool = True

    async with AsyncMessageBroker.start_server() as (broker, config):
        isolated_context = IsolatedContext(
            webcontroller=webcontroller,
            webserver_config=None,
            message_config=config,
        )

        with get_mountaineer_isolated_env(package) as environment:
            CONSOLE.print("[bold blue]Development manager started")

            async def handle_file_changes(metadata: CallbackMetadata):
                try:
                    LOGGER.debug(f"Handling file changes: {metadata}")
                    nonlocal first_run
                    nonlocal file_changes_state

                    # First collect all the files that need updating
                    for event in metadata.events:
                        if event.path.suffix in KNOWN_JS_EXTENSIONS:
                            file_changes_state.pending_js.add(event.path)
                        elif event.path.suffix == ".py":
                            file_changes_state.pending_python.add(event.path)

                    if not first_run and not (
                        file_changes_state.pending_js
                        or file_changes_state.pending_python
                    ):
                        return

                    try:
                        if file_changes_state.pending_python or first_run:
                            await restart_backend(
                                environment,
                                broker,
                                file_changes_state,
                                isolated_context,
                            )

                        if file_changes_state.pending_js or first_run:
                            await rebuild_frontend(
                                broker,
                                file_changes_state,
                            )
                    except BrokerExecutionError as e:
                        CONSOLE.print(f"[red]Error: {e.error}\n\n{e.traceback}")
                        return

                    # If we've succeeded, we should clear out the pending
                    # files so we don't rebuild them again
                    file_changes_state.pending_js.clear()
                    file_changes_state.pending_python.clear()

                    first_run = False

                except Exception as e:
                    # Otherwise silently caught by our watchfiles command
                    CONSOLE.print(f"[red]Error: {e}")
                    CONSOLE.print(traceback.format_exc())
                    raise e

            watchdog = build_common_watchdog(
                package,
                handle_file_changes,
                subscribe_to_mountaineer=subscribe_to_mountaineer,
            )
            await watchdog.start_watching()

    CONSOLE.print("[green]Shutdown complete")


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
    await watcher_webservice.start()

    file_changes_state = FileChangesState()

    # Nonlocal vars for shutdown context
    watchdog: PackageWatchdog
    first_run: bool = True

    async with AsyncMessageBroker.start_server() as (broker, config):
        isolated_context = IsolatedContext(
            webcontroller=webcontroller,
            webserver_config=WebserverConfig(
                host=host,
                port=port,
                live_reload_port=watcher_webservice.port,
            ),
            message_config=config,
        )

        with get_mountaineer_isolated_env(package) as environment:
            CONSOLE.print("[bold blue]Development manager started")

            async def handle_file_changes(metadata: CallbackMetadata):
                try:
                    LOGGER.debug(f"Handling file changes: {metadata}")
                    nonlocal first_run
                    nonlocal file_changes_state

                    # First collect all the files that need updating
                    for event in metadata.events:
                        if event.path.suffix in KNOWN_JS_EXTENSIONS:
                            file_changes_state.pending_js.add(event.path)
                        elif event.path.suffix == ".py":
                            file_changes_state.pending_python.add(event.path)

                    if not first_run and not (
                        file_changes_state.pending_js
                        or file_changes_state.pending_python
                    ):
                        return

                    try:
                        if file_changes_state.pending_python or first_run:
                            await restart_backend(
                                environment,
                                broker,
                                file_changes_state,
                                isolated_context,
                            )

                        if file_changes_state.pending_js or first_run:
                            await rebuild_frontend(
                                broker,
                                file_changes_state,
                            )
                    except BrokerExecutionError as e:
                        CONSOLE.print(f"[red]Error: {e.error}\n\n{e.traceback}")
                        return

                    # If we've succeeded, we should clear out the pending
                    # files so we don't rebuild them again
                    file_changes_state.pending_js.clear()
                    file_changes_state.pending_python.clear()

                    # Ping the watcher webservice to let it know we've updated
                    await watcher_webservice.broadcast_listeners()

                    first_run = False

                except Exception as e:
                    # Otherwise silently caught by our watchfiles command
                    CONSOLE.print(f"[red]Error: {e}")
                    CONSOLE.print(traceback.format_exc())
                    raise e

            watchdog = build_common_watchdog(
                package,
                handle_file_changes,
                subscribe_to_mountaineer=subscribe_to_mountaineer,
            )
            await watchdog.start_watching()

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

    # Initialize the isolated context directly
    isolated_context = IsolatedAppContext.from_webcontroller(
        webcontroller=webcontroller,
        use_dev_exceptions=False,
    )

    # Initialize app state
    response = await isolated_context.initialize_app_state()
    if not isinstance(response, SuccessResponse):
        raise ValueError("Failed to initialize app state")

    # Type validation
    assert isolated_context.js_compiler is not None
    assert isolated_context.app_compiler is not None
    assert isolated_context.app_controller is not None

    # Build the frontend support bundle
    await isolated_context.js_compiler.build_use_server()
    await isolated_context.app_compiler.run_builder_plugins()

    # Get the build-enabled controllers
    build_controllers = [
        controller_definition
        for controller_definition in isolated_context.app_controller.controllers
        if controller_definition.controller._build_enabled
    ]

    # Get view paths for all controllers
    all_view_paths: list[list[str]] = []
    for controller_definition in build_controllers:
        (
            _,
            direct_hierarchy,
        ) = isolated_context.app_controller._view_hierarchy_for_controller(
            controller_definition.controller
        )
        direct_hierarchy.reverse()
        all_view_paths.append([str(layout.path) for layout in direct_hierarchy])

    # Find tsconfig.json in the parent directories of the view paths
    tsconfig_path = find_tsconfig(all_view_paths)

    # Compile the final client bundle
    client_bundle_result = mountaineer_rs.compile_production_bundle(
        all_view_paths,
        str(isolated_context.app_controller._view_root / "node_modules"),
        "production",
        minify,
        str(get_static_path("live_reload.ts").resolve().absolute()),
        False,
        tsconfig_path,
    )

    static_output = isolated_context.app_controller._view_root.get_managed_static_dir()
    ssr_output = isolated_context.app_controller._view_root.get_managed_ssr_dir()

    # If we don't have the same number of entrypoints as controllers, something went wrong
    if len(client_bundle_result["entrypoints"]) != len(build_controllers):
        raise ValueError(
            f"Mismatch between number of controllers and number of entrypoints in the client bundle\n"
            f"Controllers: {len(build_controllers)}\n"
            f"Entrypoints: {len(client_bundle_result['entrypoints'])}"
        )

    # Try to parse the format (entrypoint{}.js or entrypoint{}.js.map)
    for controller_definition, content, map_content in zip(
        build_controllers,
        client_bundle_result["entrypoints"],
        client_bundle_result["entrypoint_maps"],
    ):
        script_root = underscore(controller_definition.controller.__class__.__name__)
        content_hash = md5(content.encode()).hexdigest()
        (static_output / f"{script_root}-{content_hash}.js").write_text(content)
        (static_output / f"{script_root}-{content_hash}.map.js").write_text(map_content)

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
        tsconfig_path,
    )

    # Write each script to disk
    for controller_definition, script in zip(build_controllers, result_scripts):
        script_root = underscore(controller_definition.controller.__class__.__name__)
        (ssr_output / f"{script_root}.js").write_text(script)

    LOGGER.info(f"Build completed in {(time() - start):.2f}s")


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


@contextmanager
def get_mountaineer_isolated_env(package: str):
    """
    Allow users to deny certain imports from being loaded into the core environment, in case
    these launch threads during initialization.

    :param package: The package to isolate imports from.

    """
    ignored_modules_raw = getenv("MOUNTAINEER_IGNORE_HOTRELOAD", "")
    ignored_modules = (
        [mod.strip() for mod in ignored_modules_raw.split(",")]
        if ignored_modules_raw
        else None
    )

    with isolate_imports(package, ignored_modules=ignored_modules) as environment:
        yield environment
