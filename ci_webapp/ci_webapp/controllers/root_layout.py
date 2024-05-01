from uuid import UUID

from fastapi import Request
from mountaineer import LayoutControllerBase, Metadata, RenderBase


class RootLayoutRender(RenderBase):
    client_ip: str


class RootLayoutController(LayoutControllerBase):
    view_path = "/app/layout.tsx"

    def __init__(self):
        super().__init__()

    def render(self, detail_id: UUID, request: Request) -> RootLayoutRender:
        return RootLayoutRender(
            client_ip=request.client.host if request.client else "unknown",
            metadata=Metadata(title=f"Detail: {detail_id}"),
        )
