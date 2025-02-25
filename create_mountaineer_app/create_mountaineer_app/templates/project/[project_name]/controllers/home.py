{% if create_stub_files %}
from mountaineer import sideeffect, ControllerBase, Metadata, RenderBase
from iceaxe.mountaineer import DatabaseDependencies
from iceaxe import DBConnection, select

from fastapi import Depends

from {{project_name}} import models


class HomeRender(RenderBase):
    items: list[models.DetailItem]


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    async def render(
        self,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> HomeRender:
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
