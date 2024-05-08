from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import text

from mountaineer.migrations.actions import (
    DatabaseActions,
    DryRunAction,
    assert_is_safe_sql_identifier,
    format_sql_values,
)


@pytest.fixture
def db_backed_actions(
    db_session: AsyncSession,
    isolated_sqlalchemy,
    clear_all_database_objects,
):
    """
    Fixture that should be used for actions that should actually be executed
    against a database. We will clear all database objects before and after
    the test, so no SQLModel backed objects will be available.

    """
    return DatabaseActions(dry_run=False, db_session=db_session)


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


@pytest.mark.parametrize(
    "identifier, expected_is_valid",
    [
        # Valid identifiers
        ("validTableName", True),
        ("_valid_table_name", True),
        ("Table123", True),
        ("_", True),
        ("t", True),
        # Invalid identifiers
        ("123table", False),
        ("table-name", False),
        ("table name", False),
        ("table$name", False),
        ("table!name", False),
        ("table@name", False),
        ("table#name", False),
        ("", False),
        (" ", False),
        (" table", False),
        ("table ", False),
        ("table\n", False),
        # SQL injection attempts
        ("table; DROP TABLE users;", False),
        ("table; SELECT * FROM users", False),
        ("1;1", False),
        (";", False),
        ("--comment", False),
        ("' OR '1'='1", False),
        ('" OR "1"="1', False),
        ("table`", False),
        ("[table]", False),
        ("{table}", False),
        ("<script>", False),
        ('"; DROP TABLE users; --', False),
        ("'; DROP TABLE users; --", False),
    ],
)
def test_is_safe_sql_identifier(identifier: str, expected_is_valid: bool):
    if expected_is_valid:
        assert_is_safe_sql_identifier(identifier)
    else:
        with pytest.raises(ValueError):
            assert_is_safe_sql_identifier(identifier)


@pytest.mark.parametrize(
    "values, expected",
    [
        # Simple strings without special characters
        (["single"], "'single'"),
        ([], ""),
        (["apple", "banana"], "'apple', 'banana'"),
        # Strings with single quotes that need escaping
        (["O'Neill", "d'Artagnan"], "'O''Neill', 'd''Artagnan'"),
        # Mixed strings, no special characters and with special characters
        (["hello", "it's a test"], "'hello', 'it''s a test'"),
        # Strings that contain SQL-like syntax
        (
            ["SELECT * FROM users;", "DROP TABLE students;"],
            "'SELECT * FROM users;', 'DROP TABLE students;'",
        ),
        # Empty strings and spaces
        (["", " ", "   "], "'', ' ', '   '"),
    ],
)
def test_format_sql_values(values, expected):
    assert format_sql_values(values) == expected


@pytest.mark.asyncio
async def test_add_table(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    await db_backed_actions.add_table("test_table")
    await db_session.commit()

    # We should have a table in the database
    assert await db_session.execute(text("SELECT * FROM test_table"))
