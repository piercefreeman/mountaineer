from sys import argv
from time import time

from mountaineer import mountaineer as mountaineer_rs  # type: ignore
from mountaineer.development.isolation import IsolatedAppContext
from mountaineer.frontend import vite_style_paths, write_build_metadata
from mountaineer.io import async_to_sync
from mountaineer.logging import LOGGER


def run_dev() -> None:
    try:
        mountaineer_rs.run_dev(argv[1:])
    except KeyboardInterrupt:
        pass


def run_prod() -> None:
    try:
        mountaineer_rs.run_prod(argv[1:])
    except KeyboardInterrupt:
        pass


def run_watch() -> None:
    try:
        mountaineer_rs.run_watch(argv[1:])
    except KeyboardInterrupt:
        pass


def handle_watch(
    *,
    package: str,
    webcontroller: str,
    subscribe_to_mountaineer: bool = False,
):
    """
    Start the native client-type watcher with legacy project arguments.

    :param package: The Python package containing the application
    :param webcontroller: The app controller import path
    :param subscribe_to_mountaineer: Retained for compatibility with existing
        project scripts
    """
    mountaineer_rs.run_watch(
        [
            "--package",
            package,
            "--webcontroller",
            webcontroller,
        ]
    )


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
    Start the native development server with legacy project arguments.

    :param package: The Python package containing the application
    :param webservice: Retained for compatibility with existing project scripts
    :param webcontroller: The app controller import path
    :param host: The public host to bind
    :param port: Desired port for the webapp while running locally
    :param hotreload_host: Retained for compatibility with existing project scripts
    :param hotreload_port: Retained for compatibility with existing project scripts
    :param subscribe_to_mountaineer: Retained for compatibility with existing project scripts
    """
    try:
        mountaineer_rs.run_dev(
            [
                "--package",
                package,
                "--webcontroller",
                webcontroller,
                "--host",
                host,
                "--port",
                str(port),
            ]
        )
    except KeyboardInterrupt:
        pass


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
    await isolated_context.initialize_app_state()

    # Type validation
    assert isolated_context.js_compiler is not None
    assert isolated_context.app_controller is not None

    # Clear stale artifacts and build the generated TypeScript API.
    await isolated_context.js_compiler.build_all()

    # Get the build-enabled controllers
    build_controllers = [
        controller_definition
        for controller_definition in isolated_context.app_controller.graph.controllers
        if controller_definition.build_enabled
    ]

    entrypoints = [
        (controller_definition.controller.script_name, view_paths)
        for controller_definition in build_controllers
        for view_paths in controller_definition.get_hierarchy_view_paths()
    ]

    if not entrypoints:
        LOGGER.warning("No controllers found to build. Skipping bundling steps.")
        LOGGER.info(f"Build completed in {(time() - start):.2f}s")
        return

    static_output = isolated_context.app_controller._view_root.get_managed_static_dir()
    ssr_output = isolated_context.app_controller._view_root.get_managed_ssr_dir()
    mountaineer_rs.build_frontend(
        str(isolated_context.app_controller._view_root),
        str(static_output),
        str(ssr_output),
        entrypoints,
        [
            str(path)
            for path in vite_style_paths(isolated_context.app_controller._view_root)
        ],
        minify,
    )
    write_build_metadata(isolated_context.app_controller._view_root)

    LOGGER.info(f"Build completed in {(time() - start):.2f}s")
