from enum import Enum
from unittest.mock import ANY

import pytest
from sqlmodel import Field, SQLModel

from mountaineer.migrations.actions import (
    ColumnType,
    ConstraintType,
    DatabaseActions,
    DryRunAction,
    DryRunComment,
)
from mountaineer.migrations.db_memory_serializer import DatabaseMemorySerializer


@pytest.mark.asyncio
async def test_from_scratch_migration():
    """
    Test a migration from scratch.

    """

    class OldValues(Enum):
        A = "A"

    class ModelA(SQLModel):
        id: int = Field(primary_key=True)
        animal: OldValues
        was_nullable: str | None

    migrator = DatabaseMemorySerializer()

    db_objects = list(migrator.delegate([ModelA], context=None))
    next_ordering = migrator.order_db_objects(db_objects)

    actor = DatabaseActions()
    actions = await migrator.build_actions(
        actor, [], {}, [obj for obj, _ in db_objects], next_ordering
    )

    assert actions == [
        DryRunComment(
            text="\n" "NEW TABLE: modela\n",
        ),
        DryRunAction(
            fn=actor.add_table,
            kwargs={
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "id",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                # Primary integers should be made to auto-increment
                "explicit_data_type": ColumnType.SERIAL,
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={
                "table_name": "modela",
                "column_name": "id",
            },
        ),
        DryRunAction(
            fn=actor.add_type,
            kwargs={
                "type_name": "oldvalues",
                "values": [
                    "A",
                ],
            },
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "was_nullable",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.VARCHAR,
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_constraint,
            kwargs={
                "columns": [
                    "id",
                ],
                "constraint": ConstraintType.PRIMARY_KEY,
                "constraint_args": None,
                "constraint_name": "modela_pkey",
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "animal",
                "custom_data_type": "oldvalues",
                "explicit_data_is_list": False,
                "explicit_data_type": None,
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={
                "table_name": "modela",
                "column_name": "animal",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_diff_migration():
    """
    Test the diff migration between two schemas.

    """

    class OldValues(Enum):
        A = "A"

    class NewValues(Enum):
        A = "A"
        B = "B"

    class ModelA(SQLModel):
        id: int = Field(primary_key=True)
        animal: OldValues
        was_nullable: str | None

    class ModelANew(SQLModel):
        __tablename__ = "modela"  # type: ignore
        id: int = Field(primary_key=True)
        name: str
        animal: NewValues
        was_nullable: str

    actor = DatabaseActions()
    migrator = DatabaseMemorySerializer()

    db_objects = list(migrator.delegate([ModelA], context=None))
    db_objects_previous = [obj for obj, _ in db_objects]
    previous_ordering = migrator.order_db_objects(db_objects)

    db_objects_new = list(migrator.delegate([ModelANew], context=None))
    db_objects_next = [obj for obj, _ in db_objects_new]
    next_ordering = migrator.order_db_objects(db_objects_new)

    actor = DatabaseActions()
    actions = await migrator.build_actions(
        actor, db_objects_previous, previous_ordering, db_objects_next, next_ordering
    )
    assert actions == [
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "name",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.VARCHAR,
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={
                "table_name": "modela",
                "column_name": "name",
            },
        ),
        DryRunAction(
            fn=actor.add_type,
            kwargs={
                "type_name": "newvalues",
                "values": [
                    "A",
                    "B",
                ],
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={
                "column_name": "was_nullable",
                "table_name": "modela",
            },
        ),
        DryRunComment(
            text=ANY,
        ),
        DryRunAction(
            fn=actor.modify_column_type,
            kwargs={
                "column_name": "animal",
                "custom_data_type": "newvalues",
                "explicit_data_is_list": False,
                "explicit_data_type": None,
                "table_name": "modela",
            },
        ),
        DryRunAction(
            fn=actor.drop_type,
            kwargs={
                "type_name": "oldvalues",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_duplicate_enum_migration():
    """
    Test that the shared reference to an enum across multiple tables results in only
    one migration action to define the type.

    """

    class EnumValues(Enum):
        A = "A"
        B = "B"

    class Model1(SQLModel):
        id: int = Field(primary_key=True)
        value: EnumValues

    class Model2(SQLModel):
        id: int = Field(primary_key=True)
        value: EnumValues

    migrator = DatabaseMemorySerializer()

    db_objects = list(migrator.delegate([Model1, Model2], context=None))
    next_ordering = migrator.order_db_objects(db_objects)

    actor = DatabaseActions()
    actions = await migrator.build_actions(
        actor, [], {}, [obj for obj, _ in db_objects], next_ordering
    )

    assert actions == [
        DryRunComment(text="\nNEW TABLE: model1\n"),
        DryRunAction(fn=actor.add_table, kwargs={"table_name": "model1"}),
        DryRunComment(text="\nNEW TABLE: model2\n"),
        DryRunAction(fn=actor.add_table, kwargs={"table_name": "model2"}),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "id",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.SERIAL,
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null, kwargs={"column_name": "id", "table_name": "model1"}
        ),
        DryRunAction(
            fn=actor.add_type, kwargs={"type_name": "enumvalues", "values": ["A", "B"]}
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "id",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.SERIAL,
                "table_name": "model2",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null, kwargs={"column_name": "id", "table_name": "model2"}
        ),
        DryRunAction(
            fn=actor.add_constraint,
            kwargs={
                "columns": ["id"],
                "constraint": ConstraintType.PRIMARY_KEY,
                "constraint_args": None,
                "constraint_name": "model1_pkey",
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "value",
                "custom_data_type": "enumvalues",
                "explicit_data_is_list": False,
                "explicit_data_type": None,
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={"column_name": "value", "table_name": "model1"},
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "value",
                "custom_data_type": "enumvalues",
                "explicit_data_is_list": False,
                "explicit_data_type": None,
                "table_name": "model2",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={"column_name": "value", "table_name": "model2"},
        ),
        DryRunAction(
            fn=actor.add_constraint,
            kwargs={
                "columns": ["id"],
                "constraint": ConstraintType.PRIMARY_KEY,
                "constraint_args": None,
                "constraint_name": "model2_pkey",
                "table_name": "model2",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_required_db_default():
    """
    Even if we have a default value in Python, we should still force the content
    to have a value at the db level.

    """

    class Model1(SQLModel):
        id: int = Field(primary_key=True)
        value: str = "ABC"
        value2: str = Field(default="ABC")

    migrator = DatabaseMemorySerializer()

    db_objects = list(migrator.delegate([Model1], context=None))
    next_ordering = migrator.order_db_objects(db_objects)

    actor = DatabaseActions()
    actions = await migrator.build_actions(
        actor, [], {}, [obj for obj, _ in db_objects], next_ordering
    )

    assert actions == [
        DryRunComment(text="\nNEW TABLE: model1\n"),
        DryRunAction(fn=actor.add_table, kwargs={"table_name": "model1"}),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "id",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.SERIAL,
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null, kwargs={"column_name": "id", "table_name": "model1"}
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "value",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.VARCHAR,
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={"column_name": "value", "table_name": "model1"},
        ),
        DryRunAction(
            fn=actor.add_column,
            kwargs={
                "column_name": "value2",
                "custom_data_type": None,
                "explicit_data_is_list": False,
                "explicit_data_type": ColumnType.VARCHAR,
                "table_name": "model1",
            },
        ),
        DryRunAction(
            fn=actor.add_not_null,
            kwargs={"column_name": "value2", "table_name": "model1"},
        ),
        DryRunAction(
            fn=actor.add_constraint,
            kwargs={
                "columns": ["id"],
                "constraint": ConstraintType.PRIMARY_KEY,
                "constraint_args": None,
                "constraint_name": "model1_pkey",
                "table_name": "model1",
            },
        ),
    ]
