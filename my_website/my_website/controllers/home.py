from uuid import UUID

from fastapi import Request

from filzl.actions import passthrough, sideeffect
from filzl.controller import ControllerBase
from filzl.render import RenderBase
from pydantic import BaseModel

from my_website.views import get_view_path


class HomeRender(RenderBase):
    client_ip: str
    current_count: int


class IncrementCountRequest(BaseModel):
    count: int


class GetExternalDataResponse(BaseModel):
    first_name: str


class HomeController(ControllerBase):
    # view_path = "/testing/[post_id]/mytemplate.tsx"
    url = "/home/{home_id}/"
    view_path = get_view_path("/app/home/page.tsx")

    def __init__(self):
        super().__init__()
        self.global_count = 0

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest):
        self.global_count += payload.count

    @sideeffect(reload=(HomeRender.current_count,))
    def increment_count_only(self, payload: IncrementCountRequest, url_param: int):
        self.global_count += payload.count

    @passthrough(response_model=GetExternalDataResponse)
    def get_external_data(self):
        # Execute a server action without automatically reloading the server state
        # Typically side-effects are the recommended way to get static data to the client
        # but sometimes you need to get data from a third-party API or gated resource
        return dict(
            first_name="John",
        )

    def render(self, home_id: UUID, request: Request) -> HomeRender:
        return HomeRender(
            client_ip=request.client.host if request.client else "unknown",
            current_count=self.global_count,
        )