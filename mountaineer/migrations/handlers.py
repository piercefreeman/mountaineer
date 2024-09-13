from abc import abstractmethod
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import Enum, IntEnum
from typing import TYPE_CHECKING, Any, Generator, Generic, Type, TypeVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from pydantic.fields import FieldInfo as PydanticFieldInfo
from pydantic_core import PydanticUndefinedType
from sqlalchemy.sql import sqltypes
from sqlmodel import SQLModel
from sqlmodel._compat import is_field_noneable
from sqlmodel.main import FieldInfo as SQLModelFieldInfo

from mountaineer.compat import StrEnum
from mountaineer.migrations.actions import (
    CheckConstraint,
    ColumnType,
    ConstraintType,
    DatabaseActions,
    ForeignKeyConstraint,
)
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
from mountaineer.migrations.generics import (
    remove_null_type,
)

if TYPE_CHECKING:
    from mountaineer.migrations.db_memory_serializer import DatabaseMemorySerializer


@dataclass
class DelegateContext:
    """
    Track data context from the high level (table) to the low level (column and constraints)

    """

    current_table: str | None = None
    current_column: str | None = None


N = TypeVar("N")


class HandlerBaseMeta(type):
    _registry: list["HandlerBaseMeta"] = []

    def __init__(cls, name, bases, nmspc):
        super(HandlerBaseMeta, cls).__init__(name, bases, nmspc)
        # Avoid registering HandlerBase itself
        if cls.__name__ != "HandlerBase":
            HandlerBaseMeta._registry.append(cls)

    @classmethod
    def get_registry(cls):
        return cls._registry


class HandlerBase(Generic[N], metaclass=HandlerBaseMeta):
    """
    Unlike table schema definitions that are defined in Postgres, in-memory representations
    of a data model are more ambiguous / varied. SQLModels for instance can support
    their own native types/attributes, SQLAlchemy columns, or SQLAlchemy types. We therefore
    consolidate the parsing logic into DBObjects into multiple refactored classes
    that own a particular family of types with the same parsing strategy.

    """

    def __init__(self, migrator: "DatabaseMemorySerializer"):
        self.serializer = migrator

    @abstractmethod
    def convert(
        self, next: N, context: DelegateContext
    ) -> Generator[tuple[DBObject, list[DBObject | DBObjectPointer]], Any, None]:
        pass


class TypeDeclarationResponse(DBObject):
    # Not really a db object, but we need to fulfill the yield contract
    # They'll be filtered out later
    primitive_type: ColumnType | None = None
    custom_type: DBType | None = None
    is_list: bool

    def representation(self) -> str:
        raise NotImplementedError()

    def create(self, actor: DatabaseActions):
        raise NotImplementedError()

    def destroy(self, actor: DatabaseActions):
        raise NotImplementedError()

    def migrate(self, previous, actor: DatabaseActions):
        raise NotImplementedError()


class DatabaseHandler(HandlerBase[list[SQLModel]]):
    def convert(self, next: list[SQLModel], context: DelegateContext):
        for model in next:
            table_name = model.__tablename__
            if table_name is None:
                raise ValueError("Table name cannot be None")
            elif not isinstance(table_name, str):
                raise ValueError(
                    f"Table name {table_name} must be a string, not {type(table_name)}"
                )

            # Delegate to the table handler
            yield from self.serializer.delegate(
                model,
                context=replace(context, current_table=table_name),
            )


