from pathlib import Path
from threading import Event, Thread
from time import sleep

import pytest
from watchfiles import Change

from mountaineer.watch import (
    CallbackDefinition,
    CallbackEvent,
    CallbackMetadata,
    CallbackType,
    FileWatcher,
    PackageWatchdog,
)


@pytest.mark.parametrize(
    "path, ignore_list, ignore_hidden, expected_ignore",
    [
        ("myproject/regular.py", ["__pycache__"], True, False),
        ("myproject/.hidden", [""], True, True),
        ("myproject/.hidden/subfile", [""], True, True),
        ("myproject/.hidden/subfile", [""], False, False),
        ("myproject/__cache__", ["__cache__"], True, True),
    ],
)
def test_ignore_path(
    path: str,
    ignore_list: list[str],
    ignore_hidden: bool,
    expected_ignore: bool,
):
    watcher = FileWatcher([], ignore_list=ignore_list, ignore_hidden=ignore_hidden)
    assert watcher.should_ignore_path(Path(path)) == expected_ignore


@pytest.mark.parametrize(
    "paths, expected_paths",
    [
        (
            # Unique paths
            ["myproject/regular.py", "myproject/.hidden"],
            ["myproject/regular.py", "myproject/.hidden"],
        ),
        (
            # Simple subdirectory
            ["myproject", "myproject/subdir"],
            ["myproject"],
        ),
        (
            # More specific directory first
            ["myproject/subdir1/subdir2", "myproject/subdir1"],
            ["myproject/subdir1"],
        ),
    ],
)
def test_merge_paths(paths: list[str], expected_paths: list[str]):
    handler = PackageWatchdog("mountaineer", [])
    assert set(handler.merge_paths(paths)) == {
        str(Path(path).absolute()) for path in expected_paths
    }


def test_change_mapping():
    watcher = FileWatcher([])
    assert watcher._map_change_to_callback_type(Change.added) == CallbackType.CREATED
    assert (
        watcher._map_change_to_callback_type(Change.modified) == CallbackType.MODIFIED
    )
    assert watcher._map_change_to_callback_type(Change.deleted) == CallbackType.DELETED


def test_file_notification(tmp_path: Path):
    callback_events: list[CallbackEvent] = []
    stop_event = Event()

    def receive_callback(metadata: CallbackMetadata):
        callback_events.extend(metadata.events)

    def simulate_changes(watcher: FileWatcher):
        # Make sleeps longer than the debounce interval (0.1s)
        sleep(0.15)
        watcher.process_changes([(Change.added, str(tmp_path / "test.txt"))])
        sleep(0.15)
        watcher.process_changes([(Change.modified, str(tmp_path / "test.txt"))])
        sleep(0.15)
        watcher.process_changes([(Change.deleted, str(tmp_path / "test.txt"))])
        sleep(0.15)
        stop_event.set()

    watcher = FileWatcher(
        callbacks=[
            CallbackDefinition(
                action=CallbackType.CREATED
                | CallbackType.MODIFIED
                | CallbackType.DELETED,
                callback=receive_callback,
            )
        ],
    )

    changes_thread = Thread(target=simulate_changes, args=(watcher,))
    changes_thread.start()

    # Wait for all changes to be processed
    stop_event.wait(timeout=2.0)

    event_actions: list[CallbackType] = []
    for event in callback_events:
        if event.action not in event_actions:
            event_actions.append(event.action)

    assert event_actions == [
        CallbackType.CREATED,
        CallbackType.MODIFIED,
        CallbackType.DELETED,
    ]
