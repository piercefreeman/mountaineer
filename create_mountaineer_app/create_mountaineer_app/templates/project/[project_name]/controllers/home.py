from uuid import UUID, uuid4

from fastapi import Request
from mountaineer.actions import passthrough, sideeffect
from mountaineer.controller import ControllerBase
from mountaineer.render import Metadata, RenderBase
from pydantic import BaseModel


class HomeRender(RenderBase):
    current_count: int


class IncrementCountRequest(BaseModel):
    count: int


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

    def __init__(self):
        super().__init__()
        self.global_count = 0

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest):
        self.global_count += payload.count

    def render(self) -> HomeRender:
        return HomeRender(
            current_count=self.global_count,
            metadata=Metadata(title="Home"),
        )
