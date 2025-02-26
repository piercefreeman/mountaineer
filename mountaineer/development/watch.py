import asyncio
import importlib.metadata
from dataclasses import dataclass
from enum import Flag, auto
from pathlib import Path
from typing import Any, Callable, Coroutine, Iterable

from watchfiles import Change, awatch

from mountaineer.console import CONSOLE
from mountaineer.logging import LOGGER, pluralize
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
    callback: Callable[[CallbackMetadata], Coroutine[Any, Any, None]]


class FileWatcher:
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
        self.callbacks = callbacks
        self.ignore_list = ignore_list
        self.ignore_hidden = ignore_hidden
        self.debounce_interval = debounce_interval
        self.debounce_task: asyncio.Task | None = None
        self.pending_events: list[CallbackEvent] = []

    def should_ignore_path(self, path: Path | str) -> bool:
        path_str = str(path)
        path_components = set(path_str.split("/"))

        # Check for any nested hidden directories and ignored directories
        if self.ignore_hidden and any(
            component.startswith(".") for component in path_components
        ):
            return True
        elif path_components & set(self.ignore_list) != set():
            return True
        return False

    def _map_change_to_callback_type(self, change: Change) -> CallbackType:
        if change == Change.added:
            return CallbackType.CREATED
        elif change == Change.modified:
            return CallbackType.MODIFIED
        elif change == Change.deleted:
            return CallbackType.DELETED
        # Default to modified for any other changes
        return CallbackType.MODIFIED

    async def _debounce(self, action: CallbackType, path: Path):
        if self.debounce_task is not None:
            self.debounce_task.cancel()

        self.pending_events.append(CallbackEvent(action=action, path=path))

        self.debounce_task = asyncio.create_task(self._handle_callbacks_after_delay())

    async def _handle_callbacks_after_delay(self):
        await asyncio.sleep(self.debounce_interval)
        await self.handle_callbacks()

    async def handle_callbacks(self):
        """
        Runs all callbacks for the given action.
        """
        for callback in self.callbacks:
            valid_events = [
                event
                for event in self.pending_events
                if event.action in callback.action
            ]
            if valid_events:
                await callback.callback(CallbackMetadata(events=valid_events))

        self.pending_events = []

    async def process_changes(self, changes: Iterable[tuple[Change, str]]):
        """
        Process a batch of changes from watchfiles.
        """
        for change, path_str in changes:
            path = Path(path_str)
            if self.should_ignore_path(path):
                continue

            action = self._map_change_to_callback_type(change)
            if not action.name:
                continue
            CONSOLE.print(f"[yellow]File {action.name.lower()}: {path}")
            await self._debounce(action, path)


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
        self.stop_event = asyncio.Event()
        self.running = False

        self.check_packages_installed()
        self.get_package_paths()

    async def start_watching(self):
        if self.run_on_bootup:
            for callback_definition in self.callbacks:
                await callback_definition.callback(CallbackMetadata(events=[]))

        if self.running:
            raise ValueError("Watchdog is already running")
        self.running = True

        watcher = FileWatcher(callbacks=self.callbacks)

        CONSOLE.print(
            f"👀 Watching {len(self.paths)} {pluralize(len(self.paths), 'path', 'paths')}"
        )
        for path in self.paths:
            LOGGER.info(f"Watching {path}")

        async for changes in awatch(
            *self.paths, stop_event=self.stop_event, watch_filter=None
        ):
            await watcher.process_changes(changes)

    def stop_watching(self):
        self.stop_event.set()
        self.stop_event = asyncio.Event()
        self.running = False

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
