from collections import defaultdict
from typing import Type, cast

from pydantic import BaseModel
from sqlalchemy import (
    UniqueConstraint,
    inspect,
)
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.sql.schema import Table

from mountaineer.database.sqlmodel import SQLModel
from mountaineer.logging import LOGGER


class FieldSchema(BaseModel):
    name: str
    type: str
    primary_key: bool = False
    nullable: bool = True
    foreign_key: str | None = None
    unique: bool = False


class TableSchema(BaseModel):
    name: str
    fields: dict[str, FieldSchema]


class DatabaseValidator:
    """
    Validate that the database schemas are aligned with our ORM defined models. This does a live lookup
    against the current table definitions, so you'll have to pass an active Engine to the constructor.
    Internally we'll use this engine throughout the validation lifecycle.

    """

    def __init__(self, engine):
        self.engine = engine

    def validate_database_alignment(self, models: list[Type[SQLModel]]):
        """
        Returns the discrepancies between the current database schema and the expected schema, if any.

        """
        current_schema = self.get_current_schema()
        expected_schema = self.parse_model_definitions(models)
        discrepancies = self.compare_schemas(current_schema, expected_schema)
        return {
            table_key: list(found_issues)
            for table_key, found_issues in discrepancies.items()
        }

    def parse_model_definitions(
        self, models: list[Type[SQLModel]]
    ) -> dict[str, TableSchema]:
        """
        Parse the Python model for the current definitions
        """
        model_schemas: dict[str, TableSchema] = {}
        for model in models:
            fields: dict[str, FieldSchema] = {}
            table = cast(Table, model.__table__)  # type: ignore
            primary_keys = {pk.name for pk in table.primary_key}
            unique_constraints = {
                col.name
                for constraint in table.constraints
                if isinstance(constraint, UniqueConstraint)
                for col in constraint.columns
            }
            foreign_keys = {
                fk.parent.name: fk.column.table.name + "(" + fk.column.name + ")"
                for fk in table.foreign_keys
            }

            for column in table.columns:
                field_schema = FieldSchema(
                    name=column.name,
                    type=str(column.type),
                    primary_key=column.name in primary_keys,
                    nullable=column.nullable if column.nullable is not None else True,
                    foreign_key=foreign_keys.get(column.name),
                    unique=column.name in unique_constraints,
                )
                fields[column.name] = field_schema
            table_name = model.__tablename__
            if not isinstance(table_name, str):
                raise ValueError(
                    f"Table name for model {model} is not a string: {table_name}"
                )
            model_schemas[table_name] = TableSchema(name=table_name, fields=fields)
        return model_schemas

    def get_current_schema(self) -> dict[str, TableSchema]:
        """
        Parse the database for the current table schema
        """
        inspector: Inspector = inspect(self.engine)
        tables_schema: dict[str, TableSchema] = {}

        for table_name in inspector.get_table_names():
            columns_info = inspector.get_columns(table_name)
            pk_constraint = inspector.get_pk_constraint(table_name)
            fk_constraints = inspector.get_foreign_keys(table_name)
            indexes = inspector.get_indexes(table_name)

            # Mapping of primary key columns
            primary_keys = set(pk_constraint.get("constrained_columns", []))
            # Mapping for unique columns (simplified, considering only unique indexes, not unique constraints)
            unique_columns = {
                index["column_names"][0]
                for index in indexes
                if index["unique"] and len(index["column_names"]) == 1
            }

            table_schema: dict[str, FieldSchema] = {}
            for column_info in columns_info:
                column_name = column_info["name"]
                foreign_key = None
                for fk_constraint in fk_constraints:
                    if column_name in fk_constraint.get("constrained_columns", []):
                        # Simplified representation of foreign key as 'referenced_table(referenced_column)'
                        ref_table = fk_constraint["referred_table"]
                        ref_column = (
                            fk_constraint["referred_columns"][0]
                            if fk_constraint["referred_columns"]
                            else None
                        )
                        foreign_key = (
                            f"{ref_table}({ref_column})" if ref_column else ref_table
                        )
                        break

                field_schema = FieldSchema(
                    name=column_name,
                    type=column_info["type"].__str__(),
                    primary_key=column_name in primary_keys,
                    nullable=column_info["nullable"],
                    foreign_key=foreign_key,
                    unique=column_name in unique_columns,
                )

                table_schema[column_name] = field_schema

            tables_schema[table_name] = TableSchema(
                name=table_name, fields=table_schema
            )

        return tables_schema

    def compare_schemas(
        self, db_schema: dict[str, TableSchema], model_schema: dict[str, TableSchema]
    ):
        discrepancies = defaultdict(list)

        # Check for tables missing in the database
        for table in model_schema:
            if table not in db_schema:
                discrepancies[table].append("Missing table in database")
                continue  # No need to compare fields if the table is missing

        for table, model_fields in model_schema.items():
            LOGGER.info(f"Comparing {table}")
            db_fields = db_schema.get(table)

            for field_name, model_field in model_fields.fields.items():
                LOGGER.info(f"Comparing {table}.{field_name}")
                db_field = db_fields.fields.get(field_name) if db_fields else None

                # Field missing in the database
                if not db_field:
                    discrepancies[f"{table}.{field_name}"].append(
                        "Missing field in database"
                    )
                    continue

                # Compare field type
                if model_field.type != db_field.type:
                    discrepancies[f"{table}.{field_name}"].append(
                        f"Type mismatch (Model: {model_field.type}, DB: {db_field.type})"
                    )

                # Compare primary key status
                if model_field.primary_key != db_field.primary_key:
                    discrepancies[f"{table}.{field_name}"].append(
                        f"Primary key mismatch (Model: {model_field.primary_key}, DB: {db_field.primary_key})"
                    )

                # Compare nullable status
                if model_field.nullable != db_field.nullable:
                    discrepancies[f"{table}.{field_name}"].append(
                        f"Nullable mismatch (Model: {model_field.nullable}, DB: {db_field.nullable})"
                    )

                # Compare unique constraint status
                if model_field.unique != db_field.unique:
                    discrepancies[f"{table}.{field_name}"].append(
                        f"Unique constraint mismatch (Model: {model_field.unique}, DB: {db_field.unique})"
                    )

                # Compare foreign keys
                if model_field.foreign_key != db_field.foreign_key:
                    discrepancies[f"{table}.{field_name}"].append(
                        f"Foreign key mismatch (Model: {model_field.foreign_key}, DB: {db_field.foreign_key})"
                    )

        # Check for fields in DB not present in model
        for table, db_fields in db_schema.items():
            if table in model_schema:  # Only check if table is expected to exist
                for field_name in db_fields.fields:
                    if field_name not in model_schema[table].fields:
                        discrepancies[f"{table}.{field_name}"].append(
                            "Extra field in database"
                        )

        return discrepancies
