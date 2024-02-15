from fastapi import Depends, status
from starlette.responses import RedirectResponse
from filzl import (
    ControllerBase,
    ManagedViewPath,
    Metadata,
    RenderBase,
)
from filzl_auth.dependencies import AuthDependencies

from filzl_auth.views import get_auth_view_path


class LogoutController(ControllerBase):
    url = "/auth/logout"
    view_path = (
        ManagedViewPath.from_view_root(get_auth_view_path(""), package_root_link=None)
        / "auth/logout/page.tsx"
    )

    def __init__(self, post_logout_redirect: str):
        super().__init__()
        self.post_logout_redirect = post_logout_redirect

    def render(
        self,
        access_token_cookie_key: str = Depends(AuthDependencies.access_token_cookie_key)
    ) -> RenderBase:
        response = RedirectResponse(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            url=self.post_logout_redirect,
        )

        # Remove the cookies
        response.delete_cookie(access_token_cookie_key)

        return RenderBase(
            metadata=Metadata(
                title="Logout",
                explicit_response=response,
            )
        )
