from inspect import isclass
from time import monotonic_ns
from typing import cast

from click import command, option, group
from mountaineer.cli import handle_runserver, handle_watch, handle_build
from mountaineer.io import async_to_sync
from mountaineer.dependencies import get_function_dependencies
from mountaineer import Depends, CoreDependencies

from iceaxe import DBConnection
from iceaxe.base import DBModelMetaclass, TableBase
from iceaxe.io import resolve_package_path
from iceaxe.logging import CONSOLE
from iceaxe.mountaineer import DatabaseDependencies
from iceaxe.postgres import ForeignKeyModifications
from iceaxe.schemas.actions import (
    CheckConstraint,
    ConstraintType,
    ForeignKeyConstraint,
)
from iceaxe.schemas.cli import create_all
from iceaxe.schemas.db_serializer import DatabaseSerializer
from iceaxe.schemas.db_stubs import DBColumnPointer, DBConstraint

from {{project_name}} import models as models  # noqa: F401
from {{project_name}}.config import AppConfig


class MigrationDatabaseSerializer(DatabaseSerializer):
    """
    Iceaxe tracks nullability from information_schema.columns, so PostgreSQL 18
    NOT NULL pg_constraint rows should not be serialized as separate constraints.
    """

    async def get_constraints(self, session: DBConnection, table_name: str):
        query = """
            SELECT
                pg_constraint.oid,
                conname,
                contype,
                conrelid,
                confrelid,
                conkey,
                confkey,
                confupdtype,
                confdeltype
            FROM pg_constraint
            INNER JOIN pg_class ON pg_constraint.conrelid = pg_class.oid
            WHERE pg_class.relname = $1
                AND pg_constraint.contype <> 'n'
        """
        result = await session.conn.fetch(query, table_name)
        for row in result:
            contype = self._unwrap_db_str(row["contype"])
            if contype == "p":
                ctype = ConstraintType.PRIMARY_KEY
            elif contype == "f":
                ctype = ConstraintType.FOREIGN_KEY
            elif contype == "u":
                ctype = ConstraintType.UNIQUE
            elif contype == "c":
                ctype = ConstraintType.CHECK
            else:
                raise ValueError(f"Unknown constraint type: {row['contype']}")

            columns = await self.fetch_constraint_columns(
                session, row["conkey"], table_name
            )

            fk_constraint: ForeignKeyConstraint | None = None
            check_constraint: CheckConstraint | None = None

            if ctype == ConstraintType.FOREIGN_KEY:
                fk_query = "SELECT relname FROM pg_class WHERE oid = $1"
                fk_result = await session.conn.fetch(fk_query, row["confrelid"])
                target_table = fk_result[0]["relname"]

                target_columns_query = """
                    SELECT a.attname AS column_name
                    FROM pg_attribute a
                    WHERE a.attrelid = $1 AND a.attnum = ANY($2)
                """
                target_columns_result = await session.conn.fetch(
                    target_columns_query,
                    row["confrelid"],
                    row["confkey"],
                )
                target_columns = {row["column_name"] for row in target_columns_result}

                action_map = {
                    "a": "NO ACTION",
                    "r": "RESTRICT",
                    "c": "CASCADE",
                    "n": "SET NULL",
                    "d": "SET DEFAULT",
                }
                on_update = action_map.get(
                    self._unwrap_db_str(row["confupdtype"]),
                    "NO ACTION",
                )
                on_delete = action_map.get(
                    self._unwrap_db_str(row["confdeltype"]),
                    "NO ACTION",
                )

                fk_constraint = ForeignKeyConstraint(
                    target_table=target_table,
                    target_columns=frozenset(target_columns),
                    on_delete=cast(ForeignKeyModifications, on_delete),
                    on_update=cast(ForeignKeyModifications, on_update),
                )
            elif ctype == ConstraintType.CHECK:
                check_query = """
                    SELECT pg_get_constraintdef(c.oid) AS consrc
                    FROM pg_constraint c
                    WHERE c.oid = $1
                    """
                check_result = await session.conn.fetch(check_query, row["oid"])
                check_constraint = CheckConstraint(
                    check_condition=check_result[0]["consrc"],
                )

            yield (
                DBConstraint(
                    table_name=table_name,
                    constraint_name=row["conname"],
                    columns=frozenset(columns),
                    constraint_type=ctype,
                    foreign_key_constraint=fk_constraint,
                    check_constraint=check_constraint,
                ),
                [
                    DBColumnPointer(table_name=table_name, column_name=column)
                    for column in columns
                ],
            )


