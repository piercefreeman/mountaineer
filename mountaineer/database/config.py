from enum import Enum
from typing import Any

from pydantic import PostgresDsn, model_validator
from pydantic_settings import BaseSettings


class PoolType(Enum):
    # Default value, no in-memory pooling at the SQLAlchemy layer. This assumes
    # you'll establish a 3rd party connection pool closer to the database
    # layer - or you have low enough traffic that you don't need one at all.
    NULL = "NULL"

    # Fixed quantity for each process spawned
    # This corresponds to the SQLAlchemy `AsyncAdaptedQueuePool`
    FIXED_PROCESS = "FIXED_PROCESS"


class DatabaseConfig(BaseSettings):
    POSTGRES_HOST: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: int = 5432
    SQLALCHEMY_DATABASE_URI: PostgresDsn | None = None

    DATABASE_POOL_TYPE: PoolType = PoolType.NULL

    @model_validator(mode="before")
    def build_db_connection(cls, values: Any) -> Any:
        if not values.get("SQLALCHEMY_DATABASE_URI"):
            values["SQLALCHEMY_DATABASE_URI"] = PostgresDsn.build(  # type: ignore
                scheme="postgresql+asyncpg",
                username=values["POSTGRES_USER"],
                password=values["POSTGRES_PASSWORD"],
                host=values["POSTGRES_HOST"],
                port=int(values.get("POSTGRES_PORT", 5432)),
                path=values["POSTGRES_DB"],
            )
        return values
