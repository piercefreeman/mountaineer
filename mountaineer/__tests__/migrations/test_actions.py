from unittest.mock import AsyncMock

import pytest

from mountaineer.migrations.actions import DatabaseActions, DryRunAction


def example_action_fn(arg_1: str):
    pass


@pytest.mark.asyncio
async def test_record_signature_dry_run():
    database_actions = DatabaseActions(dry_run=True)

    await database_actions._record_signature(
        example_action_fn, {"arg_1": "test"}, "SQL"
    )

    assert database_actions.dry_run_actions == [
        DryRunAction(fn=example_action_fn, kwargs={"arg_1": "test"})
    ]
    assert database_actions.prod_sqls == []


@pytest.mark.asyncio
async def test_record_signature_prod():
    database_actions = DatabaseActions(dry_run=False, db_session=AsyncMock())

    await database_actions._record_signature(
        example_action_fn, {"arg_1": "test"}, "SQL"
    )

    assert database_actions.dry_run_actions == []
    assert database_actions.prod_sqls == ["SQL"]


@pytest.mark.asyncio
async def test_record_signature_incorrect_kwarg():
    database_actions = DatabaseActions(dry_run=False, db_session=AsyncMock())

    # An extra, non-existent kwarg is provided
    with pytest.raises(ValueError):
        await database_actions._record_signature(
            example_action_fn, {"arg_1": "test", "arg_2": "test"}, "SQL"
        )

    # A required kwarg is missing
    with pytest.raises(ValueError):
        await database_actions._record_signature(example_action_fn, {}, "SQL")
