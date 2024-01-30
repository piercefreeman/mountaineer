from uuid import UUID

from fastapi import Request
from filzl.actions import passthrough, sideeffect
from filzl.controller import ControllerBase
from filzl.render import Metadata, RenderBase
from pydantic import BaseModel

from my_website.views import get_view_path


class DetailRender(RenderBase):
    client_ip: str


class DetailController(ControllerBase):
    url = "/detail/{detail_id}/"
    view_path = get_view_path("/app/home/page.tsx")

    def __init__(self):
        super().__init__()

    def render(self, detail_id: UUID, request: Request) -> DetailRender:
        return DetailRender(
            client_ip=request.client.host if request.client else "unknown",
            metadata=Metadata(title=f"Detail: {detail_id}"),
        )