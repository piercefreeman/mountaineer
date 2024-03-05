{% if create_stub_files %}
from uuid import UUID, uuid4

from mountaineer import sideeffect, ControllerBase, Metadata, RenderBase
from mountaineer.database import DatabaseDependencies

from fastapi import Request, Depends
from pydantic import BaseModel
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        items = await session.execute(select(models.DetailItem))
        return HomeRender(
            items=items.scalars().all(),
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