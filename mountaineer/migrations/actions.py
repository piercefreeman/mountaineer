from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any, Callable, Literal, overload

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import text

from mountaineer.compat import StrEnum
from mountaineer.logging import LOGGER


class ColumnType(StrEnum):
    # The values of the enum are the actual SQL types. When constructing
    # the column they can be case-insensitive, but when we're casting from
    # the database to memory they must align with the on-disk representation
    # which is lowercase.

    # Numeric Types
    SMALLINT = "smallint"
    INTEGER = "integer"
    BIGINT = "bigint"
    DECIMAL = "decimal"
    NUMERIC = "numeric"
    REAL = "real"
    DOUBLE_PRECISION = "double precision"
    SERIAL = "serial"
    BIGSERIAL = "bigserial"

    # Monetary Type
    MONEY = "money"

    # Character Types
    CHAR = "char"
    VARCHAR = "character varying"
    TEXT = "text"

    # Binary Data Types
    BYTEA = "bytea"

    # Date/Time Types
    DATE = "date"
    TIME = "time"
    TIME_WITH_TIME_ZONE = "time with time zone"
    TIMESTAMP = "timestamp"
    TIMESTAMP_WITH_TIME_ZONE = "timestamp with time zone"
    INTERVAL = "interval"

    # Boolean Type
    BOOLEAN = "boolean"

    # Geometric Types
    POINT = "point"
    LINE = "line"
    LSEG = "lseg"
    BOX = "box"
    PATH = "path"
    POLYGON = "polygon"
    CIRCLE = "circle"

    # Network Address Types
    CIDR = "cidr"
    INET = "inet"
    MACADDR = "macaddr"
    MACADDR8 = "macaddr8"

    # Bit String Types
    BIT = "bit"
    BIT_VARYING = "bit varying"

    # Text Search Types
    TSVECTOR = "tsvector"
    TSQUERY = "tsquery"

    # UUID Type
    UUID = "uuid"

    # XML Type
    XML = "xml"

    # JSON Types
    JSON = "json"
    JSONB = "jsonb"

    # Range Types
    INT4RANGE = "int4range"
    NUMRANGE = "numrange"
    TSRANGE = "tsrange"
    TSTZRANGE = "tstzrange"
    DATERANGE = "daterange"

    # Object Identifier Type
    OID = "oid"


class ConstraintType(StrEnum):
    PRIMARY_KEY = "PRIMARY KEY"
    FOREIGN_KEY = "FOREIGN KEY"
    UNIQUE = "UNIQUE"
    CHECK = "CHECK"
    EXCLUDE = "EXCLUDE"


class ForeignKeyConstraint(BaseModel):
    target_table: str
    target_columns: frozenset[str]

    model_config = {
        "frozen": True,
    }


class CheckConstraint(BaseModel):
    check_condition: str

    model_config = {
        "frozen": True,
    }


class ExcludeConstraint(BaseModel):
    exclude_operator: str

    model_config = {
        "frozen": True,
    }


@dataclass
class DryRunAction:
    fn: Callable
    kwargs: dict[str, Any]


@dataclass
class DryRunComment:
    text: str


