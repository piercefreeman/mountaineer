# Database Migrations

!!! warning

    This feature is experimental. Explore using it while developing locally but make sure to backup your data before applying changes. It should support all SQLModel definitions, but if you encounter a bug or lack of support, please report it so we can improve the test coverage.

## Overview

Once your application is in production, you'll need some method of updating your database schema as you update your application's functionality. You _could_ write raw SQL to accomplish these migrations, or manually modify database table definitions. But the former is inconvenient and the second is risky. Mountaineer ships with a migration tool that can automatically generate migration files for you and apply them to your database. Its features:

- Fast with no external dependencies outside of Mountaineer core.
- Zero config required, optional programmatic customization.
- Unit-testable migration paths that work with normal `pytest` harnesses.
- Baked-in support for common Postgres types that overlap with Python, most specifically Enums and datetimes.
- File-based groundtruth of migration logic, so it can be audited in source control and customized by you.
- Simple API surface, with atomic Python functions that perform the most common migration operations. Direct database queries (or integration with ORM objects in limited cases) can be used for more complex migration logic.

## Project Integration

Following the current standard for Mountaineer CLI integrations, we require client applications to explicitly define their CLI endpoints. We include basic handlers for import in `mountaineer.migrations.cli`. This should look very similar to the default handlers for `runserver` and `build`.

You can integrate like so in your CLI file:

```python title="myapp/cli.py"
from click import group, option

from mountaineer.io import async_to_sync
from mountaineer.migrations.cli import handle_apply, handle_generate, handle_rollback
from myapp.config import AppConfig

@group
def migrate():
    pass

@migrate.command()
@option("--message", required=False)
@async_to_sync
async def generate(message: str | None):
    _ = AppConfig()  # type: ignore
    await handle_generate(message=message)

@migrate.command()
@async_to_sync
async def apply():
    _ = AppConfig()  # type: ignore
    await handle_apply()

@migrate.command()
@async_to_sync
async def rollback():
    _ = AppConfig()  # type: ignore
    await handle_rollback()
```

Also modify your project's pyproject.toml file.

```toml title="pyproject.toml"
[tool.poetry.scripts]
migrate = "myapp.cli:migrate"
```

### Generate

```bash
$ poetry run migrate generate --message "Add author column to article"
```

Generate a migration file, to update the database schema to the ones defined in your code.

### Apply

```bash
$ poetry run migrate apply
```

Apply all migration files that have not been applied to the database.

### Rollback

```bash
$ poetry run migrate rollback
```

Rollback the last migration that was applied to the database.

## Migration files

All data changes live in separate migration files. You can generate them through the Mountaineer CLI and modify them as you need to handle your data migrations.

The goal of a migration file is to determine the goal database state (ie. what you current have in code). It then figures out how to transition the current database state to the new goal state. As such, before generating your migration file, make sure your local database has the same schema configuration as your production database. Otherwise your migration files might be incorrect and not apply properly.

```bash
poetry run migrate generate --message "Add author column to article"
```

The created migration will be placed into `myapp/migrations` and include a unix timestamp of when the migration was created. Since most IDEs will sort directories by integer value, you can look towards the bottom of your migrations directory to see the most recent migration that will be run.

```python
from mountaineer.migrations.migrator import Migrator
from mountaineer.migrations.migration import MigrationRevisionBase
from mountaineer.migrations.dependency import MigrationDependencies
from fastapi.param_functions import Depends

class MigrationRevision(MigrationRevisionBase):
    up_revision: str = "1715044020"
    down_revision: str | None = None

    async def up(
        self,
        migrator: Migrator = Depends(MigrationDependencies.get_migrator),
    ):
        await migrator.actor.add_not_null(
            table_name="article",
            column_name="author"
        )

    async def down(
        self,
        migrator: Migrator = Depends(MigrationDependencies.get_migrator),
    ):
        await migrator.actor.drop_not_null(
            table_name="article",
            column_name="author"
        )
```

Let's break down the migration file that was just generated:

There's an `up` function that covers the migration to the new application state. These are standard dependency injection functions, so you can use any dependency injector in your application if you want to inject other variables. By default we just supply the migrator: Migrator which is a shallow wrapper that provides a database session (with an open connection) alongside an actor object that includes some common migration recipes.

The `down` function does the inverse. It takes the database state after your migration has been run and downgrades it to the last version. It's useful to have this specified in case you need to rollback your migration to conform to the previously deployed service. This often requires some care at considering how you can safely rollback your migration, perhaps through keeping temporary columns around inbetween migrations that you know you might have to rollback.

The `up_revision` and `down_revision` are used to track the migration state. The `up_revision` is the timestamp of the migration file, and the `down_revision` is the timestamp of the previous migration file. If you don't have a down revision, it will be set to `None`. These will be injected into a dynamic "migration_info" table in your database to track the current state of your migrations.

## Extending Migration Files

The `Migrator` object is a thin wrapper around the `DatabaseActions` object, which is a collection of common migration operations. If you need to perform a more complex migration operation, you can customize the logic by calling `migrator.actor` yourself. Head over to the [DatabaseActions documentation](./api/database/migrations.md) to see the full list of available migration operations.

In addition to the actor, you can also access the underlying database session object. This is useful if you need to run raw SQL queries that aren't covered by the actor object.

```python
async def up(
    self,
    migrator: Migrator = Depends(MigrationDependencies.get_migrator),
):
    result = await migrator.db_session.exec("SELECT * FROM article")
```

We recommend using the actor object whenever possible, as it provides a more consistent and safe way to run migrations. If you are using the raw database session object, be aware that we require migrations to be run in a single transaction. This ensures that if a migration fails, the database will be rolled back to its previous state. We therefore disable calling `db_session.commit()` explicitly from within user code.

## Alternatives

While the Mountaineer core authors only support its native migration workflow, since the database primitives build off of SQLModel/SQLAlchemy there are other options in the ecosystem for migration generation.

The industry standard migration package for SQLAlchemy is Alembic, which is a powerful and robust file-based migration library. A quick list of pros and our perceived cons:

Pros:

- Mature project with a large user base and extensive documentation.
- It has a rich feature set, including support for multiple database backends and complex migration operations.

Cons:

- Non-trivial setup complexity with configuration files and a separate CLI.
- In steady state it's sometimes unclear what migration responsibility Alembic owns, versus what should be delegated to SQLAlchemy.
