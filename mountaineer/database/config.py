from typing import Any

from pydantic import PostgresDsn, model_validator
from pydantic_settings import BaseSettings


class DatabaseConfig(BaseSettings):
    POSTGRES_HOST: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
    SQLALCHEMY_DATABASE_URI: PostgresDsn | None = None

    @model_validator(mode="before")
    def build_db_connection(cls, values: Any) -> Any:
        if not values.get("SQLALCHEMY_DATABASE_URI"):
            values["SQLALCHEMY_DATABASE_URI"] = PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=values["POSTGRES_USER"],
                password=values["POSTGRES_PASSWORD"],
                host=values["POSTGRES_HOST"],
                port=int(values.get("POSTGRES_PORT", 5432)),
                path=values["POSTGRES_DB"],
            )
        return values
