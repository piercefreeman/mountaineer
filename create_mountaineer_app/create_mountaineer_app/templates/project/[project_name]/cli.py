from click import command, option, group
from mountaineer.cli import handle_runserver, handle_watch, handle_build
from mountaineer.io import async_to_sync
from mountaineer.dependencies import get_function_dependencies
from mountaineer import Depends, CoreDependencies

from iceaxe import DBConnection
{% if create_stub_files %}
from iceaxe import select
{% endif %}
from iceaxe.migrations.cli import handle_apply, handle_generate, handle_rollback
from iceaxe.mountaineer import DatabaseDependencies
from iceaxe.schemas.cli import create_all

from {{project_name}} import models as models  # noqa: F401
from {{project_name}}.config import AppConfig

{% if create_stub_files %}

async def seed_starter_data(db_connection: DBConnection):
    existing_items = await db_connection.exec(select(models.DetailItem).limit(1))
    if existing_items:
        return

    await db_connection.insert(
        [
            models.DetailItem(description="Explore the generated Mountaineer app"),
            models.DetailItem(description="Edit this item from the detail page"),
            models.DetailItem(description="Add a new item from the home page"),
        ]
    )
{% endif %}


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
        {% if create_stub_files %}
        await seed_starter_data(db_connection)
        {% endif %}

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
