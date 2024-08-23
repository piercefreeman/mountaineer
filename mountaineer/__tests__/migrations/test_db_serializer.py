from enum import Enum, IntEnum

import pytest
import sqlalchemy as sa
from pydantic import create_model
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import Field, SQLModel
from sqlmodel.main import FieldInfo

from mountaineer.compat import StrEnum
from mountaineer.database.session import AsyncSession
from mountaineer.migrations.actions import (
    ColumnType,
    ConstraintType,
    ForeignKeyConstraint,
)
from mountaineer.migrations.db_serializer import DatabaseSerializer
from mountaineer.migrations.db_stubs import (
    DBColumn,
    DBColumnPointer,
    DBConstraint,
    DBObject,
    DBObjectPointer,
    DBTable,
    DBType,
    DBTypePointer,
)


class ValueEnumStandard(Enum):
    A = "A"


class ValueEnumStr(StrEnum):
    A = "A"


class ValueEnumInt(IntEnum):
    A = 1


def compare_db_objects(
    calculated: list[tuple[DBObject, list[DBObject | DBObjectPointer]]],
    expected: list[tuple[DBObject, list[DBObject | DBObjectPointer]]],
):
    """
    Helper function to compare lists of DBObjects. The order doesn't actually matter
    for downstream uses, but we can't do a simple equality check with a set because the
    dependencies list is un-hashable.

    """
    return sorted(calculated, key=lambda x: x[0].representation()) == sorted(
        expected, key=lambda x: x[0].representation()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_name, annotation, field_info, expected_db_objects",
    [
        # Enum
        (
            "standard_enum",
            ValueEnumStandard,
            Field(),
            [
                (
                    DBType(
                        name="valueenumstandard",
                        values=frozenset({"A"}),
                        reference_columns=frozenset(
                            {("exampledbmodel", "standard_enum")}
                        ),
                    ),
                    [
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
                (
                    DBColumn(
                        table_name="exampledbmodel",
                        column_name="standard_enum",
                        column_type=DBTypePointer(
                            name="valueenumstandard",
                        ),
                        column_is_list=False,
                        nullable=False,
                    ),
                    [
                        DBType(
                            name="valueenumstandard",
                            values=frozenset({"A"}),
                            reference_columns=frozenset(
                                {("exampledbmodel", "standard_enum")}
                            ),
                        ),
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
            ],
        ),
        (
            "str_enum",
            ValueEnumStr,
            Field(),
            [
                (
                    DBType(
                        name="valueenumstr",
                        values=frozenset({"A"}),
                        reference_columns=frozenset({("exampledbmodel", "str_enum")}),
                    ),
                    [
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
                (
                    DBColumn(
                        table_name="exampledbmodel",
                        column_name="str_enum",
                        column_type=DBTypePointer(
                            name="valueenumstr",
                        ),
                        column_is_list=False,
                        nullable=False,
                    ),
                    [
                        DBType(
                            name="valueenumstr",
                            values=frozenset({"A"}),
                            reference_columns=frozenset(
                                {("exampledbmodel", "str_enum")}
                            ),
                        ),
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
            ],
        ),
        (
            "int_enum",
            ValueEnumInt,
            Field(),
            [
                (
                    DBType(
                        name="valueenumint",
                        values=frozenset({"A"}),
                        reference_columns=frozenset({("exampledbmodel", "int_enum")}),
                    ),
                    [
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
                (
                    DBColumn(
                        table_name="exampledbmodel",
                        column_name="int_enum",
                        column_type=DBTypePointer(
                            name="valueenumint",
                        ),
                        column_is_list=False,
                        nullable=False,
                    ),
                    [
                        DBType(
                            name="valueenumint",
                            values=frozenset({"A"}),
                            reference_columns=frozenset(
                                {("exampledbmodel", "int_enum")}
                            ),
                        ),
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
            ],
        ),
        # Nullable type
        (
            "was_nullable",
            str | None,
            Field(),
            [
                (
                    DBColumn(
                        table_name="exampledbmodel",
                        column_name="was_nullable",
                        column_type=ColumnType.VARCHAR,
                        column_is_list=False,
                        nullable=True,
                    ),
                    [
                        DBTable(table_name="exampledbmodel"),
                    ],
                ),
            ],
        ),
        # List types
        (
            "array_list",
            list[str],
            Field(sa_column=sa.Column(sa.ARRAY(sa.String), nullable=False)),
            [
                (
                    DBColumn(
                        table_name="exampledbmodel",
                        column_name="array_list",
                        column_type=ColumnType.VARCHAR,
                        column_is_list=True,
                        nullable=False,
                    ),
                    [
                        DBTable(table_name="exampledbmodel"),
                    ],
                )
            ],
        ),
    ],
)
async def test_simple_db_serializer(
    field_name: str,
    annotation: type,
    field_info: FieldInfo,
    expected_db_objects: list[tuple[DBObject, list[DBObject | DBObjectPointer]]],
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    isolated_sqlalchemy,
):
    ExampleDBModel = create_model(  # type: ignore
        "ExampleDBModel",
        __base__=SQLModel,
        __cls_kwargs__={"table": True},
        **{  # type: ignore
            # Requires the ID to be specified for the model to be constructed correctly
            "id": (int, Field(primary_key=True)),
            field_name: (annotation, field_info),
        },
    )
    assert ExampleDBModel.__tablename__

    # Create this new database
    async with db_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    db_serializer = DatabaseSerializer()
    db_objects = []
    async for values in db_serializer.get_objects(db_session):
        db_objects.append(values)

    # Table and primary key are created for each model
    base_db_objects: list[tuple[DBObject, list[DBObject | DBObjectPointer]]] = [
        (
            DBTable(table_name="exampledbmodel"),
            [],
        ),
        (
            DBColumn(
                table_name="exampledbmodel",
                column_name="id",
                column_type=ColumnType.INTEGER,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="exampledbmodel"),
            ],
        ),
        (
            DBConstraint(
                table_name="exampledbmodel",
                constraint_name="exampledbmodel_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
            ),
            [
                DBColumnPointer(table_name="exampledbmodel", column_name="id"),
                DBTable(table_name="exampledbmodel"),
            ],
        ),
    ]

    assert compare_db_objects(db_objects, base_db_objects + expected_db_objects)


@pytest.mark.asyncio
async def test_db_serializer_foreign_key(
    db_engine: AsyncEngine,
    db_session: AsyncSession,
    isolated_sqlalchemy,
):
    class ForeignModel(SQLModel, table=True):
        id: int = Field(primary_key=True)

    class ExampleDBModel(SQLModel, table=True):
        id: int = Field(primary_key=True)
        foreign_key_id: int = Field(foreign_key="foreignmodel.id")

    # Create this new database
    async with db_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    db_serializer = DatabaseSerializer()
    db_objects = []
    async for values in db_serializer.get_objects(db_session):
        db_objects.append(values)

    expected_db_objects: list[tuple[DBObject, list[DBObject | DBObjectPointer]]] = [
        # Basic ExampleDBModel table
        (
            DBTable(table_name="exampledbmodel"),
            [],
        ),
        (
            DBColumn(
                table_name="exampledbmodel",
                column_name="foreign_key_id",
                column_type=ColumnType.INTEGER,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="exampledbmodel"),
            ],
        ),
        (
            DBColumn(
                table_name="exampledbmodel",
                column_name="id",
                column_type=ColumnType.INTEGER,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="exampledbmodel"),
            ],
        ),
        # ForeignModel table
        (
            DBTable(table_name="foreignmodel"),
            [],
        ),
        (
            DBConstraint(
                table_name="foreignmodel",
                constraint_name="foreignmodel_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
            ),
            [
                DBColumnPointer(table_name="foreignmodel", column_name="id"),
                DBTable(table_name="foreignmodel"),
            ],
        ),
        (
            DBColumn(
                table_name="foreignmodel",
                column_name="id",
                column_type=ColumnType.INTEGER,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="foreignmodel"),
            ],
        ),
        # Foreign key constraint to link ExampleDBModel to ForeignModel
        (
            DBConstraint(
                table_name="exampledbmodel",
                constraint_name="exampledbmodel_foreign_key_id_fkey",
                columns=frozenset({"foreign_key_id"}),
                constraint_type=ConstraintType.FOREIGN_KEY,
                foreign_key_constraint=ForeignKeyConstraint(
                    target_table="foreignmodel", target_columns=frozenset({"id"})
                ),
            ),
            [
                DBColumnPointer(
                    table_name="exampledbmodel", column_name="foreign_key_id"
                ),
                DBTable(table_name="exampledbmodel"),
            ],
        ),
        (
            DBConstraint(
                table_name="exampledbmodel",
                constraint_name="exampledbmodel_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
            ),
            [
                DBColumnPointer(table_name="exampledbmodel", column_name="id"),
                DBTable(table_name="exampledbmodel"),
            ],
        ),
    ]

    assert compare_db_objects(db_objects, expected_db_objects)
