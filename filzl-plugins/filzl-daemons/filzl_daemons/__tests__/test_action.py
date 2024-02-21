import pytest

from filzl_daemons.actions import action


def test_requires_async():
    with pytest.raises(
        ValueError, match="Function test_sync_action is not a coroutine function"
    ):

        @action
        def test_sync_action():
            pass
