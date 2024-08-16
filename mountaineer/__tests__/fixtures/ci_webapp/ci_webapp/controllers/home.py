from uuid import UUID, uuid4

from fastapi import Request
from mountaineer import ControllerBase, Metadata, RenderBase, passthrough, sideeffect
from pydantic import BaseModel


class HomeRender(RenderBase):
    client_ip: str
    current_count: int
    random_uuid: UUID


class IncrementCountRequest(BaseModel):
    count: int


class GetExternalDataResponse(BaseModel):
    first_name: str


class HomeController(ControllerBase):
    url = "/"
    view_path = "/app/home/page.tsx"

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
    def get_external_data(self) -> GetExternalDataResponse:
        # Execute a server action without automatically reloading the server state
        # Typically side-effects are the recommended way to get static data to the client
        # but sometimes you need to get data from a third-party API or gated resource
        return GetExternalDataResponse(
            first_name="John",
        )

    def render(self, request: Request) -> HomeRender:
        return HomeRender(
            client_ip=request.client.host if request.client else "unknown",
            current_count=self.global_count,
            # Bust the server-side cache
            random_uuid=uuid4(),
            metadata=Metadata(title="Home"),
        )
