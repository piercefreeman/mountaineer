from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import text

from mountaineer.migrations.actions import (
    ColumnType,
    ConstraintType,
    DatabaseActions,
    DryRunAction,
    ForeignKeyConstraint,
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


@pytest.mark.asyncio
async def test_drop_table(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.execute(text("CREATE TABLE test_table (id SERIAL PRIMARY KEY)"))
    await db_session.commit()

    await db_backed_actions.drop_table("test_table")

    # We should not have a table in the database
    # SQLAlchemy re-raises the exception as a ProgrammingError, but includes
    # the original exception as a string representation that we can match against
    with pytest.raises(ProgrammingError, match="UndefinedTableError"):
        await db_session.execute(text("SELECT * FROM test_table"))


@pytest.mark.asyncio
async def test_add_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.execute(text("CREATE TABLE test_table (id SERIAL PRIMARY KEY)"))
    await db_session.commit()

    # Standard type
    await db_backed_actions.add_column(
        "test_table",
        "test_column",
        explicit_data_type=ColumnType.VARCHAR,
    )

    # Standard, list type
    await db_backed_actions.add_column(
        "test_table",
        "test_column_list",
        explicit_data_type=ColumnType.VARCHAR,
        explicit_data_is_list=True,
    )

    # We should now have columns in the table
    # Insert an object with the expected columns
    await db_session.execute(
        text(
            "INSERT INTO test_table (test_column, test_column_list) VALUES (:column_value, :list_values)"
        ),
        {
            "column_value": "test_value",
            "list_values": ["value_1", "value_2"],
        },
    )

    await db_session.commit()

    # Make sure that we can retrieve the object
    result = await db_session.execute(text("SELECT * FROM test_table"))
    row = result.fetchone()
    assert row[1] == "test_value"
    assert row[2] == ["value_1", "value_2"]


@pytest.mark.asyncio
async def test_drop_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.execute(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    await db_backed_actions.drop_column("test_table", "test_column")

    # We should not have a column in the table
    with pytest.raises(ProgrammingError, match="UndefinedColumn"):
        await db_session.execute(text("SELECT test_column FROM test_table"))


@pytest.mark.asyncio
async def test_rename_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.execute(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    await db_backed_actions.rename_column("test_table", "test_column", "new_column")

    # We should have a column in the table
    assert await db_session.execute(text("SELECT new_column FROM test_table"))

    # We should not have a column in the table
    with pytest.raises(ProgrammingError, match="UndefinedColumn"):
        await db_session.execute(text("SELECT test_column FROM test_table"))


@pytest.mark.asyncio
async def modify_column_type(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table with the old types
    await db_session.execute(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    # Modify the column type, since nothing is in the column we should
    # be able to do this without any issues
    await db_backed_actions.modify_column_type(
        "test_table", "test_column", ColumnType.INTEGER
    )

    # We should now be able to inject an integer value
    await db_session.execute(
        text("INSERT INTO test_table (test_column) VALUES (:column_value)"),
        {
            "column_value": 1,
        },
    )

    await db_session.commit()

    # Make sure that we can retrieve the object
    result = await db_session.execute(text("SELECT * FROM test_table"))
    row = result.fetchone()
    assert row[1] == 1


@pytest.mark.asyncio
async def test_add_constraint_foreign_key(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up two tables since we need a table target
    await db_session.execute(
        text(
            "CREATE TABLE external_table (id SERIAL PRIMARY KEY, external_column VARCHAR)"
        )
    )
    await db_session.execute(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column_id INTEGER)")
    )

    # Insert an existing object into the external table
    await db_session.execute(
        text(
            "INSERT INTO external_table (id, external_column) VALUES (:id, :column_value)",
        ),
        {
            "id": 1,
            "column_value": "test_value",
        },
    )

    # Add a foreign_key
    await db_backed_actions.add_constraint(
        "test_table",
        ["test_column_id"],
        ConstraintType.FOREIGN_KEY,
        "test_foreign_key_constraint",
        constraint_args=ForeignKeyConstraint(
            target_table="external_table",
            target_columns=["id"],
        ),
    )

    # We should now have a foreign key constraint
    # Insert an object that links to our known external object
    await db_session.execute(
        text(
            "INSERT INTO test_table (test_column_id) VALUES (:column_value)",
        ),
        {
            "column_value": 1,
        },
    )

    # We should not be able to insert an object that does not link to the external object
    with pytest.raises(IntegrityError, match="foreign key constraint"):
        await db_session.execute(
            text(
                "INSERT INTO test_table (test_column_id) VALUES (:column_value)",
            ),
            {
                "column_value": 2,
            },
        )
