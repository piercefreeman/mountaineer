import asyncio
from hashlib import md5
from multiprocessing import get_start_method, set_start_method
from pathlib import Path
from signal import SIGINT, signal
from tempfile import mkdtemp
from time import time
from typing import Callable

from inflection import underscore
from rich.traceback import install as rich_traceback_install

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.app_manager import (
    DevAppManager,
    find_packages_with_prefix,
    package_path_to_module,
)
from mountaineer.client_builder.builder import APIBuilder
from mountaineer.console import CONSOLE
from mountaineer.constants import KNOWN_JS_EXTENSIONS
from mountaineer.hotreload import HotReloader
from mountaineer.logging import LOGGER
from mountaineer.static import get_static_path
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

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    app_manager = DevAppManager.from_webcontroller(webcontroller)
    js_compiler = APIBuilder(
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
            asyncio.run(js_compiler.build_all())

        # For now, we don't do any js analysis besides building - which
        # we don't need to do if we're just watching for changes

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

    # Initialize components
    watcher_webservice = WatcherWebservice(
        webservice_host=hotreload_host or host, webservice_port=hotreload_port
    )
    watcher_webservice.start()

    app_manager = DevAppManager.from_webcontroller(
        webcontroller, host=host, port=port, live_reload_port=watcher_webservice.port
    )

    # Initialize hot reloader with root package
    hot_reloader = HotReloader(
        root_package=package,
        package_path=Path(package.replace(".", "/")),
        entrypoint=webcontroller.rsplit(":")[0],
    )

    # Initial build
    asyncio.run(app_manager.js_compiler.build_all())
    asyncio.run(app_manager.app_compiler.run_builder_plugins())

    app_manager.restart_server()

    async def handle_file_changes(metadata: CallbackMetadata):
        LOGGER.info(f"Handling file changes: {metadata}")
        start = time()
        updated_js = set()
        updated_python = set()

        for event in metadata.events:
            if event.path.suffix in KNOWN_JS_EXTENSIONS:
                updated_js.add(event.path)
            elif event.path.suffix == ".py":
                updated_python.add(event.path)

        if not (updated_js or updated_python):
            return

        # Handle Python changes
        if updated_python:
            module_names = [
                package_path_to_module(package, module_path)
                for module_path in updated_python
            ]
            success, reloaded = hot_reloader.reload_modules(module_names)

            if reloaded:
                app_manager.update_module()
                await app_manager.js_compiler.build_use_server()
                app_manager.restart_server()

            if not success:
                CONSOLE.print(f"[bold red]Failed to reload {updated_python}")

        # Handle JS changes
        if updated_js:
            await app_manager.app_compiler.run_builder_plugins(
                limit_paths=list(updated_js)
            )
            for path in updated_js:
                app_manager.app_controller.invalidate_view(path)

        # Wait for server to be ready
        start_time = time()
        while time() - start_time < 5:
            if app_manager.is_port_open(host, port):
                break
            await asyncio.sleep(0.1)

        watcher_webservice.notification_queue.put(True)
        CONSOLE.print(f"[bold green]🚀 App relaunched in {time() - start:.2f} seconds")

    def handle_shutdown(signum, frame):
        watcher_webservice.stop()
        CONSOLE.print("[yellow]Services shutdown, now exiting...")
        exit(0)

    signal(SIGINT, handle_shutdown)

    watchdog = build_common_watchdog(
        package,
        lambda metadata: asyncio.run(handle_file_changes(metadata)),
        subscribe_to_mountaineer=subscribe_to_mountaineer,
    )
    watchdog.start_watching()


def handle_build(
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
    app_manager = DevAppManager.from_webcontroller(webcontroller)
    app_manager.js_compiler.live_reload_port = None

    start = time()

    # Build the latest client support files (useServer)
    asyncio.run(app_manager.js_compiler.build_all())
    asyncio.run(app_manager.app_compiler.run_builder_plugins())

    # Compile the final bundle
    # This requires us to get each entrypoint, which should just be the controllers
    # that are registered to the app
    # We also need to inspect the hierarchy
    all_view_paths: list[list[str]] = []

    for controller_definition in app_manager.app_controller.controllers:
        _, direct_hierarchy = app_manager.app_controller._view_hierarchy_for_controller(
            controller_definition.controller
        )
        direct_hierarchy.reverse()
        all_view_paths.append([str(layout.path) for layout in direct_hierarchy])

    # Compile the final client bundle
    client_bundle_result = mountaineer_rs.compile_production_bundle(
        all_view_paths,
        str(app_manager.app_controller._view_root / "node_modules"),
        "production",
        minify,
        str(get_static_path("live_reload.ts").resolve().absolute()),
        False,
    )

    static_output = app_manager.app_controller._view_root.get_managed_static_dir()
    ssr_output = app_manager.app_controller._view_root.get_managed_ssr_dir()

    # If we don't have the same number of entrypoints as controllers, something went wrong
    if len(client_bundle_result["entrypoints"]) != len(
        app_manager.app_controller.controllers
    ):
        raise ValueError(
            f"Mismatch between number of controllers and number of entrypoints in the client bundle\n"
            f"Controllers: {len(app_manager.app_controller.controllers)}\n"
            f"Entrypoints: {len(client_bundle_result['entrypoints'])}"
        )

    # Try to parse the format (entrypoint{}.js or entrypoint{}.js.map)
    for controller_definition, content, map_content in zip(
        app_manager.app_controller.controllers,
        client_bundle_result["entrypoints"],
        client_bundle_result["entrypoint_maps"],
    ):
        # TODO: Consolidate naming conventions for scripts into our `ManagedPath` class
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
        str(app_manager.app_controller._view_root / "node_modules"),
        "production",
        0,
        str(get_static_path("live_reload.ts").resolve().absolute()),
        True,
    )

    for controller, script in zip(
        app_manager.app_controller.controllers, result_scripts
    ):
        script_root = underscore(controller.controller.__class__.__name__)
        content_hash = md5(script.encode()).hexdigest()
        (ssr_output / f"{script_root}.js").write_text(script)

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
