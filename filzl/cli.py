from importlib import import_module
from typing import Callable

from filzl.client_interface.builder import ClientBuilder
from filzl.watch import CallbackDefinition, CallbackType, PackageWatchdog
from filzl.webservice import UvicornThread


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

    def update_build():
        # Import just within the scope of the build, so we can pick up changes that
        # are made over time
        client_builder = ClientBuilder(import_from_string(webcontroller))
        client_builder.build()

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
    current_uvicorn_thread: UvicornThread | None = None

    def restart_uvicorn():
        nonlocal current_uvicorn_thread
        if current_uvicorn_thread:
            current_uvicorn_thread.stop()
            current_uvicorn_thread.join()

        current_uvicorn_thread = UvicornThread(
            webservice,
            port=port,
        )
        current_uvicorn_thread.start()

    def update_build():
        client_builder = ClientBuilder(import_from_string(webcontroller))
        client_builder.build()
        restart_uvicorn()

    # Initial launch
    restart_uvicorn()

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
