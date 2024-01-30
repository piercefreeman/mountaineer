import importlib.metadata
import os
from dataclasses import dataclass
from enum import Flag, auto
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class CallbackType(Flag):
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()


@dataclass
class CallbackDefinition:
    action: CallbackType
    callback: Callable


class ChangeEventHandler(FileSystemEventHandler):
    def __init__(self, callbacks: list[CallbackDefinition]):
        super().__init__()
        self.callbacks = callbacks
        self.ignore_changes = False

    def on_modified(self, event):
        super().on_modified(event)
        if self.ignore_changes:
            return
        if not event.is_directory:
            print(f"File modified: {event.src_path}")
            self.handle_callbacks(CallbackType.MODIFIED)

    def on_created(self, event):
        super().on_created(event)
        if self.ignore_changes:
            return
        if not event.is_directory:
            print(f"File created: {event.src_path}")
            self.handle_callbacks(CallbackType.CREATED)

    def on_deleted(self, event):
        super().on_deleted(event)
        if self.ignore_changes:
            return
        if not event.is_directory:
            print(f"File deleted: {event.src_path}")
            self.handle_callbacks(CallbackType.DELETED)

    def handle_callbacks(self, action: CallbackType):
        """
        Runs all callbacks for the given action. Since callbacks are allowed to make
        modifications to the filesystem, we temporarily disable the event handler to avoid
        infinite loops.

        """
        self.ignore_changes = True
        for callback in self.callbacks:
            if action in callback.action:
                callback.callback()
        self.ignore_changes = False


class PackageWatchdog:
    def __init__(
        self,
        package_names: list[str],
        callbacks: list[CallbackDefinition] | None = None,
    ):
        self.packages = package_names
        self.paths: list[str] = []
        self.callbacks: list[CallbackDefinition] = callbacks or []

        self.check_packages_installed()
        self.get_package_paths()

    def check_packages_installed(self):
        for package in self.packages:
            try:
                importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                raise ValueError(
                    f"Package '{package}' is not installed in the current environment"
                )

    def get_package_paths(self):
        for package in self.packages:
            dist = importlib.metadata.distribution(package)
            package_path = self.resolve_package_path(dist)
            self.paths.append(str(package_path))

    def resolve_package_path(self, dist: importlib.metadata.Distribution):
        """
        Given a package distribution, returns the local file directory that should be watched
        """
        # Recent versions of poetry install development packages (-e .) as direct URLs
        # https://the-hitchhikers-guide-to-packaging.readthedocs.io/en/latest/introduction.html
        # "Path configuration files have an extension of .pth, and each line must
        # contain a single path that will be appended to sys.path."
        package_name = dist.name.replace("-", "_")
        symbolic_links = [
            path for path in (dist.files or []) if path.name == f"{package_name}.pth"
        ]
        explicit_links = [
            path
            for path in (dist.files or [])
            if path.parent.name == package_name and path.name == "__init__.py"
        ]

        if symbolic_links:
            direct_url_path = symbolic_links[0]
            return dist.locate_file(direct_url_path.read_text())

        if explicit_links:
            # Since we found the __init__.py file for the root, we should be able to go up
            # to the main path
            explicit_link = explicit_links[0]
            return dist.locate_file(explicit_link.parent)

        raise ValueError(
            f"Could not find a valid path for package {dist.name}, found files: {dist.files}"
        )

    def start_watching(self):
        event_handler = ChangeEventHandler(callbacks=self.callbacks)
        observer = Observer()

        for path in self.paths:
            print(f"Watching {path}")
            if os.path.isdir(path):
                observer.schedule(event_handler, path, recursive=True)
            else:
                observer.schedule(event_handler, os.path.dirname(path), recursive=False)

        observer.start()
        try:
            while True:
                pass  # Keep the script running
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
