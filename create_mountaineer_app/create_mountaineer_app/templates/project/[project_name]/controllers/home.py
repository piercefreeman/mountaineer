{% if create_stub_files %}
from mountaineer import sideeffect, ControllerBase, Metadata, RenderBase
from iceaxe.mountaineer import DatabaseDependencies
from iceaxe import DBConnection, select

from fastapi import Depends
from pydantic import Field

from {{project_name}} import models
from {{project_name}}.database_setup import (
    DatabaseSetupRequired,
    get_database_setup_required,
)


class HomeRender(RenderBase):
    items: list[models.DetailItem] = Field(default_factory=list)
    database_setup_required: DatabaseSetupRequired | None = None


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    async def render(
        self,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection),
        database_setup_required: DatabaseSetupRequired
        | None = Depends(get_database_setup_required),
    ) -> HomeRender:
        if database_setup_required:
            return HomeRender(
                database_setup_required=database_setup_required,
                metadata=Metadata(title="Database Setup Required"),
            )

        items = await session.exec(select(models.DetailItem))
        return HomeRender(
            items=items,
            metadata=Metadata(title="Home"),
        )

    @sideeffect
    async def new_detail(
        self,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> None:
        obj = models.DetailItem(description="Untitled Item")
        await session.insert([obj])
{% endif %}
