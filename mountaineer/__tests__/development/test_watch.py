import asyncio
from pathlib import Path

import pytest
from watchfiles import Change

from mountaineer.development.watch import (
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


@pytest.mark.asyncio
async def test_file_notification(tmp_path: Path):
    callback_events: list[CallbackEvent] = []
    stop_event = asyncio.Event()

    async def receive_callback(metadata: CallbackMetadata):
        callback_events.extend(metadata.events)

    async def simulate_changes(watcher: FileWatcher):
        # Make sleeps longer than the debounce interval (0.1s)
        await asyncio.sleep(0.15)
        await watcher.process_changes([(Change.added, str(tmp_path / "test.txt"))])
        await asyncio.sleep(0.15)
        await watcher.process_changes([(Change.modified, str(tmp_path / "test.txt"))])
        await asyncio.sleep(0.15)
        await watcher.process_changes([(Change.deleted, str(tmp_path / "test.txt"))])
        await asyncio.sleep(0.15)
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

    changes_task = asyncio.create_task(simulate_changes(watcher))
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        changes_task.cancel()

    event_actions: list[CallbackType] = []
    for event in callback_events:
        if event.action not in event_actions:
            event_actions.append(event.action)

    assert event_actions == [
        CallbackType.CREATED,
        CallbackType.MODIFIED,
        CallbackType.DELETED,
    ]
