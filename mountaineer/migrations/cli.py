from inspect import isclass
from time import monotonic_ns

from fastapi import Depends
from sqlalchemy.orm import mapperlib
from sqlmodel import SQLModel

from mountaineer import CoreDependencies
from mountaineer.config import ConfigBase
from mountaineer.console import CONSOLE
from mountaineer.database import DatabaseDependencies
from mountaineer.database.config import DatabaseConfig
from mountaineer.database.session import AsyncSession
from mountaineer.dependencies import get_function_dependencies
from mountaineer.migrations.client_io import fetch_migrations, sort_migrations
from mountaineer.migrations.db_serializer import DatabaseSerializer
from mountaineer.migrations.generator import MigrationGenerator
from mountaineer.migrations.migrator import Migrator
from mountaineer.paths import resolve_package_path


async def handle_generate(message: str | None = None):
    """
    Creates a new migration definition file, comparing the previous version
    (if it exists) with the current schema.

    """

    async def generate_migration(
        config: DatabaseConfig = Depends(
            CoreDependencies.get_config_with_type(DatabaseConfig)
        ),
        db_session: AsyncSession = Depends(DatabaseDependencies.get_db_session),
    ):
        assert isinstance(config, ConfigBase)
        if not config.PACKAGE:
            raise ValueError(
                "PACKAGE must be set in the config to generate a new migration."
            )

        CONSOLE.print(
            f"Reference db: {config.POSTGRES_USER}@{config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}"
        )

        # Locate the migrations directory that belongs to this project
        package_path = resolve_package_path(config.PACKAGE)
        migrations_path = package_path / "migrations"

        # Create the path if it doesn't exist
        migrations_path.mkdir(exist_ok=True)
        if not (migrations_path / "__init__.py").exists():
            (migrations_path / "__init__.py").touch()

        # Get all of the SQLModel instances that have been registered
        # in memory scope by the user.
        models = [
            cls
            for obj in mapperlib._mapper_registries
            for cls in obj._class_registry.values()
            if isclass(cls) and issubclass(cls, SQLModel)
        ]

        db_serializer = DatabaseSerializer()
        db_objects = []
        async for values in db_serializer.get_objects(db_session):
            db_objects.append(values)

        migration_generator = MigrationGenerator()
        up_objects = list(migration_generator.serializer.delegate(models, context=None))

        # Get the current revision from the database, this should represent the "down" revision
        # for the new migration
        migrator = Migrator(db_session)
        await migrator.init_db()
        current_revision = await migrator.get_active_revision()

        # Make sure there's not a duplicate revision that already have this down revision. If so that means
        # that we will have two conflicting migration chains
        migration_revisions = fetch_migrations(migrations_path)
        conflict_migrations = [
            migration
            for migration in migration_revisions
            if migration.down_revision == current_revision
        ]
        if conflict_migrations:
            up_revisions = {migration.up_revision for migration in conflict_migrations}
            raise ValueError(
                f"Found conflicting migrations with down revision {current_revision} (conflicts: {up_revisions}).\n"
                "If you're trying to generate a new migration, make sure to apply the previous migration first - or delete the old one and recreate."
            )

        migration_code, revision = await migration_generator.new_migration(
            db_objects,
            up_objects,
            down_revision=current_revision,
            user_message=message,
        )

        # Create the migration file. The change of a conflict with this timestamp is very low, but we make sure
        # not to override any existing files anyway.
        migration_file_path = migrations_path / f"rev_{revision}.py"
        if migration_file_path.exists():
            raise ValueError(
                f"Migration file {migration_file_path} already exists. Wait a second and try again."
            )

        migration_file_path.write_text(migration_code)
        return migration_file_path

    CONSOLE.print("[bold blue]Generating migration to current schema")

    CONSOLE.print(
        "[grey58]Note that Mountaineer's migration support is well tested but still in beta."
    )
    CONSOLE.print(
        "[grey58]File an issue @ https://github.com/piercefreeman/mountaineer/issues if you encounter any problems."
    )

    async with get_function_dependencies(callable=generate_migration) as values:
        migration_file_path = await generate_migration(**values)

    CONSOLE.print(f"[bold green]New migration added: {migration_file_path.name}")


