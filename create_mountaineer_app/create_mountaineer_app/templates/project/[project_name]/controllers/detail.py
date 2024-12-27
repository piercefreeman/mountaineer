{% if create_stub_files %}
from uuid import UUID

from mountaineer import Metadata, RenderBase, ControllerBase, APIException, sideeffect
from mountaineer.mountaineer import DatabaseDependencies
from mountaineer import DBConnection

from fastapi import Request, Depends
from fastapi.exceptions import HTTPException
from pydantic import BaseModel

from {{project_name}} import models

class NotFoundException(APIException):
    status_code = 404
    detail = "Detail item not found"


class UpdateTextRequest(BaseModel):
    description: str


class DetailRender(RenderBase):
    id: int
    description: str


class DetailController(ControllerBase):
    url = "/detail/{detail_id}/"
    view_path = "/app/detail/page.tsx"

    def __init__(self):
        super().__init__()

    async def render(
        self,
        detail_id: int,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> DetailRender:
        detail_item = await session.get(models.DetailItem, detail_id)
        if not detail_item:
            raise NotFoundException()

        return DetailRender(
            id=detail_item.id,
            description=detail_item.description,
            metadata=Metadata(title=f"Detail: {detail_id}"),
        )

    @sideeffect
    async def update_text(
        self,
        detail_id: int,
        payload: UpdateTextRequest,
        session: DBConnection = Depends(DatabaseDependencies.get_db_connection)
    ) -> None:
        detail_item = await session.get(models.DetailItem, detail_id)
        if not detail_item:
            raise NotFoundException()

        detail_item.description = payload.description
        await session.update([detail_item])
{% endif %}
