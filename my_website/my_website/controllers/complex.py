from uuid import UUID, uuid4

from fastapi import Request
from filzl.controller import ControllerBase
from filzl.render import Metadata, RenderBase

from my_website.views import get_view_path


class ComplexRender(RenderBase):
    client_ip: str
    random_uuid: UUID


class ComplexController(ControllerBase):
    url = "/complex/{detail_id}/"
    view_path = get_view_path("/app/complex/page.tsx")

    def __init__(self):
        super().__init__()

    def render(self, detail_id: UUID, request: Request) -> ComplexRender:
        return ComplexRender(
            client_ip=request.client.host if request.client else "unknown",
            random_uuid=uuid4(),
            metadata=Metadata(title=f"Complex: {detail_id}"),
        )
