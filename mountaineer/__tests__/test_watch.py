from pathlib import Path
from threading import Thread
from time import sleep

import pytest

from mountaineer.watch import (
    CallbackDefinition,
    CallbackEvent,
    CallbackMetadata,
    CallbackType,
    ChangeEventHandler,
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
    handler = ChangeEventHandler(
        [], ignore_list=ignore_list, ignore_hidden=ignore_hidden
    )
    assert handler.should_ignore_path(Path(path)) == expected_ignore


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


def test_file_notification(tmp_path: Path):
    callback_events: list[CallbackEvent] = []

    def receive_callback(metadata: CallbackMetadata):
        callback_events.extend(metadata.events)

    def test_file_lifecycle():
        # Make sleeps longer than the debounce interval (0.1s)
        sleep(0.15)
        (tmp_path / "test.txt").write_text("Original")
        sleep(0.15)
        (tmp_path / "test.txt").write_text("Modified")
        sleep(0.15)
        (tmp_path / "test.txt").unlink()
        sleep(0.15)

        assert handler.observer
        handler.observer.stop()

    handler = PackageWatchdog(
        "mountaineer",
        [],
        callbacks=[
            CallbackDefinition(
                action=CallbackType.CREATED
                | CallbackType.MODIFIED
                | CallbackType.DELETED,
                callback=receive_callback,
            )
        ],
    )

    # Override the paths found from the package name with our temporary path
    # where we can write additional files
    handler.paths = [str(tmp_path)]

    lifecycle_thread = Thread(target=test_file_lifecycle)
    lifecycle_thread.start()

    handler.start_watching()

    event_actions: list[CallbackType] = []
    for event in callback_events:
        if event.action not in event_actions:
            event_actions.append(event.action)

    assert event_actions == [
        CallbackType.CREATED,
        CallbackType.MODIFIED,
        CallbackType.DELETED,
    ]