class TableHandler(HandlerBase[SQLModel]):
    def convert(self, next: SQLModel, context: DelegateContext):
        if not context.current_table:
            raise ValueError(f"Table must be set before creating a table: {context}")

        # Table must be created before we populate the fields
        table = DBTable(table_name=context.current_table)
        yield table, []

        for field_name, field in next.model_fields.items():
            yield from self.serializer.delegate(
                field,
                context=replace(context, current_column=field_name),
                dependent_on=[table],
            )

        # Assemble all the primary keys and create a new primary key constraint
        primary_key_columns = [
            field_name
            for field_name, field in next.model_fields.items()
            if isinstance(field, SQLModelFieldInfo) and field.primary_key is True
        ]
        if primary_key_columns:
            yield from self.serializer.delegate(
                ConstraintWrapper(columns=primary_key_columns, primary_key=True),
                dependent_on=[
                    DBColumnPointer(
                        table_name=table.table_name, column_name=column_name
                    )
                    for column_name in primary_key_columns
                ],
                context=context,
            )

        # Also handle the metadata defined at the table level, usually unique constraints
        # that affect multiple columns
        # We need to wrap in a custom class to indicate to the proper handler that it
        # needs to pick up this normal dictionary
        if hasattr(next, "__table_args__"):
            for constraint in next.__table_args__:  # type: ignore
                yield from self.serializer.delegate(
                    constraint,
                    context=context,
                    dependent_on=[table],
                )


class ColumnHandler(HandlerBase[PydanticFieldInfo]):
    def convert(
        self, next: PydanticFieldInfo, context: DelegateContext
    ) -> Generator[tuple[DBObject, list[DBObject | DBObjectPointer]], Any, None]:
        if not context.current_table or not context.current_column:
            raise ValueError(
                f"Table and column must be set before creating a column: {context}"
            )

        # We need to make sure the field type is created before
        # we try to create the column itself
        delegated_results = []
        is_nullable = is_field_noneable(next)
        is_primary_key = (
            (
                next.primary_key
                if not isinstance(next.primary_key, PydanticUndefinedType)
                else False
            )
            if isinstance(next, SQLModelFieldInfo)
            else False
        )

        if isinstance(next, SQLModelFieldInfo):
            sa_type = (
                next.sa_type
                if not isinstance(next.sa_type, PydanticUndefinedType)
                else None
            )
            sa_column = (
                next.sa_column
                if not isinstance(next.sa_column, PydanticUndefinedType)
                else None
            )

            # An explicit SQLAlchemy column type has been provided, we should parse
            # this as the root type
            if sa_type is not None or sa_column is not None:
                delegated_results = list(
                    self.serializer.delegate(sa_type or sa_column, context)
                )

            # Use the SQLModel definition to determine if the value is nullable
            # There's some conditional logic within their internal implementation to determine
            # if a column can be nullable (ie. not a primary key, not explicitly required, etc)
            # We mirror that logic here so the type definitions out of Mountaineer will mirror those
            # that would be generated with a from-scratch table creation in SQLModel
            if sa_column is None:
                if not isinstance(next.nullable, PydanticUndefinedType):
                    is_nullable = next.nullable
                else:
                    # https://github.com/tiangolo/sqlmodel/blob/main/sqlmodel/main.py#L633
                    is_nullable = not is_primary_key and is_nullable
            else:
                # We take the nullable value from the column definition
                is_nullable = sa_column.nullable

        if not delegated_results and next.annotation is not None:
            delegated_results = list(
                self.serializer.delegate(remove_null_type(next.annotation), context)
            )

        type_results = [
            (result, dependencies)
            for result, dependencies in delegated_results
            if isinstance(result, TypeDeclarationResponse)
        ]
        nontype_results = [
            (result, dependencies)
            for result, dependencies in delegated_results
            if not isinstance(result, TypeDeclarationResponse)
        ]
        yield from nontype_results

        if len(type_results) > 1:
            raise ValueError(
                f"Conflicting types for column {context.current_column} in table {context.current_table}"
                "\n".join(str(type_result) for type_result in type_results)
            )
        elif len(type_results) == 0:
            raise ValueError(
                f"No types found for column {context.current_column} in table {context.current_table}"
            )

        # Only forward along if we're creating the type
        type_payload, type_dependencies = type_results[0]
        if not isinstance(type_payload, TypeDeclarationResponse):
            raise ValueError(
                f"Expected a type declaration response, got {type_payload}"
            )

        # Create the actual db object if need be
        if type_payload.custom_type:
            yield type_payload.custom_type, type_dependencies

        column_type = (
            DBTypePointer(name=type_payload.custom_type.name)
            if type_payload.custom_type
            else type_payload.primitive_type
        )
        if not column_type:
            raise ValueError(
                f"No column type found for column {context.current_column} in table {context.current_table}"
            )

        # Special case handling for SERIAL keys: if an integer is a primary key,
        # we should automatically convert it to a SERIAL type. We have to do here instead
        # of at the type conversion level because the type conversion level doesn't have
        # the context of the primary key
        if (
            is_primary_key
            and type_payload.primitive_type
            and type_payload.primitive_type == ColumnType.INTEGER
        ):
            column_type = ColumnType.SERIAL

        # We need to create the column itself once types have been created
        column = DBColumn(
            table_name=context.current_table,
            column_name=context.current_column,
            column_type=column_type,
            column_is_list=type_payload.is_list,
            nullable=is_nullable,
        )
        yield (
            column,
            [db_obj.custom_type for db_obj, _ in type_results if db_obj.custom_type],
        )

        # Delegate to the constraint handler to handle the constraints
        yield from self.serializer.delegate(
            self.field_to_constraint_wrapper(next, context.current_column),
            context=context,
            dependent_on=[column],
        )

    def field_to_constraint_wrapper(
        self,
        field_info: PydanticFieldInfo,
        current_column: str,
    ):
        # Validation that applies regardless of the additional metadata that
        # the SQLModelFieldInfo might provide
        common_constraint = ConstraintWrapper(
            columns=[current_column],
        )

        if isinstance(field_info, SQLModelFieldInfo):
            if field_info.foreign_key and not isinstance(
                field_info.foreign_key, PydanticUndefinedType
            ):
                common_constraint.foreign_key = field_info.foreign_key
            if field_info.unique and not isinstance(
                field_info.unique, PydanticUndefinedType
            ):
                common_constraint.unique = field_info.unique
            if field_info.index and not isinstance(
                field_info.index, PydanticUndefinedType
            ):
                common_constraint.index = field_info.index

            # Primary keys have to be handled at the table-level so we can support
            # adding a composite primary key that spans multiple columns

        return common_constraint


