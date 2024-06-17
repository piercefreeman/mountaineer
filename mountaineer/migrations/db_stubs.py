from abc import abstractmethod
from typing import Union

from pydantic import BaseModel, Field, model_validator

from mountaineer.compat import Self
from mountaineer.migrations.actions import (
    CheckConstraint,
    ColumnType,
    ConstraintType,
    DatabaseActions,
    ForeignKeyConstraint,
)


class DBObject(BaseModel):
    """
    A subclass for all models that are intended to store
    an in-memory representation of a database object that
    we can perform diff support against.

    """

    model_config = {
        "frozen": True,
    }

    @abstractmethod
    def representation(self) -> str:
        """
        The representation should be unique in global namespace, used to de-duplicate
        objects across multiple migration revisions.

        """
        pass

    @abstractmethod
    async def create(self, actor: DatabaseActions):
        pass

    @abstractmethod
    async def migrate(self, previous: Self, actor: DatabaseActions):
        pass

    @abstractmethod
    async def destroy(self, actor: DatabaseActions):
        pass

    def merge(self, other: Self):
        """
        If there is another object with the same .reference() as this object
        this function is in charge of merging the two objects. By default
        we will just use an equality check to ensure that the objects are the
        same and return the current object.

        If clients override this function, ensure that the result is the same regardless
        of the order that the merge is called in. Callers make no guarantee about the
        resolution order.

        """
        if self != other:
            raise ValueError(
                f"Conflicting definitions for {self.representation()}\n{self} != {other}"
            )
        return self


class DBObjectPointer(BaseModel):
    """
    A pointer to an object that was already created elsewhere. Used only for DAG comparisons. Make sure
    the representation mirrors the root object string - otherwise comparison
    won't work properly.

    We typically use pointers in cases where we want to reference an object that should
    already be created, and the change in the child value shouldn't auto-update the parent.
    Since by default we use direct model-equality to determine whether we create a migration
    stage, nesting a full DBObject within a parent object would otherwise cause the parent
    to update.

    """

    model_config = {
        "frozen": True,
    }

    @abstractmethod
    def representation(self) -> str:
        pass


class DBTable(DBObject):
    table_name: str

    def representation(self):
        return self.table_name

    async def create(self, actor: DatabaseActions):
        actor.add_comment(f"\nNEW TABLE: {self.table_name}\n")
        await actor.add_table(self.table_name)

    async def migrate(self, previous: "DBObject", actor: DatabaseActions):
        raise NotImplementedError

    async def destroy(self, actor: DatabaseActions):
        await actor.drop_table(self.table_name)


class DBColumnBase(BaseModel):
    table_name: str
    column_name: str

    def representation(self):
        return f"{self.table_name}.{self.column_name}"


class DBColumnPointer(DBColumnBase, DBObjectPointer):
    pass


class DBColumn(DBColumnBase, DBObject):
    # Use a type pointer here to avoid full equality checks
    # of the values; if the pointer is the same, we can avoid
    # updating the column type during a migration.
    column_type: Union["DBTypePointer", ColumnType]
    column_is_list: bool

    nullable: bool

    async def create(self, actor: DatabaseActions):
        await actor.add_column(
            self.table_name,
            self.column_name,
            explicit_data_type=(
                self.column_type if isinstance(self.column_type, ColumnType) else None
            ),
            explicit_data_is_list=self.column_is_list,
            custom_data_type=(
                self.column_type.representation()
                if isinstance(self.column_type, DBTypePointer)
                else None
            ),
        )

        if not self.nullable:
            await actor.add_not_null(self.table_name, self.column_name)

    async def destroy(self, actor: DatabaseActions):
        # If we are changing the type, we need to drop and re-create the column
        await actor.drop_column(self.table_name, self.column_name)

        if not self.nullable:
            await actor.drop_not_null(self.table_name, self.column_name)

    async def migrate(self, previous: "DBColumn", actor: DatabaseActions):
        if (
            self.column_type != previous.column_type
            or self.column_is_list != previous.column_is_list
        ):
            previous_column_metadata = " (is list)" if previous.column_is_list else ""
            new_column_metadata = " (is list)" if self.column_is_list else ""

            actor.add_comment(
                "Migrating column type from "
                f"{previous.column_type.name}{previous_column_metadata} to {self.column_type.name}{new_column_metadata}\n"
                "Changing column type does not perform a migration of values.\n"
                "Typically you'll want to create a new column, migrate values, and drop the old column instead."
            )
            await actor.modify_column_type(
                self.table_name,
                self.column_name,
                explicit_data_type=(
                    self.column_type
                    if isinstance(self.column_type, ColumnType)
                    else None
                ),
                explicit_data_is_list=self.column_is_list,
                custom_data_type=(
                    self.column_type.name
                    if isinstance(self.column_type, DBTypePointer)
                    else None
                ),
            )

        if not self.nullable and previous.nullable:
            await actor.add_not_null(self.table_name, self.column_name)
        if self.nullable and not previous.nullable:
            await actor.drop_not_null(self.table_name, self.column_name)