class DatabaseActions:
    """
    Track the actions that need to be executed to the database. Provides
    a shallow, typed ORM on top of the raw SQL commands that we'll execute
    through sqlalchemy.

    """

    def __init__(
        self,
        dry_run: bool = True,
        db_session: AsyncSession | None = None,
    ):
        self.dry_run = dry_run

        if not dry_run:
            if db_session is None:
                raise ValueError("Must provide a db_session when not in dry run mode.")

        self.dry_run_actions: list[DryRunAction | DryRunComment] = []
        self.db_session = db_session
        self.prod_sqls: list[str] = []

    async def add_table(self, table_name: str):
        await self._record_signature(
            self.add_table,
            dict(table_name=table_name),
            f"""
            CREATE TABLE {table_name}
            """,
        )

    async def drop_table(self, table_name: str):
        await self._record_signature(
            self.drop_table,
            dict(table_name=table_name),
            f"""
            DROP TABLE {table_name}
            """,
        )

    async def add_column(
        self,
        table_name: str,
        column_name: str,
        explicit_data_type: ColumnType | None = None,
        explicit_data_is_list: bool = False,
        custom_data_type: str | None = None,
    ):
        if not explicit_data_type and not custom_data_type:
            raise ValueError(
                "Must provide either an explicit data type or a custom data type."
            )
        if explicit_data_type and custom_data_type:
            raise ValueError(
                "Cannot provide both an explicit data type and a custom data type."
            )

        column_type = self._get_column_type(
            explicit_data_type=explicit_data_type,
            explicit_data_is_list=explicit_data_is_list,
            custom_data_type=custom_data_type,
        )

        await self._record_signature(
            self.add_column,
            dict(
                table_name=table_name,
                column_name=column_name,
                explicit_data_type=explicit_data_type,
                explicit_data_is_list=explicit_data_is_list,
                custom_data_type=custom_data_type,
            ),
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {column_type}
            """,
        )

    async def drop_column(self, table_name: str, column_name: str):
        await self._record_signature(
            self.drop_column,
            dict(table_name=table_name, column_name=column_name),
            f"""
            ALTER TABLE {table_name}
            DROP COLUMN {column_name}
            """,
        )

    async def rename_column(
        self, table_name: str, old_column_name: str, new_column_name: str
    ):
        await self._record_signature(
            self.rename_column,
            dict(
                table_name=table_name,
                old_column_name=old_column_name,
                new_column_name=new_column_name,
            ),
            f"""
            ALTER TABLE {table_name}
            RENAME COLUMN {old_column_name} TO {new_column_name}
            """,
        )

    async def modify_column_type(
        self,
        table_name: str,
        column_name: str,
        explicit_data_type: ColumnType | None = None,
        explicit_data_is_list: bool = False,
        custom_data_type: str | None = None,
    ):
        if not explicit_data_type and not custom_data_type:
            raise ValueError(
                "Must provide either an explicit data type or a custom data type."
            )
        if explicit_data_type and custom_data_type:
            raise ValueError(
                "Cannot provide both an explicit data type and a custom data type."
            )

        column_type = self._get_column_type(
            explicit_data_type=explicit_data_type,
            explicit_data_is_list=explicit_data_is_list,
            custom_data_type=custom_data_type,
        )

        await self._record_signature(
            self.modify_column_type,
            dict(
                table_name=table_name,
                column_name=column_name,
                explicit_data_type=explicit_data_type,
                explicit_data_is_list=explicit_data_is_list,
                custom_data_type=custom_data_type,
            ),
            f"""
            ALTER TABLE {table_name}
            MODIFY COLUMN {column_name} {column_type}
            """,
        )

    @overload
    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: Literal[ConstraintType.FOREIGN_KEY],
        constraint_name: str,
        constraint_args: ForeignKeyConstraint,
    ):
        ...

    @overload
    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: Literal[ConstraintType.PRIMARY_KEY],
        constraint_name: str,
        constraint_args: None = None,
    ):
        ...

    @overload
    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: Literal[ConstraintType.UNIQUE],
        constraint_name: str,
        constraint_args: None = None,
    ):
        ...

    @overload
    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: Literal[ConstraintType.EXCLUDE],
        constraint_name: str,
        constraint_args: None = None,
    ):
        ...

    @overload
    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: Literal[ConstraintType.CHECK],
        constraint_name: str,
        constraint_args: None = None,
    ):
        ...

    async def add_constraint(
        self,
        table_name: str,
        columns: list[str],
        constraint: ConstraintType,
        constraint_name: str,
        constraint_args: BaseModel | None = None,
    ):
        columns_formatted = ", ".join(columns)

        sql = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} "

        if constraint == ConstraintType.PRIMARY_KEY:
            sql += f"PRIMARY KEY ({columns_formatted})"
        elif constraint == ConstraintType.FOREIGN_KEY:
            if not isinstance(constraint_args, ForeignKeyConstraint):
                raise ValueError(
                    f"Constraint type FOREIGN_KEY must have ForeignKeyConstraint args, received: {constraint_args}"
                )
            ref_cols_formatted = ", ".join(constraint_args.target_columns)
            sql += f"FOREIGN KEY ({columns_formatted}) REFERENCES {constraint_args.target_table} ({ref_cols_formatted})"
        elif constraint == ConstraintType.UNIQUE:
            sql += f"UNIQUE ({columns_formatted})"
        elif constraint == ConstraintType.CHECK:
            if not isinstance(constraint_args, CheckConstraint):
                raise ValueError(
                    f"Constraint type CHECK must have CheckConstraint args, received: {constraint_args}"
                )
            sql += f"CHECK ({constraint_args.check_condition})"
        elif constraint == ConstraintType.EXCLUDE:
            if not isinstance(constraint_args, ExcludeConstraint):
                raise ValueError(
                    f"Constraint type EXCLUDE must have ExcludeConstraint args, received: {constraint_args}"
                )
            sql += f"EXCLUDE USING {constraint_args.exclude_operator} ({columns_formatted})"
        else:
            raise ValueError("Unsupported constraint type")

        sql += ";"
        await self._record_signature(
            self.add_constraint,
            dict(
                table_name=table_name,
                columns=columns,
                constraint=constraint,
                constraint_name=constraint_name,
                constraint_args=constraint_args,
            ),
            sql,
        )

    async def drop_constraint(
        self,
        table_name: str,
        constraint_name: str,
    ):
        await self._record_signature(
            self.drop_constraint,
            dict(
                table_name=table_name,
                constraint_name=constraint_name,
            ),
            f"""
            ALTER TABLE {table_name}
            DROP CONSTRAINT {constraint_name}
            """,
        )

    async def add_not_null(self, table_name: str, column_name: str):
        await self._record_signature(
            self.add_not_null,
            dict(table_name=table_name, column_name=column_name),
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN {column_name}
            SET NOT NULL
            """,
        )

    async def drop_not_null(self, table_name: str, column_name: str):
        await self._record_signature(
            self.drop_not_null,
            dict(table_name=table_name, column_name=column_name),
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN {column_name}
            DROP NOT NULL
            """,
        )

    async def add_type(self, type_name: str, values: list[str]):
        formatted_values = ", ".join(f"'{value}'" for value in values)

        await self._record_signature(
            self.add_type,
            dict(type_name=type_name, values=values),
            f"""
            CREATE TYPE {type_name} AS ENUM ({formatted_values})
            """,
        )

    async def add_type_value(self, type_name: str, value: str):
        await self._record_signature(
            self.add_type_value,
            dict(type_name=type_name, value=value),
            f"""
            ALTER TYPE {type_name} ADD VALUE '{value}'
            """,
        )

    async def drop_type_value(self, type_name: str, value: str):
        await self._record_signature(
            self.drop_type_value,
            dict(type_name=type_name, value=value),
            f"""
            ALTER TYPE {type_name} DROP VALUE '{value}'
            """,
        )

    async def drop_type(self, type_name: str):
        await self._record_signature(
            self.drop_type,
            dict(type_name=type_name),
            f"""
            DROP TYPE {type_name}
            """,
        )

    def _get_column_type(
        self,
        explicit_data_type: ColumnType | None = None,
        explicit_data_is_list: bool = False,
        custom_data_type: str | None = None,
    ) -> str:
        if explicit_data_type:
            return f"{explicit_data_type}{'[]' if explicit_data_is_list else ''}"
        elif custom_data_type:
            return custom_data_type
        else:
            raise ValueError(
                "Must provide either an explicit data type or a custom data type."
            )

    async def _record_signature(
        self,
        action: Callable,
        kwargs: dict[str, Any],
        sql: str,
    ):
        """
        If we are doing a dry-run through the migration, only record the method
        signature that was provided. Otherwise if we're actually executing the
        migration, record the SQL that was generated.

        """
        # Validate that the kwargs can populate all of the action signature arguments
        # that are not optional, and that we don't provide any kwargs that aren't specified
        # in the action signature
        # Get the signature of the action
        sig = signature(action)
        parameters = sig.parameters

        # Check for required arguments not supplied
        missing_args = [
            name
            for name, param in parameters.items()
            if param.default is Parameter.empty and name not in kwargs
        ]
        if missing_args:
            raise ValueError(f"Missing required arguments: {missing_args}")

        # Check for extraneous arguments in kwargs
        extraneous_args = [key for key in kwargs if key not in parameters]
        if extraneous_args:
            raise ValueError(f"Extraneous arguments provided: {extraneous_args}")

        if self.dry_run:
            self.dry_run_actions.append(
                DryRunAction(
                    fn=action,
                    kwargs=kwargs,
                )
            )
        else:
            if self.db_session is None:
                raise ValueError("Cannot execute migration without a database session")

            LOGGER.debug(f"Executing migration SQL: {sql}")

            self.prod_sqls.append(sql)
            await self.db_session.execute(text(sql))

    def add_comment(self, text: str):
        if self.dry_run:
            self.dry_run_actions.append(DryRunComment(text=text))
