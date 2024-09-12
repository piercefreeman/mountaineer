import re

from sqlalchemy import text
from sqlalchemy.engine.result import Result

from mountaineer.database.session import AsyncSession
from mountaineer.io import lru_cache_async
from mountaineer.migrations.actions import (
    CheckConstraint,
    ColumnType,
    ConstraintType,
    ForeignKeyConstraint,
)
from mountaineer.migrations.db_stubs import (
    DBColumn,
    DBColumnPointer,
    DBConstraint,
    DBObject,
    DBTable,
    DBType,
    DBTypePointer,
)


class DatabaseSerializer:
    """
    Convert the current database state to the intermediary DBObject representations that
    represent its current configuration properties. Used for introspection
    and comparison to the in-code definitions.

    """

    def __init__(self):
        # Internal tables used for migration management, shouldn't be managed in-memory and therefore
        # won't be mirrored by our DBMemorySerializer. We exclude them from this serialization lest there
        # be a detected conflict and we try to remove the migration metadata.
        self.ignore_tables = ["migration_info"]

    async def get_objects(self, session: AsyncSession):
        tables = []
        async for table, dependencies in self.get_tables(session):
            tables.append(table)
            yield table, dependencies

        for table in tables:
            async for column, dependencies in self.get_columns(
                session, table.table_name
            ):
                yield column, dependencies + [table]

            async for constraint, dependencies in self.get_constraints(
                session, table.table_name
            ):
                yield constraint, dependencies + [table]

            async for constraint, dependencies in self.get_indexes(
                session, table.table_name
            ):
                yield constraint, dependencies + [table]

    async def get_tables(self, session: AsyncSession):
        result: Result = await session.exec(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        )

        for row in result.fetchall():
            if row.table_name in self.ignore_tables:
                continue
            yield DBTable(table_name=row.table_name), []

    async def get_columns(self, session: AsyncSession, table_name: str):
        query = text(
            """
            SELECT
                cols.column_name,
                cols.udt_name,
                cols.data_type,
                cols.is_nullable,
                CASE
                    WHEN cols.data_type = 'ARRAY' THEN elem_type.data_type
                    ELSE NULL
                END AS element_type
            FROM information_schema.columns AS cols
            LEFT JOIN information_schema.element_types AS elem_type
                ON cols.table_catalog = elem_type.object_catalog
                AND cols.table_schema = elem_type.object_schema
                AND cols.table_name = elem_type.object_name
                AND cols.dtd_identifier = elem_type.collection_type_identifier
            WHERE cols.table_name = :table_name
                AND cols.table_schema = 'public';

        """
        )
        result = await session.exec(query, params={"table_name": table_name})

        column_dependencies: list[DBObject] = []

        for row in result.fetchall():
            column_is_list = False

            if row.data_type == "USER-DEFINED":
                column_type, column_type_deps = await self.fetch_custom_type(
                    session, row.udt_name
                )
                column_dependencies.append(column_type)
                yield column_type, column_type_deps
            elif row.data_type == "ARRAY":
                column_is_list = True
                column_type = ColumnType(row.element_type)
            else:
                column_type = ColumnType(row.data_type)

            yield (
                DBColumn(
                    table_name=table_name,
                    column_name=row.column_name,
                    column_type=(
                        DBTypePointer(name=column_type.name)
                        if isinstance(column_type, DBType)
                        else column_type
                    ),
                    column_is_list=column_is_list,
                    nullable=(row.is_nullable == "YES"),
                ),
                column_dependencies,
            )

    async def get_constraints(self, session: AsyncSession, table_name: str):
        query = text(
            """
            SELECT conname, contype, conrelid, confrelid, conkey, confkey
            FROM pg_constraint
            INNER JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
            WHERE pg_class.relname = :table_name
        """
        )
        result = await session.exec(query, params={"table_name": table_name})
        for row in result.fetchall():
            contype = (
                row.contype.decode() if isinstance(row.contype, bytes) else row.contype
            )
            # Determine type
            if contype == "p":
                ctype = ConstraintType.PRIMARY_KEY
            elif contype == "f":
                ctype = ConstraintType.FOREIGN_KEY
            elif contype == "u":
                ctype = ConstraintType.UNIQUE
            elif contype == "c":
                ctype = ConstraintType.CHECK
            else:
                raise ValueError(f"Unknown constraint type: {row.contype}")

            columns = await self.fetch_constraint_columns(
                session, row.conkey, table_name
            )

            # Handle foreign key specifics
            fk_constraint: ForeignKeyConstraint | None = None
            check_constraint: CheckConstraint | None = None

            if ctype == ConstraintType.FOREIGN_KEY:
                # Fetch target table
                fk_query = text("SELECT relname FROM pg_class WHERE oid = :oid")
                fk_result = await session.exec(fk_query, params={"oid": row.confrelid})
                target_table = fk_result.scalar_one()

                # Fetch target columns
                target_columns_query = text(
                    """
                    SELECT a.attname
                    FROM pg_attribute a
                    WHERE a.attrelid = :oid AND a.attnum = ANY(:conkey)
                """
                )
                target_columns_result = await session.exec(
                    target_columns_query,
                    params={"oid": row.confrelid, "conkey": row.confkey},
                )
                target_columns = {row[0] for row in target_columns_result}

                fk_constraint = ForeignKeyConstraint(
                    target_table=target_table, target_columns=frozenset(target_columns)
                )
            elif ctype == ConstraintType.CHECK:
                # Retrieve the check constraint expression
                check_query = text(
                    """
                    SELECT pg_get_constraintdef(c.oid) AS consrc
                    FROM pg_constraint c
                    WHERE c.oid = :oid
                    """
                )
                check_result = await session.exec(check_query, params={"oid": row.oid})
                check_constraint_expr = check_result.scalar_one()

                check_constraint = CheckConstraint(
                    check_condition=check_constraint_expr,
                )

            yield (
                DBConstraint(
                    table_name=table_name,
                    constraint_name=row.conname,
                    columns=frozenset(columns),
                    constraint_type=ctype,
                    foreign_key_constraint=fk_constraint,
                    check_constraint=check_constraint,
                ),
                [
                    # We require the columns to be created first
                    DBColumnPointer(table_name=table_name, column_name=column)
                    for column in columns
                ],
            )

    async def get_indexes(self, session: AsyncSession, table_name: str):
        # Query for indexes, excluding primary keys
        index_query = text(
            """
            SELECT i.indexname, i.indexdef
            FROM pg_indexes i
            LEFT JOIN pg_constraint c ON c.conname = i.indexname
            WHERE i.tablename = :table_name
            AND c.conname IS NULL
            AND i.indexdef NOT ILIKE '%UNIQUE INDEX%'
        """
        )
        index_result = await session.exec(
            index_query, params={"table_name": table_name}
        )

        for row in index_result:
            index_name = row.indexname
            index_def = row.indexdef

            # Extract columns from index definition
            columns_match = re.search(r"\((.*?)\)", index_def)
            if columns_match:
                # Reserved names are quoted in the response body
                columns = [
                    col.strip().strip('"') for col in columns_match.group(1).split(",")
                ]
            else:
                columns = []

            yield (
                DBConstraint(
                    table_name=table_name,
                    columns=frozenset(columns),
                    constraint_name=index_name,
                    constraint_type=ConstraintType.INDEX,
                ),
                [
                    DBColumnPointer(table_name=table_name, column_name=column)
                    for column in columns
                ],
            )

    async def fetch_constraint_columns(self, session: AsyncSession, conkey, table_name):
        # Assume conkey is a list of column indices; this function would fetch actual column names
        query = text(
            "SELECT attname FROM pg_attribute WHERE attnum = ANY(:conkey) AND attrelid = (SELECT oid FROM pg_class WHERE relname = :table_name)"
        )
        result = await session.exec(
            query, params={"conkey": conkey, "table_name": table_name}
        )
        return list(result.scalars().all())

    # Enum values are not expected to change within one session, cache the same
    # type if we see it within the same session
    @lru_cache_async(maxsize=None)
    async def fetch_custom_type(self, session: AsyncSession, type_name: str):
        # Get the values in this enum
        values_query = text(
            """
        SELECT enumlabel
        FROM pg_enum
        JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
        WHERE pg_type.typname = :type_name
        """
        )
        values_result = await session.exec(
            values_query, params={"type_name": type_name}
        )
        values = frozenset(values_result.scalars().all())

        # Determine all the columns where this type is referenced
        reference_columns_query = text(
            """
            SELECT
                n.nspname AS schema_name,
                c.relname AS table_name,
                a.attname AS column_name
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            JOIN pg_catalog.pg_attribute a ON a.atttypid = t.oid
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            WHERE
                t.typname = :type_name
                AND a.attnum > 0
                AND NOT a.attisdropped;
            """
        )
        reference_columns_results = await session.exec(
            reference_columns_query, params={"type_name": type_name}
        )
        reference_columns = frozenset(
            {
                (row.table_name, row.column_name)
                for row in reference_columns_results.fetchall()
            }
        )
        return DBType(
            name=type_name, values=values, reference_columns=reference_columns
        ), []
