from click import command, option, group
from mountaineer.cli import handle_runserver, handle_watch, handle_build
from mountaineer.database.cli import handle_createdb
from mountaineer.io import async_to_sync
from mountaineer.migrations.cli import handle_apply, handle_generate, handle_rollback

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
    _ = AppConfig() # type: ignore
    await handle_createdb(models)


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