class ConstraintWrapper(BaseModel):
    explicit_name: str | None = None

    unique: bool | None = None
    index: bool | None = None
    primary_key: bool | None = None
    foreign_key: str | None = None
    check_expression: str | None = None

    columns: list[str]


class ColumnConstraintHandler(HandlerBase[ConstraintWrapper]):
    def convert(
        self,
        next: ConstraintWrapper,
        context: DelegateContext,
    ):
        if not context.current_table:
            raise ValueError(
                f"The constraint handler requires the current table to be passed in: {context}"
            )

        # All constraints can only be added after the columns
        # they depend on have been added. This must be made explicit here
        # (versus the implicit hierarchy dependencies) in the case of multiple
        # constraints being added on the table level versus the column level
        common_col_dependencies: list[DBObject | DBObjectPointer] = [
            DBColumnPointer(
                table_name=context.current_table,
                column_name=column_name,
            )
            for column_name in next.columns
        ]

        if next.primary_key:
            yield (
                DBConstraint(
                    table_name=context.current_table,
                    constraint_type=ConstraintType.PRIMARY_KEY,
                    columns=frozenset(next.columns),
                    constraint_name=(
                        next.explicit_name
                        if next.explicit_name
                        else DBConstraint.new_constraint_name(
                            context.current_table,
                            next.columns,
                            ConstraintType.PRIMARY_KEY,
                        )
                    ),
                ),
                common_col_dependencies,
            )
        if next.index:
            yield (
                DBConstraint(
                    table_name=context.current_table,
                    constraint_type=ConstraintType.INDEX,
                    columns=frozenset(next.columns),
                    constraint_name=(
                        next.explicit_name
                        if next.explicit_name
                        else DBConstraint.new_constraint_name(
                            context.current_table,
                            next.columns,
                            ConstraintType.INDEX,
                        )
                    ),
                ),
                common_col_dependencies,
            )
        if next.foreign_key:
            target_table, target_column = next.foreign_key.rsplit(".", 1)

            yield (
                DBConstraint(
                    table_name=context.current_table,
                    constraint_type=ConstraintType.FOREIGN_KEY,
                    columns=frozenset(next.columns),
                    constraint_name=(
                        next.explicit_name
                        if next.explicit_name
                        else DBConstraint.new_constraint_name(
                            context.current_table,
                            next.columns,
                            ConstraintType.FOREIGN_KEY,
                        )
                    ),
                    foreign_key_constraint=ForeignKeyConstraint(
                        target_table=target_table,
                        target_columns=frozenset({target_column}),
                    ),
                ),
                common_col_dependencies,
            )
        if next.unique:
            yield (
                DBConstraint(
                    table_name=context.current_table,
                    constraint_type=ConstraintType.UNIQUE,
                    columns=frozenset(next.columns),
                    constraint_name=(
                        next.explicit_name
                        if next.explicit_name
                        else DBConstraint.new_constraint_name(
                            context.current_table, next.columns, ConstraintType.UNIQUE
                        )
                    ),
                ),
                common_col_dependencies,
            )
        if next.check_expression:
            yield (
                DBConstraint(
                    table_name=context.current_table,
                    constraint_type=ConstraintType.CHECK,
                    columns=frozenset(next.columns),
                    constraint_name=(
                        next.explicit_name
                        if next.explicit_name
                        else DBConstraint.new_constraint_name(
                            context.current_table, next.columns, ConstraintType.CHECK
                        )
                    ),
                    check_constraint=CheckConstraint(
                        check_condition=next.check_expression,
                    ),
                ),
                common_col_dependencies,
            )


