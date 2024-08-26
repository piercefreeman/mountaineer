{% if create_stub_files %}
from uuid import UUID, uuid4

from mountaineer import sideeffect, ControllerBase, Metadata, RenderBase
from mountaineer.database import DatabaseDependencies
from mountaineer.database.session import AsyncSession

from fastapi import Request, Depends
from pydantic import BaseModel
from sqlmodel import select

from {{project_name}} import models


class HomeRender(RenderBase):
    items: list[models.DetailItem]


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    async def render(
        self,
        session: AsyncSession = Depends(DatabaseDependencies.get_db_session)
    ) -> HomeRender:
        items = (await session.exec(select(models.DetailItem))).all()
        return HomeRender(
            items=items,
            metadata=Metadata(title="Home"),
        )

    @sideeffect
    async def new_detail(
        self,
        session: AsyncSession = Depends(DatabaseDependencies.get_db_session)
    ) -> None:
        obj = models.DetailItem(description="Untitled Item")
        session.add(obj)
        await session.commit()
{% endif %}
