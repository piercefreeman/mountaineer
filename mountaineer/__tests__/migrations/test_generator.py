from dataclasses import dataclass
from enum import Enum
from typing import Any

import pytest
from pydantic import BaseModel

from mountaineer.migrations.actions import ColumnType, DatabaseActions, DryRunAction
from mountaineer.migrations.db_memory_serializer import DatabaseMemorySerializer
from mountaineer.migrations.db_stubs import DBTable
from mountaineer.migrations.dependency import MigrationDependencies
from mountaineer.migrations.generator import MigrationGenerator
from mountaineer.migrations.migration import MigrationRevisionBase


@pytest.mark.asyncio
async def test_new_migration():
    migration_generator = MigrationGenerator()

    code, up_revision = await migration_generator.new_migration(
        down_objects_with_dependencies=[
            (
                DBTable(
                    table_name="test_table_a",
                ),
                [],
            )
        ],
        up_objects_with_dependencies=[
            (
                DBTable(
                    table_name="test_table_b",
                ),
                [],
            )
        ],
        down_revision="test_down_revision",
        user_message="test_user_message",
    )

    # Expected up
    assert 'await migrator.actor.add_table(table_name="test_table_b")' in code
    assert 'await migrator.actor.drop_table(table_name="test_table_a")' in code

    # Expected down
    assert 'await migrator.actor.drop_table(table_name="test_table_b")' in code
    assert 'await migrator.actor.add_table(table_name="test_table_a")' in code

    assert "Context: test_user_message" in code
    assert 'down_revision: str | None = "test_down_revision"' in code


def test_actions_to_code():
    actor = DatabaseActions()
    migration_generator = MigrationGenerator()

    code = migration_generator.actions_to_code(
        [
            DryRunAction(
                fn=actor.add_column,
                kwargs={
                    "table_name": "test_table",
                    "column_name": "test_column",
                    "explicit_data_type": ColumnType.VARCHAR,
                },
            )
        ]
    )
    assert code == [
        'await migrator.actor.add_column(table_name="test_table", column_name="test_column", explicit_data_type=ColumnType.VARCHAR)'
    ]


def test_actions_to_code_pass():
    """
    We support generating migrations where there are no schema-level changes, so users can
    write their own data migration logic. In these cases we should pass the code-block
    so the resulting file is still legitimate.

    """
    migration_generator = MigrationGenerator()
    code = migration_generator.actions_to_code([])
    assert code == ["pass"]


class ExampleEnum(Enum):
    A = "a"
    B = "b"


class ExampleModel(BaseModel):
    value: str


@dataclass
class ExampleDataclass:
    value: str


@pytest.mark.parametrize(
    "value, expected_value",
    [
        (ExampleEnum.A, "ExampleEnum.A"),
        ("example_arg", '"example_arg"'),
        (1, "1"),
        (
            {"key": "value", "nested": {"key": "value2"}},
            '{"key": "value", "nested": {"key": "value2"}}',
        ),
        (
            {
                "key": ExampleModel(value="test"),
                "enum": ExampleEnum.B,
            },
            '{"key": ExampleModel(value="test"), "enum": ExampleEnum.B}',
        ),
        (ExampleModel(value="test"), 'ExampleModel(value="test")'),
        (ExampleDataclass(value="test"), 'ExampleDataclass(value="test")'),
        (True, "True"),
        (False, "False"),
        (frozenset({"A", "B"}), 'frozenset({"A", "B"})'),
        ({"A", "B"}, '{"A", "B"}'),
        (("A",), '("A",)'),
        (("A", "B"), '("A", "B")'),
    ],
)
def test_format_arg(value: Any, expected_value: str):
    migration_generator = MigrationGenerator()
    assert migration_generator.format_arg(value) == expected_value


def test_track_import():
    migration_generator = MigrationGenerator()

    migration_generator.track_import(DatabaseMemorySerializer)
    migration_generator.track_import(MigrationRevisionBase)
    migration_generator.track_import(
        MigrationDependencies,
        explicit="mountaineer.migrations.dependency.MigrationDependencies",
    )

    assert dict(migration_generator.import_tracker) == {
        "mountaineer.migrations.dependency": {"MigrationDependencies"},
        "mountaineer.migrations.migration": {"MigrationRevisionBase"},
        "mountaineer.migrations.db_memory_serializer": {"DatabaseMemorySerializer"},
    }
