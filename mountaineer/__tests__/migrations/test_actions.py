from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlmodel import text

from mountaineer.database.session import AsyncSession
from mountaineer.migrations.actions import (
    CheckConstraint,
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
    assert await db_session.exec(text("SELECT * FROM test_table"))


@pytest.mark.asyncio
async def test_add_table_reserved_keyword(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    """
    Confirm that table migrations will wrap the table name in double quotes
    to avoid conflicts with reserved keywords.

    """
    await db_backed_actions.add_table("user")
    await db_session.commit()

    # We should have a table in the database
    assert await db_session.exec(text("SELECT * FROM user"))


@pytest.mark.asyncio
async def test_drop_table(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.exec(text("CREATE TABLE test_table (id SERIAL PRIMARY KEY)"))
    await db_session.commit()

    await db_backed_actions.drop_table("test_table")

    # We should not have a table in the database
    # SQLAlchemy re-raises the exception as a ProgrammingError, but includes
    # the original exception as a string representation that we can match against
    with pytest.raises(ProgrammingError, match="UndefinedTableError"):
        await db_session.exec(text("SELECT * FROM test_table"))


@pytest.mark.asyncio
async def test_add_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.exec(text("CREATE TABLE test_table (id SERIAL PRIMARY KEY)"))
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
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column, test_column_list) VALUES (:column_value, :list_values)"
        ),
        params={
            "column_value": "test_value",
            "list_values": ["value_1", "value_2"],
        },
    )

    await db_session.commit()

    # Make sure that we can retrieve the object
    result = await db_session.exec(text("SELECT * FROM test_table"))
    row = result.fetchone()
    assert row
    assert row[1] == "test_value"
    assert row[2] == ["value_1", "value_2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enum_value", [value for value in ColumnType])
async def test_add_column_any_type(
    enum_value: ColumnType,
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    """
    Simple test that all our known type enum values are formatted properly
    to be inserted into the database, since we don't otherwise validate insertion
    values here.

    """
    # Set up a table for us to drop first
    await db_session.exec(text("CREATE TABLE test_table (id SERIAL PRIMARY KEY)"))
    await db_session.commit()

    await db_backed_actions.add_column(
        "test_table",
        "test_column",
        explicit_data_type=enum_value,
    )

    # Query the postgres index to see if the column was created
    result = await db_session.exec(
        text(
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'test_table' AND column_name = 'test_column'"
        )
    )
    row = result.fetchone()

    # Some values are shortcuts for other values when inserted without
    # additional parameters. We keep track of that mapping here so we allow
    # some flexibility when checking the expected value.
    # (inserted, allowed alternative value in database)
    known_equivalents = (
        (ColumnType.DECIMAL, ColumnType.NUMERIC),
        (ColumnType.SERIAL, ColumnType.INTEGER),
        (ColumnType.BIGSERIAL, ColumnType.BIGINT),
        (ColumnType.CHAR, "character"),
        (ColumnType.TIME, "time without time zone"),
        (ColumnType.TIMESTAMP, "timestamp without time zone"),
    )

    allowed_values = {enum_value.value}
    for known_value, alternative in known_equivalents:
        if enum_value == known_value:
            allowed_values.add(alternative)

    assert row
    assert row[0] in allowed_values


@pytest.mark.asyncio
async def test_drop_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    await db_backed_actions.drop_column("test_table", "test_column")

    # We should not have a column in the table
    with pytest.raises(ProgrammingError, match="UndefinedColumn"):
        await db_session.exec(text("SELECT test_column FROM test_table"))


@pytest.mark.asyncio
async def test_rename_column(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table for us to drop first
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    await db_backed_actions.rename_column("test_table", "test_column", "new_column")

    # We should have a column in the table
    assert await db_session.exec(text("SELECT new_column FROM test_table"))

    # We should not have a column in the table
    with pytest.raises(ProgrammingError, match="UndefinedColumn"):
        await db_session.exec(text("SELECT test_column FROM test_table"))


@pytest.mark.asyncio
async def modify_column_type(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up a table with the old types
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.commit()

    # Modify the column type, since nothing is in the column we should
    # be able to do this without any issues
    await db_backed_actions.modify_column_type(
        "test_table", "test_column", ColumnType.INTEGER
    )

    # We should now be able to inject an integer value
    await db_session.exec(
        text("INSERT INTO test_table (test_column) VALUES (:column_value)"),
        params={
            "column_value": 1,
        },
    )

    await db_session.commit()

    # Make sure that we can retrieve the object
    result = await db_session.exec(text("SELECT * FROM test_table"))
    row = result.fetchone()
    assert row
    assert row[1] == 1


@pytest.mark.asyncio
async def test_add_constraint_foreign_key(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Set up two tables since we need a table target
    await db_session.exec(
        text(
            "CREATE TABLE external_table (id SERIAL PRIMARY KEY, external_column VARCHAR)"
        )
    )
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column_id INTEGER)")
    )

    # Insert an existing object into the external table
    await db_session.exec(
        text(
            "INSERT INTO external_table (id, external_column) VALUES (:id, :column_value)",
        ),
        params={
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
            target_columns=frozenset({"id"}),
        ),
    )

    # We should now have a foreign key constraint
    # Insert an object that links to our known external object
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column_id) VALUES (:column_value)",
        ),
        params={
            "column_value": 1,
        },
    )

    # We should not be able to insert an object that does not link to the external object
    with pytest.raises(IntegrityError, match="foreign key constraint"):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column_id) VALUES (:column_value)",
            ),
            params={
                "column_value": 2,
            },
        )


