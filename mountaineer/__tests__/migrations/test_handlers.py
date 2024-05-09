from uuid import UUID

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
)


def test_sa_foreign_key(isolated_sqlalchemy):
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
            sa_column=sa.Column(sa.ForeignKey("user.id")),
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
                constraint_name="examplemodel_user_id_fkey",
                columns=frozenset({"user_id"}),
                constraint_type=ConstraintType.FOREIGN_KEY,
                foreign_key_constraint=ForeignKeyConstraint(
                    target_table="user", target_columns=frozenset({"id"})
                ),
            ),
            [DBTable(table_name="examplemodel")],
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


def test_check_constraint(isolated_sqlalchemy):
    """
    Foreign keys are usually specified by a Field(foreign_key=xx) definition. However, they
    can also be specified as a native SQLAlchemy Column object. This test ensures that
    we still parse column foreign keys into the proper format.

    """

    class ExampleModel(SQLModel, table=True):
        id: UUID = Field(primary_key=True)
        price: int

        __table_args__ = (sa.CheckConstraint("price >= 0"),)

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
                constraint_name="examplemodel_key",
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
