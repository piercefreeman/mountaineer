import asyncio
import importlib
import sys
from hashlib import md5
from multiprocessing import get_start_method, set_start_method
from os import environ
from pathlib import Path
from signal import SIGINT, signal
from tempfile import mkdtemp
from time import sleep, time
from traceback import format_exc
from typing import Callable

from inflection import underscore
from rich.traceback import install as rich_traceback_install

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.app_manager import HotReloadManager, find_packages_with_prefix
from mountaineer.cache import LRUCache
from mountaineer.client_builder.builder import ClientBuilder
from mountaineer.client_compiler.compile import ClientCompiler
from mountaineer.console import CONSOLE
from mountaineer.constants import KNOWN_JS_EXTENSIONS
from mountaineer.logging import LOGGER
from mountaineer.ssr import render_ssr
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

    app_manager = HotReloadManager.from_webcontroller(webcontroller)
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

    # The global cache will let us keep cache files warm across
    # different builds
    global_build_cache = Path(mkdtemp())

    # Start the webservice - it should persist for the lifetime of the
    # runserver, so a single websocket frontend can be notified across
    # multiple builds
    start = time()
    watcher_webservice = WatcherWebservice(webservice_host=host)
    watcher_webservice.start()

    app_manager = HotReloadManager.from_webcontroller(
        webcontroller, host=host, port=port, live_reload_port=watcher_webservice.port
    )
    LOGGER.debug(f"Initial load of {webcontroller} complete.")

    js_compiler = ClientBuilder(
        app_manager.app_controller,
        live_reload_port=watcher_webservice.port,
        build_cache=global_build_cache,
    )
    asyncio.run(js_compiler.build_all())

    app_compiler = ClientCompiler(
        app=app_manager.app_controller,
        view_root=app_manager.app_controller.view_root,
    )
    asyncio.run(app_compiler.run_builder_plugins())

    # Start the initial thread
    app_manager.restart_server()
    CONSOLE.print(f"[bold green]🚀 App launched in {time() - start:.2f} seconds")

    # Now that we've started the server for the first time, any additional reloads
    # must be hot-reloaded
    environ["MOUNTAINEER_HOT_RELOADING"] = "1"

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
        updated_modules: set[tuple[str, Path]] = set()

        for event in metadata.events:
            if (
                event.action != CallbackType.MODIFIED
                and event.action != CallbackType.CREATED
            ):
                # Keep deleted files around for now
                continue

            if event.path.suffix == ".py":
                module_name = app_manager.package_path_to_module(event.path)
                updated_modules.add((module_name, event.path))
            elif event.path.suffix in KNOWN_JS_EXTENSIONS:
                updated_js.add(event.path)

        # Update the modules in a queue fashion so we can update the dependent modules
        # where the subclasses live
        module_queue = list(updated_modules)
        seen_modules: set[str] = set()
        updated_python: set[Path] = set()

        while module_queue:
            module_name, python_path = module_queue.pop(0)
            if module_name in seen_modules:
                continue
            seen_modules.add(module_name)

            # Get the IDs before we reload the module, since they'll change after
            # the re-import
            # If module_name is not already in sys.modules, it hasn't been
            # imported yet and we don't need to worry about refreshing dependent definitions
            if module_name in sys.modules:
                LOGGER.debug(f"Changed Python: {python_path}")
                current_module = sys.modules[module_name]
                owned_by_module = app_manager.objects_in_module(current_module)

                objects_to_reload |= owned_by_module
                obj_subclasses = app_manager.get_modified_subclass_modules(
                    current_module, owned_by_module
                )
                subclass_modules = {module for module, _ in obj_subclasses}

                # Since these are just the direct subclass modules, we add it to the queue
                # to bring in all recursive subclasses
                for additional_module in subclass_modules:
                    module_path = app_manager.module_to_package_path(additional_module)
                    module_queue.append((additional_module, module_path))
            else:
                LOGGER.debug(f"Module {module_name} is new and not yet imported")

            # Now, once we've cached the ids of objects currently in memory we can clear
            # the actual model definition from the module cache
            try:
                updated_module = importlib.import_module(module_name)
                importlib.reload(updated_module)

                # Only follow the downstream dependencies if the module was successfully reloaded
                updated_python.add(python_path)
            except Exception as e:
                stacktrace = format_exc()
                CONSOLE.print(
                    f"[bold red]Error reloading {module_name}, stopping reload..."
                )
                CONSOLE.print(f"[bold red]{e}\n{stacktrace}")

                # In the case of an exception in one module we still want to try to load
                # the other ones that were affected, since we want to keep the differential
                # state of the app up to date
                continue

        # Pass all updated files to the app compiler to build stylesheets
        # and other asset compilations
        asyncio.run(
            app_compiler.run_builder_plugins(
                limit_paths=list(updated_js) + list(updated_python)
            )
        )

        # Logging in the following section assumes we're actually doing some
        # work; if we're not, we should just exit early
        if not updated_js and not updated_python:
            return

        if updated_python:
            LOGGER.debug(f"Changed Python: {updated_python}")
            asyncio.run(js_compiler.build_use_server())

        if updated_js:
            LOGGER.debug(f"Changed JS: {updated_js}")
            # asyncio.run(js_compiler.build_fe_diff(list(updated_js)))

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
            LOGGER.debug(
                f"Found dependent modules: {all_updated_components} ({app_manager.module}: {objects_to_reload})"
            )

            for updated_module in all_updated_components:
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
            # Wait up to 5s for our webserver to start, so when we push our refresh
            # websocket the new page is ready immediately.
            start_time = time()
            max_wait_time = 5
            while time() - start_time < max_wait_time:
                if app_manager.is_port_open(host, port):
                    CONSOLE.print(f"[blue]Webserver is ready on {host}:{port}!")
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
    app_manager = HotReloadManager.from_webcontroller(webcontroller)

    js_compiler = ClientBuilder(
        app_manager.app_controller,
        live_reload_port=None,
    )
    client_compiler = ClientCompiler(
        app_manager.app_controller.view_root,
        app_manager.app_controller,
    )
    start = time()

    # Build the latest client support files (useServer)
    asyncio.run(js_compiler.build_all())
    asyncio.run(client_compiler.run_builder_plugins())

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
        str(app_manager.app_controller.view_root / "node_modules"),
        "production",
        minify,
        str(get_static_path("live_reload.ts").resolve().absolute()),
        False,
    )

    static_output = app_manager.app_controller.view_root.get_managed_static_dir()
    ssr_output = app_manager.app_controller.view_root.get_managed_ssr_dir()

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
    result_scripts = mountaineer_rs.compile_independent_bundles(
        all_view_paths,
        str(app_manager.app_controller.view_root / "node_modules"),
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
