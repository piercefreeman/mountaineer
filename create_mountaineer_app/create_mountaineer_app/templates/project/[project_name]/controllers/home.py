{% if create_stub_files %}
from mountaineer import APIException, ControllerBase, Metadata, RenderBase, sideeffect
from iceaxe.mountaineer import DatabaseDependencies
from iceaxe import DBConnection, select

from fastapi import Depends

from {{project_name}} import models


class HomeRender(RenderBase):
    items: list[models.DetailItem]
    setup_required: bool = False
    setup_instructions: str | None = None


class DatabaseSetupRequired(APIException):
    status_code = 503
    detail = (
        "Database tables are not initialized. "
        "Run `migrate generate --message init` and `migrate apply`, "
        "or run `createdb` for a one-shot bootstrap."
    )


def _iter_exception_chain(error: Exception):
    current = error
    while current:
        yield current
        current = current.__cause__ or current.__context__


def _is_missing_table_error(error: Exception):
    for inner_error in _iter_exception_chain(error):
        if getattr(inner_error, "sqlstate", None) == "42P01":
            return True

        if "undefinedtable" in type(inner_error).__name__.lower():
            return True

        message = str(inner_error).lower()
        if "relation" in message and "does not exist" in message:
            return True

    return False


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    async def render(
        self,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> HomeRender:
        setup_required = False
        setup_instructions = None

        try:
            items = await session.exec(select(models.DetailItem))
        except Exception as error:
            if not _is_missing_table_error(error):
                raise

            setup_required = True
            setup_instructions = (
                "Database tables were not found. "
                "Run `migrate generate --message init` and `migrate apply`, "
                "or run `createdb` for a one-shot bootstrap."
            )
            items = []

        return HomeRender(
            items=items,
            setup_required=setup_required,
            setup_instructions=setup_instructions,
            metadata=Metadata(title="Home"),
        )

    @sideeffect
    async def new_detail(
        self,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> None:
        try:
            obj = models.DetailItem(description="Untitled Item")
            await session.insert([obj])
        except Exception as error:
            if _is_missing_table_error(error):
                raise DatabaseSetupRequired()

            raise
{% endif %}
