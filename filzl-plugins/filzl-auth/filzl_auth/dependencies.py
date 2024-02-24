from fastapi import Depends, Request
from filzl.database.dependencies import DatabaseDependencies
from filzl.dependencies import CoreDependencies
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from filzl_auth.config import AuthConfig
from filzl_auth.exceptions import UnauthorizedError
from filzl_auth.models import UserAuthMixin


class AuthDependencies:
    @staticmethod
    async def peek_user(
        request: Request,
        auth_config: AuthConfig = Depends(
            CoreDependencies.get_config_with_type(AuthConfig)
        ),
        db: AsyncSession = Depends(DatabaseDependencies.get_db_session),
    ) -> UserAuthMixin | None:
        """
        Peek the user from the request, if it exists
        """
        try:
            token = request.cookies.get(AuthDependencies.access_token_cookie_key())
            if not token:
                return None

            token = token.lstrip("Bearer").strip()
            payload = jwt.decode(
                token,
                auth_config.API_SECRET_KEY,
                algorithms=[auth_config.API_KEY_ALGORITHM],
            )

            user_id = payload.get("user_id")
            if user_id is None:
                return None

            return await db.get(auth_config.AUTH_USER, user_id)
        except ExpiredSignatureError:
            return None
        except JWTError:
            return None

    @staticmethod
    def require_valid_user(
        peeked_user: UserAuthMixin | None = Depends(peek_user),
    ):
        if peeked_user is None:
            raise UnauthorizedError()

        return peeked_user

    @staticmethod
    def require_admin(
        user: UserAuthMixin = Depends(require_valid_user),
    ):
        if not user.is_admin:
            raise UnauthorizedError()

        return user

    @staticmethod
    def access_token_cookie_key():
        return "access_key"
