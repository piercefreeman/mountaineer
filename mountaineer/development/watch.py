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
    """
    Monitors Python packages for file changes and triggers registered callbacks when changes occur.

    Manages the lifecycle of file watching across multiple packages, optimizing the watch paths
    to avoid redundant watchers, and verifying package availability. Used as the foundation for
    hot-reloading and development tooling in Mountaineer.

    ```python {{sticky: True}}
    import asyncio
    from mountaineer.development.watch import PackageWatchdog, CallbackDefinition, CallbackType, CallbackMetadata

    # Define a callback function to handle file changes
    async def reload_modules(metadata: CallbackMetadata) -> None:
        print(f"Changes detected in {len(metadata.events)} files")
        for event in metadata.events:
            print(f"  {event.action.name}: {event.path}")
            # You would typically reload modules or trigger other actions here

    # Create a watchdog for your main package and any dependencies
    watchdog = PackageWatchdog(
        main_package="my_app",
        dependent_packages=["my_library"],
        callbacks=[
            CallbackDefinition(
                action=CallbackType.MODIFIED | CallbackType.CREATED,
                callback=reload_modules
            )
        ],
        run_on_bootup=True
    )

    await watchdog.start_watching()
    ```

    """

    def __init__(
        self,
        main_package: str,
        dependent_packages: list[str],
        callbacks: list[CallbackDefinition] | None = None,
        run_on_bootup: bool = False,
    ):
        """
        Initialize a package watchdog to monitor file changes across multiple packages.

        :param main_package: Primary package to monitor for file changes
        :param dependent_packages: Additional packages to monitor for changes
        :param callbacks: List of callback definitions to execute when changes occur
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

    async def start_watching(self):
        """
        Begin asynchronously watching all package paths for file changes.

        If configured with run_on_bootup=True, immediately runs all callbacks once.
        Sets up the FileWatcher with registered callbacks and processes changes
        as they occur on the filesystem.

        :raises ValueError: If the watchdog is already running

        """
        self.check_packages_installed()
        self.get_package_paths()

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
        """
        Stop watching all file paths and reset the watchdog state.

        Signals the underlying watchfiles library to stop watching by setting
        the stop event and resets internal state for potential restart.
        """
        self.stop_event.set()
        self.stop_event = asyncio.Event()
        self.running = False

    def check_packages_installed(self):
        """
        Verify that all packages being watched are installed in the current environment.

        :raises ValueError: If any package is not installed
        """
        for package in self.packages:
            try:
                importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                raise ValueError(
                    f"Package '{package}' is not installed in the current environment"
                )

    def get_package_paths(self):
        """
        Resolve filesystem paths for all monitored packages.

        Finds each package's location on disk using importlib and optimizes
        the path list to eliminate redundant watchers through merge_paths.
        """
        paths: list[str] = []
        for package in self.packages:
            package_path = resolve_package_path(package)
            paths.append(str(package_path))
        self.paths = self.merge_paths(paths)

    def merge_paths(self, raw_paths: list[str]) -> list[str]:
        """
        Optimize the list of paths by removing subdirectories when their parent is already watched.

        If one path is a subdirectory of another, we only want to watch the parent
        directory. This function merges the paths to avoid duplicate watchers.

        :param raw_paths: List of directory paths to optimize

        :return List of optimized directory paths with redundancies removed
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
