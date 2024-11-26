import importlib.metadata
import os
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Flag, auto
from pathlib import Path
from threading import Timer
from typing import Any, Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from mountaineer.console import CONSOLE
from mountaineer.paths import resolve_package_path


class CallbackType(Flag):
    CREATED = auto()
    MODIFIED = auto()
    DELETED = auto()


@dataclass
class CallbackEvent:
    action: CallbackType
    path: Path


@dataclass
class CallbackMetadata:
    # Since events can be debounced, we need to send all events that occurred
    # in the batch.
    events: list[CallbackEvent]


@dataclass
class CallbackDefinition:
    action: CallbackType
    callback: Callable[[CallbackMetadata], None]


class ChangeEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        callbacks: list[CallbackDefinition],
        ignore_list=["__pycache__", "_ssr", "_static", "_server", "_metadata"],
        ignore_hidden=True,
        debounce_interval=0.1,
    ):
        """
        :param debounce_interval: Seconds to wait for more events. Will only send one event per batched
        interval to avoid saturating clients with one action that results in many files.

        """
        super().__init__()
        self.callbacks = callbacks
        self.ignore_changes = False
        self.ignore_list = ignore_list
        self.ignore_hidden = ignore_hidden
        self.debounce_interval = debounce_interval
        self.debounce_timer: Timer | None = None
        self.pending_events: list[CallbackEvent] = []

    def on_modified(self, event):
        super().on_modified(event)
        if self.should_ignore_path(event.src_path):
            return
        if not event.is_directory:
            CONSOLE.print(f"[yellow]File modified: {event.src_path}")
            self._debounce(CallbackType.MODIFIED, Path(event.src_path))

    def on_created(self, event):
        super().on_created(event)
        if self.should_ignore_path(event.src_path):
            return
        if not event.is_directory:
            CONSOLE.print(f"[yellow]File created: {event.src_path}")
            self._debounce(CallbackType.CREATED, Path(event.src_path))

    def on_deleted(self, event):
        super().on_deleted(event)
        if self.should_ignore_path(event.src_path):
            return
        if not event.is_directory:
            CONSOLE.print(f"[yellow]File deleted: {event.src_path}")
            self._debounce(CallbackType.DELETED, Path(event.src_path))

    def _debounce(self, action: CallbackType, path: Path):
        if self.debounce_timer is not None:
            self.debounce_timer.cancel()

        self.pending_events.append(CallbackEvent(action=action, path=path))

        self.debounce_timer = Timer(
            self.debounce_interval,
            self.handle_callbacks,
        )
        self.debounce_timer.start()

    def handle_callbacks(self):
        """
        Runs all callbacks for the given action. Since callbacks are allowed to make
        modifications to the filesystem, we temporarily disable the event handler to avoid
        infinite loops.

        """
        self.ignore_changes = True

        for callback in self.callbacks:
            valid_events = [
                event
                for event in self.pending_events
                if event.action in callback.action
            ]
            if valid_events:
                callback.callback(CallbackMetadata(events=valid_events))

        self.pending_events = []
        self.ignore_changes = False

    def should_ignore_path(self, path: Path):
        if self.ignore_changes:
            return True

        path_components = set(str(path).split("/"))

        # Check for any nested hidden directories and ignored directories
        if self.ignore_hidden and any(
            (component for component in path_components if component.startswith("."))
        ):
            return True
        elif path_components & set(self.ignore_list) != set():
            return True
        return False


class WatchdogLockError(Exception):
    def __init__(self, lock_path: Path):
        super().__init__(
            f"Watch lock file exists, another process may be running. If you're sure this is not the case, run:\n"
            f"`$ rm {lock_path}`",
        )
        self.lock_path = lock_path


class PackageWatchdog:
    def __init__(
        self,
        main_package: str,
        dependent_packages: list[str],
        callbacks: list[CallbackDefinition] | None = None,
        run_on_bootup: bool = False,
    ):
        """
        :param run_on_bootup: Typically, we will only notify callback if there has been
            a change to the filesystem. If this is set to True, we will run all callbacks
            on bootup as well.
        """
        self.main_package = main_package
        self.packages = [main_package] + dependent_packages
        self.paths: list[str] = []
        self.callbacks: list[CallbackDefinition] = callbacks or []
        self.run_on_bootup = run_on_bootup

        self.event_handler: ChangeEventHandler | None = None
        self.observer: Any | None = None

        self.check_packages_installed()
        self.get_package_paths()

    def start_watching(self):
        with self.acquire_watchdog_lock():
            if self.run_on_bootup:
                for callback_definition in self.callbacks:
                    callback_definition.callback(CallbackMetadata(events=[]))

            self.event_handler = ChangeEventHandler(callbacks=self.callbacks)
            self.observer = Observer()

            for path in self.paths:
                CONSOLE.print(f"[green]Watching {path}")
                if os.path.isdir(path):
                    self.observer.schedule(self.event_handler, path, recursive=True)
                else:
                    self.observer.schedule(
                        self.event_handler, os.path.dirname(path), recursive=False
                    )

            self.observer.start()

            try:
                self.observer.join()
            except KeyboardInterrupt:
                self.observer.stop()
                self.observer.join()

    def check_packages_installed(self):
        for package in self.packages:
            try:
                importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                raise ValueError(
                    f"Package '{package}' is not installed in the current environment"
                )

    def get_package_paths(self):
        paths: list[str] = []
        for package in self.packages:
            package_path = resolve_package_path(package)
            paths.append(str(package_path))
        self.paths = self.merge_paths(paths)

    @contextmanager
    def acquire_watchdog_lock(self):
        """
        We only want one watchdog running at a time or otherwise we risk stepping
        on each other or having infinitely looping file change notifications.

        """
        package_path = resolve_package_path(self.main_package)

        lock_path = (Path(str(package_path)) / ".watchdog.lock").absolute()
        if lock_path.exists():
            raise WatchdogLockError(lock_path=lock_path)

        try:
            # Create the lock - this caller should now have exclusive access to the watchdog
            lock_path.touch()
            yield
        finally:
            # Remove the lock
            lock_path.unlink()

    def merge_paths(self, raw_paths: list[str]):
        """
        If one path is a subdirectory of another, we only want to watch the parent
        directory. This function merges the paths to avoid duplicate watchers.

        """
        paths = [Path(path).resolve() for path in raw_paths]

        # Parents should come before their subdirectories
        paths.sort(key=lambda path: len(path.parts))

        merged: list[Path] = []

        for path in paths:
            # Check if the current path is a subdirectory of any path in the merged list
            if not any(path.is_relative_to(parent) for parent in merged):
                merged.append(path)

        # Convert Path objects back to strings
        return [str(path) for path in merged]
