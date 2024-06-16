from enum import Enum
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from mountaineer.migrations.actions import (
    CheckConstraint,
    ColumnType,
    ConstraintType,
    ForeignKeyConstraint,
)
from mountaineer.migrations.db_memory_serializer import DatabaseMemorySerializer
from mountaineer.migrations.db_stubs import (
    DBColumn,
    DBColumnPointer,
    DBConstraint,
    DBTable,
    DBType,
    DBTypePointer,
)


@pytest.mark.parametrize(
    "explicit_constraint_name",
    [
        None,
        "test_custom_value_key",
    ],
)
def test_sa_foreign_key(
    isolated_sqlalchemy,
    explicit_constraint_name: str | None,
):
    """
    Foreign keys are usually specified by a Field(foreign_key=xx) definition. However, they
    can also be specified as a native SQLAlchemy Column object. This test ensures that
    we still parse column foreign keys into the proper format.

    """

    class User(SQLModel, table=True):
        id: UUID = Field(primary_key=True)

    class ExampleModel(SQLModel, table=True):
        id: UUID = Field(primary_key=True)
        user_id: UUID = Field(
            sa_column=sa.Column(
                sa.ForeignKey("user.id", name=explicit_constraint_name)
            ),
        )

    migrator = DatabaseMemorySerializer()
    db_objects = list(migrator.delegate([ExampleModel], context=None))
    assert db_objects == [
        (DBTable(table_name="examplemodel"), []),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="id",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [DBTable(table_name="examplemodel")],
        ),
        (
            DBConstraint(
                table_name="examplemodel",
                constraint_name=(
                    explicit_constraint_name
                    if explicit_constraint_name
                    else "examplemodel_user_id_fkey"
                ),
                columns=frozenset({"user_id"}),
                constraint_type=ConstraintType.FOREIGN_KEY,
                foreign_key_constraint=ForeignKeyConstraint(
                    target_table="user", target_columns=frozenset({"id"})
                ),
            ),
            [
                DBTable(table_name="examplemodel"),
                DBColumnPointer(table_name="examplemodel", column_name="user_id"),
            ],
        ),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="user_id",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=True,
            ),
            [DBTable(table_name="examplemodel")],
        ),
        (
            DBConstraint(
                table_name="examplemodel",
                constraint_name="examplemodel_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
            ),
            [DBColumnPointer(table_name="examplemodel", column_name="id")],
        ),
    ]


@pytest.mark.parametrize(
    "explicit_constraint_name",
    [
        None,
        "test_custom_value_key",
    ],
)
def test_sa_check_constraint(
    isolated_sqlalchemy,
    explicit_constraint_name: str | None,
):
    """
    Foreign keys are usually specified by a Field(foreign_key=xx) definition. However, they
    can also be specified as a native SQLAlchemy Column object. This test ensures that
    we still parse column foreign keys into the proper format.

    """

    class ExampleModel(SQLModel, table=True):
        id: UUID = Field(primary_key=True)
        price: int

        __table_args__ = (
            sa.CheckConstraint("price >= 0", name=explicit_constraint_name),
        )

    migrator = DatabaseMemorySerializer()
    db_objects = list(migrator.delegate([ExampleModel], context=None))
    assert db_objects == [
        (DBTable(table_name="examplemodel"), []),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="id",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [DBTable(table_name="examplemodel")],
        ),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="price",
                column_type=ColumnType.INTEGER,
                column_is_list=False,
                nullable=False,
            ),
            [DBTable(table_name="examplemodel")],
        ),
        (
            DBConstraint(
                table_name="examplemodel",
                constraint_name="examplemodel_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
                check_constraint=None,
            ),
            [DBColumnPointer(table_name="examplemodel", column_name="id")],
        ),
        # This is the critical extracted object, should translate the internal representation
        # of the SQL text into a regular string
        (
            DBConstraint(
                table_name="examplemodel",
                constraint_name=explicit_constraint_name
                if explicit_constraint_name
                else "examplemodel_key",
                columns=frozenset(),
                constraint_type=ConstraintType.CHECK,
                foreign_key_constraint=None,
                check_constraint=CheckConstraint(check_condition="price >= 0"),
            ),
            [DBTable(table_name="examplemodel")],
        ),
    ]


