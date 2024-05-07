from sqlalchemy import text
from sqlalchemy.engine.result import Result
from sqlalchemy.ext.asyncio import AsyncSession

from mountaineer.migrations.actions import (
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

    async def get_tables(self, session: AsyncSession):
        result: Result = await session.execute(
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
        result = await session.execute(query, {"table_name": table_name})

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
                    column_type=column_type,
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
        result = await session.execute(query, {"table_name": table_name})
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
            fk_constraint = None
            if ctype == ConstraintType.FOREIGN_KEY:
                # Fetch target table
                fk_query = text("SELECT relname FROM pg_class WHERE oid = :oid")
                fk_result = await session.execute(fk_query, {"oid": row.confrelid})
                target_table = fk_result.scalar_one()

                # Fetch target columns
                target_columns_query = text(
                    """
                    SELECT a.attname
                    FROM pg_attribute a
                    WHERE a.attrelid = :oid AND a.attnum = ANY(:conkey)
                """
                )
                target_columns_result = await session.execute(
                    target_columns_query, {"oid": row.confrelid, "conkey": row.confkey}
                )
                target_columns = {row[0] for row in target_columns_result}

                fk_constraint = ForeignKeyConstraint(
                    target_table=target_table, target_columns=frozenset(target_columns)
                )

            yield (
                DBConstraint(
                    table_name=table_name,
                    constraint_name=row.conname,
                    columns=frozenset(columns),
                    constraint_type=ctype,
                    foreign_key_constraint=fk_constraint,
                ),
                [
                    # We require the columns to be created first
                    DBColumnPointer(table_name=table_name, column_name=column)
                    for column in columns
                ],
            )

    async def fetch_constraint_columns(self, session: AsyncSession, conkey, table_name):
        # Assume conkey is a list of column indices; this function would fetch actual column names
        query = text(
            "SELECT attname FROM pg_attribute WHERE attnum = ANY(:conkey) AND attrelid = (SELECT oid FROM pg_class WHERE relname = :table_name)"
        )
        result = await session.execute(
            query, {"conkey": conkey, "table_name": table_name}
        )
        return list(result.scalars().all())

    async def fetch_custom_type(self, session: AsyncSession, type_name: str):
        query = text(
            """
        SELECT enumlabel
        FROM pg_enum
        JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
        WHERE pg_type.typname = :type_name
        """
        )
        result = await session.execute(query, {"type_name": type_name})
        values = frozenset(result.scalars().all())
        return DBType(name=type_name, values=values), []