async def handle_generate(
    package: str,
    db_connection: DBConnection,
    message: str | None = None,
    ignore_tables: list[str] | None = None,
):
    from iceaxe.migrations.client_io import fetch_migrations
    from iceaxe.migrations.generator import MigrationGenerator
    from iceaxe.migrations.migrator import Migrator

    CONSOLE.print("[bold blue]Generating migration to current schema")
    CONSOLE.print(
        "[grey58]Note that Iceaxe's migration support is well tested but still in beta."
    )
    CONSOLE.print(
        "[grey58]File an issue @ https://github.com/piercefreeman/iceaxe/issues if you encounter any problems."
    )

    package_path = resolve_package_path(package)
    migrations_path = package_path / "migrations"
    migrations_path.mkdir(exist_ok=True)
    if not (migrations_path / "__init__.py").exists():
        (migrations_path / "__init__.py").touch()

    ignore_tables_set = set(ignore_tables or [])
    registered_models = [
        cls
        for cls in DBModelMetaclass.get_registry()
        if isclass(cls)
        and issubclass(cls, TableBase)
        and cls.get_table_name() not in ignore_tables_set
    ]

    db_serializer = MigrationDatabaseSerializer(ignore_tables=ignore_tables)
    db_objects = []
    async for values in db_serializer.get_objects(db_connection):
        db_objects.append(values)

    migration_generator = MigrationGenerator()
    up_objects = list(migration_generator.serializer.delegate(registered_models))

    migrator = Migrator(db_connection)
    await migrator.init_db()
    current_revision = await migrator.get_active_revision()

    migration_revisions = fetch_migrations(migrations_path)
    conflict_migrations = [
        migration
        for migration in migration_revisions
        if migration.down_revision == current_revision
    ]
    if conflict_migrations:
        up_revisions = {migration.up_revision for migration in conflict_migrations}
        raise ValueError(
            f"Found conflicting migrations with down revision {current_revision} "
            f"(conflicts: {up_revisions}).\n"
            "If you're trying to generate a new migration, make sure to apply the "
            "previous migration first - or delete the old one and recreate."
        )

    migration_code, revision = await migration_generator.new_migration(
        db_objects,
        up_objects,
        down_revision=current_revision,
        user_message=message,
    )

    migration_file_path = migrations_path / f"rev_{revision}.py"
    if migration_file_path.exists():
        raise ValueError(
            f"Migration file {migration_file_path} already exists. Wait a second and try again."
        )

    migration_file_path.write_text(migration_code)
    CONSOLE.print(f"[bold green]New migration added: {migration_file_path.name}")


async def handle_apply(package: str, db_connection: DBConnection):
    from iceaxe.migrations.client_io import fetch_migrations, sort_migrations
    from iceaxe.migrations.migrator import Migrator

    migrations_path = resolve_package_path(package) / "migrations"
    if not migrations_path.exists():
        raise ValueError(f"Migrations path {migrations_path} does not exist.")

    migration_revisions = fetch_migrations(migrations_path)
    migration_revisions = sort_migrations(migration_revisions)

    migrator = Migrator(db_connection)
    await migrator.init_db()
    current_revision = await migrator.get_active_revision()

    CONSOLE.print(f"Current revision: {current_revision}")

    next_migration_index = None
    for index, revision in enumerate(migration_revisions):
        if revision.down_revision == current_revision:
            next_migration_index = index
            break

    if next_migration_index is None:
        raise ValueError(
            f"Could not find a migration to apply after revision {current_revision}."
        )

    migration_chain = migration_revisions[next_migration_index:]
    CONSOLE.print(f"Applying {len(migration_chain)} migrations...")

    for migration in migration_chain:
        with CONSOLE.status(
            f"[bold blue]Applying {migration.up_revision}...",
            spinner="dots",
        ):
            start = monotonic_ns()
            await migration._handle_up(db_connection)

        CONSOLE.print(
            f"[bold green]Applied {migration.up_revision} in "
            f"{(monotonic_ns() - start) / 1e9:.2f}s"
        )