def test_multiple_primary_keys(isolated_sqlalchemy):
    """
    Support models defined SQLModel with multiple primary keys. This should
    result in a composite constraint, which has different handling internally
    than most other field-constraints that are isolated to the field itself.

    """

    class ExampleModel(SQLModel, table=True):
        value_a: UUID = Field(primary_key=True)
        value_b: UUID = Field(primary_key=True)

    migrator = DatabaseMemorySerializer()
    db_objects = list(migrator.delegate([ExampleModel], context=None))
    assert db_objects == [
        (
            DBTable(table_name="examplemodel"),
            [],
        ),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="value_a",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="examplemodel"),
            ],
        ),
        (
            DBColumn(
                table_name="examplemodel",
                column_name="value_b",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [
                DBTable(table_name="examplemodel"),
            ],
        ),
        (
            DBConstraint(
                table_name="examplemodel",
                constraint_name="examplemodel_pkey",
                columns=frozenset({"value_a", "value_b"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
            ),
            [
                DBColumnPointer(table_name="examplemodel", column_name="value_a"),
                DBColumnPointer(table_name="examplemodel", column_name="value_b"),
            ],
        ),
    ]


def test_enum_column_assignment(isolated_sqlalchemy):
    """
    Enum values will just yield the current column that they are assigned to even if they
    are assigned to multiple columns. It's up to the full memory serializer to combine them
    so we can properly track how we can migrate existing enum/column pairs to the
    new values.

    """

    class CommonEnum(Enum):
        A = "a"
        B = "b"

    class ExampleModel1(SQLModel, table=True):
        id: UUID = Field(primary_key=True)
        value: CommonEnum

    class ExampleModel2(SQLModel, table=True):
        id: UUID = Field(primary_key=True)
        value: CommonEnum

    migrator = DatabaseMemorySerializer()
    db_objects = list(migrator.delegate([ExampleModel1, ExampleModel2], context=None))
    assert db_objects == [
        (DBTable(table_name="examplemodel1"), []),
        (
            DBColumn(
                table_name="examplemodel1",
                column_name="id",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [DBTable(table_name="examplemodel1")],
        ),
        (
            DBType(
                name="commonenum",
                values=frozenset({"B", "A"}),
                # This is the important part where we track the reference columns
                reference_columns=frozenset({("examplemodel1", "value")}),
            ),
            [DBTable(table_name="examplemodel1")],
        ),
        (
            DBColumn(
                table_name="examplemodel1",
                column_name="value",
                column_type=DBTypePointer(name="commonenum"),
                column_is_list=False,
                nullable=False,
            ),
            [
                DBType(
                    name="commonenum",
                    values=frozenset({"B", "A"}),
                    reference_columns=frozenset({("examplemodel1", "value")}),
                ),
                DBTable(table_name="examplemodel1"),
            ],
        ),
        (
            DBConstraint(
                table_name="examplemodel1",
                constraint_name="examplemodel1_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
                check_constraint=None,
            ),
            [DBColumnPointer(table_name="examplemodel1", column_name="id")],
        ),
        (DBTable(table_name="examplemodel2"), []),
        (
            DBColumn(
                table_name="examplemodel2",
                column_name="id",
                column_type=ColumnType.UUID,
                column_is_list=False,
                nullable=False,
            ),
            [DBTable(table_name="examplemodel2")],
        ),
        (
            DBType(
                name="commonenum",
                values=frozenset({"B", "A"}),
                # This is the important part where we track the reference columns
                reference_columns=frozenset({("examplemodel2", "value")}),
            ),
            [DBTable(table_name="examplemodel2")],
        ),
        (
            DBColumn(
                table_name="examplemodel2",
                column_name="value",
                column_type=DBTypePointer(name="commonenum"),
                column_is_list=False,
                nullable=False,
            ),
            [
                DBType(
                    name="commonenum",
                    values=frozenset({"B", "A"}),
                    reference_columns=frozenset({("examplemodel2", "value")}),
                ),
                DBTable(table_name="examplemodel2"),
            ],
        ),
        (
            DBConstraint(
                table_name="examplemodel2",
                constraint_name="examplemodel2_pkey",
                columns=frozenset({"id"}),
                constraint_type=ConstraintType.PRIMARY_KEY,
                foreign_key_constraint=None,
                check_constraint=None,
            ),
            [DBColumnPointer(table_name="examplemodel2", column_name="id")],
        ),
    ]
