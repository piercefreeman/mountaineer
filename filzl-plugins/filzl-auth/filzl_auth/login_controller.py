from datetime import datetime, timedelta
from typing import Type
from uuid import UUID, uuid4

from fastapi import Depends, Request, status
from fastapi.responses import JSONResponse
from filzl.actions import passthrough
from filzl.controller import ControllerBase
from filzl.database.dependencies import DatabaseDependencies
from filzl.dependencies import CoreDependencies, get_function_dependencies
from filzl.exceptions import APIException
from filzl.paths import ManagedViewPath
from filzl.render import Metadata, RedirectStatus, RenderBase
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from filzl_auth.config import AuthConfig
from filzl_auth.dependencies import AuthDependencies
from filzl_auth.user_model import User
from filzl_auth.views import get_auth_view_path


class LoginRequest(BaseModel):
    username: EmailStr
    password: str


class LoginInvalid(APIException):
    status_code = 401
    invalid_reason: str


class LoginController(ControllerBase):
    """
    Clients can override this login controller to instantiate their own login / view conventions.
    """

    url = "/auth/login"
    view_path = (
        ManagedViewPath.from_view_root(get_auth_view_path(""), package_root_link=None)
        / "auth/login/page.tsx"
    )

    # Defaults to 24 hours
    token_expiration_minutes: int = 60 * 24

    def __init__(
        self,
        post_login_redirect: str,
        user_model: Type[User] = User,
    ):
        super().__init__()
        self.user_model = user_model
        self.post_login_redirect = post_login_redirect

    async def render(
        self,
        request: Request,
    ) -> RenderBase:
        # Workaround to provide user-defined models into the dependency layer
        get_dependencies_fn = AuthDependencies.peek_user(self.user_model)
        async with get_function_dependencies(
            callable=get_dependencies_fn, url=self.url, request=request
        ) as values:
            user = get_dependencies_fn(**values)

        if user is not None:
            # return RedirectResponse(url=self.post_login_redirect, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
            return RenderBase(
                metadata=Metadata(
                    redirect=RedirectStatus(
                        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                        url=self.post_login_redirect,
                    )
                )
            )

        # Otherwise continue to load the initial page
        return RenderBase()

    @passthrough(exception_models=[LoginInvalid])
    def login(
        self,
        login_payload: LoginRequest,
        auth_config: AuthConfig = Depends(
            CoreDependencies.get_config_with_type(AuthConfig)
        ),
        session: Session = Depends(DatabaseDependencies.get_db_session),
    ):
        matched_users = select(self.user_model).where(
            self.user_model.email == login_payload.username
        )
        user = session.exec(matched_users).first()
        if user is None:
            raise LoginInvalid(invalid_reason="User not found.")
        if not user.verify_password(login_payload.password):
            raise LoginInvalid(invalid_reason="Invalid password.")

        access_token = self.authorize_user(user.id, auth_config)
        response = JSONResponse(content=None, status_code=status.HTTP_200_OK)

        response.set_cookie(
            key=AuthDependencies.access_token_cookie_key(),
            value=f"Bearer {access_token}",
            httponly=True,
            # secure=True,  # Set to False if you're testing locally without HTTPS
            secure=False,
            samesite="lax",  # Helps with CSRF protection
        )

        return response

    def authorize_user(self, user_id: UUID, auth_config: AuthConfig):
        """
        Generates the user a new temporary API key

        """
        # Randomly seed with a uuid4, then encrypt with our secret key to add
        # more entropy to the tokens and make it harder to brute-force the raw token ID
        raw_token = str(uuid4())
        expire = datetime.utcnow() + timedelta(minutes=self.token_expiration_minutes)
        to_encode = {"sub": str(raw_token), "user_id": str(user_id), "exp": expire}
        encoded_token = jwt.encode(
            to_encode,
            auth_config.API_SECRET_KEY,
            algorithm=auth_config.API_KEY_ALGORITHM,
        )

        return encoded_token
