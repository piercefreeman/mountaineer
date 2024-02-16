from fastapi import Request
from filzl.controller import ControllerBase
from filzl.render import RenderBase
from filzl_auth.dependencies import AuthDependencies
from filzl_auth.user_model import User
from filzl.dependencies import get_function_dependencies
from filzl import ManagedViewPath
from filzl_daemons.views import get_daemons_view_path
from filzl_daemons.controllers.base_controller import DaemonControllerBase

class DaemonHomeRender(RenderBase):
    pass

class DaemonHomeController(DaemonControllerBase):
    url = "/admin/daemons"
    view_path = (
        ManagedViewPath.from_view_root(get_daemons_view_path(""), package_root_link=None)
        / "daemons/home/page.tsx"
    )

    async def render(self, request: Request) -> DaemonHomeRender:
        await self.require_admin(request)

        return DaemonHomeRender()