class SQLAlchemyColumnHandler(HandlerBase[sa.Column]):
    def convert(self, next: sa.Column, context: DelegateContext):
        results = self.serializer.delegate(next.type, context)
        yield from results

        for foreign_key in next.foreign_keys:
            yield from self.serializer.delegate(
                foreign_key, context, dependent_on=[db_obj for db_obj, _ in results]
            )

        if next.index and context.current_column:
            common_constraint = ConstraintWrapper(
                columns=[context.current_column],
                index=True,
            )
            yield from self.serializer.delegate(common_constraint, context)


class SQLAlchemyForeignKeyHandler(HandlerBase[sa.ForeignKey]):
    def convert(self, next: sa.ForeignKey, context: DelegateContext):
        if not context.current_column:
            raise ValueError(
                f"Foreign key handler requires the current column to be set: {context}"
            )

        target_table = next.column.table.name
        target_column = next.column.name

        if next.name is not None and not isinstance(next.name, str):
            raise ValueError(
                f"Foreign key name must be a string, got {next.name} of type {type(next.name)}"
            )

        yield from self.serializer.delegate(
            ConstraintWrapper(
                explicit_name=next.name,
                foreign_key=f"{target_table}.{target_column}",
                columns=[context.current_column],
            ),
            context=context,
        )


class SQLAlchemyCheckConstraintHandler(HandlerBase[sa.CheckConstraint]):
    def convert(self, next: sa.CheckConstraint, context: DelegateContext):
        if next.name is not None and not isinstance(next.name, str):
            raise ValueError(
                f"Foreign key name must be a string, got {next.name} of type {type(next.name)}"
            )

        yield from self.serializer.delegate(
            ConstraintWrapper(
                explicit_name=next.name,
                check_expression=str(next.sqltext),
                columns=[],  # This is a table-level constraint
            ),
            context=context,
        )


