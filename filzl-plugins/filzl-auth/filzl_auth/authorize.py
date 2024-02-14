from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi.responses import Response
from jose import jwt

from filzl_auth.config import AuthConfig
from filzl_auth.dependencies import AuthDependencies


def authorize_response(
    response: Response,
    *,
    user_id: UUID,
    auth_config: AuthConfig,
    token_expiration_minutes: int,
):
    """
    Adds a cookie to the passed response that authorizes the given
    user via a session cookie.
    """
    access_token = authorize_user(
        user_id=user_id,
        auth_config=auth_config,
        token_expiration_minutes=token_expiration_minutes,
    )

    response.set_cookie(
        key=AuthDependencies.access_token_cookie_key(),
        value=f"Bearer {access_token}",
        httponly=True,
        # secure=True,  # Set to False if you're testing locally without HTTPS
        secure=False,
        samesite="lax",  # Helps with CSRF protection
    )
    return response


def authorize_user(
    *,
    user_id: UUID,
    auth_config: AuthConfig,
    token_expiration_minutes: int,
):
    """
    Generates the user a new temporary API key

    """
    # Randomly seed with a uuid4, then encrypt with our secret key to add
    # more entropy to the tokens and make it harder to brute-force the raw token ID
    raw_token = str(uuid4())
    expire = datetime.utcnow() + timedelta(minutes=token_expiration_minutes)
    to_encode = {"sub": str(raw_token), "user_id": str(user_id), "exp": expire}
    encoded_token = jwt.encode(
        to_encode,
        auth_config.API_SECRET_KEY,
        algorithm=auth_config.API_KEY_ALGORITHM,
    )

    return encoded_token