async def handle_apply():
    """
    Applies all migrations that have not been applied to the database.

    """

    async def apply_migration(
        # This db session is just for initial metadata lookup, the actual migrations will be run in
        # their own separate session context
        db_session: AsyncSession = Depends(DatabaseDependencies.get_db_session),
        config: ConfigBase = Depends(CoreDependencies.get_config_with_type(ConfigBase)),
    ):
        assert isinstance(config, ConfigBase)
        if not config.PACKAGE:
            raise ValueError("PACKAGE must be set in the config to apply migrations.")

        migrations_path = resolve_package_path(config.PACKAGE) / "migrations"
        if not migrations_path.exists():
            raise ValueError(f"Migrations path {migrations_path} does not exist.")

        # Load all the migration files into memory and locate the subclasses of MigrationRevisionBase
        migration_revisions = fetch_migrations(migrations_path)
        migration_revisions = sort_migrations(migration_revisions)

        # Get the current revision from the database
        migrator = Migrator(db_session)
        await migrator.init_db()
        current_revision = await migrator.get_active_revision()

        CONSOLE.print(f"Current revision: {current_revision}")

        # Find the item in the sequence that has down_revision equal to the current_revision
        # This indicates the next migration to apply
        next_migration_index = None
        for i, revision in enumerate(migration_revisions):
            if revision.down_revision == current_revision:
                next_migration_index = i
                break

        if next_migration_index is None:
            raise ValueError(
                f"Could not find a migration to apply after revision {current_revision}."
            )

        # Get the chain after this index, this should indicate the next migration to apply
        migration_chain = migration_revisions[next_migration_index:]
        CONSOLE.print(f"Applying {len(migration_chain)} migrations...")

        for migration in migration_chain:
            with CONSOLE.status(
                f"[bold blue]Applying {migration.up_revision}...", spinner="dots"
            ):
                start = monotonic_ns()
                await migration.handle_up()

            CONSOLE.print(
                f"[bold green]🚀 Applied {migration.up_revision} in {(monotonic_ns() - start) / 1e9:.2f}s"
            )

    async with get_function_dependencies(callable=apply_migration) as values:
        await apply_migration(**values)


async def handle_rollback():
    """
    Rolls back the last migration that was applied to the database.

    """

    async def apply_migration(
        db_session: AsyncSession = Depends(DatabaseDependencies.get_db_session),
        config: ConfigBase = Depends(CoreDependencies.get_config_with_type(ConfigBase)),
    ):
        if not config.PACKAGE:
            raise ValueError("PACKAGE must be set in the config to apply migrations.")

        migrations_path = resolve_package_path(config.PACKAGE) / "migrations"
        if not migrations_path.exists():
            raise ValueError(f"Migrations path {migrations_path} does not exist.")

        # Load all the migration files into memory and locate the subclasses of MigrationRevisionBase
        migration_revisions = fetch_migrations(migrations_path)
        migration_revisions = sort_migrations(migration_revisions)

        # Get the current revision from the database
        migrator = Migrator(db_session)
        await migrator.init_db()
        current_revision = await migrator.get_active_revision()

        CONSOLE.print(f"Current revision: {current_revision}")

        # Find the item in the sequence that has down_revision equal to the current_revision
        # This indicates the next migration to apply
        this_migration_index = None
        for i, revision in enumerate(migration_revisions):
            if revision.up_revision == current_revision:
                this_migration_index = i
                break

        if this_migration_index is None:
            raise ValueError(
                f"Could not find a migration matching {current_revision} for rollback."
            )

        # Get the chain after this index, this should indicate the next migration to apply
        this_migration = migration_revisions[this_migration_index]

        with CONSOLE.status(
            f"[bold blue]Rolling back revision {this_migration.up_revision} to {this_migration.down_revision}...",
            spinner="dots",
        ):
            start = monotonic_ns()
            await this_migration.handle_down()

        CONSOLE.print(
            f"[bold green]🪃 Rolled back migration to {this_migration.down_revision} in {(monotonic_ns() - start) / 1e9:.2f}s"
        )

    async with get_function_dependencies(callable=apply_migration) as values:
        await apply_migration(**values)