async def handle_rollback(package: str, db_connection: DBConnection):
    from iceaxe.migrations.client_io import fetch_migrations, sort_migrations
    from iceaxe.migrations.migrator import Migrator

    migrations_path = resolve_package_path(package) / "migrations"
    if not migrations_path.exists():
        raise ValueError(f"Migrations path {migrations_path} does not exist.")

    migration_revisions = fetch_migrations(migrations_path)
    migration_revisions = sort_migrations(migration_revisions)

    migrator = Migrator(db_connection)
    await migrator.init_db()
    current_revision = await migrator.get_active_revision()

    CONSOLE.print(f"Current revision: {current_revision}")

    this_migration = None
    for revision in migration_revisions:
        if revision.up_revision == current_revision:
            this_migration = revision
            break

    if this_migration is None:
        raise ValueError(
            f"Could not find a migration matching {current_revision} for rollback."
        )

    with CONSOLE.status(
        "[bold blue]Rolling back revision "
        f"{this_migration.up_revision} to {this_migration.down_revision}...",
        spinner="dots",
    ):
        start = monotonic_ns()
        await this_migration._handle_down(db_connection)

    CONSOLE.print(
        f"[bold green]Rolled back migration to {this_migration.down_revision} in "
        f"{(monotonic_ns() - start) / 1e9:.2f}s"
    )


@command()
@option("--host", default="127.0.0.1", help="Host to run the server on")
@option("--port", default=5006, help="Port to run the server on")
def runserver(host: str, port: int):
    handle_runserver(
        package="{{project_name}}",
        webservice="{{project_name}}.main:app",
        webcontroller="{{project_name}}.app:controller",
        host=host,
        port=port,
    )


@command()
def watch():
    handle_watch(
        package="{{project_name}}",
        webcontroller="{{project_name}}.app:controller",
    )


@command()
def build():
    handle_build(
        webcontroller="{{project_name}}.app:controller",
    )


@command()
@async_to_sync
async def createdb():
    _ = AppConfig()  # type: ignore

    async def run_bootstrap(
        db_connection: DBConnection = Depends(DatabaseDependencies.get_db_connection),
    ):
        await create_all(db_connection=db_connection)

    async with get_function_dependencies(callable=run_bootstrap) as values:
        await run_bootstrap(**values)


@group
def migrate():
    pass


@migrate.command()
@option("--message", required=False)
@option("--ignore-table", "ignore_tables", multiple=True)
@async_to_sync
async def generate(message: str | None, ignore_tables: tuple[str, ...]):
    async def _inner(
        config: AppConfig = Depends(CoreDependencies.get_config_with_type(AppConfig)),
        db_connection: DBConnection = Depends(DatabaseDependencies.get_db_connection),
    ):
        assert config.PACKAGE
        await handle_generate(
            config.PACKAGE,
            db_connection,
            message=message,
            ignore_tables=list(ignore_tables),
        )

    _ = AppConfig()  # type: ignore
    async with get_function_dependencies(callable=_inner) as deps:
        await _inner(**deps)


@migrate.command()
@async_to_sync
async def apply():
    async def _inner(
        config: AppConfig = Depends(CoreDependencies.get_config_with_type(AppConfig)),
        db_connection: DBConnection = Depends(DatabaseDependencies.get_db_connection),
    ):
        assert config.PACKAGE
        await handle_apply(config.PACKAGE, db_connection)

    _ = AppConfig()  # type: ignore
    async with get_function_dependencies(callable=_inner) as deps:
        await _inner(**deps)


@migrate.command()
@async_to_sync
async def rollback():
    async def _inner(
        config: AppConfig = Depends(CoreDependencies.get_config_with_type(AppConfig)),
        db_connection: DBConnection = Depends(DatabaseDependencies.get_db_connection),
    ):
        assert config.PACKAGE
        await handle_rollback(config.PACKAGE, db_connection)

    _ = AppConfig()  # type: ignore
    async with get_function_dependencies(callable=_inner) as deps:
        await _inner(**deps)