@pytest.mark.asyncio
async def test_add_constraint_unique(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Add the table that should have a unique column
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )

    # Add a unique constraint
    await db_backed_actions.add_constraint(
        "test_table",
        ["test_column"],
        ConstraintType.UNIQUE,
        "test_unique_constraint",
    )

    # We should now have a unique constraint, make sure that we can't
    # insert the same value twice
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "test_value",
        },
    )

    with pytest.raises(
        IntegrityError, match="duplicate key value violates unique constraint"
    ):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column) VALUES (:column_value)",
            ),
            params={
                "column_value": "test_value",
            },
        )


@pytest.mark.asyncio
async def test_add_constraint_primary_key(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create an empty table to simulate one just created
    await db_session.exec(text("CREATE TABLE test_table ()"))

    # Add a new column
    await db_backed_actions.add_column("test_table", "test_column", ColumnType.INTEGER)

    # Promote the column to a primary key
    await db_backed_actions.add_constraint(
        "test_table",
        ["test_column"],
        ConstraintType.PRIMARY_KEY,
        "test_primary_key_constraint",
    )

    # We should now have a primary key constraint, make sure that we can insert
    # a value into the column
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": 1,
        },
    )

    # We should not be able to insert a duplicate primary key value
    with pytest.raises(
        IntegrityError, match="duplicate key value violates unique constraint"
    ):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column) VALUES (:column_value)",
            ),
            params={
                "column_value": 1,
            },
        )


@pytest.mark.asyncio
async def test_add_constraint_check(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create a table with a integer price column
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, price INTEGER)")
    )

    # Now we add a check constraint that this price column should be positive
    await db_backed_actions.add_constraint(
        "test_table",
        [],
        ConstraintType.CHECK,
        "test_check_constraint",
        constraint_args=CheckConstraint(check_condition="price > 0"),
    )

    # Make sure that we can insert a positive value
    await db_session.exec(
        text(
            "INSERT INTO test_table (price) VALUES (:price)",
        ),
        params={
            "price": 1,
        },
    )

    # We expect negative values to fail
    with pytest.raises(IntegrityError, match="violates check constraint"):
        await db_session.exec(
            text(
                "INSERT INTO test_table (price) VALUES (:price)",
            ),
            params={
                "price": -1,
            },
        )


@pytest.mark.asyncio
async def test_drop_constraint(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Manually create a table with a unique constraint
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )
    await db_session.exec(
        text(
            "ALTER TABLE test_table ADD CONSTRAINT test_unique_constraint UNIQUE (test_column)"
        )
    )

    # Drop the unique constraint
    await db_backed_actions.drop_constraint("test_table", "test_unique_constraint")

    # We should now be able to insert the same value twice
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "test_value",
        },
    )

    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "test_value",
        },
    )


