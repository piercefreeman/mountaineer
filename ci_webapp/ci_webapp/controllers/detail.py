from uuid import UUID

from fastapi import Request
from mountaineer import ControllerBase, Metadata, RenderBase


class DetailRender(RenderBase):
    client_ip: str


class DetailController(ControllerBase):
    url = "/detail/{detail_id}/"
    view_path = "/app/detail/page.tsx"

    def __init__(self):
        super().__init__()

    def render(self, detail_id: UUID, request: Request) -> DetailRender:
        return DetailRender(
            client_ip=request.client.host if request.client else "unknown",
            metadata=Metadata(title=f"Detail: {detail_id}"),
        )