class SQLAlchemyArrayHandler(HandlerBase[sa.ARRAY]):
    def convert(self, next: sa.ARRAY, context: DelegateContext):
        # Get the internal type of the array
        for core_type, dependencies in self.serializer.delegate(
            next.item_type, context
        ):
            if not isinstance(core_type, TypeDeclarationResponse):
                raise ValueError(
                    f"Expected a type declaration response, got {core_type}"
                )

            yield (
                TypeDeclarationResponse(
                    primitive_type=core_type.primitive_type,
                    custom_type=core_type.custom_type,
                    is_list=True,
                ),
                dependencies,
            )


class TableConstraintHandler(HandlerBase[sa.UniqueConstraint]):
    """
    Constraints defined at the __table_args__ level that can span multiple
    columns.

    """

    def convert(
        self, next: sa.UniqueConstraint, context: DelegateContext
    ) -> Generator[tuple[DBObject, list[DBObject | DBObjectPointer]], Any, None]:
        if not context.current_table:
            raise ValueError(
                f"Table must be set before creating a table constraint: {context}"
            )

        column_names = [col.name for col in next.columns]

        yield (
            DBConstraint(
                table_name=context.current_table,
                constraint_type=ConstraintType.UNIQUE,
                constraint_name=DBConstraint.new_constraint_name(
                    context.current_table, column_names, ConstraintType.UNIQUE
                ),
                columns=frozenset(column_names),
            ),
            [
                # Since we don't directly have access to the columns here, but still
                # want to create this constraint only after the columns have been
                # created, we use a object pointer.
                DBColumnPointer(
                    table_name=context.current_table, column_name=column_name
                )
                for column_name in column_names
            ],
        )


class IndexConstraintHandler(HandlerBase[sa.Index]):
    """
    Indexes defined at the __table_args__ level that can span multiple
    columns.

    """

    def convert(
        self, next: sa.Index, context: DelegateContext
    ) -> Generator[tuple[DBObject, list[DBObject | DBObjectPointer]], Any, None]:
        if not context.current_table:
            raise ValueError(
                f"Table must be set before creating a table constraint: {context}"
            )

        column_names = [col.name for col in next.columns]

        yield (
            DBConstraint(
                table_name=context.current_table,
                constraint_type=ConstraintType.INDEX,
                constraint_name=DBConstraint.new_constraint_name(
                    context.current_table, column_names, ConstraintType.INDEX
                ),
                columns=frozenset(column_names),
            ),
            [
                # Since we don't directly have access to the columns here, but still
                # want to create this constraint only after the columns have been
                # created, we use a object pointer.
                DBColumnPointer(
                    table_name=context.current_table, column_name=column_name
                )
                for column_name in column_names
            ],
        )


PRIMITIVE_TYPES = int | float | str | bool | bytes | UUID
PRIMITIVE_WRAPPER_TYPES = list[PRIMITIVE_TYPES] | PRIMITIVE_TYPES


