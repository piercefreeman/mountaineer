from typing import Type, TypeVar

from fastapi import Depends, Request
from filzl.database.dependencies import DatabaseDependencies
from filzl.dependencies import CoreDependencies
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from filzl_auth.config import AuthConfig
from filzl_auth.exceptions import UnauthorizedError
from filzl_auth.models import UserAuthMixin

T = TypeVar("T", bound=UserAuthMixin)


class AuthDependencies:
    @staticmethod
    def peek_user(user_model: Type[T]):
        async def internal(
            request: Request,
            auth_config: AuthConfig = Depends(
                CoreDependencies.get_config_with_type(AuthConfig)
            ),
            db: AsyncSession = Depends(DatabaseDependencies.get_db_session),
        ) -> T | None:
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

                return await db.get(user_model, user_id)
            except ExpiredSignatureError:
                return None
            except JWTError:
                return None

        return internal

    @staticmethod
    def require_valid_user(
        user_model: Type[T],
    ):
        def internal(
            peeked_user: T | None = Depends(AuthDependencies.peek_user(user_model)),
        ) -> T:
            if peeked_user is None:
                raise UnauthorizedError()

            return peeked_user

        return internal

    @staticmethod
    def require_admin(
        user_model: Type[T],
    ):
        def internal(
            user: T = Depends(AuthDependencies.require_valid_user(user_model)),
        ) -> T:
            if not user.is_admin:
                raise UnauthorizedError()

            return user

        return internal

    @staticmethod
    def access_token_cookie_key():
        return "access_key"
