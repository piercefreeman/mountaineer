from filzl.render import RenderBase
from filzl.sideeffects import sideeffect, passthrough
from filzl.controller import BaseController
from my_website.views import get_view_path
from pydantic import BaseModel

class HomeRender(RenderBase):
    first_name: str
    current_count: int

class IncrementCountRequest(BaseModel):
    count: int

class HomeController(BaseController):
    # view_path = "/testing/[post_id]/mytemplate.tsx"
    url = "/"
    view_path = get_view_path("/app/home.tsx")

    def __init__(self):
        self.global_count = 0

    def render(self) -> HomeRender:
        return HomeRender(
            first_name="John",
            current_count=self.global_count,
        )

    @sideeffect
    def increment_count(self, payload: IncrementCountRequest):
        self.global_count += payload.count

    @passthrough
    def get_external_data(self):
        # Execute a server action without automatically reloading the server state
        # Typically side-effects are the recommended way to get static data to the client
        # but sometimes you need to get data from a third-party API or gated resource
        return dict(
            first_name="John",
        )