class PrimitiveHandler(HandlerBase[PRIMITIVE_WRAPPER_TYPES]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.python_to_sql = {
            int: ColumnType.INTEGER,
            float: ColumnType.DOUBLE_PRECISION,
            str: ColumnType.VARCHAR,
            bool: ColumnType.BOOLEAN,
            bytes: ColumnType.BYTEA,
            UUID: ColumnType.UUID,
            Any: ColumnType.JSON,
        }

    def convert(
        self,
        next: PRIMITIVE_WRAPPER_TYPES,
        context: DelegateContext,
    ):
        if not context.current_table or not context.current_column:
            raise ValueError(
                f"The column handler requires a full context to be passed in: {context}"
            )

        for primitive, json_type in self.python_to_sql.items():
            if next == primitive or next == list[primitive]:  # type: ignore
                yield (
                    TypeDeclarationResponse(
                        primitive_type=json_type,
                        is_list=(next == list[primitive]),  # type: ignore
                    ),
                    [],
                )
                return


SQLALCHEMY_PRIMITIVE_TYPES = (
    sa.UUID | sqltypes.Uuid | sa.Float | sa.String | sa.Boolean | sa.Integer | sa.JSON
)


class SQLAlchemyPrimitiveHandler(HandlerBase[SQLALCHEMY_PRIMITIVE_TYPES]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.primitive_to_sql = {
            sa.Integer: ColumnType.INTEGER,
            sa.Float: ColumnType.DOUBLE_PRECISION,
            sa.String: ColumnType.VARCHAR,
            sa.Boolean: ColumnType.BOOLEAN,
            sa.UUID: ColumnType.UUID,
            sqltypes.Uuid: ColumnType.UUID,
            sa.JSON: ColumnType.JSON,
        }

    def convert(self, next: SQLALCHEMY_PRIMITIVE_TYPES, context: DelegateContext):
        for primitive, column_type in self.primitive_to_sql.items():
            if next == primitive or isinstance(next, primitive):
                yield (
                    TypeDeclarationResponse(
                        primitive_type=column_type,
                        is_list=False,
                    ),
                    [],
                )
                return


ALL_PYTHON_DATETIME_TYPES = datetime | date | time | timedelta
ALL_SQLALCHEMY_DATETIME_TYPES = sa.DateTime | sa.Date | sa.Time | sa.Interval


class DateHandler(
    HandlerBase[ALL_PYTHON_DATETIME_TYPES | ALL_SQLALCHEMY_DATETIME_TYPES]
):
    def convert(
        self,
        next: ALL_PYTHON_DATETIME_TYPES | ALL_SQLALCHEMY_DATETIME_TYPES,
        context: DelegateContext,
    ):
        if next == datetime or next == sa.DateTime:
            yield (
                TypeDeclarationResponse(
                    primitive_type=ColumnType.TIMESTAMP, is_list=False
                ),
                [],
            )
        elif isinstance(next, sa.DateTime):
            # Unlike python datetimes, we need to be timezone aware when parsing sqlalchemy objects
            yield (
                TypeDeclarationResponse(
                    primitive_type=(
                        ColumnType.TIMESTAMP_WITH_TIME_ZONE
                        if next.timezone
                        else ColumnType.TIMESTAMP
                    ),
                    is_list=False,
                ),
                [],
            )
        elif next == date or next == sa.Date or isinstance(next, sa.Date):
            yield (
                TypeDeclarationResponse(primitive_type=ColumnType.DATE, is_list=False),
                [],
            )
        elif next == time or sa == sa.Time or isinstance(next, sa.Time):
            yield (
                TypeDeclarationResponse(primitive_type=ColumnType.TIME, is_list=False),
                [],
            )
        elif next == timedelta or next == sa.Interval or isinstance(next, sa.Interval):
            yield (
                TypeDeclarationResponse(
                    primitive_type=ColumnType.INTERVAL, is_list=False
                ),
                [],
            )
        else:
            raise ValueError(f"Unsupported datetime type: {next}")


# Cast a wide net for all the enum types so str doesn't capture str enums
ALL_ENUM_TYPES = Type[Enum | StrEnum | IntEnum]


class EnumHandler(HandlerBase[ALL_ENUM_TYPES]):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # We don't want to handle the same enum type multiple times since the type
        # is global and can be shared across multiple columns
        self.next_to_previous: dict[ALL_ENUM_TYPES, set[ALL_ENUM_TYPES]] = {}
        self.all_previous: set[ALL_ENUM_TYPES] = set()

    def convert(self, next: ALL_ENUM_TYPES, context: DelegateContext):
        if not context.current_table or not context.current_column:
            raise ValueError(
                f"The enum handler requires a full context to be passed in: {context}"
            )

        yield (
            TypeDeclarationResponse(
                custom_type=DBType(
                    name=next.__name__.lower(),
                    values=frozenset([value.name for value in next]),
                    reference_columns=frozenset(
                        {(context.current_table, context.current_column)}
                    ),
                ),
                is_list=False,
            ),
            [],
        )