class DBConstraint(DBObject):
    table_name: str
    constraint_name: str = Field(exclude=True)
    columns: frozenset[str]

    constraint_type: ConstraintType

    foreign_key_constraint: ForeignKeyConstraint | None = None
    check_constraint: CheckConstraint | None = None

    @model_validator(mode="after")
    def validate_constraint_type(self):
        if (
            self.constraint_type == ConstraintType.FOREIGN_KEY
            and self.foreign_key_constraint is None
        ):
            raise ValueError("Foreign key constraints require a ForeignKeyConstraint")
        if (
            self.constraint_type != ConstraintType.FOREIGN_KEY
            and self.foreign_key_constraint is not None
        ):
            raise ValueError(
                "Only foreign key constraints require a ForeignKeyConstraint"
            )
        return self

    def representation(self) -> str:
        # Different construction methods sort the constraint parameters in different ways
        # We rely on sorting these parameters to ensure that the representation matches
        # across these different construction methods
        return f"{self.table_name}.{sorted(self.columns)}.{self.constraint_type}"

    @classmethod
    def new_constraint_name(
        cls,
        table_name: str,
        columns: list[str],
        constraint_type: ConstraintType,
    ):
        # We follow the basic naming conventions of sqlalchemy, but there may be variations
        elements = [table_name]
        if constraint_type == ConstraintType.PRIMARY_KEY:
            elements.append("pkey")
        elif constraint_type == ConstraintType.FOREIGN_KEY:
            elements += sorted(columns)
            elements.append("fkey")
        elif constraint_type == ConstraintType.UNIQUE:
            elements += sorted(columns)
            elements.append("unique")
        else:
            elements += sorted(columns)
            elements.append("key")
        return "_".join(elements)

    async def create(self, actor: DatabaseActions):
        if self.constraint_type == ConstraintType.FOREIGN_KEY:
            assert self.foreign_key_constraint is not None
            await actor.add_constraint(
                self.table_name,
                constraint=self.constraint_type,
                constraint_name=self.constraint_name,
                constraint_args=self.foreign_key_constraint,
                columns=list(self.columns),
            )
        elif self.constraint_type == ConstraintType.CHECK:
            assert self.check_constraint is not None
            await actor.add_constraint(
                self.table_name,
                constraint=self.constraint_type,
                constraint_name=self.constraint_name,
                constraint_args=self.check_constraint,
                columns=list(self.columns),
            )
        else:
            await actor.add_constraint(
                self.table_name,
                constraint=self.constraint_type,
                constraint_name=self.constraint_name,
                columns=list(self.columns),
            )

    async def destroy(self, actor: DatabaseActions):
        await actor.drop_constraint(
            self.table_name,
            constraint_name=self.constraint_name,
        )

    async def migrate(self, previous: "DBConstraint", actor: DatabaseActions):
        if self.constraint_type != previous.constraint_type:
            raise NotImplementedError

        # Since we allow some flexibility in column ordering, and that affects
        # the actual constarint name, it's possible that this function is being called
        # with a previous example that is actually the same - but fails the equality check.
        # We re-do a proper comparison here to ensure that we don't do unnecessary work.
        has_changed = False

        self_dict = self.model_dump()
        previous_dict = previous.model_dump()

        for key in self_dict.keys():
            previous_value = self_dict[key]
            current_value = previous_dict[key]
            if previous_value != current_value:
                has_changed = True
                break

        if has_changed:
            await self.destroy(actor)
            await self.create(actor)


class DBTypeBase(BaseModel):
    name: str

    def representation(self):
        # Type definitions are global by nature
        return self.name


class DBTypePointer(DBTypeBase, DBObjectPointer):
    pass


class DBType(DBTypeBase, DBObject):
    values: frozenset[str]

    # Captures the columns that use this type value, (table_name, column_name)
    # so we can migrate them properly to new types. Type dropping in Postgres
    # isn't supported.
    reference_columns: frozenset[tuple[str, str]]

    async def create(self, actor: DatabaseActions):
        await actor.add_type(self.name, sorted(list(self.values)))

    async def destroy(self, actor: DatabaseActions):
        await actor.drop_type(self.name)

    async def migrate(self, previous: "DBType", actor: DatabaseActions):
        previous_values = {value for value in previous.values}
        next_values = {value for value in self.values}

        # We need to update the enum with the new values
        new_values = set(next_values) - set(previous_values)
        deleted_values = set(previous_values) - set(next_values)

        if new_values:
            await actor.add_type_values(
                self.name,
                sorted(new_values),
            )

        if deleted_values:
            await actor.drop_type_values(
                self.name,
                sorted(deleted_values),
                list(self.reference_columns),
            )

    def merge(self, other: "DBType") -> "DBType":
        # We should only be merged with other types that are basically the same
        # but might have different reference columns since they might be produced by
        # different parts of the pipeline.
        if self.name != other.name or self.values != other.values:
            raise ValueError(
                "Cannot merge types with different core values: {self.name}({self.values}) != {other.name}({other.values})"
            )

        return DBType(
            name=self.name,
            values=self.values,
            reference_columns=self.reference_columns | other.reference_columns,
        )
