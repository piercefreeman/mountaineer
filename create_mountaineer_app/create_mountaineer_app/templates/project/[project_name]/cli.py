from click import command, option, group
from mountaineer.cli import handle_runserver, handle_watch, handle_build
from mountaineer.io import async_to_sync
from mountaineer.dependencies import get_function_dependencies
from mountaineer import Depends, CoreDependencies

from iceaxe import DBConnection
from iceaxe.mountaineer import DatabaseConfig, DatabaseDependencies
from iceaxe.migrations.cli import handle_apply, handle_generate, handle_rollback
from iceaxe.schemas.cli import create_all

from {{project_name}} import models
from {{project_name}}.config import AppConfig


@command()
@option("--port", default=5006, help="Port to run the server on")
def runserver(port: int):
    handle_runserver(
        package="{{project_name}}",
        webservice="{{project_name}}.main:app",
        webcontroller="{{project_name}}.app:controller",
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
@async_to_sync
async def generate(message: str | None):
    async def _inner(
        config: AppConfig = Depends(CoreDependencies.get_config_with_type(AppConfig)),
        db_connection: DBConnection = Depends(DatabaseDependencies.get_db_connection),
    ):
        assert config.PACKAGE
        await handle_generate(config.PACKAGE, db_connection, message=message)

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