@pytest.mark.asyncio
async def test_add_not_null(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create a table with a nullable column (default behavior for fields)
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR)")
    )

    await db_backed_actions.add_not_null("test_table", "test_column")

    # We should now have a not null constraint, make sure that we can't insert a null value
    with pytest.raises(IntegrityError, match="null value in column"):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column) VALUES (:column_value)",
            ),
            params={
                "column_value": None,
            },
        )


@pytest.mark.asyncio
async def test_drop_not_null(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create a table with a not null column
    await db_session.exec(
        text(
            "CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column VARCHAR NOT NULL)"
        )
    )

    await db_backed_actions.drop_not_null("test_table", "test_column")

    # We should now be able to insert a null value
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": None,
        },
    )


@pytest.mark.asyncio
async def test_add_type(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    await db_backed_actions.add_type("test_type", ["A", "B"])

    # Create a new table with a column of the new type
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column test_type)")
    )

    # We should be able to insert values that match this type
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "A",
        },
    )

    # Values not in the enum type definition should fail during insertion
    with pytest.raises(DBAPIError, match="InvalidTextRepresentationError"):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column) VALUES (:column_value)",
            ),
            params={
                "column_value": "C",
            },
        )


@pytest.mark.asyncio
async def test_add_type_values(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create an existing enum
    await db_session.exec(text("CREATE TYPE test_type AS ENUM ('A')"))

    # Create a table that uses this enum
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column test_type)")
    )

    # Add a new value to this enum
    await db_backed_actions.add_type_values("test_type", ["B"])

    # New enum values need to be committed before they can be used
    await db_session.commit()

    # We should be able to insert values that match this type
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "B",
        },
    )


@pytest.mark.asyncio
async def test_drop_type_values_no_existing_references(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create an existing enum with two values
    await db_session.exec(text("CREATE TYPE test_type AS ENUM ('A', 'B')"))

    # Drop a value from this enum
    await db_backed_actions.drop_type_values("test_type", ["B"], target_columns=[])
    await db_session.commit()

    # Create a table that uses this enum
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column test_type)")
    )

    # Fetch the values for the enum that are currently in use
    result = await db_session.exec(
        text("SELECT array_agg(unnest) FROM unnest(enum_range(NULL::test_type))")
    )
    current_values = result.scalar()
    assert current_values == ["A"]


@pytest.mark.asyncio
async def test_drop_type_values(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create an existing enum with two values
    await db_session.exec(text("CREATE TYPE test_type AS ENUM ('A', 'B')"))

    # Create a table that uses this enum
    await db_session.exec(
        text("CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column test_type)")
    )

    # Drop a value from this enum
    await db_backed_actions.drop_type_values(
        "test_type", ["B"], target_columns=[("test_table", "test_column")]
    )
    await db_session.commit()

    # Fetch the values for the enum that are currently in use
    result = await db_session.exec(
        text("SELECT array_agg(unnest) FROM unnest(enum_range(NULL::test_type))")
    )
    current_values = result.scalar()
    assert current_values == ["A"]

    # We should be able to insert values that match A but not B
    await db_session.exec(
        text(
            "INSERT INTO test_table (test_column) VALUES (:column_value)",
        ),
        params={
            "column_value": "A",
        },
    )

    with pytest.raises(DBAPIError, match="InvalidTextRepresentationError"):
        await db_session.exec(
            text(
                "INSERT INTO test_table (test_column) VALUES (:column_value)",
            ),
            params={
                "column_value": "B",
            },
        )


@pytest.mark.asyncio
async def test_drop_type(
    db_backed_actions: DatabaseActions,
    db_session: AsyncSession,
):
    # Create a new type
    await db_session.exec(text("CREATE TYPE test_type AS ENUM ('A')"))

    # Drop this type
    await db_backed_actions.drop_type("test_type")

    # We shouldn't be able to create a table with this type
    with pytest.raises(ProgrammingError, match='type "test_type" does not exist'):
        await db_session.exec(
            text(
                "CREATE TABLE test_table (id SERIAL PRIMARY KEY, test_column test_type)"
            )
        )
