from typing import Type

from pydantic import model_validator
from pydantic_settings import BaseSettings

from filzl_auth.models import UserAuthMixin


class AuthConfig(BaseSettings):
    API_SECRET_KEY: str
    API_KEY_ALGORITHM: str = "HS256"

    RECAPTCHA_ENABLED: bool = False

    # base64 encoded service-account access key
    RECAPTCHA_GCP_SERVICE: str | None = None
    # Project ID that hosts your ReCapcha, includes the GCP service account definition
    RECAPTCHA_GCP_PROJECT_ID: str | None = None
    # Client-side key for browser embedding, tied to your GCP ReCapcha instance
    RECAPTCHA_GCP_CLIENT_KEY: str | None = None

    AUTH_USER: Type[UserAuthMixin]

    @model_validator(mode="after")
    def validate_recaptcha(self) -> "AuthConfig":
        if not self.RECAPTCHA_ENABLED:
            return self

        # Otherwise ensure the values are provided
        if not self.RECAPTCHA_GCP_SERVICE:
            raise ValueError("RECAPTCHA_GCP_SERVICE is required")
        if not self.RECAPTCHA_GCP_PROJECT_ID:
            raise ValueError("RECAPTCHA_GCP_PROJECT_ID is required")
        if not self.RECAPTCHA_GCP_CLIENT_KEY:
            raise ValueError("RECAPTCHA_GCP_CLIENT_KEY is required")

        return self
