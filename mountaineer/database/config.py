from enum import Enum
from typing import Any

from pydantic import PostgresDsn, model_validator
from pydantic_core import PydanticUndefinedType
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
        # Support users specifying some defaults via the pydantic
        # model directly
        cls_defaults = {
            field_name: field.default
            for field_name, field in cls.model_fields.items()
            if field.default and not isinstance(field.default, PydanticUndefinedType)
        }

        all_values = {**cls_defaults, **values}

        if not values.get("SQLALCHEMY_DATABASE_URI"):
            values["SQLALCHEMY_DATABASE_URI"] = PostgresDsn.build(  # type: ignore
                scheme="postgresql+asyncpg",
                username=all_values["POSTGRES_USER"],
                password=all_values["POSTGRES_PASSWORD"],
                host=all_values["POSTGRES_HOST"],
                port=int(all_values.get("POSTGRES_PORT", 5432)),
                path=all_values["POSTGRES_DB"],
            )

        return values
