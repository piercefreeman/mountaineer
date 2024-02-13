import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel

from filzl_daemons.__tests__.conf_models import (
    LOCAL_MODEL_DEFINITION,
)
from filzl_daemons.db import PostgresBackend
from filzl_daemons.workflow import DaemonClient


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    test_database_url = "postgresql+asyncpg://filzl_daemons:mysecretpassword@localhost:5434/filzl_daemons_test_db"
    engine = create_async_engine(test_database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture
def postgres_backend(db_engine: AsyncEngine):
    return PostgresBackend(
        engine=db_engine,
        local_models=LOCAL_MODEL_DEFINITION,
    )


@pytest.fixture
def daemon_client(postgres_backend: PostgresBackend):
    return DaemonClient(
        backend=postgres_backend,
    )
